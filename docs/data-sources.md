# 데이터 소스 조사 결과

> 조사일: 2026-07-02 · data.go.kr 검색 기준 · 상태: 존재 확인 (키 발급/실호출 전)

---

## 🍊 제주 특화 레이어 계획 (2026-07-03) — 발표 하이라이트

전략: **시스템은 전국, 발표는 제주 집중.** 제주는 도정 오픈데이터가 풍부해 심화 기능을 얹기 좋음.
후보 API 전체 목록: `../../jeju-startup-checkup/docs/제주_공공API_전체목록.xlsx` (417개 중 캠핑 관련 89개 추림)

**1순위 · 시설 마커 (좌표 있어 바로 붙음)**
- 제주시_공중화장실 조회 — ⭐**위도/경도 포함** (전국판은 좌표 없어 지오코딩 필요 → 제주는 원본에 좌표. "제주는 더 정밀" 어필)
- 제주_주차장기본정보 — 주차장명·운영요일·주차면수 (전국 통합 주차장 API 없는 걸 제주가 메움)
- 제주시_클린하우스 / 재활용도움센터 — 좌표+운영시간 (캠퍼 쓰레기 배출 pain point)
- 제주_심야약국정보 — 야간 응급

**2순위 · 안전 특화 CCTV (차박 킬러 데모) ⭐**
- 제주시_월파 감시 CCTV — 좌표+CCTV URL. 해변 차박 중 파도 넘침 위험 실시간 확인
- 제주시_하천 감시 CCTV / 적설 감시 CCTV — 하천·겨울 차박 안전
- 제주_일별 기상 정보 / 대기환경정보(실시간 미세먼지)

**3순위 · 축제/혼잡 (혼잡 회피 신호)**
- 한국관광공사 TourAPI `searchFestival` — 제주 축제 위치·기간 (IJTO 대체)
- 제주_읍면동 유동인구 / 관광지별 유입자수 — 혼잡도 proxy (historical)

### ⚡ 제주 ITS센터 OPEN API (2026-07-06 승인·검증) — `api.jejuits.go.kr`, `?code=`(=.env `JEJU_ITS_CODE`)

data.go.kr와 별개 플랫폼(제주 ITS센터). 4종 실호출 확인:

| API | 엔드포인트 | 건수 | 좌표 | 비고 |
|---|---|---|---|---|
| **전기차 충전소 기본** | `/api/infoEvInfoList` | 8,664 | ✅ WGS84 (x_crdn=lat, y_crdn=lon) | name·addr·use_time(24시간)·free(무료)·사업자 |
| **전기차 실시간 가용** | `/api/infoEvList` | 2,597 | (id로 조인) | fast(급속)·slow(완속) 현재 가능 대수 — **실시간** |
| **관광지** | `/api/infoTourList` | 1,136 | ✅ WGS84 (latitude/longitude) | title·tag·introduction·**img_path(사진)** → RAG용으로도 |
| 주유소/LPG | `/api/infoGasInfoList` | 224 | ⚠️ 투영좌표(gisxcoor, KATEC 추정→변환필요) | osnm·adr·lpgyn |

**활용 결정**:
- ⭐ **전기차 충전소** = 제주 특화 킬러 레이어로 채택. 두 API를 `id`로 조인 → "지금 급속 N대 가능". WGS84라 변환 불필요. 제주 전기차 렌터카 차박족 겨냥
- 관광지 = "주변 볼거리" 부가 레이어 + RAG 지식베이스(소개문) 후보
- 주유소 = 좌표 변환 필요, 후순위

### 🎪 제주 행사·축제 소식 (RAG 소스, 2026-07-06 검토) — **키 불필요**
- 엔드포인트: `https://www.jeju.go.kr/api/jejutoseoul/festival/` (⚠️ **끝 슬래시 필수**, 인증키 없음)
- 응답 JSON, 행사 소식 33건. 필드: title·writeDate·url·contents(HTML)·writer
- ⚠️ **좌표·장소·기간 없음** = 게시판 뉴스 텍스트 → 지도 레이어 불가
- ✅ **RAG 지식베이스 소재(③)**: 챗봇이 "요즘 제주 행사?" 답할 때 인용. Tier 2(주1회 갱신). 이슈 #3

### ⚠️ IJTO 제주관광빅데이터플랫폼 (data.ijto.or.kr) — 사용 불가 확정
- 실시간 축제 유동인구·핫플레이스·방문차량 대시보드 = **SKT 모바일 라이선스 데이터, 대시보드 전용**
- Open API·데이터 다운로드 없음 (자료실은 리포트만). 크롤링은 약관 위반
- → 3순위 API(TourAPI 축제 + 제주 유동인구)로 유사 기능 재현. 축제를 "혼잡 신호"로 역이용

---

## 🧪 Phase 1 실호출 검증 결과 (2026-07-03 최종)

**핵심 API 5종 전부 검증 완료. 서비스 구현 가능 확정.**

| API | 정확한 호출 방법 | 결과 | 핵심 발견 |
|---|---|---|---|
| **공중화장실** (P0) | `1741000/public_restroom_info_v2/`**`info_v2`**`?serviceKey=&pageNo=&numOfRows=&type=json` | ✅ | **전국 59,768건**, 필드 34개. ⚠️**좌표 없음 확정** → 지오코딩 필수. 개방시간(OPN_HR)은 자유 텍스트("상시" 등) |
| **고캠핑** (야영장) | `B551011/GoCamping/basedList?MobileOS=ETC&MobileApp=명&_type=json` | ✅ | **mapX/mapY 좌표 있음**. 시설명·주소·전화·사이트수(일반/자동차/글램핑/카라반) |
| **해수욕장 정보** | `1192000/service/OceansBeachInfoService1/getOceansBeachInfo1?`**`SIDO_NM=부산`**(짧은 시도명!)`&resultType=json` | ✅ | **lat/lon 좌표 있음** (⚠️일부 null — 다대포 등 결측 존재). sta_nm, beach_wid/len, beach_knd(모래). 부산 7건 |
| **해수욕장 날씨** | `1360000/BeachInfoservice/getWhBuoyBeach`(파고)·`getTwBuoyBeach`(수온)`?beach_num=&`**`searchTime=YYYYMMDDHHMM`**`&dataType=JSON` | ✅ | 파고 0.2m·수온 23.3°C 실시간 응답 확인. 조석(getTideInfoBeach)은 파라미터 상이 — 추후 확인 |
| **기상청 단기예보** | `1360000/VilageFcstInfoService_2.0/getVilageFcst?base_date=&base_time=&nx=&ny=&dataType=JSON` | ✅ | 정상. **nx/ny 격자 변환 필요** |
| 해수욕장 수질 | `OceansBeachSeawaterService1/getOceansBeachSeawaterInfo1` | ❌ Forbidden | **별개 API라 활용신청 필요** (한국 IP에서도 거부 → 미신청이 원인). 수질은 nice-to-have라 P2로 |

### 공중화장실 주요 필드 (34개 중 서비스에 쓸 것)
`RSTRM_NM`(화장실명), `LCTN_ROAD_NM_ADDR`/`LCTN_LOTNO_ADDR`(도로명/지번주소), `OPN_HR`(개방시간),
`MALE_TOILT_CNT`/`FEMALE_TOILT_CNT`(변기수), `MALE_FRDBL_TOILT_CNT`(장애인), `DIAP_EXCHCON_EN`(기저귀교환대),
`EMRGNCBLL_INSTL_YN`(비상벨), `RSTRM_ENTRAN_CCTV_INSTL_EN`(CCTV), `MNG_INST_NM`(관리기관), `TELNO`

### 다음 단계 (Phase 2 진입 조건 충족)
1. **지오코딩 전략 확정** — 화장실 5.97만 건 주소→좌표 배치 변환 (카카오 로컬 API 일 10만 건 무료 / 행안부 주소 API 대안)
2. 해수욕장 수질 API는 원하면 별도 활용신청 (P2)
3. 개방시간 정규화 규칙 설계 ("상시"/"24시간"/"09:00~18:00" 혼재)

## 1. 공중화장실 ✅ (P0 핵심)

**행정안전부_공중화장실정보 조회서비스**
- 전국 통합 유일 (검색된 110개 API 중 나머지는 전부 지자체 단위)
- XML/JSON, 국가중점데이터, 최종 갱신 2026-06 (관리 활발)
- "전국공중화장실표준데이터" 표준 스키마 기반 — 표준 필드:
  위도/경도, 개방시간, 남녀 변기 수, 장애인 화장실, 관리기관/전화번호
- Day 1 검증 포인트: 좌표 결측률, 개방시간이 자유 텍스트인지("24시간", "09:00~18:00" 혼재 가능)

## 2. 야영장 ✅ (P1)

**한국관광공사_고캠핑 정보 조회서비스_GW**
- 전국 지자체 인허가 시스템에 등록된 야영장(캠핑장) 운영 현황
- 가장 포괄적인 전국 단위 캠핑장 API
- 대안: 행정안전부_문화_일반야영장업 / 자동차야영장업 조회서비스 (인허가 데이터)

## 3. 날씨 ✅ (P1)

**기상청_단기예보 조회서비스**
- 기온/강수/풍속 예보
- ⚠️ 기상청은 위경도가 아닌 자체 격자 좌표계 사용 → 변환 로직 필요 (공식 변환식 공개되어 있음)

## 4-A. ⭐ 둔치주차장 4종 API (재난안전플랫폼, 2026-07-06 승인·수집완료) — **서비스 핵심**

`safetydata.go.kr/V2/api/DSSP-IF-*` · API별 개별 키(.env `SAFETY_DUNCHI_*_KEY`) · 일일 1,000건/키

| API | ID | 건수 | 내용 |
|---|---|---|---|
| 본체 | DSSP-IF-10830 | 563 주소점 | 좌표(EPSG:5179)·주소 |
| **속성** | DSSP-IF-00162 | **322 주차장** | ⭐ 이름·**침수위험등급(RSK_GRD 1~3)**·**주차면수**·**하천명**·시설형태 |
| 영역 | DSSP-IF-00160 | 322 | 부지 POLYGON (EPSG:3857) |
| 진입로 | DSSP-IF-00161 | 278 | 진입로 LINESTRING (EPSG:3857) |

- 조인키: `THINGS_MNG_NO`(=본체 `OBJT_MNG_NO`) — `collect_dunchi.py`가 통합해 DB(category='parking') 반영 완료
- **322곳 전부 좌표 확보** (본체 주소점 + 폴리곤 중심 보완). **제주 1곳**(한천 공영노상주차장, 172면) 포함
- 위험등급 분포: 3등급 227 / 2등급 46 / **1등급 10** / 미상 39 (⚠️ 등급 방향(1이 위험한지) 기술문서로 확인 필요)
- **활용**: ① 위험등급별 마커 색(신호등) ② 부지 폴리곤·진입로 지도 표시 ③ 기상 예보(비)×등급 → 챗 추천에서 침수 경고 ④ "정부 위험등급으로 안전 안내" = 발표 방어 논리

## 4-B. 둔치주차장 (구 조사 기록)

**행정안전부_둔치주차장** (전국, 강변/하천변 주차장 = 차박 후보지)
- 샘플 CSV 실검증 완료 (2026-07-02). 전체 데이터는 API 승인 후 확보 예정.
- 컬럼: GID, OBJT_MNG_NO(객체관리번호), CTPV_NM(시도), SGG_NM(시군구), EMD_NM(읍면동),
  ADDR(전체주소), ROAD_NM(도로명), UDGD_YN(지하여부), XCRD/YCRD(좌표)
- ✅ 이름·주소·도로명 다 있음, 전국 커버리지
- ⚠️ **좌표계 EPSG:5179 (UTM-K)** → WGS84 변환 필요 (pyproj로 검증 완료, 주소와 정확히 일치)
- ⚠️ **한 주차장이 여러 주소점 행으로 중복** → `OBJT_MNG_NO` 기준 dedupe 필요 (샘플 100행=고유 65개소)
- ⚠️ 수용대수·화장실 유무 필드 없음 → 공중화장실 데이터와 좌표 조인으로 보완

**주의**: `행정안전부_둔치주차장_진입로.csv`는 별개 파일 — 진입로 LINESTRING만 있고 이름/시설 없음, 좌표계도 EPSG:3857. **사용 안 함.**

일반 공영주차장은 전국 통합 API 없음(지자체 분산)이라 이번엔 제외.

## ⚠️ 좌표계 정리 (소스마다 다름 — 파이프라인에서 통일 필요)

| 데이터 | 원본 좌표계 | 처리 |
|---|---|---|
| 둔치주차장 | EPSG:5179 (UTM-K) | pyproj로 WGS84 변환 |
| 공중화장실 | **좌표 없음** (2025.02 중단) | 주소 → 지오코딩으로 좌표 생성 |
| 둔치주차장_진입로 (미사용) | EPSG:3857 (Web Mercator) | — |

→ 최종적으로 전부 WGS84(위경도)로 통일해서 GCS/DB에 저장, 거리 계산은 haversine.

## 신청 순서 (data.go.kr 로그인 → 활용신청)

1. 행정안전부_공중화장실정보 조회서비스
2. 기상청_단기예보 조회서비스
3. 한국관광공사_고캠핑 정보 조회서비스_GW

일반 인증 API는 대부분 즉시 자동승인. 마이페이지에서 인증키(Encoding) 확인.

---

## 📌 7/6 저녁 추가 승인·수집 (행안부 표준데이터 4종 + LOCALDATA 2종)

전부 기존 `DATA_GO_KR_KEY` 그대로. 표준데이터는 `https://api.data.go.kr/openapi/{api}?serviceKey=키&pageNo=1&numOfRows=1000&type=json`.

| 데이터 | 엔드포인트(api) | 건수 | 반영 |
|---|---|---|---|
| ⭐ 전국문화축제표준 | `tn_pubr_public_cltur_fstvl_api` | 1,300(좌표 1,072) | category='festival' 메인 레이어. fstvlNm·opar(장소)·Start/EndDate·fstvlCo·lat/lon |
| 전국주차장정보표준 | `tn_pubr_prkplce_info_api` | 18,530(좌표 17,007) | category='parking_public'. prkplceSe(공영/민영)·prkcmprt(면수)·요금 |
| 전국관광안내소표준 | `tn_pubr_public_trsmic_api` | 572 | category='tourinfo'. 외국어 안내 여부 포함 |
| 전국시티투어표준 | `tn_pubr_public_city_tour_api` | 301 | 지도 미표시 — RAG 텍스트 `data/raw/city_tour.jsonl` |
| LOCALDATA 일반테마파크업 CSV | (파일, cp949) | 영업중 464 | RAG `theme_park.jsonl` — 아이 동반 놀거리 |
| LOCALDATA 한옥체험업 CSV | (파일, cp949) | 영업중 2,951 | RAG `hanok_stay.jsonl` — 촌캉스 숙박 대안 |

- LOCALDATA 좌표계는 **TM중부 EPSG:2097** (5174 아님 — 서울 샘플 실측으로 확인, 250m 오차). 변환·지오코딩 보완은 `prepare_rag_data.py`
- 표준데이터 신규 승인 직후 `SERVICE KEY IS NOT REGISTERED`(코드30)가 뜰 수 있음 = 포털 반영 지연, 잠시 후 재시도
- 제주 행사 '소식'(jejutoseoul)은 category='festival_news'로 분리 (GPT 추출 후보완, 이슈 #12)
