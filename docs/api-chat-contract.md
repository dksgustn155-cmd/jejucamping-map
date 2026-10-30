# /api/chat ↔ 프론트 지도 연동 계약 (A ↔ C 합의용)

> 작성: A (2026-07-07) · 상태: **제안 — C 확인 후 확정**
> 프론트는 이 규격의 mock으로 UI를 먼저 구현해 둠 (`frontend/app.js`의 `mockChat()`).
> C가 실제 `/api/chat`을 이 규격으로 응답하면 **프론트 수정 없이** 그대로 연결됨.

> 🔀 **역할 분리(7/9 확정)**: `/api/chat` = **대화**(§4 멀티턴 — 되묻기·요약·컨펌),
> `/api/recommend` = **추천 생성**(§1 — 시설 확인 페이지의 [추천 받기]가 호출, pins·score·why 반환).
> 프론트는 §1 응답을 `/api/recommend`에서 기대하며, 없으면 임시 스코어링 엔진으로 폴백.

## 1. POST /api/recommend (시설 확인 → 추천 생성, C #13)

### Request
```json
{
  "message": "서귀포 바다 보이는 조용한 차박지 알려줘. 화장실 가까우면 좋겠어",
  "categories": ["parking_public", "restroom", "camping", "beach", "cctv"]
}
```
| 필드 | 필수 | 설명 |
|---|---|---|
| `message` | ✅ | 사용자 질문 원문 |
| `categories` | ✅ (7/8 추가) | **시나리오 페이지에서 유저가 확정한 필요 시설** — 추천 후보·점수화에 활용 권장. 응답의 `map.layers`를 생략하면 프론트가 이 목록으로 레이어를 켬 |

> User flow(7/8 확정): 메인 검색 입력 → **시나리오 페이지**(질문 수정 + 시설 11종 체크, 키워드 자동 제안) → [추천 받기] → 지도 결과.

### Response 200 (7/8 확장 — 스코어링 필드 포함, `docs/scoring-design.md`)
```json
{
  "reply": "📊 서귀포 후보 54곳을 조건 검증해 상위 5곳을 골랐어요. (차박 불가 8곳 제외) …",
  "map": {
    "bbox": [33.23, 126.54, 33.29, 126.61],
    "layers": [],
    "pins": [
      {
        "id": "camping:101857",
        "lat": 33.2461, "lon": 126.5653,
        "label": "1위 · 75점",
        "item": { "...": "/api/facilities 아이템과 동일 구조 (핀 클릭 시 상세카드)" },
        "score": 75,
        "why": [
          { "check": "restroom", "pass": true, "detail": "화장실 88m (보목동어촌계)", "delta": 20,
            "ref": { "id": "restroom:…", "category": "restroom", "name": "보목동어촌계",
                     "lat": 33.245, "lon": 126.566, "d": 88, "item": { "...": "시설 전체" } } },
          { "check": "ev", "pass": true, "detail": "EV충전소 307m", "delta": 15, "ref": { "...": "…" } },
          { "check": "natural_park", "pass": true, "detail": "자연공원 구역 아님", "delta": 0 }
        ]
      }
    ]
  }
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `reply` | ✅ | 사용자에게 보여줄 답변 텍스트 (개행 `\n` 허용) |
| `map` | ❌ | 없으면 지도 전환 안 함 (일반 문답) |
| `map.bbox` | ❌ | `[sw_lat, sw_lng, ne_lat, ne_lng]` — 지도를 이 영역으로 이동 (추천 시엔 핀 범위 권장) |
| `map.layers` | ❌ | 켤 레이어 목록 (**이 목록으로 정확히 세팅**). **빈 배열 `[]` = 핀만 표출**(추천 모드 권장, 7/8). 미지정(생략) 시 프론트가 유저 선택 시설로 채움 |
| `map.pins` | ❌ | 추천 핀. `item` 있으면 클릭 시 상세카드 |
| `pins[].score` | ❌ | 차박 적합도 0~100 — 있으면 **점수 뱃지 핀 + 리스트 버튼 + 적합성 리포트** 렌더 |
| `pins[].why[]` | ❌ | 검증 근거: `{check, pass, detail, delta, ref?}` — 리포트 체크리스트로 표시 |
| `why[].ref` | ❌ | 근거 시설 `{id, category, name, lat, lon, d(m), item}` — 지도에 **근거 마커+점선**으로 표시, 클릭 시 그 시설 상세 |

> 🔎 **현재 프론트 임시 엔진(`frontend/scoring.js`)이 정확히 이 형식으로 생성 중** — C가 같은 형식으로
> 응답하면 UI(핀·리스트·리포트·근거마커)가 무수정으로 동작. 검증 규칙·가중치는 `docs/scoring-design.md` V1~V12.

## 2. POST /api/feedback (추천 로그 — 질문 학습 루프용, #13)

```json
{
  "question": "원래 질문", "reply": "봇 답변", "vote": 1, "pin_id": null,
  "results": [ { "id": "camping:101857", "score": 75 }, { "id": "parking_public:…", "score": 75 } ]
}
```
- `vote`: 👍 = `1`, 👎 = `-1`
- `pin_id`: 특정 핀에 대한 피드백이면 그 id (전체 답변 피드백이면 null)
- `results` (7/8 추가): 이번 추천 상위 후보의 id·점수 — **chat_logs.results 컬럼에 그대로 적재**하면
  주간 배치(가중치 튜닝·인기 보정)의 입력이 됨 (recommendation-pipeline.md §5)
- 응답: `202` (본문 무관). **엔드포인트 없어도 프론트는 조용히 무시** (UI 막힘 없음)

## 3. 프론트 동작 (구현됨)
1. 답변 수신 → 채팅에 표시 → `map` 있으면 0.9초 후 지도 화면 전환
2. `bbox`로 이동 + `layers` 세팅(칩/체크박스 동기화) + 금색 번호 핀 표시
3. 지도 하단 **답변 배너** (reply 요약 + 👍👎 + 닫기)
4. 핀 클릭 → 상세카드 (모바일: 바텀시트)

## 4. 멀티턴 대화 확장 (제안 v1 — 7/9, A → B·C 합의 요청)

> User flow 개편: 메인 채팅에서 **AI가 조건을 되물어 충분히 대화** → 조건 요약 →
> **유저 컨펌** → 시설 확인 페이지 진입. "무엇을 몇 번 묻는지"(대화 정책)는 B·C가 결정하고,
> 프론트는 아래 `next` 필드만 보고 렌더링한다 — **정책이 바뀌어도 프론트 무수정**.

### Request (기존 + `history`)
```json
{
  "message": "바다 보이는 데서 차박하고 싶어",
  "history": [
    { "role": "user", "content": "이전 사용자 발화" },
    { "role": "assistant", "content": "이전 봇 답변" }
  ],
  "categories": ["parking_public", "restroom"]
}
```
- `history`: 이번 세션의 대화 이력 (오래된 것부터). 첫 턴이면 빈 배열

### Response — `next` 가 프론트 동작을 결정
```json
{
  "reply": "좋아요! 어느 지역으로 떠나실 계획이세요?",
  "next": "ask",
  "quick_replies": ["서귀포", "애월", "성산", "협재"],
  "slots": { "region": null, "ev": null, "view": "바다", "kids": null }
}
```
```json
{
  "reply": "정리해 드릴게요 — 서귀포 · 전기차 · 바다 뷰로 찾아볼까요?",
  "next": "confirm",
  "slots": { "region": "서귀포", "ev": true, "view": "바다", "kids": false },
  "summary": "📍 서귀포 · ⚡ 전기차 · 🌊 바다 뷰"
}
```

| `next` 값 | 프론트 동작 |
|---|---|
| `"ask"` | reply를 채팅에 표시 + `quick_replies`를 탭 가능한 칩으로 렌더 (탭=그 텍스트로 다음 턴 전송) |
| `"confirm"` | **요약 카드**(`summary`) + `[✅ 이 조건으로 시설 확인]` `[✏️ 더 대화]` 버튼. ✅ 시 `slots`를 시설 프리셋으로 매핑해 시나리오 페이지 진입 |
| `"map"` (또는 기존처럼 `map` 객체 존재) | 기존 §1 동작 — 지도 전환 + 핀 (대화 없이 바로 결과를 주고 싶을 때) |
| 없음/미지정 | 기존 단일턴 동작 (하위 호환 — 지금의 `{reply}` 응답 그대로 유효) |

### slots → 시설 프리셋 매핑 (프론트 구현)
`region`→지역 bbox · `ev`→전기차충전소 · `view=바다`→해수욕장+CCTV · `view=숲/계곡`→야영장 ·
`kids`→화장실 가중 · (미지정 슬롯은 기존 키워드 자동 제안 유지)

### 🙋 B·C가 결정할 대화 정책 (A는 어느 쪽이든 수용)
1. **필수 슬롯**: region만? region+1~2개?
2. **최대 되묻기 턴 수**: 무한정 물으면 데모가 늘어짐 — 상한 제안 (예: 2턴 후 무조건 confirm)
3. **"바로 추천해줘" 인식**: 유저가 대화 생략을 원할 때 즉시 confirm으로 갈지
4. **slots 표준 키 목록**: region/date/ev/view/kids/quiet 외 추가?
5. `history` 없이 서버 세션으로 관리할지 (프론트는 둘 다 가능 — history 전송이 더 단순)

### 프론트 폴백 (백엔드 완성 전 데모용)
`/api/chat` 부재/형식 불일치 시: **프론트 규칙 스텁**이 같은 계약으로 동작
(지역 없으면 1회 되묻기 → confirm 카드) → 컨펌 후 기존 임시 스코어링 추천. B·C 완성 시 자동 대체.

## 5. B·C가 할 일
- [ ] 이 규격 확인/수정 제안 (카톡) — 특히 **§4 멀티턴 정책 질문 5개** 답변
- [ ] `/api/chat`이 `map` 객체 포함해 응답 — 점수·근거는 `scoring-design.md` V1~V12 서버 구현(#13) 또는
      초기엔 프론트 임시 엔진 유지하고 `reply`(GPT 생성)만 서버 담당해도 됨
- [ ] (멀티턴 채택 시) `next`/`quick_replies`/`slots`/`summary` 응답 — B의 `detect_region`·파싱과 연결
- [ ] `/api/feedback` 수신 → `chat_logs` 테이블 적재 (`results` 포함)
- [ ] ⚠️ 현 `backend/chat.py` 초안: main.py 라우터 통합 + `{response}`→`{reply}` 전환 + fastmcp 의존성 requirements 반영 필요
- [ ] 완료되면 A에게 알림 → 프론트 `MOCK_CHAT=false` (한 줄) — 임시 엔진 호출이 서버 응답으로 대체됨
