# 협업 가이드

4명이 며칠 안에 함께 만드는 프로젝트입니다. 규칙은 **가볍게, 충돌 없이**가 목표.

## 🔑 비밀 파일·데이터 (절대 git에 올리지 말 것)

`.gitignore`로 이미 제외돼 있지만 다시 강조:

| 파일 | 공유 방법 |
|---|---|
| `.env` (API 키) | **카톡 DM**으로 팀원 D가 전달. 절대 커밋 금지 |
| `data/facilities.db` (**9개 카테고리 6.8만 건**, 둔치주차장·행사 포함) | **구글드라이브 링크**로 공유 → `data/`에 넣기. 데이터 갱신 시 팀원 D가 새 링크 공지 |
| `*.csv`, `data/raw/*` | 원본 데이터(RAG용 `festival.jsonl` 포함). 필요 시 드라이브 공유 |

> 실수로 `.env`를 커밋하면 → 바로 카톡방에 알리고 키 재발급. GitHub에 올라간 키는 공개된 것으로 간주.

## 🗂️ 역할 = 폴더로 분리 (충돌 최소화) — 2026-07-06 재배분

데이터 수집·파이프라인·CI가 완료되어, **남은 개발은 A·B·C 세 명이 진행**합니다.
팀원 D는 일정 점검(스탠드업 진행·TODO 관리)과 발표 자료를 담당하고, 키·DB 공유 창구 역할을 계속합니다.

| 팀원 | 역할 | 주 작업 폴더 | 남은 핵심 작업 |
|---|---|---|---|
| A | 프론트 & 통합 | `frontend/` | 신규 레이어 토글 5종(#10), 정보창 다듬기, 위험등급 확인(#11), 통합 데모 |
| B | AI / RAG | `rag/` (신규) | 지식베이스→임베딩→FAISS 검색(#3) + **축제 GPT 추출**(#12) |
| C | 추천 백엔드 + 배포 | `backend/`, `Dockerfile` | `/api/chat`(#5)·`/api/beach-timing`(#6) + **Cloud Run 배포·CD**(#8) |
| D | 일정 · 발표 | `docs/`, `TODO.md` | 일정 점검, 발표 자료·시나리오, GPT 키 수령(7/8)·`.env` 배포 |

- **B+C 페어** (RAG 검색 모듈 ↔ `/api/chat` 연결 — 인터페이스 먼저 합의!)
- **A는 D에게** 데이터 질문 (extra 필드 구조 등은 `docs/data-sources.md` 먼저 확인)
- 남의 폴더를 고쳐야 하면 **카톡으로 먼저 한마디** ("app.js 잠깐 만질게요")
- 공용 파일(`README`, `TODO.md`, `requirements.txt`)은 수정 후 바로 push + 카톡 공지

## 🔀 Git 워크플로

```
main            항상 작동하는 버전 (직접 push 금지, PR로만)
 ├─ feat/ui-jeju-layer   팀원 A (프론트)
 ├─ feat/rag             팀원 B (RAG + 축제 GPT)
 └─ feat/chat-api        팀원 C (백엔드 + 배포)
```

작업 순서:
```bash
git checkout main && git pull        # 1. 항상 최신 main에서 시작
git checkout -b feat/내작업          # 2. 내 브랜치 생성
# ... 작업 ...
git add . && git commit -m "설명"    # 3. 작은 단위로 자주 커밋
git push -u origin feat/내작업       # 4. 푸시 후 GitHub에서 PR 생성
```
- PR은 **작게, 자주**. 서로 슥 보고 merge.
- **규칙 2개만**: ① push 전 `git pull` ② `.env`·`data/` 커밋 금지

## 커밋 메시지 (간단히)
```
feat: 채팅 추천 API 추가
fix: 로드뷰 없을 때 안내 처리
docs: README 온보딩 보완
data: 해수욕장 수집 스크립트
```

## 🗓️ 소통 (카톡)

- **매일 15분 스탠드업** (카톡 or 통화): 어제 한 것 / 오늘 할 것 / 막힌 것
- 막히면 30분 이상 혼자 붙잡지 말고 **바로 카톡 + 화면공유**
- 진행 상황은 `TODO.md` 체크박스로 표시하고 커밋

## 실행 확인 (PR 전 최소 체크)
- [ ] `uvicorn backend.main:app --port 8000` 정상 실행되는지
- [ ] 브라우저 localhost:8000에서 지도 뜨는지
- [ ] `.env` / `data/` 가 커밋에 안 들어갔는지 (`git status`로 확인)
- [ ] **PR의 CI(GitHub Actions)가 초록 ✅ 인지** — 빨강이면 merge 금지, 로그 보고 수정

## 🤖 CI (자동 검사)
push·PR마다 `.github/workflows/ci.yml`이 자동 실행: 문법검사 + 백엔드 import + **키 유출 검사**.
- PR에 ❌ 뜨면 → Actions 탭에서 로그 확인 후 고치고 다시 push
- 키 유출 검사에 걸리면 → 키를 `.env`로 옮기고, 공개 레포이므로 **해당 키 재발급**
