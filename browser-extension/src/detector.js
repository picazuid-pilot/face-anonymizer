/*
 * Draait in een verborgen extensie-iframe. Ontvangt verkleinde frames als
 * ImageBitmap, draait YuNet met ONNX Runtime Web (WASM) en stuurt de
 * gezichtsboxen terug. Alles gebeurt lokaal in de browser.
 */
/* global ort, YuNet */
(() => {
  const SIZE = YuNet.SIZE;
  const canvas = new OffscreenCanvas(SIZE, SIZE);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  let port = null;
  let session = null;

  ort.env.wasm.wasmPaths = new URL('lib/', location.href).href;
  ort.env.wasm.numThreads = 1; // geen cross-origin isolation in een iframe

  async function load() {
    try {
      session = await ort.InferenceSession.create('models/yunet.onnx', {
        executionProviders: ['wasm'],
        graphOptimizationLevel: 'all',
      });
      await run(new Uint8ClampedArray(SIZE * SIZE * 4)); // opwarmen
      port.postMessage({ type: 'ready' });
    } catch (e) {
      port.postMessage({ type: 'error', message: String(e && e.message || e) });
    }
  }

  async function run(rgba) {
    const input = new ort.Tensor('float32', YuNet.toTensor(rgba), [1, 3, SIZE, SIZE]);
    const res = await session.run({ input });
    const out = {};
    for (const k of Object.keys(res)) out[k] = res[k].data;
    return YuNet.decode(out, 0.3, 0.3); // fijnere drempel stelt de pagina zelf in
  }

  let queue = Promise.resolve();
  function onRequest(e) {
    queue = queue.then(() => handle(e.data || {}));
  }

  async function handle(m) {
    if (m.type !== 'detect' || !m.bitmap) return;
    try {
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, SIZE, SIZE);
      ctx.drawImage(m.bitmap, 0, 0);
      m.bitmap.close();
      const boxes = await run(ctx.getImageData(0, 0, SIZE, SIZE).data);
      port.postMessage({ type: 'result', id: m.id, boxes });
    } catch (err) {
      port.postMessage({ type: 'error', message: String(err && err.message || err) });
    }
  }

  window.addEventListener('message', (e) => {
    if (port || !e.data || e.data.type !== 'init' || !e.ports[0]) return;
    port = e.ports[0];
    port.onmessage = onRequest;
    load();
  });
})();
