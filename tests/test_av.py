"""Tests voor Face Anonymizer for AV (video, beeldreeks, foto). Geen scherm nodig.

Maakt zelf een korte testvideo met een bewegend gezicht, geluid en een GPS-locatie.
"""
import sys
import urllib.request
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
av = pytest.importorskip("av")
import av_core as ac  # noqa: E402
import face_core as fc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / ".cache" / "yunet"
FPS, N, W, H = 25, 75, 960, 540


def lena():
    p = CACHE / "lena.jpg"
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve("https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg", p)
    return cv2.imread(str(p))


def scene(i):
    """Beeld i: een hoofd dat heen en weer beweegt, plus waar het gezicht zit."""
    head = cv2.resize(lena(), (W, H))[110:450, 360:720]          # 360x340
    bg = np.full((H, W, 3), 110, np.uint8)
    x = int(240 + 200 * np.sin(2 * np.pi * i / FPS / 3.0))
    bg[100:440, x:x + 360] = head
    return bg, (x + 56, 152, 258, 261)                           # waar YuNet het gezicht vindt


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    path = tmp_path_factory.mktemp("in") / "opname.mp4"
    out = av.open(str(path), "w")
    out.metadata["location"] = "+51.4416+005.4697/"
    out.metadata["title"] = "geheim"
    vs = out.add_stream("libx264", rate=FPS)
    vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
    aus = out.add_stream("aac", rate=48000)
    for i in range(N):
        img, _ = scene(i)
        for p in vs.encode(av.VideoFrame.from_ndarray(img, format="bgr24")):
            out.mux(p)
    t = np.arange(int(48000 * N / FPS)) / 48000
    tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    for k in range(0, len(tone), 1024):
        chunk = tone[k:k + 1024]
        af = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="fltp", layout="mono")
        af.sample_rate, af.pts, af.time_base = 48000, k, Fraction(1, 48000)
        for p in aus.encode(af):
            out.mux(p)
    for s in (vs, aus):
        for p in s.encode(None):
            out.mux(p)
    out.close()
    return path


@pytest.fixture(scope="module")
def settings():
    return ac.Settings(overlay=ROOT / "assets" / "overlay.png")


def visible(out_img, src_img, box):
    x, y, w, h = box
    cx, cy, r = x + w // 2, y + h // 2, int(w * 0.35)
    a = out_img[cy - r:cy + r, cx - r:cx + r].astype(int)
    b = src_img[cy - r:cy + r, cx - r:cx + r].astype(int)
    return (np.abs(a - b).max(axis=2) < 25).mean()


def test_video_faces_audio_metadata(video, settings, tmp_path):
    item = ac.items_for_paths([video])[0]
    ac.plan_output(item, tmp_path)
    ac.process(item, settings, ac.Detector(settings))
    assert item.out.name == "opname_anoniem.mp4" and item.face_count >= 1

    c = av.open(str(item.out))
    assert c.streams.audio, "geluid moet behouden blijven"
    assert "location" not in c.metadata and "title" not in c.metadata, "metadata moet weg"
    frames = [f.to_ndarray(format="bgr24") for f in c.decode(video=0)]
    assert len(frames) == N
    assert abs(float(c.duration) / 1e6 - N / FPS) < 0.15
    worst = max(visible(frames[i], scene(i)[0], scene(i)[1]) for i in range(N))
    assert worst < 0.1, f"gezicht {worst:.0%} zichtbaar"


def test_gap_is_filled(video, settings, tmp_path):
    item = ac.items_for_paths([video])[0]
    ac.plan_output(item, tmp_path)
    ac.analyse(item, settings, ac.Detector(settings))
    for i in range(30, 42):                       # 0,5 s lang geen detecties
        item.detections[i] = []
    ac.build_tracks(item, settings)
    assert all(item.frame_faces(i) for i in range(N)), "elk beeld moet een masker hebben"
    assert any(t.filled for t in item.tracks), "opgevulde beelden moeten gemarkeerd zijn"
    ac.render(item, settings)
    frames = [f.to_ndarray(format="bgr24") for f in av.open(str(item.out)).decode(video=0)]
    worst = max(visible(frames[i], scene(i)[0], scene(i)[1]) for i in range(30, 42))
    assert worst < 0.1


def test_single_false_hit_is_dropped(settings):
    item = ac.Item("video", Path("x.mp4"), fps=25, n_frames=50)
    item.detections = [[] for _ in range(50)]
    item.detections[10] = [fc.Face(100, 100, 50, 50, 0.55)]          # één losse twijfelachtige treffer
    for i in range(20, 40):
        item.detections[i] = [fc.Face(300 + i, 100, 60, 60, 0.9)]   # echt gezicht
    ac.build_tracks(item, settings)
    assert len(item.tracks) == 1


def test_manual_mask_and_remove(settings):
    item = ac.Item("video", Path("x.mp4"), fps=25, n_frames=100)
    item.detections = [[fc.Face(10, 10, 40, 40, 0.9)] for _ in range(100)]
    ac.build_tracks(item, settings)
    t = ac.add_manual(item, 50, 74, (200, 200, 60, 60))
    assert len(item.frame_faces(60)) == 2 and len(item.frame_faces(80)) == 1
    item.removed.add(item.tracks[0].id)
    assert len(item.frame_faces(60)) == 1 and item.frame_faces(60)[0].manual
    assert t.manual


def test_sequence_and_folder_scan(settings, tmp_path):
    seq = tmp_path / "shot"
    seq.mkdir()
    for i in range(12):
        cv2.imwrite(str(seq / f"shot_{i + 1:04d}.png"), scene(i)[0])
    cv2.imwrite(str(seq / "los.jpg"), scene(0)[0])
    items = ac.items_for_paths([seq])
    kinds = sorted(i.kind for i in items)
    assert kinds == ["photo", "sequence"]
    s_item = next(i for i in items if i.kind == "sequence")
    assert len(s_item.files) == 12
    ac.plan_output(s_item, tmp_path / "uit")
    ac.process(s_item, settings, ac.Detector(settings))
    outs = sorted(p.name for p in s_item.out.iterdir())
    assert outs == [f"shot_{i + 1:04d}.png" for i in range(12)]
    for i in range(12):
        assert visible(cv2.imread(str(s_item.out / outs[i])), scene(i)[0], scene(i)[1]) < 0.1


@pytest.mark.parametrize("rotation,op", [(90, cv2.ROTATE_90_CLOCKWISE), (-90, cv2.ROTATE_90_COUNTERCLOCKWISE),
                                         (270, cv2.ROTATE_90_COUNTERCLOCKWISE), (180, cv2.ROTATE_180)])
def test_upright_undoes_phone_rotation(rotation, op):
    img = scene(0)[0]
    stored = cv2.rotate(img, op)              # zo slaat een telefoon het beeld op
    assert np.array_equal(ac.upright(stored, rotation), img)


def test_overlay_fills_mask():
    r = fc.MaskRenderer("overlay", ROOT / "assets" / "overlay.png", 1.6)
    img = np.full((400, 400, 3), 128, np.uint8)
    f = fc.Face(140, 140, 100, 100, 1)
    r.apply(img, [f])
    x0, y0, size = r.mask_box(f)
    ys, xs = np.where(np.any(img != 128, axis=2))
    assert xs.max() - xs.min() + 1 >= size - 2, "logo moet het hele maskervlak vullen"
