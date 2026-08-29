#!/usr/bin/env python3
"""
Lithophane Keychain Generator — Rev 2.0
Copyright © 2026 NovaForge Innovations LLC. All rights reserved.

Customer photo → keychain + hole + lithophane → STL (Bambu Studio ready)

Usage (always use the project venv):
  ./venv/bin/python keychain.py
  source venv/bin/activate && python keychain.py
  ./run.sh
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _reexec_with_venv() -> None:
    """If launched with system Python, switch to ./venv/bin/python."""
    root = Path(__file__).resolve().parent
    venv_python = root / "venv" / "bin" / "python"
    if not venv_python.exists():
        return
    if Path(sys.executable).resolve() == venv_python.resolve():
        return
    os.execv(str(venv_python), [str(venv_python), *sys.argv])


_reexec_with_venv()

import argparse
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
from stl import mesh

from app_info import APP_NAME, COPYRIGHT, REV


# ---------------------------------------------------------------------------
# Spec & shapes
# ---------------------------------------------------------------------------

SHAPES = ("circle", "oval", "rounded_square", "rectangle", "heart", "hexagon")

SHAPE_LABELS = {
    "circle": "Circle",
    "oval": "Oval",
    "rounded_square": "Rounded Square",
    "rectangle": "Rectangle",
    "heart": "Heart",
    "hexagon": "Hexagon",
}

PRINT_MODES = ("white", "four_color", "layer_art")

PRINT_MODE_LABELS = {
    "white": "White Lithophane",
    "four_color": "4-Color Lithophane (CMYW)",
    "layer_art": "Color Layer Art",
}

PRINT_MODE_EXT = {
    "white": ".stl",
    "four_color": ".3mf",
    "layer_art": ".3mf",
}


@dataclass
class KeychainSpec:
    size_mm: float = 45.0  # major dimension (diameter / width)
    shape: str = "circle"
    print_mode: str = "white"  # white | four_color | layer_art
    hole_diameter_mm: float = 4.5
    rim_mm: float = 3.0
    min_thickness_mm: float = 0.8
    max_thickness_mm: float = 2.8
    base_thickness_mm: float = 0.4
    pixels_per_mm: float = 4.0
    hole_collar_mm: float = 1.6
    corner_radius_mm: float = 6.0  # rounded_square / rectangle
    contrast: float = 1.15
    invert: bool = False

    # Backward-compatible alias used by older CLI flags
    @property
    def diameter_mm(self) -> float:
        return self.size_mm

    @property
    def export_ext(self) -> str:
        return PRINT_MODE_EXT.get(self.print_mode, ".stl")


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

ContainsFn = Callable[[float, float], bool]


# ---------------------------------------------------------------------------
# Shape geometry
# ---------------------------------------------------------------------------

def shape_bounds(shape: str, size_mm: float) -> tuple[float, float]:
    """Return (width, height) of the axis-aligned bounding box in mm."""
    if shape == "circle":
        return size_mm, size_mm
    if shape == "oval":
        return size_mm, size_mm * 0.78
    if shape == "rounded_square":
        return size_mm, size_mm
    if shape == "rectangle":
        return size_mm, size_mm * 0.72
    if shape == "heart":
        return size_mm, size_mm * 0.95
    if shape == "hexagon":
        # flat-to-flat = size → vertex-to-vertex = size / cos(30°)
        return size_mm / math.cos(math.pi / 6), size_mm
    raise ValueError(f"Unknown shape: {shape}")


def _rounded_rect_contains(
    x: float, y: float, half_w: float, half_h: float, radius: float
) -> bool:
    ax, ay = abs(x), abs(y)
    if ax > half_w or ay > half_h:
        return False
    r = min(radius, half_w, half_h)
    ix, iy = half_w - r, half_h - r
    if ax <= ix or ay <= iy:
        return True
    return (ax - ix) ** 2 + (ay - iy) ** 2 <= r * r


def _heart_contains(x: float, y: float, size_mm: float) -> bool:
    """Implicit heart, scaled so bounding width ≈ size_mm."""
    # Classic: (x²+y²-1)³ - x²y³ ≤ 0, x∈[-1.2,1.2] approx
    s = size_mm / 2.4
    u, v = x / s, y / s
    # Shift up slightly so lobes sit nicer in the bbox
    v = v - 0.15
    return (u * u + v * v - 1.0) ** 3 - (u * u) * (v ** 3) <= 0.0


def _hexagon_contains(x: float, y: float, size_mm: float) -> bool:
    """Regular hexagon, flat-to-flat = size_mm, flat top."""
    R = (size_mm / 2.0) / math.cos(math.pi / 6)
    ax = abs(x)
    ay = abs(y)
    if ay > R * math.cos(math.pi / 6):
        return False
    return ax <= R - ay * math.tan(math.pi / 6)


def make_contains(spec: KeychainSpec) -> ContainsFn:
    shape = spec.shape
    size = spec.size_mm
    w, h = shape_bounds(shape, size)
    hw, hh = w / 2.0, h / 2.0

    if shape == "circle":
        r2 = (size / 2.0) ** 2

        def contains(x: float, y: float) -> bool:
            return x * x + y * y <= r2

        return contains

    if shape == "oval":
        a2, b2 = hw * hw, hh * hh

        def contains(x: float, y: float) -> bool:
            return (x * x) / a2 + (y * y) / b2 <= 1.0

        return contains

    if shape == "rounded_square":
        rad = min(spec.corner_radius_mm, hw, hh)

        def contains(x: float, y: float) -> bool:
            return _rounded_rect_contains(x, y, hw, hh, rad)

        return contains

    if shape == "rectangle":
        rad = min(spec.corner_radius_mm * 0.5, hw, hh)

        def contains(x: float, y: float) -> bool:
            return _rounded_rect_contains(x, y, hw, hh, rad)

        return contains

    if shape == "heart":

        def contains(x: float, y: float) -> bool:
            return _heart_contains(x, y, size)

        return contains

    if shape == "hexagon":

        def contains(x: float, y: float) -> bool:
            return _hexagon_contains(x, y, size)

        return contains

    raise ValueError(f"Unknown shape: {shape}")


def clamp_to_outline(x: float, y: float, contains: ContainsFn) -> tuple[float, float]:
    """Project a point outside the shape onto the outline (ray from origin)."""
    if contains(x, y):
        return x, y
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        # Degenerate — nudge up
        for t in np.linspace(0.01, 1.0, 40):
            if contains(0.0, float(t)):
                return 0.0, float(t)
        return x, y
    lo, hi = 0.0, 1.0
    # If origin is outside (shouldn't happen), search outward then inward
    origin_inside = contains(0.0, 0.0)
    if not origin_inside:
        # find any inside point near (x,y) direction at small radius
        for s in np.linspace(0.05, 1.0, 30):
            if contains(x * float(s), y * float(s)):
                lo = float(s)
                break
        else:
            return x, y
    for _ in range(28):
        mid = 0.5 * (lo + hi)
        if contains(x * mid, y * mid):
            lo = mid
        else:
            hi = mid
    return x * lo, y * lo


def clamp_out_of_hole(
    x: float, y: float, hx: float, hy: float, hr: float
) -> tuple[float, float]:
    dh = math.hypot(x - hx, y - hy)
    if dh >= hr:
        return x, y
    if dh < 1e-12:
        return hx, hy + hr
    s = hr / dh
    return hx + (x - hx) * s, hy + (y - hy) * s


def is_rim_point(x: float, y: float, rim_mm: float, contains: ContainsFn) -> bool:
    if not contains(x, y):
        return False
    for k in range(16):
        a = (2.0 * math.pi * k) / 16.0
        if not contains(x + rim_mm * math.cos(a), y + rim_mm * math.sin(a)):
            return True
    return False


def hole_center_for_shape(
    spec: KeychainSpec, contains: ContainsFn
) -> tuple[float, float]:
    """Place keyring hole near the top, with solid plastic around it."""
    w, h = shape_bounds(spec.shape, spec.size_mm)
    hr = spec.hole_diameter_mm / 2.0
    clearance = hr + 1.2
    # Walk down from top until the hole disk fits inside the outline
    for y in np.linspace(h / 2.0 - clearance, 0.0, 80):
        cy = float(y)
        ok = True
        for k in range(12):
            a = (2.0 * math.pi * k) / 12.0
            px = hr * math.cos(a)
            py = cy + hr * math.sin(a)
            # also require a little outer wall
            ox = (hr + 1.0) * math.cos(a)
            oy = cy + (hr + 1.0) * math.sin(a)
            if not contains(px, py) or not contains(ox, oy):
                ok = False
                break
        if ok:
            return 0.0, cy
    # Fallback
    return 0.0, h / 2.0 - clearance


def shape_mask_preview(
    spec: KeychainSpec, width_px: int = 280, height_px: int | None = None
) -> Image.Image:
    """RGBA silhouette for GUI preview overlay."""
    w_mm, h_mm = shape_bounds(spec.shape, spec.size_mm)
    if height_px is None:
        height_px = max(1, int(round(width_px * (h_mm / w_mm))))

    # Render cheap low-res mask, then upscale for UI
    scale = max(width_px, height_px) / 160.0
    rw = max(32, int(round(width_px / max(scale, 1.0))))
    rh = max(32, int(round(height_px / max(scale, 1.0))))

    contains = make_contains(spec)
    hx, hy = hole_center_for_shape(spec, contains)
    hr = spec.hole_diameter_mm / 2.0

    xs = (np.linspace(0.0, 1.0, rw) - 0.5) * w_mm
    ys = (0.5 - np.linspace(0.0, 1.0, rh)) * h_mm
    xx, yy = np.meshgrid(xs, ys)

    body = np.fromiter(
        (contains(float(x), float(y)) for x, y in zip(xx.ravel(), yy.ravel())),
        dtype=bool,
        count=rw * rh,
    ).reshape(rh, rw)
    hole = np.hypot(xx - hx, yy - hy) < hr
    inside = body & ~hole

    step = max(spec.rim_mm, 0.5)
    rim = np.zeros_like(inside)
    for dx, dy in (
        (step, 0.0),
        (-step, 0.0),
        (0.0, step),
        (0.0, -step),
        (step * 0.7, step * 0.7),
        (-step * 0.7, step * 0.7),
        (step * 0.7, -step * 0.7),
        (-step * 0.7, -step * 0.7),
    ):
        sample = np.fromiter(
            (
                (not contains(float(x + dx), float(y + dy))) if inn else False
                for x, y, inn in zip(xx.ravel(), yy.ravel(), inside.ravel())
            ),
            dtype=bool,
            count=rw * rh,
        ).reshape(rh, rw)
        rim |= sample

    collar = inside & (np.hypot(xx - hx, yy - hy) <= hr + spec.hole_collar_mm)
    solid = rim | collar

    rgba = np.zeros((rh, rw, 4), dtype=np.uint8)
    rgba[inside] = (220, 220, 230, 90)
    rgba[solid] = (40, 40, 45, 200)
    img = Image.fromarray(rgba, "RGBA")
    if (rw, rh) != (width_px, height_px):
        img = img.resize((width_px, height_px), Image.Resampling.NEAREST)
    return img


# ---------------------------------------------------------------------------
# Image → height field
# ---------------------------------------------------------------------------

def prepare_image(
    path: Path,
    width_px: int,
    height_px: int,
    contrast: float = 1.15,
    invert: bool = False,
) -> np.ndarray:
    """Load, aspect-crop, enhance → grayscale float array [0,1] shaped (H, W)."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")

    target_aspect = width_px / height_px
    w, h = img.size
    src_aspect = w / h
    if src_aspect > target_aspect:
        new_w = int(round(h * target_aspect))
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(round(w / target_aspect))
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))

    img = img.resize((width_px, height_px), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=80, threshold=2))
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)

    arr = np.asarray(img, dtype=np.float64) / 255.0
    if invert:
        arr = 1.0 - arr
    return arr


def prepare_color_image(
    path: Path,
    width_px: int,
    height_px: int,
    contrast: float = 1.15,
) -> np.ndarray:
    """Load → RGB uint8 array shaped (H, W, 3)."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")

    target_aspect = width_px / height_px
    w, h = img.size
    src_aspect = w / h
    if src_aspect > target_aspect:
        new_w = int(round(h * target_aspect))
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(round(w / target_aspect))
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))

    img = img.resize((width_px, height_px), Image.Resampling.LANCZOS)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    return np.asarray(img, dtype=np.uint8)


def brightness_to_thickness(
    brightness: np.ndarray, min_t: float, max_t: float
) -> np.ndarray:
    return min_t + (1.0 - brightness) * (max_t - min_t)


def grid_and_body_masks(
    spec: KeychainSpec,
) -> tuple[int, int, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return nx, ny, xs, ys, body, solid masks for the keychain outline."""
    w_mm, h_mm = shape_bounds(spec.shape, spec.size_mm)
    nx = max(48, int(round(w_mm * spec.pixels_per_mm)))
    ny = max(48, int(round(h_mm * spec.pixels_per_mm)))
    if nx % 2 == 0:
        nx += 1
    if ny % 2 == 0:
        ny += 1

    contains = make_contains(spec)
    hole_r = spec.hole_diameter_mm / 2.0
    hole_cx, hole_cy = hole_center_for_shape(spec, contains)

    xs_1d = np.linspace(-w_mm / 2.0, w_mm / 2.0, nx)
    ys_1d = np.linspace(-h_mm / 2.0, h_mm / 2.0, ny)
    xs, ys = np.meshgrid(xs_1d, ys_1d)
    hole_dist = np.hypot(xs - hole_cx, ys - hole_cy)

    body = np.zeros((ny, nx), dtype=bool)
    solid = np.zeros((ny, nx), dtype=bool)
    for i in range(ny):
        for j in range(nx):
            x, y = float(xs[i, j]), float(ys[i, j])
            if contains(x, y) and hole_dist[i, j] >= hole_r:
                body[i, j] = True
                if is_rim_point(x, y, spec.rim_mm, contains) or hole_dist[
                    i, j
                ] <= hole_r + spec.hole_collar_mm:
                    solid[i, j] = True
    return nx, ny, xs, ys, body, solid


# ---------------------------------------------------------------------------
# Mesh builder
# ---------------------------------------------------------------------------

def build_slab_mesh_triangles(
    xs: np.ndarray,
    ys: np.ndarray,
    top_z: np.ndarray,
    z_bottom: float,
    active: np.ndarray,
    *,
    min_corners: int = 2,
    cell_mask: np.ndarray | None = None,
) -> np.ndarray | None:
    """
    Build watertight triangle array (N,3,3) for a height field slab.

    A grid cell is included when:
      - cell_mask[i,j] is True (if provided), else
      - at least `min_corners` of its 4 vertices are in `active`
    and the mean top height is above z_bottom.

    Corner vertices missing from `active` inherit height from active
    corners of the same cell so boundaries stay printable.
    """
    ny, nx = top_z.shape
    top = top_z.astype(np.float64, copy=True)

    cells = np.zeros((ny - 1, nx - 1), dtype=bool)
    if cell_mask is not None:
        if cell_mask.shape != (ny - 1, nx - 1):
            raise ValueError("cell_mask shape must be (ny-1, nx-1)")
        cells[:, :] = cell_mask
    else:
        for i in range(ny - 1):
            for j in range(nx - 1):
                corners = (
                    int(active[i, j])
                    + int(active[i, j + 1])
                    + int(active[i + 1, j])
                    + int(active[i + 1, j + 1])
                )
                if corners >= min_corners:
                    cells[i, j] = True

    # Drop flat / empty cells; lift inactive corners on kept cells
    for i in range(ny - 1):
        for j in range(nx - 1):
            if not cells[i, j]:
                continue
            zs = [
                top[i, j],
                top[i, j + 1],
                top[i + 1, j],
                top[i + 1, j + 1],
            ]
            acts = [
                bool(active[i, j]),
                bool(active[i, j + 1]),
                bool(active[i + 1, j]),
                bool(active[i + 1, j + 1]),
            ]
            active_zs = [z for z, a in zip(zs, acts) if a and z > z_bottom + 1e-9]
            if not active_zs:
                # cell_mask path: use any top above bottom
                active_zs = [z for z in zs if z > z_bottom + 1e-9]
            if not active_zs:
                cells[i, j] = False
                continue
            fill = float(max(active_zs))
            if 0.25 * sum(zs) <= z_bottom + 1e-6 and fill <= z_bottom + 1e-6:
                cells[i, j] = False
                continue
            # Ensure all four corners have printable height for this cell
            for di, dj in ((0, 0), (0, 1), (1, 0), (1, 1)):
                if top[i + di, j + dj] <= z_bottom + 1e-9:
                    top[i + di, j + dj] = fill

    if not np.any(cells):
        return None

    used = np.zeros((ny, nx), dtype=bool)
    used[:-1, :-1] |= cells
    used[:-1, 1:] |= cells
    used[1:, :-1] |= cells
    used[1:, 1:] |= cells

    def tid(i: int, j: int) -> int:
        return i * nx + j

    def bid(i: int, j: int) -> int:
        return ny * nx + i * nx + j

    vertices: list[list[float]] = []
    for i in range(ny):
        for j in range(nx):
            z = float(top[i, j]) if used[i, j] else float(z_bottom)
            vertices.append([float(xs[i, j]), float(ys[i, j]), z])
    for i in range(ny):
        for j in range(nx):
            vertices.append([float(xs[i, j]), float(ys[i, j]), float(z_bottom)])

    faces: list[list[int]] = []

    def add_quad(a: int, b: int, c: int, d: int) -> None:
        faces.append([a, b, c])
        faces.append([a, c, d])

    def add_wall(i0: int, j0: int, i1: int, j1: int, outward_flip: bool) -> None:
        if outward_flip:
            add_quad(tid(i0, j0), tid(i1, j1), bid(i1, j1), bid(i0, j0))
        else:
            add_quad(tid(i0, j0), bid(i0, j0), bid(i1, j1), tid(i1, j1))

    for i in range(ny - 1):
        for j in range(nx - 1):
            if not cells[i, j]:
                continue
            add_quad(tid(i, j), tid(i, j + 1), tid(i + 1, j + 1), tid(i + 1, j))
            add_quad(bid(i, j), bid(i + 1, j), bid(i + 1, j + 1), bid(i, j + 1))

            right = cells[i, j + 1] if j + 1 < nx - 1 else False
            if not right:
                add_wall(i, j + 1, i + 1, j + 1, outward_flip=False)

            left = cells[i, j - 1] if j > 0 else False
            if not left:
                add_wall(i, j, i + 1, j, outward_flip=True)

            up = cells[i + 1, j] if i + 1 < ny - 1 else False
            if not up:
                add_wall(i + 1, j, i + 1, j + 1, outward_flip=False)

            down = cells[i - 1, j] if i > 0 else False
            if not down:
                add_wall(i, j, i, j + 1, outward_flip=True)

    verts = np.asarray(vertices, dtype=np.float64)
    tris = np.asarray([verts[f] for f in faces], dtype=np.float64)
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    signed_vol = float(np.sum(np.cross(v0, v1) * v2) / 6.0)
    if signed_vol < 0:
        tris[:, [1, 2]] = tris[:, [2, 1]]
    return tris


def build_lithophane_mesh(height: np.ndarray, spec: KeychainSpec) -> mesh.Mesh:
    """
    Watertight STL from height field.
    X/Y centered, hole near +Y, Z=0 flat back.
    """
    ny, nx = height.shape
    w_mm, h_mm = shape_bounds(spec.shape, spec.size_mm)
    contains = make_contains(spec)
    hole_r = spec.hole_diameter_mm / 2.0
    hole_cx, hole_cy = hole_center_for_shape(spec, contains)

    xs_1d = np.linspace(-w_mm / 2.0, w_mm / 2.0, nx)
    ys_1d = np.linspace(-h_mm / 2.0, h_mm / 2.0, ny)
    xs, ys = np.meshgrid(xs_1d, ys_1d)

    litho_t = brightness_to_thickness(
        height, spec.min_thickness_mm, spec.max_thickness_mm
    )
    hole_dist = np.hypot(xs - hole_cx, ys - hole_cy)

    solid = np.zeros_like(height, dtype=bool)
    body = np.zeros_like(height, dtype=bool)
    for i in range(ny):
        for j in range(nx):
            x, y = float(xs[i, j]), float(ys[i, j])
            if contains(x, y) and hole_dist[i, j] >= hole_r:
                body[i, j] = True
                if is_rim_point(x, y, spec.rim_mm, contains) or hole_dist[
                    i, j
                ] <= hole_r + spec.hole_collar_mm:
                    solid[i, j] = True

    top_z = np.where(
        solid,
        spec.base_thickness_mm + spec.max_thickness_mm,
        spec.base_thickness_mm + litho_t,
    )
    top_z = np.where(body, top_z, 0.0)

    # Clamp boundary vertices for cleaner outline
    cells = np.zeros((ny - 1, nx - 1), dtype=bool)
    for i in range(ny - 1):
        for j in range(nx - 1):
            cx = 0.5 * (xs[i, j] + xs[i + 1, j + 1])
            cy = 0.5 * (ys[i, j] + ys[i + 1, j + 1])
            cells[i, j] = contains(cx, cy) and math.hypot(
                cx - hole_cx, cy - hole_cy
            ) >= hole_r

    used = np.zeros((ny, nx), dtype=bool)
    used[:-1, :-1] |= cells
    used[:-1, 1:] |= cells
    used[1:, :-1] |= cells
    used[1:, 1:] |= cells
    for i in range(ny):
        for j in range(nx):
            if not used[i, j]:
                continue
            x, y = float(xs[i, j]), float(ys[i, j])
            if not contains(x, y):
                x, y = clamp_to_outline(x, y, contains)
            x, y = clamp_out_of_hole(x, y, hole_cx, hole_cy, hole_r)
            xs[i, j], ys[i, j] = x, y

    tris = build_slab_mesh_triangles(xs, ys, top_z, z_bottom=0.0, active=body)
    if tris is None:
        raise RuntimeError("No faces generated — check image / size settings.")

    data = np.zeros(len(tris), dtype=mesh.Mesh.dtype)
    stl_mesh = mesh.Mesh(data)
    stl_mesh.vectors[:] = tris
    stl_mesh.update_normals()
    return stl_mesh


# ---------------------------------------------------------------------------
# Preview rendering (backlit lithophane simulation)
# ---------------------------------------------------------------------------

@dataclass
class GenerateResult:
    output_path: Path
    preview_path: Path | None
    preview_image: Image.Image
    print_mode: str = "white"

    @property
    def stl_path(self) -> Path:
        """Backward-compatible alias."""
        return self.output_path


def _body_and_solid_masks(
    ny: int, nx: int, xs: np.ndarray, ys: np.ndarray, spec: KeychainSpec
) -> tuple[np.ndarray, np.ndarray]:
    contains = make_contains(spec)
    hole_r = spec.hole_diameter_mm / 2.0
    hole_cx, hole_cy = hole_center_for_shape(spec, contains)
    hole_dist = np.hypot(xs - hole_cx, ys - hole_cy)

    body = np.zeros((ny, nx), dtype=bool)
    solid = np.zeros((ny, nx), dtype=bool)
    for i in range(ny):
        for j in range(nx):
            x, y = float(xs[i, j]), float(ys[i, j])
            if contains(x, y) and hole_dist[i, j] >= hole_r:
                body[i, j] = True
                if is_rim_point(x, y, spec.rim_mm, contains) or hole_dist[
                    i, j
                ] <= hole_r + spec.hole_collar_mm:
                    solid[i, j] = True
    return body, solid


def render_result_preview(
    image_path: Path,
    spec: KeychainSpec,
    preview_width: int = 720,
) -> Image.Image:
    """
    Build a side-by-side preview: source (in shape) | backlit lithophane simulation.
    """
    w_mm, h_mm = shape_bounds(spec.shape, spec.size_mm)
    # Use a moderate grid for a sharp but fast preview
    ppm = min(spec.pixels_per_mm, 5.0)
    nx = max(64, int(round(w_mm * ppm)))
    ny = max(64, int(round(h_mm * ppm)))
    if nx % 2 == 0:
        nx += 1
    if ny % 2 == 0:
        ny += 1

    height = prepare_image(
        image_path, nx, ny, contrast=spec.contrast, invert=spec.invert
    )
    xs_1d = np.linspace(-w_mm / 2.0, w_mm / 2.0, nx)
    ys_1d = np.linspace(-h_mm / 2.0, h_mm / 2.0, ny)
    xs, ys = np.meshgrid(xs_1d, ys_1d)
    body, solid = _body_and_solid_masks(ny, nx, xs, ys, spec)

    litho_t = brightness_to_thickness(
        height, spec.min_thickness_mm, spec.max_thickness_mm
    )
    thickness = np.where(
        solid,
        spec.max_thickness_mm,
        litho_t,
    )
    thickness = np.where(body, thickness, 0.0)

    # Beer–Lambert-ish: thicker → darker when backlit
    t_min = spec.min_thickness_mm
    t_max = spec.max_thickness_mm
    norm = np.clip((thickness - t_min) / max(t_max - t_min, 1e-6), 0.0, 1.0)
    transmit = np.exp(-2.8 * norm)  # 0..1 glow
    transmit = np.where(body, transmit, 0.0)

    # Warm backlit look on dark background
    glow = (transmit * 255.0).astype(np.uint8)
    backlit = np.zeros((ny, nx, 3), dtype=np.uint8)
    backlit[..., 0] = (glow.astype(np.float64) * 1.00).clip(0, 255).astype(np.uint8)
    backlit[..., 1] = (glow.astype(np.float64) * 0.96).clip(0, 255).astype(np.uint8)
    backlit[..., 2] = (glow.astype(np.float64) * 0.88).clip(0, 255).astype(np.uint8)
    # Soft amber fill in mid tones
    mid = (transmit > 0.05) & body
    backlit[mid, 0] = np.maximum(backlit[mid, 0], (glow[mid].astype(np.float64) * 1.05).clip(0, 255).astype(np.uint8))

    # Source panel: grayscale photo inside shape
    src = (np.clip(height, 0, 1) * 255).astype(np.uint8)
    source_rgb = np.stack([src, src, src], axis=-1)
    source_rgb = np.where(body[..., None], source_rgb, 32)

    src_img = Image.fromarray(source_rgb, "RGB")
    lit_img = Image.fromarray(backlit, "RGB")

    # Scale panels to a shared display height
    panel_h = 340
    aspect = w_mm / h_mm
    panel_w = max(1, int(round(panel_h * aspect)))
    src_img = src_img.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
    lit_img = lit_img.resize((panel_w, panel_h), Image.Resampling.LANCZOS)

    gap = 16
    label_h = 36
    pad = 20
    total_w = pad * 2 + panel_w * 2 + gap
    total_h = pad * 2 + label_h + panel_h + 28
    # Stretch if caller wants wider
    if preview_width > total_w:
        scale = preview_width / total_w
        panel_w = int(panel_w * scale)
        panel_h = int(panel_h * scale)
        src_img = src_img.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
        lit_img = lit_img.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
        total_w = pad * 2 + panel_w * 2 + gap
        total_h = pad * 2 + label_h + panel_h + 28

    canvas = Image.new("RGB", (total_w, total_h), (28, 27, 25))
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, pad), "Source (in shape)", fill=(200, 198, 190))
    draw.text((pad + panel_w + gap, pad), "Backlit preview (as printed)", fill=(200, 198, 190))

    y0 = pad + label_h
    canvas.paste(src_img, (pad, y0))
    canvas.paste(lit_img, (pad + panel_w + gap, y0))

    # Thin frames
    draw.rectangle((pad, y0, pad + panel_w - 1, y0 + panel_h - 1), outline=(80, 78, 72))
    draw.rectangle(
        (pad + panel_w + gap, y0, pad + panel_w + gap + panel_w - 1, y0 + panel_h - 1),
        outline=(80, 78, 72),
    )

    footer = (
        f"{SHAPE_LABELS.get(spec.shape, spec.shape)}  ·  "
        f"{w_mm:.0f}×{h_mm:.0f} mm  ·  "
        f"thickness {spec.base_thickness_mm + spec.min_thickness_mm:.1f}"
        f"–{spec.base_thickness_mm + spec.max_thickness_mm:.1f} mm"
    )
    draw.text((pad, total_h - 22), footer, fill=(150, 148, 140))
    return canvas


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def generate_keychain(
    image_path: Path,
    output_path: Path,
    spec: KeychainSpec,
    log: Callable[[str], None] | None = None,
    save_preview: bool = True,
) -> GenerateResult:
    say = log or print
    mode = spec.print_mode if spec.print_mode in PRINT_MODES else "white"
    ext = PRINT_MODE_EXT[mode]
    output_path = Path(output_path)
    if output_path.suffix.lower() != ext:
        output_path = output_path.with_suffix(ext)

    w_mm, h_mm = shape_bounds(spec.shape, spec.size_mm)
    say(f"  image  : {image_path}")
    say(f"  mode   : {PRINT_MODE_LABELS[mode]} → {ext}")
    say(f"  shape  : {SHAPE_LABELS.get(spec.shape, spec.shape)}")
    say(
        f"  size   : {w_mm:.1f}×{h_mm:.1f} mm  hole Ø{spec.hole_diameter_mm} mm  "
        f"thickness {spec.base_thickness_mm + spec.min_thickness_mm:.1f}"
        f"–{spec.base_thickness_mm + spec.max_thickness_mm:.1f} mm"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview_image: Image.Image

    if mode == "white":
        nx = max(48, int(round(w_mm * spec.pixels_per_mm)))
        ny = max(48, int(round(h_mm * spec.pixels_per_mm)))
        if nx % 2 == 0:
            nx += 1
        if ny % 2 == 0:
            ny += 1
        say(f"  mesh   : {nx}×{ny}  ({spec.pixels_per_mm} px/mm)")
        height = prepare_image(
            image_path, nx, ny, contrast=spec.contrast, invert=spec.invert
        )
        stl_mesh = build_lithophane_mesh(height, spec)
        stl_mesh.save(str(output_path))
        mb = output_path.stat().st_size / (1024 * 1024)
        say(f"  saved  : {output_path}  ({mb:.2f} MB, {len(stl_mesh.vectors)} tris)")
        say("  preview: rendering backlit simulation…")
        preview_image = render_result_preview(image_path, spec)
    else:
        from color_modes import export_color_3mf

        say("  mesh   : building multi-color objects…")
        _, preview_image = export_color_3mf(image_path, output_path, spec, mode)
        mb = output_path.stat().st_size / (1024 * 1024)
        say(f"  saved  : {output_path}  ({mb:.2f} MB 3MF)")

    preview_path: Path | None = None
    if save_preview:
        preview_path = output_path.with_name(output_path.stem + "_preview.png")
        preview_image.save(preview_path, format="PNG")
        say(f"  preview: {preview_path}")

    return GenerateResult(
        output_path=output_path,
        preview_path=preview_path,
        preview_image=preview_image,
        print_mode=mode,
    )


def collect_images(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Photo → lithophane keychain STL for Bambu Studio / Etsy",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=COPYRIGHT,
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {REV}\n{COPYRIGHT}",
    )
    p.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=None,
        help="Photo file or folder (omit to open GUI)",
    )
    p.add_argument("-o", "--output", type=Path, default=None, help="Output STL path")
    p.add_argument("--batch", action="store_true", help="Batch folder → ./stl_out/")
    p.add_argument("--gui", action="store_true", help="Open graphical interface")
    p.add_argument(
        "--shape",
        choices=SHAPES,
        default="circle",
        help="Keychain outline shape",
    )
    p.add_argument(
        "--mode",
        choices=PRINT_MODES,
        default="white",
        help="Print mode: white→STL, four_color/layer_art→3MF",
    )
    p.add_argument("--size", "--diameter", type=float, default=45.0, dest="size",
                   help="Major size mm (diameter / width)")
    p.add_argument("--hole", type=float, default=4.5, help="Keyring hole diameter mm")
    p.add_argument("--rim", type=float, default=3.0, help="Solid rim width mm")
    p.add_argument("--min-thickness", type=float, default=0.8)
    p.add_argument("--max-thickness", type=float, default=2.8)
    p.add_argument("--base", type=float, default=0.4)
    p.add_argument("--ppm", type=float, default=4.0)
    p.add_argument("--corner-radius", type=float, default=6.0)
    p.add_argument("--contrast", type=float, default=1.15)
    p.add_argument("--invert", action="store_true")
    return p.parse_args(argv)


def spec_from_args(args: argparse.Namespace) -> KeychainSpec:
    return KeychainSpec(
        size_mm=args.size,
        shape=args.shape,
        print_mode=args.mode,
        hole_diameter_mm=args.hole,
        rim_mm=args.rim,
        min_thickness_mm=args.min_thickness,
        max_thickness_mm=args.max_thickness,
        base_thickness_mm=args.base,
        pixels_per_mm=args.ppm,
        corner_radius_mm=args.corner_radius,
        contrast=args.contrast,
        invert=args.invert,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.gui or args.input is None:
        from gui import run_gui

        run_gui()
        return 0

    spec = spec_from_args(args)

    if args.batch or args.input.is_dir():
        images = collect_images(args.input)
        if not images:
            print(f"No images found in {args.input}", file=sys.stderr)
            return 1
        out_dir = args.output if args.output else Path("stl_out")
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"Batch: {len(images)} image(s) → {out_dir}/")
        for img in images:
            out = out_dir / f"{img.stem}_{spec.shape}_{spec.print_mode}_keychain{spec.export_ext}"
            result = generate_keychain(img, out, spec)
            print()
        return 0

    if not args.input.is_file():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 1

    out = args.output or args.input.with_name(
        f"{args.input.stem}_{spec.shape}_{spec.print_mode}_keychain{spec.export_ext}"
    )
    result = generate_keychain(args.input, out, spec)
    if spec.print_mode == "white":
        print("\nOpen the STL in Bambu Studio. Suggested:")
        print("  • Filament: translucent white PETG or PLA")
        print("  • Layer height: 0.08–0.12 mm  |  Wall: 2–3  |  Infill: 100%")
    else:
        print("\nOpen the 3MF in Bambu Studio:")
        print("  • Each object = one AMS filament (match preview swatches)")
        print("  • Enable multi-color / AMS; layer height 0.08–0.16 mm")
    if result.preview_path:
        print(f"  • Preview image: {result.preview_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
