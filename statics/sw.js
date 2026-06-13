const CACHE_NAME = 'sparkling-studio-v3';
const ASSETS = [
  '/',
  '/manifest.json',
  '/statics/icon-192.png',
  '/statics/icon-512.png'
];

// इंस्टॉल होते ही ज़रूरी एसेट्स को कैश में डालना
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS);
    })
  );
});

// रिक्वेस्ट्स को तेजी से सर्व करना
self.addEventListener('fetch', (e) => {
  e.respondWith(
    caches.match(e.request).then((response) => {
      return response || fetch(e.request);
    })
  );
});
