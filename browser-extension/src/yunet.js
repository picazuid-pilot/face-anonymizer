/*
 * YuNet (face_detection_yunet_2023mar) pre- en postprocessing.
 * Identiek aan OpenCV's cv::FaceDetectorYN, geverifieerd tegen de Python-tool.
 * Werkt in de browser (globalThis.YuNet) en in Node (module.exports).
 */
(function (root) {
  const SIZE = 640;            // het model heeft een vaste invoer van 640x640
  const STRIDES = [8, 16, 32];

  /** RGBA-pixels (SIZE x SIZE) -> Float32Array in BGR, 0-255, NCHW. */
  function toTensor(rgba) {
    const n = SIZE * SIZE;
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
   * Geeft [[x, y, w, h, score], ...] in 640x640-coördinaten, na NMS.
   */
  function decode(outputs, scoreThreshold = 0.3, nmsThreshold = 0.3) {
    const cands = [];
    for (const s of STRIDES) {
      const cols = SIZE / s;
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

  const api = { SIZE, toTensor, decode, iou };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.YuNet = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
