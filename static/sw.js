const CACHE_NAME = 'gerador-orcamentos-cache-v1';
// Lista de arquivos essenciais para o funcionamento offline do app.
const urlsToCache = [
  '/',
  '/login',
  '/orcamentos',
  '/manifest.json'
];

// Evento de Instalação: Salva os arquivos essenciais no cache.
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Cache aberto com sucesso.');
        return cache.addAll(urlsToCache);
      })
  );
});

// Evento Fetch: Intercepta as requisições.
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        // Se o recurso já estiver no cache, retorna a versão do cache.
        if (response) {
          return response;
        }
        // Senão, busca o recurso na rede.
        return fetch(event.request);
      })
  );
});