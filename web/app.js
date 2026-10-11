/* Foto Anonymizer – webversie. Alle verwerking gebeurt lokaal in web workers. */
/* global makeZip */
(() => {
  const $ = (id) => document.getElementById(id);
  const ACCEPT = /\.(jpe?g|png|webp|bmp|gif|heic|heif)$/i;
  const DEFAULT_OVERLAY = 'assets/overlay.png';
  const STORE_KEY = 'foto-anonymizer-settings';

  // ------------------------------------------------------------ instellingen
  const settings = { mode: 'overlay', scale: 1.6, mirror: false, accuracy: 'normal', confidence: 0.5 };
  try { Object.assign(settings, JSON.parse(localStorage.getItem(STORE_KEY) || '{}')); } catch (_) { /* geen opslag */ }
  const persist = () => { try { localStorage.setItem(STORE_KEY, JSON.stringify(settings)); } catch (_) { /* geen opslag */ } };
  const nl = (v, d) => Number(v).toFixed(d).replace('.', ',');

  // --------------------------------------------------------------- workers
  const POOL = Math.max(1, Math.min(4, Math.floor((navigator.hardwareConcurrency || 2) / 2)));
  const workers = [];
  const queue = [];
  let overlayBlob = null;
  let overlayLoaded = false; // eerste foto pas verwerken als het logo er is

  function startWorkers() {
    for (let i = 0; i < POOL; i++) {
      const w = new Worker('worker.js');
      const slot = { w, ready: false, job: null };
      w.onmessage = (e) => onWorkerMessage(slot, e.data);
      w.onerror = (e) => { console.error(e); setBar('De verwerking kon niet starten. Herlaad de pagina.'); };
      w.postMessage({ type: 'init' });
      workers.push(slot);
    }
  }

  function sendOverlay() {
    for (const s of workers) s.w.postMessage({ type: 'overlay', blob: overlayBlob });
  }

  function pump() {
    if (!overlayLoaded) return;
    for (const s of workers) {
      if (!s.ready || s.job || !queue.length) continue;
      const job = queue.shift();
      const item = items.get(job.id);
      if (!item) { pump(); return; }
      s.job = job;
      item.state = 'busy';
      draw(item);
      s.w.postMessage({
        type: job.kind, id: item.id, file: item.file, faces: item.faces,
        settings: { ...settings }, outType: item.outType,
      });
    }
    updateBar();
  }

  function onWorkerMessage(slot, m) {
    if (m.type === 'ready') { slot.ready = true; pump(); return; }
    const job = slot.job;
    slot.job = null;
    const item = items.get(m.id);
    if (item && job && job.version === item.version) {
      if (m.type === 'done') {
        item.faces = m.faces;
        item.width = m.width;
        item.height = m.height;
        item.blob = m.blob;
        if (item.thumbUrl) URL.revokeObjectURL(item.thumbUrl);
        item.thumbUrl = URL.createObjectURL(m.thumb);
        item.state = 'done';
        item.error = null;
      } else {
        item.state = 'error';
        item.error = m.message;
      }
      draw(item);
      if (reviewId === item.id) showReview();
    }
    pump();
  }

  // --------------------------------------------------------------- foto's
  const items = new Map();
  let seq = 0;
  const usedNames = new Set();

  function outName(rel) {
    let name = rel.replace(/\.(heic|heif|bmp|gif)$/i, '.jpg');
    if (usedNames.has(name)) {
      const dot = name.lastIndexOf('.');
      let n = 2;
      while (usedNames.has(`${name.slice(0, dot)} (${n})${name.slice(dot)}`)) n++;
      name = `${name.slice(0, dot)} (${n})${name.slice(dot)}`;
    }
    usedNames.add(name);
    return name;
  }

  function outType(name) {
    if (/\.png$/i.test(name)) return 'image/png';
    if (/\.webp$/i.test(name)) return 'image/webp';
    return 'image/jpeg';
  }

  function addFiles(list) {
    const files = [...list].filter((f) => ACCEPT.test(f.name) && !f.name.startsWith('.'));
    if (!files.length) { setBar('Geen foto\'s gevonden in wat je koos.'); $('bar').hidden = false; return; }
    files.sort((a, b) => (a.relPath || a.webkitRelativePath || a.name).localeCompare(b.relPath || b.webkitRelativePath || b.name, 'nl'));
    for (const file of files) {
      const rel = file.relPath || file.webkitRelativePath || file.name;
      const name = outName(rel);
      const item = { id: ++seq, file, rel, name, outType: outType(name), state: 'queued', faces: [], version: 0, checked: false };
      items.set(item.id, item);
      $('sheet').append(makePrint(item));
      enqueue(item, 'process');
    }
    $('checkHint').hidden = false;
    $('redetect').disabled = false;
    $('bar').hidden = false;
  }

  function enqueue(item, kind) {
    item.version++;
    // Een nieuwere opdracht voor dezelfde foto vervangt een wachtende
    const i = queue.findIndex((j) => j.id === item.id);
    if (i >= 0) queue.splice(i, 1);
    queue.push({ id: item.id, kind, version: item.version });
    item.state = item.state === 'done' ? 'rerender' : item.state;
    pump();
  }

  // ------------------------------------------------------------- contactvel
  function makePrint(item) {
    const li = document.createElement('li');
    li.innerHTML = '<button type="button" class="print busy"><span class="frame"></span>' +
      '<span class="name"></span><span class="state"></span></button>';
    li.querySelector('.name').textContent = item.rel;
    li.querySelector('.name').title = item.rel;
    li.querySelector('button').addEventListener('click', () => openReview(item.id));
    item.el = li;
    draw(item);
    return li;
  }

  function draw(item) {
    if (!item.el) return;
    const btn = item.el.querySelector('button');
    const frame = btn.querySelector('.frame');
    const state = btn.querySelector('.state');
    btn.className = 'print';
    btn.disabled = item.state !== 'done';
    if (item.thumbUrl) {
      let img = frame.querySelector('img');
      if (!img) { img = document.createElement('img'); img.alt = ''; frame.replaceChildren(img); }
      if (img.src !== item.thumbUrl) img.src = item.thumbUrl;
    }
    if (item.state === 'queued') { btn.classList.add('busy'); state.textContent = 'Wacht…'; }
    else if (item.state === 'busy' || item.state === 'rerender') { btn.classList.add('busy'); state.textContent = 'Bezig…'; }
    else if (item.state === 'error') { btn.classList.add('error'); state.textContent = item.error; btn.disabled = true; }
    else if (!item.faces.length && !item.checked) { btn.classList.add('warn'); state.textContent = 'Geen gezicht gevonden. Controleer!'; }
    else {
      btn.classList.add(item.checked ? 'checked' : 'ok');
      const n = item.faces.length;
      state.textContent = `${n} ${n === 1 ? 'gezicht' : 'gezichten'} afgedekt${item.checked ? ', nagelopen' : ''}`;
    }
    btn.setAttribute('aria-label', `${item.rel}: ${state.textContent}`);
  }

  function counts() {
    let done = 0, faces = 0, warn = 0, err = 0;
    for (const it of items.values()) {
      if (it.state === 'done') { done++; faces += it.faces.length; if (!it.faces.length && !it.checked) warn++; }
      if (it.state === 'error') err++;
    }
    return { total: items.size, done, faces, warn, err };
  }

  function setBar(text) { $('barText').textContent = text; }

  function updateBar() {
    const c = counts();
    const finished = c.done + c.err;
    $('progressFill').style.width = c.total ? `${(finished / c.total) * 100}%` : '0';
    const busy = finished < c.total || workers.some((s) => s.job) || queue.length;
    if (!c.total) {
      $('summary').textContent = 'Nog geen foto\'s.';
    } else {
      let s = `${c.done} van ${c.total} foto's klaar, ${c.faces} ${c.faces === 1 ? 'gezicht' : 'gezichten'} afgedekt.`;
      if (c.warn) s += ` ${c.warn} zonder gezicht: loop die na.`;
      if (c.err) s += ` ${c.err} niet gelukt.`;
      $('summary').textContent = s;
    }
    if (busy) setBar(`Bezig met ${finished + 1} van ${c.total}…`);
    else if (c.total) setBar(c.warn ? `Klaar. ${c.warn} foto's zonder gezicht, controleer die voor je downloadt.` : 'Klaar. Controleer de foto\'s en download ze.');
    $('downloadAll').disabled = busy || !c.done;
  }

  // ----------------------------------------------------------- nalopen
  let reviewId = null;
  let order = [];

  function openReview(id) {
    order = [...items.values()].filter((it) => it.state === 'done').map((it) => it.id);
    reviewId = id;
    if (!$('review').open) $('review').showModal();
    showReview();
  }

  function showReview() {
    const item = items.get(reviewId);
    if (!item) return;
    const pos = order.indexOf(item.id);
    $('reviewTitle').textContent = `${pos + 1} / ${order.length}  ${item.rel}`;
    $('prev').disabled = pos <= 0;
    $('next').disabled = pos >= order.length - 1;
    const img = $('reviewImg');
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    const src = $('showOriginal').checked ? item.file : item.blob;
    const url = URL.createObjectURL(src);
    img.dataset.url = url;
    img.onload = layoutBoxes;
    img.src = url;
    if (!item.checked) { item.checked = true; draw(item); updateBar(); }
  }

  function maskBox(f) {
    const size = Math.max(f.w, f.h) * settings.scale;
    return [f.x + f.w / 2 - size / 2, f.y + f.h / 2 - size / 2, size];
  }

  function layoutBoxes() {
    const item = items.get(reviewId);
    const img = $('reviewImg');
    const boxes = $('boxes');
    if (!item || !img.naturalWidth) return;
    const s = img.clientWidth / item.width;
    boxes.style.left = `${img.offsetLeft}px`;
    boxes.style.top = `${img.offsetTop}px`;
    boxes.style.width = `${img.clientWidth}px`;
    boxes.style.height = `${img.clientHeight}px`;
    boxes.replaceChildren();
    item.faces.forEach((f, i) => {
      const [x, y, size] = maskBox(f);
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'box' + (f.manual ? ' manual' : '');
      b.style.cssText = `left:${x * s}px;top:${y * s}px;width:${size * s}px;height:${size * s}px`;
      b.title = 'Masker weghalen';
      b.setAttribute('aria-label', `Masker ${i + 1} weghalen`);
      b.addEventListener('click', (e) => { e.stopPropagation(); removeFace(item, f); });
      boxes.append(b);
    });
    boxes.dataset.scale = s;
  }

  function removeFace(item, face) {
    item.faces = item.faces.filter((f) => f !== face);
    rerender(item);
  }

  function rerender(item) {
    layoutBoxes();
    enqueue(item, 'render');
  }

  // Slepen om een masker toe te voegen
  let drag = null;
  $('boxes').addEventListener('pointerdown', (e) => {
    if (e.target !== $('boxes')) return;
    const r = $('boxes').getBoundingClientRect();
    drag = { x: e.clientX - r.left, y: e.clientY - r.top, el: document.createElement('div') };
    drag.el.className = 'box draft';
    $('boxes').append(drag.el);
    $('boxes').setPointerCapture(e.pointerId);
  });
  $('boxes').addEventListener('pointermove', (e) => {
    if (!drag) return;
    const r = $('boxes').getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    drag.el.style.cssText = `left:${Math.min(x, drag.x)}px;top:${Math.min(y, drag.y)}px;` +
      `width:${Math.abs(x - drag.x)}px;height:${Math.abs(y - drag.y)}px`;
    drag.x2 = x; drag.y2 = y;
  });
  $('boxes').addEventListener('pointerup', () => {
    if (!drag) return;
    const d = drag;
    drag = null;
    d.el.remove();
    if (d.x2 == null || (Math.abs(d.x2 - d.x) < 6 && Math.abs(d.y2 - d.y) < 6)) return;
    const item = items.get(reviewId);
    const s = Number($('boxes').dataset.scale);
    const side = Math.max(Math.abs(d.x2 - d.x), Math.abs(d.y2 - d.y)) / s;
    const cx = (d.x + d.x2) / 2 / s, cy = (d.y + d.y2) / 2 / s;
    const core = side / settings.scale; // het getekende vak wordt het masker
    item.faces = [...item.faces, { x: cx - core / 2, y: cy - core / 2, w: core, h: core, score: 1, manual: true }];
    rerender(item);
  });

  function step(dir) {
    const pos = order.indexOf(reviewId) + dir;
    if (pos >= 0 && pos < order.length) { reviewId = order[pos]; showReview(); }
  }
  $('prev').addEventListener('click', () => step(-1));
  $('next').addEventListener('click', () => step(1));
  $('closeReview').addEventListener('click', () => $('review').close());
  $('showOriginal').addEventListener('change', showReview);
  $('review').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') step(-1);
    if (e.key === 'ArrowRight') step(1);
  });
  $('review').addEventListener('close', () => { reviewId = null; });
  window.addEventListener('resize', () => { if (reviewId) layoutBoxes(); });
  $('downloadOne').addEventListener('click', () => {
    const item = items.get(reviewId);
    if (item && item.blob) save(item.blob, item.name.split('/').pop());
  });

  // ------------------------------------------------------------- download
  function save(blob, name) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60_000);
  }

  $('downloadAll').addEventListener('click', async () => {
    const c = counts();
    if (c.warn && !confirm(`${c.warn} foto's zijn nog niet nagelopen en hebben geen gezicht gevonden. Toch downloaden?`)) return;
    const done = [...items.values()].filter((it) => it.state === 'done');
    $('downloadAll').disabled = true;
    setBar('ZIP maken…');
    const zip = await makeZip(done.map((it) => ({ name: `anoniem/${it.name}`, blob: it.blob })));
    save(zip, `anoniem-${new Date().toISOString().slice(0, 10)}.zip`);
    updateBar();
  });

  $('clear').addEventListener('click', () => {
    if (!confirm('Alle foto\'s uit deze lijst halen? Je originelen blijven gewoon staan.')) return;
    queue.length = 0;
    for (const it of items.values()) if (it.thumbUrl) URL.revokeObjectURL(it.thumbUrl);
    items.clear();
    usedNames.clear();
    $('sheet').replaceChildren();
    $('checkHint').hidden = true;
    $('redetect').disabled = true;
    $('bar').hidden = true;
    updateBar();
  });

  // ------------------------------------------------------------ invoer
  const drop = $('drop');
  $('files').addEventListener('change', (e) => { addFiles(e.target.files); e.target.value = ''; });
  $('folder').addEventListener('change', (e) => { addFiles(e.target.files); e.target.value = ''; });
  $('pickFolder').addEventListener('click', (e) => { e.preventDefault(); $('folder').click(); });
  drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('files').click(); } });
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', async (e) => {
    e.preventDefault();
    drop.classList.remove('over');
    const entries = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    if (!entries.length) { addFiles(e.dataTransfer.files); return; }
    addFiles(await readEntries(entries));
  });
  // Ook mappen slepen, inclusief submappen
  async function readEntries(entries, prefix = '') {
    const out = [];
    for (const entry of entries) {
      if (entry.isFile) {
        const f = await new Promise((res, rej) => entry.file(res, rej));
        f.relPath = prefix + f.name;
        out.push(f);
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        let batch;
        const children = [];
        do {
          batch = await new Promise((res, rej) => reader.readEntries(res, rej));
          children.push(...batch);
        } while (batch.length);
        out.push(...await readEntries(children, `${prefix}${entry.name}/`));
      }
    }
    return out;
  }
  // Ook plakken (Ctrl+V) van een foto
  document.addEventListener('paste', (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) addFiles(files.map((f, i) => new File([f], f.name || `geplakt-${i + 1}.png`, { type: f.type })));
  });

  // ---------------------------------------------------- instellingen (UI)
  function bindRadios(name, key, onChange) {
    for (const r of document.querySelectorAll(`input[name=${name}]`)) {
      r.checked = r.value === settings[key];
      r.addEventListener('change', () => { settings[key] = r.value; persist(); onChange(); });
    }
  }
  function maskChanged() {
    $('overlayRow').hidden = settings.mode !== 'overlay';
    // Bestaande resultaten opnieuw tekenen met dezelfde gezichten (zonder opnieuw te zoeken)
    for (const it of items.values()) if (it.state === 'done' || it.state === 'rerender') enqueue(it, 'render');
    if (reviewId) layoutBoxes();
  }
  bindRadios('mode', 'mode', maskChanged);
  bindRadios('accuracy', 'accuracy', () => {});
  $('overlayRow').hidden = settings.mode !== 'overlay';

  $('scale').value = settings.scale;
  $('scaleOut').textContent = `${nl(settings.scale, 1)}×`;
  let scaleTimer;
  $('scale').addEventListener('input', () => {
    settings.scale = Number($('scale').value);
    $('scaleOut').textContent = `${nl(settings.scale, 1)}×`;
    persist();
    clearTimeout(scaleTimer);
    scaleTimer = setTimeout(maskChanged, 250);
  });
  $('confidence').value = settings.confidence;
  $('confidenceOut').textContent = nl(settings.confidence, 2);
  $('confidence').addEventListener('input', () => {
    settings.confidence = Number($('confidence').value);
    $('confidenceOut').textContent = nl(settings.confidence, 2);
    persist();
  });
  $('mirror').checked = settings.mirror;
  $('mirror').addEventListener('change', () => { settings.mirror = $('mirror').checked; persist(); maskChanged(); });

  $('redetect').addEventListener('click', () => {
    const edited = [...items.values()].some((it) => it.faces.some((f) => f.manual));
    if (edited && !confirm('Opnieuw doorzoeken haalt je handmatige aanpassingen weg. Doorgaan?')) return;
    for (const it of items.values()) { it.checked = false; it.state = 'queued'; enqueue(it, 'process'); draw(it); }
  });

  // Overlay
  $('pickOverlay').addEventListener('click', () => $('overlayFile').click());
  $('overlayFile').addEventListener('change', async () => {
    const f = $('overlayFile').files[0];
    if (!f) return;
    overlayBlob = f;
    $('overlayPreview').src = URL.createObjectURL(f);
    sendOverlay();
    maskChanged();
  });
  $('resetOverlay').addEventListener('click', async () => {
    overlayBlob = await (await fetch(DEFAULT_OVERLAY)).blob();
    $('overlayPreview').src = DEFAULT_OVERLAY;
    sendOverlay();
    maskChanged();
  });

  // ------------------------------------------------------------- start
  startWorkers();
  fetch(DEFAULT_OVERLAY).then((r) => (r.ok ? r.blob() : null)).then((b) => { if (!overlayBlob && b) overlayBlob = b; })
    .catch(() => { /* zonder overlay valt de modus terug op pixels */ })
    .finally(() => { sendOverlay(); overlayLoaded = true; pump(); });

  // Voor geautomatiseerde tests
  window.__fotoAnonymizer = { items, settings, counts, queue, workers };
})();
