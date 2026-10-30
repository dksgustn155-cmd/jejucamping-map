// 숲으로 바다로 — 서비스워커 (PWA 1단계, 홈화면 설치용)
// 전략: 네트워크 우선 + 실패 시 캐시 (개발 중 stale 방지). /api/·/config.js 는 캐시 안 함.
const CACHE = "sbb-v10";
const SHELL = ["/", "/static/style.css?v=22", "/static/app.js?v=26", "/static/scoring.js?v=4",
               "/static/icons/icon-192.png", "/static/icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;                       // 카카오 SDK 등 외부는 브라우저에 맡김
  if (url.pathname.startsWith("/api/") || url.pathname === "/config.js") return;  // 실시간 데이터·키는 항상 네트워크
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
