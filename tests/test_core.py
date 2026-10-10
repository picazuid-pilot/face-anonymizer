"""Headless tests voor de kernlogica (geen camera of scherm nodig).

Draaien:  python -m pytest tests/    of    python tests/test_core.py
De gezichtstest downloadt eenmalig het YuNet-model en een testfoto van GitHub.
"""
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import face_anonymizer as fa  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEST_IMG_URL = "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg"


def make_worker():
    w = fa.AnonymizerWorker()
    w.load_overlay(ROOT / "assets" / "overlay.png")
    return w


def face(**kw):
    f = dict(id=0, x=100, y=100, w=80, h=80, confidence=0.9, first_seen=1, last_seen=1, hits=10)
    f.update(kw)
    return f


def test_debug_never_in_stream():
    w = make_worker()
    w.show_debug = True
    w.faces = [face()]
    w.frame_count = 1
    w.detector = None
    w.detect_faces = lambda frame: [(100, 100, 80, 80, 0.9)]
    stream, preview, _ = w.process_frame(np.full((480, 640, 3), 127, np.uint8), 1)
    assert stream is not preview
    # het debug-kader is pure groen (0,255,0); dat mag alleen in de preview staan
    green = lambda img: np.all(img == (0, 255, 0), axis=2).sum()
    assert green(stream) == 0 and green(preview) > 0


def test_fail_safe_without_overlay():
    w = fa.AnonymizerWorker()  # geen overlay geladen
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    before = frame.copy()
    w.frame_count = 1
    w.anonymize_face(frame, face())
    assert not np.array_equal(frame[100:180, 100:180], before[100:180, 100:180])


def test_overlay_covers_face_and_handles_edges():
    w = make_worker()
    for f in [face(), face(x=-40, y=-40), face(x=600, y=440)]:  # midden, linksboven, rechtsonder
        frame = np.full((480, 640, 3), 127, np.uint8)
        w.frame_count = 1
        w.anonymize_face(frame, f)
        cx, cy = f['x'] + f['w'] // 2, f['y'] + f['h'] // 2
        if 0 <= cx < 640 and 0 <= cy < 480:
            assert not np.array_equal(frame[cy, cx], [127, 127, 127])


def test_overlay_cache_reset_and_bounded():
    w = make_worker()
    for s in range(20, 2000, 3):
        w._scaled_overlay(s)
    assert len(w.overlay_cache) <= fa.OVERLAY_CACHE_MAX
    w.load_overlay(ROOT / "assets" / "overlay.png")
    assert w.overlay_cache == {}


def test_smart_persistence():
    w = make_worker()
    w.persistence_frames = 60
    w.update_faces([(10, 10, 50, 50, 0.5)], 1)           # één losse (valse) detectie
    for n in range(2, 2 + fa.CONFIRM_HITS):                # één echt gezicht, meerdere keren gezien
        w.update_faces([(300, 300, 80, 80, 0.9)], n)
    w.update_faces([], 1 + fa.TENTATIVE_PERSISTENCE + 1)
    ids_left = [f['hits'] for f in w.faces]
    assert ids_left == [fa.CONFIRM_HITS]                   # vals weg, echt gezicht blijft


def test_lost_face_mask_grows():
    w = make_worker()
    f = face(last_seen=1)
    w.frame_count = 1
    s0 = w._mask_box(f)[2]
    w.frame_count = 21
    assert w._mask_box(f)[2] > s0


def test_mirror_overlay():
    w = make_worker()
    w.frame_count = 1
    f = face(x=200, y=150, w=160, h=160)
    plain = np.full((480, 640, 3), 127, np.uint8)
    w.anonymize_face(plain, f)
    w.update_parameters({'mirror_overlay': True})
    mirrored = np.full((480, 640, 3), 127, np.uint8)
    w.anonymize_face(mirrored, f)
    x0, y0, size = w._mask_box(f)
    a = plain[y0:y0 + size, x0:x0 + size]
    b = mirrored[y0:y0 + size, x0:x0 + size]
    assert not np.array_equal(a, b)                       # echt anders
    assert np.abs(a.astype(int) - b[:, ::-1].astype(int)).mean() < 2  # en precies gespiegeld


def test_toggle_pause():
    w = fa.AnonymizerWorker()
    assert w.toggle_pause() is True and w.toggle_pause() is False


def test_real_face_detection_and_downscaled_detection(tmp_path=None):
    img_path = Path.home() / ".cache" / "yunet" / "lena.jpg"
    if not img_path.exists():
        img_path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(TEST_IMG_URL, img_path)
    img = cv2.imread(str(img_path))
    img = cv2.resize(img, (1920, 1080))  # simuleer 1080p
    w = make_worker()
    w.detector = w._load_yunet(img.shape[1], img.shape[0])
    full = w.detect_faces(img)
    w.detect_width = 640
    small = w.detect_faces(img)
    assert len(full) >= 1 and len(small) >= 1
    # de teruggeschaalde box moet ongeveer op dezelfde plek zitten
    (x1, y1, *_), (x2, y2, *_) = full[0], small[0]
    assert abs(x1 - x2) < 40 and abs(y1 - y2) < 40


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK ", name)
