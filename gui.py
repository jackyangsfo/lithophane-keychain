#!/usr/bin/env python3
"""Tkinter GUI for the Lithophane Keychain Generator — Rev 2.1."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _reexec_with_venv() -> None:
    root = Path(__file__).resolve().parent
    venv_python = root / "venv" / "bin" / "python"
    if not venv_python.exists():
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return
    os.execv(str(venv_python), [str(venv_python), *sys.argv])


_reexec_with_venv()

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk

from keychain import (
    PRINT_MODE_EXT,
    PRINT_MODE_LABELS,
    PRINT_MODES,
    PRODUCT_PRESETS,
    PRODUCT_TYPE_LABELS,
    PRODUCT_TYPES,
    SHAPE_LABELS,
    SHAPES,
    GenerateResult,
    KeychainSpec,
    apply_product_preset,
    generate_keychain,
    shape_bounds,
    shape_mask_preview,
)
from app_info import ABOUT_TEXT, APP_NAME, COPYRIGHT_OWNER, REV


class ResultPreviewWindow(tk.Toplevel):
    """Shows source + backlit lithophane preview after STL export."""

    def __init__(
        self,
        master: tk.Tk,
        result: GenerateResult,
        photo_path: Path,
    ) -> None:
        super().__init__(master)
        self.title("Processing complete — Preview")
        self.configure(bg="#eceae6")
        self.transient(master)
        self.grab_set()

        self._photo_ref: ImageTk.PhotoImage | None = None
        self.result = result

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text="Lithophane preview",
            style="Title.TLabel",
        ).pack(anchor=tk.W)

        detail = f"Saved: {result.output_path.name}"
        if result.preview_path:
            detail += f"  ·  Preview: {result.preview_path.name}"
        mode = PRINT_MODE_LABELS.get(result.print_mode, result.print_mode)
        ttk.Label(frame, text=f"{mode}", style="Card.TLabel").pack(anchor=tk.W)
        ttk.Label(frame, text=detail, style="Muted.TLabel").pack(anchor=tk.W, pady=(4, 12))

        img = result.preview_image.copy()
        # Fit to screen
        max_w, max_h = 860, 480
        img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        self._photo_ref = ImageTk.PhotoImage(img)

        canvas = tk.Label(frame, image=self._photo_ref, bg="#1c1b19", bd=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(btns, text="Open preview folder", command=self._reveal).pack(side=tk.LEFT)
        if result.preview_path and result.preview_path.is_file():
            ttk.Button(btns, text="Open preview PNG", command=self._open_png).pack(
                side=tk.LEFT, padx=(8, 0)
            )
        ttk.Button(btns, text="Done", style="Accent.TButton", command=self.destroy).pack(
            side=tk.RIGHT
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        # Center on parent
        self.update_idletasks()
        pw, ph = master.winfo_rootx(), master.winfo_rooty()
        mw, mh = master.winfo_width(), master.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{pw + (mw - w) // 2}+{ph + (mh - h) // 2}")

    def _reveal(self) -> None:
        folder = self.result.output_path.parent
        try:
            os.system(f'open "{folder}"')  # macOS
        except OSError:
            messagebox.showinfo("Folder", str(folder), parent=self)

    def _open_png(self) -> None:
        if self.result.preview_path:
            try:
                os.system(f'open "{self.result.preview_path}"')
            except OSError:
                pass


class KeychainApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} — {REV}")
        self.geometry("960x660")
        self.minsize(860, 560)
        self.configure(bg="#eceae6")

        self.photo_path: Path | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._result_photo: ImageTk.PhotoImage | None = None
        self._last_result: GenerateResult | None = None
        self._busy = False
        self._preview_after: str | None = None
        self._view_mode = tk.StringVar(value="photo")  # photo | result

        self.size_var = tk.DoubleVar(value=45.0)
        self.hole_var = tk.DoubleVar(value=4.5)
        self.rim_var = tk.DoubleVar(value=3.0)
        self.min_t_var = tk.DoubleVar(value=0.8)
        self.max_t_var = tk.DoubleVar(value=2.8)
        self.base_var = tk.DoubleVar(value=0.4)
        self.ppm_var = tk.DoubleVar(value=4.0)
        self.corner_var = tk.DoubleVar(value=6.0)
        self.contrast_var = tk.DoubleVar(value=1.15)
        self.invert_var = tk.BooleanVar(value=False)
        self.shape_var = tk.StringVar(value="circle")
        self.print_mode_var = tk.StringVar(value="white")
        self.product_var = tk.StringVar(value="keychain")
        self.product_hint_var = tk.StringVar(
            value=PRODUCT_PRESETS["keychain"]["hint"]
        )
        self.export_path_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Open a customer photo to begin.")
        self.export_label_var = tk.StringVar(value="Export STL path")
        self.export_btn_var = tk.StringVar(value="Export STL")

        self._build_style()
        self._build_ui()
        self._update_export_path()
        self._refresh_preview()

    # ------------------------------------------------------------------ UI
    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#eceae6")
        style.configure("Card.TFrame", background="#f7f5f2")
        style.configure("TLabel", background="#eceae6", foreground="#1c1b19", font=("Helvetica Neue", 12))
        style.configure("Card.TLabel", background="#f7f5f2", foreground="#1c1b19", font=("Helvetica Neue", 12))
        style.configure("Title.TLabel", background="#eceae6", foreground="#1c1b19", font=("Helvetica Neue", 20, "bold"))
        style.configure("Muted.TLabel", background="#f7f5f2", foreground="#6a6760", font=("Helvetica Neue", 11))
        style.configure("TRadiobutton", background="#f7f5f2", foreground="#1c1b19", font=("Helvetica Neue", 11))
        style.configure("TCheckbutton", background="#f7f5f2", foreground="#1c1b19", font=("Helvetica Neue", 11))
        style.configure("Accent.TButton", font=("Helvetica Neue", 13, "bold"), padding=(14, 10))
        style.configure("TButton", font=("Helvetica Neue", 12), padding=(10, 8))
        style.configure("Horizontal.TScale", background="#f7f5f2")

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill=tk.BOTH, expand=True)

        ttk.Label(root, text="Lithophane Studio", style="Title.TLabel").pack(anchor=tk.W)
        header_row = ttk.Frame(root)
        header_row.pack(fill=tk.X, anchor=tk.W)
        ttk.Label(
            header_row,
            text="Photo → Product → Print Mode → STL / 3MF for Bambu Studio",
            style="TLabel",
        ).pack(side=tk.LEFT)
        ttk.Button(header_row, text="About", command=self._show_about).pack(side=tk.RIGHT)
        ttk.Label(
            root,
            text=f"{REV}  ·  © {COPYRIGHT_OWNER}",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(2, 12))

        body = ttk.Frame(root)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        # Preview card
        left = ttk.Frame(body, style="Card.TFrame", padding=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        btns = ttk.Frame(left, style="Card.TFrame")
        btns.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(btns, text="Open Photo…", command=self._open_photo).pack(side=tk.LEFT)
        self.export_btn = ttk.Button(
            btns,
            textvariable=self.export_btn_var,
            style="Accent.TButton",
            command=self._export_stl,
        )
        self.export_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(
            btns,
            text="Photo",
            value="photo",
            variable=self._view_mode,
            command=self._show_current_view,
        ).pack(side=tk.RIGHT)
        ttk.Radiobutton(
            btns,
            text="Result",
            value="result",
            variable=self._view_mode,
            command=self._show_current_view,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        export_row = ttk.Frame(left, style="Card.TFrame")
        export_row.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        export_row.columnconfigure(0, weight=1)
        ttk.Label(export_row, textvariable=self.export_label_var, style="Card.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        self.export_entry = ttk.Entry(export_row, textvariable=self.export_path_var)
        self.export_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(export_row, text="Browse…", command=self._browse_export_path).grid(
            row=1, column=1, sticky="e"
        )

        self.preview_label = tk.Label(left, bg="#2a2926", bd=0, highlightthickness=0)
        self.preview_label.grid(row=2, column=0, sticky="nsew")

        ttk.Label(left, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=3, column=0, sticky="ew", pady=(10, 0)
        )

        # Controls card
        right = ttk.Frame(body, style="Card.TFrame", padding=14)
        right.grid(row=0, column=1, sticky="nsew")

        ttk.Label(right, text="Product Type", style="Card.TLabel").pack(anchor=tk.W)
        product_frame = ttk.Frame(right, style="Card.TFrame")
        product_frame.pack(fill=tk.X, pady=(4, 2))
        for key in PRODUCT_TYPES:
            ttk.Radiobutton(
                product_frame,
                text=PRODUCT_TYPE_LABELS[key],
                value=key,
                variable=self.product_var,
                command=self._on_product_change,
            ).pack(anchor=tk.W, pady=1)
        ttk.Label(
            right,
            textvariable=self.product_hint_var,
            style="Muted.TLabel",
            wraplength=280,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 10))

        ttk.Label(right, text="Print Mode", style="Card.TLabel").pack(anchor=tk.W)
        mode_frame = ttk.Frame(right, style="Card.TFrame")
        mode_frame.pack(fill=tk.X, pady=(4, 4))
        for key in PRINT_MODES:
            ext = PRINT_MODE_EXT[key].upper().lstrip(".")
            ttk.Radiobutton(
                mode_frame,
                text=f"{PRINT_MODE_LABELS[key]}  →  {ext}",
                value=key,
                variable=self.print_mode_var,
                command=self._on_print_mode_change,
            ).pack(anchor=tk.W, pady=1)

        self.cmyw_hint_var = tk.StringVar(value="")
        self.cmyw_hint = ttk.Label(
            right,
            textvariable=self.cmyw_hint_var,
            style="Muted.TLabel",
            wraplength=280,
            justify=tk.LEFT,
        )
        self.cmyw_hint.pack(anchor=tk.W, pady=(0, 10))
        self._update_cmyw_hint()

        ttk.Label(right, text="Shape", style="Card.TLabel").pack(anchor=tk.W)
        shape_frame = ttk.Frame(right, style="Card.TFrame")
        shape_frame.pack(fill=tk.X, pady=(4, 12))
        for i, key in enumerate(SHAPES):
            ttk.Radiobutton(
                shape_frame,
                text=SHAPE_LABELS[key],
                value=key,
                variable=self.shape_var,
                command=self._on_shape_change,
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 12), pady=2)

        self._slider(right, "Size (mm)", self.size_var, 25, 180, 1)
        self._slider(right, "Hole Ø (mm)", self.hole_var, 0.0, 8.0, 0.1)
        self._slider(right, "Rim (mm)", self.rim_var, 1.5, 8.0, 0.1)
        self._slider(right, "Corner radius (mm)", self.corner_var, 1.0, 20.0, 0.5)
        self._slider(right, "Min thickness (mm)", self.min_t_var, 0.4, 1.5, 0.05)
        self._slider(right, "Max thickness (mm)", self.max_t_var, 1.5, 4.0, 0.05)
        self._slider(right, "Base plate (mm)", self.base_var, 0.2, 1.2, 0.05)
        self._slider(right, "Detail (px/mm)", self.ppm_var, 2.0, 7.0, 0.5)
        self._slider(right, "Contrast", self.contrast_var, 0.8, 1.8, 0.05)

        ttk.Checkbutton(
            right,
            text="Invert lithophane (white → thick)",
            variable=self.invert_var,
            command=self._on_param_change,
        ).pack(anchor=tk.W, pady=(8, 0))

    def _slider(
        self,
        parent: ttk.Frame,
        label: str,
        var: tk.DoubleVar,
        from_: float,
        to: float,
        resolution: float,
    ) -> None:
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill=tk.X, pady=3)
        head = ttk.Frame(row, style="Card.TFrame")
        head.pack(fill=tk.X)
        ttk.Label(head, text=label, style="Card.TLabel").pack(side=tk.LEFT)
        val = ttk.Label(head, text=f"{var.get():.2f}", style="Muted.TLabel")
        val.pack(side=tk.RIGHT)

        def update_label(_a=None, _b=None, _c=None) -> None:
            v = var.get()
            if resolution >= 1:
                val.configure(text=f"{v:.0f}")
            elif resolution >= 0.1:
                val.configure(text=f"{v:.1f}")
            else:
                val.configure(text=f"{v:.2f}")

        def on_move(_event=None) -> None:
            update_label()
            self._on_param_change()

        scale = ttk.Scale(
            row,
            from_=from_,
            to=to,
            variable=var,
            orient=tk.HORIZONTAL,
            command=lambda _v: on_move(),
        )
        scale.pack(fill=tk.X)
        var.trace_add("write", update_label)
        update_label()

    def _show_about(self) -> None:
        messagebox.showinfo(f"About — {APP_NAME}", ABOUT_TEXT, parent=self)

    # --------------------------------------------------------------- helpers
    def _default_export_path(self) -> Path:
        out_dir = Path(__file__).resolve().parent / "stl_out"
        spec = self._current_spec()
        ext = spec.export_ext
        if self.photo_path:
            return out_dir / (
                f"{self.photo_path.stem}_{spec.product_type}_{spec.shape}_"
                f"{spec.print_mode}{ext}"
            )
        return out_dir / f"{spec.product_type}_{spec.print_mode}{ext}"

    def _update_export_path(self) -> None:
        self.export_path_var.set(str(self._default_export_path()))
        self._sync_export_labels()

    def _sync_export_labels(self) -> None:
        mode = self.print_mode_var.get()
        ext = PRINT_MODE_EXT.get(mode, ".stl").upper().lstrip(".")
        self.export_label_var.set(f"Export {ext} path")
        self.export_btn_var.set(f"Export {ext}")

    def _update_cmyw_hint(self) -> None:
        if self.print_mode_var.get() == "four_color":
            self.cmyw_hint_var.set(
                "Filaments: Cyan（青） · Magenta（洋红） · Yellow（黄） · White（白）"
            )
        elif self.print_mode_var.get() == "layer_art":
            self.cmyw_hint_var.set("Stacked color layers → assign each object in AMS")
        else:
            self.cmyw_hint_var.set("Translucent white PETG / PLA · backlit lithophane")

    def _on_product_change(self) -> None:
        product = self.product_var.get()
        spec = apply_product_preset(KeychainSpec(), product)
        hint = PRODUCT_PRESETS[product].get("hint", "")
        self.product_hint_var.set(str(hint))
        self.size_var.set(spec.size_mm)
        self.hole_var.set(spec.hole_diameter_mm)
        self.rim_var.set(spec.rim_mm)
        self.min_t_var.set(spec.min_thickness_mm)
        self.max_t_var.set(spec.max_thickness_mm)
        self.base_var.set(spec.base_thickness_mm)
        self.ppm_var.set(spec.pixels_per_mm)
        self.corner_var.set(spec.corner_radius_mm)
        self.shape_var.set(spec.shape)
        self.print_mode_var.set(spec.print_mode)
        self._update_cmyw_hint()
        self._update_export_path()
        self._on_param_change()

    def _on_print_mode_change(self) -> None:
        self._update_cmyw_hint()
        self._update_export_path()
        self._on_param_change()

    def _on_shape_change(self) -> None:
        self._update_export_path()
        self._on_param_change()

    def _browse_export_path(self) -> None:
        spec = self._current_spec()
        ext = spec.export_ext
        initial = Path(self.export_path_var.get().strip() or self._default_export_path())
        initial_dir = initial.parent if initial.parent.exists() else Path.cwd()
        if ext == ".3mf":
            filetypes = [("3MF", "*.3mf"), ("All files", "*.*")]
            title = "Choose export 3MF path"
        else:
            filetypes = [("STL", "*.stl"), ("All files", "*.*")]
            title = "Choose export STL path"
        path = filedialog.asksaveasfilename(
            title=title,
            defaultextension=ext,
            initialdir=str(initial_dir),
            initialfile=initial.name,
            filetypes=filetypes,
        )
        if path:
            self.export_path_var.set(path)

    def _resolve_export_path(self) -> Path | None:
        raw = self.export_path_var.get().strip()
        if not raw:
            messagebox.showwarning("Export path", "Please set an export file path.")
            return None
        out = Path(raw).expanduser()
        ext = self._current_spec().export_ext
        if out.suffix.lower() != ext:
            out = out.with_suffix(ext)
            self.export_path_var.set(str(out))
        if not out.parent.exists():
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(
                    "Export path", f"Cannot create folder:\n{out.parent}\n\n{exc}"
                )
                return None
        return out

    def _current_spec(self) -> KeychainSpec:
        product = self.product_var.get()
        collar = float(
            PRODUCT_PRESETS.get(product, {}).get("hole_collar_mm", 1.6)
        )
        return KeychainSpec(
            size_mm=float(self.size_var.get()),
            shape=self.shape_var.get(),
            product_type=product,
            print_mode=self.print_mode_var.get(),
            hole_diameter_mm=float(self.hole_var.get()),
            rim_mm=float(self.rim_var.get()),
            min_thickness_mm=float(self.min_t_var.get()),
            max_thickness_mm=float(self.max_t_var.get()),
            base_thickness_mm=float(self.base_var.get()),
            pixels_per_mm=float(self.ppm_var.get()),
            hole_collar_mm=collar,
            corner_radius_mm=float(self.corner_var.get()),
            contrast=float(self.contrast_var.get()),
            invert=bool(self.invert_var.get()),
        )

    def _on_param_change(self) -> None:
        if self._busy:
            return
        # Param change → go back to live photo preview
        self._view_mode.set("photo")
        if self._preview_after is not None:
            self.after_cancel(self._preview_after)
        self._preview_after = self.after(80, self._refresh_preview)

    def _open_photo(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose customer photo",
            filetypes=[
                ("Images", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.photo_path = Path(path)
        self._last_result = None
        self._view_mode.set("photo")
        self._update_export_path()
        self.status_var.set(f"Loaded: {self.photo_path.name}")
        self._refresh_preview()

    def _export_stl(self) -> None:
        if self._busy:
            return
        if not self.photo_path or not self.photo_path.is_file():
            messagebox.showwarning("No photo", "Please open a customer photo first.")
            return

        spec = self._current_spec()
        if spec.min_thickness_mm >= spec.max_thickness_mm:
            messagebox.showerror("Invalid thickness", "Min thickness must be less than max.")
            return

        out = self._resolve_export_path()
        if out is None:
            return

        self._busy = True
        self.status_var.set(f"Generating → {out.name}…")
        self.update_idletasks()

        logs: list[str] = []
        export_path = out

        def work() -> None:
            try:
                result = generate_keychain(
                    self.photo_path,  # type: ignore[arg-type]
                    export_path,
                    spec,
                    log=logs.append,
                    save_preview=True,
                )
                self.after(0, lambda: self._on_done(True, result, "\n".join(logs)))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._on_done(False, None, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _on_done(
        self, ok: bool, result: GenerateResult | None, detail: str
    ) -> None:
        self._busy = False
        if ok and result:
            self._last_result = result
            self.export_path_var.set(str(result.output_path))
            self._view_mode.set("result")
            self._show_result_in_panel(result)
            self.status_var.set(f"Saved: {result.output_path.name}")
            ResultPreviewWindow(self, result, self.photo_path or result.output_path)
        else:
            self.status_var.set("Generation failed.")
            messagebox.showerror("Error", detail)

    def _show_current_view(self) -> None:
        if self._view_mode.get() == "result" and self._last_result is not None:
            self._show_result_in_panel(self._last_result)
        else:
            self._refresh_preview()

    def _show_result_in_panel(self, result: GenerateResult) -> None:
        self.update_idletasks()
        max_w = max(280, self.preview_label.winfo_width() or 420)
        max_h = max(280, self.preview_label.winfo_height() or 420)
        max_w, max_h = min(max_w, 560), min(max_h, 560)

        img = result.preview_image.copy()
        img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        self._result_photo = ImageTk.PhotoImage(img)
        self.preview_label.configure(image=self._result_photo)

    def _refresh_preview(self) -> None:
        if self._view_mode.get() == "result" and self._last_result is not None:
            self._show_result_in_panel(self._last_result)
            self._preview_after = None
            return

        spec = self._current_spec()
        self.update_idletasks()
        max_w = max(280, self.preview_label.winfo_width() or 420)
        max_h = max(280, self.preview_label.winfo_height() or 420)
        max_w, max_h = min(max_w, 560), min(max_h, 560)

        w_mm, h_mm = shape_bounds(spec.shape, spec.size_mm)
        aspect = w_mm / h_mm
        if max_w / max_h > aspect:
            ph = max_h
            pw = int(ph * aspect)
        else:
            pw = max_w
            ph = int(pw / aspect)

        canvas = Image.new("RGB", (pw, ph), (42, 41, 38))

        if self.photo_path and self.photo_path.is_file():
            try:
                photo = Image.open(self.photo_path)
                photo = ImageOps.exif_transpose(photo)
                photo = photo.convert("RGB")
                target_aspect = w_mm / h_mm
                w, h = photo.size
                src_aspect = w / h
                if src_aspect > target_aspect:
                    nw = int(h * target_aspect)
                    left = (w - nw) // 2
                    photo = photo.crop((left, 0, left + nw, h))
                else:
                    nh = int(w / target_aspect)
                    top = (h - nh) // 2
                    photo = photo.crop((0, top, w, top + nh))
                photo = photo.resize((pw, ph), Image.Resampling.LANCZOS)
                canvas = photo
            except OSError:
                pass

        overlay = shape_mask_preview(spec, width_px=pw, height_px=ph)
        outside = Image.new("RGBA", (pw, ph), (42, 41, 38, 210))
        alpha = overlay.split()[-1]
        base = canvas.convert("RGBA")
        darkened = Image.alpha_composite(base, outside)
        shaped = Image.composite(base, darkened, alpha)
        rim_layer = overlay.copy()
        shaped = Image.alpha_composite(shaped, rim_layer)

        draw = ImageDraw.Draw(shaped)
        draw.rectangle((0, 0, pw - 1, ph - 1), outline=(90, 88, 82), width=1)

        label = f"{SHAPE_LABELS.get(spec.shape, spec.shape)}  ·  {w_mm:.0f}×{h_mm:.0f} mm"
        draw.rectangle((8, ph - 28, 8 + 8 * len(label), ph - 8), fill=(20, 20, 18, 160))
        draw.text((12, ph - 26), label, fill=(240, 238, 232))

        self._preview_photo = ImageTk.PhotoImage(shaped.convert("RGB"))
        self.preview_label.configure(image=self._preview_photo)
        self._preview_after = None


def run_gui() -> None:
    app = KeychainApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
