/*
 * Verwerkt foto's in de achtergrond: decoderen, gezichten zoeken (YuNet via
 * ONNX Runtime Web), maskers tekenen en opnieuw coderen. Alles lokaal.
 * Dezelfde aanpak als face_core.py in de desktop-app.
 */
/* global ort, YuNet */
importScripts('lib/ort.wasm.min.js', 'lib/yunet.js');

ort.env.wasm.wasmPaths = new URL('lib/', self.location.href).href;
ort.env.wasm.numThreads = 1; // meerdere workers draaien naast elkaar

const ACCURACY = {
  fast: { levels: [1280], tiles: false },
  normal: { levels: [640, 1600], tiles: false },
  thorough: { levels: [640, 1600], tiles: true },
};
const TILE = 1280;
const TILE_OVERLAP = 0.25;
const THUMB = 480;

let session = null;
let overlay = null;

// ------------------------------------------------------------------ detectie
async function runModel(source, sx, sy, sw, sh, scale) {
  const cw = Math.max(1, Math.round(sw * scale)), ch = Math.max(1, Math.round(sh * scale));
  const W = Math.ceil(cw / 32) * 32, H = Math.ceil(ch / 32) * 32;
  const c = new OffscreenCanvas(W, H);
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(source, sx, sy, sw, sh, 0, 0, cw, ch);
  const rgba = ctx.getImageData(0, 0, W, H).data;
  const res = await session.run({ input: new ort.Tensor('float32', YuNet.toTensor(rgba, W, H), [1, 3, H, W]) });
  const out = {};
  for (const k of Object.keys(res)) out[k] = res[k].data;
  return YuNet.decode(out, W, H, 0.3, 0.3).map(([x, y, w, h, s]) => ({
    x: x / scale + sx, y: y / scale + sy, w: w / scale, h: h / scale, score: s,
    lx: x / scale, ly: y / scale, tw: sw, th: sh,
  }));
}

function tileStarts(len) {
  if (len <= TILE) return [0];
  const step = Math.floor(TILE * (1 - TILE_OVERLAP));
  const s = [];
  for (let v = 0; v < len - TILE; v += step) s.push(v);
  s.push(len - TILE);
  return s;
}

function overlap(a, b) {
  const x1 = Math.max(a.x, b.x), y1 = Math.max(a.y, b.y);
  const x2 = Math.min(a.x + a.w, b.x + b.w), y2 = Math.min(a.y + a.h, b.y + b.h);
  if (x2 <= x1 || y2 <= y1) return [0, 0];
  const inter = (x2 - x1) * (y2 - y1);
  return [inter / (a.w * a.h + b.w * b.h - inter), inter / Math.min(a.w * a.h, b.w * b.h)];
}

function merge(faces) {
  faces.sort((a, b) => b.score - a.score);
  const keep = [];
  for (const f of faces) {
    if (keep.every((k) => { const [iou, cont] = overlap(f, k); return iou <= 0.3 && cont <= 0.7; })) keep.push(f);
  }
  return keep;
}

async function detect(bitmap, accuracy, minScore) {
  const cfg = ACCURACY[accuracy] || ACCURACY.normal;
  const w = bitmap.width, h = bitmap.height, long = Math.max(w, h);
  let found = [];
  const levels = [...new Set(cfg.levels.map((lv) => Math.min(lv, Math.max(long, 640))))].sort((a, b) => a - b);
  for (const lv of levels) found = found.concat(await runModel(bitmap, 0, 0, w, h, lv / long));

  if (cfg.tiles && long > TILE * 1.25) {
    const maxFace = TILE * TILE_OVERLAP * 0.8, m = 4;
    for (const ty of tileStarts(h)) {
      for (const tx of tileStarts(w)) {
        const tw = Math.min(TILE, w - tx), th = Math.min(TILE, h - ty);
        for (const f of await runModel(bitmap, tx, ty, tw, th, 1)) {
          if (Math.max(f.w, f.h) > maxFace) continue; // stukje van een groot gezicht
          const cut = (f.lx < m && tx > 0) || (f.ly < m && ty > 0) ||
            (f.lx + f.w > tw - m && tx + tw < w) || (f.ly + f.h > th - m && ty + th < h);
          if (!cut) found.push(f);
        }
      }
    }
  }
  return merge(found.filter((f) => f.score >= minScore))
    .map(({ x, y, w: fw, h: fh, score }) => ({ x, y, w: fw, h: fh, score, manual: false }));
}

// ------------------------------------------------------------------ maskers
function maskBox(f, scale) {
  const size = Math.round(Math.max(f.w, f.h) * scale);
  return [Math.round(f.x + f.w / 2 - size / 2), Math.round(f.y + f.h / 2 - size / 2), size];
}

function render(bitmap, faces, s) {
  const c = new OffscreenCanvas(bitmap.width, bitmap.height);
  const ctx = c.getContext('2d');
  ctx.drawImage(bitmap, 0, 0);
  const small = new OffscreenCanvas(12, 12);
  const sctx = small.getContext('2d');
  const sorted = [...faces].sort((a, b) => a.w * a.h - b.w * b.h);
  for (const f of sorted) {
    const [x, y, size] = maskBox(f, s.scale);
    let mode = s.mode;
    if (mode === 'overlay' && !overlay) mode = 'pixelate'; // nooit onbedekt
    if (mode === 'overlay') {
      const r = size / Math.max(overlay.width, overlay.height);
      const dw = overlay.width * r, dh = overlay.height * r;
      ctx.save();
      if (s.mirror) {
        ctx.translate(x + size / 2, 0);
        ctx.scale(-1, 1);
        ctx.drawImage(overlay, -dw / 2, y + (size - dh) / 2, dw, dh);
      } else {
        ctx.drawImage(overlay, x + (size - dw) / 2, y + (size - dh) / 2, dw, dh);
      }
      ctx.restore();
    } else if (mode === 'pixelate') {
      small.width = 10; small.height = 10;
      sctx.drawImage(c, x, y, size, size, 0, 0, 10, 10);
      ctx.save();
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(small, 0, 0, 10, 10, x, y, size, size);
      ctx.restore();
    } else if (mode === 'blur') {
      small.width = 12; small.height = 12;
      sctx.filter = 'blur(1px)';
      sctx.drawImage(c, x, y, size, size, 0, 0, 12, 12);
      sctx.filter = 'none';
      ctx.save();
      ctx.beginPath();
      ctx.rect(x, y, size, size);
      ctx.clip();
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(small, 0, 0, 12, 12, x, y, size, size);
      ctx.restore();
    } else {
      ctx.fillStyle = '#000';
      ctx.fillRect(x, y, size, size);
    }
  }
  return c;
}

async function encode(canvas, type, quality) {
  return canvas.convertToBlob({ type, quality });
}

async function thumbnail(canvas) {
  const r = Math.min(1, THUMB / Math.max(canvas.width, canvas.height));
  const t = new OffscreenCanvas(Math.max(1, Math.round(canvas.width * r)), Math.max(1, Math.round(canvas.height * r)));
  const tctx = t.getContext('2d');
  tctx.imageSmoothingQuality = 'high';
  tctx.drawImage(canvas, 0, 0, t.width, t.height);
  return t.convertToBlob({ type: 'image/jpeg', quality: 0.8 });
}

async function decode(file) {
  try {
    return await createImageBitmap(file, { imageOrientation: 'from-image' }); // telefoonfoto's rechtop
  } catch (e) {
    const name = (file.name || '').toLowerCase();
    if (name.endsWith('.heic') || name.endsWith('.heif')) {
      throw new Error('HEIC-foto\'s (iPhone) kan de browser niet openen. Gebruik de desktop-app of exporteer als JPG.');
    }
    throw new Error('Dit bestand is geen leesbare foto.');
  }
}

// --------------------------------------------------------------- berichten
self.onmessage = async (e) => {
  const m = e.data;
  try {
    if (m.type === 'init') {
      session = await ort.InferenceSession.create('models/yunet.onnx', { executionProviders: ['wasm'] });
      self.postMessage({ type: 'ready' });
    } else if (m.type === 'overlay') {
      overlay = m.blob ? await createImageBitmap(m.blob) : null;
    } else if (m.type === 'process' || m.type === 'render') {
      const bitmap = await decode(m.file);
      const faces = m.type === 'process' ? await detect(bitmap, m.settings.accuracy, m.settings.confidence) : m.faces;
      const canvas = render(bitmap, faces, m.settings);
      const [blob, thumb] = await Promise.all([encode(canvas, m.outType, 0.92), thumbnail(canvas)]);
      self.postMessage({ type: 'done', id: m.id, faces, width: bitmap.width, height: bitmap.height, blob, thumb });
      bitmap.close();
    }
  } catch (err) {
    self.postMessage({ type: 'error', id: m.id, message: err && err.message ? err.message : String(err) });
  }
};
