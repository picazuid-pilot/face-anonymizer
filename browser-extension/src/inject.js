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

  async function setOverlay(blob) {
    try {
      overlayBitmap = blob ? await createImageBitmap(blob) : null;
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
      const s = 640 / Math.max(w, h); // letterbox naar 640x640
      let bitmap;
      try {
        bitmap = await createImageBitmap(frame, {
          resizeWidth: Math.max(1, Math.round(w * s)),
          resizeHeight: Math.max(1, Math.round(h * s)),
          resizeQuality: 'medium',
        });
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
      this.port.postMessage({ type: 'detect', id, bitmap }, [bitmap]);
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

  class Tracker {
    constructor() { this.faces = []; this.tick = 0; }

    update(boxes) {
      this.tick++;
      const dets = boxes
        .filter(([, , w, h, s]) => s >= settings.confidence && w > settings.minSize && h > settings.minSize)
        .map(([x, y, w, h]) => ({ x, y, w, h }));

      // Gulzige koppeling op hoogste overlap (bij enkele tot tientallen gezichten
      // praktisch gelijk aan de Hongaarse methode in de Python-tool).
      const pairs = [];
      dets.forEach((d, i) => this.faces.forEach((f, j) => {
        const v = iou(d, f);
        if (v > 0.25) pairs.push([v, i, j]);
      }));
      pairs.sort((a, b) => b[0] - a[0]);
      const usedD = new Set(), usedF = new Set();
      for (const [, i, j] of pairs) {
        if (usedD.has(i) || usedF.has(j)) continue;
        usedD.add(i); usedF.add(j);
        Object.assign(this.faces[j], dets[i], { last: this.tick });
        this.faces[j].hits++;
      }
      dets.forEach((d, i) => {
        if (!usedD.has(i)) this.faces.push({ ...d, last: this.tick, hits: 1 });
      });

      this.faces = this.faces.filter((f) => {
        let limit = settings.persistence;
        if (settings.smartPersistence && f.hits < CONFIRM_HITS) limit = Math.min(limit, TENTATIVE_PERSISTENCE);
        return this.tick - f.last <= limit;
      });
    }

    /** Vierkante maskers [x, y, size], kleinste eerst; groeien als een gezicht kwijt is. */
    masks() {
      return this.faces
        .map((f) => {
          const lost = this.tick - f.last;
          const grow = 1 + Math.min(LOST_GROWTH_MAX, LOST_GROWTH * lost);
          const size = Math.max(f.w, f.h) * settings.scale * grow;
          return [f.x + f.w / 2 - size / 2, f.y + f.h / 2 - size / 2, size];
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
      detector.detect(frame.clone(), w, h)
        .then((boxes) => { this.tracker.update(boxes); this.lastResult = performance.now(); })
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
        for (const [x, y, size] of this.tracker.masks()) this.mask(x, y, size);
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
        ctx.drawImage(overlayBitmap, x + (size - ow * r) / 2, y + (size - oh * r) / 2, ow * r, oh * r);
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
