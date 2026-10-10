/*
 * YuNet (face_detection_yunet_2023mar) pre- en postprocessing.
 * Identiek aan OpenCV's cv::FaceDetectorYN, geverifieerd tegen de Python-tool.
 * Het meegeleverde model accepteert elke invoergrootte die een veelvoud van 32 is
 * (zoals OpenCV's setInputSize), zodat een 16:9-beeld niet tot een vierkant
 * opgevuld hoeft te worden.
 * Werkt in de browser (globalThis.YuNet) en in Node (module.exports).
 */
(function (root) {
  const STRIDES = [8, 16, 32];

  /** Invoergrootte (veelvoud van 32) voor een beeld van w x h bij een gewenste lange zijde. */
  function inputSize(w, h, longSide) {
    const s = longSide / Math.max(w, h);
    const cw = Math.max(1, Math.round(w * s)), ch = Math.max(1, Math.round(h * s));
    return { scale: s, cw, ch, W: Math.ceil(cw / 32) * 32, H: Math.ceil(ch / 32) * 32 };
  }

  /** RGBA-pixels (W x H) -> Float32Array in BGR, 0-255, NCHW. */
  function toTensor(rgba, W, H) {
    const n = W * H;
    const data = new Float32Array(3 * n);
    for (let i = 0, p = 0; i < n; i++, p += 4) {
      data[i] = rgba[p + 2];          // B
      data[n + i] = rgba[p + 1];      // G
      data[2 * n + i] = rgba[p];      // R
    }
    return data;
  }

  function iou(a, b) {
    const x1 = Math.max(a[0], b[0]), y1 = Math.max(a[1], b[1]);
    const x2 = Math.min(a[0] + a[2], b[0] + b[2]), y2 = Math.min(a[1] + a[3], b[1] + b[3]);
    if (x2 <= x1 || y2 <= y1) return 0;
    const inter = (x2 - x1) * (y2 - y1);
    const union = a[2] * a[3] + b[2] * b[3] - inter;
    return union > 0 ? inter / union : 0;
  }

  /**
   * outputs: object met cls_8.., obj_8.., bbox_8.. (Float32Array's)
   * Geeft [[x, y, w, h, score], ...] in invoercoördinaten, na NMS.
   */
  function decode(outputs, W, H, scoreThreshold = 0.3, nmsThreshold = 0.3) {
    const cands = [];
    for (const s of STRIDES) {
      const cols = W / s;
      const cls = outputs['cls_' + s], obj = outputs['obj_' + s], bb = outputs['bbox_' + s];
      for (let i = 0; i < cls.length; i++) {
        const c = Math.min(Math.max(cls[i], 0), 1);
        const o = Math.min(Math.max(obj[i], 0), 1);
        const score = Math.sqrt(c * o);
        if (score < scoreThreshold) continue;
        const r = Math.floor(i / cols), col = i % cols;
        const cx = (col + bb[i * 4]) * s, cy = (r + bb[i * 4 + 1]) * s;
        const w = Math.exp(bb[i * 4 + 2]) * s, h = Math.exp(bb[i * 4 + 3]) * s;
        cands.push([cx - w / 2, cy - h / 2, w, h, score]);
      }
    }
    cands.sort((a, b) => b[4] - a[4]);
    const keep = [];
    for (const c of cands) {
      if (keep.every(k => iou(k, c) <= nmsThreshold)) keep.push(c);
    }
    return keep;
  }

  const api = { inputSize, toTensor, decode, iou };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.YuNet = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
