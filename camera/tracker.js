/*
 * Volgt gezichten tussen detecties door, zoals in de browserextensie:
 * - koppelt op overlap én afstand (snelle bewegingen blijven hetzelfde gezicht)
 * - voorspelt de positie tussen twee detecties uit de bewegingsrichting
 * - masker groeit bij snelle beweging en als een gezicht even kwijt is
 * - losse twijfelachtige treffers verdwijnen snel (smart persistence)
 * Coördinaten zijn die van het camerabeeld.
 */
(function (root) {
  const CONFIRM_HITS = 5;
  const TENTATIVE_PERSISTENCE = 5;
  const LOST_GROWTH = 0.02;
  const LOST_GROWTH_MAX = 0.4;
  const MAX_PREDICT_MS = 200;
  const MAX_SPEED = 3;          // px per ms; hoger is vrijwel zeker een meetfout
  const MOTION_PAD_MS = 120;
  const MOTION_PAD_MAX = 0.35;

  function iou(a, b) {
    const x1 = Math.max(a.x, b.x), y1 = Math.max(a.y, b.y);
    const x2 = Math.min(a.x + a.w, b.x + b.w), y2 = Math.min(a.y + a.h, b.y + b.h);
    if (x2 <= x1 || y2 <= y1) return 0;
    const inter = (x2 - x1) * (y2 - y1);
    return inter / (a.w * a.h + b.w * b.h - inter);
  }

  class Tracker {
    constructor() { this.faces = []; this.tick = 0; }

    reset() { this.faces = []; }

    static predict(f, now) {
      const dt = Math.min(Math.max(0, now - f.t), MAX_PREDICT_MS);
      return { x: f.x + f.vx * dt, y: f.y + f.vy * dt, w: f.w, h: f.h };
    }

    /** boxes: [[x, y, w, h, score]] in beeldcoördinaten; t: moment van het frame. */
    update(boxes, t, opts) {
      this.tick++;
      const dets = boxes
        .filter(([, , w, h, s]) => s >= opts.confidence && w > opts.minSize && h > opts.minSize)
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
        let limit = opts.persistence;
        if (f.hits < CONFIRM_HITS) limit = Math.min(limit, TENTATIVE_PERSISTENCE);
        return this.tick - f.last <= limit;
      });
    }

    /** Vierkante maskers [x, y, size] op tijdstip `now`, kleinste eerst. */
    masks(now, scale) {
      return this.faces
        .map((f) => {
          const p = Tracker.predict(f, now);
          const base = Math.max(f.w, f.h);
          const lost = this.tick - f.last;
          const motion = Math.min(MOTION_PAD_MAX, Math.hypot(f.vx, f.vy) * MOTION_PAD_MS / base);
          const grow = 1 + Math.min(LOST_GROWTH_MAX, LOST_GROWTH * lost) + motion;
          const size = base * scale * grow;
          return [p.x + p.w / 2 - size / 2, p.y + p.h / 2 - size / 2, size];
        })
        .sort((a, b) => a[2] - b[2]);
    }
  }

  root.FaTracker = Tracker;
})(typeof globalThis !== 'undefined' ? globalThis : this);
