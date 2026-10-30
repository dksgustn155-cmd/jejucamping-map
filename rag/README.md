# 🏕️ Camping Map RAG

차박/캠핑 사용자에게

- 캠핑장 추천
- 관광지 추천
- 법령/조례 안내
- 주변 편의시설(화장실 등)
- GPT 기반 자연어 답변

을 제공하는 RAG 시스템입니다.

---

# 프로젝트 구조

```
camping-map-main/

│
├── data/
│ ├── faiss.index
│ ├── metadata.pkl
│ ├── facilities.db
│ └── rules.json
│
├── rag/
│ ├── search.py
│ ├── query_classifier.py
│ ├── nearby.py
│ ├── location_resolver.py
│ ├── gpt_context.py
│ ├── gpt_answer.py
│ └── ...
│
└── README.md
```

---

# 시스템 구조

사용자 질문

↓

Query Classifier

↓

RAG Search

↓

Location Resolver

↓

Nearby Facility Search

↓

GPT Context 생성

↓

GPT Answer

---

# 주요 기능

## 1. Query Classifier

사용자의 질문을 분석하여

- category
- region
- tags

를 추출합니다.

예시

```
제주에서 아이와 갈 만한 캠핑장 추천

↓

{
 category : camping,
 region : 제주,
 tags : ["아이 동반 추천"]
}
```

---

## 2. Smart Search

FAISS 기반 의미검색 수행

지원

- 캠핑장
- 관광지
- 법령
- 조례

---

## 3. Fallback Search

검색 결과가 없으면

```
category + region + tag

↓

category + tag

↓

category

↓

전체 검색
```

순으로 자동 완화합니다.

---

## 4. Rule RAG

법령 및 조례 검색

예시

```
공영주차장에서 차박해도 돼?

↓

관련 법령 검색

↓

GPT 답변 생성
```

---

## 5. Location Resolver

질문에서 장소명을 추출하여

좌표(lat/lon)를 자동 검색합니다.

예시

```
함덕해수욕장

↓

lat
lon
```

---

## 6. Nearby Search

좌표를 이용하여

SQLite DB에서

근처

- 화장실
- 편의시설

검색

---

## 7. GPT Context

RAG 결과 +

Nearby 결과를

GPT Prompt로 생성합니다.

---

## 8. GPT Answer

GPT가

- 규정 안내
- 근처 화장실
- 캠핑장 추천

을 자연어로 생성합니다.

---

# 실행 방법

## 1.

```
pip install -r requirements.txt
```

## 2.

프로젝트 루트에

```
.env
```

생성

```
OPENAI_API_KEY=YOUR_API_KEY
```

## 3.

```
python -m rag.gpt_answer
```

---

# 예시

입력

```
함덕해수욕장에서 취사 가능해?
근처 화장실도 알려줘
```

출력

```
- 취사는 지정 장소에서만 가능합니다.

- 근처 화장실

① 서우봉해변야영장

② 서우봉 관리사무소

...
```

---

# 사용 데이터

- Camping Data
- Tourist Spot Data
- Rule / Law Data
- Nearby Facility Database(SQLite)

---

# 사용 기술

- Python
- FAISS
- SentenceTransformer
- SQLite
- OpenAI GPT
- RAG
- dotenv

---

# 향후 개선사항

- 장소명 인식 정확도 향상
- 다중 장소 인식
- 지도 API 연동
- 실시간 편의시설 검색
- FastAPI 연동
- Frontend 연동

---

# 개발 담당

RAG Pipeline

- Query Classifier
- Smart Search
- Rule RAG
- Fallback Search
- Location Resolver
- Nearby Search
- GPT Context
- GPT Answer
