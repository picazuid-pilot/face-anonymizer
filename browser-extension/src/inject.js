/*
 * Draait in de paginawereld (MAIN) vóór de scripts van de website.
 * Vervangt navigator.mediaDevices.getUserMedia: de website krijgt een
 * videotrack waarin gezichten al zijn afgedekt. Het ruwe camerabeeld komt
 * nooit bij de website.
 *
 * Veiligheidsprincipe: bij twijfel dicht. Zolang de detector niet klaar is of
 * niet meer reageert, wordt het hele beeld vervaagd.
 */
(() => {
  if (window.__faceAnonymizerInstalled) return;
  window.__faceAnonymizerInstalled = true;

  const md = navigator.mediaDevices;
  if (!md || typeof md.getUserMedia !== 'function') return;
  const originalGetUserMedia = md.getUserMedia.bind(md);

  const CONFIRM_HITS = 5;
  const TENTATIVE_PERSISTENCE = 5;
  const LOST_GROWTH = 0.02;
  const LOST_GROWTH_MAX = 0.4;
  const DETECTOR_STALE_MS = 1500;

  let port = null;
  let settings = null;
  let detectorUrl = null;
  let overlayBitmap = null;
  let resolveReady;
  const ready = new Promise((r) => { resolveReady = r; });

  /** Knipt een doorzichtige rand weg, zodat het logo het hele maskervlak vult. */
  async function trimTransparent(bitmap) {
    const w = bitmap.width, h = bitmap.height;
    const scale = Math.min(1, 512 / Math.max(w, h)); // zoeken op een kleine versie is snel genoeg
    const sw = Math.max(1, Math.round(w * scale)), sh = Math.max(1, Math.round(h * scale));
    const c = new OffscreenCanvas(sw, sh);
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(bitmap, 0, 0, sw, sh);
    const a = ctx.getImageData(0, 0, sw, sh).data;
    let x0 = sw, y0 = sh, x1 = -1, y1 = -1;
    for (let y = 0; y < sh; y++) {
      for (let x = 0; x < sw; x++) {
        if (a[(y * sw + x) * 4 + 3] > 8) {
          if (x < x0) x0 = x; if (x > x1) x1 = x;
          if (y < y0) y0 = y; if (y > y1) y1 = y;
        }
      }
    }
    if (x1 < 0 || (x0 === 0 && y0 === 0 && x1 === sw - 1 && y1 === sh - 1)) return bitmap;
    const sx = Math.floor(x0 / scale), sy = Math.floor(y0 / scale);
    const ex = Math.min(w, Math.ceil((x1 + 1) / scale)), ey = Math.min(h, Math.ceil((y1 + 1) / scale));
    const trimmed = await createImageBitmap(bitmap, sx, sy, ex - sx, ey - sy);
    bitmap.close();
    return trimmed;
  }

  async function setOverlay(blob) {
    try {
      overlayBitmap = blob ? await trimTransparent(await createImageBitmap(blob)) : null;
    } catch (e) {
      overlayBitmap = null;
      console.warn('[Face Anonymizer] overlay ongeldig', e);
    }
  }

  window.addEventListener('message', (e) => {
    if (e.source !== window || !e.data || e.data.__faInit !== true || port || !e.ports[0]) return;
    port = e.ports[0];
    detectorUrl = e.data.detectorUrl;
    settings = e.data.settings;
    setOverlay(e.data.overlay);
    port.onmessage = (ev) => {
      const m = ev.data || {};
      if (m.type === 'settings') settings = m.settings;
      else if (m.type === 'overlay') setOverlay(m.overlay);
    };
    resolveReady();
  });
  window.postMessage({ __faHello: true }, '*');

  // ------------------------------------------------------------ detector
  // Eén verborgen extensie-iframe per pagina draait het YuNet-model (WASM).
  const detector = {
    iframe: null, port: null, ready: false, seq: 0, pending: new Map(),

    ensure() {
      if (this.iframe && this.iframe.isConnected) return;
      this.ready = false;
      for (const p of this.pending.values()) p.reject(new Error('detector reset'));
      this.pending.clear();
      const ch = new MessageChannel();
      this.port = ch.port1;
      this.port.onmessage = (e) => this.onMessage(e.data);
      const f = document.createElement('iframe');
      f.src = detectorUrl;
      f.setAttribute('aria-hidden', 'true');
      f.tabIndex = -1;
      f.style.cssText = 'position:fixed;width:0;height:0;border:0;opacity:0;pointer-events:none;';
      f.addEventListener('load', () => {
        f.contentWindow.postMessage({ type: 'init' }, new URL(detectorUrl).origin, [ch.port2]);
      }, { once: true });
      (document.body || document.documentElement).appendChild(f);
      this.iframe = f;
    },

    onMessage(m) {
      if (m.type === 'ready') this.ready = true;
      else if (m.type === 'error') console.error('[Face Anonymizer] detector:', m.message);
      else if (m.type === 'result') {
        const p = this.pending.get(m.id);
        if (p) { this.pending.delete(m.id); p.resolve(m.boxes); }
      }
    },

    /** Detecteert gezichten; geeft boxen [x,y,w,h,score] in framecoördinaten. */
    async detect(frame, w, h) {
      this.ensure();
      if (!this.ready) { frame.close(); throw new Error('not ready'); }
      // Lange zijde naar de gekozen detectiegrootte; opvullen tot een veelvoud van 32
      // (zoals OpenCV) in plaats van tot een vierkant: scheelt bij 16:9 bijna de helft.
      const s = (settings.detectSize || 480) / Math.max(w, h);
      const cw = Math.max(1, Math.round(w * s)), ch = Math.max(1, Math.round(h * s));
      const W = Math.ceil(cw / 32) * 32, H = Math.ceil(ch / 32) * 32;
      let bitmap;
      try {
        bitmap = await createImageBitmap(frame, { resizeWidth: cw, resizeHeight: ch, resizeQuality: 'medium' });
      } finally {
        frame.close();
      }
      const id = ++this.seq;
      const result = new Promise((resolve, reject) => {
        this.pending.set(id, { resolve, reject });
        setTimeout(() => {
          if (this.pending.delete(id)) reject(new Error('timeout'));
        }, 1500);
      });
      this.port.postMessage({ type: 'detect', id, bitmap, W, H }, [bitmap]);
      const boxes = await result;
      return boxes.map(([x, y, bw, bh, score]) => [x / s, y / s, bw / s, bh / s, score]);
    },
  };

  // ------------------------------------------------------------- tracking
  function iou(a, b) {
    const x1 = Math.max(a.x, b.x), y1 = Math.max(a.y, b.y);
    const x2 = Math.min(a.x + a.w, b.x + b.w), y2 = Math.min(a.y + a.h, b.y + b.h);
    if (x2 <= x1 || y2 <= y1) return 0;
    const inter = (x2 - x1) * (y2 - y1);
    return inter / (a.w * a.h + b.w * b.h - inter);
  }

  const MAX_PREDICT_MS = 200;   // niet verder vooruit voorspellen dan dit
  const MAX_SPEED = 3;          // px per ms; hoger is vrijwel zeker een meetfout
  const MOTION_PAD_MS = 120;    // masker groeit met de afstand die je in deze tijd aflegt
  const MOTION_PAD_MAX = 0.35;

  class Tracker {
    constructor() { this.faces = []; this.tick = 0; }

    /** Voorspelde positie van een gezicht op tijdstip `now` (constante snelheid). */
    static predict(f, now) {
      const dt = Math.min(Math.max(0, now - f.t), MAX_PREDICT_MS);
      return { x: f.x + f.vx * dt, y: f.y + f.vy * dt, w: f.w, h: f.h };
    }

    /**
     * boxes: detecties in framecoördinaten; t: moment waarop het frame gemaakt is.
     * Koppelt op overlap én afstand, zodat een snelle beweging hetzelfde gezicht
     * blijft (geen spookmasker op de oude plek).
     */
    update(boxes, t) {
      this.tick++;
      const dets = boxes
        .filter(([, , w, h, s]) => s >= settings.confidence && w > settings.minSize && h > settings.minSize)
        .map(([x, y, w, h]) => ({ x, y, w, h }));

      const pairs = [];
      dets.forEach((d, i) => this.faces.forEach((f, j) => {
        const p = Tracker.predict(f, t);
        const v = iou(d, p);
        const dist = Math.hypot(d.x + d.w / 2 - (p.x + p.w / 2), d.y + d.h / 2 - (p.y + p.h / 2)) / Math.max(f.w, f.h);
        const score = v > 0.2 ? 1 + v : (dist < 1.2 ? 1 - dist / 1.2 : 0);
        if (score > 0) pairs.push([score, i, j]);
      }));
      pairs.sort((a, b) => b[0] - a[0]);
      const usedD = new Set(), usedF = new Set();
      for (const [, i, j] of pairs) {
        if (usedD.has(i) || usedF.has(j)) continue;
        usedD.add(i); usedF.add(j);
        const f = this.faces[j], d = dets[i];
        const dt = t - f.t;
        if (dt > 0 && dt < 1000) {
          const clamp = (v) => Math.max(-MAX_SPEED, Math.min(MAX_SPEED, v));
          const vx = clamp((d.x + d.w / 2 - (f.x + f.w / 2)) / dt);
          const vy = clamp((d.y + d.h / 2 - (f.y + f.h / 2)) / dt);
          f.vx = f.hits > 1 ? 0.6 * vx + 0.4 * f.vx : vx;
          f.vy = f.hits > 1 ? 0.6 * vy + 0.4 * f.vy : vy;
        }
        Object.assign(f, d, { t, last: this.tick });
        f.hits++;
      }
      dets.forEach((d, i) => {
        if (!usedD.has(i)) this.faces.push({ ...d, t, vx: 0, vy: 0, last: this.tick, hits: 1 });
      });

      // Kwijtgeraakte tracks die in een vers gezien gezicht vallen zijn dubbel
      const fresh = this.faces.filter((f) => f.last === this.tick);
      this.faces = this.faces.filter((f) => {
        if (f.last !== this.tick && fresh.some((g) =>
          Math.hypot(f.x + f.w / 2 - (g.x + g.w / 2), f.y + f.h / 2 - (g.y + g.h / 2)) < 0.8 * Math.max(g.w, g.h))) {
          return false;
        }
        let limit = settings.persistence;
        if (settings.smartPersistence && f.hits < CONFIRM_HITS) limit = Math.min(limit, TENTATIVE_PERSISTENCE);
        return this.tick - f.last <= limit;
      });
    }

    /**
     * Vierkante maskers [x, y, size] op tijdstip `now`, kleinste eerst.
     * Ze schuiven mee met de beweging, groeien bij snelle bewegingen en als
     * een gezicht kwijt is.
     */
    masks(now) {
      return this.faces
        .map((f) => {
          const p = Tracker.predict(f, now);
          const base = Math.max(f.w, f.h);
          const lost = this.tick - f.last;
          const motion = Math.min(MOTION_PAD_MAX, Math.hypot(f.vx, f.vy) * MOTION_PAD_MS / base);
          const grow = 1 + Math.min(LOST_GROWTH_MAX, LOST_GROWTH * lost) + motion;
          const size = base * settings.scale * grow;
          return [p.x + p.w / 2 - size / 2, p.y + p.h / 2 - size / 2, size];
        })
        .sort((a, b) => a[2] - b[2]);
    }
  }

  // ------------------------------------------------------------ rendering
  class Renderer {
    constructor() {
      this.canvas = new OffscreenCanvas(2, 2);
      this.ctx = this.canvas.getContext('2d', { alpha: false, desynchronized: true });
      this.small = new OffscreenCanvas(8, 8);
      this.sctx = this.small.getContext('2d');
      this.tracker = new Tracker();
      this.busy = false;
      this.lastResult = -Infinity; // "nog nooit": niet 0, want performance.now() begint bij het laden van de pagina
    }

    scheduleDetection(frame, w, h) {
      if (this.busy) return;
      this.busy = true;
      const t = performance.now(); // moment van dit frame; de uitkomst komt later binnen
      detector.detect(frame.clone(), w, h)
        .then((boxes) => { this.tracker.update(boxes, t); this.lastResult = performance.now(); })
        .catch(() => { /* fail-safe hieronder vangt dit af */ })
        .finally(() => { this.busy = false; });
    }

    process(frame) {
      const w = frame.displayWidth, h = frame.displayHeight;
      if (this.canvas.width !== w || this.canvas.height !== h) {
        this.canvas.width = w;
        this.canvas.height = h;
      }
      const ctx = this.ctx;
      ctx.drawImage(frame, 0, 0, w, h);
      this.scheduleDetection(frame, w, h);

      const healthy = performance.now() - this.lastResult < DETECTOR_STALE_MS;
      if (!healthy && settings.failSafeBlur) {
        this.failSafe(w, h);
      } else {
        for (const [x, y, size] of this.tracker.masks(performance.now())) this.mask(x, y, size);
      }
      return new VideoFrame(this.canvas, { timestamp: frame.timestamp, duration: frame.duration ?? undefined });
    }

    failSafe(w, h) {
      const ctx = this.ctx;
      // Sterk verkleinen en weer vergroten: onherkenbaar, ook zonder filter-ondersteuning
      this.small.width = 16; this.small.height = 9;
      this.sctx.drawImage(this.canvas, 0, 0, 16, 9);
      ctx.save();
      ctx.filter = 'blur(12px)';
      ctx.drawImage(this.small, 0, 0, 16, 9, -20, -20, w + 40, h + 40);
      ctx.restore();
      ctx.fillStyle = 'rgba(0,0,0,0.45)';
      ctx.fillRect(0, h / 2 - 30, w, 60);
      ctx.fillStyle = '#fff';
      ctx.font = `${Math.max(16, Math.round(h / 24))}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('Face Anonymizer wordt geladen…', w / 2, h / 2);
    }

    mask(x, y, size) {
      const ctx = this.ctx;
      let mode = settings.mode;
      if (mode === 'overlay' && !overlayBitmap) mode = 'pixelate'; // nooit onbedekt

      if (mode === 'overlay') {
        const ow = overlayBitmap.width, oh = overlayBitmap.height;
        const r = size / Math.max(ow, oh);
        const dw = ow * r, dh = oh * r;
        if (settings.mirrorOverlay) {
          // Spiegelen rond het midden van het masker
          ctx.save();
          ctx.translate(x + size / 2, 0);
          ctx.scale(-1, 1);
          ctx.drawImage(overlayBitmap, -dw / 2, y + (size - dh) / 2, dw, dh);
          ctx.restore();
        } else {
          ctx.drawImage(overlayBitmap, x + (size - dw) / 2, y + (size - dh) / 2, dw, dh);
        }
      } else if (mode === 'pixelate') {
        this.small.width = 8; this.small.height = 8;
        this.sctx.drawImage(this.canvas, x, y, size, size, 0, 0, 8, 8);
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(this.small, 0, 0, 8, 8, x, y, size, size);
        ctx.imageSmoothingEnabled = true;
      } else if (mode === 'blur') {
        ctx.save();
        ctx.beginPath();
        ctx.rect(x, y, size, size);
        ctx.clip();
        ctx.filter = `blur(${Math.max(10, Math.round(size / 6))}px)`;
        ctx.drawImage(this.canvas, 0, 0);
        ctx.restore();
      } else {
        ctx.fillStyle = '#000';
        ctx.fillRect(x, y, size, size);
      }
    }
  }

  // ---------------------------------------------------- track vervangen
  function wrapTrack(src) {
    const processor = new MediaStreamTrackProcessor({ track: src });
    const generator = new MediaStreamTrackGenerator({ kind: 'video' });
    const renderer = new Renderer();

    processor.readable.pipeThrough(new TransformStream({
      transform(frame, controller) {
        if (!settings.enabled) { controller.enqueue(frame); return; } // live uit te zetten
        let out;
        try {
          out = renderer.process(frame);
        } catch (e) {
          console.error('[Face Anonymizer]', e);
          out = null; // frame overslaan i.p.v. onbewerkt doorsturen
        } finally {
          frame.close();
        }
        if (out) controller.enqueue(out);
      },
    })).pipeTo(generator.writable).catch(() => {});

    // Gedrag van de echte camera doorgeven, zodat de webapp niets merkt
    const stopGenerator = generator.stop.bind(generator);
    generator.stop = () => { stopGenerator(); src.stop(); };
    src.addEventListener('ended', () => { try { stopGenerator(); } catch (_) { /* al gestopt */ } });
    generator.getSettings = () => src.getSettings();
    generator.getConstraints = () => src.getConstraints();
    generator.applyConstraints = (c) => src.applyConstraints(c);
    if (src.getCapabilities) generator.getCapabilities = () => src.getCapabilities();
    Object.defineProperty(generator, 'label', { get: () => src.label });
    return generator;
  }

  function stopAll(stream) { stream.getTracks().forEach((t) => t.stop()); }

  async function getUserMedia(constraints) {
    const stream = await originalGetUserMedia(constraints);
    if (!stream.getVideoTracks().length) return stream;

    await Promise.race([ready, new Promise((r) => setTimeout(r, 3000))]);
    if (!settings) {
      stopAll(stream);
      throw new DOMException('Face Anonymizer is niet goed geladen. Herlaad de pagina.', 'NotReadableError');
    }
    if (!('MediaStreamTrackProcessor' in window) || !('MediaStreamTrackGenerator' in window)) {
      if (!settings.enabled) return stream;
      stopAll(stream);
      throw new DOMException('Deze browser wordt niet ondersteund door Face Anonymizer (gebruik Chrome of Edge).', 'NotSupportedError');
    }
    const out = new MediaStream();
    for (const t of stream.getTracks()) out.addTrack(t.kind === 'video' ? wrapTrack(t) : t);
    return out;
  }

  // Zo native mogelijk ogen: sommige sites controleren de functienaam
  Object.defineProperty(getUserMedia, 'name', { value: 'getUserMedia' });
  md.getUserMedia = getUserMedia;
})();
