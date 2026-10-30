/* MJ: service worker. Served from the site root by myproject.views.service_worker so its scope is
   the whole site (a worker only controls pages at or below its own URL).

   Its one job is NET-001: when a page is opened with no internet, the browser would normally show
   its own "no connection" screen, which says nothing about the store. Instead we answer the
   navigation from the cache with /offline/, which explains the code and reloads itself once the
   connection is back.

   Pages themselves are never served stale: a store that showed yesterday's prices, stock or bag
   offline would be worse than saying "you are offline". Only /offline/ and the static files are
   cached. */
'use strict';

const VERSION = 'mj-v1';
const SHELL = `${VERSION}-shell`;    // The offline page and the logo.
const ASSETS = `${VERSION}-assets`;  // CSS, JS and images from /static/.
const OFFLINE_URL = '/offline/';

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL);
    // reload: skip the HTTP cache, so a deploy always precaches the current offline page.
    await cache.addAll([new Request(OFFLINE_URL, { cache: 'reload' }), '/static/img/mj-mark.svg']);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keep = [SHELL, ASSETS];
    await Promise.all((await caches.keys()).filter((key) => !keep.includes(key)).map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;                       // Never touch checkout, chat or sign-in.
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;            // Fonts and icon CDNs: straight to the network.

  // Pages: always ask the network, and fall back to the offline page (NET-001) when it fails.
  if (request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        return await fetch(request);
      } catch (err) {
        return (await caches.match(OFFLINE_URL)) || new Response(
          '<!doctype html><title>Offline</title><h1>No internet connection (NET-001)</h1>'
          + '<p>Check your connection and reload.</p>',
          { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } },
        );
      }
    })());
    return;
  }

  // Static files: serve from the cache when we have them, and refresh the copy in the background.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith((async () => {
      const cache = await caches.open(ASSETS);
      const hit = await cache.match(request, { ignoreSearch: false });
      const update = fetch(request).then((res) => {
        if (res && res.ok) cache.put(request, res.clone());
        return res;
      }).catch(() => null);
      return hit || (await update) || Response.error();
    })());
  }

  // Everything else (/api/, /assistant/, /media/) goes to the network. The page catches the
  // failure itself and shows the NET-002 banner, which is more useful than a cached answer.
});
