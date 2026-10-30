# 숲으로 바다로 — 배포용 단일 이미지 (backend.server = main + chat 통합), RAG 포함
# 베이스는 Google 미러 사용 → Cloud Build 의 Docker Hub rate limit 회피
FROM mirror.gcr.io/library/python:3.12-slim

# faiss/torch 가 쓰는 OpenMP 런타임
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) 의존성 (torch/faiss/sentence-transformers 포함 — 규정 검색 RAG)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) 임베딩 모델을 빌드 시 미리 받아 이미지에 포함 → 콜드스타트 단축 + 런타임 HF 의존 제거
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('jhgan/ko-sroberta-multitask')"

# 3) 앱 소스 (rag/vectorstore 인덱스 포함, .dockerignore 로 .venv·docs 등 제외)
COPY . .

ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1

# Cloud Run 이 주입하는 PORT(기본 8080)로 리슨
CMD ["sh", "-c", "uvicorn backend.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
