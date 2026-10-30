# 임시 추천 스코어링 설계 (A — 프론트 임시 엔진)

> 작성: A (2026-07-08) · 상태: **P1 설계 — 컨펌 후 P2 구현**
> 상위 설계: [recommendation-pipeline.md](recommendation-pipeline.md) (팀 확정 가중치표 준수)
> 원칙: C의 `/api/recommend`(#13) 완성 전까지의 **임시(temporary) 엔진**. 출력 형식·가중치를
> 서버 설계와 동일하게 맞춰, C 완성 시 **엔진 호출 1곳만 교체**하면 되도록 한다.

---

## 1. 위치·전환 경로 (확정)

- 구현 위치: **frontend JS** (`frontend/scoring.js` 신규) — A 담당 폴더, C와 역할 충돌 없음
- 데이터 소스: 기존 실서비스 API만 사용 (`/api/facilities` · `/api/ev-status` · `/api/zone-check`)
- 전환(P5): `recommend(question, conds)` 호출부 1곳을 C의 `POST /api/recommend`로 교체 → 프론트 UI 무수정

## 2. 후보군 (recommendation-pipeline §3 준수)

| 후보군 | 조건 | 비고 |
|---|---|---|
| 공영주차장 `parking_public` | region bbox 내 | "주차+화장실 조합" 우회 프레이밍 |
| 야영장 `camping` | region bbox 내 | 합법 대안 — 동점 시 우선 |
| 둔치주차장 `parking` | region bbox 내 | 침수등급 감점 적용(V6) |

- region: 시나리오 질문의 지역 키워드 → bbox (기존 `MOCK_REGIONS` 확장: 서귀포·제주·애월·협재·담양 + 추가 용이한 사전 구조)
- 후보 수 상한: bbox당 카테고리별 최대 300 (API limit 내), 시설 조회는 카테고리별 1회 fetch

## 3. Validation Check 11종 (가중치 = 팀 확정표 + V11 신규)

| # | 체크 | 판정 | 점수 | 계산 방법 |
|---|---|---|---|---|
| V1 | 🚻 화장실 근접 | ≤150 / ≤300 / ≤500m | +20 / +15 / +8 | 후보↔restroom 하버사인 최근접 |
| V2 | 🕒 화장실 24시간 | V1 최근접 화장실 open_hours에 "24시간·상시·연중" | +5 | 문자열 판정 |
| V3 | 🌊 바다 뷰 | 해수욕장 ≤500m / ≤1km | +15 / +10 | 후보↔beach 최근접. **질문 view=바다일 때만** |
| V4 | 🏞️ 숲·계곡 뷰 | camping 후보의 `extra.loc_type`이 질문 view(계곡·숲·호수)와 일치 | +15 | camping 후보 한정 |
| V5 | ⚡ EV | **질문 ev=true일 때만**: EV충전소 ≤1km (+15) / 그중 실시간 급속>0 (+5) | +15/+5 | ev_charger 최근접 + `/api/ev-status` 조인 |
| V6 | ⚠️ 침수 위험 | 둔치 후보 `risk_grade` 1 / 2등급 | −20 / −10 | parking 후보 한정 |
| V7 | 📹 안전 CCTV | ≤500m | +3 | cctv 최근접 |
| V8 | 💊 심야약국 | ≤3km | +3 | pharmacy 최근접 |
| V9 | ♻️ 클린하우스 | ≤500m | +2 | cleanhouse 최근접 |
| V10 | 🎉 혼잡(축제) | **오늘이 개최기간 중**인 festival ≤1km | −8 | `extra.start ≤ 오늘 ≤ extra.end` + 거리 |
| V11 | 🚫 자연공원 | `/api/zone-check` 판정 구역 내 | **−50** | **팀 결정(7/8): 제외 아닌 큰 감점** — 목록 하위에 남겨 "왜 안 되는지" 투명하게 표시. 리포트에 굵은 경고 + 법 조항 |
| V12 | 🏗️ 구조(차박 가능성) | 주차 **건축물** 판정 | **제외 / −15** | **신설(7/8 피드백)**: 이름·유형에 빌딩·타워·기계식·지하·옥내·옥상 → **후보 하드 제외**(물리적으로 차박 불가). `type=노상`(도로변)은 −15 감점+⚠️ 표시. 제외 건수는 답변에 "(차박 불가 N곳 제외)" 로 투명 공개 |

- 점수 범위: 합산 후 `0~100` clamp. 기본점 30 (후보로 선정된 것 자체의 기본 접근성)
- 제외 항목(P1 명시): 인기 보정(주간 배치 산출물 — C/D), 아이 동반 테마파크(jsonl 미서빙), 호우예보 감점(기상청 미연동 — C의 beach-timing 이후)

## 4. 가중치 파일 (초기값 — 서버 `data/score_weights.json`과 동일 형식)

```json
{
  "base": 30,
  "restroom":   { "d150": 20, "d300": 15, "d500": 8 },
  "restroom_24h": 5,
  "sea_view":   { "d500": 15, "d1000": 10 },
  "nature_view": 15,
  "ev":         { "d1000": 15, "fast_bonus": 5 },
  "flood":      { "grade1": -20, "grade2": -10 },
  "cctv_500": 3,
  "pharmacy_3000": 3,
  "cleanhouse_500": 2,
  "festival_active_1000": -8,
  "natural_park": -50
}
```
- P2에선 `frontend/scoring.js` 상수로 시작 → C의 주간 배치가 갱신하는 `score_weights.json`을 서빙하게 되면 fetch로 교체

## 5. 조건 파싱 (임시 — GPT 파싱 전 규칙 기반)

시나리오 페이지가 이미 확보한 신호를 최대 활용:

| 조건 | 출처 |
|---|---|
| region | 질문 키워드 → REGIONS 사전 (미인식 시 기본 서귀포 + 리포트에 "지역 미인식" 표시) |
| ev | 시나리오에서 `ev_charger` 체크 **또는** 질문에 전기차/충전 |
| view=바다 | 시나리오 `beach` 체크 또는 질문에 바다/해변/해수욕 |
| view=숲·계곡 | 질문에 숲/계곡/호수 |
| 야간약국 필요 | 시나리오 `pharmacy` 체크 → V8 가중 ×2 |

→ C의 GPT 파싱(`parsed` json)이 오면 이 규칙층은 폴백으로 강등

## 6. 출력 스키마 (C 계약 확장안 — api-chat-contract.md에 병합 예정)

```json
{
  "reply": "…",
  "map": {
    "bbox": [...], "layers": [...],
    "pins": [{
      "id": "parking_public:…", "lat": 33.25, "lon": 126.56,
      "label": "추천 1위", "item": { … },
      "score": 78,
      "why": [
        { "check": "restroom", "pass": true,  "detail": "화장실 120m",        "delta": 20 },
        { "check": "restroom_24h", "pass": true, "detail": "24시간 개방",      "delta": 5 },
        { "check": "sea_view", "pass": true,  "detail": "해수욕장 400m",       "delta": 15 },
        { "check": "ev", "pass": true,        "detail": "급속 2대 · 850m",     "delta": 20 },
        { "check": "festival", "pass": false, "detail": "축제 개최중 600m",    "delta": -8 },
        { "check": "natural_park", "pass": true, "detail": "자연공원 구역 아님", "delta": 0 }
      ]
    }]
  }
}
```
- `why[]`가 곧 **적합성 리포트** — pass/detail/delta 3요소로 어떤 UI든 렌더 가능
- 👍👎 로그(P4): `results`에 `[{id, score}]` 포함 → chat_logs 학습 루프(주간 배치) 신호와 호환

## 7. UI 시안 (P3)

**추천 핀**: 금색 핀 + 점수 뱃지 (`78`), 상위 3~5개. V11 감점 후보는 회색 핀 + 🚫
**표출 정책(7/8 피드백)**: 추천 결과 표시 시 **카테고리 레이어 전체 OFF — 추천 핀만 지도에 표출**, 화면은 핀 범위로 맞춤(fit). 다른 시설은 유저가 칩으로 직접 켤 때만.
**상세카드 적합성 리포트**:
```
⭐ 차박 적합도 78 / 100
✅ 화장실 120m               +20
✅ 24시간 개방                +5
✅ 해수욕장 400m (바다 뷰)     +15
✅ EV 급속 2대 · 850m        +20
⚠️ 축제 개최중 600m           −8
🚫 자연공원 아님 (통과)
```
**배너**: 1위 요약 "1위 ○○(78점) — 화장실 120m·바다뷰·EV" + 👍👎

## 8. 단계·컨펌 게이트

- [x] **P1** 설계 문서 (이 문서) — ✅ 7/8 승인
- [x] **P2** `frontend/scoring.js` 엔진 — ✅ 7/8 (서귀포 ev=true 62후보 251ms 실측)
- [x] **P3** UI — ✅ 7/8 (점수 뱃지 핀 + 적합성 리포트 + 리스트 버튼 + 근거 마커·점선, V12·핀만 표출 피드백 반영)
- [x] **P4** 👍👎 로그 확장(`results`) + 계약 문서 병합 — ✅ 7/8 (C 공지 필요)
- [x] **P5** 전환 가이드 — 아래 §9

## 9-1. ✅ 서버 구현 완료 (7/9, A → C 인수 대상) — `backend/recommend.py`

프론트 임시 엔진을 서버로 이관. **기존 백엔드 자산 재사용**:

| 구성 | 재사용 |
|---|---|
| V11 자연공원 | main.py `_zone_of()` 함수 직접 호출 — **전 후보 판정** (프론트 2-pass 한계 해소) |
| V5 EV 실시간 | main.py `_ev_status_now()` (3분 캐시 공용) |
| 거리 | B의 `rag/nearby.py haversine_km` + 위도 이분탐색 윈도우 (<0.5s) |
| 가중치 | **`data/score_weights.json` 로더** — 주간 배치(§5) 인터페이스 완성 |
| reply | **gpt-5-mini** — 점수·거리 데이터만 인용 (pipeline §7), 실패 시 템플릿 폴백 |

- 프론트는 `/api/recommend` 실패 시에만 `scoring.js` 폴백 (참조 구현으로 유지)
- main.py 배선: `_recommend.configure(zone_lookup, ev_status_getter)` + `include_router` (순환 import 방지)

## 9. C `/api/recommend` 전환 가이드 (P5)

C가 서버 점수화(#13)를 완성하면:

1. **응답 형식**: `api-chat-contract.md` §1의 `pins[].score / why[] / ref` 그대로 생성
   (규칙·가중치는 이 문서 V1~V12 — 특히 **V12 구조 하드 제외**를 서버에서도 유지할 것)
2. **프론트 전환**: `frontend/app.js`의 `MOCK_CHAT = false` 한 줄 → `tempRecommend`(임시 엔진) 호출이
   사라지고 `/api/chat` 응답만 사용. UI(핀·리스트·리포트·근거마커·피드백)는 무수정
3. **정리(선택)**: 안정화 후 `frontend/scoring.js`와 index.html의 스크립트 태그 제거
4. **가중치 파일**: 서버는 `data/score_weights.json` 로드 — 초기값은 이 문서 §4 (주간 배치가 갱신)
