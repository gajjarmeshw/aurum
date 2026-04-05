/* ═══════════════════════════════════════════════════════
   AURUM PWA — Service Worker (HTTP-compatible)
   Caches shell assets for faster loads. Never caches SSE.
   ═══════════════════════════════════════════════════════ */

const CACHE = 'aurum-v1';

const SHELL = [
  '/',
  '/static/style.css',
  '/static/charts.js',
  '/static/sse.js',
  '/static/manifest.json',
];

// Never cache these (live data)
const NO_CACHE = ['/api/stream', '/api/', '/api/backtest/step'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL)).catch(console.warn)
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = e.request.url;

  // Always bypass cache for API calls and SSE
  if (NO_CACHE.some(p => url.includes(p))) {
    e.respondWith(fetch(e.request));
    return;
  }

  // Cache-first for static shell assets
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(resp => {
        // Only cache successful, same-origin or CDN GET responses
        if (resp.ok && e.request.method === 'GET') {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone)).catch(() => {});
        }
        return resp;
      }).catch(() => cached); // fallback to cache if network fails
    })
  );
});
