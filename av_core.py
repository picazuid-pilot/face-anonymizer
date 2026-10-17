"""
Verwerkingskern van Face Anonymizer for AV: video's, beeldreeksen en losse foto's.

Werkwijze voor video's en beeldreeksen (twee rondes):
  1. In elk beeld gezichten zoeken (face_core) en de tijdstempels onthouden.
  2. Detecties over de tijd koppelen tot sporen. Gaten waarin een gezicht even
     gemist werd, worden opgevuld (de tool kent het beeld ervoor én erna), en
     elk spoor krijgt een marge in tijd. Daarna wordt alles opnieuw geschreven:
     video met het originele geluid, zonder metadata (GPS, titel, toestel).

Gebruikt door av_anonymizer.py (venster en opdrachtregel).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import face_core as fc
from photo_anonymizer import load_image, HEIC  # EXIF-rotatie en HEIC

try:
    import av
    VIDEO_SUPPORT = True
except ImportError:  # pragma: no cover
    av = None
    VIDEO_SUPPORT = False

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts", ".mpg", ".mpeg", ".wmv", ".3gp"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"} | ({".heic", ".heif"} if HEIC else set())

# Snelheid/nauwkeurigheid: in hoeveel beelden wordt gezocht, en hoe grondig
SPEED = {
    "fast": {"accuracy": "fast", "every": 2},       # elk 2e beeld, ertussen wordt aangevuld
    "normal": {"accuracy": "normal", "every": 1},
    "thorough": {"accuracy": "thorough", "every": 1},
}
SEQUENCE_FPS = 25          # aangenomen beeldsnelheid voor beeldreeksen (voor tijdsmarges)
MIN_SEQUENCE = 3           # minimaal zoveel genummerde beelden om als reeks te tellen
COPY_AUDIO = {"aac", "mp3", "alac", "opus", "ac3", "eac3"}  # zonder hercoderen naar mp4


@dataclass
class Settings:
    mode: str = "overlay"
    overlay: object = None          # pad of None
    scale: float = 1.6
    mirror: bool = False
    speed: str = "normal"
    confidence: float = 0.5
    gap_s: float = 1.5              # gaten tot zo lang worden opgevuld (bijv. even opzij kijken)
    pad_s: float = 0.4              # masker zoveel eerder/later tonen
    quality: int = 18               # x264 CRF (lager = beter)


@dataclass
class Track:
    id: int
    obs: dict = field(default_factory=dict)     # beeld -> (x, y, w, h, score), echt gedetecteerd
    boxes: dict = field(default_factory=dict)   # beeld -> (x, y, w, h), na opvullen/marge/gladstrijken
    manual: bool = False
    filled: set = field(default_factory=set)    # beelden die opgevuld zijn (geen eigen detectie)

    @property
    def max_score(self):
        return max((o[4] for o in self.obs.values()), default=1.0)


@dataclass
class Item:
    """Eén ding in de wachtrij: een video, een beeldreeks of een foto."""
    kind: str                       # "video" | "sequence" | "photo"
    source: Path                    # bestand, of map bij een reeks
    files: list = field(default_factory=list)   # beelden bij een reeks
    out: Path = None
    fps: float = 25.0
    n_frames: int = 0
    size: tuple = (0, 0)            # (breedte, hoogte) rechtop
    rotation: int = 0
    pts: list = field(default_factory=list)
    detections: list = field(default_factory=list)   # per beeld: [Face]
    tracks: list = field(default_factory=list)
    removed: set = field(default_factory=set)        # handmatig weggehaalde sporen
    status: str = "wacht"
    error: str = ""
    seconds: float = 0.0

    @property
    def name(self):
        return self.source.name

    @property
    def label(self):
        return {"video": "Video", "sequence": f"Reeks ({len(self.files)} beelden)", "photo": "Foto"}[self.kind]

    def frame_faces(self, idx):
        """Alle maskers in beeld idx (sporen + handmatig), als face_core.Face."""
        faces = []
        for t in self.tracks:
            if t.id in self.removed:
                continue
            b = t.boxes.get(idx)
            if b:
                faces.append(fc.Face(*b[:4], 1.0, manual=t.manual))
        return faces

    @property
    def face_count(self):
        return sum(1 for t in self.tracks if t.id not in self.removed)


# ------------------------------------------------------------- invoer zoeken
_NUM = re.compile(r"^(.*?)(\d+)$")


def _natural_key(p: Path):
    return [int(s) if s.isdigit() else s.lower() for s in re.split(r"(\d+)", p.name)]


def scan_folder(folder: Path):
    """Een map wordt een beeldreeks (genummerde beelden met dezelfde naam) of losse foto's/video's."""
    files = sorted((p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")), key=_natural_key)
    images = [p for p in files if p.suffix.lower() in IMAGE_EXT]
    videos = [p for p in files if p.suffix.lower() in VIDEO_EXT]
    items = [Item("video", v) for v in videos]

    # Groepeer beelden op (voorvoegsel, extensie) als ze eindigen op een nummer
    groups, singles = {}, []
    for p in images:
        m = _NUM.match(p.stem)
        if m:
            groups.setdefault((m.group(1), p.suffix.lower()), []).append(p)
        else:
            singles.append(p)
    for (prefix, ext), members in groups.items():
        if len(members) >= MIN_SEQUENCE:
            items.append(Item("sequence", folder if len(groups) == 1 and not singles else folder / f"{prefix}*{ext}",
                              files=sorted(members, key=_natural_key)))
        else:
            singles += members
    items += [Item("photo", p) for p in sorted(singles, key=_natural_key)]
    return items


def items_for_paths(paths):
    items = []
    for p in map(Path, paths):
        if p.is_dir():
            items += scan_folder(p)
        elif p.suffix.lower() in VIDEO_EXT:
            items.append(Item("video", p))
        elif p.suffix.lower() in IMAGE_EXT:
            items.append(Item("photo", p))
    return items


def plan_output(item: Item, out_dir: Path):
    """Uitvoerpad naast de originelen nooit overschrijven: altijd een aparte naam."""
    if item.kind == "video":
        item.out = out_dir / f"{item.source.stem}_anoniem.mp4"
    elif item.kind == "sequence":
        base = item.files[0].parent.name if "*" not in item.source.name else item.source.name.split("*")[0].rstrip("_-. ")
        item.out = out_dir / f"{base or 'reeks'}_anoniem"
    else:
        ext = ".jpg" if item.source.suffix.lower() in {".heic", ".heif"} else item.source.suffix.lower()
        item.out = out_dir / f"{item.source.stem}_anoniem{ext}"
    return item.out


# --------------------------------------------------------------- beelden
def upright(img, rotation):
    """Zet een videobeeld rechtop volgens de draaiing uit de video (zoals ffmpeg)."""
    r = int(round(rotation)) % 360
    if r == 90:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if r == 270:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if r == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    return img


def save_still(img, path: Path, fast=False):
    """Slaat een beeld op zonder metadata. fast: geen extra compressie (voor reeksen)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    ext = path.suffix.lower()
    tmp = path.with_name(path.name + ".part")
    if ext in (".jpg", ".jpeg"):
        im.save(tmp, "JPEG", quality=92, optimize=not fast)
    elif ext == ".webp":
        im.save(tmp, "WEBP", quality=92)
    elif ext == ".png":
        im.save(tmp, "PNG", optimize=not fast, compress_level=6 if not fast else 3)
    elif ext in (".tif", ".tiff"):
        im.save(tmp, "TIFF", compression="tiff_deflate")
    else:
        im.save(tmp, "BMP")
    tmp.replace(path)


class VideoReader:
    """Leest beelden uit een video, rechtop, met willekeurige toegang voor het nalopen."""

    def __init__(self, path):
        self.c = av.open(str(path))
        self.vs = self.c.streams.video[0]
        self.vs.thread_type = "AUTO"

    def frames(self):
        for fr in self.c.decode(self.vs):
            yield fr, upright(fr.to_ndarray(format="bgr24"), fr.rotation)

    def frame_at(self, pts):
        self.c.seek(pts, stream=self.vs, backward=True, any_frame=False)
        last = None
        for fr in self.c.decode(self.vs):
            last = fr
            if fr.pts is not None and fr.pts >= pts:
                break
        return upright(last.to_ndarray(format="bgr24"), last.rotation) if last else None

    def close(self):
        self.c.close()


def read_frame(item: Item, idx: int, reader=None):
    if item.kind == "video":
        own = reader is None
        reader = reader or VideoReader(item.source)
        try:
            return reader.frame_at(item.pts[idx])
        finally:
            if own:
                reader.close()
    if item.kind == "sequence":
        return load_image(item.files[idx])
    return load_image(item.source)


# --------------------------------------------------------------- ronde 1
class Detector:
    def __init__(self, settings: Settings):
        self.s = settings
        cfg = SPEED[settings.speed]
        self.accuracy, self.every = cfg["accuracy"], cfg["every"]
        # Iets lagere drempel om sporen te kunnen volgen; een spoor telt pas
        # mee als het minstens één keer de echte drempel haalt (zie build_tracks).
        self.low = max(0.3, settings.confidence - 0.15)
        self.net = fc.create_detector(score=self.low)

    def detect(self, img):
        return fc.detect_faces(self.net, img, self.accuracy, self.low)


def analyse(item: Item, settings: Settings, detector: Detector, progress=None, stop=None, preview=None):
    """Ronde 1: zoek gezichten in elk beeld en bouw de sporen."""
    t0 = time.time()
    item.detections, item.pts, item.removed = [], [], set()
    if item.kind == "photo":
        img = load_image(item.source)
        item.size, item.n_frames, item.fps = (img.shape[1], img.shape[0]), 1, 1
        # Een foto staat stil: grondig zoeken kost bijna niets extra
        faces = fc.detect_faces(detector.net, img, "thorough" if settings.speed != "fast" else "normal",
                                settings.confidence)
        item.detections = [faces]
        item.tracks = [Track(i, {0: (*f.box(), f.score)}, {0: f.box()}) for i, f in enumerate(faces)]
        return

    if item.kind == "video":
        reader = VideoReader(item.source)
        vs = reader.vs
        item.fps = float(vs.average_rate or vs.guessed_rate or 25)
        total = vs.frames or int(float(vs.duration * vs.time_base) * item.fps) if vs.duration else 0
        frames = reader.frames()
    else:
        item.fps = SEQUENCE_FPS
        total = len(item.files)
        frames = ((None, load_image(p)) for p in item.files)
        reader = None

    try:
        for idx, (fr, img) in enumerate(frames):
            if stop is not None and stop.is_set():
                raise InterruptedError
            if idx == 0:
                item.size = (img.shape[1], img.shape[0])
                item.rotation = fr.rotation if fr is not None else 0
            item.pts.append(fr.pts if fr is not None else idx)
            item.detections.append(detector.detect(img) if idx % detector.every == 0 else None)
            if progress and idx % 5 == 0:
                progress(idx, max(total, idx + 1), "Gezichten zoeken")
            if preview and idx % 15 == 0:
                preview(img, item.detections[-1] or [])
    finally:
        if reader:
            reader.close()
    item.n_frames = len(item.pts)
    build_tracks(item, settings)
    item.seconds = time.time() - t0


# --------------------------------------------------------------- sporen
def _center(b):
    return b[0] + b[2] / 2, b[1] + b[3] / 2


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def build_tracks(item: Item, s: Settings):
    """Koppel detecties over de tijd, vul gaten op, voeg marge toe en strijk glad."""
    fps = item.fps or 25
    max_gap = max(2, int(round(s.gap_s * fps)))
    pad = int(round(s.pad_s * fps))
    tracks, active, next_id = [], [], 0

    for idx, dets in enumerate(item.detections):
        if dets is None:
            continue
        active = [t for t in active if idx - max(t.obs) <= max_gap]
        pairs = []
        for di, d in enumerate(dets):
            db = d.box()
            for ti, t in enumerate(active):
                last_f = max(t.obs)
                lb = t.obs[last_f][:4]
                # Voorspel waar het gezicht nu is uit de laatste twee waarnemingen
                frames = sorted(t.obs)
                if len(frames) >= 2:
                    pf = frames[-2]
                    (cx0, cy0), (cx1, cy1) = _center(t.obs[pf]), _center(lb)
                    k = (idx - last_f) / max(1, last_f - pf)
                    pc = (cx1 + (cx1 - cx0) * k, cy1 + (cy1 - cy0) * k)
                else:
                    pc = _center(lb)
                size = max(lb[2], lb[3])
                dist = np.hypot(_center(db)[0] - pc[0], _center(db)[1] - pc[1]) / size
                ratio = max(db[2], db[3]) / size
                # Hoe langer het gezicht kwijt was, hoe verder het verplaatst mag zijn
                # (tot ~3 gezichtsbreedtes per seconde: een snel draaiend hoofd).
                gate = min(3.5, 0.9 + 3.0 * (idx - last_f) / fps)
                if 0.5 < ratio < 2.0 and (dist < gate or _iou(db, lb) > 0.2):
                    pairs.append((dist, di, ti))
        pairs.sort()
        used_d, used_t = set(), set()
        for _, di, ti in pairs:
            if di in used_d or ti in used_t:
                continue
            used_d.add(di)
            used_t.add(ti)
            d = dets[di]
            active[ti].obs[idx] = (*d.box(), d.score)
        for di, d in enumerate(dets):
            if di not in used_d:
                t = Track(next_id, {idx: (*d.box(), d.score)})
                next_id += 1
                tracks.append(t)
                active.append(t)

    # Losse twijfelgevallen weg: een spoor moet de echte drempel halen,
    # en één losse treffer telt alleen als die overtuigend is.
    keep = []
    for t in tracks:
        if t.max_score < s.confidence:
            continue
        if len(t.obs) < 2 and t.max_score < min(0.95, s.confidence + 0.25):
            continue
        keep.append(t)

    n = item.n_frames
    for t in keep:
        frames = sorted(t.obs)
        obs = {f: np.array(t.obs[f][:4], float) for f in frames}
        centers = {f: np.array(_center(obs[f])) for f in frames}

        def velocity(i):
            """Snelheid (px per beeld) rond waarneming i, uit de buren."""
            lo, hi = frames[max(0, i - 1)], frames[min(len(frames) - 1, i + 1)]
            return (centers[hi] - centers[lo]) / (hi - lo) if hi != lo else np.zeros(2)

        raw, t.filled = {}, set()
        for i, (a, b) in enumerate(zip(frames, frames[1:])):
            A, B = obs[a], obs[b]
            span = b - a
            va, vb = velocity(i) * span, velocity(i + 1) * span
            for f in range(a, b):
                u = (f - a) / span
                if span <= 2:
                    raw[f] = A + (B - A) * u
                    continue
                # Gat opvullen langs een gebogen baan (Hermite): houdt rekening met
                # de bewegingsrichting aan beide kanten van het gat.
                h00, h10, h01, h11 = 2*u**3 - 3*u**2 + 1, u**3 - 2*u**2 + u, -2*u**3 + 3*u**2, u**3 - u**2
                c = h00 * centers[a] + h10 * va + h01 * centers[b] + h11 * vb
                size = A[2:] + (B[2:] - A[2:]) * u
                # Hoe verder van een echte waarneming, hoe onzekerder: masker groeit mee
                away = min(f - a, b - f) / fps
                size = size * min(2.2, 1 + 1.2 * away)
                raw[f] = np.array([c[0] - size[0] / 2, c[1] - size[1] / 2, size[0], size[1]])
                if span > 3:
                    t.filled.add(f)
        raw[frames[-1]] = obs[frames[-1]]
        # Marge in tijd: het masker staat er al iets eerder en blijft iets langer
        first, last = np.array(t.obs[frames[0]][:4]), raw[frames[-1]]
        for f in range(max(0, frames[0] - pad), frames[0]):
            raw[f] = first
        for f in range(frames[-1] + 1, min(n, frames[-1] + pad + 1)):
            raw[f] = last
        # Gladstrijken (voorkomt trillende maskers), venster van 5 beelden
        keys = sorted(raw)
        arr = np.array([raw[k] for k in keys])
        if len(arr) >= 5:
            def smooth(v):
                return np.convolve(np.pad(v, 2, mode="edge"), np.ones(5) / 5, mode="valid")
            cx = smooth(arr[:, 0] + arr[:, 2] / 2)
            cy = smooth(arr[:, 1] + arr[:, 3] / 2)
            # Grootte nooit kleiner dan de echte detectie (veiligheid gaat voor)
            bw = np.maximum(smooth(arr[:, 2]), arr[:, 2])
            bh = np.maximum(smooth(arr[:, 3]), arr[:, 3])
            arr = np.stack([cx - bw / 2, cy - bh / 2, bw, bh], axis=1)
        t.boxes = {k: tuple(float(v) for v in arr[i]) for i, k in enumerate(keys)}
    item.tracks = keep
    return keep


def add_manual(item: Item, start: int, end: int, box):
    """Handmatig masker: vast vak van beeld start t/m end."""
    tid = max((t.id for t in item.tracks), default=-1) + 1
    t = Track(tid, {start: (*box, 1.0)}, {f: tuple(box) for f in range(max(0, start), min(item.n_frames, end + 1))},
              manual=True)
    item.tracks.append(t)
    return t


def tracks_at(item: Item, idx: int, x: float, y: float, renderer):
    """Sporen waarvan het masker in beeld idx het punt (x, y) bedekt, kleinste eerst."""
    hits = []
    for t in item.tracks:
        if t.id in item.removed or idx not in t.boxes:
            continue
        mx, my, size = renderer.mask_box(fc.Face(*t.boxes[idx][:4], 1.0))
        if mx <= x <= mx + size and my <= y <= my + size:
            hits.append((size, t))
    return [t for _, t in sorted(hits, key=lambda h: h[0])]


# --------------------------------------------------------------- ronde 2
def make_renderer(s: Settings):
    ov = s.overlay if s.overlay and Path(s.overlay).exists() else None
    return fc.MaskRenderer(s.mode, ov, s.scale, s.mirror)


def render(item: Item, s: Settings, progress=None, stop=None, preview=None, renderer=None):
    """Ronde 2: schrijf het resultaat weg met maskers."""
    renderer = renderer or make_renderer(s)
    if item.kind == "photo":
        img = load_image(item.source)
        renderer.apply(img, item.frame_faces(0))
        save_still(img, item.out)
        return
    if item.kind == "sequence":
        item.out.mkdir(parents=True, exist_ok=True)
        for idx, p in enumerate(item.files):
            if stop is not None and stop.is_set():
                raise InterruptedError
            img = load_image(p)
            renderer.apply(img, item.frame_faces(idx))
            ext = ".jpg" if p.suffix.lower() in {".heic", ".heif"} else p.suffix.lower()
            save_still(img, item.out / (p.stem + ext), fast=True)
            if progress and idx % 5 == 0:
                progress(idx, len(item.files), "Wegschrijven")
            if preview and idx % 15 == 0:
                preview(img, [])
        return
    _render_video(item, s, renderer, progress, stop, preview)


def _render_video(item, s, renderer, progress, stop, preview):
    out_tmp = item.out.with_name(item.out.stem + ".part.mp4")
    item.out.parent.mkdir(parents=True, exist_ok=True)
    inp = av.open(str(item.source))
    vin = inp.streams.video[0]
    vin.thread_type = "AUTO"
    ain = inp.streams.audio[0] if inp.streams.audio else None
    pts_index = {p: i for i, p in enumerate(item.pts)}

    out = av.open(str(out_tmp), "w", format="mp4", options={"movflags": "+faststart"})
    rate = vin.average_rate or vin.guessed_rate or Fraction(25)
    w, h = item.size
    w2, h2 = w - (w % 2), h - (h % 2)   # H.264 vraagt even afmetingen
    codec = "libx264" if "libx264" in av.codecs_available else "mpeg4"
    vout = out.add_stream(codec, rate=rate)
    vout.width, vout.height, vout.pix_fmt = w2, h2, "yuv420p"
    vout.time_base = vin.time_base
    if codec == "libx264":
        vout.options = {"crf": str(s.quality), "preset": "medium"}
    vout.codec_context.time_base = vin.time_base

    aout, copy_audio, resampler = None, False, None
    if ain is not None:
        copy_audio = ain.codec_context.name in COPY_AUDIO
        if copy_audio:
            aout = out.add_stream_from_template(ain)
        else:
            aout = out.add_stream("aac", rate=ain.rate or 48000)
            resampler = av.AudioResampler(format="fltp", layout=ain.layout.name if ain.layout else "stereo",
                                          rate=ain.rate or 48000)
    # Geen metadata overnemen: geen GPS-locatie, titel of toestel in het resultaat
    out.metadata.clear() if hasattr(out.metadata, "clear") else None

    idx = 0
    streams = [vin] + ([ain] if ain is not None else [])
    try:
        for packet in inp.demux(*streams):
            if stop is not None and stop.is_set():
                raise InterruptedError
            if packet.stream is ain:
                if copy_audio:
                    if packet.dts is None:
                        continue
                    packet.stream = aout
                    out.mux(packet)
                else:
                    for af in packet.decode():
                        for rf in resampler.resample(af):
                            for p in aout.encode(rf):
                                out.mux(p)
                continue
            for fr in packet.decode():
                img = upright(fr.to_ndarray(format="bgr24"), fr.rotation)
                fi = pts_index.get(fr.pts, idx)
                renderer.apply(img, item.frame_faces(fi))
                if (w2, h2) != (img.shape[1], img.shape[0]):
                    img = img[:h2, :w2]
                nf = av.VideoFrame.from_ndarray(np.ascontiguousarray(img), format="bgr24")
                nf.pts, nf.time_base = fr.pts, fr.time_base
                for p in vout.encode(nf):
                    out.mux(p)
                if progress and idx % 5 == 0:
                    progress(idx, max(item.n_frames, idx + 1), "Wegschrijven")
                if preview and idx % 15 == 0:
                    preview(img, [])
                idx += 1
        for p in vout.encode(None):
            out.mux(p)
        if aout is not None and not copy_audio:
            for p in aout.encode(None):
                out.mux(p)
    except BaseException:
        out.close()
        inp.close()
        out_tmp.unlink(missing_ok=True)
        raise
    out.close()
    inp.close()
    out_tmp.replace(item.out)   # nooit een half geschreven video achterlaten


def process(item: Item, s: Settings, detector: Detector, progress=None, stop=None, preview=None):
    analyse(item, s, detector, progress, stop, preview)
    render(item, s, progress, stop, preview)
