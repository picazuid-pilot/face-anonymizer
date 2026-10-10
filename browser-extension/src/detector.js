/*
 * Draait in een verborgen extensie-iframe. Ontvangt verkleinde frames als
 * ImageBitmap, draait YuNet met ONNX Runtime Web (WASM) en stuurt de
 * gezichtsboxen terug. Alles gebeurt lokaal in de browser.
 */
/* global ort, YuNet */
(() => {
  const canvas = new OffscreenCanvas(32, 32);
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
      // Opwarmen op de gangbare formaten (16:9 bij elke snelheidsstand)
      for (const [W, H] of [[480, 288], [640, 384], [320, 192]]) {
        await run(new Uint8ClampedArray(W * H * 4), W, H);
      }
      port.postMessage({ type: 'ready' });
    } catch (e) {
      port.postMessage({ type: 'error', message: String(e && e.message || e) });
    }
  }

  async function run(rgba, W, H) {
    const input = new ort.Tensor('float32', YuNet.toTensor(rgba, W, H), [1, 3, H, W]);
    const res = await session.run({ input });
    const out = {};
    for (const k of Object.keys(res)) out[k] = res[k].data;
    return YuNet.decode(out, W, H, 0.3, 0.3); // fijnere drempel stelt de pagina zelf in
  }

  // ONNX Runtime kan niet twee berekeningen tegelijk op één sessie draaien
  let queue = Promise.resolve();
  function onRequest(e) {
    queue = queue.then(() => handle(e.data || {}));
  }

  async function handle(m) {
    if (m.type !== 'detect' || !m.bitmap) return;
    try {
      const { W, H } = m;
      if (canvas.width !== W || canvas.height !== H) {
        canvas.width = W;
        canvas.height = H;
      }
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, W, H);
      ctx.drawImage(m.bitmap, 0, 0);
      m.bitmap.close();
      const t0 = performance.now();
      const boxes = await run(ctx.getImageData(0, 0, W, H).data, W, H);
      port.postMessage({ type: 'result', id: m.id, boxes, ms: performance.now() - t0 });
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
