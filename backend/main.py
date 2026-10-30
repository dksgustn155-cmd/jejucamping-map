"""
차박/캠핑 편의시설 지도 — FastAPI 백엔드 (뼈대)

엔드포인트:
  GET /api/health                    상태 확인
  GET /api/facilities?bbox=...        지도 화면 영역(bbox) 내 시설 (모드2 지도용, SQLite)
  GET /api/beach-timing?...           해수욕장 방문 타이밍 (Day4 구현)
  POST /api/chat                      대화형 추천 (Day4 구현)
  GET /config.js                      프론트에 카카오 JS 키 주입

실행(개발): uvicorn backend.main:app --reload --port 8000
"""
import os
import json
import time
import sqlite3
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
FRONTEND_DIR = ROOT / "frontend"


# ── .env 로드 ─────────────────────────────────────────────────────────
def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip())


load_env()
KAKAO_JS_KEY = os.environ.get("KAKAO_JS_KEY", "")
JEJU_ITS_CODE = os.environ.get("JEJU_ITS_CODE", "")

app = FastAPI(title="캠핑 편의시설 지도 API")

# 전기차 실시간 가용 캐시 (Tier 3: 저장 안 하고 짧은 캐시로 API 폭주 방지, docs/data-management.md)
_EV_CACHE = {"t": 0.0, "data": {}}
_EV_TTL = 180  # 3분


def get_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(500, "facilities.db 없음 — data_pipeline/build_db.py 먼저 실행")
    # timeout: 지오코딩 배치가 쓰기 커밋 중일 때 잠깐 기다렸다 읽음 (database is locked 방지)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    return con


@app.get("/api/health")
def health():
    info = {"status": "ok", "db": DB_PATH.exists()}
    if DB_PATH.exists():
        con = get_db()
        try:
            info["counts"] = {
                row["category"]: row["n"]
                for row in con.execute("SELECT category, COUNT(*) n FROM facilities GROUP BY category")
            }
            info["with_coord"] = con.execute(
                "SELECT COUNT(*) FROM facilities WHERE lat IS NOT NULL"
            ).fetchone()[0]
        finally:
            con.close()  # 예외가 나도 커넥션 누수 방지
    return info


@app.get("/api/facilities")
def facilities(
    sw_lat: float = Query(..., description="남서 위도"),
    sw_lng: float = Query(..., description="남서 경도"),
    ne_lat: float = Query(..., description="북동 위도"),
    ne_lng: float = Query(..., description="북동 경도"),
    category: str | None = Query(None, description="restroom/camping/beach/parking (콤마 다중)"),
    limit: int = Query(500, le=2000),
):
    """지도 화면 영역(bounding box) 안의 시설을 반환 (모드2)."""
    con = get_db()
    try:
        sql = [
            "SELECT id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra",
            "FROM facilities",
            "WHERE lat IS NOT NULL AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        ]
        params = [sw_lat, ne_lat, sw_lng, ne_lng]
        if category:
            cats = [c.strip() for c in category.split(",") if c.strip()]
            sql.append("AND category IN (%s)" % ",".join("?" * len(cats)))
            params += cats
        # 민가 많은 주차장은 지도에서 제외 (배치로 사전계산한 extra.houses > 150 배제, 미상은 유지)
        sql.append("AND NOT (category IN ('parking_public','parking') "
                   "AND COALESCE(CAST(json_extract(extra,'$.houses') AS INTEGER), 0) > 150)")
        sql.append("LIMIT ?")
        params.append(limit)

        rows = con.execute(" ".join(sql), params).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        d = dict(r)
        d["extra"] = json.loads(d["extra"]) if d["extra"] else {}
        out.append(d)
    return {"count": len(out), "items": out}


def _ev_status_now() -> dict:
    """EV 실시간 가용 (3분 캐시) — /api/ev-status 와 /api/recommend 가 공용. 실패 시 {}"""
    now = time.time()
    if _EV_CACHE["data"] and now - _EV_CACHE["t"] < _EV_TTL:
        return _EV_CACHE["data"]
    if not JEJU_ITS_CODE:
        return {}
    url = f"http://api.jejuits.go.kr/api/infoEvList?code={JEJU_ITS_CODE}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.load(r)
    except Exception:  # noqa: BLE001 — 외부 API 장애 시 빈 값 (추천은 보너스만 생략됨)
        return {}
    status = {
        it["id"]: {"fast": it.get("fast", 0), "slow": it.get("slow", 0)}
        for it in data.get("info", []) if it.get("id")
    }
    _EV_CACHE["t"], _EV_CACHE["data"] = now, status
    return status


@app.get("/api/ev-status")
def ev_status():
    """제주 전기차 충전소 실시간 급속/완속 가용 대수 (ITS infoEvList). 3분 캐시.
    반환: {"cached": bool, "status": {충전소id: {"fast": n, "slow": m}}}"""
    cached_before = bool(_EV_CACHE["data"]) and time.time() - _EV_CACHE["t"] < _EV_TTL
    status = _ev_status_now()
    if not status and not JEJU_ITS_CODE:
        raise HTTPException(500, ".env 에 JEJU_ITS_CODE 없음")
    if not status:
        raise HTTPException(502, "ITS 실시간 API 오류")
    return {"cached": cached_before, "status": status}


# ── 규제 구역 판정 (GIS point-in-polygon) ─────────────────────────────
# 자연공원 경계: 국립(공공데이터포털) + 도립·군립(브이월드 WFS) — 자연공원법 동일 적용
def _load_zones():
    zones = []  # (이름, 종류, [폴리곤(=링 리스트)들])
    for path, default_kind in [(ROOT / "data" / "gis" / "national_parks.geojson", "국립공원"),
                               (ROOT / "data" / "gis" / "natural_parks_vworld.geojson", None)]:
        if not path.exists():
            continue
        for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
            g = f["geometry"]
            polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            kind = f["properties"].get("kind") or default_kind
            zones.append((f["properties"]["name"], kind, polys))
    return zones


_ZONES = _load_zones()


def _in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_polys(lon, lat, polys):
    for rings in polys:
        if _in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, h) for h in rings[1:]):
            return True
    return False


def _zone_of(lat: float, lon: float):
    """좌표의 자연공원 판정 — /api/zone-check 와 /api/recommend(V11) 공용."""
    for name, kind, polys in _ZONES:
        if _in_polys(lon, lat, polys):
            return (name, kind)
    return None


@app.get("/api/zone-check")
def zone_check(lat: float = Query(...), lon: float = Query(...)):
    """이 좌표가 자연공원(국립·도립·군립) 안인지 판정 → 챗봇이 규정 인용에 사용.
    반환 예: {"zone": "한라산", "kind": "국립공원", "rules": ["자연공원법 제27조 …"]}"""
    for name, kind, polys in _ZONES:
        if _in_polys(lon, lat, polys):
            return {"zone": name, "kind": kind,
                    "rules": [f"{name} {kind} 구역 — 자연공원법 제27조: 지정장소 외 야영·취사·주차 금지 "
                              "(과태료: 야영 50만·취사 20만원 이하, 제86조)"]}
    return {"zone": None, "kind": None, "rules": []}


@app.get("/api/beach-timing")
def beach_timing(beach: str = Query(...)):
    """해수욕장 방문 타이밍 (만조/파고/수온) — Day4 구현 예정."""
    raise HTTPException(501, "Day4 구현 예정")


# ── POST /api/recommend — 차박 적합도 추천 (A 임시 통합, C #13 인수용) ──────
# 점수화 V1~V12 는 backend/recommend.py — 자연공원·EV 캐시를 여기서 주입 (순환 import 방지)
try:
    from backend import recommend as _recommend
    _recommend.configure(zone_lookup=_zone_of, ev_status_getter=_ev_status_now)
    app.include_router(_recommend.router)
except Exception as _re:  # noqa: BLE001 — rag 의존성 없는 환경에서도 서버는 뜸 (프론트 폴백)
    print(f"[recommend] 비활성: {_re}")


# ── POST /api/chat — 멀티턴 대화 (A 임시 통합 어댑터, 7/9) ─────────────────
# ⚠️ C 인수용: backend/chat.py 통합 시 이 계약(docs/api-chat-contract.md §1·§4)을 유지해 주세요.
#    B의 rag 파이프라인(detect_region + RAG검색 + gpt-5-mini)을 계약 형식으로 감싼 얇은 층입니다.
#    rag 의존성(faiss·sentence-transformers)이 없으면 503 → 프론트가 규칙 스텁으로 폴백합니다.
os.environ.setdefault("OPENAI_API_KEY", os.environ.get("GPT_MINI_API_KEY", ""))
try:
    from rag.query_classifier import detect_region          # B: 지역 인식
    from rag.gpt_answer import generate_answer              # B: RAG 근거 + gpt-5-mini 답변
    _RAG_READY, _RAG_ERR = True, ""
except Exception as _e:  # noqa: BLE001 — 의존성 미설치 환경(팀원 로컬 등)에서도 서버는 떠야 함
    _RAG_READY, _RAG_ERR = False, str(_e)

from pydantic import BaseModel


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []
    categories: list[str] = []


_QUICK_REGIONS = ["서귀포", "애월", "협재", "성산", "함덕", "담양"]


def _chat_slots(text: str, region: str | None) -> dict:
    """대화 전체 텍스트에서 조건 슬롯 추출 (B의 GPT 파싱 도입 전 규칙 기반)."""
    return {
        "region": region,
        "ev": any(k in text for k in ("전기차", "충전", "EV", "ev")),
        "view": "바다" if any(k in text for k in ("바다", "해변", "해수욕")) else
                ("숲·계곡" if any(k in text for k in ("숲", "계곡", "호수")) else None),
        "pharmacy": "약국" in text,
    }


@app.post("/api/chat")
def chat(req: ChatIn):
    """계약 §4: next(ask/confirm)로 프론트 렌더 결정. 대화 정책(임시): 지역만 필수."""
    if not _RAG_READY:
        raise HTTPException(503, f"rag 미준비(의존성 설치 필요): {_RAG_ERR}")
    user_text = " ".join(
        [m.get("content", "") for m in req.history if m.get("role") == "user"] + [req.message])
    region = detect_region(user_text)
    asked = any(m.get("role") == "assistant" and "어느 지역" in m.get("content", "")
                for m in req.history)
    if not region and not asked:
        return {
            "reply": "좋아요! 어느 지역으로 떠나실 계획이세요? 🗺️ (아래에서 고르거나 직접 입력해 주세요)",
            "next": "ask",
            "quick_replies": _QUICK_REGIONS,
            "slots": _chat_slots(user_text, None),
        }
    slots = _chat_slots(user_text, region or "제주")
    # B 파이프라인: 좌표 해석 → 주변시설 근거 → gpt-5-mini 답변 (환각 방지 프롬프트)
    try:
        result = generate_answer(user_text)
        reply = (result.get("answer") or "").strip() or "조건을 정리했어요. 이대로 진행할까요?"
    except Exception as e:  # noqa: BLE001 — GPT 장애 시에도 confirm 플로우는 유지
        reply = f"조건을 정리했어요. 이대로 주변 편의시설을 확인해 볼까요? (AI 답변 지연: {type(e).__name__})"
    parts = [f"📍 {slots['region']}"]
    if slots["ev"]:
        parts.append("⚡ 전기차")
    if slots["view"]:
        parts.append("🌊 바다 뷰" if slots["view"] == "바다" else "🌲 숲·계곡")
    if slots["pharmacy"]:
        parts.append("💊 심야약국")
    return {"reply": reply, "next": "confirm", "slots": slots, "summary": " · ".join(parts)}


@app.get("/config.js")
def config_js():
    """프론트가 카카오 JS 키를 받아가는 엔드포인트 (키를 HTML에 하드코딩하지 않기 위함)."""
    body = f"window.APP_CONFIG = {{ KAKAO_JS_KEY: '{KAKAO_JS_KEY}' }};"
    return Response(content=body, media_type="application/javascript")


# ── 프론트 정적 파일 서빙 (frontend/ 가 있으면) ──────────────────────────
if FRONTEND_DIR.exists():
    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/sw.js")
    def sw_js():
        """PWA 서비스워커 — 루트 경로에서 서빙해야 scope가 '/' 전체가 됨."""
        return FileResponse(FRONTEND_DIR / "sw.js", media_type="application/javascript")

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
