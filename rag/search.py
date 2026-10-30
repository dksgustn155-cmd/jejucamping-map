import pickle
from typing import Optional

import faiss
from sentence_transformers import SentenceTransformer

from rag.config import EMBEDDING_MODEL_NAME, FAISS_INDEX_PATH, METADATA_PATH
from rag.query_classifier import classify_query


class RagSearcher:
    def __init__(self):
        if not FAISS_INDEX_PATH.exists():
            raise FileNotFoundError(f"FAISS index not found: {FAISS_INDEX_PATH}")

        if not METADATA_PATH.exists():
            raise FileNotFoundError(f"metadata not found: {METADATA_PATH}")

        print("[LOAD] FAISS index")
        self.index = faiss.read_index(str(FAISS_INDEX_PATH))

        print("[LOAD] metadata")
        with open(METADATA_PATH, "rb") as f:
            data = pickle.load(f)

        self.texts = data["texts"]
        self.metadata = data["metadata"]

        print(f"[LOAD] embedding model: {EMBEDDING_MODEL_NAME}")
        self.model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    def _match_filter(
        self,
        meta: dict,
        category: Optional[str] = None,
        region: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> bool:
        if category and meta.get("category") != category:
            return False

        if region:
            target = str(meta.get("region", "")) + " " + str(meta.get("address", ""))
            if region not in target:
                return False

        if tags:
            meta_tags = meta.get("feature_tags", [])
            if not any(tag in meta_tags for tag in tags):
                return False

        return True

    def search(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
        region: Optional[str] = None,
        tags: Optional[list[str]] = None,
        candidate_k: int = 500,
    ) -> list[dict]:
        query_embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype("float32")

        scores, indices = self.index.search(query_embedding, candidate_k)
        results = []

        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue

            meta = self.metadata[idx]

            if not self._match_filter(
                meta,
                category=category,
                region=region,
                tags=tags,
            ):
                continue

            results.append(
                {
                    "score": float(score),
                    "text": self.texts[idx],
                    "metadata": meta,
                }
            )

            if len(results) >= top_k:
                break

        return results


_searcher: Optional[RagSearcher] = None


def get_searcher() -> RagSearcher:
    global _searcher

    if _searcher is None:
        _searcher = RagSearcher()

    return _searcher


def search(
    query: str,
    top_k: int = 5,
    category: Optional[str] = None,
    region: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> list[dict]:
    searcher = get_searcher()

    return searcher.search(
        query=query,
        top_k=top_k,
        category=category,
        region=region,
        tags=tags,
        candidate_k=500,
    )


def smart_search(query: str, top_k: int = 5) -> dict:
    info = classify_query(query)
    searcher = get_searcher()

    attempts = [
        {
            "category": info["category"],
            "region": info["region"],
            "tags": info["tags"],
            "fallback_level": "category+region+tags",
        },
        {
            "category": info["category"],
            "region": info["region"],
            "tags": None,
            "fallback_level": "category+region",
        },
        {
            "category": info["category"],
            "region": None,
            "tags": None,
            "fallback_level": "category_only",
        },
        {
            "category": None,
            "region": None,
            "tags": None,
            "fallback_level": "no_filter",
        },
    ]

    for attempt in attempts:
        results = searcher.search(
            query=query,
            top_k=top_k,
            category=attempt["category"],
            region=attempt["region"],
            tags=attempt["tags"],
            candidate_k=1000,
        )

        if results:
            return {
                "query": query,
                "original_filters": {
                    "category": info["category"],
                    "region": info["region"],
                    "tags": info["tags"],
                },
                "applied_filters": {
                    "category": attempt["category"],
                    "region": attempt["region"],
                    "tags": attempt["tags"],
                },
                "fallback_level": attempt["fallback_level"],
                "results": results,
            }

    return {
        "query": query,
        "original_filters": {
            "category": info["category"],
            "region": info["region"],
            "tags": info["tags"],
        },
        "applied_filters": {
            "category": None,
            "region": None,
            "tags": None,
        },
        "fallback_level": "no_result",
        "results": [],
    }


if __name__ == "__main__":
    tests = [
        "공영주차장에서 차박해도 돼?",
        "노지 캠핑 장소 추천해줘",
        "제주 해수욕장에서 취사 가능해?",
        "담양 계곡에서 취사 돼?",
        "제주에서 아이와 갈 만한 캠핑장 추천해줘",
    ]

    for query in tests:
        print("\n" + "=" * 70)
        print("SMART SEARCH")
        print("질문:", query)
        print("=" * 70)

        result = smart_search(query, top_k=5)

        print("원본 필터:", result["original_filters"])
        print("적용 필터:", result["applied_filters"])
        print("Fallback:", result["fallback_level"])

        if not result["results"]:
            print("검색 결과 없음")
            continue

        for i, item in enumerate(result["results"], start=1):
            print(f"\n[{i}] score={item['score']:.4f}")
            print("metadata:", item["metadata"])
            print(item["text"][:500])