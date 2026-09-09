/*
 * Future Leaders Preparatory Academy — service worker.
 * Built by Innovative FrancisTech.
 *
 * Student and staff records are private, so pages are never stored. Only the
 * branded shell (logo, icons, offline notice) is cached, which keeps the app
 * installable and gives a proper offline screen instead of the browser error.
 */
const CACHE_VERSION = 'flpa-shell-v1';
const OFFLINE_URL = '/static/offline.html';

const SHELL_ASSETS = [
  OFFLINE_URL,
  '/static/images/LOGO.png',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  '/manifest.webmanifest',
];

// Never cached: uploaded photos, scanned documents, and report/PDF exports.
const PRIVATE_PATHS = ['/static/uploads/'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'flpa-skip-waiting') self.skipWaiting();
});

function isCacheableAsset(url) {
  if (!url.pathname.startsWith('/static/')) return false;
  return !PRIVATE_PATHS.some((prefix) => url.pathname.startsWith(prefix));
}

/* Serve the stored copy at once, then quietly refresh it for next time. */
async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok && response.type === 'basic') {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => cached);
  return cached || network;
}

/* Pages always come from the server; offline shows the branded notice. */
async function networkFirstPage(request) {
  try {
    return await fetch(request);
  } catch (error) {
    const cached = await caches.match(OFFLINE_URL);
    return (
      cached ||
      new Response('You are offline.', {
        status: 503,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      })
    );
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  let url;
  try {
    url = new URL(request.url);
  } catch (error) {
    return;
  }
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstPage(request));
    return;
  }
  if (isCacheableAsset(url)) {
    event.respondWith(staleWhileRevalidate(request));
  }
});
