import pickle

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from rag.config import (
    EMBEDDING_MODEL_NAME,
    FAISS_INDEX_PATH,
    METADATA_PATH,
    VECTORSTORE_DIR,
)
from rag.document_builder import build_documents
from rag.loader import load_all_data


def build_faiss_index():
    VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] 데이터 로드 중...")
    records = load_all_data()

    print("[2/4] Document 생성 중...")
    docs = build_documents(records)
    texts = [doc.page_content for doc in docs]
    metadata = [doc.metadata for doc in docs]

    print(f"총 Document 수: {len(texts)}개")

    print(f"[3/4] 임베딩 모델 로드: {EMBEDDING_MODEL_NAME}")
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    print("[4/4] 임베딩 생성 중...")
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    embeddings = embeddings.astype("float32")

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    faiss.write_index(index, str(FAISS_INDEX_PATH))

    with open(METADATA_PATH, "wb") as f:
        pickle.dump(
            {
                "texts": texts,
                "metadata": metadata,
                "model_name": EMBEDDING_MODEL_NAME,
            },
            f,
        )

    print("\n✅ FAISS 인덱스 저장 완료")
    print(f"- index: {FAISS_INDEX_PATH}")
    print(f"- metadata: {METADATA_PATH}")
    print(f"- vectors: {index.ntotal}")


if __name__ == "__main__":
    build_faiss_index()