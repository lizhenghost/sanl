/* Sanl PWA Service Worker
 * 策略：
 *  - API 请求(/api/)：永远走网络（数据实时性优先），失败时返回离线提示 JSON
 *  - 导航请求(页面跳转)：网络优先，失败回退缓存——保证用户尽快拿到最新前端
 *  - 静态资源(静态页面/vendor/图标)：Cache-first + 后台更新 (stale-while-revalidate)
 *  - 订阅输出(/sub/、/api/sub)：走网络
 */
const CACHE = 'sanl-v2';
const CORE = [
  '/',
  '/static/index.html',
  '/static/worldmap.js',
  '/manifest.webmanifest',
  '/vendor/echarts.min.js',
  '/vendor/qrcode.min.js',
  '/vendor/world.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(CORE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;

  // API 与订阅：网络优先，不污染缓存；离线时给出可识别的降级响应
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/sub/')) {
    e.respondWith(
      fetch(e.request).catch(() =>
        new Response(JSON.stringify({ error: 'offline', detail: '当前离线，Sanl 无法访问后端' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } })
      )
    );
    return;
  }

  // 导航请求（页面跳转/刷新）：网络优先，失败回退缓存——安卓 PWA 能及时拿到最新前端
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).then((resp) => {
        if (resp && resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put('/static/index.html', copy));
        }
        return resp;
      }).catch(() => caches.match('/static/index.html'))
    );
    return;
  }

  // 静态资源：缓存优先 + 异步刷新
  e.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(e.request);
      const fetchPromise = fetch(e.request).then((resp) => {
        if (resp && resp.ok && url.origin === location.origin) {
          cache.put(e.request, resp.clone());
        }
        return resp;
      }).catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
