#!/usr/bin/env python3
"""
FACE ANONYMIZER FOR AV
Anonimiseert gezichten in video's, beeldreeksen (genummerde beelden) en losse foto's.

- Originelen blijven onaangeroerd; resultaten krijgen "_anoniem" in de naam
- Video's houden hun geluid; metadata (GPS, titel, toestel) wordt verwijderd
- Gezichten worden over de tijd gevolgd: korte missers worden opgevuld
- Nalopen: door de video bladeren, maskers weghalen of toevoegen

Gebruik:
    python av_anonymizer.py                                   # venster
    python av_anonymizer.py BESTAND_OF_MAP ... -o DOELMAP     # zonder venster (zie --help)
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

import av_core as ac
import face_core as fc

APP_DIR = Path(__file__).resolve().parent
DEFAULT_OVERLAY = APP_DIR / "assets" / "overlay.png"
MODE_LABELS = {"Overlay": "overlay", "Pixels": "pixelate", "Blur": "blur", "Zwart": "black"}
SPEED_LABELS = {"Snel": "fast", "Normaal": "normal", "Grondig": "thorough"}


def fmt_time(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds < 3600 else f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def open_folder(path: Path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def default_output_dir(items):
    first = items[0].source
    base = first if first.is_dir() and items[0].kind != "sequence" else first.parent
    if "*" in base.name:
        base = base.parent
    return base / "anoniem"


# ------------------------------------------------------------- opdrachtregel
def run_cli(argv):
    ap = argparse.ArgumentParser(description="Anonimiseer gezichten in video's, beeldreeksen en foto's.")
    ap.add_argument("invoer", nargs="+", type=Path, help="video's, foto's of mappen (een map met genummerde beelden is een reeks)")
    ap.add_argument("-o", "--uitvoer", type=Path, help="doelmap (standaard: map 'anoniem' naast de invoer)")
    ap.add_argument("--mode", choices=fc.MODES, default="overlay")
    ap.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    ap.add_argument("--scale", type=float, default=1.6)
    ap.add_argument("--mirror", action="store_true")
    ap.add_argument("--speed", choices=list(ac.SPEED), default="normal")
    ap.add_argument("--confidence", type=float, default=0.5)
    ap.add_argument("--gap", type=float, default=1.5, help="gaten tot zoveel seconden opvullen")
    a = ap.parse_args(argv)

    items = ac.items_for_paths(a.invoer)
    if not items:
        print("Geen video's of foto's gevonden.")
        return 1
    out_dir = (a.uitvoer or default_output_dir(items)).resolve()
    s = ac.Settings(a.mode, a.overlay if a.overlay.exists() else None, a.scale, a.mirror, a.speed,
                    a.confidence, a.gap)
    det = ac.Detector(s)
    failed = 0
    for n, item in enumerate(items, 1):
        ac.plan_output(item, out_dir)
        if item.out.resolve() == item.source.resolve():
            print(f"[{n}/{len(items)}] {item.name}: uitvoer zou het origineel overschrijven, overgeslagen")
            failed += 1
            continue
        t0 = time.time()

        def progress(i, total, phase, n=n):
            print(f"\r[{n}/{len(items)}] {item.name}: {phase} {i * 100 // max(1, total)}%   ", end="", flush=True)
        try:
            ac.process(item, s, det, progress)
            filled = sum(len(t.filled) for t in item.tracks)
            print(f"\r[{n}/{len(items)}] {item.name}: {item.face_count} gezicht(en), {fmt_time(time.time() - t0)}"
                  f"{f', {filled} beelden opgevuld' if filled else ''} → {item.out}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"\r[{n}/{len(items)}] {item.name}: FOUT {e}")
    return 1 if failed else 0


# --------------------------------------------------------------------- venster
def build_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from PIL import Image, ImageTk

    BG, PANEL, FG, MUTED, ACCENT, WARN = '#2b2b2b', '#333333', 'white', '#9a9a9a', '#4CAF50', '#ffcc66'

    def to_photo(bgr, max_w, max_h):
        h, w = bgr.shape[:2]
        s = min(max_w / w, max_h / h, 1.0)
        small = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        return ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))), s

    class App:
        def __init__(self, root):
            self.root = root
            self.items = []
            self.msgs = queue.Queue()
            self.stop_flag = threading.Event()
            self.worker = None
            self.overlay_path = DEFAULT_OVERLAY if DEFAULT_OVERLAY.exists() else None
            self.out_dir = None
            self.review = None
            self._build()
            self.root.after(60, self.poll)

        # -------------------------------------------------------- opbouw
        def _label(self, parent, text, **kw):
            return tk.Label(parent, text=text, bg=kw.pop('bg', BG), fg=kw.pop('fg', FG), **kw)

        def _section(self, parent, title):
            f = tk.LabelFrame(parent, text=title, bg=BG, fg=FG, font=('Arial', 10, 'bold'), padx=8, pady=4)
            f.pack(fill=tk.X, pady=4)
            return f

        def _radios(self, parent, var, labels, command=None):
            row = tk.Frame(parent, bg=BG)
            for lab in labels:
                tk.Radiobutton(row, text=lab, value=lab, variable=var, indicatoron=False, width=8, bg=PANEL, fg=FG,
                               selectcolor='#2e5e30', activebackground=PANEL, activeforeground=FG, relief=tk.FLAT,
                               pady=3, command=command).pack(side=tk.LEFT, padx=2)
            return row

        def _slider(self, parent, label, var, frm, to, res, fmt):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill=tk.X)
            self._label(row, label, width=15, anchor='w').pack(side=tk.LEFT)
            out = self._label(row, "", fg=MUTED, width=6)
            out.pack(side=tk.RIGHT)
            tk.Scale(row, from_=frm, to=to, resolution=res, orient=tk.HORIZONTAL, variable=var, showvalue=False,
                     bg=BG, fg=FG, highlightthickness=0, troughcolor='#444',
                     command=lambda v: out.config(text=fmt(float(v)))).pack(side=tk.LEFT, fill=tk.X, expand=True)
            out.config(text=fmt(var.get()))

        def _button(self, parent, text, cmd, **kw):
            return tk.Button(parent, text=text, command=cmd, bg=kw.pop('bg', '#4a4a4a'), fg=kw.pop('fg', FG),
                             relief=tk.FLAT, padx=kw.pop('padx', 8), pady=kw.pop('pady', 3), **kw)

        def _build(self):
            r = self.root
            r.title("Face Anonymizer for AV")
            r.configure(bg=BG)
            r.geometry("1180x760")
            r.minsize(980, 640)

            left = tk.Frame(r, bg=BG, padx=12, pady=10, width=390)
            left.pack(side=tk.LEFT, fill=tk.Y)
            left.pack_propagate(False)
            right = tk.Frame(r, bg='#1f1f1f')
            right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            tk.Label(left, text="🎬 Face Anonymizer for AV", font=('Arial', 16, 'bold'), bg=BG,
                     fg=ACCENT).pack(anchor='w')
            self._label(left, "Video's, beeldreeksen en foto's. Originelen blijven bewaard; geluid blijft, "
                              "metadata (zoals GPS) gaat eruit.", fg=MUTED, wraplength=360,
                        justify='left').pack(anchor='w', pady=(0, 6))

            s = self._section(left, "Afdekking")
            self.mode_var = tk.StringVar(value="Overlay")
            self._radios(s, self.mode_var, MODE_LABELS).pack(anchor='w', pady=2)
            row = tk.Frame(s, bg=BG)
            row.pack(fill=tk.X, pady=2)
            self._button(row, "Overlay kiezen…", self.pick_overlay).pack(side=tk.LEFT)
            self.overlay_label = self._label(row, self.overlay_path.name if self.overlay_path else "geen (wordt pixels)",
                                             fg=MUTED)
            self.overlay_label.pack(side=tk.LEFT, padx=8)
            self.mirror_var = tk.BooleanVar(value=False)
            tk.Checkbutton(s, text="Overlay spiegelen", variable=self.mirror_var, bg=BG, fg=FG, selectcolor=BG,
                           activebackground=BG).pack(anchor='w')
            self.scale_var = tk.DoubleVar(value=1.6)
            self._slider(s, "Maskergrootte", self.scale_var, 1.0, 3.0, 0.1, lambda v: f"{v:.1f}×")

            s = self._section(left, "Detectie")
            self.speed_var = tk.StringVar(value="Normaal")
            self._radios(s, self.speed_var, SPEED_LABELS).pack(anchor='w', pady=2)
            self._label(s, "Snel zoekt in elk 2e beeld. Grondig vindt ook kleine gezichten ver weg, maar is "
                           "een stuk trager.", fg=MUTED, wraplength=350, justify='left').pack(anchor='w')
            self.conf_var = tk.DoubleVar(value=0.5)
            self._slider(s, "Zekerheid", self.conf_var, 0.3, 0.9, 0.05, lambda v: f"{v:.2f}")
            self.gap_var = tk.DoubleVar(value=1.5)
            self._slider(s, "Missers opvullen", self.gap_var, 0.0, 3.0, 0.1, lambda v: f"{v:.1f} s")
            self._label(s, "Als een gezicht even niet gevonden wordt (opzij kijken, hand voor het gezicht), "
                           "blijft het masker tot zo lang staan.", fg=MUTED, wraplength=350,
                        justify='left').pack(anchor='w')

            s = self._section(left, "Opslaan in")
            row = tk.Frame(s, bg=BG)
            row.pack(fill=tk.X)
            self.out_var = tk.StringVar(value="(map 'anoniem' naast de eerste invoer)")
            self._label(row, "", textvariable=self.out_var, fg=MUTED, anchor='w', wraplength=270,
                        justify='left').pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._button(row, "Kies…", self.pick_out).pack(side=tk.RIGHT)

            row = tk.Frame(left, bg=BG)
            row.pack(fill=tk.X, pady=(10, 4))
            self.start_btn = self._button(row, "▶ Start", self.start, bg=ACCENT, fg='white',
                                          font=('Arial', 11, 'bold'), padx=16, pady=4)
            self.start_btn.pack(side=tk.LEFT)
            self.stop_btn = self._button(row, "⏹ Stop", self.stop, bg='#f44336', fg='white', state='disabled')
            self.stop_btn.pack(side=tk.LEFT, padx=6)
            self.open_btn = self._button(row, "📂 Map openen", self.open_output, state='disabled')
            self.open_btn.pack(side=tk.RIGHT)

            style = ttk.Style()
            style.theme_use('default')
            style.configure("green.Horizontal.TProgressbar", background=ACCENT, troughcolor='#444')
            self.progress = ttk.Progressbar(left, style="green.Horizontal.TProgressbar", mode='determinate',
                                            maximum=1000)
            self.progress.pack(fill=tk.X, pady=4)
            self.status = self._label(left, "Voeg video's, foto's of een map toe.", fg=MUTED, wraplength=360,
                                      justify='left', anchor='w')
            self.status.pack(fill=tk.X)

            # Rechts: wachtrij + voorbeeld
            top = tk.Frame(right, bg='#1f1f1f')
            top.pack(fill=tk.X, padx=8, pady=(8, 0))
            self._button(top, "+ Bestanden…", self.add_files).pack(side=tk.LEFT)
            self._button(top, "+ Map…", self.add_folder).pack(side=tk.LEFT, padx=6)
            self._button(top, "Uit lijst halen", self.remove_selected).pack(side=tk.LEFT)
            self.review_btn = self._button(top, "Nalopen…", self.open_review, state='disabled')
            self.review_btn.pack(side=tk.RIGHT)

            style.configure("Treeview", background='#262626', fieldbackground='#262626', foreground=FG,
                            rowheight=22, borderwidth=0)
            style.configure("Treeview.Heading", background='#333', foreground=FG)
            self.tree = ttk.Treeview(right, columns=("kind", "faces", "status"), show="tree headings", height=9)
            for col, text, width in [("#0", "Naam", 330), ("kind", "Soort", 150), ("faces", "Gezichten", 80),
                                     ("status", "Status", 260)]:
                self.tree.heading(col, text=text)
                self.tree.column(col, width=width, anchor='w' if col in ("#0", "status") else 'center')
            self.tree.tag_configure("warn", foreground=WARN)
            self.tree.tag_configure("err", foreground='#ff6b6b')
            self.tree.tag_configure("ok", foreground='#9be29f')
            self.tree.pack(fill=tk.X, padx=8, pady=6)
            self.tree.bind("<Double-1>", lambda e: self.open_review())
            self.tree.bind("<<TreeviewSelect>>", lambda e: self.review_btn.config(
                state='normal' if self.selected() and self.selected().status == "klaar" else 'disabled'))

            self.preview = tk.Label(right, bg='#1f1f1f', fg='#666', font=('Arial', 13),
                                    text="Voeg video's, foto's of een map toe met de knoppen hierboven.\n\n"
                                         "Een map met genummerde beelden (bijv. frame_0001.png) wordt een beeldreeks.")
            self.preview.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # ------------------------------------------------------ wachtrij
        def add_items(self, new):
            known = {(i.kind, str(i.source)) for i in self.items}
            for it in new:
                if (it.kind, str(it.source)) in known:
                    continue
                self.items.append(it)
                self.tree.insert("", "end", iid=str(id(it)), text=it.name, values=(it.label, "", "wacht"))
            if self.items and self.out_dir is None:
                self.out_var.set(str(default_output_dir(self.items)))
            self.set_status(f"{len(self.items)} in de lijst. Druk op Start.")

        def add_files(self):
            vids = " ".join(f"*{e}" for e in sorted(ac.VIDEO_EXT))
            imgs = " ".join(f"*{e}" for e in sorted(ac.IMAGE_EXT))
            files = filedialog.askopenfilenames(title="Video's of foto's", filetypes=[
                ("Video's en foto's", f"{vids} {imgs} {vids.upper()} {imgs.upper()}"), ("Alle bestanden", "*")])
            if files:
                self.add_items(ac.items_for_paths(files))

        def add_folder(self):
            d = filedialog.askdirectory(title="Map met video's, foto's of een beeldreeks")
            if d:
                found = ac.items_for_paths([d])
                if not found:
                    messagebox.showinfo("Face Anonymizer for AV", "Geen video's of foto's in deze map.")
                self.add_items(found)

        def remove_selected(self):
            if self.worker and self.worker.is_alive():
                return
            for iid in self.tree.selection():
                self.items = [i for i in self.items if str(id(i)) != iid]
                self.tree.delete(iid)

        def selected(self):
            sel = self.tree.selection()
            return next((i for i in self.items if str(id(i)) == sel[0]), None) if sel else None

        def pick_overlay(self):
            f = filedialog.askopenfilename(title="Overlay (PNG met transparantie werkt het best)",
                                           filetypes=[("Afbeeldingen", "*.png *.webp *.jpg *.jpeg")])
            if f:
                self.overlay_path = Path(f)
                self.overlay_label.config(text=self.overlay_path.name)

        def pick_out(self):
            d = filedialog.askdirectory(title="Map voor de geanonimiseerde bestanden")
            if d:
                self.out_dir = Path(d)
                self.out_var.set(d)

        def settings(self):
            return ac.Settings(MODE_LABELS[self.mode_var.get()], self.overlay_path, self.scale_var.get(),
                               self.mirror_var.get(), SPEED_LABELS[self.speed_var.get()], self.conf_var.get(),
                               self.gap_var.get())

        def set_status(self, text, color=MUTED):
            self.status.config(text=text, fg=color)

        def set_row(self, item, status, tag=()):
            faces = item.face_count if item.status == "klaar" else ""
            self.tree.item(str(id(item)), values=(item.label, faces, status), tags=tag)

        # ------------------------------------------------------ verwerken
        def start(self):
            todo = [i for i in self.items if i.status != "klaar"]
            if not todo:
                messagebox.showinfo("Face Anonymizer for AV", "Alles in de lijst is al klaar. Voeg iets toe.")
                return
            out_dir = self.out_dir or default_output_dir(self.items)
            for it in todo:
                ac.plan_output(it, out_dir)
                if it.out.resolve() == it.source.resolve():
                    messagebox.showerror("Face Anonymizer for AV", f"{it.name} zou zichzelf overschrijven.")
                    return
            existing = [it for it in todo if it.out.exists()]
            if existing and not messagebox.askyesno(
                    "Face Anonymizer for AV", f"{len(existing)} resultaat/resultaten bestaan al. Overschrijven?"):
                return
            self.settings_used = self.settings()
            self.stop_flag.clear()
            self.start_btn.config(state='disabled')
            self.stop_btn.config(state='normal')
            self.review_btn.config(state='disabled')
            self.worker = threading.Thread(target=self.work, args=(todo, self.settings_used), daemon=True)
            self.worker.start()

        def stop(self):
            self.stop_flag.set()
            self.set_status("Stoppen…")

        def work(self, todo, s):
            try:
                det = ac.Detector(s)
            except Exception as e:  # noqa: BLE001
                self.msgs.put(("fatal", str(e)))
                return
            for n, item in enumerate(todo, 1):
                if self.stop_flag.is_set():
                    break
                t0 = time.time()
                self.msgs.put(("row", item, "bezig…", ()))

                def progress(i, total, phase, item=item, n=n, t0=t0):
                    frac = (0 if phase == "Gezichten zoeken" else 0.5) + 0.5 * i / max(1, total)
                    if item.kind == "photo":
                        frac = 1
                    elapsed = time.time() - t0
                    eta = elapsed / frac - elapsed if frac > 0.02 else None
                    self.msgs.put(("progress", item, n, len(todo), frac, phase, eta))

                def preview(img, faces):
                    self.msgs.put(("preview", img.copy(), list(faces)))
                try:
                    ac.process(item, s, det, progress, self.stop_flag, preview)
                    item.status = "klaar"
                    self.msgs.put(("done", item, time.time() - t0))
                except InterruptedError:
                    item.status = "wacht"
                    self.msgs.put(("row", item, "gestopt", ("warn",)))
                    break
                except Exception as e:  # noqa: BLE001
                    item.status, item.error = "fout", str(e)
                    self.msgs.put(("row", item, f"Fout: {e}", ("err",)))
            self.msgs.put(("finished",))

        def poll(self):
            latest_preview = None
            try:
                while True:
                    m = self.msgs.get_nowait()
                    kind = m[0]
                    if kind == "row":
                        self.set_row(m[1], m[2], m[3])
                    elif kind == "progress":
                        _, item, n, total, frac, phase, eta = m
                        self.progress.config(value=int(frac * 1000))
                        eta_txt = f", nog ± {fmt_time(eta)}" if eta else ""
                        self.set_status(f"{n}/{total} {item.name}: {phase.lower()} {int(frac * 100)}%{eta_txt}")
                        self.set_row(item, f"{phase.lower()} {int(frac * 100)}%")
                    elif kind == "preview":
                        latest_preview = m
                    elif kind == "done":
                        _, item, secs = m
                        filled = sum(len(t.filled) for t in item.tracks)
                        if item.face_count == 0:
                            self.set_row(item, "⚠ geen gezicht gevonden, controleer", ("warn",))
                        elif filled:
                            self.set_row(item, f"klaar in {fmt_time(secs)}, {filled} beelden opgevuld: nalopen",
                                         ("warn",))
                        else:
                            self.set_row(item, f"klaar in {fmt_time(secs)}", ("ok",))
                    elif kind == "fatal":
                        messagebox.showerror("Face Anonymizer for AV", m[1])
                    elif kind == "finished":
                        self.start_btn.config(state='normal')
                        self.stop_btn.config(state='disabled')
                        self.open_btn.config(state='normal')
                        self.progress.config(value=1000 if not self.stop_flag.is_set() else 0)
                        done = [i for i in self.items if i.status == "klaar"]
                        check = [i for i in done if i.face_count == 0 or any(t.filled for t in i.tracks)]
                        msg = f"Klaar: {len(done)} van {len(self.items)} verwerkt."
                        if check:
                            msg += f" {len(check)} om na te lopen (oranje in de lijst)."
                        self.set_status(msg, WARN if check else ACCENT)
                        sel = self.selected()
                        self.review_btn.config(state='normal' if sel and sel.status == "klaar" else 'disabled')
            except queue.Empty:
                pass
            if latest_preview:
                _, img, faces = latest_preview
                vis = img
                if faces:
                    vis = img.copy()
                    for f in faces:
                        cv2.rectangle(vis, (int(f.x), int(f.y)), (int(f.x + f.w), int(f.y + f.h)), (80, 200, 80), 3)
                photo, _ = to_photo(vis, max(200, self.preview.winfo_width()), max(150, self.preview.winfo_height()))
                self.preview.config(image=photo, text="")
                self.preview.image = photo
            self.root.after(60, self.poll)

        def open_output(self):
            d = self.out_dir or (default_output_dir(self.items) if self.items else None)
            if d and Path(d).exists():
                open_folder(Path(d))

        def open_review(self):
            item = self.selected()
            if item and item.status == "klaar" and not (self.worker and self.worker.is_alive()):
                self.review = ReviewWindow(self, item)

    class ReviewWindow:
        """Door het resultaat bladeren; klik = masker (hele spoor) weg, slepen = masker toevoegen."""

        def __init__(self, app, item):
            self.app, self.item = app, item
            self.s = app.settings_used
            self.renderer = ac.make_renderer(self.s)
            self.reader = ac.VideoReader(item.source) if item.kind == "video" else None
            self.idx, self.frame, self.drag, self.dirty, self.undo = 0, None, None, False, []
            self.segments = self._filled_segments()

            w = self.win = tk.Toplevel(app.root, class_="Face-anonymizer-av")
            w.title(f"Nalopen – {item.name}")
            w.geometry("1150x800")
            w.configure(bg='#1f1f1f')
            w.protocol("WM_DELETE_WINDOW", self.close)

            # Regel 1: waar ben je, en opslaan
            bar = tk.Frame(w, bg=BG, pady=6, padx=8)
            bar.pack(fill=tk.X)
            self.info = tk.Label(bar, bg=BG, fg=FG, font=('Arial', 10, 'bold'), anchor='w')
            self.info.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.save_btn = app._button(bar, "💾 Opnieuw opslaan", self.save, bg=ACCENT, fg='white', state='disabled')
            self.save_btn.pack(side=tk.RIGHT)
            app._button(bar, "↶ Ongedaan maken", self.undo_last).pack(side=tk.RIGHT, padx=6)
            self.orig = tk.BooleanVar(value=False)
            tk.Checkbutton(bar, text="Origineel tonen", variable=self.orig, bg=BG, fg=FG, selectcolor=BG,
                           activebackground=BG, command=self.redraw).pack(side=tk.RIGHT, padx=6)

            # Regel 2: bladeren en masker-duur
            nav = tk.Frame(w, bg=BG, padx=8, pady=4)
            nav.pack(fill=tk.X)
            self.dur_var = tk.DoubleVar(value=2.0)
            if item.n_frames > 1:
                app._button(nav, "◀", lambda: self.go(self.idx - 1)).pack(side=tk.LEFT)
                app._button(nav, "▶", lambda: self.go(self.idx + 1)).pack(side=tk.LEFT, padx=4)
                app._button(nav, "⏮ Vorig opgevuld stuk", lambda: self.jump(-1)).pack(side=tk.LEFT, padx=(12, 0))
                app._button(nav, "Volgend opgevuld stuk ⏭", lambda: self.jump(1)).pack(side=tk.LEFT, padx=4)
                tk.Label(nav, text="s", bg=BG, fg=MUTED).pack(side=tk.RIGHT)
                tk.Spinbox(nav, from_=0.1, to=600, increment=0.5, width=5, textvariable=self.dur_var,
                           bg='#3a3a3a', fg=FG, relief=tk.FLAT).pack(side=tk.RIGHT, padx=4)
                tk.Label(nav, text="Nieuw masker duurt", bg=BG, fg=MUTED).pack(side=tk.RIGHT)

            what = "in de hele video " if item.n_frames > 1 else ""
            tk.Label(w, text=f"Klik op een masker om het {what}weg te halen. Sleep over een gemist gezicht om een "
                             "masker toe te voegen. Kaders: groen = gevonden, oranje = opgevuld (controleer), "
                             "geel = handmatig.", bg='#1f1f1f', fg=MUTED, wraplength=1100, justify='left',
                     anchor='w').pack(fill=tk.X, padx=8, pady=(6, 0))

            self.canvas = tk.Canvas(w, bg='#1f1f1f', highlightthickness=0, cursor='crosshair')
            self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
            self.canvas.bind("<ButtonPress-1>", self.on_press)
            self.canvas.bind("<B1-Motion>", self.on_drag)
            self.canvas.bind("<ButtonRelease-1>", self.on_release)
            self.canvas.bind("<Configure>", lambda e: self.redraw())

            if item.n_frames > 1:
                self.pos = tk.Scale(w, from_=0, to=item.n_frames - 1, orient=tk.HORIZONTAL, showvalue=False,
                                    bg=BG, fg=FG, highlightthickness=0, troughcolor='#444',
                                    command=lambda v: self.go(int(float(v)), from_slider=True))
                self.pos.pack(fill=tk.X, padx=8, pady=(0, 4))
                self.strip = tk.Canvas(w, height=10, bg='#262626', highlightthickness=0)
                self.strip.pack(fill=tk.X, padx=8, pady=(0, 8))
                self.strip.bind("<Configure>", lambda e: self.draw_strip())
            w.bind("<Left>", lambda e: self.go(self.idx - 1))
            w.bind("<Right>", lambda e: self.go(self.idx + 1))
            self._pending = None
            self.go(self.segments[0][0] if self.segments else 0)

        # ------------------------------------------------- navigatie
        def _filled_segments(self):
            frames = sorted({f for t in self.item.tracks if t.id not in self.item.removed for f in t.filled})
            segs = []
            for f in frames:
                if segs and f == segs[-1][1] + 1:
                    segs[-1][1] = f
                else:
                    segs.append([f, f])
            return segs

        def draw_strip(self):
            """Tijdlijn: oranje streepjes = opgevulde stukken om te controleren."""
            c = self.strip
            c.delete("all")
            W, n = c.winfo_width(), max(1, self.item.n_frames)
            for a, b in self.segments:
                c.create_rectangle(a / n * W, 0, (b + 1) / n * W + 1, 10, fill='#ff9800', width=0)
            c.create_line(self.idx / n * W, 0, self.idx / n * W, 10, fill='white', width=2)

        def jump(self, direction):
            if not self.segments:
                return
            if direction > 0:
                nxt = next((a for a, _ in self.segments if a > self.idx), self.segments[0][0])
            else:
                nxt = next((a for a, _ in reversed(self.segments) if a < self.idx), self.segments[-1][0])
            self.go(nxt)

        def go(self, idx, from_slider=False):
            idx = max(0, min(self.item.n_frames - 1, idx))
            self.idx = idx
            if not from_slider and self.item.n_frames > 1:
                self.pos.set(idx)
            # Wacht even met inlezen tot de schuifregelaar stilstaat
            if self._pending:
                self.win.after_cancel(self._pending)
            self._pending = self.win.after(60 if from_slider else 1, self.load)

        def load(self):
            self._pending = None
            try:
                self.frame = ac.read_frame(self.item, self.idx, self.reader)
            except Exception as e:  # noqa: BLE001
                self.info.config(text=f"Kon beeld niet lezen: {e}")
                return
            self.redraw()

        # --------------------------------------------------- tekenen
        def redraw(self):
            if self.frame is None:
                return
            img = self.frame.copy()
            faces = self.item.frame_faces(self.idx)
            if not self.orig.get():
                self.renderer.apply(img, faces)
            cw, ch = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
            self.photo, self.sc = to_photo(img, cw, ch)
            h, w = img.shape[:2]
            self.ox, self.oy = (cw - w * self.sc) / 2, (ch - h * self.sc) / 2
            self.canvas.delete("all")
            self.canvas.create_image(self.ox, self.oy, image=self.photo, anchor='nw')
            for t in self.item.tracks:
                if t.id in self.item.removed or self.idx not in t.boxes:
                    continue
                x0, y0, size = self.renderer.mask_box(fc.Face(*t.boxes[self.idx][:4], 1.0))
                color = '#ffeb3b' if t.manual else ('#ff9800' if self.idx in t.filled else ACCENT)
                self.canvas.create_rectangle(self.ox + x0 * self.sc, self.oy + y0 * self.sc,
                                             self.ox + (x0 + size) * self.sc, self.oy + (y0 + size) * self.sc,
                                             outline=color, width=2, dash=(5, 3))
            fps = self.item.fps or 25
            where = (f"beeld {self.idx + 1} / {self.item.n_frames}   {fmt_time(self.idx / fps)}"
                     if self.item.n_frames > 1 else "")
            self.info.config(text=f"{where}   {len(faces)} masker(s){'   • niet opgeslagen' if self.dirty else ''}")
            if self.item.n_frames > 1:
                self.draw_strip()

        # ------------------------------------------------- bewerken
        def to_img(self, ex, ey):
            return (ex - self.ox) / self.sc, (ey - self.oy) / self.sc

        def on_press(self, e):
            self.drag = [e.x, e.y, None]

        def on_drag(self, e):
            if self.drag:
                if self.drag[2]:
                    self.canvas.delete(self.drag[2])
                self.drag[2] = self.canvas.create_rectangle(self.drag[0], self.drag[1], e.x, e.y,
                                                            outline='#ffeb3b', width=2)

        def on_release(self, e):
            if not self.drag:
                return
            x0, y0, _ = self.drag
            self.drag = None
            if abs(e.x - x0) < 6 and abs(e.y - y0) < 6:
                hits = ac.tracks_at(self.item, self.idx, *self.to_img(e.x, e.y), self.renderer)
                if hits:
                    self.item.removed.add(hits[0].id)
                    self.undo.append(("remove", hits[0].id))
                    self.changed()
                return
            ax, ay = self.to_img(min(x0, e.x), min(y0, e.y))
            bx, by = self.to_img(max(x0, e.x), max(y0, e.y))
            side = max(bx - ax, by - ay)
            core = side / self.renderer.scale        # het getekende vak wordt het masker
            cx, cy = (ax + bx) / 2, (ay + by) / 2
            frames = max(1, int(round(float(self.dur_var.get() or 0) * (self.item.fps or 25))))
            t = ac.add_manual(self.item, self.idx, self.idx + frames - 1,
                              (cx - core / 2, cy - core / 2, core, core))
            self.undo.append(("add", t.id))
            self.changed()

        def undo_last(self):
            if not self.undo:
                return
            action, tid = self.undo.pop()
            if action == "remove":
                self.item.removed.discard(tid)
            else:
                self.item.tracks = [t for t in self.item.tracks if t.id != tid]
            self.changed()

        def changed(self):
            self.dirty = True
            self.save_btn.config(state='normal')
            self.segments = self._filled_segments()
            self.redraw()
            if self.item.kind == "photo":   # foto: meteen opslaan, gaat snel
                self.save()

        def save(self):
            self.save_btn.config(state='disabled', text="Opslaan…")
            self.win.config(cursor='watch')
            done = threading.Event()
            state = {}

            def run():
                try:
                    ac.render(self.item, self.s, renderer=self.renderer,
                              progress=lambda i, n, p: state.__setitem__('pct', i * 100 // max(1, n)))
                except Exception as e:  # noqa: BLE001
                    state['err'] = str(e)
                done.set()

            def watch():
                if not done.is_set():
                    self.save_btn.config(text=f"Opslaan… {state.get('pct', 0)}%")
                    self.win.after(200, watch)
                    return
                self.win.config(cursor='')
                if 'err' in state:
                    messagebox.showerror("Opslaan mislukt", state['err'], parent=self.win)
                    self.save_btn.config(state='normal', text="💾 Opnieuw opslaan")
                    return
                self.dirty = False
                self.save_btn.config(text="✓ Opgeslagen")
                self.app.set_row(self.item, "nagelopen en opgeslagen", ("ok",))
                self.redraw()
            threading.Thread(target=run, daemon=True).start()
            watch()

        def close(self):
            if self.dirty and not messagebox.askyesno(
                    "Nalopen", "Je wijzigingen zijn nog niet opgeslagen. Toch sluiten?", parent=self.win):
                return
            if self.reader:
                self.reader.close()
            self.win.destroy()
            self.app.review = None

    root = tk.Tk(className="face-anonymizer-av")
    icon = APP_DIR / "assets" / "av_icon.png"
    if icon.exists():
        try:
            root.iconphoto(True, tk.PhotoImage(file=str(icon)))
        except tk.TclError:
            pass
    app = App(root)
    if not ac.VIDEO_SUPPORT:
        messagebox.showwarning("Face Anonymizer for AV", "Het pakket 'av' ontbreekt: video's werken niet, foto's "
                                                         "en beeldreeksen wel. Voer install.sh opnieuw uit.")
    return root, app


def gui_main():
    root, _ = build_gui()
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(run_cli(sys.argv[1:]))
    gui_main()
