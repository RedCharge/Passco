// Service Worker for Past Questions App
const CACHE_NAME = 'past-questions-v1.0';
const APP_NAME = 'Past Questions App';

// Core assets to cache on install
const CORE_ASSETS = [
  '/',
  '/manifest.json',
  '/static/style.css',
  '/static/js/app.js',
  // Favicons
  '/favicon.ico',
  '/apple-touch-icon.png',
  '/android-chrome-192x192.png',
  '/android-chrome-512x512.png',
  // Logo
  '/static/images/logos.jpg'
];

// Strategy: Cache First, Network Fallback
async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const cachedResponse = await cache.match(request);
  
  if (cachedResponse) {
    return cachedResponse;
  }
  
  try {
    const networkResponse = await fetch(request);
    
    // Cache successful responses (except for API calls)
    if (networkResponse.ok && !request.url.includes('/api/')) {
      await cache.put(request, networkResponse.clone());
    }
    
    return networkResponse;
  } catch (error) {
    // For navigation requests, return offline page
    if (request.mode === 'navigate') {
      return cache.match('/offline.html') || 
             new Response('You are offline. Please check your connection.', {
               status: 503,
               headers: { 'Content-Type': 'text/html' }
             });
    }
    
    throw error;
  }
}

// Strategy: Network First, Cache Fallback (for API calls)
async function networkFirst(request) {
  try {
    const networkResponse = await fetch(request);
    const cache = await caches.open(CACHE_NAME);
    
    if (networkResponse.ok) {
      await cache.put(request, networkResponse.clone());
    }
    
    return networkResponse;
  } catch (error) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }
    
    return new Response('Network error', {
      status: 408,
      headers: { 'Content-Type': 'text/plain' }
    });
  }
}

// Install Event
self.addEventListener('install', event => {
  console.log(`[Service Worker] ${APP_NAME} installing...`);
  
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[Service Worker] Caching core assets');
        return cache.addAll(CORE_ASSETS);
      })
      .then(() => {
        console.log('[Service Worker] Installation complete');
        return self.skipWaiting();
      })
      .catch(error => {
        console.error('[Service Worker] Installation failed:', error);
      })
  );
});

// Activate Event
self.addEventListener('activate', event => {
  console.log(`[Service Worker] ${APP_NAME} activating...`);
  
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            console.log('[Service Worker] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
    .then(() => {
      console.log('[Service Worker] Activation complete');
      return self.clients.claim();
    })
  );
});

// Fetch Event
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  
  // Skip non-HTTP requests and browser extensions
  if (!url.protocol.startsWith('http')) {
    return;
  }
  
  // API calls use Network First strategy
  if (url.pathname.startsWith('/api/') || url.pathname.includes('firebase')) {
    event.respondWith(networkFirst(event.request));
    return;
  }
  
  // Static assets use Cache First strategy
  if (url.pathname.startsWith('/static/') || 
      url.pathname.includes('favicon') ||
      url.pathname.includes('apple-touch-icon') ||
      url.pathname.includes('android-chrome')) {
    event.respondWith(cacheFirst(event.request));
    return;
  }
  
  // HTML pages - Cache First with Network Fallback
  if (event.request.mode === 'navigate') {
    event.respondWith(cacheFirst(event.request));
    return;
  }
  
  // Default: try cache, then network
  event.respondWith(cacheFirst(event.request));
});

// Message Event (for communication with app)
self.addEventListener('message', event => {
  if (event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  
  if (event.data.type === 'GET_CACHE_INFO') {
    event.ports[0].postMessage({
      cacheName: CACHE_NAME,
      version: '1.0'
    });
  }
});

// Background Sync (for offline actions)
self.addEventListener('sync', event => {
  if (event.tag === 'sync-questions') {
    console.log('[Service Worker] Background sync: sync-questions');
    event.waitUntil(syncQuestions());
  }
});

async function syncQuestions() {
  // Implement background sync for questions
  console.log('[Service Worker] Syncing questions...');
  // You can add IndexedDB or localStorage sync logic here
}

// Push Notifications
self.addEventListener('push', event => {
  console.log('[Service Worker] Push received');
  
  const options = {
    body: event.data?.text() || 'New update from Past Questions App',
    icon: '/android-chrome-192x192.png',
    badge: '/favicon-32x32.png',
    vibrate: [100, 50, 100],
    data: {
      dateOfArrival: Date.now(),
      primaryKey: 1
    },
    actions: [
      {
        action: 'explore',
        title: 'Explore'
      },
      {
        action: 'close',
        title: 'Close'
      }
    ]
  };
  
  event.waitUntil(
    self.registration.showNotification('Past Questions App', options)
  );
});

self.addEventListener('notificationclick', event => {
  console.log('[Service Worker] Notification clicked');
  
  event.notification.close();
  
  if (event.action === 'explore') {
    event.waitUntil(
      clients.openWindow('/')
    );
  } else if (event.action === 'close') {
    // Do nothing
  } else {
    event.waitUntil(
      clients.openWindow('/')
    );
  }
});