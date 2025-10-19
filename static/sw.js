// ATENÇÃO: Mudamos a versão para 'v8' para garantir que esta nova lógica seja instalada.
const CACHE_VERSION = 'v8';
const CACHE_NAME = `gerador-orcamentos-cache-${CACHE_VERSION}`;

// Arquivos do "esqueleto" do aplicativo (App Shell).
const APP_SHELL_URLS = [
  '/',
  '/login',
  '/orcamentos',
  '/static/manifest.json',
  'https://cdn.tailwindcss.com',
  'https://unpkg.com/@popperjs/core@2',
  'https://unpkg.com/tippy.js@6',
  'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.11.338/pdf.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.11.338/pdf.worker.min.js'
];

// Instala o Service Worker e cacheia o App Shell.
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log(`[Service Worker] Cacheando App Shell (v${CACHE_VERSION}).`);
        const externalRequests = APP_SHELL_URLS.filter(url => url.startsWith('http'))
          .map(url => new Request(url, { mode: 'no-cors' }));
        const localUrls = APP_SHELL_URLS.filter(url => !url.startsWith('http'));
        return cache.addAll([...localUrls, ...externalRequests]);
      })
      .catch(err => console.error("Falha ao cachear o App Shell:", err))
  );
});

// Limpa caches antigos quando uma nova versão é ativada.
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => Promise.all(
      cacheNames
        .filter(cacheName => cacheName !== CACHE_NAME)
        .map(cacheName => caches.delete(cacheName))
    ))
  );
  return self.clients.claim();
});

// Intercepta requisições.
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') { return; }

  // Estratégia "Network falling back to Cache".
  // Sempre tenta a rede primeiro. Se falhar, usa o cache.
  // Isso funciona para TUDO: páginas, API e PDFs.
  event.respondWith(
    fetch(event.request)
      .then(networkResponse => {
        // Se a resposta da rede for válida, a clona e a salva no cache.
        if (networkResponse && (networkResponse.ok || networkResponse.type === 'opaque')) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(() => {
        // Se a rede falhar, retorna a correspondência do cache.
        return caches.match(event.request);
      })
  );
});