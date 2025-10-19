// ATENÇÃO: Mudamos a versão para 'v3' para forçar a atualização do Service Worker.
const CACHE_VERSION = 'v3'; 
const CACHE_NAME = `gerador-orcamentos-cache-${CACHE_VERSION}`;

// Lista de TODOS os arquivos essenciais para o funcionamento offline.
const URLS_TO_CACHE = [
  // Páginas principais
  '/',
  '/login',
  '/orcamentos',

  // Arquivo de manifesto PWA
  '/manifest.json',

  // === RECURSOS EXTERNOS ESSENCIAIS ADICIONADOS AQUI ===
  'https://cdn.tailwindcss.com',
  'https://unpkg.com/@popperjs/core@2',
  'https://unpkg.com/tippy.js@6',
  'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.11.338/pdf.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.11.338/pdf.worker.min.js'
];

// Evento de Instalação: Salva os arquivos essenciais no cache.
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[Service Worker] Cacheando todos os recursos essenciais.');
        return cache.addAll(URLS_TO_CACHE);
      })
  );
});

// Evento de Ativação: Limpa os caches antigos (como o 'v2' que estava incompleto).
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            console.log('[Service Worker] Limpando cache antigo:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  return self.clients.claim();
});

// Evento Fetch: Estratégia "Stale-While-Revalidate" para a API e "Cache First" para o resto.
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') {
    return;
  }
  
  const requestUrl = new URL(event.request.url);

  // Estratégia para a API: Tenta o cache, depois a rede, e atualiza.
  if (requestUrl.pathname.startsWith('/api/')) {
    event.respondWith(
      caches.open(CACHE_NAME).then(cache => {
        return cache.match(event.request).then(cachedResponse => {
          const fetchPromise = fetch(event.request).then(networkResponse => {
            cache.put(event.request, networkResponse.clone());
            return networkResponse;
          });
          return cachedResponse || fetchPromise;
        });
      })
    );
  } 
  // Estratégia para o resto: Tenta o cache primeiro. Se falhar, busca na rede.
  else {
    event.respondWith(
      caches.match(event.request).then(response => {
        return response || fetch(event.request);
      })
    );
  }
});