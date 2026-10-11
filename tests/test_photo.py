"""Tests voor face_core en de Foto Anonymizer (geen scherm nodig).

Downloadt eenmalig het YuNet-model en twee testfoto's van GitHub (OpenCV).
"""
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import face_core as fc  # noqa: E402
import photo_anonymizer as pa  # noqa: E402

CACHE = Path.home() / ".cache" / "yunet"
SAMPLES = {
    "group.pgm": "https://raw.githubusercontent.com/opencv/opencv_extra/4.x/testdata/gpu/haarcascade/group_1_640x480_VGA.pgm",
    "lena.jpg": "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg",
}


def sample(name):
    p = CACHE / name
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SAMPLES[name], p)
    return cv2.imread(str(p))


@pytest.fixture(scope="module")
def detector():
    return fc.create_detector()


def test_group_photo_all_accuracies(detector):
    img = cv2.resize(sample("group.pgm"), (2560, 1920))
    for acc in fc.ACCURACY:
        assert len(fc.detect_faces(detector, img, acc, 0.5)) >= 20, acc


def test_close_up_is_one_face_even_with_tiles(detector):
    img = cv2.resize(sample("lena.jpg"), (4000, 4000))
    assert len(fc.detect_faces(detector, img, "thorough", 0.5)) == 1


def test_small_faces_far_away_found(detector):
    canvas = np.full((3000, 4000, 3), 90, np.uint8)
    canvas[1800:2760, 2500:3780] = cv2.resize(sample("group.pgm"), (1280, 960))
    assert len(fc.detect_faces(detector, canvas, "normal", 0.5)) >= 20


def test_merge_removes_duplicates():
    a = fc.Face(100, 100, 50, 50, 0.9)
    b = fc.Face(102, 101, 50, 50, 0.8)        # zelfde gezicht, andere schaal
    c = fc.Face(110, 110, 20, 20, 0.7)        # stukje binnen a
    d = fc.Face(400, 100, 50, 50, 0.6)        # ander gezicht
    assert fc.merge_faces([b, c, a, d]) == [a, d]


@pytest.mark.parametrize("mode", fc.MODES)
def test_every_mode_covers_the_face(mode):
    img = sample("lena.jpg")
    face = fc.Face(217, 201, 173, 173, 0.9)
    out = img.copy()
    fc.MaskRenderer(mode, Path(__file__).resolve().parents[1] / "assets" / "overlay.png").apply(out, [face])
    core = (slice(250, 330), slice(260, 340))
    assert np.abs(out[core].astype(int) - img[core].astype(int)).mean() > 15


def test_masks_at_the_edge_do_not_crash():
    img = np.full((300, 400, 3), 128, np.uint8)
    r = fc.MaskRenderer("pixelate")
    r.apply(img, [fc.Face(-60, -60, 100, 100, 1), fc.Face(350, 250, 120, 120, 1), fc.Face(1000, 1000, 50, 50, 1)])


def test_exif_orientation_metadata_and_folders(tmp_path):
    src, dst = tmp_path / "in", tmp_path / "out"
    (src / "sub").mkdir(parents=True)
    sample("lena.jpg")
    lena = Image.open(CACHE / "lena.jpg").convert("RGB")
    exif = Image.Exif()
    exif[0x0112] = 6                       # telefoonfoto: 90° gedraaid opgeslagen
    exif[0x010F] = "TestCam"               # cameramerk
    lena.transpose(Image.ROTATE_90).save(src / "sub" / "foto.jpg", exif=exif.tobytes())
    (src / "kapot.jpg").write_bytes(b"geen foto")

    assert pa.run_cli([str(src), str(dst), "-r", "--mode", "black"]) == 1  # 1 = er was een mislukt bestand
    out = Image.open(dst / "sub" / "foto.jpg")
    assert len(out.getexif()) == 0                                            # metadata weg
    up = np.asarray(lena.convert("L"), float)
    got = np.asarray(out.convert("L"), float)
    assert np.abs(got[-60:] - up[-60:]).mean() < 10                           # rechtop gezet
    assert (src / "sub" / "foto.jpg").exists()                                # origineel bewaard


def test_refuses_same_folder(tmp_path):
    with pytest.raises(ValueError):
        pa.check_folders(tmp_path, tmp_path)
