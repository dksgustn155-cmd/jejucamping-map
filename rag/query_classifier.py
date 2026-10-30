from typing import Optional


REGION_KEYWORDS = [
    "서울", "경기", "경기도", "인천", "강원", "강원도",
    "충북", "충청북도", "충남", "충청남도",
    "대전", "세종", "전북", "전라북도",
    "전남", "전라남도", "광주",
    "경북", "경상북도", "경남", "경상남도",
    "대구", "부산", "울산",
    "제주", "제주도", "서귀포", "제주시",

    # 시군구 보강
    "담양", "담양군", "양평", "포천", "김포",
]


def detect_region(query: str) -> Optional[str]:
    for region in REGION_KEYWORDS:
        if region in query:
            if region in ["제주도", "서귀포", "제주시"]:
                return "제주"
            if region == "경기":
                return "경기도"
            if region == "강원":
                return "강원도"
            if region == "충북":
                return "충청북도"
            if region == "충남":
                return "충청남도"
            if region == "전북":
                return "전라북도"
            if region == "전남":
                return "전라남도"
            if region == "경북":
                return "경상북도"
            if region == "경남":
                return "경상남도"
            if region == "담양군":
                return "담양"
            return region
    return None


def detect_category(query: str) -> Optional[str]:
    rule_keywords = [
        "차박해도", "차박 가능", "차박 가능한", "차박",
        "가능해", "가능한가", "해도 돼", "해도되", "돼?",
        "불법", "합법", "금지", "규정", "법", "단속",
        "노지", "공영주차장", "둔치", "하천변",
        "취사", "야영", "비박", "백패킹",
        "불멍", "화기", "모닥불", "장작", "텐트",
        "과태료", "벌금", "위반", "제한",
        "가능", "허용",
    ]

    festival_keywords = [
        "축제", "행사", "이벤트", "공연", "체험",
    ]

    tour_keywords = [
        "관광", "볼거리", "놀거리", "아이랑 갈 곳",
        "테마파크", "한옥", "촌캉스",
    ]

    camping_keywords = [
        "캠핑", "야영장", "글램핑", "카라반", "오토캠핑",
    ]

    if any(k in query for k in rule_keywords):
        return "rule"

    if any(k in query for k in festival_keywords):
        return "festival"

    if any(k in query for k in camping_keywords):
        return "camping"

    if any(k in query for k in tour_keywords):
        return "tour"

    return None


def detect_tags(query: str) -> list[str]:
    tags = []

    if any(k in query for k in ["아이", "어린이", "가족", "키즈", "유아", "초등"]):
        tags.append("아이 동반 추천")

    if any(k in query for k in ["강아지", "반려견", "애견", "반려동물", "펫"]):
        tags.append("반려동물 관련")

    if any(k in query for k in ["바다", "해변", "해수욕장", "오션뷰", "해안"]):
        tags.append("바다 근처")

    # "강아지"의 "강" 때문에 물가로 오탐되는 문제 방지
    if any(k in query for k in ["계곡", "강가", "강변", "하천", "물가", "호수", "저수지"]):
        tags.append("물가 근처")

    if any(k in query for k in ["전기", "전기 사용", "전기차"]):
        tags.append("전기 사용 가능")

    if any(k in query for k in ["샤워", "온수", "씻을 수"]):
        tags.append("샤워/온수 가능")

    if any(k in query for k in ["편의점", "마트", "매점"]):
        tags.append("매점/편의시설 있음")

    if "글램핑" in query:
        tags.append("글램핑")

    if "카라반" in query:
        tags.append("카라반")

    if any(k in query for k in ["오토캠핑", "자동차야영장"]):
        tags.append("오토캠핑")

    return tags


def classify_query(query: str) -> dict:
    return {
        "query": query,
        "category": detect_category(query),
        "region": detect_region(query),
        "tags": detect_tags(query),
    }


if __name__ == "__main__":
    test_queries = [
        "제주에서 아이와 갈 만한 캠핑장 추천해줘",
        "경기도에서 바다 근처 캠핑장 알려줘",
        "강아지랑 갈 수 있는 글램핑장 있어?",
        "공영주차장에서 차박해도 돼?",
        "비 오는 날 둔치주차장에서 자도 괜찮아?",
        "아이랑 갈 만한 테마파크 추천해줘",
        "담양 계곡에서 취사 돼?",
        "제주 해수욕장에서 취사 가능해?",
        "노지 캠핑 장소 추천해줘",
        "근처 화장실 알려줘",
        "근처 편의시설 알려줘",
        "근처 전기차충전시설 알려줘",
    ]

    for q in test_queries:
        print("\n질문:", q)
        print(classify_query(q))