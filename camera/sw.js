/*
 * Maakt de camera-app offline bruikbaar: alle bestanden (ook het model en
 * ONNX Runtime, samen ~15 MB) worden bij de eerste keer bewaard.
 * Nieuwe versie online? Dan wordt die op de achtergrond opgehaald en bij de
 * volgende start gebruikt. VERSION wordt door build.sh ingevuld.
 */
const VERSION = 'dev';
const CACHE = 'fa-camera-' + VERSION;
const FILES = [
  './', 'index.html', 'camera.css', 'camera.js', 'tracker.js', 'detector-worker.js', 'manifest.webmanifest',
  'icons/icon-192.png', 'icons/icon-512.png', 'icons/maskable-512.png', 'icons/apple-touch-icon.png',
  '../lib/ort.wasm.min.js', '../lib/ort-wasm-simd-threaded.mjs', '../lib/ort-wasm-simd-threaded.wasm',
  '../lib/yunet.js', '../models/yunet.onnx', '../assets/overlay.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith('fa-camera-') && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  e.respondWith(caches.match(req, { ignoreSearch: true }).then((hit) => hit || fetch(req)));
});
