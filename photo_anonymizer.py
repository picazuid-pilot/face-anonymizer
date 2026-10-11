#!/usr/bin/env python3
"""
FOTO ANONYMIZER
Anonimiseert alle gezichten in een map met foto's.

- Originelen blijven onaangeroerd; resultaten gaan naar een aparte map
- Overlay (bijv. een logo), pixels, blur of zwart vlak
- Metadata (GPS-locatie, camera, datum) wordt verwijderd
- Na afloop kun je elke foto nalopen en maskers toevoegen of weghalen

Gebruik:
    python photo_anonymizer.py                       # venster
    python photo_anonymizer.py BRON DOEL [opties]    # zonder venster (zie --help)
"""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

import face_core as fc

try:  # iPhone-foto's (HEIC)
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC = True
except ImportError:
    HEIC = False

APP_DIR = Path(__file__).resolve().parent
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"} | ({".heic", ".heif"} if HEIC else set())
ACCURACY_LABELS = {"Snel": "fast", "Normaal": "normal", "Grondig": "thorough"}
MODE_LABELS = {"Overlay": "overlay", "Pixels": "pixelate", "Blur": "blur", "Zwart": "black"}
JPEG_QUALITY = 92


# ------------------------------------------------------------------ bestanden
def find_images(src: Path, recursive: bool):
    pattern = "**/*" if recursive else "*"
    files = [p for p in src.glob(pattern)
             if p.is_file() and p.suffix.lower() in EXTENSIONS and not p.name.startswith(".")]
    return sorted(files, key=lambda p: str(p).lower())


def output_path(src_root: Path, dst_root: Path, file: Path) -> Path:
    rel = file.relative_to(src_root)
    if rel.suffix.lower() in {".heic", ".heif"}:
        rel = rel.with_suffix(".jpg")  # HEIC kan bijna niemand openen
    return dst_root / rel


def load_image(path: Path) -> np.ndarray:
    """Leest een foto als BGR, rechtop gezet volgens de EXIF-oriëntatie."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            # Transparantie platslaan op wit
            if "A" in im.getbands():
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[3])
                im = bg
            else:
                im = im.convert("RGB")
        arr = np.asarray(im.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def save_image(img: np.ndarray, path: Path):
    """Slaat op zonder metadata (geen EXIF/GPS)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    ext = path.suffix.lower()
    tmp = path.with_name(path.name + ".part")
    if ext in (".jpg", ".jpeg"):
        im.save(tmp, "JPEG", quality=JPEG_QUALITY, optimize=True)
    elif ext == ".webp":
        im.save(tmp, "WEBP", quality=JPEG_QUALITY)
    elif ext == ".png":
        im.save(tmp, "PNG", optimize=True)
    elif ext in (".tif", ".tiff"):
        im.save(tmp, "TIFF", compression="tiff_deflate")
    else:
        im.save(tmp, "BMP")
    tmp.replace(path)  # nooit een half geschreven bestand achterlaten


def check_folders(src: Path, dst: Path):
    src, dst = src.resolve(), dst.resolve()
    if not src.is_dir():
        raise ValueError(f"Bronmap bestaat niet: {src}")
    if dst == src:
        raise ValueError("De doelmap mag niet dezelfde zijn als de bronmap (originelen blijven altijd bewaard).")
    if src in dst.parents:
        # Toegestaan, maar dan mag de doelmap niet opnieuw als bron meetellen
        pass
    return src, dst


# --------------------------------------------------------------- verwerking
class Processor:
    """Verwerkt een lijst foto's; bruikbaar vanuit venster en opdrachtregel."""

    def __init__(self, mode="overlay", overlay=None, scale=1.6, mirror=False,
                 accuracy="normal", confidence=0.5, min_size=0):
        self.renderer = fc.MaskRenderer(mode, overlay, scale, mirror)
        self.accuracy = accuracy
        self.confidence = confidence
        self.min_size = min_size
        self.detector = None

    def detect(self, img):
        if self.detector is None:
            self.detector = fc.create_detector(score=min(0.3, self.confidence))
        return fc.detect_faces(self.detector, img, self.accuracy, self.confidence, self.min_size)

    def render(self, img, faces):
        out = img.copy()
        self.renderer.apply(out, faces)
        return out


# ---------------------------------------------------------------- opdrachtregel
def run_cli(argv):
    ap = argparse.ArgumentParser(description="Anonimiseer alle gezichten in een map met foto's.")
    ap.add_argument("bron", type=Path, help="map met foto's")
    ap.add_argument("doel", type=Path, nargs="?", help="map voor de resultaten (standaard: <bron>_anoniem)")
    ap.add_argument("--mode", choices=fc.MODES, default="overlay")
    ap.add_argument("--overlay", type=Path, default=APP_DIR / "assets" / "overlay.png")
    ap.add_argument("--scale", type=float, default=1.6, help="maskergrootte t.o.v. het gezicht")
    ap.add_argument("--mirror", action="store_true", help="overlay spiegelen")
    ap.add_argument("--accuracy", choices=list(fc.ACCURACY), default="normal")
    ap.add_argument("--confidence", type=float, default=0.5)
    ap.add_argument("--recursive", "-r", action="store_true", help="ook submappen")
    ap.add_argument("--overwrite", action="store_true", help="bestaande resultaten overschrijven")
    a = ap.parse_args(argv)

    dst = a.doel or a.bron.with_name(a.bron.name + "_anoniem")
    src, dst = check_folders(a.bron, dst)
    files = [f for f in find_images(src, a.recursive) if dst not in f.parents]
    proc = Processor(a.mode, a.overlay if a.overlay.exists() else None, a.scale, a.mirror,
                     a.accuracy, a.confidence)
    print(f"{len(files)} foto's in {src}\n→ {dst}")
    no_face, failed = [], []
    for i, f in enumerate(files, 1):
        out = output_path(src, dst, f)
        rel = f.relative_to(src)
        if out.exists() and not a.overwrite:
            print(f"[{i}/{len(files)}] {rel}: bestaat al, overgeslagen")
            continue
        try:
            img = load_image(f)
            faces = proc.detect(img)
            save_image(proc.render(img, faces), out)
            flag = "  ⚠ geen gezicht gevonden, controleer" if not faces else ""
            print(f"[{i}/{len(files)}] {rel}: {len(faces)} gezicht(en){flag}")
            if not faces:
                no_face.append(rel)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(files)}] {rel}: FOUT {e}")
            failed.append(rel)
    print(f"\nKlaar. {len(files) - len(failed)} verwerkt, {len(no_face)} zonder gezicht, {len(failed)} mislukt.")
    return 1 if failed else 0


# --------------------------------------------------------------------- venster
def build_gui():
    """Bouwt het venster; geeft (root, app) terug. gui_main() start het."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from PIL import ImageTk

    BG, PANEL, FG, MUTED, ACCENT, WARN = '#2b2b2b', '#333333', 'white', '#9a9a9a', '#4CAF50', '#ffcc66'

    class App:
        def __init__(self, root):
            self.root = root
            self.msgs = queue.Queue()
            self.worker = None
            self.stop_flag = threading.Event()
            self.results = {}   # rel-pad -> dict(src, out, faces)
            self.order = []
            self.src_root = self.dst_root = None
            self.overlay_path = APP_DIR / "assets" / "overlay.png"
            self.processor = None
            self._build()
            self.root.after(50, self.poll)

        # ---------------------------------------------------------- opbouw
        def _label(self, parent, text, **kw):
            return tk.Label(parent, text=text, bg=kw.pop('bg', BG), fg=kw.pop('fg', FG), **kw)

        def _section(self, parent, title):
            f = tk.LabelFrame(parent, text=title, bg=BG, fg=FG, font=('Arial', 10, 'bold'), padx=8, pady=4)
            f.pack(fill=tk.X, pady=4)
            return f

        def _radios(self, parent, var, labels, command=None):
            row = tk.Frame(parent, bg=BG)
            for lab in labels:
                tk.Radiobutton(row, text=lab, value=lab, variable=var, indicatoron=False, width=9,
                               bg=PANEL, fg=FG, selectcolor='#2e5e30', activebackground=PANEL,
                               activeforeground=FG, relief=tk.FLAT, pady=3,
                               command=command).pack(side=tk.LEFT, padx=2)
            return row

        def _folder_row(self, parent, label, var, command):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill=tk.X, pady=2)
            self._label(row, label, width=9, anchor='w').pack(side=tk.LEFT)
            tk.Entry(row, textvariable=var, bg='#3a3a3a', fg=FG, insertbackground=FG,
                     relief=tk.FLAT).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, ipady=3)
            tk.Button(row, text="Kies…", command=command, bg='#4a4a4a', fg=FG,
                      relief=tk.FLAT).pack(side=tk.LEFT)

        def _build(self):
            r = self.root
            r.title("Foto Anonymizer")
            r.configure(bg=BG)
            r.geometry("1100x720")
            r.minsize(900, 600)

            left = tk.Frame(r, bg=BG, padx=12, pady=10, width=400)
            left.pack(side=tk.LEFT, fill=tk.Y)
            left.pack_propagate(False)
            right = tk.Frame(r, bg='#1f1f1f')
            right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            tk.Label(left, text="🖼 Foto Anonymizer", font=('Arial', 17, 'bold'), bg=BG,
                     fg=ACCENT).pack(anchor='w')
            self._label(left, "Originelen blijven altijd bewaard. Metadata (zoals GPS) wordt verwijderd.",
                        fg=MUTED, wraplength=370, justify='left').pack(anchor='w', pady=(0, 6))

            s = self._section(left, "Mappen")
            self.src_var, self.dst_var = tk.StringVar(), tk.StringVar()
            self._folder_row(s, "Foto's:", self.src_var, self.pick_src)
            self._folder_row(s, "Opslaan in:", self.dst_var, self.pick_dst)
            self.recursive_var = tk.BooleanVar(value=True)
            tk.Checkbutton(s, text="Ook submappen", variable=self.recursive_var, bg=BG, fg=FG,
                           selectcolor=BG, activebackground=BG).pack(anchor='w')

            s = self._section(left, "Anonimisering")
            self.mode_var = tk.StringVar(value="Overlay")
            self._radios(s, self.mode_var, MODE_LABELS, self.on_settings).pack(anchor='w', pady=2)
            row = tk.Frame(s, bg=BG)
            row.pack(fill=tk.X, pady=2)
            tk.Button(row, text="Overlay kiezen…", command=self.pick_overlay, bg='#4a4a4a', fg=FG,
                      relief=tk.FLAT).pack(side=tk.LEFT)
            self.overlay_label = self._label(row, self.overlay_path.name if self.overlay_path.exists()
                                             else "geen (wordt pixels)", fg=MUTED)
            self.overlay_label.pack(side=tk.LEFT, padx=8)
            self.mirror_var = tk.BooleanVar(value=False)
            tk.Checkbutton(s, text="Overlay spiegelen", variable=self.mirror_var, bg=BG, fg=FG,
                           selectcolor=BG, activebackground=BG,
                           command=self.on_settings).pack(anchor='w')
            row = tk.Frame(s, bg=BG)
            row.pack(fill=tk.X)
            self._label(row, "Maskergrootte", width=13, anchor='w').pack(side=tk.LEFT)
            self.scale_var = tk.DoubleVar(value=1.6)
            tk.Scale(row, from_=1.0, to=3.0, resolution=0.1, orient=tk.HORIZONTAL, variable=self.scale_var,
                     bg=BG, fg=FG, highlightthickness=0, troughcolor='#444',
                     command=lambda _: self.on_settings()).pack(side=tk.LEFT, fill=tk.X, expand=True)

            s = self._section(left, "Detectie")
            self.acc_var = tk.StringVar(value="Normaal")
            self._radios(s, self.acc_var, ACCURACY_LABELS).pack(anchor='w', pady=2)
            self._label(s, "Grondig vindt ook kleine gezichten ver weg (publiek), maar is trager.",
                        fg=MUTED, wraplength=360, justify='left').pack(anchor='w')
            row = tk.Frame(s, bg=BG)
            row.pack(fill=tk.X)
            self._label(row, "Zekerheid", width=13, anchor='w').pack(side=tk.LEFT)
            self.conf_var = tk.DoubleVar(value=0.5)
            tk.Scale(row, from_=0.3, to=0.9, resolution=0.05, orient=tk.HORIZONTAL, variable=self.conf_var,
                     bg=BG, fg=FG, highlightthickness=0, troughcolor='#444').pack(side=tk.LEFT, fill=tk.X,
                                                                                    expand=True)

            row = tk.Frame(left, bg=BG)
            row.pack(fill=tk.X, pady=(8, 4))
            self.start_btn = tk.Button(row, text="▶ Start", command=self.start, bg=ACCENT, fg='white',
                                       font=('Arial', 11, 'bold'), relief=tk.FLAT, padx=16, pady=4)
            self.start_btn.pack(side=tk.LEFT)
            self.stop_btn = tk.Button(row, text="⏹ Stop", command=self.stop, bg='#f44336', fg='white',
                                      relief=tk.FLAT, padx=12, pady=4, state='disabled')
            self.stop_btn.pack(side=tk.LEFT, padx=6)
            self.open_btn = tk.Button(row, text="📂 Map openen", command=self.open_output, bg='#4a4a4a',
                                      fg=FG, relief=tk.FLAT, padx=8, pady=4, state='disabled')
            self.open_btn.pack(side=tk.RIGHT)

            style = ttk.Style()
            style.theme_use('default')
            style.configure("green.Horizontal.TProgressbar", background=ACCENT, troughcolor='#444')
            self.progress = ttk.Progressbar(left, style="green.Horizontal.TProgressbar", mode='determinate')
            self.progress.pack(fill=tk.X, pady=4)
            self.status = self._label(left, "Kies een map met foto's.", fg=MUTED, wraplength=370,
                                      justify='left', anchor='w')
            self.status.pack(fill=tk.X)

            # Rechts: lijst + voorbeeld
            top = tk.Frame(right, bg='#1f1f1f')
            top.pack(fill=tk.X, padx=8, pady=(8, 0))
            self._label(top, "Resultaten — dubbelklik om na te lopen en te corrigeren", bg='#1f1f1f',
                        fg=MUTED).pack(side=tk.LEFT)
            self.review_btn = tk.Button(top, text="Nalopen…", command=self.open_review, bg='#4a4a4a', fg=FG,
                                        relief=tk.FLAT, state='disabled')
            self.review_btn.pack(side=tk.RIGHT)

            style.configure("Treeview", background='#262626', fieldbackground='#262626', foreground=FG,
                            rowheight=22, borderwidth=0)
            style.configure("Treeview.Heading", background='#333', foreground=FG)
            self.tree = ttk.Treeview(right, columns=("faces", "note"), show="tree headings", height=8)
            self.tree.heading("#0", text="Foto")
            self.tree.heading("faces", text="Gezichten")
            self.tree.heading("note", text="")
            self.tree.column("#0", width=380)
            self.tree.column("faces", width=80, anchor='center')
            self.tree.column("note", width=220)
            self.tree.tag_configure("warn", foreground=WARN)
            self.tree.tag_configure("err", foreground='#ff6b6b')
            self.tree.pack(fill=tk.X, padx=8, pady=6)
            self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_selected())
            self.tree.bind("<Double-1>", lambda e: self.open_review())

            self.preview = tk.Label(right, bg='#1f1f1f', fg='#666', text="Voorbeeld", font=('Arial', 14))
            self.preview.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # --------------------------------------------------------- acties
        def pick_src(self):
            d = filedialog.askdirectory(title="Map met foto's")
            if d:
                self.src_var.set(d)
                if not self.dst_var.get():
                    p = Path(d)
                    self.dst_var.set(str(p.with_name(p.name + "_anoniem")))
                n = len(find_images(Path(d), self.recursive_var.get()))
                self.set_status(f"{n} foto's gevonden.")

        def pick_dst(self):
            d = filedialog.askdirectory(title="Map voor de geanonimiseerde foto's")
            if d:
                self.dst_var.set(d)

        def pick_overlay(self):
            f = filedialog.askopenfilename(title="Overlay (PNG met transparantie werkt het best)",
                                           filetypes=[("Afbeeldingen", "*.png *.webp *.jpg *.jpeg")])
            if f:
                self.overlay_path = Path(f)
                self.overlay_label.config(text=self.overlay_path.name)
                self.on_settings()

        def make_processor(self):
            return Processor(MODE_LABELS[self.mode_var.get()],
                             self.overlay_path if self.overlay_path and self.overlay_path.exists() else None,
                             self.scale_var.get(), self.mirror_var.get(),
                             ACCURACY_LABELS[self.acc_var.get()], self.conf_var.get())

        def on_settings(self):
            """Maskerinstellingen gelden ook voor nalopen/opnieuw opslaan."""
            if self.processor is not None:
                r = self.processor.renderer
                r.mode = MODE_LABELS[self.mode_var.get()]
                r.scale = self.scale_var.get()
                r.mirror = self.mirror_var.get()
                r.set_overlay(self.overlay_path if self.overlay_path and self.overlay_path.exists() else None)

        def set_status(self, text, color=MUTED):
            self.status.config(text=text, fg=color)

        def start(self):
            try:
                src, dst = check_folders(Path(self.src_var.get()), Path(self.dst_var.get()))
            except ValueError as e:
                messagebox.showerror("Foto Anonymizer", str(e))
                return
            files = [f for f in find_images(src, self.recursive_var.get()) if dst not in f.parents]
            if not files:
                messagebox.showinfo("Foto Anonymizer", "Geen foto's gevonden in deze map.")
                return
            existing = sum(output_path(src, dst, f).exists() for f in files)
            if existing and not messagebox.askyesno(
                    "Foto Anonymizer", f"{existing} foto's bestaan al in de doelmap. Overschrijven?"):
                return
            self.src_root, self.dst_root = src, dst
            self.results.clear()
            self.order = []
            self.tree.delete(*self.tree.get_children())
            self.processor = self.make_processor()
            self.progress.config(maximum=len(files), value=0)
            self.stop_flag.clear()
            self.start_btn.config(state='disabled')
            self.stop_btn.config(state='normal')
            self.worker = threading.Thread(target=self.work, args=(files,), daemon=True)
            self.worker.start()

        def stop(self):
            self.stop_flag.set()
            self.set_status("Stoppen na deze foto…")

        def work(self, files):
            t0 = time.time()
            for i, f in enumerate(files, 1):
                if self.stop_flag.is_set():
                    self.msgs.put(("done", i - 1, time.time() - t0, True))
                    return
                rel = f.relative_to(self.src_root)
                out = output_path(self.src_root, self.dst_root, f)
                try:
                    img = load_image(f)
                    faces = self.processor.detect(img)
                    res = self.processor.render(img, faces)
                    save_image(res, out)
                    self.msgs.put(("file", i, len(files), str(rel), f, out, faces, res))
                except Exception as e:  # noqa: BLE001
                    self.msgs.put(("error", i, len(files), str(rel), str(e)))
            self.msgs.put(("done", len(files), time.time() - t0, False))

        def poll(self):
            try:
                while True:
                    m = self.msgs.get_nowait()
                    if m[0] == "file":
                        _, i, n, rel, src, out, faces, res = m
                        self.results[rel] = {"src": src, "out": out, "faces": faces}
                        self.order.append(rel)
                        note = "⚠ geen gezicht gevonden, controleer" if not faces else ""
                        self.tree.insert("", "end", iid=rel, text=rel, values=(len(faces), note),
                                         tags=("warn",) if not faces else ())
                        self.progress.config(value=i)
                        self.set_status(f"{i} / {n}: {rel}")
                        self.show_image(res)
                    elif m[0] == "error":
                        _, i, n, rel, err = m
                        self.tree.insert("", "end", iid=rel, text=rel, values=("–", f"Fout: {err}"), tags=("err",))
                        self.progress.config(value=i)
                    elif m[0] == "done":
                        _, n, secs, stopped = m
                        self.start_btn.config(state='normal')
                        self.stop_btn.config(state='disabled')
                        self.open_btn.config(state='normal')
                        self.review_btn.config(state='normal' if self.results else 'disabled')
                        none = sum(1 for r in self.results.values() if not r["faces"])
                        msg = (f"{'Gestopt' if stopped else 'Klaar'}: {len(self.results)} foto's in {secs:.0f} s, "
                               f"{sum(len(r['faces']) for r in self.results.values())} gezichten afgedekt.")
                        if none:
                            msg += f" {none} foto's zonder gezicht: loop die even na."
                        self.set_status(msg, WARN if none else ACCENT)
            except queue.Empty:
                pass
            self.root.after(50, self.poll)

        def show_image(self, bgr):
            lw, lh = max(self.preview.winfo_width(), 200), max(self.preview.winfo_height(), 150)
            h, w = bgr.shape[:2]
            s = min(lw / w, lh / h, 1.0)
            small = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
            photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))
            self.preview.config(image=photo, text="")
            self.preview.image = photo

        def show_selected(self):
            sel = self.tree.selection()
            if sel and sel[0] in self.results:
                try:
                    self.show_image(load_image(self.results[sel[0]]["out"]))
                except Exception:  # noqa: BLE001
                    pass

        def open_output(self):
            if self.dst_root and self.dst_root.exists():
                open_folder(self.dst_root)

        def open_review(self):
            if not self.results or (self.worker and self.worker.is_alive()):
                return
            sel = self.tree.selection()
            start = self.order.index(sel[0]) if sel and sel[0] in self.order else 0
            self.review = ReviewWindow(self, start)

        def mark_reviewed(self, rel):
            faces = self.results[rel]["faces"]
            self.tree.item(rel, values=(len(faces), "✓ nagelopen"), tags=())

    class ReviewWindow:
        """Klik op een masker om het weg te halen; sleep om een masker toe te voegen."""

        def __init__(self, app, index):
            self.app = app
            self.index = index
            self.win = tk.Toplevel(app.root, class_="Foto-anonymizer")
            self.win.title("Nalopen")
            self.win.geometry("1100x760")
            self.win.configure(bg='#1f1f1f')
            bar = tk.Frame(self.win, bg=BG, pady=6, padx=8)
            bar.pack(fill=tk.X)
            tk.Button(bar, text="◀ Vorige", command=lambda: self.go(-1), bg='#4a4a4a', fg=FG,
                      relief=tk.FLAT).pack(side=tk.LEFT)
            tk.Button(bar, text="Volgende ▶", command=lambda: self.go(1), bg='#4a4a4a', fg=FG,
                      relief=tk.FLAT).pack(side=tk.LEFT, padx=6)
            self.title = tk.Label(bar, bg=BG, fg=FG, font=('Arial', 11, 'bold'))
            self.title.pack(side=tk.LEFT, padx=10)
            self.show_orig = tk.BooleanVar(value=False)
            tk.Checkbutton(bar, text="Origineel tonen", variable=self.show_orig, bg=BG, fg=FG, selectcolor=BG,
                           activebackground=BG, command=self.redraw).pack(side=tk.RIGHT)
            tk.Label(self.win, text="Klik op een masker om het weg te halen · sleep over een gezicht om een "
                                    "masker toe te voegen · wijzigingen worden direct opgeslagen · ←/→ bladeren",
                     bg='#1f1f1f', fg=MUTED).pack(fill=tk.X, pady=(4, 0))
            self.canvas = tk.Canvas(self.win, bg='#1f1f1f', highlightthickness=0, cursor='crosshair')
            self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            self.canvas.bind("<ButtonPress-1>", self.on_press)
            self.canvas.bind("<B1-Motion>", self.on_drag)
            self.canvas.bind("<ButtonRelease-1>", self.on_release)
            self.canvas.bind("<Configure>", lambda e: self.redraw())
            self.win.bind("<Left>", lambda e: self.go(-1))
            self.win.bind("<Right>", lambda e: self.go(1))
            self.img = None
            self.drag = None
            self.load()

        @property
        def rel(self):
            return self.app.order[self.index]

        def load(self):
            r = self.app.results[self.rel]
            self.img = load_image(r["src"])
            self.title.config(text=f"{self.index + 1} / {len(self.app.order)}   {self.rel}")
            self.app.tree.selection_set(self.rel)
            self.app.tree.see(self.rel)
            self.app.mark_reviewed(self.rel)
            self.redraw()

        def go(self, step):
            self.index = max(0, min(len(self.app.order) - 1, self.index + step))
            self.load()

        def redraw(self):
            if self.img is None:
                return
            faces = self.app.results[self.rel]["faces"]
            shown = self.img if self.show_orig.get() else self.app.processor.render(self.img, faces)
            cw, ch = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
            h, w = shown.shape[:2]
            self.s = min(cw / w, ch / h)
            self.ox, self.oy = (cw - w * self.s) / 2, (ch - h * self.s) / 2
            small = cv2.resize(shown, (max(1, int(w * self.s)), max(1, int(h * self.s))),
                               interpolation=cv2.INTER_AREA)
            self.photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))
            self.canvas.delete("all")
            self.canvas.create_image(self.ox, self.oy, image=self.photo, anchor='nw')
            for f in faces:
                x0, y0, size = self.app.processor.renderer.mask_box(f)
                color = '#ffcc66' if f.manual else ACCENT
                self.canvas.create_rectangle(self.ox + x0 * self.s, self.oy + y0 * self.s,
                                             self.ox + (x0 + size) * self.s, self.oy + (y0 + size) * self.s,
                                             outline=color, width=2, dash=(4, 3))

        def to_img(self, ex, ey):
            return (ex - self.ox) / self.s, (ey - self.oy) / self.s

        def on_press(self, e):
            self.drag = (e.x, e.y, None)

        def on_drag(self, e):
            if not self.drag:
                return
            x0, y0, rect = self.drag
            if rect:
                self.canvas.delete(rect)
            rect = self.canvas.create_rectangle(x0, y0, e.x, e.y, outline='#ffcc66', width=2)
            self.drag = (x0, y0, rect)

        def on_release(self, e):
            if not self.drag:
                return
            x0, y0, _ = self.drag
            self.drag = None
            faces = self.app.results[self.rel]["faces"]
            if abs(e.x - x0) < 6 and abs(e.y - y0) < 6:
                # Klik: kleinste masker onder de muis weghalen
                px, py = self.to_img(e.x, e.y)
                hits = []
                for f in faces:
                    mx, my, size = self.app.processor.renderer.mask_box(f)
                    if mx <= px <= mx + size and my <= py <= my + size:
                        hits.append((size, f))
                if hits:
                    faces.remove(min(hits, key=lambda t: t[0])[1])
                    self.save()
            else:
                ax, ay = self.to_img(min(x0, e.x), min(y0, e.y))
                bx, by = self.to_img(max(x0, e.x), max(y0, e.y))
                side = max(bx - ax, by - ay)
                # Het getekende vak wordt het masker: gezicht = vak / maskergrootte
                core = side / self.app.processor.renderer.scale
                cx, cy = (ax + bx) / 2, (ay + by) / 2
                faces.append(fc.Face(cx - core / 2, cy - core / 2, core, core, 1.0, manual=True))
                self.save()
            self.redraw()

        def save(self):
            r = self.app.results[self.rel]
            save_image(self.app.processor.render(self.img, r["faces"]), r["out"])
            self.app.mark_reviewed(self.rel)

    root = tk.Tk(className="foto-anonymizer")
    icon = APP_DIR / "assets" / "photo_icon.png"
    if icon.exists():
        try:
            root.iconphoto(True, tk.PhotoImage(file=str(icon)))
        except tk.TclError:
            pass
    return root, App(root)


def gui_main():
    root, _ = build_gui()
    root.mainloop()


def open_folder(path: Path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            sys.exit(run_cli(sys.argv[1:]))
        except ValueError as e:
            sys.exit(f"Fout: {e}")
    gui_main()
