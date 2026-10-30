"""차박 적합도 추천 API — POST /api/recommend

⚠️ A 임시 통합(7/9) — C(#13) 인수용. 규칙·가중치는 docs/scoring-design.md V1~V12,
   응답 형식은 docs/api-chat-contract.md §1. 프론트 scoring.js가 동일 로직의 참조 구현(폴백).

백엔드 기존 자산 재사용:
  - 시설 조회: data/facilities.db (main의 /api/facilities와 동일 스키마)
  - V11 자연공원: main.py의 _ZONES/_in_polys 를 configure()로 주입받아 함수 직접 호출 (전 후보 판정)
  - V5 EV 실시간: main.py의 ITS 캐시 getter 주입
  - 거리: rag/nearby.py 의 haversine_km (B)
  - reply: gpt-5-mini — 점수·근거만 인용해 생성 (recommendation-pipeline.md §7), 실패 시 템플릿
가중치: data/score_weights.json 로드 (없으면 내장 기본값) — 주간 배치가 갱신하는 인터페이스(§5)
"""
import json
import math
import os
import re
import sqlite3
import time
import urllib.request
from bisect import bisect_left
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from rag.nearby import haversine_km  # B 파이프라인 재사용

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "facilities.db"
WEIGHTS_PATH = ROOT / "data" / "score_weights.json"

router = APIRouter()

# main.py가 기동 시 주입 (순환 import 방지)
_zone_lookup = lambda lat, lon: None          # → (이름, 종류) | None
_ev_status = lambda: {}                        # → {충전소id: {fast, slow}}


def configure(zone_lookup, ev_status_getter):
    global _zone_lookup, _ev_status
    _zone_lookup = zone_lookup
    _ev_status = ev_status_getter


# ── 가중치 (scoring-design.md §4 — score_weights.json 이 있으면 그 값 사용) ──
DEFAULT_WEIGHTS = {
    "base": 15,
    # 우선순위: 한적함(_seclusion, 1순위) > 풍경(sea/nature_view, 2순위) > 화장실(3순위)
    "restroom": {"d150": 12, "d300": 8, "d500": 4},   # 3순위 (하향)
    "restroom_24h": 3,
    "sea_view": {"d500": 24, "d1000": 17},            # 2순위 풍경 (상향)
    "nature_view": 22,                                 # 2순위 풍경
    "ev": {"d1000": 12, "fast_bonus": 5},
    "flood": {"grade1": -20, "grade2": -10},
    "cctv_500": 3,
    "pharmacy_3000": 3,
    "cleanhouse_500": 2,
    "festival_active_1000": -8,
    "natural_park": -50,
    "structure_roadside": -15,
}


def load_weights() -> dict:
    if WEIGHTS_PATH.exists():
        try:
            return {**DEFAULT_WEIGHTS, **json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001 — 파일 깨져도 기본값으로 동작
            pass
    return DEFAULT_WEIGHTS


# 민가 많은 주차장 배제 임계값 — 주변 건물 이 수 초과면 지도·추천·조회에서 제외 (배치 사전계산 houses)
PARKING_HOUSE_MAX = 150

# 명백한 부적합 구역 — 추천 후보에서 제외 (min_lat, min_lon, max_lat, max_lon)
# 좌표만으론 GPT가 못 잡는 공항부지 등을 결정적으로 차단 (GPT verify 는 그 외 케이스 백스톱).
EXCLUDE_ZONES = [
    (33.495, 126.466, 33.517, 126.512),   # 제주국제공항 부지 + 도두동 남측 공항인접 산업지(화물·렌터카)
    (33.450, 126.595, 33.472, 126.625),   # 라켄CC(봉개동) 골프장 부지 — 골프장 내 잡종지 오검출 제외
]


def _in_exclude_zone(lat, lon):
    return any(a <= lat <= c and b <= lon <= d for (a, b, c, d) in EXCLUDE_ZONES)

# ── 이용자 피드백(👍👎) 집계 — data/feedback.jsonl (60초 캐시) ──
_FB_CACHE = {"t": 0.0, "data": {}}


def feedback_counts():
    """spot_id별 {up, down} 집계."""
    now = time.time()
    if now - _FB_CACHE["t"] < 60 and _FB_CACHE["data"]:
        return _FB_CACHE["data"]
    path = ROOT / "data" / "feedback.jsonl"
    latest = {}  # (spot_id, user_id) -> 최신 투표 — 한 사람이 여러 번 눌러도 마지막 것만 반영
    if path.exists():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            sid = r.get("spot_id")
            if sid is None or sid == "":
                continue
            uid = r.get("user_id") or f"_anon{i}"   # 옛 익명 표는 각각 1표로 유지
            key = (str(sid), uid)
            v = r.get("vote")
            if v in ("up", "down"):
                latest[key] = v
            else:                                    # "none"/취소 → 표 제거
                latest.pop(key, None)
    counts = {}
    for (sid, _uid), v in latest.items():
        counts.setdefault(sid, {"up": 0, "down": 0})[v] += 1
    _FB_CACHE["t"], _FB_CACHE["data"] = now, counts
    return counts


# ── 지역·조건 (프론트 parseConds와 동일 규칙 — B의 GPT 파싱 도입 시 대체) ──
REGIONS = {
    "서귀포": [33.21, 126.42, 33.32, 126.62],
    "중문":   [33.23, 126.38, 33.28, 126.46],
    "성산":   [33.40, 126.86, 33.50, 126.95],
    "애월":   [33.40, 126.22, 33.50, 126.42],
    "협재":   [33.37, 126.20, 33.42, 126.30],
    "함덕":   [33.52, 126.64, 33.57, 126.72],
    "제주":   [33.40, 126.35, 33.58, 126.70],
    "담양":   [35.25, 126.88, 35.45, 127.12],
}


def parse_conds(text: str, cats: list[str]) -> dict:
    region = next((k for k in REGIONS if k in text), None)
    return {
        "region": region or "서귀포",
        "regionMatched": region is not None,
        "ev": "ev_charger" in cats or bool(re.search(r"전기차|충전|[eE][vV]", text)),
        "seaView": "beach" in cats or bool(re.search(r"바다|해변|해수욕", text)),
        "natureView": bool(re.search(r"숲|계곡|호수", text)),
        "pharmacyNeed": "pharmacy" in cats or "약국" in text,
        "quiet": bool(re.search(r"조용|한적|민가|호젓|한산|사람\s*없|노지", text)),
    }


# ── 시설 조회 ──
def _fetch(con, bbox, cat, limit):
    sa, so, na, no = bbox
    rows = con.execute(
        "SELECT id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra "
        "FROM facilities WHERE lat IS NOT NULL AND category=? "
        "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? LIMIT ?",
        (cat, sa, na, so, no, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["extra"] = json.loads(d["extra"]) if d["extra"] else {}
        out.append(d)
    return out


# ── 최근접 탐색: 위도 정렬 + 이분탐색 윈도우 (900후보 × 수천시설도 <0.5s) ──
def _index(items):
    s = sorted(items, key=lambda x: x["lat"])
    return s, [x["lat"] for x in s]


def _nearest(cand, idx, radius_m):
    items, lats = idx
    if not items:
        return None
    dlat = radius_m / 111_000 * 1.2  # 여유 창
    lo = bisect_left(lats, cand["lat"] - dlat)
    hi = bisect_left(lats, cand["lat"] + dlat)
    best, bd = None, float("inf")
    for it in items[lo:hi]:
        d = haversine_km(cand["lat"], cand["lon"], it["lat"], it["lon"]) * 1000
        if d < bd:
            best, bd = it, d
    return (best, bd) if best and bd <= radius_m else None


def _fmt(m):  # 거리 표기 — 프론트와 동일
    return f"{round(m)}m" if m < 1000 else f"{m / 1000:.1f}km"


def _ref(hit):
    it, d = hit
    return {"id": it["id"], "category": it["category"], "name": it["name"],
            "lat": it["lat"], "lon": it["lon"], "d": round(d), "item": it}


# ── V12 구조 판정 ──
_STRUCT_RE = re.compile(r"빌딩|타워|기계식|지하|옥내|옥상")


def _struct_impossible(c):
    return c["category"] == "parking_public" and (
        _STRUCT_RE.search(c["name"] or "") or _STRUCT_RE.search(c["extra"].get("type") or ""))


# ── 후보 1건 채점 (V1~V10, V12) — 프론트 scoring.js와 동일 규칙 ──
def _score(cand, refs, conds, W):
    why, score = [], W["base"]

    def add(check, ok, detail, delta, ref=None):
        nonlocal score
        score += delta
        row = {"check": check, "pass": ok, "detail": detail, "delta": delta}
        if ref:
            row["ref"] = ref
        why.append(row)

    r = _nearest(cand, refs["restroom"], 500)
    rd = r[1] if r else 99999
    if "restroom" in (conds.get("priorities") or []):  # '화장실'을 추가 고려로 선택했을 때만 점수 반영
        if r:
            d = r[1]
            w = W["restroom"]["d150"] if d <= 150 else W["restroom"]["d300"] if d <= 300 else W["restroom"]["d500"]
            add("restroom", True, f"화장실 {_fmt(d)} ({r[0]['name']})", w, _ref(r))
            if re.search(r"24시간|상시|연중", r[0].get("open_hours") or ""):
                add("restroom_24h", True, "24시간 개방", W["restroom_24h"])
        else:
            add("restroom", False, "화장실 500m 내 없음", 0)

    # 풍경 — 선택한 종류(바다/산/숲/계곡)만 평가 (지정 없으면 전체)
    vts = conds.get("view_types") or []
    want_sea = (not vts) or ("바다" in vts)
    nature_kinds = [x for x in vts if x in ("산", "숲", "계곡")]
    want_nature = (not vts) or bool(nature_kinds)
    b = _nearest(cand, refs["beach"], 1500) if want_sea else None
    loc = (cand["extra"].get("loc_type") or "") if cand["category"] == "camping" else ""
    if b:
        add("sea_view", True, f"바다뷰 — 해수욕장 {_fmt(b[1])} ({b[0]['name']})",
            W["sea_view"]["d500"] if b[1] <= 500 else W["sea_view"]["d1000"], _ref(b))
    elif want_nature and re.search("|".join(nature_kinds) or r"산|숲|계곡|호수|호반", loc):
        add("nature_view", True, f"자연 풍경 입지: {loc}", W["nature_view"])

    if conds["ev"]:
        e = _nearest(cand, refs["ev"], 1000)
        if e:
            add("ev", True, f"EV충전소 {_fmt(e[1])} ({e[0]['name']})", W["ev"]["d1000"], _ref(e))
            live = refs["ev_live"].get(str(e[0]["id"]).replace("ev:", ""))
            if live and live.get("fast", 0) > 0:
                add("ev_fast", True, f"지금 급속 {live['fast']}대 가능", W["ev"]["fast_bonus"])
        else:
            add("ev", False, "EV충전소 1km 내 없음", 0)

    if cand["category"] == "parking_public":  # V12 노상 감점 / 노외 통과 표기
        t = cand["extra"].get("type") or ""
        if "노상" in t:
            add("structure", False, "노상(도로변) 주차장 — 차박 부적합", W["structure_roadside"])
        elif "노외" in t:
            add("structure", True, "노외 개방형 주차장", 0)
        try:
            cap = int(str(cand["extra"].get("capacity") or "").strip() or 0)
        except ValueError:
            cap = 0
        if cap >= 150:  # 대형 공영주차장 = 시장·상업지 혼잡(예: 오일시장) → 차박 부적합
            add("busy_lot", False, f"대형 주차장({cap}면) — 혼잡·상업지 가능성", -12)

    if cand["category"] == "parking":  # V6 침수 (둔치)
        g = str(cand["extra"].get("risk_grade") or "").strip()
        if g == "1":
            add("flood", False, "침수위험 1등급(위험)", W["flood"]["grade1"])
        elif g == "2":
            add("flood", False, "침수위험 2등급(주의)", W["flood"]["grade2"])
        elif g == "3":
            add("flood", True, "침수위험 3등급(양호)", 0)

    if cand["category"] == "nakji":  # 빈터: 배치때 계산한 주변 건물수로 한적함 반영 (화장실 무관)
        sd, sdetail, sok = _seclusion(cand["extra"].get("houses"))
        sm = conds.get("sec_mult", 1.0)
        if conds.get("quiet") and sm < 1.3:
            sm = 1.3
        add("seclusion", sok, sdetail, round(sd * sm))

    c = _nearest(cand, refs["cctv"], 500)
    if c:
        add("cctv", True, f"안전CCTV {_fmt(c[1])}", W["cctv_500"], _ref(c))
    p = _nearest(cand, refs["pharmacy"], 3000)
    if p:
        w = W["pharmacy_3000"] * (2 if conds["pharmacyNeed"] else 1)
        add("pharmacy", True, f"심야약국 {_fmt(p[1])} ({p[0]['name']})", w, _ref(p))
    elif conds["pharmacyNeed"]:
        add("pharmacy", False, "심야약국 3km 내 없음", 0)
    h = _nearest(cand, refs["cleanhouse"], 500)
    if h:
        add("cleanhouse", True, f"클린하우스 {_fmt(h[1])}", W["cleanhouse_500"], _ref(h))

    f = _nearest(cand, refs["festival_active"], 1000)
    if f:
        add("festival", False, f"축제 개최중 {_fmt(f[1])} ({f[0]['name']}) — 붐빌 수 있음",
            W["festival_active_1000"], _ref(f))

    fb = (conds.get("feedback") or {}).get(str(cand["id"]))  # 이용자 평가 반영 (부정에 더 민감)
    if fb and (fb["up"] or fb["down"]):
        delta = max(-30, min(20, fb["up"] * 4 - fb["down"] * 8))
        add("feedback", fb["down"] <= fb["up"], f"이용자 평가 👍{fb['up']} 👎{fb['down']}", delta)

    # 선호 장소유형 — 사용자가 고른 순서대로 가점 (1순위 +10, 2순위 +6, 3순위 +3)
    place_order = conds.get("place_order") or []
    if cand["category"] in place_order:
        rank = place_order.index(cand["category"])
        bonus = [10, 6, 3][rank] if rank < 3 else 0
        if bonus:
            add("place_pref", True, f"선호 장소유형 {rank + 1}순위 ({_CAT_LABEL.get(cand['category'], cand['category'])})", bonus)

    # V11 자연공원 — 서버는 폴리곤 함수 직접 호출 → 전 후보 판정 (프론트 2-pass 한계 해소)
    zone = _zone_lookup(cand["lat"], cand["lon"])
    if zone:
        add("natural_park", False,
            f"{zone[0]} {zone[1]} 구역 — 야영·취사 금지(자연공원법 27조)", W["natural_park"])
    else:
        add("natural_park", True, "자연공원 구역 아님", 0)

    return {"cand": cand, "score": score, "why": why, "_rd": rd}


# ── reply 생성: gpt-5-mini — 전달한 점수·근거만 인용 (pipeline §7). 실패 시 템플릿 ──
def _gpt_reply(question, conds, top, total, excluded):
    key = (os.environ.get("GPT_MINI_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("no key")
    from openai import OpenAI
    facts = "\n".join(
        f"{i + 1}위 {s['cand']['name']} ({catlabel(s['cand']['category'])}, {s['score']}점): "
        + "; ".join(w["detail"] for w in s["why"] if w["pass"] and w["delta"] > 0)
        for i, s in enumerate(top[:3]))
    prompt = f"""사용자 질문: {question}

우리 데이터로 계산한 추천 결과 (후보 {total}곳 검증, 구조상 차박 불가 {excluded}곳 제외):
{facts}

규칙: 위 데이터만 인용해 4~6문장으로 답해줘. 순위·점수·거리를 그대로 쓰고, 없는 정보는 만들지 마.
공영주차장은 '차박하세요'가 아니라 '주차+화장실이 가까운 지점' 으로 우회 표현. 한국어로."""
    client = OpenAI(api_key=key)
    res = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "system",
                   "content": "너는 차박/캠핑 편의시설 지도 서비스의 안내자다. 전달받은 점수·거리 데이터만 인용한다."},
                  {"role": "user", "content": prompt}])
    return (res.choices[0].message.content or "").strip()


_CAT_LABEL = {"parking_public": "공영주차장", "camping": "야영장", "parking": "둔치주차장", "nakji": "공공 빈터(노지)"}


def catlabel(c):
    return _CAT_LABEL.get(c, c)


def _display_name(cand):
    """공영/둔치 주차장은 지번명(예: '신엄리 3009-4') 대신 '{리/동} 공영주차장' 으로 표기.
    야영장 등 실제 명칭이 있는 카테고리는 그대로 사용."""
    nm = (cand.get("name") or "").strip()
    cat = cand["category"]
    if cat in ("parking_public", "parking"):
        addr = cand.get("road_addr") or cand.get("lotno_addr") or ""
        areas = re.findall(r"[가-힣0-9]+[동리]", addr)
        area = areas[-1] if areas else nm
        return f"{area} {'공영주차장' if cat == 'parking_public' else '둔치주차장'}"
    if cat == "nakji":
        addr = cand.get("lotno_addr") or cand.get("road_addr") or ""
        areas = re.findall(r"[가-힣0-9]+[동리]", addr)
        return f"{(areas[-1] if areas else nm)} 빈터(노지)"
    return nm


def _display_names(top):
    """상위 후보의 표시명 목록. 같은 리/동이라 이름이 겹칠 때만 지번 번호로 구분자를 붙여 유일화."""
    names = [_display_name(s["cand"]) for s in top]
    dup = {n for n in names if names.count(n) > 1}
    out = []
    for s, nm in zip(top, names):
        if nm in dup:
            addr = s["cand"].get("lotno_addr") or s["cand"].get("road_addr") or ""
            nums = re.findall(r"\d+(?:-\d+)?", addr)
            tok = nums[-1] if nums else str(s["cand"]["id"]).split(":")[-1][:6]
            nm = f"{nm} ({tok})"
        out.append(nm)
    return out


# ── 민가 한적함 (V-World 건물레이어 LT_C_SPBD) — D 추가 7/9 ──
_HOUSE_CACHE: dict = {}


def house_count(lat, lon, radius_m=250):
    """좌표 주변 반경 내 건물(민가) 수. V-World 실패/키없음 시 None."""
    k = (round(lat, 4), round(lon, 4))
    if k in _HOUSE_CACHE:
        return _HOUSE_CACHE[k]
    vkey = os.environ.get("VWORLD_KEY", "").strip()
    if not vkey:
        return None
    dlat = radius_m / 111000.0
    dlon = radius_m / (111000.0 * math.cos(lat * math.pi / 180) or 1)
    box = f"BOX({lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat})"
    url = ("https://api.vworld.kr/req/data?service=data&request=GetFeature&version=2.0"
           "&data=LT_C_SPBD&format=json&size=1000&crs=EPSG:4326&domain=localhost"
           f"&geomFilter={box}&key={vkey}")
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            resp = json.load(r).get("response", {})
        if resp.get("status") != "OK":
            _HOUSE_CACHE[k] = None
            return None
        total = (resp.get("record") or {}).get("total")
        n = int(total) if total is not None else len(
            ((resp.get("result") or {}).get("featureCollection") or {}).get("features") or [])
        _HOUSE_CACHE[k] = n
        return n
    except Exception:  # noqa: BLE001 — V-World 장애 시 한적함 미반영(중립)
        _HOUSE_CACHE[k] = None
        return None


def _seclusion(n):
    """민가 수 → 연속 점수. 1순위 팩터라 크게 (−28~+38). 적을수록 가점."""
    if n is None:
        return 0, "주변 민가 정보 없음", False
    delta = max(-28, round(38 - n * 0.55))  # 1순위: 0채 +38, 20채 +27, 50채 +11, 100채 −17
    if n == 0:
        label = "주변 건물 0채 — 매우 한적"
    elif n <= 15:
        label = f"주변 건물 {n}채 — 한적"
    elif n <= 40:
        label = f"주변 건물 {n}채 — 다소 한적"
    elif n <= 100:
        label = f"주변 건물 {n}채 — 보통"
    else:
        label = f"주변 건물 {n}채 — 밀집(민가 많음)"
    return delta, label, n <= 40


def _apply_seclusion(scored, conds):
    """한적함이 1순위 팩터 — 상위 후보의 민가를 V-World로 조회해 점수·순위 반영 (항상 적용)."""
    sec_mult = conds.get("sec_mult", 1.0)
    if conds.get("quiet") and sec_mult < 1.3:
        sec_mult = 1.3  # '조용/한적' 키워드도 한적함 강화
    # 대상: 주차장은 화장실 근접(_rd) 순으로 런타임 평가. 빈터(nakji)는 배치때 계산한 값을 _score에서
    #       직접 반영하므로 여기선 제외 (화장실 멀어도 경치·공터 좋으면 추천되게)
    cap = min(len(scored), 30 if sec_mult > 1.0 else 18)
    targets = [s for s in sorted(scored, key=lambda s: s["_rd"])
               if s["cand"]["category"] != "nakji"][:cap]
    for s in targets:
        n = s["cand"]["extra"].get("houses")   # 배치로 사전계산한 값 우선 (실시간 V-World 호출 절약 → 응답 ↑)
        if n is None:
            n = house_count(s["cand"]["lat"], s["cand"]["lon"])  # 미계산분만 실시간 조회
        delta, detail, ok = _seclusion(n)
        delta = round(delta * sec_mult)
        s["score"] += delta
        s["why"].append({"check": "seclusion", "pass": ok, "detail": detail, "delta": delta})
    scored.sort(key=lambda s: (-s["score"], s["_rd"]))


class RecommendIn(BaseModel):
    message: str
    categories: list[str] = []


_PRIORITY_MULT = {0: 2.0, 1: 1.5, 2: 1.2}  # 1·2·3순위 가중 배율, 그 외 1.0


def _priority_mult(priorities, factor):
    if priorities and factor in priorities:
        return _PRIORITY_MULT.get(priorities.index(factor), 1.0)
    return 1.0


def _apply_priorities(W, priorities):
    """우선순위 순서에 따라 해당 스코어 항목 가중치를 배율 조정."""
    if not priorities:
        return W
    W = json.loads(json.dumps(W))  # deep copy
    def scale(key, m):
        if isinstance(W.get(key), dict):
            W[key] = {k: round(v * m) for k, v in W[key].items()}
        elif isinstance(W.get(key), (int, float)):
            W[key] = round(W[key] * m)
    mv = _priority_mult(priorities, "view")
    scale("sea_view", mv); scale("nature_view", mv)
    mr = _priority_mult(priorities, "restroom")
    scale("restroom", mr); scale("restroom_24h", mr)
    scale("ev", _priority_mult(priorities, "ev"))
    return W


def _rank_core(message, categories, cfg=None):
    """화장실·풍경·EV + 민가 한적함을 랭킹. cfg={priorities,view_types,place_types}로 우선순위 조정.
    반환: (conds, cands, excluded, scored)."""
    cfg = cfg or {}
    priorities = cfg.get("priorities") or []
    W = _apply_priorities(load_weights(), priorities)
    conds = parse_conds(message, categories)
    conds["priorities"] = priorities
    conds["feedback"] = feedback_counts()
    conds["view_types"] = cfg.get("view_types") or []
    conds["sec_mult"] = _priority_mult(priorities, "seclusion")
    if "ev" in priorities:
        conds["ev"] = True
    bbox = REGIONS[conds["region"]]
    place_pref = cfg.get("place_types") or []          # 사용자가 고른 순서 (비면 기본·부스트 없음)
    conds["place_order"] = place_pref
    place_types = place_pref or ["parking_public", "parking", "nakji"]  # 기본: 주차장 + 공공 빈터(노지)

    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        cands_all = []
        for _pt in ("parking_public", "camping", "parking", "nakji"):
            if _pt in place_types:
                cands_all += _fetch(con, bbox, _pt, 300)
        # 민가 많은 주차장은 추천 후보에서 제외 (배치로 사전계산한 houses > 40, 미상은 유지)
        cands_all = [c for c in cands_all if not (
            c["category"] in ("parking_public", "parking") and (c["extra"].get("houses") or 0) > PARKING_HOUSE_MAX)]
        # 공항부지 등 명백한 부적합 구역 제외
        cands_all = [c for c in cands_all if not _in_exclude_zone(c["lat"], c["lon"])]
        refs = {
            "restroom": _index(_fetch(con, bbox, "restroom", 2000)),
            "beach": _index(_fetch(con, bbox, "beach", 300)),
            "ev": _index(_fetch(con, bbox, "ev_charger", 500) if conds["ev"] else []),
            "cctv": _index(_fetch(con, bbox, "cctv", 300)),
            "pharmacy": _index(_fetch(con, bbox, "pharmacy", 50)),
            "cleanhouse": _index(_fetch(con, bbox, "cleanhouse", 1000)),
        }
        today = date.today().isoformat()
        fests = [f for f in _fetch(con, bbox, "festival", 300)
                 if (f["extra"].get("start") or "9999") <= today <= (f["extra"].get("end") or "")]
        refs["festival_active"] = _index(fests)
    finally:
        con.close()
    refs["ev_live"] = _ev_status() if conds["ev"] else {}

    cands = [c for c in cands_all if not _struct_impossible(c)]     # V12 하드 제외
    excluded = len(cands_all) - len(cands)
    scored = sorted((_score(c, refs, conds, W) for c in cands),
                    key=lambda s: (-s["score"], s["_rd"]))
    _apply_seclusion(scored, conds)                                # 민가 한적함 (D, 7/9)
    return conds, cands, excluded, scored


def _pick_diverse(kept, scored, top_k, min_parking=2):
    """상위 위주로 뽑되 주차장이 최소 min_parking곳 포함되게 → GPT가 노지/주차장 섞을 여지.
    노지만 계속 추천되는 문제 완화. 70점 넘는 주차장이 부족하면 전체 scored에서 최고 주차장을 끌어옴
    (제주 도심 주차장은 건물 많아 70 미달인 경우가 많음 — GPT가 최종 판단하도록 후보엔 넣음)."""
    out = list(kept[:top_k])
    have = sum(1 for s in out if s["cand"]["category"] in ("parking_public", "parking"))
    if have < min_parking:
        par_all = sorted((s for s in scored if s["cand"]["category"] in ("parking_public", "parking")),
                         key=lambda s: (-s["score"], s["_rd"]))
        for p in par_all:
            if have >= min_parking:
                break
            if p in out:
                continue
            naks = [s for s in out if s["cand"]["category"] == "nakji"]
            if naks:
                out.remove(naks[-1])
            out.append(p); have += 1
    out.sort(key=lambda s: (-s["score"], s["_rd"]))
    return out


def _top_over70(scored, top_k, cutoff=70, diverse=False, min_parking=2):
    """clamp(0~100) 후 cutoff 초과 후보만 상위 top_k 반환 (70점 이하 미추천).
    diverse=True면 노지 일변도 방지를 위해 주차장 최소 포함(부족 시 전체에서 보충)."""
    for s in scored:
        s["score"] = max(0, min(100, round(s["score"])))
    kept = sorted((s for s in scored if s["score"] > cutoff), key=lambda s: (-s["score"], s["_rd"]))
    if diverse:
        return _pick_diverse(kept, scored, top_k, min_parking)
    return kept[:top_k]


@router.post("/api/recommend")
def recommend(req: RecommendIn):
    if not DB_PATH.exists():
        raise HTTPException(500, "facilities.db 없음")
    conds, cands, excluded, scored = _rank_core(req.message, req.categories)
    bbox = REGIONS[conds["region"]]
    top = _top_over70(scored, 5)

    try:
        reply = _gpt_reply(req.message, conds, top, len(cands), excluded)
    except Exception:  # noqa: BLE001 — GPT 장애 시 템플릿 폴백 (추천 자체는 항상 응답)
        lines = "\n".join(f"{i + 1}위 {s['cand']['name']} — {s['score']}점" for i, s in enumerate(top[:3]))
        reply = (f"📊 {conds['region']} 후보 {len(cands)}곳을 조건 검증해 상위 {len(top)}곳을 골랐어요."
                 + (f" (차박 불가 {excluded}곳 제외)" if excluded else "") + f"\n{lines}")

    pad = 0.015
    lats = [s["cand"]["lat"] for s in top] or [bbox[0], bbox[2]]
    lons = [s["cand"]["lon"] for s in top] or [bbox[1], bbox[3]]
    return {
        "reply": reply,
        "map": {
            "bbox": [min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad],
            "layers": [],  # 추천 핀만 표출 (계약 §1)
            "pins": [{
                "id": s["cand"]["id"], "lat": s["cand"]["lat"], "lon": s["cand"]["lon"],
                "label": f"{i + 1}위 · {s['score']}점", "item": s["cand"],
                "score": s["score"], "why": s["why"],
            } for i, s in enumerate(top)],
        },
    }


def rank_spots(message, categories=None, top_k=6):
    """챗봇 MCP 에이전트용 — GPT/map 없이 화장실·민가 랭킹 상위 후보만 반환."""
    if not DB_PATH.exists():
        return {"error": "facilities.db 없음", "results": []}
    conds, cands, excluded, scored = _rank_core(message, categories or [])
    top = _top_over70(scored, top_k)
    dnames = _display_names(top)          # 중복 이름은 지번으로 구분
    results = []
    for nm, s in zip(dnames, top):
        c = s["cand"]
        results.append({
            "name": nm, "category": catlabel(c["category"]),
            "addr": c.get("road_addr") or c.get("lotno_addr"),
            "lat": c["lat"], "lon": c["lon"],
            "score": s["score"],
            "why": [w["detail"] for w in s["why"] if w.get("delta", 0) != 0 or w["check"] in ("restroom", "seclusion")],
        })
    return {"region": conds["region"], "candidates": len(cands), "excluded": excluded, "results": results}


def rank_map(message, categories=None, top_k=5, cfg=None, diverse=False):
    """프론트 지도용 — applyMapCommand 형식 {bbox, layers, pins} 반환 (번호 핀·클릭 상세용).
    diverse=True면 노지 일변도 방지(주차장 최소 포함) — GPT 재랭킹용 후보 풀."""
    if not DB_PATH.exists():
        return {"bbox": None, "layers": [], "pins": []}
    conds, cands, excluded, scored = _rank_core(message, categories or [], cfg)
    fbc = conds.get("feedback") or {}
    top = _top_over70(scored, top_k, diverse=diverse)
    dnames = _display_names(top)          # 중복 이름은 지번으로 구분
    bb = REGIONS[conds["region"]]
    pad = 0.015
    lats = [s["cand"]["lat"] for s in top] or [bb[0], bb[2]]
    lons = [s["cand"]["lon"] for s in top] or [bb[1], bb[3]]
    return {
        "bbox": [min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad],
        "layers": [],  # 추천 핀만 먼저 표출 — 사용자가 레이어 칩으로 편의시설 켜서 검토
        "pins": [{
            "id": s["cand"]["id"], "lat": s["cand"]["lat"], "lon": s["cand"]["lon"],
            "label": f"{i + 1}위 · {s['score']}점",
            "item": {**s["cand"], "name": dnames[i],
                     "fb_up": (fbc.get(str(s["cand"]["id"])) or {}).get("up", 0),
                     "fb_down": (fbc.get(str(s["cand"]["id"])) or {}).get("down", 0)},
            "score": s["score"], "why": s["why"],
        } for i, s in enumerate(top)],
    }
