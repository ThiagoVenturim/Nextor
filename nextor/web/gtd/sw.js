const CACHE_NAME = 'nextor-gtd-shell-v1';
const ASSETS = [
  '/gtd',
  '/gtd/',
  '/gtd/index.html',
  '/gtd/app.css',
  '/gtd/app.js',
  '/gtd/manifest.webmanifest'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS).catch(() => {});
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Requisicoes de API nunca usam cache offline do shell
  if (url.pathname.startsWith('/gtd/') && !url.pathname.includes('.')) {
    // Rotas de API como /gtd/itens, /gtd/hoje, etc.
    return;
  }
  if (url.pathname.startsWith('/gtd/itens') ||
      url.pathname.startsWith('/gtd/capturar') ||
      url.pathname.startsWith('/gtd/processar') ||
      url.pathname.startsWith('/gtd/hoje') ||
      url.pathname.startsWith('/gtd/leituras') ||
      url.pathname.startsWith('/gtd/projetos') ||
      url.pathname.startsWith('/gtd/revisao') ||
      url.pathname.startsWith('/gtd/sincronizar')) {
    return;
  }

  // Shell cache-first com fallback para rede
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(event.request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      }).catch(() => {
        if (event.request.headers.get('accept')?.includes('text/html')) {
          return caches.match('/gtd/index.html');
        }
      });
    })
  );
});
