/*
 * Face Anonymizer Camera: filmen en fotograferen met gezichten al afgedekt.
 *
 * Veiligheidsprincipes
 * - Wat je ziet is wat wordt opgeslagen: video's worden opgenomen vanaf het
 *   bewerkte beeld (canvas), nooit vanaf de camera zelf.
 * - Bij twijfel dicht: zolang de gezichtsherkenning niet klaar is of niet meer
 *   reageert, wordt het hele beeld vervaagd (ook in de opname).
 * - Niets verlaat het toestel: geen netwerkverbindingen (zie CSP in index.html).
 */
/* global YuNet, FaTracker */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const DEFAULTS = {
    mode: 'overlay', kind: 'photo', scale: 1.6, confidence: 0.6, detectSize: 480,
    mirror: false, audio: true, resolution: 1080, facing: 'environment', protect: true,
    colorFixCam: { environment: 'auto', user: 'auto' }, // kleurcorrectie per camera
  };
  const STORE = 'fa-camera-settings';
  const LOGO_STORE = 'fa-camera-logo';
  const PERSISTENCE = 15;          // detecties dat een kwijtgeraakt gezicht afgedekt blijft
  const MIN_SIZE = 10;             // kleinste gezicht in beeldpixels
  const STALE_MS = 1200;           // langer geen detectie = heel beeld vervagen
  const PROTECT_CELLS = 24;        // beschermende blur: beeld terug naar 24 blokjes breed
  const MAX_RECORD_MS = 20 * 60 * 1000; // opnames staan in het geheugen tot je ze bewaart

  // ------------------------------------------------------------ instellingen
  let S = { ...DEFAULTS };
  try { S = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORE) || '{}') }; } catch (_) { /* privévenster */ }
  // Oude instelling (één waarde voor alle camera's): alleen voor de achtercamera overnemen
  if (typeof S.colorFix === 'string') {
    S.colorFixCam = { environment: S.colorFix, user: 'auto' };
    delete S.colorFix;
  }
  S.colorFixCam = { environment: 'auto', user: 'auto', ...(S.colorFixCam || {}) };
  const save = () => { try { localStorage.setItem(STORE, JSON.stringify(S)); } catch (_) { /* geen opslag */ } };

  // ---------------------------------------------------------------- elementen
  const video = $('cam');
  const view = $('view');
  const ctx = view.getContext('2d', { alpha: false });
  const det = document.createElement('canvas');
  const dctx = det.getContext('2d', { willReadFrequently: true });
  const small = document.createElement('canvas');
  const sctx = small.getContext('2d');
  const tracker = new FaTracker();

  // -------------------------------------------------------------------- staat
  let worker = null;
  let detectorReady = false;
  let detectorFailed = false;
  let busySince = 0;
  let liveReq = null;
  let lastResult = -Infinity;
  let reqId = 0;
  let detectMs = 0;
  const photoReqs = new Map();

  let stream = null;
  let micStream = null;
  let running = false;
  let fps = 0, fpsCount = 0, fpsT0 = 0;
  let healthy = false;
  let lastFaceCount = 0;

  let recorder = null;
  let recStart = 0;
  let recTimer = null;

  let overlay = null;
  let result = null;
  let wakeLock = null;
  let installPrompt = null;

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  // In de Android-app (Capacitor) bewaren en delen we via de app zelf
  const cap = window.Capacitor;
  const native = !!(cap && cap.isNativePlatform && cap.isNativePlatform() && cap.nativePromise);

  // --------------------------------------------------------------- meldingen
  let toastTimer = null;
  function toast(text, ms = 3500) {
    const t = $('toast');
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, ms);
  }

  let statusKey = '';
  function setStatus(cls, text) {
    const key = cls + text;
    if (key === statusKey) return;
    statusKey = key;
    const el = $('status');
    el.className = 'status ' + cls;
    $('status-text').textContent = text;
  }

  function refreshStatus() {
    if (recorder) {
      const s = Math.floor((performance.now() - recStart) / 1000);
      setStatus('rec', `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`);
    } else if (detectorFailed) {
      setStatus('', 'Herkenning werkt niet');
    } else if (!detectorReady) {
      setStatus('', 'Herkenning laden…');
    } else if (!healthy) {
      setStatus('', 'Even geduld…');
    } else {
      const n = lastFaceCount;
      if (n === 0 && S.protect) setStatus('', 'Beschermd · geen gezicht');
      else setStatus('ok', n === 0 ? 'Actief · geen gezichten' : `Actief · ${n} ${n === 1 ? 'gezicht' : 'gezichten'}`);
    }
    $('stats').textContent = running
      ? `Beeld ${video.videoWidth}×${video.videoHeight} · ${fps.toFixed(0)} fps · herkenning ${detectMs.toFixed(0)} ms · kleur ${
        swapRB() ? 'gecorrigeerd' : colorMode() === 'auto' && swapAuto === null ? 'wordt gecontroleerd' : 'normaal'}${frameFormat ? ` (${frameFormat})` : ''}`
      : '';
  }

  // ---------------------------------------------------------------- detector
  function startWorker() {
    worker = new Worker('detector-worker.js');
    worker.onmessage = (e) => {
      const m = e.data || {};
      if (m.type === 'ready') {
        detectorReady = true;
      } else if (m.type === 'live') {
        if (liveReq && liveReq.id === m.id) {
          const { s, t } = liveReq;
          liveReq = null;
          const boxes = m.boxes.map(([x, y, w, h, sc]) => [x / s, y / s, w / s, h / s, sc]);
          tracker.update(boxes, t, { confidence: S.confidence, minSize: MIN_SIZE, persistence: PERSISTENCE });
          lastResult = performance.now();
          detectMs = detectMs ? 0.85 * detectMs + 0.15 * m.ms : m.ms;
        }
      } else if (m.type === 'photo') {
        const r = photoReqs.get(m.id);
        if (r) { photoReqs.delete(m.id); r.resolve(m.boxes); }
      } else if (m.type === 'error') {
        console.error('[FA Camera] detector:', m.message);
        if (m.kind === 'live') liveReq = null;
        if (m.kind === 'photo') {
          const r = photoReqs.get(m.id);
          if (r) { photoReqs.delete(m.id); r.reject(new Error(m.message)); }
        }
        if (m.kind === 'init') detectorFailed = true;
      }
    };
    worker.onerror = (e) => {
      console.error('[FA Camera] worker', e.message);
      detectorFailed = true;
    };
    worker.postMessage({ type: 'init' });
  }

  /** Stuurt een verkleind beeld naar de detector als die vrij is. */
  function maybeDetect(vw, vh, now) {
    if (!detectorReady) return;
    if (liveReq) {
      if (now - busySince < 2000) return;
      liveReq = null; // antwoord kwijt: niet blijven wachten
    }
    const { scale, cw, ch, W, H } = YuNet.inputSize(vw, vh, S.detectSize);
    if (det.width !== W || det.height !== H) { det.width = W; det.height = H; }
    dctx.fillStyle = '#000';
    dctx.fillRect(0, 0, W, H);
    drawVideo(dctx, 0, 0, cw, ch);
    const buffer = dctx.getImageData(0, 0, W, H).data.buffer;
    const id = ++reqId;
    liveReq = { id, s: scale, t: now };
    busySince = now;
    worker.postMessage({ type: 'live', id, buffer, W, H }, [buffer]);
  }

  function detectPhoto(bitmap) {
    const id = ++reqId;
    return new Promise((resolve, reject) => {
      photoReqs.set(id, { resolve, reject });
      setTimeout(() => { if (photoReqs.delete(id)) reject(new Error('timeout')); }, 5000);
      worker.postMessage({ type: 'photo', id, bitmap, minScore: S.confidence }, [bitmap]);
    });
  }

  // ----------------------------------------------------------- kleurcorrectie
  // Sommige telefooncamera's (gezien in de Android-app, achtercamera) leveren beelden
  // waarin rood en blauw omgewisseld zijn als ze op een canvas getekend worden.
  // We vergelijken daarom de echte pixels van een cameraframe (VideoFrame.copyTo)
  // met wat het canvas ervan maakt, en wisselen zo nodig terug met een SVG-filter.
  let swapAuto = null;  // null = nog niet bepaald
  let colorChecks = 0;
  const probe = document.createElement('canvas');
  probe.width = 64; probe.height = 36;
  const pctx = probe.getContext('2d', { willReadFrequently: true });

  const colorMode = () => S.colorFixCam[S.facing] || 'auto';
  const swapRB = () => colorMode() === 'on' || (colorMode() === 'auto' && swapAuto === true);

  /** Tekent het camerabeeld, met kleurcorrectie als dat nodig is. */
  function drawVideo(c, x, y, w, h) {
    if (swapRB()) {
      c.save();
      c.filter = 'url(#fa-swap-rb)';
      c.drawImage(video, x, y, w, h);
      c.restore();
    } else {
      c.drawImage(video, x, y, w, h);
    }
  }

  function meanRGB(data) {
    let r = 0, g = 0, b = 0;
    const n = data.length / 4;
    for (let i = 0; i < data.length; i += 4) { r += data[i]; g += data[i + 1]; b += data[i + 2]; }
    return { r: r / n, g: g / n, b: b / n };
  }

  /** Gemiddelde kleur uit de ruwe pixels van een cameraframe, of null als dat niet kan. */
  let frameFormat = '';
  async function frameMeanRGB(vf) {
    const fmt = vf.format;
    frameFormat = fmt || 'onbekend';
    if (!fmt) return null;
    const buf = new Uint8Array(vf.allocationSize());
    const layout = await vf.copyTo(buf);
    const vr = vf.visibleRect || { x: 0, y: 0, width: vf.codedWidth, height: vf.codedHeight };
    const full = !!(vf.colorSpace && vf.colorSpace.fullRange);
    let r = 0, g = 0, b = 0, n = 0;
    for (let sy = 0; sy < 18; sy++) {
      for (let sx = 0; sx < 32; sx++) {
        const px = Math.floor(vr.x + (sx + 0.5) * vr.width / 32);
        const py = Math.floor(vr.y + (sy + 0.5) * vr.height / 18);
        let R, G, B;
        if (fmt === 'I420' || fmt === 'I420A' || fmt === 'NV12') {
          const Y = buf[layout[0].offset + py * layout[0].stride + px];
          let U, V;
          const cx = px >> 1, cy = py >> 1;
          if (fmt === 'NV12') {
            const o = layout[1].offset + cy * layout[1].stride + cx * 2;
            U = buf[o]; V = buf[o + 1];
          } else {
            U = buf[layout[1].offset + cy * layout[1].stride + cx];
            V = buf[layout[2].offset + cy * layout[2].stride + cx];
          }
          const yy = full ? Y : 1.164 * (Y - 16);
          const k = full ? 1 : 1.138; // chroma-schaal bij beperkt bereik
          R = yy + 1.402 * k * (V - 128);
          G = yy - 0.344 * k * (U - 128) - 0.714 * k * (V - 128);
          B = yy + 1.772 * k * (U - 128);
        } else if (fmt === 'RGBA' || fmt === 'RGBX' || fmt === 'BGRA' || fmt === 'BGRX') {
          const o = layout[0].offset + py * layout[0].stride + px * 4;
          const bgr = fmt[0] === 'B';
          R = buf[o + (bgr ? 2 : 0)]; G = buf[o + 1]; B = buf[o + (bgr ? 0 : 2)];
        } else {
          return null;
        }
        r += R; g += G; b += B; n++;
      }
    }
    return { r: r / n, g: g / n, b: b / n };
  }

  async function checkColors() {
    if (colorMode() !== 'auto' || swapAuto !== null || !running || !video.videoWidth) return;
    if (++colorChecks > 40 || typeof VideoFrame === 'undefined') { swapAuto = swapAuto ?? false; return; }
    let vf;
    try { vf = new VideoFrame(video, { timestamp: 0 }); } catch (_) { return; }
    try {
      // Zelfde moment: eerst het canvas laten tekenen, dan de ruwe pixels lezen
      pctx.drawImage(video, 0, 0, probe.width, probe.height);
      const shown = meanRGB(pctx.getImageData(0, 0, probe.width, probe.height).data);
      const truth = await frameMeanRGB(vf);
      if (!truth) { swapAuto = false; return; }
      if (Math.abs(truth.r - truth.b) < 12) return; // te grijs om te beoordelen; straks opnieuw
      const same = Math.abs(shown.r - truth.r) + Math.abs(shown.b - truth.b);
      const swapped = Math.abs(shown.r - truth.b) + Math.abs(shown.b - truth.r);
      if (swapped < same * 0.5) {
        swapAuto = true;
        toast('Kleuren van deze camera gecorrigeerd: rood en blauw waren omgewisseld.', 4000);
      } else if (same < swapped * 0.5) {
        swapAuto = false;
      }
    } catch (e) {
      console.warn('[FA Camera] kleurcontrole', e);
    } finally {
      vf.close();
    }
  }
  setInterval(checkColors, 700);

  // ----------------------------------------------------------------- maskers
  /** Tekent één masker in een vierkant [x, y, size] op ctx (die van canvas `cv` is). */
  function drawMask(c, cv, x, y, size) {
    let mode = S.mode;
    if (mode === 'overlay' && !overlay) mode = 'pixelate'; // nooit onbedekt

    if (mode === 'overlay') {
      const ow = overlay.width, oh = overlay.height;
      const r = size / Math.max(ow, oh);
      const dw = ow * r, dh = oh * r;
      c.save();
      if (S.mirror) {
        c.translate(x + size / 2, 0);
        c.scale(-1, 1);
        c.drawImage(overlay, -dw / 2, y + (size - dh) / 2, dw, dh);
      } else {
        c.drawImage(overlay, x + (size - dw) / 2, y + (size - dh) / 2, dw, dh);
      }
      c.restore();
      return;
    }
    if (mode === 'black') {
      c.fillStyle = '#000';
      c.fillRect(x, y, size, size);
      return;
    }
    // Pixels en blur lezen het beeld zelf; binnen het canvas blijven (Safari tekent
    // niets als de bron buiten het canvas valt).
    const x0 = Math.max(0, Math.floor(x)), y0 = Math.max(0, Math.floor(y));
    const x1 = Math.min(cv.width, Math.ceil(x + size)), y1 = Math.min(cv.height, Math.ceil(y + size));
    const w = x1 - x0, h = y1 - y0;
    if (w < 2 || h < 2) return;
    const cells = mode === 'pixelate' ? 9 : 6;
    const k = cells / Math.max(w, h);
    const sw = Math.max(1, Math.round(w * k)), sh = Math.max(1, Math.round(h * k));
    small.width = sw; small.height = sh;
    sctx.imageSmoothingEnabled = true;
    sctx.drawImage(cv, x0, y0, w, h, 0, 0, sw, sh);
    c.save();
    c.imageSmoothingEnabled = mode !== 'pixelate';
    if (mode === 'blur') c.imageSmoothingQuality = 'high';
    c.drawImage(small, 0, 0, sw, sh, x0, y0, w, h);
    c.restore();
  }

  /** Heel beeld vervagen door het sterk te verkleinen en weer te vergroten (werkt overal, ook op Safari). */
  function blurAll(c, cv, cells) {
    const W = cv.width, H = cv.height;
    small.width = cells; small.height = Math.max(1, Math.round(cells * H / W));
    sctx.imageSmoothingEnabled = true;
    sctx.drawImage(cv, 0, 0, small.width, small.height);
    c.save();
    c.imageSmoothingEnabled = true;
    c.imageSmoothingQuality = 'high';
    c.drawImage(small, 0, 0, small.width, small.height, 0, 0, W, H);
    c.restore();
  }

  /** Heel beeld onherkenbaar zolang de herkenning niet (meer) werkt. */
  function failSafe(c, cv, text) {
    const W = cv.width, H = cv.height;
    blurAll(c, cv, 16);
    c.save();
    c.fillStyle = 'rgba(0,0,0,.45)';
    const band = Math.max(48, Math.max(W, H) / 11); // leesbaar, ook staand op een telefoon
    c.fillRect(0, H / 2 - band / 2, W, band);
    c.fillStyle = '#fff';
    c.font = `600 ${Math.round(band * 0.34)}px system-ui, sans-serif`;
    c.textAlign = 'center';
    c.textBaseline = 'middle';
    c.fillText(text, W / 2, H / 2);
    c.restore();
  }

  // ----------------------------------------------------------------- tekenen
  function loop() {
    if (!running) return;
    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(loop);
    else requestAnimationFrame(loop);

    const vw = video.videoWidth, vh = video.videoHeight;
    if (!vw || !vh) return;
    if (!recorder && (view.width !== vw || view.height !== vh)) {
      view.width = vw;  // tijdens een opname blijft het formaat vast
      view.height = vh;
    }
    const k = Math.min(view.width / vw, view.height / vh);
    const dw = vw * k, dh = vh * k, dx = (view.width - dw) / 2, dy = (view.height - dh) / 2;
    if (dx > 0.5 || dy > 0.5) { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, view.width, view.height); }
    drawVideo(ctx, dx, dy, dw, dh);

    const now = performance.now();
    maybeDetect(vw, vh, now);
    healthy = detectorReady && now - lastResult < STALE_MS;
    if (!healthy) {
      failSafe(ctx, view, detectorFailed ? 'Gezichtsherkenning werkt niet' : 'Gezichtsherkenning wordt geladen…');
    } else {
      const masks = tracker.masks(now, S.scale);
      lastFaceCount = masks.length;
      if (S.protect && masks.length === 0) {
        // Geen gezicht gevonden: misschien wel een gemist. Alles vervagen (zonder tekst, want dit wordt ook opgenomen).
        blurAll(ctx, view, PROTECT_CELLS);
      } else {
        for (const [x, y, size] of masks) drawMask(ctx, view, dx + x * k, dy + y * k, size * k);
      }
    }

    fpsCount++;
    if (now - fpsT0 > 1000) {
      fps = (fpsCount * 1000) / (now - fpsT0);
      fpsCount = 0;
      fpsT0 = now;
    }
  }

  // ------------------------------------------------------------------ camera
  function stopStream() {
    running = false;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  function cameraError(e) {
    const n = e && e.name;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return 'Deze browser geeft geen toegang tot de camera. Open de pagina via https:// in Chrome of Safari.';
    }
    if (n === 'NotAllowedError' || n === 'SecurityError') {
      return isIOS
        ? 'Geen toestemming voor de camera. Ga naar Instellingen → Safari → Camera en kies "Vraag" of "Sta toe", en probeer het opnieuw.'
        : 'Geen toestemming voor de camera. Tik op het slotje naast het webadres, sta de camera toe en probeer het opnieuw.';
    }
    if (n === 'NotFoundError' || n === 'OverconstrainedError') return 'Geen camera gevonden.';
    if (n === 'NotReadableError' || n === 'AbortError') return 'De camera wordt al door een andere app gebruikt. Sluit die app en probeer het opnieuw.';
    return `De camera kon niet starten (${(e && e.message) || n || 'onbekende fout'}).`;
  }

  async function startCamera() {
    stopStream();
    const long = S.resolution >= 1080 ? 1920 : 1280;
    const short = S.resolution >= 1080 ? 1080 : 720;
    const videoC = {
      facingMode: { ideal: S.facing },
      width: { ideal: long }, height: { ideal: short }, frameRate: { ideal: 30 },
    };
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: videoC, audio: S.audio });
    } catch (e) {
      if (!S.audio || e.name === 'NotFoundError' && !(await hasCamera())) throw e;
      stream = await navigator.mediaDevices.getUserMedia({ video: videoC, audio: false });
      S.audio = false;
      save();
      syncUI();
      toast('Geen toegang tot de microfoon: video\'s worden zonder geluid opgenomen.', 5000);
    }
    video.srcObject = new MediaStream(stream.getVideoTracks());
    await video.play().catch(() => {});
    tracker.reset();
    swapAuto = null; // elke camera opnieuw controleren
    frameFormat = '';
    colorChecks = 0;
    lastResult = -Infinity; // nieuwe camera: eerst weer een verse detectie
    running = true;
    fpsT0 = performance.now();
    loop();
    keepAwake();
    updateFlipButton();
  }

  async function hasCamera() {
    try {
      return (await navigator.mediaDevices.enumerateDevices()).some((d) => d.kind === 'videoinput');
    } catch (_) { return true; }
  }

  async function updateFlipButton() {
    try {
      const cams = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput');
      $('flip-btn').hidden = cams.length < 2;
    } catch (_) { /* laten staan */ }
  }

  async function keepAwake() {
    try {
      if ('wakeLock' in navigator && !wakeLock && document.visibilityState === 'visible') {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => { wakeLock = null; });
      }
    } catch (_) { /* niet ondersteund of geweigerd */ }
  }

  // ------------------------------------------------------------------- foto
  async function takePhoto() {
    if (!healthy) { toast('Even wachten tot de gezichtsherkenning klaar is.'); return; }
    const vw = video.videoWidth, vh = video.videoHeight;
    const live = tracker.masks(performance.now(), S.scale);
    const c = document.createElement('canvas');
    c.width = vw; c.height = vh;
    const cx = c.getContext('2d');
    drawVideo(cx, 0, 0, vw, vh);
    flash();
    $('shutter').disabled = true;

    // Op de foto zelf nog een keer grondig zoeken (ook kleinere gezichten verderop)
    let extra = [];
    try {
      extra = await detectPhoto(await createImageBitmap(c));
    } catch (e) {
      console.warn('[FA Camera] grondige detectie mislukt, live maskers gebruikt', e);
    }
    const masks = [...live];
    for (const [x, y, w, h] of extra) {
      const mx = x + w / 2, my = y + h / 2, size = Math.max(w, h) * S.scale;
      const covered = live.some(([lx, ly, ls]) => mx > lx && mx < lx + ls && my > ly && my < ly + ls);
      if (!covered) masks.push([mx - size / 2, my - size / 2, size]);
    }
    masks.sort((a, b) => a[2] - b[2]);
    const protectedAll = S.protect && masks.length === 0;
    if (protectedAll) blurAll(cx, c, PROTECT_CELLS);
    else for (const [x, y, size] of masks) drawMask(cx, c, x, y, size);

    const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.92));
    c.width = c.height = 0; // onbewerkt beeld direct weg
    $('shutter').disabled = false;
    if (!blob) { toast('Foto opslaan mislukt.'); return; }
    const n = masks.length;
    showResult(blob, 'photo', `${vw}×${vh} · ${protectedAll ? 'geen gezicht gevonden, hele foto vervaagd (beschermende blur; zet het schildje uit voor foto\'s zonder mensen)'
      : n === 0 ? 'geen gezichten gevonden' : n === 1 ? '1 gezicht afgedekt' : `${n} gezichten afgedekt`}`);
  }

  function flash() {
    const f = $('flash');
    f.classList.add('on');
    requestAnimationFrame(() => requestAnimationFrame(() => f.classList.remove('on')));
  }

  // ------------------------------------------------------------------ video
  function pickMime() {
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
    const list = [
      'video/mp4;codecs=avc1.42E01F,mp4a.40.2', 'video/mp4;codecs=avc1', 'video/mp4',
      'video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm',
    ];
    return list.find((t) => MediaRecorder.isTypeSupported(t)) || '';
  }

  async function startRecording() {
    if (!window.MediaRecorder || !view.captureStream) {
      toast('Filmen wordt door deze browser niet ondersteund. Gebruik Chrome (Android) of Safari (iPhone).', 5000);
      return;
    }
    const tracks = [...view.captureStream(30).getVideoTracks()];
    if (S.audio) {
      let audio = stream.getAudioTracks();
      if (!audio.length) {
        try {
          micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
          audio = micStream.getAudioTracks();
        } catch (_) {
          toast('Geen toegang tot de microfoon: opname zonder geluid.');
        }
      }
      tracks.push(...audio);
    }
    const mime = pickMime();
    const opts = { videoBitsPerSecond: S.resolution >= 1080 ? 6e6 : 3.5e6 };
    if (mime) opts.mimeType = mime;
    let rec;
    try {
      rec = new MediaRecorder(new MediaStream(tracks), opts);
    } catch (e) {
      toast(`Opnemen kon niet starten (${e.message}).`);
      return;
    }
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      const type = (rec.mimeType || mime || 'video/webm').split(';')[0];
      const blob = new Blob(chunks, { type });
      const secs = Math.round((performance.now() - recStart) / 1000);
      tracks.forEach((t) => { if (t.kind === 'video') t.stop(); });
      if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
      recorder = null;
      clearInterval(recTimer);
      syncUI();
      if (!blob.size) { toast('De opname is leeg.'); return; }
      showResult(blob, 'video', `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')} min · ${view.width}×${view.height}`);
    };
    recorder = rec;
    recStart = performance.now();
    rec.start(1000);
    recTimer = setInterval(() => {
      if (performance.now() - recStart > MAX_RECORD_MS) {
        toast('Opname gestopt na 20 minuten. Bewaar hem en start een nieuwe.', 6000);
        stopRecording();
      }
    }, 1000);
    syncUI();
  }

  function stopRecording() {
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }

  // --------------------------------------------------------------- resultaat
  function stamp() {
    const d = new Date(), p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
  }

  function showResult(blob, kind, info) {
    closeResult();
    const ext = kind === 'photo' ? 'jpg' : (blob.type.includes('mp4') ? 'mp4' : 'webm');
    const name = `anoniem_${stamp()}.${ext}`;
    const url = URL.createObjectURL(blob);
    const file = new File([blob], name, { type: blob.type });
    result = { blob, file, url, kind, name };

    const media = $('result-media');
    media.textContent = '';
    if (kind === 'photo') {
      const img = new Image();
      img.src = url;
      img.alt = 'Gemaakte foto';
      media.append(img);
    } else {
      const v = document.createElement('video');
      v.src = url;
      v.controls = true;
      v.playsInline = true;
      media.append(v);
    }
    $('result-info').textContent = `${info} · ${(blob.size / 1048576).toFixed(1)} MB`;

    const canShare = native || !!(navigator.canShare && navigator.canShare({ files: [file] }));
    $('share-btn').hidden = !canShare;
    const saveBtn = $('save-btn');
    if (native) {
      saveBtn.textContent = 'Bewaren';
      $('save-hint').textContent = `Komt in je galerij, map "FA Camera".`;
    } else if (isIOS && canShare) {
      saveBtn.textContent = 'Bewaar in Foto\'s';
      $('save-hint').textContent = `Kies in het menu "${kind === 'photo' ? 'Bewaar afbeelding' : 'Bewaar video'}".`;
    } else {
      saveBtn.textContent = 'Bewaren';
      $('save-hint').textContent = ext === 'webm'
        ? 'Wordt bewaard in Downloads. Deze browser maakt WebM-video\'s; de meeste apps spelen die af.'
        : 'Wordt bewaard in Downloads.';
    }
    $('discard-btn').textContent = 'Weggooien';
    $('result').hidden = false;
  }

  function closeResult() {
    if (result) URL.revokeObjectURL(result.url);
    result = null;
    $('result-media').textContent = '';
    $('result').hidden = true;
  }

  /** Android-app: in stukjes naar de galerij schrijven (grote video's passen niet in één keer). */
  async function saveNative(r) {
    if (r.uri) return r.uri;
    const CHUNK = 768 * 1024; // deelbaar door 3: base64 per stuk blijft los te decoderen
    const { id } = await cap.nativePromise('MediaSaver', 'begin', { name: r.name, mime: r.blob.type || 'application/octet-stream' });
    try {
      for (let pos = 0; pos < r.blob.size; pos += CHUNK) {
        const data = await new Promise((res, rej) => {
          const fr = new FileReader();
          fr.onload = () => res(String(fr.result).split(',')[1] || '');
          fr.onerror = () => rej(fr.error);
          fr.readAsDataURL(r.blob.slice(pos, pos + CHUNK));
        });
        await cap.nativePromise('MediaSaver', 'append', { id, data });
      }
      const { uri } = await cap.nativePromise('MediaSaver', 'finish', { id });
      r.uri = uri;
      return uri;
    } catch (e) {
      cap.nativePromise('MediaSaver', 'cancel', { id }).catch(() => {});
      throw e;
    }
  }

  let saving = false;
  async function nativeAction(andShare) {
    if (!result || saving) return;
    saving = true;
    const r = result;
    $('save-btn').disabled = $('share-btn').disabled = true;
    try {
      const uri = await saveNative(r);
      if (andShare) {
        await cap.nativePromise('MediaSaver', 'share', { uri, mime: r.blob.type });
        toast('Ook bewaard in je galerij (map FA Camera).');
      } else {
        toast('Bewaard in je galerij (map FA Camera).');
      }
      closeResult();
    } catch (e) {
      toast(`Bewaren mislukt (${(e && e.message) || e}).`, 6000);
    } finally {
      saving = false;
      $('save-btn').disabled = $('share-btn').disabled = false;
    }
  }

  async function share() {
    if (!result) return;
    if (native) { nativeAction(true); return; }
    try {
      await navigator.share({ files: [result.file] });
      closeResult();
    } catch (e) {
      if (e.name !== 'AbortError') toast(`Delen lukte niet (${e.message}).`);
    }
  }

  function download() {
    if (!result) return;
    const a = document.createElement('a');
    a.href = result.url;
    a.download = result.name;
    document.body.append(a);
    a.click();
    a.remove();
    const r = result;
    result = null; // URL nog even laten bestaan voor de download
    setTimeout(() => URL.revokeObjectURL(r.url), 60000);
    $('result-media').textContent = '';
    $('result').hidden = true;
    toast('Bewaard in Downloads.');
  }

  let discardArmed = false;
  function discard() {
    if (!discardArmed) {
      discardArmed = true;
      $('discard-btn').textContent = 'Zeker weten?';
      setTimeout(() => { discardArmed = false; if (result) $('discard-btn').textContent = 'Weggooien'; }, 3000);
      return;
    }
    discardArmed = false;
    closeResult();
  }

  // ------------------------------------------------------------------ overlay
  async function trimTransparent(bitmap) {
    const w = bitmap.width, h = bitmap.height;
    const scale = Math.min(1, 512 / Math.max(w, h));
    const sw = Math.max(1, Math.round(w * scale)), sh = Math.max(1, Math.round(h * scale));
    const c = document.createElement('canvas');
    c.width = sw; c.height = sh;
    const cx = c.getContext('2d', { willReadFrequently: true });
    cx.drawImage(bitmap, 0, 0, sw, sh);
    const a = cx.getImageData(0, 0, sw, sh).data;
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
      overlay = await trimTransparent(await createImageBitmap(blob));
      const url = URL.createObjectURL(blob);
      const img = $('logo-preview');
      if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
      img.dataset.url = url;
      img.src = url;
      return true;
    } catch (e) {
      console.warn('[FA Camera] overlay', e);
      return false;
    }
  }

  async function loadOverlay() {
    try {
      const stored = localStorage.getItem(LOGO_STORE);
      if (stored) {
        const blob = await (await fetch(stored)).blob();
        if (await setOverlay(blob)) return;
      }
    } catch (_) { /* geen eigen logo */ }
    try {
      await setOverlay(await (await fetch('../assets/overlay.png')).blob());
    } catch (_) { overlay = null; }
  }

  async function chooseLogo(file) {
    if (!file) return;
    if (!(await setOverlay(file))) { toast('Dit bestand is geen bruikbare afbeelding.'); return; }
    try {
      if (file.size < 1.5 * 1048576) {
        const dataUrl = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(r.result);
          r.onerror = rej;
          r.readAsDataURL(file);
        });
        localStorage.setItem(LOGO_STORE, dataUrl);
      } else {
        localStorage.removeItem(LOGO_STORE);
        toast('Logo is groot: het wordt niet onthouden voor de volgende keer.');
      }
    } catch (_) { /* geen opslag */ }
    S.mode = 'overlay';
    save();
    syncUI();
  }

  // ---------------------------------------------------------------------- UI
  function syncUI() {
    document.querySelectorAll('.chips [data-mode]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.mode === S.mode)));
    document.querySelectorAll('.capture-kind [data-kind]').forEach((b) => {
      b.setAttribute('aria-checked', String(b.dataset.kind === S.kind));
      b.disabled = !!recorder;
    });
    document.querySelectorAll('[data-detect]').forEach((b) => b.setAttribute('aria-checked', String(Number(b.dataset.detect) === S.detectSize)));
    const sh = $('shutter');
    sh.classList.toggle('video', S.kind === 'video');
    sh.classList.toggle('recording', !!recorder);
    sh.setAttribute('aria-label', S.kind === 'photo' ? 'Foto maken' : recorder ? 'Opname stoppen' : 'Opname starten');
    $('flip-btn').disabled = !!recorder;
    $('settings-btn').disabled = !!recorder;
    $('audio-btn').setAttribute('aria-pressed', String(S.audio));
    $('protect-btn').setAttribute('aria-pressed', String(S.protect));
    $('protect').checked = S.protect;
    $('audio-btn').disabled = !!recorder;
    $('mirror').checked = S.mirror;
    $('scale').value = S.scale;
    $('scale-out').textContent = `${Number(S.scale).toFixed(1)}×`;
    $('confidence').value = S.confidence;
    $('conf-out').textContent = Number(S.confidence).toFixed(2);
    $('resolution').value = String(S.resolution);
    $('colorfix').value = colorMode();
    $('colorfix-cam').textContent = S.facing === 'user' ? 'selfiecamera' : 'achtercamera';
  }

  function bind() {
    document.querySelectorAll('.chips [data-mode]').forEach((b) => b.addEventListener('click', () => {
      S.mode = b.dataset.mode; save(); syncUI();
    }));
    document.querySelectorAll('.capture-kind [data-kind]').forEach((b) => b.addEventListener('click', () => {
      if (recorder) return;
      S.kind = b.dataset.kind; save(); syncUI();
    }));
    document.querySelectorAll('[data-detect]').forEach((b) => b.addEventListener('click', () => {
      S.detectSize = Number(b.dataset.detect); save(); syncUI();
    }));
    $('shutter').addEventListener('click', () => {
      if (!running) return;
      if (S.kind === 'photo') takePhoto();
      else if (recorder) stopRecording();
      else if (!healthy) toast('Even wachten tot de gezichtsherkenning klaar is.');
      else startRecording();
    });
    $('flip-btn').addEventListener('click', async () => {
      if (recorder) return;
      S.facing = S.facing === 'user' ? 'environment' : 'user';
      save();
      syncUI(); // kleurcorrectie van de andere camera tonen en gebruiken
      try { await startCamera(); } catch (e) { toast(cameraError(e), 6000); }
    });
    const setProtect = (on) => {
      S.protect = on; save(); syncUI();
      toast(on ? 'Beschermende blur aan: zonder gevonden gezicht wordt alles vervaagd.'
        : 'Beschermende blur uit: alleen gevonden gezichten worden afgedekt.', 2600);
    };
    $('protect-btn').addEventListener('click', () => setProtect(!S.protect));
    $('protect').addEventListener('change', (e) => setProtect(e.target.checked));
    $('audio-btn').addEventListener('click', () => {
      if (recorder) return;
      S.audio = !S.audio; save(); syncUI();
      toast(S.audio ? 'Video\'s worden met geluid opgenomen.' : 'Video\'s worden zonder geluid opgenomen.', 2200);
    });
    $('settings-btn').addEventListener('click', () => { $('settings').hidden = false; });
    $('settings').addEventListener('click', (e) => {
      if (e.target === e.currentTarget || e.target.closest('[data-close]')) $('settings').hidden = true;
    });
    $('mirror').addEventListener('change', (e) => { S.mirror = e.target.checked; save(); });
    $('scale').addEventListener('input', (e) => { S.scale = Number(e.target.value); save(); syncUI(); });
    $('confidence').addEventListener('input', (e) => { S.confidence = Number(e.target.value); save(); syncUI(); });
    $('resolution').addEventListener('change', async (e) => {
      S.resolution = Number(e.target.value); save();
      if (running && !recorder) { try { await startCamera(); } catch (err) { toast(cameraError(err), 6000); } }
    });
    $('colorfix').addEventListener('change', (e) => {
      S.colorFixCam[S.facing] = e.target.value; save();
      if (e.target.value === 'auto') { swapAuto = null; colorChecks = 0; }
    });
    $('logo-file').addEventListener('change', (e) => { chooseLogo(e.target.files[0]); e.target.value = ''; });
    $('logo-reset').addEventListener('click', async () => {
      try { localStorage.removeItem(LOGO_STORE); } catch (_) { /* geen opslag */ }
      await loadOverlay();
    });
    $('save-btn').addEventListener('click', () => {
      if (native) nativeAction(false);
      else if (isIOS && !$('share-btn').hidden) share(); else download();
    });
    $('share-btn').addEventListener('click', share);
    $('discard-btn').addEventListener('click', discard);

    $('start-btn').addEventListener('click', async () => {
      const btn = $('start-btn');
      btn.disabled = true;
      $('start-error').hidden = true;
      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('nomedia');
        await startCamera();
        $('intro').hidden = true;
      } catch (e) {
        $('start-error').textContent = cameraError(e);
        $('start-error').hidden = false;
      } finally {
        btn.disabled = false;
      }
    });

    document.addEventListener('visibilitychange', async () => {
      if (document.visibilityState === 'hidden') {
        stopRecording(); // telefoon stopt de camera toch; opname netjes afronden
        return;
      }
      keepAwake();
      if (running && video.paused) video.play().catch(() => {});
      if (running && (!stream || stream.getVideoTracks().every((t) => t.readyState === 'ended'))) {
        try { await startCamera(); } catch (e) { toast(cameraError(e), 6000); }
      }
    });

    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      installPrompt = e;
      const hint = $('install-hint');
      hint.textContent = '';
      const b = document.createElement('button');
      b.className = 'btn';
      b.textContent = 'Als app installeren';
      b.addEventListener('click', async () => {
        installPrompt.prompt();
        await installPrompt.userChoice.catch(() => {});
        installPrompt = null;
        hint.hidden = true;
      });
      hint.append(b);
      hint.hidden = false;
    });

    setInterval(refreshStatus, 250);
  }

  function introHints() {
    if (native) $('pwa-tip').hidden = true;
    if (standalone || native) return;
    const hint = $('install-hint');
    if (isIOS) {
      hint.textContent = 'Tip: tik in Safari op Delen en kies "Zet op beginscherm". Dan opent hij als app en werkt hij ook zonder internet.';
      hint.hidden = false;
    }
  }

  // ------------------------------------------------------------------- start
  bind();
  syncUI();
  introHints();
  startWorker();
  loadOverlay();
  // Android-terugknop: eerst panelen sluiten of de opname stoppen
  window.__faBack = () => {
    if (!$('settings').hidden) { $('settings').hidden = true; return true; }
    if (!$('result').hidden) { toast('Kies eerst Bewaren of Weggooien.'); return true; }
    if (recorder) { stopRecording(); return true; }
    return false;
  };
  if (!native && 'serviceWorker' in navigator && location.protocol === 'https:') {
    navigator.serviceWorker.register('sw.js').catch(() => { /* offline werkt dan niet, de app wel */ });
  }
  // Test- en ontwikkelhaak (geen invloed op gebruik)
  window.__faCamera = { get swapAuto() { return swapAuto; }, get healthy() { return healthy; }, get faces() { return lastFaceCount; }, get fps() { return fps; }, get detectMs() { return detectMs; } };
})();
