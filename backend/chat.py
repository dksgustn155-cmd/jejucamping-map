import asyncio
import json
import os
import re
import sqlite3
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastmcp import FastMCP, Client
from pydantic import BaseModel
from fastapi_mcp import FastApiMCP

# 실행(개발): uvicorn backend.chat:app --reload --port 8000

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DB_PATH = ROOT / "data" / "facilities.db"
FRONTEND_DIR = ROOT / "frontend"

# 전기차 실시간 가용 캐시 (Tier 3: 저장 안 하고 짧은 캐시로 API 폭주 방지, docs/data-management.md)
_EV_CACHE = {"t": 0.0, "data": {}}
_EV_TTL = 180  # 3분

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 시작 시 실행할 코드
    print("Startup!")
    # 마운트한 FastMCP(/mcp)의 세션 매니저 lifespan 을 함께 실행 (없으면 MCP 호출 시 task group 오류)
    async with mcp_app.lifespan(app):
        yield
    # 앱 종료 시 실행할 코드
    print("Shutdown!")

def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.split("#", 1)[0].strip())


load_env()
KAKAO_JS_KEY = os.environ.get("KAKAO_JS_KEY", "")
JEJU_ITS_CODE = os.environ.get("JEJU_ITS_CODE", "")





app = FastAPI(title="캠핑 편의시설 지도 API", lifespan=lifespan)
# 프론트(main.py:8000)에서 이 서버(8011)의 /api/agent/stream 을 크로스오리진 호출하도록 허용 (로컬 데모)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# router = APIRouter(prefix="/api/chat", tags=["chat"])

# MCP 서버 생성
# mcp = FastApiMCP(
#     app,
#     name="제주도의 자유 캠핑장 추천",
#     description="제주도 자유 캠핑장 추천을 위한 시설 카테고리 목록 제공 및 대화형 추천 기능",
#     base_url="http://localhost:8000"  # 요청 라우팅에 중요
# )
# FastMCP 도구 정의
mcp = FastMCP("MyMCPTools")

# MCP를 FastAPI 앱에 등록
# app.include_router(mcp.router, prefix="/mcp")
# Mount your MCP app as a sub-application
# app = mcp.streamable_http_app()

# 4. FastAPI에 FastMCP 라우터를 결합
# mcp.init_app(app, router_prefix="/mcp")

class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    history: Optional[list] = None  # [{role, content}...] 멀티턴 대화 맥락


class ChatResponse(BaseModel):
    response: str


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """사용자의 질문을 GPT-호환 API로 전달하고 응답을 반환합니다."""
    api_key = os.environ.get("GPT_MINI_API_KEY", "").strip()
    base_url = os.environ.get("GPT_MINI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    if not api_key:
        raise HTTPException(status_code=500, detail=".env 에 GPT_MINI_API_KEY 가 없습니다")

    model_name = request.model or os.environ.get("GPT_MINI_MODEL", "gpt-4o-mini")

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": request.system_prompt or "당신은 캠핑/제주도 여행 정보를 도와주는 친절한 비서입니다.",
            },
            {"role": "user", "content": request.message},
        ],
        "temperature": 0.7
    }
    

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = json.load(response)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"GPT API 호출 실패: {exc}") from exc

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="GPT API 응답 형식이 올바르지 않습니다") from exc

    return ChatResponse(response=content)


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

@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """두 숫자를 더합니다."""
    print(f"add_numbers() 호출됨: a={a}, b={b}")
    return a + b

@mcp.tool()
def categories():
    """시설 카테고리 목록 조회.
    제주도 자유 캠핑장 추천을 위한 시설 카테고리 목록 제공.
    역할: facilities 테이블에서 사용 가능한 카테고리 값을 확인한다.
    요청 파라미터: 없음.
    응답: {"categories": ["restroom", "camping", ...]} 형태의 목록.
    """
    print("categories() 호출됨")
    con = get_db()
    try:
        rows = con.execute(
            "SELECT DISTINCT category FROM facilities WHERE category IS NOT NULL ORDER BY category"
        ).fetchall()
    finally:
        con.close()
    return {"categories": [row["category"] for row in rows]}

@mcp.tool()
def addr_facilities(
    address_keyword: str,
    category: str | None = None,
    limit: int = 500,
):
    """주소 키워드 기반 시설 조회.

    역할: road_addr 또는 lotno_addr에 특정 지역명/키워드가 포함된 시설 정보를 반환한다.
    요청 파라미터: address_keyword(필수 문자열), category(선택 문자열), limit(선택 정수).
    응답: {"count": N, "items": [{...시설 정보...}]} 형태.
    """
    print(f"addr_facilities() 호출됨: address_keyword={address_keyword}, category={category}, limit={limit}")
    con = get_db()
    try:
        sql = [
            "SELECT id, category, name, lat, lon, road_addr, lotno_addr, open_hours, tel, extra",
            "FROM facilities",
            "WHERE lat IS NOT NULL AND (LOWER(road_addr) LIKE ? OR LOWER(lotno_addr) LIKE ?)",
        ]
        pattern = f"%{address_keyword.strip().lower()}%"
        params = [pattern, pattern]

        if category:
            cats = [c.strip() for c in category.split(",") if c.strip()]
            sql.append("AND category IN (%s)" % ",".join("?" * len(cats)))
            params += cats

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

@mcp.tool()
def facilities(
    sw_lat: float,
    sw_lng: float,
    ne_lat: float,
    ne_lng: float,
    category: str | None = None,
    limit: int = 500,
):
    """지도 영역 기반 시설 조회.

    역할: 지정한 지도 bounding box 안에 포함된 시설 정보를 반환한다.
    요청 파라미터: sw_lat, sw_lng, ne_lat, ne_lng(필수 실수), category(선택 문자열), limit(선택 정수).
    응답: {"count": N, "items": [{...시설 정보...}]} 형태.
    """
    print(f"facilities() 호출됨: sw_lat={sw_lat}, sw_lng={sw_lng}, ne_lat={ne_lat}, ne_lng={ne_lng}, category={category}, limit={limit}")
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


@mcp.tool()
def search_regulations(query: str, top_k: int = 5):
    """캠핑·야영·차박·취사 관련 **법령/조례/고시** 및 시설 규정을 의미 기반(RAG)으로 검색.

    역할: "여기서 자도 돼?", "한라산 취사 가능?", "해수욕장 야영 규정" 처럼
    합법성·규정·과태료를 묻는 질문에 사용한다. (단순 시설 위치는 addr_facilities/facilities 사용)
    요청 파라미터: query(필수 문자열), top_k(선택 정수, 기본 5).
    응답: {"fallback_level": ..., "results": [{"score","source","region","text"}...]}.
    text 에 법 조문·조례 원문 근거가 들어있으니, 답변 시 이 근거만 인용하라.
    """
    print(f"search_regulations() 호출됨: query={query}, top_k={top_k}")
    try:
        from rag.search import smart_search  # 지연 import (무거운 faiss/torch 로드를 호출 시로 미룸)
        res = smart_search(query, top_k=top_k)
    except Exception as e:  # noqa: BLE001 — RAG 미탑재(경량 배포) 시 크래시 대신 안내
        print(f"search_regulations RAG 불가: {e!r}")
        return {"query": query, "fallback_level": "unavailable", "results": [],
                "note": "규정 검색(RAG)은 이 배포 환경에서 준비 중입니다. 지역 조례·자연공원법 등은 현장 안내판·지자체 공고를 확인해 주세요."}
    slim = []
    for r in res.get("results", []):
        meta = r.get("metadata", {}) or {}
        slim.append({
            "score": round(float(r.get("score", 0)), 3),
            "source": meta.get("category") or meta.get("source") or meta.get("law_name"),
            "region": meta.get("region"),
            "text": (r.get("text") or "")[:900],
        })
    return {"query": res.get("query", query), "fallback_level": res.get("fallback_level"), "results": slim}


@mcp.tool()
def recommend_spots(region: str, question: str = ""):
    """제주 차박/노지 캠핑 후보를 **화장실 근접 + 민가 한적함(V-World 건물)** 기준으로 랭킹해 추천.

    역할: "애월 조용한 노지 추천", "성산 차박 좋은 곳" 처럼 '장소 추천/랭킹'을 원할 때 사용.
    (단순 시설 나열은 addr_facilities, 규정은 search_regulations)
    요청 파라미터: region(지역명 — 애월/서귀포/성산/중문/협재/함덕/제주/담양), question(사용자 원문 그대로).
    응답: {"region","candidates","results":[{name,category,addr,score,why[]}...]}.
    why 에 '화장실 52m', '주변 건물 31채 — 다소 한적' 등 랭킹 근거가 들어있으니 그대로 인용하라.
    점수는 화장실 근접·한적함·안전·침수 등을 합산한 0~100 값이다.
    """
    print(f"recommend_spots() 호출됨: region={region}, question={question}")
    from backend.recommend import rank_spots  # 지연 import (팀원 C 스코어링 + 민가 공용)
    return rank_spots(f"{region} {question}", top_k=6)


@mcp.tool()
def land_check(lat: float, lon: float):
    """좌표 지점의 **필지 정보(지번·지목·소유구분)** 확인 — V-World 연속지적도+토지소유정보.

    역할: 차박/야영 후보지가 사유지인지(무단 침입 위험), 지목이 무엇인지(주차장/임야/전 등) 확인.
    추천 결과 재검증이나 "여기 사유지야?" 질문에 사용한다.
    응답: {"addr","jibun","지목","소유구분","판정"} — 판정은 공공(안심)/사유지(주의)/확인필요.
    """
    print(f"land_check() 호출됨: lat={lat}, lon={lon}")
    import urllib.parse
    vkey = os.environ.get("VWORLD_KEY", "").strip()
    if not vkey:
        return {"error": "VWORLD_KEY 없음"}
    try:
        geom = urllib.parse.quote(f"POINT({lon} {lat})")
        url = ("https://api.vworld.kr/req/data?service=data&request=GetFeature&version=2.0"
               "&data=LP_PA_CBND_BUBUN&format=json&size=1&crs=EPSG:4326&domain=localhost"
               f"&geomFilter={geom}&key={vkey}")
        with urllib.request.urlopen(url, timeout=10) as r:
            resp = json.load(r).get("response", {})
        feats = ((resp.get("result") or {}).get("featureCollection") or {}).get("features") or []
        if not feats:
            return {"error": "해당 좌표의 필지를 찾지 못함"}
        p = feats[0]["properties"]
        pnu = p.get("pnu")
        out = {"addr": p.get("addr"), "jibun": p.get("jibun"), "pnu": pnu}
        u2 = (f"https://api.vworld.kr/ned/data/getPossessionAttr?key={vkey}&pnu={pnu}"
              "&format=json&numOfRows=1&domain=localhost")
        with urllib.request.urlopen(u2, timeout=10) as r:
            fields = (json.load(r).get("possessions") or {}).get("field") or []
        if fields:
            f = fields[0]
            own = (f.get("posesnSeCodeNm") or "").strip()
            out["지목"] = f.get("lndcgrCodeNm")
            out["소유구분"] = own
            if any(k in own for k in ("국유", "공유", "군유", "시유", "도유")):
                out["판정"] = "공공 토지 — 상대적으로 안심 (단, 이용규정 확인)"
            elif any(k in own for k in ("개인", "법인", "종중", "외국")):
                out["판정"] = "사유지 — 무단 주차·야영 시 문제 소지, 소유자 동의 필요"
            else:
                out["판정"] = f"소유구분 '{own}' — 관할 기관 확인 권장"
        return out
    except Exception as exc:  # noqa: BLE001
        return {"error": f"필지 조회 실패: {exc}"}


# ── GPT ↔ MCP 에이전트 브리지 ────────────────────────────────
# GPT가 위 @mcp.tool() 들을 스스로 발견해 골라 호출하고, 결과(실제 DB)로만 답하게 한다.
AGENT_SYSTEM_PROMPT = (
    "너는 제주 캠핑/차박 도우미다. 반드시 제공된 도구(MCP)를 호출해 실제 데이터로만 답하라.\n"
    "사용 가능한 시설 카테고리(값 그대로 사용): restroom(화장실), parking_public(공영주차장), "
    "parking(둔치주차장), ev_charger(전기차충전), camping(야영장), beach(해수욕장), cctv(안전CCTV), "
    "cleanhouse(클린하우스), festival(축제), tourinfo(관광안내소), pharmacy(심야약국). "
    "→ 카테고리를 이미 알고 있으니 categories 도구는 호출하지 마라.\n"
    "도구 선택: '어디가 좋아/추천해줘/조용한 곳' 등 장소 추천은 recommend_spots(지역명, 원문)를, "
    "'특정 시설이 어디 있어' 위치 질문은 addr_facilities·facilities 를, "
    "'자도/취사/야영해도 되는지' 등 법령·조례·규정 질문은 search_regulations 를 사용하라.\n"
    "효율 규칙: 같은 도구를 같은/비슷한 인자로 반복 호출하지 마라. 카테고리별로 최대 1회만 호출하고, "
    "규정 검색도 2회 이내로 제한하라. 필요한 데이터가 모이면 더 호출하지 말고 즉시 최종 답을 작성하라.\n"
    "답변 규칙: 절대 지어내지 말고 도구 결과에 있는 것만 인용하라. 규정은 단정하지 말고 근거(법령명·조항)를 "
    "제시하되, 관련 규정을 못 찾으면 '확인되지 않았다'고 정직하게 말하고 관할기관 확인을 권하라.\n"
    "멀티턴 규칙: 추천에 필요한 지역이 없거나 요청이 모호하면, 도구를 호출하지 말고 한 문장으로 짧게 되물어라 "
    "(예: '어느 지역을 생각하세요? 애월·성산·서귀포·중문·협재·함덕 중에서요.'). "
    "지역이 파악되면 그때 recommend_spots 로 추천하라. 대화 맥락(이전 답변)을 활용해 같은 걸 다시 묻지 마라."
)


def _openai_chat(payload: dict) -> dict:
    """OpenAI 호환 chat/completions 호출 (urllib — httpx SSL 이슈 회피)."""
    api_key = os.environ.get("GPT_MINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail=".env 에 GPT_MINI_API_KEY 가 없습니다")
    base_url = os.environ.get("GPT_MINI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"GPT API 호출 실패: {exc}") from exc


def _openai_stream(payload: dict):
    """OpenAI stream=True 호출. ('delta', 텍스트)를 실시간 yield, 마지막에 ('tool_calls', [...]) yield."""
    api_key = os.environ.get("GPT_MINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail=".env 에 GPT_MINI_API_KEY 가 없습니다")
    base_url = os.environ.get("GPT_MINI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps({**payload, "stream": True}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    tool_calls: dict = {}
    with urllib.request.urlopen(req, timeout=120) as resp:
        buf = b""
        done = False
        while not done:
            piece = resp.read(64)  # 작게 읽어 줄 버퍼링 우회 (토큰이 도착하는 즉시 처리)
            if not piece:
                break
            buf += piece
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    done = True
                    break
                try:
                    choice = json.loads(data)["choices"][0]
                except (KeyError, IndexError, ValueError):
                    continue
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    yield ("delta", delta["content"])
                for tc in delta.get("tool_calls") or []:
                    slot = tool_calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
    yield ("tool_calls", [tool_calls[i] for i in sorted(tool_calls)])


async def run_agent(question: str, model: Optional[str] = None, max_steps: int = 6) -> str:
    """GPT가 MCP 도구를 발견·선택·호출하는 루프. 최종 자연어 답변을 반환."""
    model_name = model or os.environ.get("GPT_MINI_MODEL", "gpt-5-mini")
    async with Client(mcp) as client:  # 인메모리 접속 (같은 프로세스의 FastMCP)
        mcp_tools = await client.list_tools()
        oai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": (t.description or "").strip(),
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            }
            for t in mcp_tools
        ]
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        # gpt-5 계열은 추론 강도를 낮춰 속도 향상 (도구 선택엔 low 로 충분)
        extra = {"reasoning_effort": "low"} if model_name.startswith("gpt-5") else {}
        for _ in range(max_steps):
            body = _openai_chat({
                "model": model_name,
                "messages": messages,
                "tools": oai_tools,
                "tool_choice": "auto",
                "max_completion_tokens": 4000,
                **extra,
            })
            msg = body["choices"][0]["message"]
            if msg.get("tool_calls"):
                messages.append(msg)  # 도구 호출 기록 그대로 저장
                for tc in msg["tool_calls"]:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                    result = await client.call_tool(tc["function"]["name"], args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result.data, ensure_ascii=False, default=str),
                    })
                continue
            content = msg.get("content")
            if content:
                return content
            break  # 도구도 없고 답변도 비었으면(토큰 소진 등) 아래서 강제 생성

        # 루프 종료(도구 반복 초과) 또는 빈 응답 → 도구 없이 최종 답변만 강제로 받는다
        messages.append({"role": "user", "content": "위 도구 결과만 근거로, 지금까지 확인한 내용을 한국어로 최종 정리해 답해줘."})
        final = _openai_chat({
            "model": model_name,
            "messages": messages,
            "max_completion_tokens": 4000,
            **extra,
        })
        return final["choices"][0]["message"].get("content") or "(답변 생성에 실패했습니다. 질문을 조금 나눠서 다시 시도해 주세요.)"


@app.post("/api/agent", response_model=ChatResponse)
async def agent(request: ChatRequest) -> ChatResponse:
    """GPT가 MCP 도구를 골라 써서 실제 데이터 기반으로 답하는 대화형 엔드포인트."""
    answer = await run_agent(request.message, request.model)
    return ChatResponse(response=answer)


# 도구 이름 → 사용자에게 보여줄 한글 라벨 (스트리밍 진행 표시용)
_TOOL_LABEL = {
    "categories": "카테고리 확인",
    "addr_facilities": "지역 시설 조회",
    "facilities": "지도영역 시설 조회",
    "search_regulations": "법령·조례 검색",
    "recommend_spots": "추천 후보 랭킹(화장실·한적함)",
    "land_check": "필지·사유지 확인",
    "add_numbers": "계산",
}


async def run_agent_stream(question: str, model: Optional[str] = None, history=None, max_steps: int = 6):
    """SSE 제너레이터: 도구 진행 상태를 실시간으로, 최종 답변은 청크로 흘려보낸다. history=멀티턴 맥락."""
    def sse(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    model_name = model or os.environ.get("GPT_MINI_MODEL", "gpt-5-mini")
    extra = {"reasoning_effort": "low"} if model_name.startswith("gpt-5") else {}
    yield sse({"type": "status", "text": "🤖 질문을 이해하는 중…"})

    async with Client(mcp) as client:
        mcp_tools = await client.list_tools()
        oai_tools = [
            {"type": "function", "function": {
                "name": t.name, "description": (t.description or "").strip(),
                "parameters": t.inputSchema or {"type": "object", "properties": {}}}}
            for t in mcp_tools
        ]
        messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
        for h in (history or []):  # 멀티턴 맥락
            if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
                messages.append({"role": h["role"], "content": str(h["content"])})
        messages.append({"role": "user", "content": question})
        answered = False
        for _ in range(max_steps):
            collected = []
            started = False
            for kind, val in _openai_stream({
                "model": model_name, "messages": messages,
                "tools": oai_tools, "tool_choice": "auto",
                "max_completion_tokens": 4000, **extra,
            }):
                if kind == "delta":  # 최종 답변 토큰이 생성되는 대로 실시간 전송
                    if not started:
                        yield sse({"type": "answer_start"}); started = True
                    yield sse({"type": "delta", "text": val})
                    await asyncio.sleep(0)  # 이벤트 루프에 flush 기회
                elif kind == "tool_calls":
                    collected = val
            if collected:  # 이번 턴은 도구 호출 → 실행하고 다음 턴
                messages.append({"role": "assistant", "content": "", "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}} for tc in collected]})
                for tc in collected:
                    name = tc["name"]
                    args = json.loads(tc["arguments"] or "{}")
                    label = _TOOL_LABEL.get(name, name)
                    hint = args.get("address_keyword") or args.get("query") or args.get("category") or ""
                    yield sse({"type": "tool", "text": f"🔧 {label}" + (f" — {hint}" if hint else "") + " …"})
                    result = await client.call_tool(name, args)
                    data = result.data
                    cnt = ""
                    if isinstance(data, dict):
                        if "count" in data:
                            cnt = f" → {data['count']}건"
                        elif isinstance(data.get("results"), list):
                            cnt = f" → {len(data['results'])}건"
                        elif isinstance(data.get("categories"), list):
                            cnt = f" → {len(data['categories'])}종"
                    yield sse({"type": "tool_done", "text": f"✓ {label}{cnt}"})
                    # 추천이면 지도용 좌표·번호핀 데이터를 함께 전송 (프론트 applyMapCommand)
                    if name == "recommend_spots":
                        try:
                            from backend.recommend import rank_map
                            mp = rank_map(f"{args.get('region', '')} {args.get('question', '')}")
                            if mp.get("pins"):
                                yield sse({"type": "map", "map": mp})
                        except Exception:  # noqa: BLE001 — 지도 데이터 실패해도 답변은 계속
                            pass
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": json.dumps(data, ensure_ascii=False, default=str)})
                continue
            if started:  # 도구 없이 답변이 스트리밍됨 → 완료
                answered = True
            break

        if not answered:  # 도구만 쓰고 답변이 비었으면 도구 없이 최종 답변을 스트리밍
            messages.append({"role": "user", "content": "위 도구 결과만 근거로, 지금까지 확인한 내용을 한국어로 최종 정리해 답해줘."})
            started = False
            for kind, val in _openai_stream({"model": model_name, "messages": messages, "max_completion_tokens": 4000, **extra}):
                if kind == "delta":
                    if not started:
                        yield sse({"type": "answer_start"}); started = True
                    yield sse({"type": "delta", "text": val})
                    await asyncio.sleep(0)  # 이벤트 루프에 flush 기회
        yield sse({"type": "done"})


@app.post("/api/agent/stream")
async def agent_stream(request: ChatRequest):
    """/api/agent 의 SSE 스트리밍 버전 — 도구 진행 상태 + 답변을 실시간 전송."""
    return StreamingResponse(
        run_agent_stream(request.message, request.model, request.history),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── GPT 재랭킹: 후보 풀을 추론으로 비교·채점해 상위 3곳을 순위·차별화 점수로 확정 ──
VERIFY_SYSTEM_PROMPT = (
    "너는 차박/캠핑 추천의 최종 심사관이다. 후보 여러 곳(노지=공공 빈터, 주차장)이 각각 근거(주변 건물 수·각종 거리·뷰 등 why)와 "
    "함께 주어진다. 이를 실제 차박 관점에서 냉정히 비교·평가해 **가장 좋은 상위 3곳**을 순위대로 골라라.\n"
    "매우 중요: 야영·취사 등 '법령·조례 위반 가능성'은 사용자 몫이니 절대 반려·감점 사유로 삼지 마라.\n"
    "채점 — 각 후보에 **서로 다른 적합도 점수(0~100 정수)** 를 매겨라. 모두 100점 같은 무의미한 동점은 금지, 근거를 비교해 우열을 분명히 하라:\n"
    "  · 주변 건물 수가 적을수록(한적) 높게, 많을수록 감점 (숫자를 직접 비교)\n"
    "  · 바다/자연 뷰가 가깝고 뚜렷할수록 높게\n"
    "  · 화장실·클린하우스·EV 등 편의가 가까울수록 가점(단 없어도 경치·한적하면 충분히 좋게)\n"
    "  · 진입로·접근성이 나쁘거나 혐오시설 인접, 이용자 부정평가(fb_down)가 많으면 감점\n"
    "다양성 — 노지만 3곳 고르지 마라. 단 **주차장은 실제 차박 여건이 좋아 적합도 80점 이상을 줄 수 있을 때만** 포함하라"
    "(그 정도면 노지 대신 넣는다). 80점이 안 되는 주차장은 넣지 말고 노지로 채우되, 그래도 3곳이 안 되면 2곳만 추천하라. "
    "노지는 막상 가보면 별로인 경우가 많으니 맹신하지 말고 근거로 냉정히 평가하라.\n"
    "(노지 후보는 시스템이 개인·법인 사유지를 이미 걸러 공공성 있는 곳만 온다. 소유는 현장 표지 확인 권유 선에서만 언급.)\n"
    "공항 부지·활주로 인접·군사·항만·발전소·**골프장/CC/리조트 부지** 등 명백히 부적합한 곳은 그 name 을 exclude 에 넣어라"
    "(주변이 골프코스·페어웨이·리조트로 의심되거나 건물이 거의 없는데 개방된 중산간 시설부지 같으면 제외). 애매하면 넣지 마라.\n"
    "검토가 끝나면 submit_verdict 를 호출하라. overall 은 대부분 '적합'. "
    "items 에 고른 **상위 3곳을 순위대로(다양성 반영)** {name(입력의 name 을 그대로), score(0~100 정수, 서로 다르게), note} 로 담아라. "
    "note 는 한국어 1~2문장으로 친근하게: 분위기(한적함·뷰·주변)·장점·현장 주의점(진입로·화장실 등)을 그 장소에 맞게 구체적으로. "
    "summary 는 왜 이 순위인지 한 줄 총평(선택)."
)

_VERDICT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_verdict",
        "description": "재랭킹 결과 제출 (비교·채점 완료 후 반드시 호출)",
        "parameters": {
            "type": "object",
            "properties": {
                "overall": {"type": "string", "enum": ["적합", "일부적합", "부적합"]},
                "items": {"type": "array", "description": "고른 상위 3곳을 순위대로 (좋은 순)",
                          "items": {"type": "object", "properties": {
                              "name": {"type": "string", "description": "입력 결과의 name 그대로"},
                              "score": {"type": "integer", "description": "적합도 0~100 정수 — 후보마다 서로 다르게"},
                              "note": {"type": "string", "description": "그 장소 설명 1~2문장(분위기·장점·주의점)"}},
                              "required": ["name", "score", "note"]}},
                "summary": {"type": "string", "description": "왜 이 순위인지 한 줄 총평 (생략 가능)"},
                "suggestion": {"type": "string", "description": "부적합/일부적합 시 조건 변경 제안 (없으면 빈 문자열)"},
                "exclude": {"type": "array", "items": {"type": "string"},
                            "description": "추천에서 뺄 부적합 후보의 name 목록 (공항부지·군사·항만 등). 없으면 빈 배열."},
            },
            "required": ["overall", "items"],
        },
    },
}


class VerifyIn(BaseModel):
    region: str
    priorities: Optional[list] = None
    results: list  # [{name, category, addr, lat, lon, score, why: [...]}]


async def run_verify_stream(req: VerifyIn):
    def sse(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    model_name = os.environ.get("GPT_MINI_MODEL", "gpt-5-mini")
    extra = {"reasoning_effort": "low"} if model_name.startswith("gpt-5") else {}  # 재랭킹·비교는 약간의 추론 필요
    yield sse({"type": "status", "text": "🧠 GPT가 장소를 점검하고 설명을 준비하는 중…"})

    async with Client(mcp) as client:
        mcp_tools = await client.list_tools()
        use = set()  # 노지는 배치가 사유지를 이미 걸러 land_check 불필요 → 도구 없이 바로 판정(응답 속도 ↑)
        oai_tools = [
            {"type": "function", "function": {
                "name": t.name, "description": (t.description or "").strip(),
                "parameters": t.inputSchema or {"type": "object", "properties": {}}}}
            for t in mcp_tools if t.name in use
        ] + [_VERDICT_TOOL]
        messages = [
            {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
            {"role": "user", "content":
                f"지역: {req.region} / 사용자 우선순위: {req.priorities or ['기본']}\n"
                f"추천 결과(점수·근거):\n{json.dumps(req.results, ensure_ascii=False)}"},
        ]
        for _ in range(8):
            collected, started = [], False
            for kind, val in _openai_stream({
                "model": model_name, "messages": messages,
                "tools": oai_tools, "tool_choice": "auto",
                "max_completion_tokens": 4000, **extra,
            }):
                if kind == "delta":
                    if not started:
                        yield sse({"type": "answer_start"}); started = True
                    yield sse({"type": "delta", "text": val})
                    await asyncio.sleep(0)
                elif kind == "tool_calls":
                    collected = val
            if not collected:
                break
            messages.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["arguments"]}} for tc in collected]})
            for tc in collected:
                name = tc["name"]
                args = json.loads(tc["arguments"] or "{}")
                if name == "submit_verdict":  # 최종 판정 → 프론트로 전달하고 종료
                    yield sse({"type": "verdict",
                               "overall": args.get("overall", "적합"),
                               "items": args.get("items", []),
                               "summary": args.get("summary", ""),
                               "suggestion": args.get("suggestion", ""),
                               "exclude": args.get("exclude", [])})
                    yield sse({"type": "done"})
                    return
                label = _TOOL_LABEL.get(name, name)
                hint = args.get("query") or (f"({args.get('lat'):.4f},{args.get('lon'):.4f})" if args.get("lat") else "")
                yield sse({"type": "tool", "text": f"🔎 {label}" + (f" — {hint}" if hint else "") + " …"})
                result = await client.call_tool(name, args)
                data = result.data
                done_note = ""
                if name == "land_check" and isinstance(data, dict):
                    done_note = f" → {data.get('판정') or data.get('error') or ''}"
                yield sse({"type": "tool_done", "text": f"✓ {label}{done_note}"})
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": json.dumps(data, ensure_ascii=False, default=str)})
        # GPT가 submit_verdict 를 안 부르고 끝났으면 통과 처리 (지도는 보여준다)
        yield sse({"type": "verdict", "overall": "적합", "summary": "", "suggestion": ""})
        yield sse({"type": "done"})


@app.post("/api/agent/verify")
async def agent_verify(req: VerifyIn):
    """추천 결과 GPT 재검증 (SSE) — 사유지·규정·상식 검토 후 verdict 이벤트로 판정 전달."""
    return StreamingResponse(
        run_verify_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class FeedbackIn(BaseModel):
    region: Optional[str] = None
    priorities: Optional[list] = None
    spot_id: Optional[str] = None
    spot_name: Optional[str] = None
    category: Optional[str] = None
    user_id: Optional[str] = None      # 브라우저별 익명 ID (중복 평가 방지·투표 변경)
    vote: str                          # "up" | "down" | "none"(취소)


@app.post("/api/feedback")
def feedback(req: FeedbackIn):
    """장소 좋아요/싫어요 피드백 누적 (data/feedback.jsonl). user_id별 최신 투표만 집계돼
    한 사람은 1표, 반대로 바꾸면 이전 표가 상쇄됨. 갱신된 {up,down} 카운트를 돌려줌."""
    import datetime
    from backend.recommend import feedback_counts, _FB_CACHE
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "vote": req.vote,
           "region": req.region, "priorities": req.priorities, "user_id": req.user_id,
           "spot_id": req.spot_id, "spot_name": req.spot_name, "category": req.category}
    path = ROOT / "data" / "feedback.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _FB_CACHE["t"] = 0.0               # 캐시 무효화 → 방금 표 반영
    c = feedback_counts().get(str(req.spot_id), {"up": 0, "down": 0})
    return {"ok": True, "up": c.get("up", 0), "down": c.get("down", 0)}


@app.get("/api/feedback")
def feedback_get(spot_id: str):
    """장소 카드용 — 해당 장소의 현재 {up,down} 카운트 (user별 최신 1표 집계)."""
    from backend.recommend import feedback_counts
    c = feedback_counts().get(str(spot_id), {"up": 0, "down": 0})
    return {"spot_id": spot_id, "up": c.get("up", 0), "down": c.get("down", 0)}


_WX_CACHE: dict = {}   # (lat,lon 반올림) → (ts, (문구, pop)) · 주말 예보는 자주 안 바뀜


def _weekend_weather(lat, lon):
    """다가오는 토·일 날씨 예보 (Open-Meteo, 키 불필요). (문구, 최대강수확률) 반환. 실패 시 ('', None).
    30분 캐시 — 같은 좌표 반복 호출 시 외부 API 왕복(≈1.2s) 절약."""
    import datetime
    import time as _t
    ck = (round(lat, 2), round(lon, 2))
    hit = _WX_CACHE.get(ck)
    if hit and _t.time() - hit[0] < 1800:
        return hit[1]
    try:
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
               "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
               "&timezone=Asia%2FSeoul&forecast_days=14")
        with urllib.request.urlopen(url, timeout=8) as r:
            d = json.load(r)["daily"]
        out, pops, today = [], [], datetime.date.today()
        for i, ds in enumerate(d["time"]):
            dt = datetime.date.fromisoformat(ds)
            if dt >= today and dt.weekday() in (5, 6):
                pop = d["precipitation_probability_max"][i]
                pops.append(pop or 0)
                out.append(f"{dt.month}/{dt.day}({'토' if dt.weekday() == 5 else '일'}) "
                           f"{round(d['temperature_2m_min'][i])}~{round(d['temperature_2m_max'][i])}℃, "
                           f"강수확률 {pop}%")
            if len(out) >= 2:
                break
        res = (", ".join(out), (max(pops) if pops else None))
        _WX_CACHE[ck] = (_t.time(), res)
        return res
    except Exception:  # noqa: BLE001
        return "", None


def _nearby_festivals(region, window_days=10):
    """지역 내 다가오는 축제 (name, place, when, summary) 목록. 축제 데이터는 연례 행사이므로 연도는 무시하고
    월·일 기준으로 오늘부터 window_days(기본 10일) 안에 열리는 것을 가까운 순으로 반환."""
    import datetime
    from backend.recommend import REGIONS
    bbox = REGIONS.get(region)
    if not bbox or not DB_PATH.exists():
        return []
    sa, so, na, no = bbox
    today = datetime.date.today()
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT name, lotno_addr, road_addr, extra FROM facilities WHERE category='festival' "
            "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? LIMIT 300", (sa, na, so, no)).fetchall()
    finally:
        con.close()
    scored = []
    for r in rows:
        ex = json.loads(r["extra"]) if r["extra"] else {}
        start = ex.get("start")
        if not start or len(start) < 10:
            continue
        try:
            mo, dy = int(start[5:7]), int(start[8:10])
        except ValueError:
            continue
        days = None  # 올해·내년 중 오늘 이후로 가장 가까운 반복일
        for yr in (today.year, today.year + 1):
            try:
                cand = datetime.date(yr, mo, dy)
            except ValueError:
                continue
            if cand >= today:
                days = (cand - today).days
                break
        if days is not None and days <= window_days:
            nm = r["name"].strip()
            if len(nm) > 5 and nm[:2] == "20" and nm[4:5] == " ":  # 연례행사 명칭의 연도 접두 제거
                nm = nm[5:].strip()
            place = (ex.get("place") or "").strip()
            if not place:  # 개최장소 없으면 주소 끝 동/리 로 대체
                import re as _re
                areas = _re.findall(r"[가-힣0-9]+[동리읍면]", r["lotno_addr"] or r["road_addr"] or "")
                place = areas[-1] if areas else ""
            summ = (ex.get("summary") or "").strip()
            scored.append((days, nm, place, f"{mo}/{dy}", summ))
    scored.sort(key=lambda x: x[0])
    return [(nm, place, when, summ) for _, nm, place, when, summ in scored[:3]]


def _josa_iga(word):
    """받침 유무로 이/가 선택 (예: '축제'→'가', '월대천'→'이')."""
    if word:
        ch = word[-1]
        if "가" <= ch <= "힣":
            return "이" if (ord(ch) - 0xAC00) % 28 else "가"
    return "가"


def _weather_festival_prose(lat, lon, region, date_given=False):
    """평서문 마무리 안내: 이번 주말 날씨 + 근처 축제 + 지도/로드뷰 안내.
    date_given=True(사용자가 날짜·주말을 지정)면 '언제 가시는지 모르겠지만' 문구를 뺀다."""
    parts = []
    wx, pop = _weekend_weather(lat, lon)
    if wx:
        if pop is not None and pop >= 60:
            cmt = "비 소식이 있으니 우천·배수 대비는 챙기시는 게 좋겠어요."
        elif pop is not None and pop >= 30:
            cmt = "약간 비 가능성은 있지만 캠핑하기엔 무난한 편이에요."
        else:
            cmt = "캠핑을 즐기기 좋은 날씨네요."
        lead = "이번 주말 날씨는" if date_given else "언제 가시는지 모르겠지만, 이번 주말 날씨는"
        parts.append(f"{lead} {wx} 로 예상돼요. {cmt}")
    fests = _nearby_festivals(region)   # 10일 이내
    if fests:
        nm, place, when, summ = fests[0]
        where = f"{place}에서 " if place else ""
        gist = f" {summ[:45].rstrip()}…" if summ else ""
        parts.append(f"그리고 {when}경 {where}{nm}{_josa_iga(nm)} 열립니다.{gist} "
                     "인근이 다소 혼잡할 수 있으니 이동·주차에 참고해 주세요.")
    parts.append("추천지는 지도와 로드뷰로 직접 확인해 보세요.")
    return "\n\n".join(parts)


class CfgRecommendIn(BaseModel):
    region: str
    priorities: Optional[list] = None    # ["seclusion","view","restroom","ev"] 순서
    view_types: Optional[list] = None    # ["바다","산","숲","계곡"]
    place_types: Optional[list] = None   # ["parking_public","camping","parking"]
    query: Optional[str] = None          # 원문 질문 (날짜 지정 여부 판단용)


_DATE_HINT_RE = re.compile(
    r"주말|이번\s*주|다음\s*주|내일|모레|글피|오늘|평일|낼|"
    r"[월화수목금토일]요일|\d+\s*월\s*\d+\s*일|\d+\s*/\s*\d+|\d+박|연휴|휴가")


@app.post("/api/recommend_cfg")
def recommend_cfg(req: CfgRecommendIn):
    """우선순위 토글 위젯 전용 — 노지/주차장 섞은 후보 풀(≤6)을 반환. 최종 순위·점수·설명은
    프론트가 /api/agent/verify(GPT 재랭킹)로 상위 3곳을 정한다."""
    from backend.recommend import rank_map
    priorities = req.priorities or ["seclusion"]  # 미선택 시 한적함 기본 (빈 결과 방지)
    cfg = {"priorities": priorities, "view_types": req.view_types, "place_types": req.place_types}
    mp = rank_map(req.region, cfg=cfg, top_k=6, diverse=True)  # 후보 풀(주차장 최소 포함)
    pins = mp.get("pins") or []
    _lab = {"seclusion": "한적함", "view": "풍경", "restroom": "화장실", "ev": "전기차 충전소"}
    pri = " > ".join(_lab.get(x, x) for x in priorities)
    outro = ""
    if not pins:
        reply = (f"{req.region} 지역에서 조건(70점 초과)에 맞는 추천지를 찾지 못했어요.\n"
                 "우선순위나 장소 유형을 바꿔서 다시 시도해 보세요.")
    else:
        reply = f"{req.region} · 우선순위 [{pri}] 기준으로 추천 {min(3, len(pins))}곳을 골라봤어요."
        date_given = bool(req.query and _DATE_HINT_RE.search(req.query))  # 날짜·주말 지정 여부
        outro = _weather_festival_prose(pins[0]["lat"], pins[0]["lon"], req.region, date_given)
    return {"reply": reply, "outro": outro, "map": mp}


# ── FastMCP 를 FastAPI 에 마운트 (반드시 모든 @mcp.tool() 정의 이후) ──
# http_app(path="/") 로 만들어 /mcp 하위에 붙임 → MCP 엔드포인트: http://<host>/mcp/
mcp_app = mcp.http_app(path="/")
app.mount("/mcp", mcp_app)

