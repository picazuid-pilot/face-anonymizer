#!/usr/bin/env python3
"""
FACE ANONYMIZER
Anonimiseert gezichten in een live webcambeeld (YuNet-gezichtsdetectie) en
stuurt het resultaat naar een virtuele camera (OBS Virtual Camera / v4l2loopback),
zodat je het in OBS, Zoom, Teams, YouTube enz. als camerabron kunt kiezen.

- Twee vensters: bediening + preview
- Debug-kaders zijn ALLEEN zichtbaar in de preview, nooit in de stream
- Fail-safe: zonder geladen overlay wordt er automatisch gepixeld
"""

import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

import face_core

VCAM_LABEL = "Face Anonymizer"
VCAM_OPTIONS = ["devices=1", "video_nr=10", "exclusive_caps=1", f"card_label={VCAM_LABEL}"]


def _run(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def secure_boot_enabled():
    if not shutil.which("mokutil"):
        return False
    _, out = _run(["mokutil", "--sb-state"], timeout=10)
    return "enabled" in out.lower()


def repair_v4l2loopback():
    """Probeert de virtuele-cameradriver te laden. Geeft (gelukt, uitleg) terug."""
    code, _ = _run(["modinfo", "v4l2loopback"], timeout=10)
    if code != 0:
        return False, ("The virtual camera driver (v4l2loopback) is not installed for this kernel. "
                       "Run ./install.sh again, or: sudo apt install v4l2loopback-dkms "
                       "linux-headers-$(uname -r)")
    if not shutil.which("pkexec"):
        return False, ("Driver is installed but not loaded. Run: sudo modprobe v4l2loopback "
                       + " ".join(VCAM_OPTIONS[:3]) + f' card_label="{VCAM_LABEL}"')
    _, lsmod = _run(["lsmod"], timeout=10)
    loaded = any(line.split()[:1] == ["v4l2loopback"] for line in lsmod.splitlines())
    # Geladen zonder bruikbaar apparaat (bijv. devices=0): eerst ontladen, dan goed laden.
    script = ("modprobe -r v4l2loopback 2>/dev/null; " if loaded else "") + \
        "modprobe v4l2loopback " + " ".join(VCAM_OPTIONS[:3]) + f" card_label='{VCAM_LABEL}'"
    code, out = _run(["pkexec", "sh", "-c", script])
    if code == 0:
        return True, ""
    if code in (126, 127) and "rejected" not in out.lower():
        return False, "Password prompt was cancelled. Turn the virtual camera off and on to try again."
    if "key was rejected" in out.lower() or "required key not available" in out.lower() \
            or secure_boot_enabled():
        return False, ("Secure Boot blocks the virtual camera driver. Run: sudo mokutil --import "
                       "/var/lib/shim-signed/mok/MOK.der, choose a password, reboot and pick "
                       "'Enroll MOK'. See README → Problemen oplossen.")
    if "in use" in out.lower():
        return False, ("The virtual camera is in use by another program (OBS?). Close it and "
                       "turn the virtual camera off and on.")
    return False, f"Could not load v4l2loopback: {out or 'unknown error'}"


def protect_blur(frame, cells=24):
    """Heel beeld onherkenbaar maken (in place): sterk verkleinen en weer vergroten."""
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (cells, max(1, round(cells * h / w))), interpolation=cv2.INTER_AREA)
    frame[:] = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    return frame


try:
    import pyvirtualcam
    VIRTUAL_CAM_AVAILABLE = True
except ImportError:
    VIRTUAL_CAM_AVAILABLE = False

try:
    from PIL import Image, ImageTk
except ImportError:
    sys.exit("Pillow ontbreekt. Installeer de afhankelijkheden met: pip install -r requirements.txt")

APP_DIR = Path(__file__).resolve().parent

MODES = ["Overlay", "Pixelate", "Blur", "Black"]
DETECT_WIDTHS = {"Full": 0, "1280": 1280, "960": 960, "640": 640}

# Tracks die minder dan CONFIRM_HITS keer gezien zijn (waarschijnlijk
# valse detecties) verdwijnen na hooguit TENTATIVE_PERSISTENCE frames.
CONFIRM_HITS = 5
TENTATIVE_PERSISTENCE = 5
# Een kwijtgeraakt gezicht krijgt per gemist frame een iets groter masker,
# zodat het nog bedekt is als de persoon beweegt.
LOST_GROWTH_PER_FRAME = 0.015
LOST_GROWTH_MAX = 0.4
OVERLAY_CACHE_MAX = 128


class AnonymizerWorker:
    def __init__(self):
        self.running = False
        self.paused = False
        self.cap = None
        self.detector = None
        self.overlay = None
        self.overlay_cache = {}
        self.virtual_cam = None
        self._vcam_failed = False

        self.camera_id = 0
        self.scale_factor = 1.8
        self.confidence_threshold = 0.4
        self.min_face_size = 20
        self.persistence_frames = 60
        self.smart_persistence = True
        self.max_faces = 30
        self.mode = "Overlay"
        self.mirror_overlay = False
        self.protective_blur = False  # heel beeld vaag zolang er geen gezicht gevolgd wordt
        self.detect_width = 0
        self.show_debug = True
        self.force_1080p = True
        self.enable_virtual_cam = False

        self.faces = []
        self.next_id = 0
        self.frame_count = 0
        self.fps = 0
        self.last_fps_time = time.time()
        self.fps_counter = 0

        # Gedeeld met de GUI-thread
        self.lock = threading.Lock()
        self.latest_frame = None
        self.latest_frame_id = 0
        self.stats = {}
        self.messages = queue.Queue()

    # ------------------------------------------------------------ helpers
    def _status(self, text, level="info"):
        print(text)
        self.messages.put((level, text))

    def load_overlay(self, path):
        overlay = self._load_overlay(path)
        if overlay is None:
            return False
        self.overlay = overlay
        self.overlay_cache = {}  # oude geschaalde versies weggooien
        return True

    @staticmethod
    def _load_overlay(path):
        if not Path(path).exists():
            return None
        overlay = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if overlay is None:
            return None
        if overlay.ndim == 2:
            overlay = cv2.cvtColor(overlay, cv2.COLOR_GRAY2BGRA)
        elif overlay.shape[2] == 3:
            overlay = cv2.cvtColor(overlay, cv2.COLOR_BGR2BGRA)
        overlay = face_core.trim_transparent(overlay)  # logo vult het hele maskervlak
        print(f"Overlay loaded: {overlay.shape}")
        return overlay

    def _load_yunet(self, width, height):
        model_path = face_core.ensure_model(self._status)
        detector = cv2.FaceDetectorYN.create(str(model_path), "", (width, height))
        detector.setScoreThreshold(self.confidence_threshold)
        detector.setNMSThreshold(0.3)
        return detector

    def update_parameters(self, params):
        for key, attr in [('scale_factor', 'scale_factor'), ('confidence', 'confidence_threshold'),
                          ('min_face_size', 'min_face_size'), ('persistence', 'persistence_frames'),
                          ('smart_persistence', 'smart_persistence'), ('max_faces', 'max_faces'),
                          ('mode', 'mode'), ('mirror_overlay', 'mirror_overlay'), ('detect_width', 'detect_width'),
                          ('protective_blur', 'protective_blur'),
                          ('show_debug', 'show_debug'), ('force_1080p', 'force_1080p'),
                          ('enable_virtual_cam', 'enable_virtual_cam')]:
            if key in params:
                setattr(self, attr, params[key])
        if not self.enable_virtual_cam:
            self._vcam_failed = False  # opnieuw proberen bij volgende inschakeling
            self._vcam_repaired = False
        if self.detector is not None:
            self.detector.setScoreThreshold(self.confidence_threshold)

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused

    # ------------------------------------------------------ virtual camera
    def _open_virtual_cam(self, width, height, fps):
        backends = [None] if sys.platform.startswith("linux") else ["obs", None]
        last_error = None
        for backend in backends:
            try:
                kwargs = {"backend": backend} if backend else {}
                self.virtual_cam = pyvirtualcam.Camera(width=width, height=height, fps=fps, **kwargs)
                self._status(f"Virtual camera: {self.virtual_cam.device} ({width}x{height})")
                return
            except Exception as e:  # noqa: BLE001 - pyvirtualcam gooit diverse fouten
                last_error = e
        if sys.platform.startswith("linux") and not getattr(self, "_vcam_repaired", False) \
                and "v4l2" in str(last_error).lower():
            self._vcam_repaired = True  # maximaal één poging per sessie
            self._status("Virtual camera driver not loaded – asking for your password to load it…",
                         "error_soft")
            ok, why = repair_v4l2loopback()
            if ok:
                time.sleep(0.5)  # udev heeft even nodig om /dev/video10 aan te maken
                return self._open_virtual_cam(width, height, fps)
            self._vcam_failed = True
            self._status(f"Virtual camera: {why}", "error_soft")
            return
        self._vcam_failed = True
        self._status(f"Virtual camera error: {last_error}", "error_soft")

    def _sync_virtual_cam(self, frame, fps):
        if self.enable_virtual_cam and VIRTUAL_CAM_AVAILABLE:
            if self.virtual_cam is None and not self._vcam_failed:
                self._open_virtual_cam(frame.shape[1], frame.shape[0], fps)
            if self.virtual_cam is not None:
                try:
                    if (self.virtual_cam.width, self.virtual_cam.height) != (frame.shape[1], frame.shape[0]):
                        frame = cv2.resize(frame, (self.virtual_cam.width, self.virtual_cam.height))
                    self.virtual_cam.send(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                except Exception as e:  # noqa: BLE001
                    print(f"Virtual camera send error: {e}")
        elif self.virtual_cam is not None:
            self._close_virtual_cam()

    def _close_virtual_cam(self):
        if self.virtual_cam is not None:
            try:
                self.virtual_cam.close()
            finally:
                self.virtual_cam = None
                self._status("Virtual camera closed")

    # ----------------------------------------------------------- detection
    def detect_faces(self, frame):
        h, w = frame.shape[:2]
        scale = 1.0
        img = frame
        if self.detect_width and w > self.detect_width:
            scale = w / self.detect_width
            img = cv2.resize(frame, (self.detect_width, int(round(h / scale))), interpolation=cv2.INTER_AREA)

        self.detector.setInputSize((img.shape[1], img.shape[0]))
        _, detections = self.detector.detect(img)

        faces = []
        if detections is not None:
            for det in detections:
                # Niet naar binnen klemmen: een half buiten beeld vallend gezicht
                # zou anders verschuiven. Randgevallen handelt het tekenen af.
                x, y, bw, bh = (det[:4] * scale).astype(int)
                confidence = float(det[-1])
                if bw > self.min_face_size and bh > self.min_face_size:
                    faces.append((x, y, bw, bh, confidence))

        if len(faces) > self.max_faces:
            faces.sort(key=lambda f: f[4], reverse=True)
            faces = faces[:self.max_faces]
        return faces

    @staticmethod
    def iou(box1, box2):
        x1, y1, w1, h1 = box1
        x2, y2, w2, h2 = box2
        xi1, yi1 = max(x1, x2), max(y1, y2)
        xi2, yi2 = min(x1 + w1, x2 + w2), min(y1 + h1, y2 + h2)
        if xi2 <= xi1 or yi2 <= yi1:
            return 0.0
        inter = (xi2 - xi1) * (yi2 - yi1)
        union = w1 * h1 + w2 * h2 - inter
        return inter / union if union > 0 else 0.0

    def hungarian_match(self, detections, existing_faces):
        if not detections:
            return [], []
        if not existing_faces:
            return [], list(range(len(detections)))

        cost = np.ones((len(detections), len(existing_faces)))
        for i, det in enumerate(detections):
            for j, f in enumerate(existing_faces):
                cost[i, j] = 1 - self.iou(det[:4], (f['x'], f['y'], f['w'], f['h']))

        rows, cols = linear_sum_assignment(cost)
        matches = []
        unmatched = set(range(len(detections)))
        for i, j in zip(rows, cols):
            iou_val = 1 - cost[i, j]
            if iou_val > 0.25:
                matches.append((i, j, iou_val))
                unmatched.discard(i)
        return matches, sorted(unmatched)

    def update_faces(self, detections, frame_num):
        matches, unmatched = self.hungarian_match(detections, self.faces)

        for det_idx, face_idx, _ in matches:
            x, y, w, h, conf = detections[det_idx]
            self.faces[face_idx].update(x=x, y=y, w=w, h=h, confidence=conf, last_seen=frame_num)
            self.faces[face_idx]['hits'] += 1

        for det_idx in unmatched:
            x, y, w, h, conf = detections[det_idx]
            self.faces.append({'id': self.next_id, 'x': x, 'y': y, 'w': w, 'h': h,
                               'confidence': conf, 'first_seen': frame_num,
                               'last_seen': frame_num, 'hits': 1})
            self.next_id += 1

        def keep(f):
            limit = self.persistence_frames
            if self.smart_persistence and f['hits'] < CONFIRM_HITS:
                limit = min(limit, TENTATIVE_PERSISTENCE)
            return frame_num - f['last_seen'] <= limit

        self.faces = [f for f in self.faces if keep(f)]
        return self.faces

    # ---------------------------------------------------------- rendering
    def _mask_box(self, face):
        """Vierkant masker rond het gezicht, groeiend zolang het gezicht kwijt is."""
        lost = self.frame_count - face['last_seen']
        grow = 1 + min(LOST_GROWTH_MAX, LOST_GROWTH_PER_FRAME * lost)
        size = int(max(face['w'], face['h']) * self.scale_factor * grow)
        cx = face['x'] + face['w'] // 2
        cy = face['y'] + face['h'] // 2
        return cx - size // 2, cy - size // 2, size

    def _scaled_overlay(self, size):
        size = max(4, (size + 3) // 4 * 4)  # afronden beperkt het aantal cache-items
        key = (size, self.mirror_overlay)
        if key not in self.overlay_cache:
            if len(self.overlay_cache) >= OVERLAY_CACHE_MAX:
                self.overlay_cache.clear()
            oh, ow = self.overlay.shape[:2]
            ratio = size / max(oh, ow)  # beeldverhouding behouden
            tw, th = max(1, int(ow * ratio)), max(1, int(oh * ratio))
            canvas = np.zeros((size, size, 4), dtype=np.uint8)
            resized = cv2.resize(self.overlay, (tw, th), interpolation=cv2.INTER_AREA)
            oy, ox = (size - th) // 2, (size - tw) // 2
            canvas[oy:oy + th, ox:ox + tw] = resized
            if self.mirror_overlay:
                canvas = cv2.flip(canvas, 1)  # horizontaal spiegelen
            self.overlay_cache[key] = canvas
        return self.overlay_cache[key]

    def anonymize_face(self, frame, face):
        x0, y0, size = self._mask_box(face)
        if size < 4:
            return
        fh, fw = frame.shape[:2]
        dx0, dy0 = max(0, x0), max(0, y0)
        dx1, dy1 = min(fw, x0 + size), min(fh, y0 + size)
        if dx1 <= dx0 or dy1 <= dy0:
            return
        roi = frame[dy0:dy1, dx0:dx1]

        mode = self.mode
        if mode == "Overlay" and self.overlay is None:
            mode = "Pixelate"  # fail-safe: nooit een onbedekt gezicht

        if mode == "Overlay":
            ov = self._scaled_overlay(size)
            size_q = ov.shape[0]
            # ov kan door afronding een paar pixels groter zijn; centreren
            off = (size_q - size) // 2
            sx0, sy0 = dx0 - x0 + off, dy0 - y0 + off
            ov_vis = ov[sy0:sy0 + roi.shape[0], sx0:sx0 + roi.shape[1]]
            alpha = ov_vis[:, :, 3:4].astype(np.float32) / 255.0
            roi[:] = (roi.astype(np.float32) * (1 - alpha)
                      + ov_vis[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
        elif mode == "Pixelate":
            blocks = 8
            small = cv2.resize(roi, (blocks, blocks), interpolation=cv2.INTER_AREA)
            roi[:] = cv2.resize(small, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_NEAREST)
        elif mode == "Blur":
            k = max(31, (size // 3) | 1)
            roi[:] = cv2.GaussianBlur(roi, (k, k), 0)
        else:  # Black
            roi[:] = 0

    def draw_debug(self, frame):
        for face in self.faces:
            x, y, w, h = face['x'], face['y'], face['w'], face['h']
            lost = self.frame_count - face['last_seen']
            color = (0, 255, 0) if lost == 0 else (0, 165, 255)
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            label = f"{face['id']} {face['confidence']:.2f}" + (f" lost {lost}" if lost else "")
            cv2.putText(frame, label, (x, max(12, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        cv2.putText(frame, "DEBUG - preview only", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    def process_frame(self, frame, frame_num):
        """Detecteer, track en anonimiseer één frame. Geeft (stream, preview) terug."""
        self.frame_count = frame_num
        detections = self.detect_faces(frame)
        self.update_faces(detections, frame_num)
        if self.protective_blur and not self.faces:
            protect_blur(frame)  # geen gezicht gevonden: misschien wel een gemist
        for face in sorted(self.faces, key=lambda f: f['w'] * f['h']):
            self.anonymize_face(frame, face)
        preview = frame
        if self.show_debug:
            preview = frame.copy()
            self.draw_debug(preview)
        return frame, preview, len(detections)

    # ---------------------------------------------------------------- loop
    def run(self):
        self.running = True
        self.paused = False
        self.faces = []

        self.cap = cv2.VideoCapture(self.camera_id)
        if not self.cap.isOpened():
            self._status("ERROR: Cannot open camera!", "error")
            self.running = False
            return

        if self.force_1080p:
            # Veel USB-webcams leveren 1080p30 alleen als MJPG
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cam_fps = self.cap.get(cv2.CAP_PROP_FPS)
        cam_fps = int(cam_fps) if 5 <= cam_fps <= 120 else 30
        self._status(f"Camera: {width}x{height} @ {cam_fps}fps")

        try:
            self.detector = self._load_yunet(width, height)
        except Exception as e:  # noqa: BLE001
            self._status(f"ERROR: Cannot load face model: {e}", "error")
            self.cap.release()
            self.running = False
            return

        self._status("Streaming...")
        frame_num = 0
        while self.running:
            if self.paused:
                time.sleep(0.05)
                continue

            ret, frame = self.cap.read()
            if not ret:
                self._status("ERROR: Camera disconnected!", "error")
                break

            frame_num += 1
            self.fps_counter += 1
            now = time.time()
            if now - self.last_fps_time >= 1.0:
                self.fps = self.fps_counter / (now - self.last_fps_time)
                self.fps_counter = 0
                self.last_fps_time = now

            stream, preview, n_det = self.process_frame(frame, frame_num)
            self._sync_virtual_cam(stream, cam_fps)

            with self.lock:
                self.latest_frame = preview
                self.latest_frame_id = frame_num
                self.stats = {'frame': frame_num, 'faces': len(self.faces), 'detections': n_det,
                              'total_faces': self.next_id, 'fps': self.fps}

        self._close_virtual_cam()
        if self.cap:
            self.cap.release()
            self.cap = None
        self.running = False
        self._status("Stopped", "stopped")


class ControlsWindow:
    """Bedieningsvenster + apart previewvenster."""
    BG = '#2b2b2b'

    def __init__(self, root, worker):
        self.root = root
        self.worker = worker
        self.is_streaming = False
        self.update_thread = None
        self.last_rendered_id = 0

        self.setup_ui()

        for f in [APP_DIR / "overlay.png", APP_DIR / "assets" / "overlay.png",
                  Path("overlay.png"), Path("logo.png")]:
            if f.exists() and self.worker.load_overlay(f):
                self.overlay_status.config(text=f"✓ {f.name} loaded", fg="#88ff88")
                break
        else:
            self.overlay_status.config(text="No overlay (pixelate fallback)", fg="#ffcc66")

        if VIRTUAL_CAM_AVAILABLE:
            self.virtual_cam_status.config(text="✓ Available", fg="#88ff88")
        else:
            self.virtual_cam_status.config(text="✗ pyvirtualcam not installed", fg="#ff8888")

        self.update_params()
        self.root.after(15, self.poll)

    # --------------------------------------------------------------- UI
    def _frame(self, parent, text):
        f = tk.LabelFrame(parent, text=text, bg=self.BG, fg='white', font=('Arial', 10, 'bold'))
        f.pack(fill=tk.X, padx=5, pady=3)
        return f

    def _slider(self, parent, label, frm, to, init, fmt):
        row = tk.Frame(parent, bg=self.BG)
        row.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(row, text=label, bg=self.BG, fg='white', width=11, anchor='w').pack(side=tk.LEFT)
        s = tk.Scale(row, from_=frm, to=to, orient=tk.HORIZONTAL, bg=self.BG, fg='white',
                     highlightthickness=0, showvalue=False, command=self.update_params)
        s.set(init)
        s.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        lbl = tk.Label(row, text="", bg=self.BG, fg='white', width=6)
        lbl.pack(side=tk.RIGHT)
        s.value_label, s.fmt = lbl, fmt
        return s

    def _check(self, parent, text, value):
        var = tk.BooleanVar(value=value)
        tk.Checkbutton(parent, text=text, variable=var, bg=self.BG, fg='white', selectcolor=self.BG,
                       activebackground=self.BG, command=self.update_params).pack(anchor='w', padx=10, pady=1)
        return var

    def setup_ui(self):
        self.root.title("Face Anonymizer - Controls")
        self.root.configure(bg=self.BG)
        self.root.resizable(False, False)

        main = tk.Frame(self.root, bg=self.BG)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(main, text="🎭 Face Anonymizer", font=('Arial', 18, 'bold'),
                 bg=self.BG, fg='#4CAF50').pack(pady=5)
        self.status_label = tk.Label(main, text="Ready", bg=self.BG, fg='#88ff88',
                                     font=('Arial', 10), wraplength=380)
        self.status_label.pack(pady=2)

        # Stream
        stream = self._frame(main, "Stream Controls")
        row = tk.Frame(stream, bg=self.BG)
        row.pack(fill=tk.X, padx=5, pady=3)
        tk.Label(row, text="Camera:", bg=self.BG, fg='white').pack(side=tk.LEFT)
        self.camera_combo = ttk.Combobox(row, values=[str(i) for i in range(6)], width=4)
        self.camera_combo.set("0")
        self.camera_combo.pack(side=tk.LEFT, padx=5)

        btns = tk.Frame(stream, bg=self.BG)
        btns.pack(fill=tk.X, padx=5, pady=3)
        self.start_btn = tk.Button(btns, text="▶ Start", command=self.start_stream,
                                   bg='#4CAF50', fg='white', font=('Arial', 10), padx=15)
        self.start_btn.pack(side=tk.LEFT, padx=2)
        self.pause_btn = tk.Button(btns, text="⏸ Pause", command=self.toggle_pause, bg='#FF9800',
                                   fg='white', font=('Arial', 10), padx=15, state='disabled')
        self.pause_btn.pack(side=tk.LEFT, padx=2)
        self.stop_btn = tk.Button(btns, text="⏹ Stop", command=self.stop_stream, bg='#f44336',
                                  fg='white', font=('Arial', 10), padx=15, state='disabled')
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        # Anonymization
        anon = self._frame(main, "Anonymization")
        row = tk.Frame(anon, bg=self.BG)
        row.pack(fill=tk.X, padx=5, pady=3)
        tk.Label(row, text="Mode:", bg=self.BG, fg='white', width=6, anchor='w').pack(side=tk.LEFT)
        self.mode_combo = ttk.Combobox(row, values=MODES, width=10, state='readonly')
        self.mode_combo.set("Overlay")
        self.mode_combo.pack(side=tk.LEFT, padx=5)
        self.mode_combo.bind("<<ComboboxSelected>>", self.update_params)

        row = tk.Frame(anon, bg=self.BG)
        row.pack(fill=tk.X, padx=5, pady=3)
        tk.Button(row, text="📁 Select PNG", command=self.select_overlay,
                  bg='#4a4a4a', fg='white').pack(side=tk.LEFT)
        self.overlay_status = tk.Label(row, text="", bg=self.BG, fg='#ff8888')
        self.overlay_status.pack(side=tk.LEFT, padx=10)
        self.mirror_var = self._check(anon, "Mirror overlay (only if you also stream mirrored)", False)
        self.protect_var = self._check(anon, "Protective blur: blur everything while no face is found", False)
        self.scale_slider = self._slider(anon, "Scale:", 10, 35, 18, lambda v: f"{v / 10:.1f}x")

        # Detection
        det = self._frame(main, "Detection")
        self.conf_slider = self._slider(det, "Confidence:", 20, 95, 40, lambda v: f"{v / 100:.2f}")
        self.size_slider = self._slider(det, "Min Size:", 10, 100, 20, lambda v: f"{v}px")
        self.persist_slider = self._slider(det, "Persistence:", 3, 150, 60, lambda v: f"{v}f")
        self.smart_var = self._check(det, "Smart persistence (short hold for unconfirmed faces)", True)

        row = tk.Frame(det, bg=self.BG)
        row.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(row, text="Max Faces:", bg=self.BG, fg='white', width=11, anchor='w').pack(side=tk.LEFT)
        self.max_spin = tk.Spinbox(row, from_=1, to=100, width=5, bg='#3a3a3a', fg='white',
                                   relief=tk.FLAT, command=self.update_params)
        self.max_spin.delete(0, tk.END)
        self.max_spin.insert(0, "30")
        self.max_spin.pack(side=tk.LEFT, padx=5)
        self.max_spin.bind('<KeyRelease>', self.update_params)
        tk.Label(row, text="Detect at:", bg=self.BG, fg='white').pack(side=tk.LEFT, padx=(10, 2))
        self.detw_combo = ttk.Combobox(row, values=list(DETECT_WIDTHS), width=6, state='readonly')
        self.detw_combo.set("Full")
        self.detw_combo.pack(side=tk.LEFT)
        self.detw_combo.bind("<<ComboboxSelected>>", self.update_params)

        # Options
        opt = self._frame(main, "Options")
        self.debug_var = self._check(opt, "Show debug boxes (preview only, never streamed)", True)
        self.preview_var = self._check(opt, "Show preview window", True)
        self.res_var = self._check(opt, "Force 1080p (applies on next Start)", True)
        self.virtual_cam_var = self._check(opt, "Enable Virtual Camera (OBS)", False)
        row = tk.Frame(opt, bg=self.BG)
        row.pack(anchor='w', padx=25, pady=1)
        tk.Label(row, text="Virtual Cam:", bg=self.BG, fg='#888').pack(side=tk.LEFT)
        self.virtual_cam_status = tk.Label(row, text="Checking...", bg=self.BG, fg='#ff8888')
        self.virtual_cam_status.pack(side=tk.LEFT, padx=5)

        # Stats
        st = self._frame(main, "Statistics")
        self.total_faces_label = tk.Label(st, text="Total unique faces: 0", bg=self.BG, fg='white')
        self.total_faces_label.pack(anchor='w', padx=10, pady=1)
        self.frames_label = tk.Label(st, text="Frames processed: 0", bg=self.BG, fg='white')
        self.frames_label.pack(anchor='w', padx=10, pady=1)
        self.fps_label = tk.Label(st, text="FPS: 0", bg=self.BG, fg='white')
        self.fps_label.pack(anchor='w', padx=10, pady=1)

        self.create_video_window()

    def create_video_window(self):
        self.video_window = tk.Toplevel(self.root, class_="Face-anonymizer")
        self.video_window.title("Face Anonymizer - Video Preview")
        self.video_window.geometry("1280x720")
        self.video_window.minsize(640, 360)
        self.video_window.configure(bg='#1a1a1a')
        # Sluiten = verbergen; de stream naar de virtuele camera loopt door
        self.video_window.protocol("WM_DELETE_WINDOW", self.hide_preview)

        status = tk.Frame(self.video_window, bg=self.BG, height=25)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        status.pack_propagate(False)
        self.video_status = tk.Label(status, text="Live Preview", bg=self.BG, fg='#888')
        self.video_status.pack(side=tk.LEFT, padx=5)

        self.video_label = tk.Label(self.video_window, text="Waiting for stream...",
                                    bg='#1a1a1a', fg='#666', font=('Arial', 16))
        self.video_label.pack(fill=tk.BOTH, expand=True)

    def hide_preview(self):
        self.preview_var.set(False)
        self.update_params()

    # ---------------------------------------------------------- actions
    def select_overlay(self):
        path = filedialog.askopenfilename(title="Select Overlay PNG", filetypes=[("PNG Files", "*.png")])
        if path:
            if self.worker.load_overlay(path):
                self.overlay_status.config(text=f"✓ {Path(path).name}", fg="#88ff88")
            else:
                self.overlay_status.config(text="❌ Failed to load", fg="#ff8888")

    def update_params(self, *_):
        for s in (self.scale_slider, self.conf_slider, self.size_slider, self.persist_slider):
            s.value_label.config(text=s.fmt(s.get()))
        try:
            max_faces = max(1, int(self.max_spin.get()))
        except ValueError:
            max_faces = self.worker.max_faces  # half ingetypt getal negeren

        if self.preview_var.get():
            self.video_window.deiconify()
        else:
            self.video_window.withdraw()

        self.worker.update_parameters({
            'scale_factor': self.scale_slider.get() / 10.0,
            'confidence': self.conf_slider.get() / 100.0,
            'min_face_size': self.size_slider.get(),
            'persistence': self.persist_slider.get(),
            'smart_persistence': self.smart_var.get(),
            'max_faces': max_faces,
            'mode': self.mode_combo.get(),
            'mirror_overlay': self.mirror_var.get(),
            'protective_blur': self.protect_var.get(),
            'detect_width': DETECT_WIDTHS[self.detw_combo.get()],
            'show_debug': self.debug_var.get(),
            'force_1080p': self.res_var.get(),
            'enable_virtual_cam': self.virtual_cam_var.get(),
        })

    def start_stream(self):
        try:
            self.worker.camera_id = int(self.camera_combo.get())
        except ValueError:
            self.set_status("Invalid camera number", '#ff4444')
            return
        self.is_streaming = True
        self.last_rendered_id = 0
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.pause_btn.config(state='normal', text="⏸ Pause")
        self.camera_combo.config(state='disabled')
        self.update_params()
        self.update_thread = threading.Thread(target=self.worker.run, daemon=True)
        self.update_thread.start()

    def toggle_pause(self):
        if self.is_streaming:
            paused = self.worker.toggle_pause()
            self.pause_btn.config(text="▶ Resume" if paused else "⏸ Pause")

    def stop_stream(self):
        self.worker.running = False
        self.worker.paused = False
        if self.update_thread and self.update_thread is not threading.current_thread():
            self.update_thread.join(timeout=2)
        self._reset_ui()

    def _reset_ui(self):
        self.is_streaming = False
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.pause_btn.config(state='disabled', text="⏸ Pause")
        self.camera_combo.config(state='normal')
        self.video_label.config(image='', text="Stream ended")
        self.video_label.image = None

    def set_status(self, text, color='#88ff88'):
        self.status_label.config(text=text, fg=color)

    # ------------------------------------------------- GUI polling loop
    def poll(self):
        """Draait in de GUI-thread: verwerkt statusberichten en toont het nieuwste frame.
        Zo stapelen er nooit frames op als de preview trager is dan de camera."""
        try:
            while True:
                level, text = self.worker.messages.get_nowait()
                if level == "error":
                    self.set_status(text, '#ff4444')
                    self._reset_ui()
                elif level == "error_soft":
                    self.set_status(text, '#ffcc66')
                elif level == "stopped":
                    if not self.status_label.cget('text').startswith("ERROR"):
                        self.set_status("Stopped", '#888')
                else:
                    self.set_status(text)
        except queue.Empty:
            pass

        if self.is_streaming:
            with self.worker.lock:
                frame_id = self.worker.latest_frame_id
                frame = self.worker.latest_frame
                stats = dict(self.worker.stats)
            if frame is not None and frame_id != self.last_rendered_id:
                self.last_rendered_id = frame_id
                if self.preview_var.get():
                    self.update_video(frame, stats)
                self.update_stats(stats)

        self.root.after(15, self.poll)

    def update_video(self, frame, stats):
        lw, lh = self.video_label.winfo_width(), self.video_label.winfo_height()
        h, w = frame.shape[:2]
        if lw > 10 and lh > 10:
            scale = min(lw / w, lh / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            frame = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        self.video_label.config(image=photo, text="")
        self.video_label.image = photo
        self.video_status.config(text=f"Live Preview | FPS: {stats.get('fps', 0):.1f} | "
                                      f"Faces: {stats.get('faces', 0)}")

    def update_stats(self, stats):
        self.fps_label.config(text=f"FPS: {stats.get('fps', 0):.1f}")
        self.total_faces_label.config(text=f"Total unique faces: {stats.get('total_faces', 0)}")
        self.frames_label.config(text=f"Frames processed: {stats.get('frame', 0)}")

    def on_closing(self):
        self.stop_stream()
        self.root.destroy()


def main():
    # className koppelt het venster aan de snelkoppeling (StartupWMClass) in het dock
    root = tk.Tk(className="face-anonymizer")
    icon = APP_DIR / "assets" / "icon.png"
    if icon.exists():
        try:
            root.iconphoto(True, tk.PhotoImage(file=str(icon)))
        except tk.TclError:
            pass
    controls = ControlsWindow(root, AnonymizerWorker())
    root.protocol("WM_DELETE_WINDOW", controls.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
