/* global FA_DEFAULTS */
(async () => {
  const $ = (id) => document.getElementById(id);
  const FORMAT = {
    scale: (v) => `${(+v).toFixed(1)}×`,
    confidence: (v) => (+v).toFixed(2),
    minSize: (v) => `${v}px`,
    persistence: (v) => `${v}`,
  };
  const MAX_OVERLAY_BYTES = 4 * 1024 * 1024;

  const stored = await chrome.storage.local.get([...Object.keys(FA_DEFAULTS), 'overlayData']);
  const s = { ...FA_DEFAULTS, ...stored };

  const save = (patch) => chrome.storage.local.set(patch);

  function renderState() {
    const on = $('enabled').checked;
    $('state').textContent = on
      ? 'Actief: gezichten worden afgedekt zodra een website je camera gebruikt.'
      : 'Uit: websites krijgen je gewone camerabeeld.';
    $('state').classList.toggle('off', !on);
    const mode = document.querySelector('input[name=mode]:checked')?.value;
    $('overlayRow').classList.toggle('hidden', mode !== 'overlay');
    $('mirrorRow').classList.toggle('hidden', mode !== 'overlay');
  }

  // Aan/uit
  $('enabled').checked = s.enabled;
  $('enabled').addEventListener('change', (e) => { save({ enabled: e.target.checked }); renderState(); });

  // Modus
  for (const r of document.querySelectorAll('input[name=mode]')) {
    r.checked = r.value === s.mode;
    r.addEventListener('change', () => { save({ mode: r.value }); renderState(); });
  }

  // Detectiesnelheid
  const SPEED_HINT = {
    320: 'Snelst. Goed voor één persoon dicht bij de camera.',
    480: 'Aanbevolen balans tussen snelheid en kleine gezichten.',
    640: 'Vindt kleinere gezichten verder weg, maar volgt beweging trager.',
  };
  for (const r of document.querySelectorAll('input[name=detectSize]')) {
    r.checked = Number(r.value) === s.detectSize;
    r.addEventListener('change', () => { save({ detectSize: Number(r.value) }); $('speedHint').textContent = SPEED_HINT[r.value]; });
  }
  $('speedHint').textContent = SPEED_HINT[s.detectSize] || '';

  // Schuifregelaars
  for (const key of Object.keys(FORMAT)) {
    const input = $(key), out = $(key + 'Out');
    input.value = s[key];
    out.textContent = FORMAT[key](s[key]);
    input.addEventListener('input', () => {
      out.textContent = FORMAT[key](input.value);
      save({ [key]: Number(input.value) });
    });
  }

  // Vinkjes
  for (const key of ['smartPersistence', 'failSafeBlur', 'mirrorOverlay', 'protectiveBlur']) {
    $(key).checked = s[key];
    $(key).addEventListener('change', (e) => save({ [key]: e.target.checked }));
  }

  // Overlay
  const showOverlay = (data) => { $('overlayPreview').src = data || 'assets/overlay.png'; };
  showOverlay(s.overlayData);
  $('pickOverlay').addEventListener('click', () => $('overlayFile').click());
  $('overlayFile').addEventListener('change', () => {
    const file = $('overlayFile').files[0];
    if (!file) return;
    if (file.size > MAX_OVERLAY_BYTES) {
      $('state').textContent = 'Afbeelding is te groot (max. 4 MB).';
      $('state').classList.add('off');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => { save({ overlayData: reader.result }); showOverlay(reader.result); };
    reader.readAsDataURL(file);
  });
  $('resetOverlay').addEventListener('click', () => {
    chrome.storage.local.remove('overlayData');
    showOverlay(null);
  });

  renderState();
})();
