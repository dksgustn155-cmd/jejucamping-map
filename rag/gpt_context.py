from rag.search import smart_search
from rag.nearby import find_nearby_facilities


def is_same_region(target_region: str | None, meta: dict) -> bool:
    if not target_region:
        return True

    meta_region = str(meta.get("region", "") or "")
    local_gov = str(meta.get("local_gov", "") or "")

    # 전국 공통 법령/QA는 유지
    if not meta_region and not local_gov:
        return True

    # 같은 지역이면 유지
    if target_region in meta_region or target_region in local_gov:
        return True

    return False


def build_gpt_context(
    query: str,
    lat: float | None = None,
    lon: float | None = None,
    facility_type: str | None = "restroom",
    radius_km: float = 3.0,
    limit: int = 5,
) -> dict:
    rag_result = smart_search(query, top_k=5)

    target_region = None
    if rag_result.get("original_filters"):
        target_region = rag_result["original_filters"].get("region")

    filtered_results = []
    for item in rag_result["results"]:
        meta = item["metadata"]
        if is_same_region(target_region, meta):
            filtered_results.append(item)

    rag_contexts = []
    for i, item in enumerate(filtered_results, start=1):
        meta = item["metadata"]

        rag_contexts.append(
            f"""
[검색결과 {i}]
점수: {item["score"]:.4f}
이름: {meta.get("name", "")}
카테고리: {meta.get("category", "")}
지역: {meta.get("region", "")}
주소: {meta.get("address", "")}
태그: {meta.get("feature_tags", [])}
근거:
{item["text"]}
""".strip()
        )

    nearby_facilities = []

    if lat is not None and lon is not None:
        nearby_facilities = find_nearby_facilities(
            lat=lat,
            lon=lon,
            facility_type=facility_type,
            radius_km=radius_km,
            limit=limit,
        )

    nearby_contexts = []

    for i, item in enumerate(nearby_facilities, start=1):
        nearby_contexts.append(
            f"""
[근처 편의시설 {i}]
종류: {item.get("category", "")}
이름: {item.get("name", "")}
거리: {item.get("distance_km", "")}km
주소: {item.get("road_addr") or item.get("lotno_addr") or ""}
운영시간: {item.get("open_hours", "")}
전화번호: {item.get("tel", "")}
추가정보: {item.get("extra", "")}
""".strip()
        )

    return {
        "query": query,
        "filters": rag_result.get("original_filters"),
        "applied_filters": rag_result.get("applied_filters"),
        "fallback_level": rag_result.get("fallback_level"),
        "filtered_count": len(filtered_results),
        "rag_context": "\n\n".join(rag_contexts),
        "nearby_facilities": nearby_facilities,
        "nearby_context": "\n\n".join(nearby_contexts),
        "gpt_context": "\n\n".join(
            [
                "[RAG 검색 근거]",
                "\n\n".join(rag_contexts),
                "[근처 편의시설]",
                "\n\n".join(nearby_contexts),
            ]
        ),
    }


if __name__ == "__main__":
    result = build_gpt_context(
        query="제주 해수욕장에서 취사 가능해? 근처 화장실도 알려줘",
        lat=33.4996,
        lon=126.5312,
        facility_type="restroom",
        radius_km=3,
        limit=5,
    )

    print("질문:", result["query"])
    print("필터:", result["filters"])
    print("적용 필터:", result["applied_filters"])
    print("Fallback:", result["fallback_level"])
    print("필터링 후 RAG 결과 수:", result["filtered_count"])

    print("\n===== GPT CONTEXT =====")
    print(result["gpt_context"][:5000])