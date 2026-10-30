// ── 카테고리 색상/이름 ─────────────────────────────────────────────
const CAT = {
  restroom:   { color: "#2b7cd3", label: "화장실",        icon: "🚻" },
  camping:    { color: "#3aa657", label: "야영장",        icon: "⛺" },
  beach:      { color: "#17a2b8", label: "해수욕장",      icon: "🏖️" },
  parking:    { color: "#e8890c", label: "둔치주차장",    icon: "🅿️" },
  parking_public: { color: "#546e7a", label: "공영주차장", icon: "🚗" },
  ev_charger: { color: "#6f42c1", label: "전기차 충전소", icon: "🔌" },
  cctv:       { color: "#d63384", label: "안전 CCTV",     icon: "📹" },
  cleanhouse: { color: "#795548", label: "클린하우스",    icon: "♻️" },
  pharmacy:   { color: "#20c997", label: "심야약국",      icon: "💊" },
  festival:   { color: "#ff6b9d", label: "행사·축제",     icon: "🎉" },
  tourinfo:   { color: "#5c6bc0", label: "관광안내소",    icon: "ℹ️" },
  nakji:      { color: "#8a9a5b", label: "노지(공공 빈터)", icon: "🏕️" },
};
// CAT에 없는 카테고리가 와도 안 깨지게 (기본 회색 핀)
function catOf(category) {
  return CAT[category] || { color: "#888888", label: category, icon: "📍" };
}

// 둔치주차장 침수위험등급 색 (신호등) — 1등급=가장 위험으로 매핑.
// 근거: 필드명 RSK_GRD(위험등급) + 행안부 침수등급 관례 + 분포(1등급 희소).
// ⚠️ 2026-07-06 재난안전플랫폼 공식명세(DSSP-IF-00162) 확인 결과 값 정의(코드북) 없음.
//    100% 확정은 예방안전과(☎044-205-4922) 문의 필요. 반대(1=안전)면 아래 색만 뒤집으면 됨.
const RISK = {
  "1": { color: "#e24b4a", label: "1등급(위험)" },
  "2": { color: "#e8890c", label: "2등급(주의)" },
  "3": { color: "#3aa657", label: "3등급(양호)" },
  "":  { color: "#888888", label: "등급 미상" },
};

// 색깔 핀 이미지 (SVG data URI) — 색은 카테고리/위험등급, 아이콘은 이모지
// 식별성을 위해 크게(40x52) + 흰 테두리·그림자
function pinImage(color, emoji) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="52" viewBox="0 0 40 52">
       <path d="M20 1C9.9 1 1.5 9 1.5 19 1.5 31.8 20 51 20 51S38.5 31.8 38.5 19C38.5 9 30.1 1 20 1z"
             fill="rgba(0,0,0,.18)" transform="translate(1.2 1.6)"/>
       <path d="M20 1C9.9 1 1.5 9 1.5 19 1.5 31.8 20 51 20 51S38.5 31.8 38.5 19C38.5 9 30.1 1 20 1z"
             fill="${color}" stroke="#fff" stroke-width="1.8"/>
       <circle cx="20" cy="18.6" r="12.2" fill="#fff"/>
       <text x="20" y="18.8" font-size="16" text-anchor="middle" dominant-baseline="central">${emoji}</text>
     </svg>`;
  return "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
}

let map, clusterer, roadview, roadviewClient;
let markerImages = {};
let parkingOverlays = [];  // 둔치주차장 부지 폴리곤·진입로 (선택 시 그림, 다음 선택 때 제거)
let lastItems = [];        // 마지막 bbox 조회 결과 (모바일 바텀시트 리스트용)

// HTML 이스케이프 (시설명/주소에 특수문자가 있어도 화면 안 깨지게)
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ── 카카오 SDK 동적 로드 ────────────────────────────────────────────
function loadKakao() {
  const key = (window.APP_CONFIG || {}).KAKAO_JS_KEY;
  if (!key) { document.getElementById("map").innerHTML = "<p style='padding:20px'>카카오 JS 키가 없습니다 (.env 확인)</p>"; return; }
  const s = document.createElement("script");
  s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${key}&libraries=services,clusterer&autoload=false`;
  s.onload = () => kakao.maps.load(init);
  document.head.appendChild(s);
}

function init() {
  map = new kakao.maps.Map(document.getElementById("map"), {
    center: new kakao.maps.LatLng(33.383, 126.549), // 제주 중심
    level: 8,
  });
  clusterer = new kakao.maps.MarkerClusterer({ map, averageCenter: true, minLevel: 6 });
  roadviewClient = new kakao.maps.RoadviewClient();
  roadview = new kakao.maps.Roadview(document.getElementById("roadview-canvas"));

  const size = new kakao.maps.Size(40, 52);
  const opt = { offset: new kakao.maps.Point(20, 52) };  // 핀 끝(하단 중앙)이 좌표를 가리키게
  const mk = (color, emoji) => new kakao.maps.MarkerImage(pinImage(color, emoji), size, opt);
  for (const c in CAT) {
    markerImages[c] = mk(CAT[c].color, CAT[c].icon);
  }
  for (const g in RISK) {  // 둔치주차장은 위험등급 색 + 주차장 이모지
    markerImages["parking_" + g] = mk(RISK[g].color, CAT.parking.icon);
  }

  kakao.maps.event.addListener(map, "idle", refresh);
  // 지도 빈 지점 클릭 → 그 자리 로드뷰 (로드뷰 없으면 조용히 무시)
  kakao.maps.event.addListener(map, "click", (e) => openRoadview(e.latLng.getLat(), e.latLng.getLng(), true));
  refresh();
  // CSS/폰트가 지도 생성보다 늦게 적용되면 타일 크기가 어긋남 → 한 번 더 맞춤
  setTimeout(() => map.relayout(), 350);
}

// ── 화면 영역 내 시설 불러와 마커 표시 ──────────────────────────────
let refreshTimer = null;
function refresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    const b = map.getBounds();
    const sw = b.getSouthWest(), ne = b.getNorthEast();
    const cats = [...document.querySelectorAll(".layer-toggles input:checked")].map(i => i.value);
    if (!cats.length) { clusterer.clear(); lastItems = []; renderSheetList(); return; }
    const q = new URLSearchParams({
      sw_lat: sw.getLat(), sw_lng: sw.getLng(),
      ne_lat: ne.getLat(), ne_lng: ne.getLng(),
      category: cats.join(","), limit: 1000,
    });
    try {
      const res = await fetch("/api/facilities?" + q);
      const data = await res.json();
      clusterer.clear();
      clusterer.addMarkers(data.items.map(makeMarker));
      lastItems = data.items;
      renderSheetList();  // 모바일 바텀시트 리스트 갱신
    } catch (e) {
      console.warn("시설 조회 실패 (서버 재기동 중일 수 있음):", e);
    }
  }, 250);
}

function riskKey(item) {
  const g = String((item.extra && item.extra.risk_grade) || "").trim();
  return "parking_" + (RISK[g] ? g : "");
}
function makeMarker(item) {
  const pos = new kakao.maps.LatLng(item.lat, item.lon);
  const img = item.category === "parking" ? markerImages[riskKey(item)] : markerImages[item.category];
  const marker = new kakao.maps.Marker({ position: pos, image: img });
  kakao.maps.event.addListener(marker, "click", () => showDetail(item, pos));
  return marker;
}

// ── 둔치주차장 부지 폴리곤·진입로 그리기 ────────────────────────────
function clearParkingOverlays() {
  parkingOverlays.forEach(o => o.setMap(null));
  parkingOverlays = [];
}
function drawParking(extra) {
  const g = String(extra.risk_grade || "").trim();
  const color = (RISK[g] || RISK[""]).color;
  const toLL = pts => pts.map(p => new kakao.maps.LatLng(p[0], p[1]));
  if (extra.polygon && extra.polygon.length >= 3) {
    const poly = new kakao.maps.Polygon({
      path: toLL(extra.polygon), strokeWeight: 2, strokeColor: color,
      strokeOpacity: 0.9, fillColor: color, fillOpacity: 0.25,
    });
    poly.setMap(map); parkingOverlays.push(poly);
  }
  (extra.access_roads || []).forEach(road => {
    if (road && road.length >= 2) {
      const line = new kakao.maps.Polyline({
        path: toLL(road), strokeWeight: 4, strokeColor: "#333", strokeOpacity: 0.8,
      });
      line.setMap(map); parkingOverlays.push(line);
    }
  });
}

// ── 적합성 리포트 (P3) — 추천 핀의 why[]를 체크리스트로 렌더 ─────────
function fitReportHTML(item) {
  const rows = (item._why || []).map(w => {
    const icon = w.check === "natural_park" && !w.pass ? "🚫" : w.pass ? "✅" : "⚠️";
    const cls = w.delta > 0 ? "plus" : w.delta < 0 ? "minus" : "zero";
    return `<div class="fr-row"><span>${icon} ${esc(w.detail)}</span>` +
           `<span class="fr-delta ${cls}">${w.delta > 0 ? "+" : ""}${w.delta}</span></div>`;
  }).join("");
  return `<div class="fit-report">
    <div class="fr-head">⭐ 차박 적합도 <b>${item._score}</b><span class="fr-max"> / 100</span></div>
    ${rows}
  </div>`;
}

// ── 마커 클릭 → 정보창 + 로드뷰 버튼 ────────────────────────────────
function showDetail(item, pos) {
  document.getElementById("roadview").classList.add("hidden");  // 다른 마커 선택 시 로드뷰 자동 닫기
  clearParkingOverlays();
  destroyCctv();  // 이전에 틀어놓은 CCTV 스트림 정리
  const c = catOf(item.category);
  const addr = esc(item.road_addr || item.lotno_addr || "");
  const name = esc(item.name);
  const extra = item.extra || {};
  let rows = `<div class="row">📍 ${addr}</div>`;
  if (item.open_hours) rows += `<div class="row">🕒 ${esc(item.open_hours)}</div>`;
  if (item.tel) rows += `<div class="row">☎ ${esc(item.tel)}</div>`;
  if (item.category === "restroom") {
    rows += `<div class="row">🚻 남 ${extra.male_toilet||0} / 여 ${extra.female_toilet||0}` +
            (extra.disabled ? ` / 장애인 ${extra.disabled}` : "") + `</div>`;
  }
  if (item.category === "camping") {
    rows += `<div class="row">⛺ 일반 ${extra.gnrl_site||0} / 자동차 ${extra.auto_site||0} / 글램핑 ${extra.glamp_site||0}</div>`;
  }
  if (item.category === "parking") {
    const g = String(extra.risk_grade || "").trim();
    const r = RISK[g] || RISK[""];
    rows += `<div class="row">🅿️ 주차 ${extra.capacity ?? "?"}면` + (extra.river ? ` · ${esc(extra.river)}` : "") + `</div>`;
    rows += `<div class="row">⚠️ 침수위험 <b style="color:${r.color}">${esc(extra.risk_grade_nm || r.label)}</b> — 호우 시 통제될 수 있음</div>`;
    drawParking(extra);
  }
  if (item.category === "parking_public") {
    const kind = [extra.gubun, extra.type].filter(Boolean).map(esc).join(" · ");
    rows += `<div class="row">🚗 ${kind}${extra.capacity ? ` · ${esc(extra.capacity)}면` : ""}</div>`;
    if (extra.charge_info) rows += `<div class="row">💳 ${esc(extra.charge_info)}</div>`;
    if (extra.manager) rows += `<div class="row">🏢 ${esc(extra.manager)}</div>`;
  }
  if (item.category === "nakji") {
    const h = extra.houses;
    rows += `<div class="row">🏕️ 공공 빈터(노지) — 사유지(개인·법인) 제외한 공터</div>`;
    if (h != null) rows += `<div class="row">🏠 주변 건물 약 ${h}채 ${h <= 15 ? "· 한적" : h <= 40 ? "· 다소 한적" : "· 보통"}</div>`;
    if (extra.jibun) rows += `<div class="row">📄 지목: ${esc(extra.jibun)}</div>`;
  }
  if (item.category === "festival") {
    if (extra.period) rows += `<div class="row">📅 ${esc(extra.period)}</div>`;
    if (extra.place) rows += `<div class="row">📌 ${esc(extra.place)}</div>`;
    if (extra.summary) rows += `<div class="row">📝 ${esc(extra.summary)}</div>`;
    if (extra.url) rows += `<div class="row"><a href="${esc(extra.url)}" target="_blank" rel="noopener">🔗 자세히 보기</a></div>`;
  }
  if (item.category === "tourinfo") {
    if (extra.intro) rows += `<div class="row">📝 ${esc(extra.intro)}</div>`;
    if (extra.lang) rows += `<div class="row">🌐 외국어 안내: ${esc(extra.lang)}</div>`;
  }
  if (item.category === "ev_charger") {
    if (extra.operator) rows += `<div class="row">🏢 ${esc(extra.operator)}${extra.free === "Y" ? " · 무료" : ""}</div>`;
    rows += `<div class="row" id="ev-live">⏳ 실시간 가용 확인 중…</div>`;  // 아래에서 비동기로 채움
  }
  if (item.category === "cctv") {
    const kind = extra.cctv_type === "wave" ? "월파(해안 넘침) 감시" : (extra.cctv_type || "감시");
    rows += `<div class="row">📡 ${esc(kind)} CCTV · 실시간</div>`;
    if (extra.cctv_url) {
      rows += `<div class="row"><video id="cctv-video" class="cctv-video" muted autoplay playsinline controls></video>` +
              `<span id="cctv-msg" class="cctv-msg">영상 불러오는 중…</span></div>`;
      rows += `<div class="row"><a href="${esc(extra.cctv_url)}" target="_blank" rel="noopener">🔗 스트림 새 창에서 열기</a></div>`;
    } else {
      rows += `<div class="row">실시간 영상 주소가 없습니다.</div>`;
    }
  }

  // 플로팅 상세 카드 (zone-row는 자연공원 판정 결과가 오면 표시)
  const detail = document.getElementById("detail");
  detail.classList.remove("hidden");
  detail.innerHTML =
    `<button class="close" onclick="closeDetail()">✕</button>
     <h3><span class="dot ${item.category}"></span> ${name}</h3>
     <div class="cat">${c.icon} ${c.label}${item._rank ? ` · <b class="fr-rank">추천 ${item._rank}위</b>` : ""}</div>
     ${rows}
     ${item._score != null ? fitReportHTML(item) : ""}
     <div class="row zone-row" id="zone-row" style="display:none"></div>
     <button id="rv-btn" class="rv-btn" onclick="openRoadview(${item.lat},${item.lon})">🛣️ 로드뷰로 현장 보기</button>
     ${feedbackHTML(item)}`;

  // 자연공원 구역 경고 비동기 표시 — 적합성 리포트에 판정이 이미 있으면 생략(중복 방지)
  if (!item._why) fillZone(item.lat, item.lon);
  // 추천 상세면 이유 시설 마커+점선 표시, 일반 상세면 이전 이유 마커 정리
  if (item._why) drawReasons(item); else clearReasonOverlays();
  // 장소 카드: 피드백 카운트 비동기 로드 (추천 핀 상세·일반 마커 모두)
  if (FB_CAMPABLE.has(item.category)) initFeedback(String(item.id));
  // 로드뷰 없는 지점이면 버튼 비활성화 (외진 노지 등)
  if (roadviewClient) roadviewClient.getNearestPanoId(new kakao.maps.LatLng(item.lat, item.lon), 60, (pid) => {
    const rb = document.getElementById("rv-btn");
    if (rb && pid === null) { rb.disabled = true; rb.classList.add("rv-off"); rb.textContent = "🛣️ 로드뷰 없음 (외진 곳)"; rb.onclick = null; }
  });
  // 전기차: 실시간 가용 대수 비동기 반영
  if (item.category === "ev_charger") fillEvLive(String(item.id).replace(/^ev:/, ""));
  // CCTV: 실시간 HLS 스트림 재생
  if (item.category === "cctv" && extra.cctv_url) playCctv(extra.cctv_url);
  // (지도 위 인포윈도우 말풍선은 제거 — 상세는 좌측 카드로만, 로드뷰도 카드 버튼으로)

  // 모바일: 상세 카드를 바텀시트 상단에 표시 + 시트 반쯤 펼침
  if (isMobile()) {
    placeDetail();
    setSheet("half");
    const body = document.getElementById("sheet-body");
    if (body) body.scrollTop = 0;
  }
}

// ── 자연공원 구역 판정 (/api/zone-check, 팀원 GIS) — 상세카드 경고 행 ──
// 좌표별 결과 캐시 (같은 시설 재클릭 시 재호출 방지)
const _zoneCache = new Map();
async function fillZone(lat, lon) {
  try {
    const key = lat.toFixed(4) + "," + lon.toFixed(4);
    let z = _zoneCache.get(key);
    if (!z) {
      z = await (await fetch(`/api/zone-check?lat=${lat}&lon=${lon}`)).json();
      _zoneCache.set(key, z);
    }
    const el = document.querySelector("#detail #zone-row");
    if (!el || !z.zone) return;  // 다른 마커로 넘어갔거나 구역 밖이면 표시 안 함
    el.style.display = "";
    let rule = (z.rules && z.rules[0]) || "자연공원법 제27조: 지정장소 외 야영·취사 금지";
    rule = rule.replace(`${z.zone} ${z.kind} 구역 — `, "");  // 제목과 중복되는 접두어 제거
    el.innerHTML = `🚫 <b>${esc(z.zone)} ${esc(z.kind)}</b> 구역입니다<br/>` +
                   `<span class="zone-sub">${esc(rule)}</span>`;
  } catch { /* 판정 실패 시 조용히 생략 — 상세카드 자체는 정상 표시 */ }
}

// ── 전기차 실시간 가용 (급속/완속) — 3분 클라이언트 캐시 ──────────────
let _evStatus = null, _evAt = 0;
async function getEvStatus() {
  if (_evStatus && Date.now() - _evAt < 180000) return _evStatus;
  try {
    const res = await fetch("/api/ev-status");
    const data = await res.json();
    _evStatus = data.status || {}; _evAt = Date.now();
  } catch { _evStatus = _evStatus || {}; }
  return _evStatus;
}
async function fillEvLive(id) {
  const st = await getEvStatus();
  const el = document.querySelector("#detail #ev-live");
  if (!el) return;  // 그 사이 다른 마커를 눌렀으면 스킵
  const s = st[id];
  if (s) el.innerHTML = `⚡ 지금 <b style="color:#2d7d46">급속 ${s.fast}</b> / 완속 ${s.slow} 대 충전 가능`;
  else el.textContent = "⚡ 실시간 가용 정보 없음";
}

// ── CCTV 실시간 HLS 스트림 재생 (제주 월파 감시) ──────────────────────
// ⚠️ 스트림이 http 전용이라 https 배포 시 mixed-content로 차단됨 → 배포 땐 백엔드 프록시 필요(팀원 C)
let _hls = null;
function destroyCctv() {
  if (_hls) { _hls.destroy(); _hls = null; }
}
function playCctv(url) {
  const video = document.querySelector("#detail #cctv-video");
  const msg = document.querySelector("#detail #cctv-msg");
  if (!video) return;
  const fail = (t) => { if (msg) msg.textContent = t; video.style.display = "none"; };
  const ready = () => { if (msg) msg.remove(); };

  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    // Safari/iOS는 HLS 네이티브 지원
    video.src = url;
    video.addEventListener("loadeddata", ready, { once: true });
    video.addEventListener("error", () => fail("영상을 불러오지 못했습니다 (카메라 점검 중일 수 있어요)"), { once: true });
  } else if (window.Hls && Hls.isSupported()) {
    _hls = new Hls({ liveDurationInfinity: true, manifestLoadingTimeOut: 8000 });
    _hls.loadSource(url);
    _hls.attachMedia(video);
    _hls.on(Hls.Events.MANIFEST_PARSED, () => { ready(); video.play().catch(() => {}); });
    _hls.on(Hls.Events.ERROR, (_e, data) => {
      if (data.fatal) { destroyCctv(); fail("실시간 영상을 불러오지 못했습니다 (배포 환경·해외망에서는 차단될 수 있어요)"); }
    });
  } else {
    fail("이 브라우저는 실시간 영상을 지원하지 않습니다. 아래 링크로 열어주세요.");
  }
}

// 상세 카드 닫기 (CCTV 스트림도 함께 정지)
function closeDetail() {
  document.getElementById("detail").classList.add("hidden");
  destroyCctv();
}
window.closeDetail = closeDetail;

// ── 로드뷰 열기 (없으면 안내) ───────────────────────────────────────
function openRoadview(lat, lon, silent) {
  const pos = new kakao.maps.LatLng(lat, lon);
  roadviewClient.getNearestPanoId(pos, silent ? 30 : 100, (panoId) => {
    if (panoId === null) { if (!silent) alert("이 지점은 로드뷰가 제공되지 않는 곳입니다 (외진 노지 등)."); return; }
    document.getElementById("roadview").classList.remove("hidden");
    roadview.setPanoId(panoId, pos);
    setTimeout(() => roadview.relayout(), 100);
  });
}
window.openRoadview = openRoadview;

// ── UI 이벤트 ───────────────────────────────────────────────────────
const layerBoxes = [...document.querySelectorAll(".layer-toggles input")];
layerBoxes.forEach(i => i.addEventListener("change", refresh));
document.getElementById("roadview-close").onclick = () =>
  document.getElementById("roadview").classList.add("hidden");

// 레이어 모두 해제 / 모두 선택 토글
const clearBtn = document.getElementById("clear-layers");
function syncClearBtn() {
  clearBtn.textContent = layerBoxes.some(i => i.checked) ? "모두 해제" : "모두 선택";
}
clearBtn.onclick = () => {
  const anyOn = layerBoxes.some(i => i.checked);
  layerBoxes.forEach(i => { i.checked = !anyOn; });  // 하나라도 켜져 있으면 전부 끄기, 아니면 전부 켜기
  syncClearBtn();
  refresh();
};
layerBoxes.forEach(i => i.addEventListener("change", syncClearBtn));
syncClearBtn();

// 지도 전체화면 토글 (카카오는 리사이즈 후 relayout 필요)
document.getElementById("map-fullscreen").onclick = () => {
  const sec = document.getElementById("map-section");
  sec.classList.toggle("full");
  setTimeout(() => { map.relayout(); map.setCenter(map.getCenter()); }, 60);
};

// 창 크기 변경 시 지도 리레이아웃 (타일이 띠처럼 찌그러지는 것 방지)
window.addEventListener("resize", () => { if (map) map.relayout(); });

// ── 화면 전환: 랜딩 / 시나리오 / 지도 (3단 뷰) ──────────────────────
const appEl = document.getElementById("app");
function setView(v) {
  appEl.classList.toggle("view-map", v === "map");
  appEl.classList.toggle("view-scenario", v === "scenario");
  if (v !== "map") document.getElementById("map-section").classList.remove("full");
  // 숨김 상태에서 만들어진 지도는 크기가 0 → 보이게 된 뒤 재배치 필수
  if (v === "map") setTimeout(() => { if (map) { map.relayout(); refresh(); } }, 60);
}
document.getElementById("open-map").onclick = () => {
  setView("map");
  setTimeout(() => { if (map) map.setCenter(new kakao.maps.LatLng(33.383, 126.549)); }, 60);
};
document.getElementById("map-back").onclick = () => {
  setView("landing");
  // 새 검색을 위해 랜딩 대화·위젯 초기화 (입력창·예시 다시 표시)
  const lc = document.getElementById("landing-card");
  lc.classList.remove("chatting");
  lc.classList.remove("recommended");
  document.getElementById("chat-log").innerHTML = "";
  chatHistory = [];
  recommendedOnce = false;
  lastRecContext = "";
  const inp = document.getElementById("chat-input");
  if (inp) inp.placeholder = "예: 이번 주말 전남 담양 2박 3일, 아이들이랑 계곡 근처로 가고 싶어";
};

// ── 예상 질문 칩: 10개 풀에서 4개 랜덤 노출 ─────────────────────────
const QUESTIONS = [
  "이번 주말 전남 담양으로 2박 3일, 아이 둘이랑 계곡 근처 추천해줘. 애들이 수영을 좋아해",
  "서귀포 바다 보이는 조용한 차박지 알려줘. 화장실 가까우면 좋겠어",
  "전기차인데 충전 걱정 없이 차박할 수 있는 곳 있어?",
  "비 오는 주말인데 하천 근처 주차장 위험하지 않을까?",
  "애월 근처에 밤늦게 문 여는 약국 있어?",
  "이번 주 제주 축제 뭐 있어? 붐비는 데는 피하고 싶어",
  "한라산 근처에서 취사해도 돼? 법적으로 문제 없는지 알려줘",
  "장비 없이 갈 수 있는 글램핑장 추천해줘",
  "반려견 동반 가능한 캠핑장 있을까?",
  "지금 협재해수욕장 물놀이 괜찮아? 파도랑 수온 어때?",
];
{
  const box = document.getElementById("chips");
  [...QUESTIONS].sort(() => Math.random() - 0.5).slice(0, 4).forEach(q => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "chip";
    b.textContent = q.length > 26 ? q.slice(0, 25) + "…" : q;
    b.title = q;
    b.onclick = () => {
      document.getElementById("chat-input").value = q;
      document.getElementById("chat-form").requestSubmit();
    };
    box.appendChild(b);
  });
}

// ── 데이터 자랑: /api/health 건수로 실시간 채움 (실패 시 HTML 기본값 유지) ──
(async () => {
  try {
    const d = await (await fetch("/api/health")).json();
    const c = d.counts || {};
    const total = Object.values(c).reduce((a, b) => a + b, 0);
    if (!total) return;
    document.getElementById("brag-total").textContent = total.toLocaleString();
    const order = ["restroom", "parking_public", "ev_charger", "camping", "festival", "cleanhouse",
                   "tourinfo", "parking", "beach", "cctv", "pharmacy"];
    document.getElementById("brag-detail").textContent =
      order.filter(k => c[k]).map(k => `${catOf(k).label} ${c[k].toLocaleString()}`).join(" · ");
  } catch { /* 서버 재기동 중이면 정적 문구 유지 */ }
})();

// ── 메인 채팅: 멀티턴 대화 → 조건 요약 → 유저 컨펌 → 시설 확인 페이지 ──
// 계약 §4 (docs/api-chat-contract.md): 응답의 next(ask/confirm/map)가 렌더를 결정.
// 백엔드(B/C) 미완 시 stubDialog 폴백 — 지역 1회 되묻기 후 confirm (P3 데모 스텁)
const MOCK_CHAT = true;  // C의 /api/chat 완성 시 false 한 줄만
// 실시간 스트리밍 에이전트(/api/agent/stream, chat.py) 사용. AGENT_BASE=chat.py 서버(8011).
// 같은 서버로 합치면 AGENT_BASE="" 로. false면 팀원 멀티턴 /api/chat 사용.
const AGENT_STREAM = true;
const USE_PRIORITY_WIDGET = true;  // 첫 질문 후 우선순위 토글 위젯으로 조건 선택 → 추천
// 합친 서버(backend.server)에서 chat 은 /agent 하위 → 같은 도메인이라 CORS·URL 문제 없음
const AGENT_BASE = "/agent";
let chatHistory = [];    // {role: "user"|"assistant", content}
let recommendedOnce = false;   // 첫 추천 후엔 입력창을 후속 질문(대화형)으로 라우팅

document.getElementById("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  // 지역명이 있으면 새 추천(위젯) / 첫 질문도 위젯 / 그 외(후속 질문)는 대화형 에이전트
  const mentionsRegion = REGION_KEYS.some((k) => text.includes(k));
  const flow = (USE_PRIORITY_WIDGET && (!recommendedOnce || mentionsRegion)) ? startRecommendFlow
             : AGENT_STREAM ? sendChatTurnStream : sendChatTurn;
  flow(text);
});

async function sendChatTurn(text) {
  clearQuickReplies();  // 이전 턴의 칩 정리
  addMsg("user", text);
  chatHistory.push({ role: "user", content: text });
  addMsg("bot", "…");
  let data = null;
  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: chatHistory.slice(0, -1), categories: [] }),
    });
    if (!res.ok) throw new Error("not ready");
    data = await res.json();
    if (data && !data.reply && typeof data.response === "string") data.reply = data.response;  // C 초안 호환
    if (!data || typeof data.reply !== "string" || !data.reply) throw new Error("unexpected shape");
  } catch {
    if (MOCK_CHAT) data = stubDialog();  // P3: 규칙 기반 데모 스텁
  }
  if (!data) {
    replaceLastBot("🚧 대화 기능을 준비하고 있어요. 잠시 후 다시 시도해 주세요.");
    return;
  }
  replaceLastBot(data.reply);
  chatHistory.push({ role: "assistant", content: data.reply });

  if (data.next === "ask" && Array.isArray(data.quick_replies)) {
    renderQuickReplies(data.quick_replies);
  } else if (data.next === "confirm") {
    renderConfirmCard(data);
  } else if (data.map) {
    setTimeout(() => applyMapCommand(text, data), 900);  // 기존 단일턴(지도 직행) 하위 호환
  }
}

// ── 실시간 스트리밍 에이전트: 도구 진행 상태 + 답변 타이핑 (SSE, chat.py /api/agent/stream) ──
async function sendChatTurnStream(text) {
  clearQuickReplies();
  document.getElementById("landing-card")?.classList.add("chatting");  // 대화 시작 → 홍보 요소 숨김(깔끔한 채팅)
  const hist = chatHistory.slice();  // 이전 대화 맥락 (멀티턴)
  if (lastRecContext) {  // 직전 추천 목록을 맥락으로 주입 → 후속 질문의 "1번" 등 인식 (#4)
    hist.push({ role: "assistant", content: "[직전 추천 결과 — 사용자가 '1번/2번'이라 하면 이 목록의 순번]\n" + lastRecContext });
  }
  addMsg("user", text);
  chatHistory.push({ role: "user", content: text });

  const bubble = document.createElement("div");
  bubble.className = "msg bot";
  const steps = document.createElement("div");
  steps.className = "agent-steps";
  steps.innerHTML = '<div class="step">🤖 생각 중…</div>';
  const answer = document.createElement("div");
  answer.className = "agent-answer";
  bubble.append(steps, answer);
  document.getElementById("chat-log").appendChild(bubble);
  bubble.scrollIntoView();

  let ans = "", firstEvent = true, recMap = null;
  try {
    const res = await fetch(AGENT_BASE + "/api/agent/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history: hist }),
    });
    if (!res.ok || !res.body) throw new Error("stream unavailable");
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i).split("\n").find((l) => l.startsWith("data:"));
        buf = buf.slice(i + 2);
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }
        if (firstEvent) { steps.innerHTML = ""; firstEvent = false; }
        if (ev.type === "status" || ev.type === "tool") {
          steps.innerHTML += `<div class="step">${esc(ev.text)}</div>`;
        } else if (ev.type === "tool_done") {
          steps.innerHTML += `<div class="step done">${esc(ev.text)}</div>`;
        } else if (ev.type === "map") {
          recMap = ev.map;  // 추천 좌표·번호핀 — 답변 후 지도에 표시
        } else if (ev.type === "answer_start") {
          steps.classList.add("collapsed");
        } else if (ev.type === "delta") {
          ans += ev.text;
          answer.textContent = ans;
        }
        bubble.scrollIntoView();
      }
    }
  } catch (e) {
    if (!ans) answer.textContent = "🚧 실시간 답변 서버(8011)에 연결하지 못했어요. chat.py 실행을 확인해 주세요.";
  }
  if (ans) chatHistory.push({ role: "assistant", content: ans });
  // 추천 결과가 있으면 지도로 전환 → 번호 마커 + 레이어 토글로 검토 (팀원 applyMapCommand 재사용)
  if (recMap && Array.isArray(recMap.pins) && recMap.pins.length) {
    setTimeout(() => applyMapCommand(text, { reply: ans, map: recMap }), 700);
  }
}

// ── 우선순위 토글 위젯: 첫 질문 후 조건을 순서대로 골라 추천 (멀티턴 대체) ──
const REGION_KEYS = ["서귀포", "중문", "성산", "애월", "협재", "함덕", "제주", "담양"];
// 한적함·풍경은 캠핑 기본이라 항상 최상위 고정. 화장실·전기차만 선택 옵션.
const OPTION_DEFS = [
  { key: "restroom", label: "🚻 화장실" }, { key: "ev", label: "🔌 전기차 충전소" },
];
// 찾을 장소 유형 (미선택 시 전체)
const PLACE_CHOICE = [
  { key: "parking", label: "🚗 공영주차장", cats: ["parking_public", "parking"] },
  { key: "nakji", label: "🏕️ 노지(빈터)", cats: ["nakji"] },
];
const VIEW_TYPES = ["바다", "산", "숲", "계곡"];
const PLACE_DEFS = [
  { key: "parking_public", label: "🚗 공영주차장" }, { key: "camping", label: "⛺ 야영장" },
  { key: "parking", label: "🅿️ 둔치주차장" },
];

function startRecommendFlow(text) {
  clearQuickReplies();
  document.querySelectorAll("#chat-log .rec-actions").forEach((el) => el.remove());  // 새 검색 → 이전 버튼 정리
  document.getElementById("landing-card").classList.add("chatting");
  addMsg("user", text);
  showPriorityWidget(REGION_KEYS.find((k) => text.includes(k)) || null, text);
}

function showPriorityWidget(region, query) {
  const st = { region, viewTypes: [], options: [], places: [], query: query || "" };  // 한적함·풍경 고정
  const w = document.createElement("div");
  w.className = "msg bot priority-widget";
  const chips = (arr) => arr.join("");
  const render = () => {
    w.innerHTML =
      `<div class="pw-q">캠핑 조건을 골라주세요.</div>
      <div class="pw-sec"><span class="pw-lab">지역</span><div class="pw-chips">${chips(
        REGION_KEYS.map((r) => `<button class="pw-chip${st.region === r ? " on" : ""}" data-region="${r}">${r}</button>`))}</div></div>
      <div class="pw-sec"><span class="pw-lab">찾을 장소 <small>(미선택 시 전체)</small></span><div class="pw-chips">${chips(
        PLACE_CHOICE.map((p) => `<button class="pw-chip${st.places.includes(p.key) ? " on" : ""}" data-place="${p.key}">${p.label}</button>`))}</div></div>
      <div class="pw-sec"><span class="pw-lab">캠핑 기본 <small>(항상 우선)</small></span>
        <div class="pw-base">🤫 한적함 · 🏞️ 풍경</div></div>
      <div class="pw-sec"><span class="pw-lab">어떤 풍경?</span><div class="pw-chips">${chips(
        VIEW_TYPES.map((v) => `<button class="pw-chip${st.viewTypes.includes(v) ? " on" : ""}" data-view="${v}">${v}</button>`))}</div></div>
      <div class="pw-sec"><span class="pw-lab">추가로 중요하면 선택</span><div class="pw-chips">${chips(
        OPTION_DEFS.map((p) => `<button class="pw-chip${st.options.includes(p.key) ? " on" : ""}" data-opt="${p.key}">${p.label}</button>`))}</div></div>
      <button class="pw-go" type="button">이 조건으로 추천받기 →</button>`;
  };
  const toggle = (arr, v) => { const i = arr.indexOf(v); if (i >= 0) arr.splice(i, 1); else arr.push(v); };
  w.addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.region) st.region = b.dataset.region;
    else if (b.dataset.place) toggle(st.places, b.dataset.place);
    else if (b.dataset.view) toggle(st.viewTypes, b.dataset.view);
    else if (b.dataset.opt) toggle(st.options, b.dataset.opt);
    else if (b.classList.contains("pw-go")) {
      if (!st.region) return alert("지역을 선택해 주세요.");
      b.disabled = true; b.textContent = "⏳ 추천 찾는 중…";
      // 한적함·풍경 항상 최상위 + 선택한 옵션(화장실/전기차)
      const priorities = ["seclusion", "view", ...st.options];
      let place_types = st.places.flatMap((k) => PLACE_CHOICE.find((p) => p.key === k).cats);
      if (!place_types.length) place_types = ["parking_public", "parking", "nakji"];
      lastRecRegion = st.region; lastRecPriorities = priorities;  // 피드백용
      const payload = { region: st.region, priorities, view_types: st.viewTypes, place_types, query: st.query };
      try {
        const data = await (await fetch(AGENT_BASE + "/api/recommend_cfg", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        })).json();
        if (data.map && data.map.pins && data.map.pins.length) {
          verifyRecommendation({ region: st.region, priorities }, data);  // 리스트+점검+안내를 한 답변으로
        } else { addMsg("bot", data.reply || "추천 결과를 가져오지 못했어요."); b.disabled = false; b.textContent = "다시 추천받기 →"; }
      } catch { addMsg("bot", "🚧 추천 서버(8011)에 연결하지 못했어요."); b.disabled = false; b.textContent = "다시 추천받기 →"; }
      return;
    }
    render();
  });
  render();
  document.getElementById("chat-log").appendChild(w);
  w.scrollIntoView();
}

// ── 장소 피드백 (👍👎) — 장소 카드에서만, 1인 1표(로컬 저장), 전환/취소 지원 ──
let lastRecRegion = null, lastRecPriorities = null;
const FB_CAMPABLE = new Set(["parking_public", "parking", "nakji", "camping", "beach"]);

function fbUserId() {  // 브라우저별 익명 ID (중복 평가 방지)
  let u = localStorage.getItem("fb_uid");
  if (!u) { u = "u" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8); localStorage.setItem("fb_uid", u); }
  return u;
}
function fbVotes() { try { return JSON.parse(localStorage.getItem("fb_votes") || "{}"); } catch { return {}; } }
function fbSetVote(sid, v) {
  const m = fbVotes(); if (v) m[sid] = v; else delete m[sid];
  localStorage.setItem("fb_votes", JSON.stringify(m));
}
function feedbackHTML(item) {
  if (!FB_CAMPABLE.has(item.category)) return "";  // 캠핑 가능 장소 카드에만 (추천 리스트는 별도라 영향 없음)
  const sid = String(item.id), mine = fbVotes()[sid] || "";
  return `<div class="fb-row" data-sid="${esc(sid)}" data-sname="${esc(item.name)}" data-scat="${item.category}" data-up="0" data-down="0">
    <span class="fb-q">이 장소 어때요?</span>
    <button class="fb-btn fb-up${mine === "up" ? " on" : ""}" data-vote="up">👍 <b class="fb-n">0</b></button>
    <button class="fb-btn fb-down${mine === "down" ? " on" : ""}" data-vote="down">👎 <b class="fb-n">0</b></button></div>`;
}
function applyFbCounts(row, up, down) {
  row.dataset.up = up; row.dataset.down = down;
  const nu = row.querySelector(".fb-up .fb-n"), nd = row.querySelector(".fb-down .fb-n");
  if (nu) nu.textContent = up;
  if (nd) nd.textContent = down;
}
function initFeedback(sid) {  // 서버에서 현재 카운트 로드
  fetch(AGENT_BASE + "/api/feedback?spot_id=" + encodeURIComponent(sid))
    .then(r => r.json())
    .then(d => { const row = document.querySelector(`.fb-row[data-sid="${CSS.escape(sid)}"]`); if (row) applyFbCounts(row, d.up || 0, d.down || 0); })
    .catch(() => {});
}
document.addEventListener("click", (e) => {
  const b = e.target.closest(".fb-btn"); if (!b) return;
  const row = b.closest(".fb-row"); if (!row) return;
  const sid = row.dataset.sid, vote = b.dataset.vote;
  const prev = fbVotes()[sid] || "";
  const next = prev === vote ? "" : vote;                 // 같은 걸 또 누르면 취소, 다르면 전환
  let up = +row.dataset.up || 0, down = +row.dataset.down || 0;
  if (prev === "up") up--; else if (prev === "down") down--;   // 이전 표 상쇄
  if (next === "up") up++; else if (next === "down") down++;   // 새 표 반영
  applyFbCounts(row, Math.max(0, up), Math.max(0, down));
  row.querySelector(".fb-up").classList.toggle("on", next === "up");
  row.querySelector(".fb-down").classList.toggle("on", next === "down");
  fbSetVote(sid, next);
  fetch(AGENT_BASE + "/api/feedback", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vote: next || "none", spot_id: sid, spot_name: row.dataset.sname,
      category: row.dataset.scat, user_id: fbUserId(), region: lastRecRegion, priorities: lastRecPriorities }),
  }).then(r => r.json()).then(d => { if (d && d.up != null) applyFbCounts(row, d.up, d.down); }).catch(() => {});
});

// ── 추천: 후보 풀을 즉시 띄우고 → GPT가 비교·채점해 상위 3곳을 순위·차별화 점수로 확정 ──
let lastRecContext = "";   // 후속 질문용 맥락 (직전 추천 목록 — "1번" 등 인식)
async function verifyRecommendation(st, data) {
  recommendedOnce = true;                               // 이후 입력창은 후속 질문(대화형)으로
  const inp = document.getElementById("chat-input");
  if (inp) inp.placeholder = "추가로 궁금한 점을 물어보세요 (예: 1번 화장실 있어?)";
  document.getElementById("landing-card").classList.add("recommended");  // 후속 질문 입력창 노출
  document.querySelectorAll("#chat-log .rec-actions").forEach((el) => el.remove());  // 이전 추천 버튼 정리

  const norm = (s) => (s || "").replace(/\s/g, "");
  const match = (a, b) => { a = norm(a); b = norm(b); return !!(a && b && (a === b || a.includes(b) || b.includes(a))); };
  const pool = (data.map.pins || []).slice();          // 후보 풀 (≤6, 노지/주차장 섞임)
  const header0 = (data.reply || "").split("\n\n")[0] || "";
  const bubble = document.createElement("div");
  bubble.className = "msg bot";
  document.getElementById("chat-log").appendChild(bubble);

  // rows = [{name, score|null, note|null, idx(=data.map.pins 내 위치)}]
  const paintRows = (rows, phase) => {
    let html = `<div class="rec-list">${esc(header0)}</div>`;
    html += rows.map((r, i) => `<div class="rec-item">
        <div class="ri-head"><b>${i + 1}) ${esc(r.name)}</b> ${r.score != null
          ? `<span class="ri-score">${r.score}점</span>`
          : `<span class="ri-score pending">평가 중…</span>`}</div>
        ${r.note ? `<div class="ri-note">${esc(r.note)}</div>` : (phase ? `<div class="ri-note loading">설명 준비 중…</div>` : "")}
        <a class="ri-map" data-idx="${r.idx}">🗺️ 지도로 가기</a>
      </div>`).join("");
    if (phase) html += `<div class="rec-progress">${esc(phase)}</div>`;
    if (data.outro) html += `<div class="rec-outro">${esc(data.outro)}</div>`;
    bubble.innerHTML = html;
    bubble.querySelectorAll(".ri-map").forEach((a) => { a.onclick = () => goToMapPin(st.region, data, +a.dataset.idx); });
  };
  // 즉시: 풀 상위 3곳 이름만 (점수·설명은 GPT 평가 중)
  const prelim = pool.slice(0, 3).map((p, i) => ({ name: p.item.name, score: null, note: null, idx: i }));
  // 검증이 실제로 진행 중임을 보여주는 단계 표시 (#5)
  const phases = [
    `🧠 후보 ${pool.length}곳을 불러왔어요`,
    "🔍 한적함·주변 건물 수를 하나씩 비교하는 중",
    "🌊 바다·자연 뷰와 접근성을 따져보는 중",
    "🧭 실제 차박 적합도로 순위·점수를 매기는 중",
    "✍️ 각 장소 설명을 정리하는 중",
  ];
  let phaseI = 0;
  paintRows(prelim, phases[0]);
  const phaseTimer = setInterval(() => { phaseI = Math.min(phaseI + 1, phases.length - 1); paintRows(prelim, phases[phaseI]); }, 2400);
  bubble.scrollIntoView();

  // 기다리기 싫은 사용자용 건너뛰기 칩
  const skipRow = document.createElement("div");
  skipRow.className = "qr-row";
  const sk = document.createElement("button");
  sk.type = "button"; sk.className = "chip"; sk.textContent = "🗺️ 건너뛰고 지도 보기";
  sk.onclick = () => { data.map.pins = pool.slice(0, 3); applyMapCommand(st.region, data); };
  skipRow.appendChild(sk);
  document.getElementById("chat-log").appendChild(skipRow);

  const results = pool.map((p) => ({
    name: p.item.name, category: p.item.category,
    addr: p.item.road_addr || p.item.lotno_addr,
    lat: p.lat, lon: p.lon, score: p.score,
    fb_up: p.item.fb_up || 0, fb_down: p.item.fb_down || 0,
    why: (p.why || []).map((w) => w.detail),
  }));
  let verdict = null;
  try {
    const res = await fetch(AGENT_BASE + "/api/agent/verify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ region: st.region, priorities: st.priorities, results }),
    });
    if (!res.ok || !res.body) throw new Error("verify unavailable");
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i).split("\n").find((l) => l.startsWith("data:"));
        buf = buf.slice(i + 2);
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }
        if (ev.type === "verdict") verdict = ev;
      }
    }
  } catch { verdict = { overall: "적합", items: [], exclude: [] }; }  // 점검 서버 문제 시 통과
  clearInterval(phaseTimer);
  skipRow.remove();
  const v = verdict || { overall: "적합", items: [], exclude: [] };

  // 공항 등 제외 후보 빼기
  const exNames = (v.exclude || []).map((s) => String(s || "").trim()).filter((x) => x.length >= 3);
  let avail = pool.filter((p) => !exNames.some((x) => match(p.item.name, x)));
  if (!avail.length) avail = pool.slice();

  // GPT 순위·점수 → 풀 핀에 매핑 (상위 3곳)
  const finalPins = [], rows = [];
  (v.items || []).forEach((it) => {
    if (!it || !it.name || finalPins.length >= 3) return;
    const pin = avail.find((p) => !finalPins.includes(p) && match(p.item.name, it.name));
    if (!pin) return;
    const sc = (it.score != null ? it.score : pin.score);
    const isParking = pin.item.category === "parking_public" || pin.item.category === "parking";
    if (isParking && sc < 80) return;   // 주차장은 적합도 80점 이상일 때만 (#3) — 아니면 뺌
    finalPins.push(pin); rows.push({ name: pin.item.name, score: sc, note: it.note || "", idx: finalPins.length - 1 });
  });
  if (!rows.length) avail.slice(0, 3).forEach((p, i) => { finalPins.push(p); rows.push({ name: p.item.name, score: p.score, note: "", idx: i }); });

  // 지도·상세용 핀 재정렬 + GPT 점수 반영
  data.map.pins = finalPins;
  finalPins.forEach((p, i) => { p.score = rows[i].score; p.label = `${i + 1}위 · ${rows[i].score}점`; });

  // 후속 질문용 맥락 (#4: "1번" 인식)
  lastRecContext = rows.map((r, i) =>
    `${i + 1}번: ${r.name} (${r.score}점)${r.note ? " — " + r.note : ""} [${finalPins[i].item.road_addr || finalPins[i].item.lotno_addr || "-"}]`).join("\n");

  if (!rows.length) {
    bubble.innerHTML = `<div class="rec-list">${esc(header0 || "적합한 추천지를 찾지 못했어요.")}\n\n(점검 결과 적합한 곳이 없어 제외했어요.)</div>`;
  } else {
    paintRows(rows, null);   // 최종: 순위·GPT 점수·설명 확정
  }
  bubble.scrollIntoView();
  renderVerifyActions(st, data, rows.length > 0 && v.overall !== "부적합");
}

// 항목별 '지도로 가기' → 지도로 전환 후 그 핀 상세 열기
function goToMapPin(question, data, idx) {
  applyMapCommand(question, data);
  const p = (data.map.pins || [])[idx];
  if (p) setTimeout(() => openRecPin(p), 220);
}

function renderVerifyActions(st, data, passed) {
  const row = document.createElement("div");
  row.className = "qr-row rec-actions";   // rec-actions: 후속 대화에도 안 사라지게 (clearQuickReplies 제외)
  const mk = (label, fn) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "chip"; b.textContent = label;
    b.onclick = fn; row.appendChild(b);
  };
  if (!passed) {
    mk("🔁 조건 다시 고르기", () => { row.remove(); showPriorityWidget(st.region); });
    mk("🗺️ 그래도 지도에서 보기", () => applyMapCommand(st.region, data));
  } else {
    mk("🗺️ 지도에서 보기", () => applyMapCommand(st.region, data));
    mk("🔄 다시 검색하기", () => { row.remove(); showPriorityWidget(st.region); });
  }
  document.getElementById("chat-log").appendChild(row);
  row.scrollIntoView();
}

// ── quick-reply 칩 (next:"ask") — 탭하면 그 텍스트로 다음 턴 전송 ──
// .rec-actions(지도보기·다시검색)는 후속 대화에도 유지하려고 제외
function clearQuickReplies() {
  document.querySelectorAll("#chat-log .qr-row:not(.rec-actions), #chat-log .confirm-card .cc-actions").forEach(el => el.remove());
}
function renderQuickReplies(options) {
  const row = document.createElement("div");
  row.className = "qr-row";
  options.forEach(opt => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.textContent = opt;
    b.onclick = () => sendChatTurn(opt);
    row.appendChild(b);
  });
  document.getElementById("chat-log").appendChild(row);
  row.scrollIntoView();
}

// ── 요약 카드 (next:"confirm") — 컨펌 시 slots를 시설 프리셋으로 진입 ──
function renderConfirmCard(data) {
  const card = document.createElement("div");
  card.className = "confirm-card";
  card.innerHTML =
    `<div class="cc-summary">${esc(data.summary || "이 조건으로 진행할까요?")}</div>
     <div class="cc-actions">
       <button type="button" class="cc-go">✅ 이 조건으로 시설 확인</button>
       <button type="button" class="cc-more">✏️ 더 대화</button>
     </div>`;
  card.querySelector(".cc-go").onclick = () => openScenarioFromSlots(data.slots);
  card.querySelector(".cc-more").onclick = () => {
    card.querySelector(".cc-actions").remove();
    const msg = "네, 좋아요! 원하는 조건을 이어서 말씀해 주세요 (예: 전기차야 / 아이랑 가 / 조용한 곳)";
    addMsg("bot", msg);
    chatHistory.push({ role: "assistant", content: msg });
    document.getElementById("chat-input").focus();
  };
  document.getElementById("chat-log").appendChild(card);
  card.scrollIntoView();
}

// 컨펌 → 시나리오 페이지: 대화 전체를 질문으로 합치고, slots를 프리셋에 덧입힘
function openScenarioFromSlots(slots) {
  const q = chatHistory.filter(m => m.role === "user").map(m => m.content).join(" ");
  openScenario(q);  // 키워드 자동 제안 (기존)
  if (slots) {      // 대화에서 확정된 슬롯을 우선 반영
    if (slots.region) { /* 지역은 질문 텍스트에 포함돼 스코어링이 인식 */ }
    if (slots.ev) scSet("ev_charger", true);
    if (slots.view === "바다") { scSet("beach", true); scSet("cctv", true); }
    if (slots.view === "숲·계곡") scSet("camping", true);
    if (slots.pharmacy) scSet("pharmacy", true);
  }
}

// ── P3 데모 스텁: 규칙 기반 대화 (백엔드 완성 시 자동 대체) ──
// 정책(임시): 지역만 필수 — 없으면 1회 되묻기, 이후 confirm. B/C 정책 확정 시 서버가 대체.
function stubDialog() {
  const userText = chatHistory.filter(m => m.role === "user").map(m => m.content).join(" ");
  const conds = Scoring.parseConds(userText, []);
  const askedRegion = chatHistory.some(m => m.role === "assistant" && m.content.includes("어느 지역"));
  if (!conds.regionMatched && !askedRegion) {
    return {
      reply: "좋아요! 어느 지역으로 떠나실 계획이세요? 🗺️ (아래에서 고르거나 직접 입력해 주세요)",
      next: "ask",
      quick_replies: ["서귀포", "애월", "협재", "성산", "함덕", "담양"],
      slots: { region: null, ev: conds.ev, view: conds.seaView ? "바다" : conds.natureView ? "숲·계곡" : null },
    };
  }
  const slots = {
    region: conds.regionMatched ? conds.region : "서귀포",
    ev: conds.ev,
    view: conds.seaView ? "바다" : conds.natureView ? "숲·계곡" : null,
    pharmacy: conds.pharmacyNeed,
  };
  const parts = [`📍 ${slots.region}${conds.regionMatched ? "" : " (기본)"}`];
  if (slots.ev) parts.push("⚡ 전기차");
  if (slots.view) parts.push(slots.view === "바다" ? "🌊 바다 뷰" : "🌲 숲·계곡");
  if (slots.pharmacy) parts.push("💊 심야약국");
  return {
    reply: "정리해 드릴게요! 이 조건으로 주변 편의시설을 확인해 볼까요?",
    next: "confirm",
    slots,
    summary: parts.join(" · "),
  };
}
function addMsg(who, text) {
  const div = document.createElement("div");
  div.className = "msg " + who;
  div.textContent = text;
  document.getElementById("chat-log").appendChild(div);
  div.scrollIntoView();
}
function replaceLastBot(text) {
  const bots = document.querySelectorAll(".msg.bot");
  if (bots.length) bots[bots.length - 1].textContent = text;
}

// ══════════ 모바일 전용 UI (네이버지도 스타일) ══════════
// ≤700px: 좌측 레이어 패널 → 상단 카테고리 칩바, 상세 카드 → 바텀시트 상단.
// 데스크톱 체크박스가 단일 진실 소스 — 칩은 체크박스를 토글하고 상태를 따라감.
function isMobile() { return matchMedia("(max-width: 700px)").matches; }

const sheetEl = document.getElementById("sheet");
const sheetBodyEl = document.getElementById("sheet-body");
const sheetListEl = document.getElementById("sheet-list");

// ── 상세 카드 위치: 모바일=바텀시트 상단 / 데스크톱=좌측 스택 ──
function placeDetail() {
  const d = document.getElementById("detail");
  if (!d || !sheetBodyEl) return;
  if (isMobile()) {
    if (d.parentElement !== sheetBodyEl) sheetBodyEl.prepend(d);
  } else {
    const stack = document.getElementById("left-stack");
    if (stack && d.parentElement !== stack) stack.appendChild(d);
  }
}
window.addEventListener("resize", placeDetail);
placeDetail();

// ── 카테고리 칩 바 (체크박스와 양방향 동기화) ──
const chipsBarEl = document.getElementById("chips-bar");
const catChips = {};
if (chipsBarEl) {
  for (const c in CAT) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip-cat";
    btn.innerHTML = `<span class="dot ${c}"></span>${CAT[c].icon} ${CAT[c].label}`;
    btn.onclick = () => {
      const box = layerBoxes.find(i => i.value === c);
      if (!box) return;
      box.checked = !box.checked;
      box.dispatchEvent(new Event("change"));  // refresh + syncClearBtn + syncChips 모두 발화
    };
    chipsBarEl.appendChild(btn);
    catChips[c] = btn;
  }
}
function syncChips() {
  layerBoxes.forEach(box => {
    const chip = catChips[box.value];
    if (!chip) return;
    chip.classList.toggle("on", box.checked);
    chip.style.background = box.checked ? catOf(box.value).color : "";
  });
}
layerBoxes.forEach(i => i.addEventListener("change", syncChips));
syncChips();

// ── 바텀시트: peek / half / full 3단 스냅 + 드래그 ──
let sheetState = "peek";
function setSheet(state) {
  if (!sheetEl) return;
  sheetState = state;
  sheetEl.classList.remove("peek", "half", "full");
  sheetEl.classList.add(state);
}
if (sheetEl) {
  const H = () => sheetEl.offsetHeight;
  const offsets = () => ({ full: 0, half: Math.round(H() * 0.46), peek: H() - 106 });
  let dragStartY = null, dragStartOff = 0;

  const onDown = (e) => {
    dragStartY = e.clientY;
    dragStartOff = offsets()[sheetState];
    sheetEl.classList.add("dragging");
    e.target.setPointerCapture?.(e.pointerId);
  };
  const onMove = (e) => {
    if (dragStartY === null) return;
    const off = Math.max(0, Math.min(H() - 106, dragStartOff + (e.clientY - dragStartY)));
    sheetEl.style.transform = `translateY(${off}px)`;
  };
  const onUp = (e) => {
    if (dragStartY === null) return;
    const moved = e.clientY - dragStartY;
    const off = Math.max(0, Math.min(H() - 106, dragStartOff + moved));
    sheetEl.classList.remove("dragging");
    sheetEl.style.transform = "";
    dragStartY = null;
    if (Math.abs(moved) < 6) {  // 탭: peek ↔ half 토글
      setSheet(sheetState === "peek" ? "half" : sheetState === "half" ? "peek" : "half");
      return;
    }
    const o = offsets();  // 가장 가까운 스냅으로
    const nearest = ["full", "half", "peek"].reduce((a, b) =>
      Math.abs(o[a] - off) <= Math.abs(o[b] - off) ? a : b);
    setSheet(nearest);
  };
  ["sheet-handle", "sheet-head"].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", () => { dragStartY = null; sheetEl.classList.remove("dragging"); sheetEl.style.transform = ""; });
  });
}

// ── 리스트: 지도 중심에서 가까운 순 (네이버 "현재 지도 중심") ──
function distM(lat1, lng1, lat2, lng2) {
  const R = 6371000, rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad, dLng = (lng2 - lng1) * rad;
  const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}
function fmtDist(m) { return m < 1000 ? Math.round(m) + "m" : (m / 1000).toFixed(1) + "km"; }

function renderSheetList() {
  if (!sheetListEl) return;
  const countEl = document.getElementById("sheet-count");
  const headEl = document.getElementById("sheet-head");
  // 추천 결과 모드: 레이어가 꺼져 있고 추천 핀이 있으면 요약 헤더 + 추천 리스트 표시 (배너 대체)
  if (!lastItems.length && lastRecPins) {
    if (headEl) headEl.innerHTML = `추천 결과 <b id="sheet-count">${lastRecPins.length}</b>곳 · 적합도 순`;
    const brief = lastRecMeta ? lastRecMeta.reply.split("\n")[0] : "";
    const headHTML = `<div class="s-rec-head">
      ${brief ? `<div class="srh-text">${esc(brief)}</div>` : ""}
      <div class="srh-actions">
        <span class="rb-hint">추천이 도움됐나요?</span>
        <button type="button" class="rb-vote" data-vote="1">👍</button>
        <button type="button" class="rb-vote" data-vote="-1">👎</button>
      </div>
    </div>`;
    sheetListEl.innerHTML = headHTML + lastRecPins.map((p, i) => {
      const reasons = (p.why || []).filter(w => w.pass && w.delta > 0).slice(0, 2)
                        .map(w => w.detail).join(" · ");
      return `<div class="s-item s-rec">
        <div class="s-line1"><span class="rb-rank">${i + 1}</span><b>${esc(p.item.name)}</b>
          <span class="rb-score">${p.score}<small>점</small></span></div>
        <div class="s-line2">${esc(reasons || catOf(p.item.category).label)}</div>
        <div class="s-line3">탭하면 적합성 리포트와 근거 시설 지도를 보여드려요</div>
      </div>`;
    }).join("");
    [...sheetListEl.querySelectorAll(".s-item")].forEach((el, i) => { el.onclick = () => openRecPin(lastRecPins[i]); });
    sheetListEl.querySelectorAll(".rb-vote").forEach(btn => {
      btn.onclick = () => {
        if (lastRecMeta) sendFeedback(lastRecMeta.question, lastRecMeta.reply, Number(btn.dataset.vote));
        sheetListEl.querySelectorAll(".rb-vote").forEach(b => b.classList.remove("picked"));
        btn.classList.add("picked");
        const hint = sheetListEl.querySelector(".rb-hint");
        if (hint) hint.textContent = "피드백 감사합니다!";
      };
    });
    return;
  }
  if (headEl && !headEl.textContent.includes("현재 지도 중심"))
    headEl.innerHTML = `현재 지도 중심 <b id="sheet-count">0</b>곳 · 가까운 순`;
  const countEl2 = document.getElementById("sheet-count");
  if (countEl2) countEl2.textContent = lastItems.length.toLocaleString();
  if (!lastItems.length) {
    sheetListEl.innerHTML = `<div class="s-empty">표시할 시설이 없습니다.<br/>위 카테고리 칩을 눌러 레이어를 켜보세요.</div>`;
    return;
  }
  const ctr = map ? map.getCenter() : null;
  const items = lastItems
    .map(it => ({ ...it, _d: ctr ? distM(ctr.getLat(), ctr.getLng(), it.lat, it.lon) : 0 }))
    .sort((a, b) => a._d - b._d)
    .slice(0, 80);  // 시트 리스트는 가까운 80개까지 (마커는 전부 표시됨)
  sheetListEl.innerHTML = items.map(it => {
    const c = catOf(it.category);
    return `<div class="s-item">
      <div class="s-line1"><span class="dot ${esc(it.category)}"></span><b>${esc(it.name)}</b>
        <span class="s-cat" style="color:${c.color}">${c.icon} ${esc(c.label)}</span></div>
      <div class="s-line2">${esc(it.road_addr || it.lotno_addr || "주소 정보 없음")}</div>
      <div class="s-line3">${it.open_hours ? "🕒 " + esc(it.open_hours) + " · " : ""}지도 중심에서 ${fmtDist(it._d)}</div>
    </div>`;
  }).join("");
  [...sheetListEl.children].forEach((el, i) => {
    el.onclick = () => {
      const it = items[i];
      const pos = new kakao.maps.LatLng(it.lat, it.lon);
      map.panTo(pos);
      showDetail(it, pos);
    };
  });
}

// ── 상단 검색바: 탭하면 랜딩(검색)으로 ──
const topbarEl = document.getElementById("map-topbar");
if (topbarEl) {
  const goBack = () => setView("landing");
  topbarEl.onclick = goBack;
  topbarEl.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") goBack(); };
}

// ══════════ 추천 → 지도 연동 (이슈 #13, docs/api-chat-contract.md) ══════════
// 답변의 map{bbox,layers,pins}를 받아: 지도 전환 + 영역 이동 + 레이어 세팅 + 금색 번호 핀 + 답변 배너(👍👎)

let recMarkers = [];
let lastRecPins = null;  // 마지막 추천 결과 (바텀시트 리스트용)
let lastRecMeta = null;  // {question, reply} — 시트 헤더 요약·피드백용
function clearRecMarkers() { recMarkers.forEach(m => m.setMap(null)); recMarkers = []; }

// ── 이유 마커: 적합성 리포트(why[].ref)의 실제 시설을 지도에 마커+점선으로 표시 ──
let reasonOverlays = [];
function clearReasonOverlays() { reasonOverlays.forEach(o => o.setMap(null)); reasonOverlays = []; }
function drawReasons(item) {
  clearReasonOverlays();
  if (!item._why || !map) return;
  const from = new kakao.maps.LatLng(item.lat, item.lon);
  item._why.forEach(w => {
    if (!w.ref) return;
    const pos = new kakao.maps.LatLng(w.ref.lat, w.ref.lon);
    const mk = new kakao.maps.Marker({
      position: pos, zIndex: 15,
      image: markerImages[w.ref.category],  // 카테고리 색 핀 그대로 (없으면 기본 마커)
    });
    mk.setMap(map);
    if (w.ref.item) kakao.maps.event.addListener(mk, "click", () =>
      showDetail(w.ref.item, pos));  // 이유 시설 클릭 → 그 시설 상세
    const line = new kakao.maps.Polyline({
      path: [from, pos], strokeWeight: 2.5,
      strokeColor: w.delta >= 0 ? "#f0a020" : "#c0392b",
      strokeOpacity: 0.85, strokeStyle: "shortdash",
    });
    line.setMap(map);
    reasonOverlays.push(mk, line);
  });
}

// 금색 추천 핀 (번호 표시, 카테고리 핀보다 크고 위에)
function recPinImage(rank) {
  return new kakao.maps.MarkerImage(
    pinImage("#f0a020", String(rank)),
    new kakao.maps.Size(46, 60),
    { offset: new kakao.maps.Point(23, 60) });
}
// 점수 뱃지 핀 (P3) — 핀 안에 적합도 점수. 자연공원 감점 후보는 회색
function recScoreImage(score, banned) {
  return new kakao.maps.MarkerImage(
    pinImage(banned ? "#9aa0a6" : "#f0a020", String(score)),
    new kakao.maps.Size(46, 60),
    { offset: new kakao.maps.Point(23, 60) });
}

function applyMapCommand(question, data) {
  const m = data.map;
  if (!m || !map) return;
  setView("map");
  setTimeout(() => {
    map.relayout();
    if (m.bbox && m.bbox.length === 4) {
      const [sa, so, na, no] = m.bbox;
      map.setBounds(new kakao.maps.LatLngBounds(
        new kakao.maps.LatLng(sa, so), new kakao.maps.LatLng(na, no)));
    }
    if (Array.isArray(m.layers)) {  // 레이어를 이 목록으로 정확히 세팅 (계약 §1)
      layerBoxes.forEach(box => { box.checked = m.layers.includes(box.value); });
      syncChips(); syncClearBtn(); refresh();
    }
    clearRecMarkers();
    (m.pins || []).forEach((p, i) => {
      const pos = new kakao.maps.LatLng(p.lat, p.lon);
      const banned = (p.why || []).some(w => w.check === "natural_park" && !w.pass);
      const img = recScoreImage(i + 1, banned);  // 지도 마커 = 순위 번호(1,2,3) · 점수는 리스트·상세에 표시
      const mk = new kakao.maps.Marker({ position: pos, image: img, zIndex: 20 - i });
      mk.setMap(map);
      if (p.item) {
        if (p.score != null) { p.item._score = p.score; p.item._why = p.why || []; p.item._rank = i + 1; }
        kakao.maps.event.addListener(mk, "click", () => showDetail(p.item, pos));
      }
      recMarkers.push(mk);
    });
    // 추천 결과를 바텀시트 리스트에도 반영 (모바일)
    lastRecPins = (m.pins || []).filter(p => p.score != null && p.item);
    if (!lastRecPins.length) lastRecPins = null;
    lastRecMeta = lastRecPins ? { question, reply: data.reply } : null;
    renderSheetList();
    showRecBanner(question, data);
  }, 80);
}

// ── 추천 리스트 아이템 클릭: 확대 + 상세 리포트 + 이유 마커 ──
function openRecPin(p) {
  const pos = new kakao.maps.LatLng(p.lat, p.lon);
  map.setLevel(5);
  map.panTo(pos);
  showDetail(p.item, pos);
  // 모바일: 배너가 리포트·지도를 가리므로 접음 (리스트는 바텀시트에 그대로 있음)
  if (isMobile()) document.getElementById("rec-banner")?.classList.remove("show");
}

// ── 답변 배너: 요약 + 추천 리스트 버튼 + 👍👎 (질문 학습 루프 로그) ──
// 모바일은 배너를 쓰지 않고 바텀시트로 일원화 (겹침 방지, 7/9 피드백) — 시트 헤더에 요약+👍👎
function showRecBanner(question, data) {
  const el = document.getElementById("rec-banner");
  if (!el) return;
  if (isMobile()) {
    el.classList.remove("show");   // 모바일: 배너 미표시 — renderSheetList가 헤더까지 담당
    setSheet("half");              // 결과가 바로 보이게 시트 반 오픈
    return;
  }
  const pins = ((data.map && data.map.pins) || []).filter(p => p.score != null && p.item);
  // 점수 리스트가 있으면 첫 줄 요약 + 버튼 리스트, 없으면(일반 답변) 본문 표시
  const brief = pins.length ? data.reply.split("\n")[0]
              : (data.reply.length > 140 ? data.reply.slice(0, 139) + "…" : data.reply);
  const listHTML = pins.length
    ? `<div class="rb-list">` + pins.map((p, i) => {
        const reasons = (p.why || []).filter(w => w.pass && w.delta > 0).slice(0, 2)
                          .map(w => w.detail.replace(/\s*\(.*?\)/g, "")).join(" · ");
        return `<button type="button" class="rb-item" data-i="${i}">
          <span class="rb-rank">${i + 1}</span>
          <span class="rb-name">${esc(p.item.name)}<small>${esc(reasons || catOf(p.item.category).label)}</small></span>
          <span class="rb-score">${p.score}<small>점</small></span>
        </button>`;
      }).join("") + `</div>`
    : "";
  el.innerHTML =
    `<button class="rb-close" title="닫기">✕</button>
     <div class="rb-text">${esc(brief)}</div>
     ${listHTML}
     <div class="rb-actions">
       <span class="rb-hint">추천이 도움됐나요?</span>
       <button class="rb-vote" data-vote="1">👍</button>
       <button class="rb-vote" data-vote="-1">👎</button>
     </div>`;
  el.classList.add("show");
  el.querySelector(".rb-close").onclick = () => {
    el.classList.remove("show");
    clearRecMarkers();
    clearReasonOverlays();
    lastRecPins = null;
    renderSheetList();
  };
  el.querySelectorAll(".rb-item").forEach(btn => {
    btn.onclick = () => openRecPin(pins[Number(btn.dataset.i)]);
  });
  el.querySelectorAll(".rb-vote").forEach(btn => {
    btn.onclick = () => {
      sendFeedback(question, data.reply, Number(btn.dataset.vote));
      el.querySelectorAll(".rb-vote").forEach(b => b.classList.remove("picked"));
      btn.classList.add("picked");
      el.querySelector(".rb-hint").textContent = "피드백 감사합니다!";
    };
  });
}

// 피드백 로그 (백엔드 미구현이어도 UI는 막히지 않음 — 계약 §2)
// results: 이번 추천 상위 후보(id·점수) — C의 chat_logs 학습 루프(주간 가중치 튜닝) 신호
function sendFeedback(question, reply, vote, pinId = null) {
  const results = (lastRecPins || []).map(p => ({ id: p.id, score: p.score }));
  fetch("/api/feedback", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, reply, vote, pin_id: pinId, results }),
  }).catch(() => {});
}

// ── 임시 추천: 스코어링 엔진(scoring.js, P2)으로 검증·채점된 결과 생성 ──
// ⚠️ C의 /api/chat 완성 시 MOCK_CHAT=false — 이 폴백은 호출되지 않음 (docs/scoring-design.md §1)
async function tempRecommend(q, cats) {
  const { conds, results, totalCandidates, excludedCount } = await Scoring.recommend(q, cats);
  if (!results.length) throw new Error("no results");
  const top = results.slice(0, 5);
  const lines = top.slice(0, 3).map((s, i) => {
    const good = s.why.filter(w => w.pass && w.delta > 0).slice(0, 3).map(w => w.detail).join(" · ");
    return `${i + 1}위 ${s.item.name} — ${s.score}점${good ? ` (${good})` : ""}`;
  }).join("\n");
  // 표출 정책(설계 §7): 추천 핀만 지도에 — 레이어 전체 OFF + 화면은 핀 범위로 맞춤
  const pad = 0.015;
  const lats = top.map(s => s.item.lat), lons = top.map(s => s.item.lon);
  const pinBbox = [Math.min(...lats) - pad, Math.min(...lons) - pad,
                   Math.max(...lats) + pad, Math.max(...lons) + pad];
  return {
    reply: `📊 ${conds.region} 후보 ${totalCandidates}곳을 조건 검증해 상위 ${top.length}곳을 골랐어요.` +
           (excludedCount ? ` (주차빌딩 등 차박 불가 ${excludedCount}곳 제외)` : "") +
           `\n${lines}\n` +
           `지도엔 추천 핀만 표시했어요 — 다른 시설은 상단 칩으로 켤 수 있어요. ` +
           `⚠️ 공영주차장 차박은 권장하지 않아요 — 주차+화장실 조합 안내입니다.` +
           (conds.regionMatched ? "" : "\n(지역을 인식하지 못해 서귀포 기준으로 찾았어요)"),
    map: {
      bbox: pinBbox,
      layers: [],  // 추천 핀만 표출 (7/8 피드백)
      pins: top.map((s, i) => ({
        id: s.item.id, lat: s.item.lat, lon: s.item.lon,
        label: `${i + 1}위 · ${s.score}점`, item: s.item, score: s.score, why: s.why,
      })),
    },
  };
}

// ══════════ 시나리오 페이지 (User flow 2단계: 질문 → 필요 시설 확인 → 추천) ══════════
// 질문 키워드로 카테고리 초기 체크를 자동 제안하고, 유저가 확정하면 /api/chat 호출

const SC_BASE = ["parking_public", "restroom", "camping"];  // 기본 제안 (차박 필수 조합)
const SC_RULES = [
  [/전기차|충전|[eE][vV]/, ["ev_charger"]],
  [/약국|상비약|아프|야간.?진료/, ["pharmacy"]],
  [/비\s|비가|비오|호우|장마|폭우|하천|침수|둔치/, ["parking", "cctv"]],
  [/바다|해수욕|해변|물놀이|수영|파도|서핑|월파/, ["beach", "cctv"]],
  [/축제|행사|공연|불꽃|붐비/, ["festival"]],
  [/쓰레기|분리수거|클린/, ["cleanhouse"]],
  [/관광|안내소|코스|볼거리/, ["tourinfo"]],
];

const scCats = {};  // { category: {el, on} }
{
  const box = document.getElementById("scenario-cats");
  if (box) for (const c in CAT) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "sc-cat";
    b.innerHTML = `<span class="ic">${CAT[c].icon}</span>${CAT[c].label}<span class="ck">✓</span>`;
    b.onclick = () => scSet(c, !scCats[c].on);
    box.appendChild(b);
    scCats[c] = { el: b, on: false };
  }
}
function scSet(c, on) {
  const s = scCats[c];
  if (!s) return;
  s.on = on;
  s.el.classList.toggle("on", on);
  s.el.style.borderColor = on ? CAT[c].color : "";
  s.el.style.background = on ? CAT[c].color + "16" : "";  // 카테고리 색 옅은 틴트
  s.el.style.color = on ? CAT[c].color : "";
}

function openScenario(question) {
  document.getElementById("scenario-q").value = question;
  const picks = new Set(SC_BASE);
  SC_RULES.forEach(([re, cats]) => { if (re.test(question)) cats.forEach(c => picks.add(c)); });
  for (const c in scCats) scSet(c, picks.has(c));
  document.getElementById("scenario-err").style.display = "none";
  setView("scenario");
}

document.getElementById("scenario-back").onclick = () => setView("landing");

document.getElementById("scenario-go").onclick = async () => {
  const q = document.getElementById("scenario-q").value.trim();
  const cats = Object.keys(scCats).filter(c => scCats[c].on);
  const err = document.getElementById("scenario-err");
  const fail = (t) => { err.textContent = t; err.style.display = "block"; };
  if (!q) return fail("질문을 입력해 주세요.");
  if (!cats.length) return fail("필요한 시설을 1개 이상 선택해 주세요.");
  err.style.display = "none";

  const btn = document.getElementById("scenario-go");
  btn.disabled = true;
  btn.textContent = "⏳ 추천 찾는 중…";
  let data = null;
  try {
    // 추천 생성은 /api/recommend (C, #13 — 계약 §1 형식). /api/chat은 대화 전용(§4)이라 분리 (7/9)
    const res = await fetch("/api/recommend", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: q, categories: cats }),  // 계약 §1: 유저 확정 시설 목록
    });
    if (!res.ok) throw new Error("not ready");
    data = await res.json();
    // 방어: 200이어도 계약 형식(pins 포함 map)이 아니면 임시 엔진으로 폴백
    if (!data || typeof data.reply !== "string" || !data.reply || !data.map) throw new Error("unexpected shape");
  } catch {
    data = null;
    if (MOCK_CHAT) { try { data = await tempRecommend(q, cats); } catch { /* 아래 폴백 */ } }
  }
  btn.disabled = false;
  btn.textContent = "🔍 추천 받기";
  if (!data || !data.reply) return fail("추천을 가져오지 못했어요. 잠시 후 다시 시도해 주세요.");

  addMsg("user", q);          // 랜딩 채팅 히스토리에도 남김
  addMsg("bot", data.reply);
  if (!data.map) data.map = {};
  // layers 미지정 시에만 유저 선택으로 채움 — 빈 배열([])은 "추천 핀만 표출" 의도이므로 존중 (7/8)
  if (!Array.isArray(data.map.layers)) data.map.layers = cats;
  applyMapCommand(q, data);   // 지도 전환 + 영역 이동 + 핀 + 배너 (User flow 3단계)
};

// ── PWA: 서비스워커 등록 (홈화면 설치형 앱 — TODO.md 모바일 앱 전환 1단계) ──
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* 미지원/실패해도 앱은 정상 */ });
  });
}

loadKakao();
