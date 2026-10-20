// Service worker : met en cache UNIQUEMENT les ressources statiques de l'application.
// Jamais d'appel /api (données, approbations, commandes) : pas de cache, pas d'exécution hors ligne.
const CACHE = 'nexus-static-v1'
const STATIC = [/^\/assets\//, /^\/icon\.svg$/, /^\/manifest\.webmanifest$/]

self.addEventListener('install', (e) => { self.skipWaiting() })
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()))
})
self.addEventListener('fetch', (e) => {
  const req = e.request
  const url = new URL(req.url)
  if (req.method !== 'GET' || url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return                 // réseau uniquement, jamais mis en cache
  if (!STATIC.some((re) => re.test(url.pathname))) return       // la page HTML elle-même n'est pas mise en cache
  e.respondWith(
    caches.open(CACHE).then(async (c) => {
      const hit = await c.match(req)
      if (hit) return hit
      const res = await fetch(req)
      if (res.ok) c.put(req, res.clone())
      return res
    }),
  )
})
