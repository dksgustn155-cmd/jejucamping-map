import os

from dotenv import load_dotenv
from openai import OpenAI

from rag.gpt_context import build_gpt_context
from rag.location_resolver import resolve_location


load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY")


SYSTEM_PROMPT = """
너는 차박/캠핑 편의시설 지도 서비스의 AI 안내자다.

원칙:
1. 노지 캠핑 장소를 직접 추천하지 않는다.
2. 사용자가 선택한 위치 주변의 화장실, 주차장, 편의시설을 안내한다.
3. 취사, 야영, 차박 가능 여부는 검색된 법령/조례 근거를 바탕으로만 말한다.
4. 확실하지 않으면 "현장 안내판 또는 지자체 공지를 확인해야 합니다"라고 말한다.
5. 답변은 한국어로 짧고 명확하게 작성한다.
"""


def extract_location_keyword(query: str) -> str | None:
    """
    질문에서 장소명을 간단히 추출한다.
    예:
    - 함덕해수욕장에서 취사 가능해? → 함덕해수욕장
    - 제주올레캠핑 근처 화장실 알려줘 → 제주올레캠핑
    """
    markers = [
        "에서",
        "근처",
        "주변",
        "인근",
        "쪽",
    ]

    for marker in markers:
        if marker in query:
            candidate = query.split(marker)[0].strip()
            if candidate:
                return candidate

    return None


def detect_facility_type(query: str) -> str | None:
    """
    질문에서 원하는 편의시설 종류를 추출한다.
    """
    if any(k in query for k in ["화장실", "공중화장실", "화장실도"]):
        return "restroom"

    if any(k in query for k in ["주차장", "주차"]):
        return "parking"

    if any(k in query for k in ["전기차", "충전소", "EV", "ev"]):
        return "ev"

    return "restroom"


def generate_answer(
    query: str,
    lat: float | None = None,
    lon: float | None = None,
    facility_type: str | None = None,
) -> dict:
    if not API_KEY:
        return {
            "query": query,
            "answer": "OPENAI_API_KEY가 설정되지 않았습니다. GPT 연동은 팀 API 키 설정 후 테스트하세요.",
            "location": None,
            "nearby_facilities": [],
        }

    resolved_location = None

    # lat/lon이 직접 안 들어오면 질문에서 장소명 추출 후 좌표 자동 탐색
    if lat is None or lon is None:
        location_keyword = extract_location_keyword(query)

        if location_keyword:
            resolved_location = resolve_location(location_keyword)

            if resolved_location:
                lat = resolved_location["lat"]
                lon = resolved_location["lon"]

    if facility_type is None:
        facility_type = detect_facility_type(query)

    context = build_gpt_context(
        query=query,
        lat=lat,
        lon=lon,
        facility_type=facility_type,
        radius_km=3,
        limit=5,
    )

    location_text = ""
    if resolved_location:
        location_text = f"""
인식된 장소:
- 이름: {resolved_location.get("name")}
- 종류: {resolved_location.get("category")}
- 위도: {resolved_location.get("lat")}
- 경도: {resolved_location.get("lon")}
- 주소: {resolved_location.get("road_addr") or resolved_location.get("lotno_addr") or ""}
"""

    user_prompt = f"""
사용자 질문:
{query}

{location_text}

검색된 근거:
{context["gpt_context"]}

위 근거만 사용해서 답변해줘.
"""

    client = OpenAI(api_key=API_KEY)

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    return {
        "query": query,
        "answer": response.choices[0].message.content,
        "location": resolved_location,
        "filters": context.get("filters"),
        "applied_filters": context.get("applied_filters"),
        "fallback_level": context.get("fallback_level"),
        "nearby_facilities": context.get("nearby_facilities", []),
    }


if __name__ == "__main__":
    result = generate_answer(
        query="함덕해수욕장에서 취사 가능해? 근처 화장실도 알려줘"
    )

    print("\n===== LOCATION =====")
    print(result["location"])

    print("\n===== GPT ANSWER =====")
    print(result["answer"])