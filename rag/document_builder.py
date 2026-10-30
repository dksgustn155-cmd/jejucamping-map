from langchain_core.documents import Document

from rag.loader import load_all_data


def get_value(record: dict, keys: list[str], default: str = "") -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return str(value).strip()
    return default


def infer_category(record: dict) -> str:
    category = record.get("category")
    if category:
        return str(category)

    # 규정/법령/조례/고시 데이터
    if record.get("type") in ["law", "qa", "ordinance", "notice"]:
        return "rule"

    if (
        record.get("법령명")
        or record.get("조례명")
        or record.get("고시명")
        or record.get("원문")
        or record.get("요약")
        or record.get("근거")
        or record.get("위반시")
    ):
        return "rule"

    # 캠핑 데이터
    if record.get("facltNm"):
        return "camping"

    # 축제/행사 데이터
    if record.get("title"):
        return "festival"

    # 관광 데이터
    if record.get("사업장명") or record.get("관광지명"):
        return "tour"

    return "unknown"


def normalize_lat(record: dict):
    return record.get("lat") or record.get("mapY") or record.get("위도")


def normalize_lon(record: dict):
    return record.get("lon") or record.get("lng") or record.get("mapX") or record.get("경도")


def has_keyword(text: str, keywords: list[str]) -> bool:
    text = text or ""
    return any(k in text for k in keywords)


def build_feature_tags(record: dict) -> list[str]:
    raw_text = " ".join(str(v) for v in record.values() if v not in (None, ""))

    tags = []

    if has_keyword(raw_text, ["놀이터", "트렘폴린", "물놀이장", "키즈", "어린이", "가족"]):
        tags.append("아이 동반 추천")

    if has_keyword(raw_text, ["반려", "애견", "반려견", "펫", "강아지"]):
        tags.append("반려동물 관련")

    if has_keyword(raw_text, ["해변", "바다", "해수욕장", "오션", "해안"]):
        tags.append("바다 근처")

    if has_keyword(raw_text, ["계곡", "강가", "강변", "하천", "호수", "저수지", "물가"]):
        tags.append("물가 근처")

    if has_keyword(raw_text, ["전기"]):
        tags.append("전기 사용 가능")

    if has_keyword(raw_text, ["온수", "샤워"]):
        tags.append("샤워/온수 가능")

    if has_keyword(raw_text, ["편의점", "마트", "매점"]):
        tags.append("매점/편의시설 있음")

    if has_keyword(raw_text, ["글램핑"]):
        tags.append("글램핑")

    if has_keyword(raw_text, ["카라반"]):
        tags.append("카라반")

    if has_keyword(raw_text, ["오토캠핑", "자동차야영장"]):
        tags.append("오토캠핑")

    return tags


def build_text(record: dict) -> str:
    category = infer_category(record)

    name = get_value(record, [
        "name", "facltNm", "title", "사업장명", "관광지명", "콘텐츠명",
        "법령명", "조례명", "고시명", "q"
    ])

    address = get_value(record, [
        "address", "addr1", "addr2", "주소", "소재지도로명주소", "소재지지번주소"
    ])

    region = get_value(record, [
        "region", "doNm", "sigunguNm", "시도명", "시군구명",
        "지자체", "지역"
    ])

    intro = get_value(record, [
        "intro", "lineIntro", "description", "content", "overview", "소개", "설명", "content_text",
        "요약", "a", "원문"
    ])

    facilities = get_value(record, [
        "sbrsCl", "posblFcltyCl", "facilities", "편의시설", "부대시설", "featureNm"
    ])

    camping_type = get_value(record, [
        "induty", "lctCl", "themaEnvrnCl", "장소유형", "분야"
    ])

    operation = get_value(record, [
        "operPdCl", "operDeCl", "open_time", "운영시간", "개방시간", "시행일"
    ])

    homepage = get_value(record, [
        "homepage", "홈페이지", "url", "link", "출처", "source"
    ])

    # 규정/법령 전용 필드
    law_type = get_value(record, ["type"])
    law_name = get_value(record, ["법령명", "조례명", "고시명"])
    article = get_value(record, ["조항", "조문", "조"])
    place_type = get_value(record, ["장소유형", "장소", "대상"])
    summary = get_value(record, ["요약"])
    violation = get_value(record, ["위반시", "과태료", "벌칙"])
    source = get_value(record, ["출처", "source", "url"])
    question = get_value(record, ["q", "question"])
    answer = get_value(record, ["a", "answer"])
    basis = get_value(record, ["근거"])
    local_gov = get_value(record, ["지자체"])
    ordinance_field = get_value(record, ["분야"])
    regulatory = get_value(record, ["규제형"])

    feature_tags = build_feature_tags(record)

    text_parts = [
        f"카테고리: {category}",
        f"이름: {name}",
        f"지역: {region}",
        f"주소: {address}",
        f"캠핑/관광 유형: {camping_type}",
        f"소개: {intro}",
        f"시설/특징: {facilities}",
        f"운영정보: {operation}",
        f"추천 태그: {', '.join(feature_tags)}",
        f"홈페이지: {homepage}",

        # 규정/법령 RAG 검색용
        f"규정 타입: {law_type}",
        f"법령/조례/고시명: {law_name}",
        f"지자체: {local_gov}",
        f"분야: {ordinance_field}",
        f"규제형: {regulatory}",
        f"조항: {article}",
        f"장소유형: {place_type}",
        f"질문: {question}",
        f"답변: {answer}",
        f"요약: {summary}",
        f"근거: {basis}",
        f"위반시: {violation}",
        f"출처: {source}",
    ]

    return "\n".join([part for part in text_parts if not part.endswith(": ")])


def build_documents(records: list[dict]) -> list[Document]:
    documents = []

    for i, record in enumerate(records):
        text = build_text(record)

        if len(text.strip()) < 20:
            continue

        category = infer_category(record)

        metadata = {
            "source_index": i,
            "category": category,
            "name": get_value(record, [
                "name", "facltNm", "title", "사업장명", "관광지명",
                "법령명", "조례명", "고시명", "q"
            ]),
            "address": get_value(record, [
                "address", "addr1", "주소", "소재지도로명주소", "소재지지번주소"
            ]),
            "region": get_value(record, [
                "region", "doNm", "sigunguNm", "시도명", "시군구명",
                "지자체", "지역"
            ]),
            "lat": normalize_lat(record),
            "lon": normalize_lon(record),
            "feature_tags": build_feature_tags(record),

            # 규정 데이터 메타데이터
            "rule_type": get_value(record, ["type"]),
            "law_name": get_value(record, ["법령명", "조례명", "고시명"]),
            "article": get_value(record, ["조항", "조문", "조"]),
            "place_type": get_value(record, ["장소유형", "장소", "대상"]),
            "violation": get_value(record, ["위반시", "과태료", "벌칙"]),
            "source": get_value(record, ["출처", "source", "url"]),
            "local_gov": get_value(record, ["지자체"]),
            "regulatory": get_value(record, ["규제형"]),
        }

        documents.append(Document(page_content=text, metadata=metadata))

    return documents


if __name__ == "__main__":
    records = load_all_data()
    docs = build_documents(records)

    print(f"\n생성된 Document 수: {len(docs)}개")

    rule_docs = [doc for doc in docs if doc.metadata.get("category") == "rule"]
    camping_docs = [doc for doc in docs if doc.metadata.get("category") == "camping"]

    print(f"캠핑 Document 수: {len(camping_docs)}개")
    print(f"규정/법령 Document 수: {len(rule_docs)}개")

    print("\n--- 샘플 Document ---")
    print(docs[0].page_content)
    print(docs[0].metadata)

    if rule_docs:
        print("\n--- 규정/법령 샘플 Document ---")
        print(rule_docs[0].page_content[:1000])
        print(rule_docs[0].metadata)

    print("\n--- 아이 동반 태그 샘플 ---")
    kid_docs = [
        doc for doc in docs
        if "아이 동반 추천" in doc.metadata.get("feature_tags", [])
    ]

    print(f"아이 동반 추천 문서 수: {len(kid_docs)}개")

    if kid_docs:
        print(kid_docs[0].page_content)
        print(kid_docs[0].metadata)