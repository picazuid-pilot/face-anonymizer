/*
 * Gezichtsdetectie voor de camera-app, in de achtergrond zodat het beeld vloeiend blijft.
 * - 'live': kleine, verkleinde beelden tijdens het filmen (snel)
 * - 'photo': het volle beeld bij het maken van een foto, op twee schalen (grondiger)
 * Alles lokaal: YuNet via ONNX Runtime Web (WASM), geen netwerk.
 */
/* global ort, YuNet */
importScripts('../lib/ort.wasm.min.js', '../lib/yunet.js');

ort.env.wasm.wasmPaths = new URL('../lib/', self.location.href).href;
ort.env.wasm.numThreads = 1; // zonder speciale serverheaders kan het niet anders

let session = null;
let queue = Promise.resolve(); // één berekening tegelijk per sessie

async function infer(rgba, W, H) {
  const input = new ort.Tensor('float32', YuNet.toTensor(rgba, W, H), [1, 3, H, W]);
  const res = await session.run({ input });
  const out = {};
  for (const k of Object.keys(res)) out[k] = res[k].data;
  return YuNet.decode(out, W, H, 0.3, 0.3);
}

async function inferBitmap(bitmap, long) {
  const { scale, cw, ch, W, H } = YuNet.inputSize(bitmap.width, bitmap.height, long);
  const c = new OffscreenCanvas(W, H);
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(bitmap, 0, 0, cw, ch);
  const boxes = await infer(ctx.getImageData(0, 0, W, H).data, W, H);
  return boxes.map(([x, y, w, h, s]) => [x / scale, y / scale, w / scale, h / scale, s]);
}

function overlap(a, b) {
  const x1 = Math.max(a[0], b[0]), y1 = Math.max(a[1], b[1]);
  const x2 = Math.min(a[0] + a[2], b[0] + b[2]), y2 = Math.min(a[1] + a[3], b[1] + b[3]);
  if (x2 <= x1 || y2 <= y1) return [0, 0];
  const inter = (x2 - x1) * (y2 - y1);
  return [inter / (a[2] * a[3] + b[2] * b[3] - inter), inter / Math.min(a[2] * a[3], b[2] * b[3])];
}

/** Grote en kleine gezichten: twee schalen, dubbele treffers samengevoegd. */
async function detectPhoto(bitmap, minScore) {
  const long = Math.max(bitmap.width, bitmap.height);
  const levels = [...new Set([640, Math.min(1280, Math.max(long, 640))])];
  let found = [];
  for (const lv of levels) found = found.concat(await inferBitmap(bitmap, lv));
  found = found.filter((b) => b[4] >= minScore).sort((a, b) => b[4] - a[4]);
  const keep = [];
  for (const f of found) {
    if (keep.every((k) => { const [iou, cont] = overlap(f, k); return iou <= 0.3 && cont <= 0.7; })) keep.push(f);
  }
  return keep;
}

async function handle(m) {
  try {
    if (m.type === 'init') {
      session = await ort.InferenceSession.create('../models/yunet.onnx', {
        executionProviders: ['wasm'],
        graphOptimizationLevel: 'all',
      });
      // Opwarmen op gangbare formaten (liggend en staand), anders is de eerste detectie traag
      for (const [W, H] of [[480, 288], [288, 480]]) await infer(new Uint8ClampedArray(W * H * 4), W, H);
      self.postMessage({ type: 'ready' });
    } else if (m.type === 'live') {
      const t0 = performance.now();
      const boxes = await infer(new Uint8ClampedArray(m.buffer), m.W, m.H);
      self.postMessage({ type: 'live', id: m.id, boxes, ms: performance.now() - t0 });
    } else if (m.type === 'photo') {
      const boxes = await detectPhoto(m.bitmap, m.minScore);
      m.bitmap.close();
      self.postMessage({ type: 'photo', id: m.id, boxes });
    }
  } catch (err) {
    if (m.bitmap) try { m.bitmap.close(); } catch (_) { /* al dicht */ }
    self.postMessage({ type: 'error', id: m.id, kind: m.type, message: String((err && err.message) || err) });
  }
}

self.onmessage = (e) => { queue = queue.then(() => handle(e.data || {})); };
