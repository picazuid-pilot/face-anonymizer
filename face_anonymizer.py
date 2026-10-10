#!/usr/bin/env python3
"""
FACE ANONYMIZER - Dual Window Fixed
- Overlay properly displayed on top
- Debug box optional (under overlay)
- Separate windows (no shrinking)
"""

import tkinter as tk
from tkinter import ttk, filedialog
import cv2
import numpy as np
from pathlib import Path
import urllib.request
import time
import threading
from scipy.optimize import linear_sum_assignment
import sys
import os

try:
    import pyvirtualcam
    VIRTUAL_CAM_AVAILABLE = True
except ImportError:
    VIRTUAL_CAM_AVAILABLE = False

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    import subprocess
    subprocess.check_call(["pip", "install", "Pillow", "--break-system-packages"])
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True

class AnonymizerWorker:
    def __init__(self):
        self.running = False
        self.paused = False
        self.cap = None
        self.detector = None
        self.overlay = None
        self.overlay_cache = {}
        self.virtual_cam = None
        
        self.camera_id = 0
        self.scale_factor = 1.8
        self.confidence_threshold = 0.4
        self.min_face_size = 20
        self.persistence_frames = 60
        self.max_faces = 30
        self.show_debug = True
        self.force_1080p = True
        self.enable_virtual_cam = False
        self.virtual_cam_resolution = (1280, 720)
        
        self.faces = []
        self.next_id = 0
        self.frame_count = 0
        self.overlay_count = 0
        self.fps = 0
        self.last_fps_time = 0
        self.fps_counter = 0
        
        self.current_frame = None
        self.stats = {}
    
    def load_overlay(self, path):
        self.overlay = self._load_overlay(path)
        return self.overlay is not None
    
    def _load_overlay(self, path):
        if Path(path).exists():
            overlay = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if overlay is not None:
                print(f"Overlay loaded: {overlay.shape}")
                if overlay.shape[2] == 3:
                    b, g, r = cv2.split(overlay)
                    alpha = np.ones(b.shape, dtype=b.dtype) * 255
                    overlay = cv2.merge([b, g, r, alpha])
                    print("Added alpha channel")
                return overlay
        return None
    
    def _load_yunet(self, width, height):
        model_dir = Path.home() / ".cache" / "yunet"
        model_dir.mkdir(parents=True, exist_ok=True)
        
        model_path = model_dir / "face_detection_yunet_2023mar.onnx"
        
        if not model_path.exists():
            print("Downloading YuNet model...")
            url = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
            urllib.request.urlretrieve(url, model_path)
            print("Download complete!")
        
        detector = cv2.FaceDetectorYN.create(str(model_path), "", (width, height))
        detector.setScoreThreshold(self.confidence_threshold)
        detector.setNMSThreshold(0.3)
        return detector
    
    def update_parameters(self, params):
        self.scale_factor = params.get('scale_factor', self.scale_factor)
        self.confidence_threshold = params.get('confidence', self.confidence_threshold)
        self.min_face_size = params.get('min_face_size', self.min_face_size)
        self.persistence_frames = params.get('persistence', self.persistence_frames)
        self.max_faces = params.get('max_faces', self.max_faces)
        self.show_debug = params.get('show_debug', self.show_debug)
        self.force_1080p = params.get('force_1080p', self.force_1080p)
        self.enable_virtual_cam = params.get('enable_virtual_cam', self.enable_virtual_cam)
        
        if self.detector is not None:
            self.detector.setScoreThreshold(self.confidence_threshold)
    
    def init_virtual_cam(self):
        if not VIRTUAL_CAM_AVAILABLE:
            return False
        
        if self.virtual_cam is None:
            try:
                self.virtual_cam = pyvirtualcam.Camera(
                    width=self.virtual_cam_resolution[0],
                    height=self.virtual_cam_resolution[1],
                    fps=30,
                    backend='obs'
                )
                return True
            except Exception as e:
                print(f"Virtual camera error: {e}")
                return False
        return True
    
    def send_to_virtual_cam(self, frame):
        if self.virtual_cam is not None and self.enable_virtual_cam:
            try:
                if frame.shape[:2] != (self.virtual_cam_resolution[1], self.virtual_cam_resolution[0]):
                    frame_resized = cv2.resize(frame, self.virtual_cam_resolution)
                else:
                    frame_resized = frame
                frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                self.virtual_cam.send(frame_rgb)
                self.virtual_cam.sleep_until_next_frame()
            except Exception as e:
                pass
    
    def detect_faces(self, frame):
        self.detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, detections = self.detector.detect(frame)
        
        faces = []
        if detections is not None:
            for det in detections:
                x, y, w, h = det[:4].astype(int)
                confidence = det[-1]
                x = max(0, min(x, frame.shape[1] - w))
                y = max(0, min(y, frame.shape[0] - h))
                
                if w > self.min_face_size and h > self.min_face_size:
                    faces.append((x, y, w, h, confidence))
        
        if len(faces) > self.max_faces:
            faces.sort(key=lambda f: f[4], reverse=True)
            faces = faces[:self.max_faces]
        
        return faces
    
    def iou(self, box1, box2):
        x1, y1, w1, h1 = box1
        x2, y2, w2, h2 = box2
        
        xi1 = max(x1, x2)
        yi1 = max(y1, y2)
        xi2 = min(x1 + w1, x2 + w2)
        yi2 = min(y1 + h1, y2 + h2)
        
        if xi2 <= xi1 or yi2 <= yi1:
            return 0
        
        intersection = (xi2 - xi1) * (yi2 - yi1)
        union = w1 * h1 + w2 * h2 - intersection
        return intersection / union if union > 0 else 0
    
    def hungarian_match(self, detections, existing_faces):
        if not detections:
            return [], []
        
        if not existing_faces:
            return [], list(range(len(detections)))
        
        num_detections = len(detections)
        num_faces = len(existing_faces)
        
        cost_matrix = np.zeros((num_detections, num_faces))
        
        for i, det in enumerate(detections):
            dx, dy, dw, dh = det[:4]
            for j, face in enumerate(existing_faces):
                fx, fy, fw, fh = face['x'], face['y'], face['w'], face['h']
                iou_val = self.iou((dx, dy, dw, dh), (fx, fy, fw, fh))
                cost_matrix[i, j] = 1 - iou_val
        
        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        
        matches = []
        unmatched_detections = list(range(num_detections))
        
        for i, j in zip(row_ind, col_ind):
            iou_val = 1 - cost_matrix[i, j]
            if iou_val > 0.25:
                matches.append((i, j, iou_val))
                if i in unmatched_detections:
                    unmatched_detections.remove(i)
        
        return matches, unmatched_detections
    
    def update_faces(self, detections, frame_num):
        matches, unmatched_detections = self.hungarian_match(detections, self.faces)
        
        for det_idx, face_idx, iou_val in matches:
            x, y, w, h, conf = detections[det_idx]
            self.faces[face_idx]['x'] = x
            self.faces[face_idx]['y'] = y
            self.faces[face_idx]['w'] = w
            self.faces[face_idx]['h'] = h
            self.faces[face_idx]['confidence'] = conf
            self.faces[face_idx]['last_seen'] = frame_num
        
        for det_idx in unmatched_detections:
            x, y, w, h, conf = detections[det_idx]
            new_face = {
                'id': self.next_id,
                'x': x,
                'y': y,
                'w': w,
                'h': h,
                'confidence': conf,
                'first_seen': frame_num,
                'last_seen': frame_num,
            }
            self.faces.append(new_face)
            print(f"New face #{self.next_id}: ({x},{y}) size={w}x{h}")
            self.next_id += 1
        
        self.faces = [f for f in self.faces if frame_num - f['last_seen'] <= self.persistence_frames]
        return self.faces
    
    def overlay_face(self, frame, face):
        """Overlay PNG on face - debug box drawn first, then overlay on top"""
        try:
            x, y, w, h = face['x'], face['y'], face['w'], face['h']
            
            if w < 15 or h < 15:
                return frame
            
            # 1. Draw debug box FIRST (underneath overlay)
            if self.show_debug:
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                frames_since = self.frame_count - face['last_seen']
                if frames_since > 0:
                    status = f"{face['id']} (lost {frames_since})"
                    color = (0, 200, 100)
                else:
                    status = f"{face['id']}"
                    color = (0, 255, 0)
                cv2.putText(frame, status, (x, y-5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            
            # 2. THEN apply overlay on top
            if self.overlay is not None:
                overlay_size = int(max(w, h) * self.scale_factor)
                
                cx = x + w // 2
                cy = y + h // 2
                
                overlay_x = cx - overlay_size // 2
                overlay_y = cy - overlay_size // 2
                
                key = (overlay_size, overlay_size)
                if key not in self.overlay_cache:
                    self.overlay_cache[key] = cv2.resize(self.overlay, key)
                
                ov = self.overlay_cache[key]
                
                # Handle edges
                src_x = max(0, -overlay_x)
                src_y = max(0, -overlay_y)
                dst_x = max(0, overlay_x)
                dst_y = max(0, overlay_y)
                
                visible_w = min(overlay_size - src_x, frame.shape[1] - dst_x)
                visible_h = min(overlay_size - src_y, frame.shape[0] - dst_y)
                
                if visible_w > 0 and visible_h > 0:
                    ov_visible = ov[src_y:src_y+visible_h, src_x:src_x+visible_w]
                    alpha = ov_visible[:, :, 3] / 255.0
                    alpha_3ch = alpha[..., np.newaxis]
                    roi = frame[dst_y:dst_y+visible_h, dst_x:dst_x+visible_w]
                    roi[:] = (roi.astype(np.float32) * (1 - alpha_3ch) + 
                              ov_visible[:, :, :3].astype(np.float32) * alpha_3ch).astype(np.uint8)
            
            return frame
        except Exception as e:
            print(f"Overlay error: {e}")
            return frame
    
    def run(self, callback):
        self.running = True
        self.paused = False
        
        self.cap = cv2.VideoCapture(self.camera_id)
        if not self.cap.isOpened():
            callback("ERROR: Cannot open camera!", None)
            return
        
        if self.force_1080p:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        callback(f"Camera: {width}x{height}", None)
        
        self.detector = self._load_yunet(width, height)
        
        if self.enable_virtual_cam:
            self.init_virtual_cam()
        
        frame_num = 0
        callback("Streaming...", None)
        
        while self.running:
            if self.paused:
                time.sleep(0.05)
                continue
            
            ret, frame = self.cap.read()
            if not ret:
                callback("Camera disconnected!", None)
                break
            
            frame_num += 1
            self.frame_count = frame_num
            
            self.fps_counter += 1
            if time.time() - self.last_fps_time >= 1.0:
                self.fps = self.fps_counter
                self.fps_counter = 0
                self.last_fps_time = time.time()
            
            detections = self.detect_faces(frame)
            self.update_faces(detections, frame_num)
            
            # Sort by size for z-ordering
            sorted_faces = sorted(self.faces, key=lambda f: f['w'] * f['h'])
            
            overlay_count = 0
            for face in sorted_faces:
                frame = self.overlay_face(frame, face)
                overlay_count += 1
            
            self.overlay_count = overlay_count
            
            if self.enable_virtual_cam and self.virtual_cam is not None:
                self.send_to_virtual_cam(frame)
            
            stats = {
                'frame': frame_num,
                'faces': len(self.faces),
                'detections': len(detections),
                'overlays': overlay_count,
                'total_faces': self.next_id,
                'fps': self.fps
            }
            self.stats = stats
            
            callback(None, frame)
        
        if self.virtual_cam is not None:
            self.virtual_cam.close()
            self.virtual_cam = None
        
        if self.cap:
            self.cap.release()
            self.cap = None
        callback("Stopped", None)


class ControlsWindow:
    """Separate window for controls"""
    def __init__(self, root, worker):
        self.root = root
        self.worker = worker
        self.is_streaming = False
        self.video_window = None
        
        self.setup_ui()
        
        # Try to load default overlay
        overlay_files = ["overlay.png", "track.png", "logo.png"]
        for f in overlay_files:
            if Path(f).exists():
                self.worker.load_overlay(f)
                self.overlay_status.config(text=f"✓ {f} loaded", fg="#88ff88")
                break
        else:
            self.overlay_status.config(text="No overlay loaded", fg="#ff8888")
        
        if VIRTUAL_CAM_AVAILABLE:
            self.virtual_cam_status.config(text="✓ Available", fg="#88ff88")
        else:
            self.virtual_cam_status.config(text="✗ Not installed", fg="#ff8888")
    
    def setup_ui(self):
        self.root.title("Face Anonymizer - Controls")
        self.root.geometry("420x780")
        self.root.minsize(400, 700)
        self.root.maxsize(450, 800)
        self.root.configure(bg='#2b2b2b')
        self.root.resizable(False, False)
        
        main_frame = tk.Frame(self.root, bg='#2b2b2b')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Title
        title = tk.Label(main_frame, text="🎭 Face Anonymizer", 
                        font=('Arial', 18, 'bold'), bg='#2b2b2b', fg='#4CAF50')
        title.pack(pady=5)
        
        # Status
        self.status_label = tk.Label(main_frame, text="Ready", 
                                    bg='#2b2b2b', fg='#88ff88', font=('Arial', 10))
        self.status_label.pack(pady=2)
        
        # --- Stream Controls ---
        stream_frame = tk.LabelFrame(main_frame, text="Stream Controls", 
                                     bg='#2b2b2b', fg='white', font=('Arial', 10, 'bold'))
        stream_frame.pack(fill=tk.X, padx=5, pady=3)
        
        cam_frame = tk.Frame(stream_frame, bg='#2b2b2b')
        cam_frame.pack(fill=tk.X, padx=5, pady=3)
        tk.Label(cam_frame, text="Camera:", bg='#2b2b2b', fg='white').pack(side=tk.LEFT)
        self.camera_combo = ttk.Combobox(cam_frame, values=["0", "1", "2", "3", "4"], width=5)
        self.camera_combo.set("0")
        self.camera_combo.pack(side=tk.LEFT, padx=5)
        
        btn_frame = tk.Frame(stream_frame, bg='#2b2b2b')
        btn_frame.pack(fill=tk.X, padx=5, pady=3)
        
        self.start_btn = tk.Button(btn_frame, text="▶ Start", command=self.start_stream,
                                  bg='#4CAF50', fg='white', font=('Arial', 10), padx=15)
        self.start_btn.pack(side=tk.LEFT, padx=2)
        
        self.pause_btn = tk.Button(btn_frame, text="⏸ Pause", command=self.toggle_pause,
                                  bg='#FF9800', fg='white', font=('Arial', 10), padx=15, state='disabled')
        self.pause_btn.pack(side=tk.LEFT, padx=2)
        
        self.stop_btn = tk.Button(btn_frame, text="⏹ Stop", command=self.stop_stream,
                                 bg='#f44336', fg='white', font=('Arial', 10), padx=15, state='disabled')
        self.stop_btn.pack(side=tk.LEFT, padx=2)
        
        # --- Overlay Controls ---
        overlay_frame = tk.LabelFrame(main_frame, text="Overlay", 
                                     bg='#2b2b2b', fg='white', font=('Arial', 10, 'bold'))
        overlay_frame.pack(fill=tk.X, padx=5, pady=3)
        
        overlay_btn_frame = tk.Frame(overlay_frame, bg='#2b2b2b')
        overlay_btn_frame.pack(fill=tk.X, padx=5, pady=3)
        
        self.overlay_btn = tk.Button(overlay_btn_frame, text="📁 Select PNG", command=self.select_overlay,
                                    bg='#4a4a4a', fg='white')
        self.overlay_btn.pack(side=tk.LEFT)
        
        self.overlay_status = tk.Label(overlay_btn_frame, text="No overlay loaded", 
                                      bg='#2b2b2b', fg='#ff8888')
        self.overlay_status.pack(side=tk.LEFT, padx=10)
        
        # Scale slider
        scale_frame = tk.Frame(overlay_frame, bg='#2b2b2b')
        scale_frame.pack(fill=tk.X, padx=5, pady=3)
        tk.Label(scale_frame, text="Scale:", bg='#2b2b2b', fg='white', width=6).pack(side=tk.LEFT)
        self.scale_slider = tk.Scale(scale_frame, from_=10, to=35, orient=tk.HORIZONTAL,
                                    bg='#2b2b2b', fg='white', highlightthickness=0,
                                    command=self.update_params)
        self.scale_slider.set(18)
        self.scale_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.scale_label = tk.Label(scale_frame, text="1.8x", bg='#2b2b2b', fg='white', width=5)
        self.scale_label.pack(side=tk.RIGHT)
        
        # --- Detection Parameters ---
        detect_frame = tk.LabelFrame(main_frame, text="Detection", 
                                    bg='#2b2b2b', fg='white', font=('Arial', 10, 'bold'))
        detect_frame.pack(fill=tk.X, padx=5, pady=3)
        
        # Confidence
        conf_frame = tk.Frame(detect_frame, bg='#2b2b2b')
        conf_frame.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(conf_frame, text="Confidence:", bg='#2b2b2b', fg='white', width=10, anchor='w').pack(side=tk.LEFT)
        self.conf_slider = tk.Scale(conf_frame, from_=20, to=80, orient=tk.HORIZONTAL,
                                   bg='#2b2b2b', fg='white', highlightthickness=0,
                                   command=self.update_params)
        self.conf_slider.set(40)
        self.conf_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.conf_label = tk.Label(conf_frame, text="0.40", bg='#2b2b2b', fg='white', width=5)
        self.conf_label.pack(side=tk.RIGHT)
        
        # Min Size
        size_frame = tk.Frame(detect_frame, bg='#2b2b2b')
        size_frame.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(size_frame, text="Min Size:", bg='#2b2b2b', fg='white', width=10, anchor='w').pack(side=tk.LEFT)
        self.size_slider = tk.Scale(size_frame, from_=10, to=100, orient=tk.HORIZONTAL,
                                   bg='#2b2b2b', fg='white', highlightthickness=0,
                                   command=self.update_params)
        self.size_slider.set(20)
        self.size_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.size_label = tk.Label(size_frame, text="20px", bg='#2b2b2b', fg='white', width=5)
        self.size_label.pack(side=tk.RIGHT)
        
        # Persistence
        persist_frame = tk.Frame(detect_frame, bg='#2b2b2b')
        persist_frame.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(persist_frame, text="Persistence:", bg='#2b2b2b', fg='white', width=10, anchor='w').pack(side=tk.LEFT)
        self.persist_slider = tk.Scale(persist_frame, from_=5, to=150, orient=tk.HORIZONTAL,
                                      bg='#2b2b2b', fg='white', highlightthickness=0,
                                      command=self.update_params)
        self.persist_slider.set(60)
        self.persist_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.persist_label = tk.Label(persist_frame, text="60f", bg='#2b2b2b', fg='white', width=5)
        self.persist_label.pack(side=tk.RIGHT)
        
        # Max Faces
        max_frame = tk.Frame(detect_frame, bg='#2b2b2b')
        max_frame.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(max_frame, text="Max Faces:", bg='#2b2b2b', fg='white', width=10, anchor='w').pack(side=tk.LEFT)
        self.max_spin = tk.Spinbox(max_frame, from_=5, to=100, width=5,
                                  bg='#3a3a3a', fg='white', relief=tk.FLAT)
        self.max_spin.delete(0, tk.END)
        self.max_spin.insert(0, "30")
        self.max_spin.pack(side=tk.LEFT, padx=5)
        self.max_spin.bind('<KeyRelease>', self.update_params)
        
        # --- Options ---
        options_frame = tk.LabelFrame(main_frame, text="Options", 
                                     bg='#2b2b2b', fg='white', font=('Arial', 10, 'bold'))
        options_frame.pack(fill=tk.X, padx=5, pady=3)
        
        self.debug_var = tk.BooleanVar(value=True)
        self.debug_check = tk.Checkbutton(options_frame, text="Show Debug Box (under overlay)",
                                         variable=self.debug_var, bg='#2b2b2b', fg='white',
                                         selectcolor='#2b2b2b', command=self.update_params)
        self.debug_check.pack(anchor='w', padx=10, pady=1)
        
        self.res_var = tk.BooleanVar(value=True)
        self.res_check = tk.Checkbutton(options_frame, text="Force 1080p",
                                       variable=self.res_var, bg='#2b2b2b', fg='white',
                                       selectcolor='#2b2b2b', command=self.update_params)
        self.res_check.pack(anchor='w', padx=10, pady=1)
        
        self.virtual_cam_var = tk.BooleanVar(value=False)
        self.virtual_cam_check = tk.Checkbutton(options_frame, text="Enable Virtual Camera (OBS)",
                                               variable=self.virtual_cam_var, bg='#2b2b2b', fg='white',
                                               selectcolor='#2b2b2b', command=self.update_params)
        self.virtual_cam_check.pack(anchor='w', padx=10, pady=1)
        
        virtual_cam_status_frame = tk.Frame(options_frame, bg='#2b2b2b')
        virtual_cam_status_frame.pack(anchor='w', padx=25, pady=1)
        tk.Label(virtual_cam_status_frame, text="Virtual Cam:", bg='#2b2b2b', fg='#888').pack(side=tk.LEFT)
        self.virtual_cam_status = tk.Label(virtual_cam_status_frame, text="Checking...", bg='#2b2b2b', fg='#ff8888')
        self.virtual_cam_status.pack(side=tk.LEFT, padx=5)
        
        # --- Statistics ---
        stats_frame = tk.LabelFrame(main_frame, text="Statistics", 
                                   bg='#2b2b2b', fg='white', font=('Arial', 10, 'bold'))
        stats_frame.pack(fill=tk.X, padx=5, pady=3)
        
        self.total_faces_label = tk.Label(stats_frame, text="Total unique faces: 0", 
                                         bg='#2b2b2b', fg='white')
        self.total_faces_label.pack(anchor='w', padx=10, pady=1)
        
        self.frames_label = tk.Label(stats_frame, text="Frames processed: 0", 
                                    bg='#2b2b2b', fg='white')
        self.frames_label.pack(anchor='w', padx=10, pady=1)
        
        self.fps_label = tk.Label(stats_frame, text="FPS: 0", bg='#2b2b2b', fg='white')
        self.fps_label.pack(anchor='w', padx=10, pady=1)
        
        # Create video window
        self.create_video_window()
        
        # Update thread
        self.update_thread = None
        self.running = False
    
    def create_video_window(self):
        """Create the separate video preview window"""
        self.video_window = tk.Toplevel(self.root)
        self.video_window.title("Face Anonymizer - Video Preview")
        self.video_window.geometry("1280x720")
        self.video_window.minsize(640, 360)
        self.video_window.configure(bg='#1a1a1a')
        
        self.video_label = tk.Label(self.video_window, text="Waiting for stream...", 
                                    bg='#1a1a1a', fg='#666', font=('Arial', 16))
        self.video_label.pack(fill=tk.BOTH, expand=True)
        
        # Status at bottom
        status_frame = tk.Frame(self.video_window, bg='#2b2b2b', height=25)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        status_frame.pack_propagate(False)
        
        self.video_status = tk.Label(status_frame, text="Live Preview | FPS: 0", 
                                     bg='#2b2b2b', fg='#888')
        self.video_status.pack(side=tk.LEFT, padx=5)
    
    def select_overlay(self):
        file_path = filedialog.askopenfilename(title="Select Overlay PNG", filetypes=[("PNG Files", "*.png")])
        if file_path:
            if self.worker.load_overlay(file_path):
                self.overlay_status.config(text=f"✓ {Path(file_path).name}", fg="#88ff88")
            else:
                self.overlay_status.config(text="❌ Failed to load", fg="#ff8888")
    
    def update_params(self, *args):
        scale = self.scale_slider.get() / 10.0
        self.scale_label.config(text=f"{scale:.1f}x")
        
        conf = self.conf_slider.get() / 100.0
        self.conf_label.config(text=f"{conf:.2f}")
        
        size = self.size_slider.get()
        self.size_label.config(text=f"{size}px")
        
        persist = self.persist_slider.get()
        self.persist_label.config(text=f"{persist}f")
        
        params = {
            'scale_factor': scale,
            'confidence': conf,
            'min_face_size': size,
            'persistence': persist,
            'max_faces': int(self.max_spin.get()),
            'show_debug': self.debug_var.get(),
            'force_1080p': self.res_var.get(),
            'enable_virtual_cam': self.virtual_cam_var.get()
        }
        
        if self.is_streaming:
            self.worker.update_parameters(params)
    
    def start_stream(self):
        camera_id = int(self.camera_combo.get())
        self.is_streaming = True
        self.worker.camera_id = camera_id
        
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.pause_btn.config(state='normal')
        self.camera_combo.config(state='disabled')
        
        self.update_params()
        
        self.running = True
        self.update_thread = threading.Thread(target=self.process_frames)
        self.update_thread.daemon = True
        self.update_thread.start()
    
    def process_frames(self):
        def callback(status, frame):
            if status and "ERROR" in status:
                self.status_label.config(text=status, fg='#ff4444')
                self.root.after(0, self.stop_stream)
                return
            
            if status:
                self.root.after(0, lambda: self.status_label.config(text=status, fg='#88ff88'))
            
            if frame is not None:
                self.root.after(0, lambda f=frame: self.update_video(f))
                self.root.after(0, lambda: self.update_stats(self.worker.stats))
        
        self.worker.run(callback)
        self.running = False
    
    def update_video(self, frame):
        """Update the video preview window"""
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            
            label_width = self.video_label.winfo_width()
            label_height = self.video_label.winfo_height()
            
            if label_width > 10 and label_height > 10:
                scale = min(label_width / w, label_height / h)
                new_w = int(w * scale)
                new_h = int(h * scale)
                if new_w > 0 and new_h > 0:
                    rgb = cv2.resize(rgb, (new_w, new_h))
                    h, w = new_h, new_w
            
            image = Image.fromarray(rgb)
            photo = ImageTk.PhotoImage(image)
            self.video_label.config(image=photo)
            self.video_label.image = photo
            
            # Update status
            self.video_status.config(text=f"Live Preview | FPS: {self.worker.fps:.1f} | Faces: {len(self.worker.faces)}")
        except Exception as e:
            pass
    
    def update_stats(self, stats):
        if stats:
            self.fps_label.config(text=f"FPS: {stats.get('fps', 0):.1f}")
            self.total_faces_label.config(text=f"Total unique faces: {stats.get('total_faces', 0)}")
            self.frames_label.config(text=f"Frames processed: {stats.get('frame', 0)}")
    
    def toggle_pause(self):
        if self.is_streaming:
            paused = self.worker.pause_stream()
            self.pause_btn.config(text="▶ Resume" if paused else "⏸ Pause")
    
    def stop_stream(self):
        self.is_streaming = False
        self.worker.running = False
        self.worker.paused = False
        
        if self.update_thread:
            self.update_thread.join(timeout=1)
        
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.pause_btn.config(state='disabled')
        self.pause_btn.config(text="⏸ Pause")
        self.camera_combo.config(state='normal')
        
        self.status_label.config(text="Stopped", fg='#888')
        self.video_label.config(image='', text="Stream ended")
        
        self.running = False
    
    def on_closing(self):
        """Handle window close"""
        self.stop_stream()
        if self.video_window:
            self.video_window.destroy()
        self.root.destroy()


def main():
    root = tk.Tk()
    worker = AnonymizerWorker()
    controls = ControlsWindow(root, worker)
    
    root.protocol("WM_DELETE_WINDOW", controls.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
