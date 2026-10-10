/*
 * Draait in de geïsoleerde wereld van de extensie. Leest de instellingen en de
 * overlay uit chrome.storage en geeft ze via een eigen MessageChannel door aan
 * inject.js (de paginawereld), ook live als je ze in de popup wijzigt.
 */
(() => {
  /* global FA_DEFAULTS */
  // Elke init krijgt een eigen kanaal: een bericht dat verstuurd wordt voordat
  // inject.js luistert gaat verloren, inclusief de meegestuurde port.
  const ports = [];

  async function loadSettings() {
    const stored = await chrome.storage.local.get(Object.keys(FA_DEFAULTS));
    return { ...FA_DEFAULTS, ...stored };
  }

  async function loadOverlay() {
    const { overlayData } = await chrome.storage.local.get('overlayData');
    const url = overlayData || chrome.runtime.getURL('assets/overlay.png');
    try {
      return await (await fetch(url)).blob();
    } catch (e) {
      console.warn('[Face Anonymizer] overlay laden mislukt', e);
      return null;
    }
  }

  async function sendInit() {
    const [settings, overlay] = await Promise.all([loadSettings(), loadOverlay()]);
    const channel = new MessageChannel();
    ports.push(channel.port1);
    window.postMessage({
      __faInit: true,
      detectorUrl: chrome.runtime.getURL('detector.html'),
      settings,
      overlay,
    }, '*', [channel.port2]);
  }

  // inject.js meldt zich als het later laadt dan dit script
  window.addEventListener('message', (e) => {
    if (e.source === window && e.data && e.data.__faHello === true) sendInit();
  });
  sendInit();

  chrome.storage.onChanged.addListener(async (changes, area) => {
    if (area !== 'local') return;
    // inject.js gebruikt de eerste port die aankomt; we sturen naar alle
    if ('overlayData' in changes) {
      const overlay = await loadOverlay();
      ports.forEach((p) => p.postMessage({ type: 'overlay', overlay }));
    }
    if (Object.keys(changes).some(k => k in FA_DEFAULTS)) {
      const settings = await loadSettings();
      ports.forEach((p) => p.postMessage({ type: 'settings', settings }));
    }
  });
})();
