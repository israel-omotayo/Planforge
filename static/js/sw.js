const CACHE_NAME = "planforge-v1";

// Pages to cache immediately on install
const PRECACHE = [
  "/offline/",
];

// Install — cache the offline page
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

// Activate — clean up old caches from previous versions
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// Fetch strategy:
// - Static assets (CSS, JS, images): cache first, fall back to network
// - Navigation (HTML pages): network first, fall back to offline page
// - POST / non-GET: never intercept
self.addEventListener("fetch", event => {
  const { request } = event;
  const url = new URL(request.url);

  // Never intercept POST requests or non-GET
  if (request.method !== "GET") return;

  // Never intercept Cloudinary CDN, Django admin, or AI/JSON endpoints
  if (
    url.hostname.includes("cloudinary") ||
    url.pathname.startsWith("/admin/") ||
    url.pathname.startsWith("/api/")
  ) return;

  // Static assets — cache first, populate cache on miss
  if (
    url.pathname.startsWith("/static/") ||
    url.pathname.startsWith("/favicon")
  ) {
    event.respondWith(
      caches.match(request).then(cached => {
        return cached || fetch(request).then(response => {
          // Only cache valid responses
          if (!response || response.status !== 200 || response.type !== "basic") {
            return response;
          }
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
          return response;
        });
      })
    );
    return;
  }

  // HTML navigation — network first, branded offline page as fallback
  if (request.headers.get("Accept")?.includes("text/html")) {
    event.respondWith(
      fetch(request).catch(() => caches.match("/offline/"))
    );
    return;
  }
});