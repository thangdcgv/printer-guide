const CACHE_NAME = 'printer-guide-v1.0.2';

// Các tài nguyên tĩnh cần lưu bộ nhớ đệm ngay khi cài đặt
const STATIC_ASSETS = [
  '/',
  '/static/favicon.png',
  '/static/manifest.json',
  'https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap',
  'https://cdn.tailwindcss.com',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css'
];

// 1. Cài đặt Service Worker và Cache tĩnh
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

// 2. Kích hoạt và dọn dẹp Cache cũ khi có phiên bản mới
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// 3. Xử lý Request
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Bỏ qua các APIPOST, PUT, DELETE hoặc Request không phải GET (không lưu Cache)
  if (request.method !== 'GET') return;

  // Đối với request HTML / Đăng nhập / API admin: Dùng chiến lược Network-First
  if (request.headers.get('accept')?.includes('text/html') || url.pathname.startsWith('/admin') || url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Lưu bản sao mới nhất vào Cache nếu thành công
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, responseClone));
          return response;
        })
        .catch(() => {
          // Nếu mất mạng hoàn toàn: Trả về Cache trang chủ hoặc asset tĩnh đã lưu
          return caches.match(request).then((cachedResponse) => {
            return cachedResponse || caches.match('/');
          });
        })
    );
    return;
  }

  // Đối với Hình ảnh, CSS, JS, Icon: Dùng chiến lược Cache-First (Tối ưu tốc độ)
  event.respondWith(
    caches.match(request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const responseClone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, responseClone));
        }
        return networkResponse;
      });
    })
  );
});