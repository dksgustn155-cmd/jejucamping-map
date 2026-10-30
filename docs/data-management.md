# 데이터 관리 전략

> 목표: **변동 주기에 맞춰 갱신** → 안 바뀌는 데이터는 자주 안 부르고, 실시간만 그때그때 호출. API 사용량·비용 최소화.

## 🧊 3-Tier 분류 (변동 주기 기준)

### Tier 1 · 정적 (거의 안 변함) → **월 1회 배치**, DB에 저장해서 서빙
지도 마커의 대부분. 위치·시설 정보라 몇 달에 한 번 바뀔까 말까. **매 요청마다 API 호출 안 함.**

| 데이터 | 건수 | 수집 스크립트 | 실제 변동 |
|---|---|---|---|
| 공중화장실 | 59,768 | collect_restroom.py (+geocode) | 분기 단위 |
| 공영주차장(전국표준) | 17,007 | collect_parking.py | 분기 단위 |
| 전기차 충전소(위치) | 3,229 | collect_jeju_ev.py | 월 단위 신설 |
| 야영장 | 3,023 | collect_camping.py | 드묾 |
| 문화축제(전국표준) | 1,072 | collect_festival_std.py | 월 단위 (개최기간 포함 → 혼잡 신호) |
| 클린하우스 | 1,403 | collect_jeju_safety.py | 드묾 |
| 관광안내소(전국표준) | 572 | collect_tourinfo.py | 드묾 |
| 둔치주차장 | 322 | collect_dunchi.py | 연 단위 |
| 해수욕장 | 281 | collect_beach.py | 거의 고정 |
| CCTV(위치) | 81 | collect_jeju_safety.py | 드묾 |
| 심야약국 | 7 | collect_jeju_pharmacy.py | 월 단위 |

**RAG 보조 데이터 (지도 미표시, `data/raw/*.jsonl`, prepare_rag_data.py 수동·분기 1회)**
: 시티투어 301 · 테마파크 464(아이 동반 놀거리) · 한옥체험 2,951(촌캉스 숙박 대안) — WGS84 좌표 변환 포함(LOCALDATA TM중부 EPSG:2097→4326, 결측은 카카오 지오코딩 보완)

→ **`refresh_all.py` 한 번**으로 전부 재수집 + DB 재빌드. Cloud Scheduler로 **월 1회 자동**.

### Tier 2 · 준정적 (텍스트/이벤트) → **주 1회 배치**
| 데이터 | 용도 |
|---|---|
| 제주 행사·축제 소식 (jejutoseoul/festival) | **이중 활용**: ①원문(`data/raw/festival.jsonl`)=RAG 지식베이스 ②GPT 추출(장소·기간·요약)→지오코딩→**category='festival' 지도 마커**. `collect_festival.py`, 키 불필요. 현재 GPT 스텁(--naive 임시), 이슈 #12 |
| 캠핑 규정·법령 문서 | RAG (거의 안 변함, 수동 갱신) |

> festival은 주 1회가 이상적이지만, 월 1회 `refresh_all.py`에도 포함해 둠 (build_db가 테이블을 재생성해 festival이 소실되는 것 방지). 주간 갱신은 `collect_festival.py` 단독 실행.

### Tier 3 · 실시간 (호출마다) → **DB 저장 안 함, 서빙 시 API 호출 + 짧은 캐시**
값이 계속 바뀌므로 저장 무의미. **요청 시 호출하되 5~10분 TTL 캐시**로 API 폭주 방지.

| 데이터 | API | 캐시 TTL(권장) |
|---|---|---|
| 날씨(기온·강수) | 기상청 단기예보 | 30분 |
| 해수욕장 파고·수온 | 기상청 BeachInfoservice | 10분 |
| 전기차 실시간 가용(급속/완속) | ITS infoEvList | 3~5분 |
| CCTV 실시간 영상 | cctvUrl (스트림) | 저장 X, URL만 전달 |

## 🔄 갱신 파이프라인

```
[월 1회 · Cloud Scheduler] ──▶ Cloud Run Job: refresh_all.py
   1. collect_restroom / camping / beach   (원본 jsonl 재수집)
   2. build_db.py                          (SQLite 재빌드 + 지오코딩 캐시 복원)
   3. geocode_restroom.py                  (신규 주소만 지오코딩 — 캐시로 대부분 스킵)
   4. collect_dunchi / jeju_ev / jeju_safety / jeju_pharmacy / festival  (카테고리별 추가)
   5. facilities.db → GCS 업로드 (타임스탬프 스냅샷)
[서빙] Cloud Run은 시작 시 GCS에서 최신 facilities.db 다운로드
```

- **왜 Cloud Run에서 돌리나**: asia-northeast3(서울) = 한국 IP라, 로컬 샌드박스에서 막히던 해수욕장 API도 정상 동작.
- **지오코딩 비용 0에 수렴**: `geocode_cache.json`이 있어 재실행 시 신규 주소만 호출.
- **스냅샷 보관**: GCS에 `facilities_YYYYMMDD.db`로 올려 롤백 가능.

## ✅ 원칙 요약
1. **안 바뀌는 건 저장**(SQLite+GCS), 자주 안 부른다 → 월 1회
2. **바뀌는 건 저장 안 함**(실시간 호출), 대신 짧은 캐시로 사용량 억제
3. **갱신은 1커맨드**(`refresh_all.py`) + 스케줄러 자동화
4. 원본은 **GCS 스냅샷**으로 버전 관리
