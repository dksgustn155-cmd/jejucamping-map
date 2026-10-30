// ══════════════════════════════════════════════════════════════
// 임시 추천 스코어링 엔진 (P2) — docs/scoring-design.md
// window.Scoring = { parseConds, recommend, WEIGHTS, REGIONS }
//
// ⚠️ C의 /api/recommend(#13) 완성 전까지의 임시 엔진.
//    출력(pins[].score, why[])은 서버 설계와 동일 — 전환 시 호출 1곳만 교체.
// 데이터: 기존 실서비스 API만 사용 (/api/facilities, /api/ev-status, /api/zone-check)
// ══════════════════════════════════════════════════════════════
(function () {
  "use strict";

  // ── 가중치 (data/score_weights.json 과 동일 형식 — 배치 학습 루프 호환) ──
  const WEIGHTS = {
    base: 30,
    restroom: { d150: 20, d300: 15, d500: 8 },
    restroom_24h: 5,
    sea_view: { d500: 15, d1000: 10 },
    nature_view: 15,
    ev: { d1000: 15, fast_bonus: 5 },
    flood: { grade1: -20, grade2: -10 },
    cctv_500: 3,
    pharmacy_3000: 3,
    cleanhouse_500: 2,
    festival_active_1000: -8,
    natural_park: -50,
    structure_roadside: -15,
  };

  // V12 구조 판정 — 주차 건축물(빌딩·타워·기계식·지하 등)은 차박이 물리적으로 불가 → 후보 제외
  const STRUCT_EXCLUDE_RE = /빌딩|타워|기계식|지하|옥내|옥상/;
  function structImpossible(cand) {
    if (cand.category !== "parking_public") return false;
    const name = cand.name || "";
    const type = (cand.extra && cand.extra.type) || "";
    return STRUCT_EXCLUDE_RE.test(name) || STRUCT_EXCLUDE_RE.test(type);
  }

  // ── 지역 사전 (미인식 시 기본 서귀포 + conds.regionMatched=false) ──
  const REGIONS = {
    "서귀포": [33.21, 126.42, 33.32, 126.62],
    "중문":   [33.23, 126.38, 33.28, 126.46],
    "성산":   [33.40, 126.86, 33.50, 126.95],
    "애월":   [33.40, 126.22, 33.50, 126.42],
    "협재":   [33.37, 126.20, 33.42, 126.30],
    "함덕":   [33.52, 126.64, 33.57, 126.72],
    "제주":   [33.40, 126.35, 33.58, 126.70],
    "담양":   [35.25, 126.88, 35.45, 127.12],
  };

  function dist(lat1, lng1, lat2, lng2) {
    const R = 6371000, rad = Math.PI / 180;
    const dLat = (lat2 - lat1) * rad, dLng = (lng2 - lng1) * rad;
    const a = Math.sin(dLat / 2) ** 2 +
              Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }
  const fmt = (m) => (m < 1000 ? Math.round(m) + "m" : (m / 1000).toFixed(1) + "km");

  // ── 조건 파싱 (규칙 기반 임시 — C의 GPT 파싱 도입 시 폴백으로 강등, 설계 §5) ──
  function parseConds(question, checkedCats) {
    const q = question || "";
    const cats = checkedCats || [];
    const regionKey = Object.keys(REGIONS).find((k) => q.includes(k)) || null;
    return {
      region: regionKey || "서귀포",
      regionMatched: !!regionKey,
      ev: cats.includes("ev_charger") || /전기차|충전|[eE][vV]/.test(q),
      seaView: cats.includes("beach") || /바다|해변|해수욕/.test(q),
      natureView: /숲|계곡|호수/.test(q),
      pharmacyNeed: cats.includes("pharmacy") || /약국/.test(q),
    };
  }

  // ── 시설 조회 헬퍼 ──
  async function fetchCat(bbox, cat, limit) {
    const [sa, so, na, no] = bbox;
    const q = new URLSearchParams({ sw_lat: sa, sw_lng: so, ne_lat: na, ne_lng: no,
                                    category: cat, limit });
    const res = await fetch("/api/facilities?" + q);
    return (await res.json()).items || [];
  }
  function nearest(cand, items) {
    let best = null, bd = Infinity;
    for (const it of items) {
      const d = dist(cand.lat, cand.lon, it.lat, it.lon);
      if (d < bd) { bd = d; best = it; }
    }
    return best ? { item: best, d: bd } : null;
  }
  // why[].ref — 근거가 된 실제 시설 (프론트가 지도에 '이유 마커'로 표시, P3+)
  function refOf(n) {
    return { id: n.item.id, category: n.item.category, name: n.item.name,
             lat: n.item.lat, lon: n.item.lon, d: Math.round(n.d), item: n.item };
  }

  // ── 개최중 축제 판정 (V10) ──
  function activeFestivals(festivals) {
    const today = new Date().toISOString().slice(0, 10);
    return festivals.filter((f) => {
      const s = f.extra && f.extra.start, e = f.extra && f.extra.end;
      return s && e && s <= today && today <= e;
    });
  }

  // ── 후보 1건 채점 (V1~V10) — why[] = 적합성 리포트 (설계 §6) ──
  function scoreCandidate(cand, refs, conds) {
    const why = [];
    let score = WEIGHTS.base;
    const add = (check, pass, detail, delta, ref) => {
      score += delta;
      why.push(ref ? { check, pass, detail, delta, ref } : { check, pass, detail, delta });
    };

    // V1·V2 화장실 (_rd = 최근접 거리 — 동점 타이브레이커용, 표시 점수엔 미반영)
    const r = nearest(cand, refs.restroom);
    if (r && r.d <= 500) {
      const w = r.d <= 150 ? WEIGHTS.restroom.d150 : r.d <= 300 ? WEIGHTS.restroom.d300 : WEIGHTS.restroom.d500;
      add("restroom", true, `화장실 ${fmt(r.d)} (${r.item.name})`, w, refOf(r));
      if (/24시간|상시|연중/.test(r.item.open_hours || "")) add("restroom_24h", true, "24시간 개방", WEIGHTS.restroom_24h);
    } else {
      add("restroom", false, "화장실 500m 내 없음", 0);
    }

    // V3 바다 뷰 (조건부)
    if (conds.seaView) {
      const b = nearest(cand, refs.beach);
      if (b && b.d <= 1000) {
        add("sea_view", true, `해수욕장 ${fmt(b.d)} (${b.item.name})`,
            b.d <= 500 ? WEIGHTS.sea_view.d500 : WEIGHTS.sea_view.d1000, refOf(b));
      } else {
        add("sea_view", false, "해수욕장 1km 내 없음", 0);
      }
    }

    // V4 숲·계곡 뷰 (camping 후보 한정, 조건부)
    if (conds.natureView && cand.category === "camping") {
      const loc = (cand.extra && cand.extra.loc_type) || "";
      if (/산|숲|계곡|호수|호반/.test(loc)) add("nature_view", true, `입지: ${loc}`, WEIGHTS.nature_view);
    }

    // V5 EV (조건부)
    if (conds.ev) {
      const e = nearest(cand, refs.ev);
      if (e && e.d <= 1000) {
        add("ev", true, `EV충전소 ${fmt(e.d)} (${e.item.name})`, WEIGHTS.ev.d1000, refOf(e));
        const live = refs.evStatus[String(e.item.id).replace(/^ev:/, "")];
        if (live && live.fast > 0) add("ev_fast", true, `지금 급속 ${live.fast}대 가능`, WEIGHTS.ev.fast_bonus);
      } else {
        add("ev", false, "EV충전소 1km 내 없음", 0);
      }
    }

    // V12 구조 (공영주차장 한정 — 건축물은 이미 후보 제외됨)
    if (cand.category === "parking_public") {
      const type = (cand.extra && cand.extra.type) || "";
      if (type.includes("노상")) {
        add("structure", false, "노상(도로변) 주차장 — 차박 부적합", WEIGHTS.structure_roadside);
      } else if (type.includes("노외")) {
        add("structure", true, "노외 개방형 주차장", 0);
      }
    }

    // V6 침수 (둔치 후보 한정)
    if (cand.category === "parking") {
      const g = String((cand.extra && cand.extra.risk_grade) || "").trim();
      if (g === "1") add("flood", false, "침수위험 1등급(위험)", WEIGHTS.flood.grade1);
      else if (g === "2") add("flood", false, "침수위험 2등급(주의)", WEIGHTS.flood.grade2);
      else if (g === "3") add("flood", true, "침수위험 3등급(양호)", 0);
    }

    // V7~V9 안전·편의
    const c = nearest(cand, refs.cctv);
    if (c && c.d <= 500) add("cctv", true, `안전CCTV ${fmt(c.d)}`, WEIGHTS.cctv_500, refOf(c));
    const p = nearest(cand, refs.pharmacy);
    if (p && p.d <= 3000) {
      const w = conds.pharmacyNeed ? WEIGHTS.pharmacy_3000 * 2 : WEIGHTS.pharmacy_3000;  // 설계 §5: 약국 필요 시 ×2
      add("pharmacy", true, `심야약국 ${fmt(p.d)} (${p.item.name})`, w, refOf(p));
    } else if (conds.pharmacyNeed) {
      add("pharmacy", false, "심야약국 3km 내 없음", 0);
    }
    const h = nearest(cand, refs.cleanhouse);
    if (h && h.d <= 500) add("cleanhouse", true, `클린하우스 ${fmt(h.d)}`, WEIGHTS.cleanhouse_500, refOf(h));

    // V10 혼잡(개최중 축제)
    const f = nearest(cand, refs.festivalActive);
    if (f && f.d <= 1000) add("festival", false, `축제 개최중 ${fmt(f.d)} (${f.item.name}) — 붐빌 수 있음`, WEIGHTS.festival_active_1000, refOf(f));

    return { item: cand, score, why, _rd: r ? r.d : 99999 };
  }

  // 동점 시 화장실이 더 가까운 후보를 앞세움 (표시 점수는 그대로)
  const rank = (a, b) => (b.score - a.score) || (a._rd - b._rd);

  // ── 메인: 추천 (2-pass — V11 zone-check는 상위 12만 조회, 설계 §3) ──
  const TOP_ZONE_CHECK = 12, TOP_RETURN = 10;
  async function recommend(question, checkedCats) {
    const conds = parseConds(question, checkedCats);
    const bbox = REGIONS[conds.region];

    // 후보 + 참조 시설 병렬 조회 (실DB)
    const [pp, camping, dunchi, restroom, beach, ev, cctv, pharmacy, cleanhouse, festival, evStatusRes] =
      await Promise.all([
        fetchCat(bbox, "parking_public", 300),
        fetchCat(bbox, "camping", 300),
        fetchCat(bbox, "parking", 300),
        fetchCat(bbox, "restroom", 2000),
        fetchCat(bbox, "beach", 300),
        conds.ev ? fetchCat(bbox, "ev_charger", 500) : Promise.resolve([]),
        fetchCat(bbox, "cctv", 300),
        fetchCat(bbox, "pharmacy", 50),
        fetchCat(bbox, "cleanhouse", 1000),
        fetchCat(bbox, "festival", 300),
        conds.ev ? fetch("/api/ev-status").then((r) => r.json()).catch(() => ({ status: {} })) : Promise.resolve({ status: {} }),
      ]);

    const refs = {
      restroom, beach, ev, cctv, pharmacy, cleanhouse,
      festivalActive: activeFestivals(festival),
      evStatus: evStatusRes.status || {},
    };
    // V12 하드 필터: 차박 물리적 불가 구조물 제외 (제외 수는 답변에 공개)
    const all = [...pp, ...camping, ...dunchi];
    const candidates = all.filter((c) => !structImpossible(c));
    const excludedCount = all.length - candidates.length;

    // 1-pass: V1~V10 채점
    let scored = candidates.map((c) => scoreCandidate(c, refs, conds));
    scored.sort(rank);

    // 2-pass: 상위 N만 자연공원 판정 (V11 −50) — 900건 전수 조회 방지
    const top = scored.slice(0, TOP_ZONE_CHECK);
    await Promise.all(top.map(async (s) => {
      try {
        const z = await (await fetch(`/api/zone-check?lat=${s.item.lat}&lon=${s.item.lon}`)).json();
        if (z.zone) {
          s.score += WEIGHTS.natural_park;
          s.why.push({ check: "natural_park", pass: false,
                       detail: `${z.zone} ${z.kind} 구역 — 야영·취사 금지(자연공원법 27조)`,
                       delta: WEIGHTS.natural_park });
        } else {
          s.why.push({ check: "natural_park", pass: true, detail: "자연공원 구역 아님", delta: 0 });
        }
      } catch { /* 판정 실패 시 감점 없이 통과 처리 */ }
    }));
    top.sort(rank);

    // 0~100 clamp + 최종 형태
    const results = top.slice(0, TOP_RETURN).map((s) => ({
      ...s, score: Math.max(0, Math.min(100, Math.round(s.score))),
    }));
    return { conds, bbox, totalCandidates: candidates.length, excludedCount, results };
  }

  window.Scoring = { parseConds, recommend, WEIGHTS, REGIONS };
})();
