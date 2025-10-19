// ATENÇÃO: Mudamos a versão para 'v7' para forçar a atualização final.
const CACHE_VERSION = 'v7';
const CACHE_NAME = `gerador-orcamentos-cache-${CACHE_VERSION}`;

// Lista de todos os recursos essenciais do "esqueleto" do app.
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

// Evento de Instalação: Salva o App Shell no cache.
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log(`[Service Worker] Cacheando App Shell (v${CACHE_VERSION}).`);
      // Faz requisições no-cors para os recursos externos
      const externalRequests = URLS_TO_CACHE.filter(url => url.startsWith('http'))
        .map(url => new Request(url, { mode: 'no-cors' }));

      // Junta as URLs locais com as requisições externas
      const localUrls = URLS_TO_CACHE.filter(url => !url.startsWith('http'));
      return cache.addAll([...localUrls, ...externalRequests]);
    })
    .catch(err => console.error("Falha ao cachear o App Shell:", err))
  );
});


// Evento de Ativação: Limpa os caches antigos.
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


// Evento Fetch: Lida com as requisições de rede.
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') {
    return;
  }

  // Estratégia: Network First, falling back to Cache
  event.respondWith(
    fetch(event.request)
      .then(networkResponse => {
        // --- CORREÇÃO IMPORTANTE AQUI ---
        // Se a resposta for válida, nós a colocamos no cache.
        // Respostas do tipo 'opaque' (para CDNs) são válidas, mas não podemos cloná-las.
        if (networkResponse && (networkResponse.ok || networkResponse.type === 'opaque')) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      })
      .catch(() => {
        // Se a rede falhar (estamos offline), busca no cache.
        console.log('[Service Worker] Rede falhou, tentando buscar no cache:', event.request.url);
        return caches.match(event.request)
          .then(cachedResponse => {
            if (cachedResponse) {
              return cachedResponse;
            }
            // Se não estiver no cache e a rede falhar, o navegador mostrará a página de erro.
          });
      })
  );
});