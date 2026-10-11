"""
Gedeelde kern voor de Face Anonymizer-tools.

- Modelbeheer (YuNet downloaden en laden)
- Gezichtsdetectie op meerdere schalen en in tegels, voor foto's waarin
  zowel grote als heel kleine gezichten (publiek op afstand) voorkomen
- Maskers tekenen: overlay, pixels, blur of zwart

Gebruikt door photo_anonymizer.py (en het modelbeheer ook door face_anonymizer.py).
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
YUNET_URLS = [
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/" + YUNET_FILE,
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/" + YUNET_FILE,
]
MODEL_DIR = Path.home() / ".cache" / "yunet"
MIN_MODEL_BYTES = 100_000  # een Git-LFS-pointer of foutpagina is maar een paar honderd bytes

MODES = ["overlay", "pixelate", "blur", "black"]

# Detectieniveaus voor foto's: lange zijde in pixels waarop gezocht wordt.
# "tiles" = daarnaast in overlappende tegels op volle resolutie (kleine gezichten).
ACCURACY = {
    "fast": {"levels": [1280], "tiles": False},
    "normal": {"levels": [640, 1600], "tiles": False},
    "thorough": {"levels": [640, 1600], "tiles": True},
}
TILE = 1280
TILE_OVERLAP = 0.25


# --------------------------------------------------------------------- model
def ensure_model(status=print) -> Path:
    """Geeft het pad van het YuNet-model; downloadt het als het ontbreekt."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / YUNET_FILE
    if model_path.exists() and model_path.stat().st_size >= MIN_MODEL_BYTES:
        return model_path

    status("Downloading YuNet model...")
    tmp = model_path.with_suffix(".part")
    errors = []
    for url in YUNET_URLS:
        try:
            urllib.request.urlretrieve(url, tmp)
            if tmp.stat().st_size >= MIN_MODEL_BYTES:
                tmp.replace(model_path)  # nooit een half/ongeldig model achterlaten
                return model_path
            errors.append(f"{url}: invalid file")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url}: {e}")
    tmp.unlink(missing_ok=True)
    raise RuntimeError("Model download failed. " + " | ".join(errors) +
                       f" — download it manually to {model_path}")


def create_detector(width=640, height=640, score=0.5, nms=0.3, status=print):
    detector = cv2.FaceDetectorYN.create(str(ensure_model(status)), "", (width, height))
    detector.setScoreThreshold(score)
    detector.setNMSThreshold(nms)
    return detector


# ----------------------------------------------------------------- detectie
@dataclass
class Face:
    x: float
    y: float
    w: float
    h: float
    score: float
    manual: bool = False  # met de hand toegevoegd in het controlevenster

    def box(self):
        return self.x, self.y, self.w, self.h

    def to_dict(self):
        return {"x": round(self.x, 1), "y": round(self.y, 1), "w": round(self.w, 1),
                "h": round(self.h, 1), "score": round(float(self.score), 3), "manual": self.manual}


def _run(detector, img, scale, ox=0, oy=0):
    """Detecteert in img en geeft gezichten terug in coördinaten van de originele foto."""
    h, w = img.shape[:2]
    detector.setInputSize((w, h))
    _, dets = detector.detect(img)
    out = []
    if dets is not None:
        for d in dets:
            x, y, bw, bh = (float(v) for v in d[:4])
            out.append(Face(x / scale + ox, y / scale + oy, bw / scale, bh / scale, float(d[-1])))
    return out


def _tiles(length, tile, overlap):
    if length <= tile:
        return [0]
    step = int(tile * (1 - overlap))
    starts = list(range(0, length - tile, step))
    starts.append(length - tile)
    return starts


def _iou(a, b):
    ax, ay, aw, ah = a.box()
    bx, by, bw, bh = b.box()
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0, 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = aw * ah + bw * bh - inter
    return inter / union, inter / min(aw * ah, bw * bh)


def merge_faces(faces, iou_thr=0.3, contain_thr=0.7):
    """Ontdubbelt detecties van verschillende schalen/tegels (hoogste score wint)."""
    faces = sorted(faces, key=lambda f: f.score, reverse=True)
    keep = []
    for f in faces:
        if all(_iou(f, k)[0] <= iou_thr and _iou(f, k)[1] <= contain_thr for k in keep):
            keep.append(f)
    return keep


def detect_faces(detector, img, accuracy="normal", min_score=0.5, min_size=0):
    """
    Zoekt gezichten in een foto (BGR) op meerdere schalen.
    Kleine foto's worden ook vergroot, zodat kleine gezichten gevonden worden.
    """
    cfg = ACCURACY[accuracy]
    h, w = img.shape[:2]
    long_side = max(h, w)
    found = []

    levels = sorted({min(lv, max(long_side, 640)) for lv in cfg["levels"]})
    for lv in levels:
        s = lv / long_side
        interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
        scaled = img if abs(s - 1) < 1e-3 else cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))),
                                                         interpolation=interp)
        found += _run(detector, scaled, s)

    if cfg["tiles"] and long_side > TILE * 1.25:
        # Tegels zijn alleen voor kleine gezichten; grote vinden de schaalstappen al.
        # Een groot "gezicht" in een tegel is meestal een stukje van een echt groot gezicht.
        max_tile_face = TILE * TILE_OVERLAP * 0.8
        margin = 4
        for ty in _tiles(h, TILE, TILE_OVERLAP):
            for tx in _tiles(w, TILE, TILE_OVERLAP):
                tile = img[ty:ty + TILE, tx:tx + TILE]
                th, tw = tile.shape[:2]
                for f in _run(detector, tile, 1.0, tx, ty):
                    if max(f.w, f.h) > max_tile_face:
                        continue
                    # Afgesneden door een tegelrand (niet de fotorand)? Dan vindt de buurtegel hem heel.
                    lx, ly = f.x - tx, f.y - ty
                    cut = ((lx < margin and tx > 0) or (ly < margin and ty > 0) or
                           (lx + f.w > tw - margin and tx + tw < w) or
                           (ly + f.h > th - margin and ty + th < h))
                    if not cut:
                        found.append(f)

    found = [f for f in found if f.score >= min_score and f.w >= min_size and f.h >= min_size]
    return merge_faces(found)


# ------------------------------------------------------------------ maskers
class MaskRenderer:
    """Tekent maskers op een BGR-beeld (in place)."""

    def __init__(self, mode="overlay", overlay=None, scale=1.6, mirror=False):
        self.mode = mode
        self.scale = scale
        self.mirror = mirror
        self.overlay = None
        self._cache = {}
        if overlay is not None:
            self.set_overlay(overlay)

    def set_overlay(self, overlay):
        """overlay: pad of BGRA/BGR-array."""
        if isinstance(overlay, (str, Path)):
            data = np.fromfile(str(overlay), dtype=np.uint8)  # werkt ook met niet-ASCII-paden
            overlay = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if overlay is None:
            self.overlay = None
        else:
            if overlay.ndim == 2:
                overlay = cv2.cvtColor(overlay, cv2.COLOR_GRAY2BGRA)
            elif overlay.shape[2] == 3:
                overlay = cv2.cvtColor(overlay, cv2.COLOR_BGR2BGRA)
            self.overlay = overlay
        self._cache = {}

    def mask_box(self, face):
        """Vierkant masker rond het gezicht: (x0, y0, size)."""
        size = int(round(max(face.w, face.h) * self.scale))
        cx, cy = face.x + face.w / 2, face.y + face.h / 2
        return int(round(cx - size / 2)), int(round(cy - size / 2)), size

    def _scaled_overlay(self, size):
        key = (size, self.mirror)
        if key not in self._cache:
            if len(self._cache) > 64:
                self._cache.clear()
            oh, ow = self.overlay.shape[:2]
            r = size / max(oh, ow)
            tw, th = max(1, int(ow * r)), max(1, int(oh * r))
            canvas = np.zeros((size, size, 4), np.uint8)
            interp = cv2.INTER_AREA if r < 1 else cv2.INTER_CUBIC
            canvas[(size - th) // 2:(size - th) // 2 + th, (size - tw) // 2:(size - tw) // 2 + tw] = \
                cv2.resize(self.overlay, (tw, th), interpolation=interp)
            if self.mirror:
                canvas = cv2.flip(canvas, 1)
            self._cache[key] = canvas
        return self._cache[key]

    def apply(self, img, faces):
        for f in sorted(faces, key=lambda f: f.w * f.h):  # kleinste eerst, grootste bovenop
            self.apply_one(img, f)
        return img

    def apply_one(self, img, face):
        x0, y0, size = self.mask_box(face)
        if size < 4:
            return
        H, W = img.shape[:2]
        dx0, dy0, dx1, dy1 = max(0, x0), max(0, y0), min(W, x0 + size), min(H, y0 + size)
        if dx1 <= dx0 or dy1 <= dy0:
            return
        roi = img[dy0:dy1, dx0:dx1]
        mode = self.mode
        if mode == "overlay" and self.overlay is None:
            mode = "pixelate"  # fail-safe: nooit onbedekt

        if mode == "overlay":
            ov = self._scaled_overlay(size)[dy0 - y0:dy1 - y0, dx0 - x0:dx1 - x0]
            a = ov[:, :, 3:4].astype(np.float32) / 255.0
            roi[:] = (roi * (1 - a) + ov[:, :, :3] * a).astype(np.uint8)
        elif mode == "pixelate":
            # Blokken op basis van het hele masker, zodat randen netjes aansluiten
            blocks = 10
            full = np.zeros((size, size, 3), np.uint8)
            full[dy0 - y0:dy1 - y0, dx0 - x0:dx1 - x0] = roi
            small = cv2.resize(full, (blocks, blocks), interpolation=cv2.INTER_AREA)
            big = cv2.resize(small, (size, size), interpolation=cv2.INTER_NEAREST)
            roi[:] = big[dy0 - y0:dy1 - y0, dx0 - x0:dx1 - x0]
        elif mode == "blur":
            # Eerst sterk verkleinen: onherkenbaar, ook bij grote foto's, en snel
            small = cv2.resize(roi, (12, 12), interpolation=cv2.INTER_AREA)
            small = cv2.GaussianBlur(small, (5, 5), 0)
            roi[:] = cv2.resize(small, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_CUBIC)
        else:
            roi[:] = 0
