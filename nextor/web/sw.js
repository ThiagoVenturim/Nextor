const CACHE_NAME = 'nextor-pwa-shell-v1';

const SHELL_ASSETS = [
  '/',
  '/painel',
  '/rosto',
  '/download',
  '/manifest.webmanifest',
  '/icone-192.png',
  '/icone-512.png',
  '/web/painel.css',
  '/web/painel.js',
  '/web/rosto.css',
  '/web/rosto.js',
  '/web/bichinho.css',
  '/web/bichinho.js',
  '/gtd',
  '/gtd/index.html',
  '/gtd/app.css',
  '/gtd/app.js',
  '/gtd/manifest.webmanifest'
];

const API_PREFIXES = [
  '/comando',
  '/anotar',
  '/falar',
  '/conversar',
  '/agenda',
  '/noticias',
  '/notas',
  '/automacoes',
  '/texto',
  '/nest',
  '/estado',
  '/modo',
  '/identidade',
  '/eventos',
  '/conversa',
  '/voz',
  '/fala/',
  '/estudos/',
  '/v1/',
  '/gtd/itens',
  '/gtd/capturar',
  '/gtd/processar',
  '/gtd/hoje',
  '/gtd/leituras',
  '/gtd/projetos',
  '/gtd/revisao',
  '/gtd/sincronizar',
  '/gtd/config',
  '/gtd/visao',
  '/gtd/pomodoro',
  '/gtd/notificacoes',
  '/gtd/agenda'
];

function ehRotaApi(pathname) {
  return API_PREFIXES.some((prefixo) => pathname === prefixo || pathname.startsWith(prefixo + '/') || pathname.startsWith(prefixo));
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(SHELL_ASSETS).catch(() => {});
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME && key.startsWith('nextor-pwa-shell-'))
          .map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (!event.data) return;
  if (event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (url.origin !== self.location.origin) {
    return;
  }

  if (req.method !== 'GET' || ehRotaApi(url.pathname)) {
    return;
  }

  const aceitaHtml = req.headers.get('accept')?.includes('text/html');

  if (aceitaHtml) {
    event.respondWith(
      fetch(req)
        .then((networkResp) => {
          if (networkResp && networkResp.status === 200) {
            const clone = networkResp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
          }
          return networkResp;
        })
        .catch(() => {
          return caches.match(req).then((cached) => {
            if (cached) return cached;
            if (url.pathname.startsWith('/gtd')) return caches.match('/gtd/index.html');
            if (url.pathname.startsWith('/rosto')) return caches.match('/rosto');
            if (url.pathname.startsWith('/download')) return caches.match('/download');
            return caches.match('/painel');
          });
        })
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cachedResp) => {
      if (cachedResp) {
        return cachedResp;
      }
      return fetch(req).then((networkResp) => {
        if (networkResp && networkResp.status === 200 && networkResp.type === 'basic') {
          const clone = networkResp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
        }
        return networkResp;
      });
    })
  );
});
