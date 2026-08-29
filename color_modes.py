"""
Rev 2.1 color print modes: 4-Color Lithophane & Color Layer Art → 3MF.
Copyright © 2026 NovaForge Innovations LLC.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from export_3mf import MeshObject, write_3mf
from keychain import (
    KeychainSpec,
    brightness_to_thickness,
    build_slab_mesh_triangles,
    grid_and_body_masks,
    prepare_color_image,
    prepare_image,
)


def quantize_colors(
    rgb: np.ndarray, body: np.ndarray, n_colors: int = 4
) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """
    Quantize RGB image (H,W,3) uint8 to up to n_colors.
    Returns (label map int, palette RGB list). Labels are -1 outside body.
    Unused palette slots are dropped; labels are remapped densely.
    """
    img = Image.fromarray(rgb, "RGB")
    q = img.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT)
    palette = q.getpalette() or []
    raw = np.asarray(q, dtype=np.int32)

    used = sorted(int(x) for x in np.unique(raw[body]) if x >= 0)
    if not used:
        used = list(range(min(n_colors, 1)))

    colors: list[tuple[int, int, int]] = []
    remap = {}
    for new_i, old_i in enumerate(used):
        r = palette[old_i * 3] if old_i * 3 + 2 < len(palette) else 128
        g = palette[old_i * 3 + 1] if old_i * 3 + 2 < len(palette) else 128
        b = palette[old_i * 3 + 2] if old_i * 3 + 2 < len(palette) else 128
        colors.append((int(r), int(g), int(b)))
        remap[old_i] = new_i

    labels = np.full(raw.shape, -1, dtype=np.int32)
    for old_i, new_i in remap.items():
        labels[raw == old_i] = new_i
    labels = np.where(body, labels, -1)
    return labels, colors


def _luminance(c: tuple[int, int, int]) -> float:
    r, g, b = c
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# Fixed AMS filament set for 4-Color Lithophane
CMYW_CHANNELS = (
    ("White", "白", (255, 255, 255)),
    ("Cyan", "青", (0, 188, 212)),
    ("Magenta", "洋红", (236, 0, 140)),
    ("Yellow", "黄", (255, 214, 0)),
)


def rgb_to_cmyw_labels(
    rgb: np.ndarray, body: np.ndarray, white_lum: float = 0.82, chroma_eps: float = 0.10
) -> tuple[np.ndarray, list[tuple[str, str, tuple[int, int, int]]]]:
    """
    Split photo into CMYW classes for AMS filaments.

    Returns label map: 0=White, 1=Cyan, 2=Magenta, 3=Yellow (−1 outside body),
    and channel metadata (en, zh, rgb).
    """
    rgb_f = rgb.astype(np.float64) / 255.0
    r, g, b = rgb_f[..., 0], rgb_f[..., 1], rgb_f[..., 2]
    # CMY inks (1 − RGB)
    c_amt = 1.0 - r
    m_amt = 1.0 - g
    y_amt = 1.0 - b
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    ink_max = np.maximum(np.maximum(c_amt, m_amt), y_amt)
    ink_min = np.minimum(np.minimum(c_amt, m_amt), y_amt)
    chroma = ink_max - ink_min  # ~0 for gray / white / black

    stack = np.stack([c_amt, m_amt, y_amt], axis=-1)
    dominant = np.argmax(stack, axis=-1) + 1  # 1=C, 2=M, 3=Y
    labels = np.where(body, dominant, -1)

    # Neutral / bright / near-black → White（白） filament
    white_mask = body & (
        (lum >= white_lum) | (chroma <= chroma_eps) | (lum <= 0.08)
    )
    labels = np.where(white_mask, 0, labels)
    labels = np.where(body, labels, -1)
    return labels, list(CMYW_CHANNELS)


def _cell_mask_for_label(
    labels: np.ndarray, body: np.ndarray, solid: np.ndarray, color_idx: int
) -> np.ndarray:
    """Cell belongs to color if top-left (cell origin) vertex matches, and is printable."""
    ny, nx = labels.shape
    cells = np.zeros((ny - 1, nx - 1), dtype=bool)
    # Prefer majority of 4 corners to reduce boundary trenches
    for i in range(ny - 1):
        for j in range(nx - 1):
            corners = (
                labels[i, j],
                labels[i, j + 1],
                labels[i + 1, j],
                labels[i + 1, j + 1],
            )
            printable = (
                body[i, j]
                or body[i, j + 1]
                or body[i + 1, j]
                or body[i + 1, j + 1]
            )
            if not printable:
                continue
            # Skip if entirely in solid rim
            if (
                solid[i, j]
                and solid[i, j + 1]
                and solid[i + 1, j]
                and solid[i + 1, j + 1]
            ):
                continue
            votes = sum(1 for c in corners if c == color_idx)
            if votes >= 2:
                cells[i, j] = True
            elif votes == 1 and corners[0] == color_idx:
                # Keep single-pixel features anchored at cell origin
                cells[i, j] = True
    return cells


def _cell_mask_from_bool(mask: np.ndarray, solid: np.ndarray) -> np.ndarray:
    """Build cell mask with majority vote; exclude fully-solid rim cells."""
    ny, nx = mask.shape
    cells = np.zeros((ny - 1, nx - 1), dtype=bool)
    for i in range(ny - 1):
        for j in range(nx - 1):
            if (
                solid[i, j]
                and solid[i, j + 1]
                and solid[i + 1, j]
                and solid[i + 1, j + 1]
            ):
                continue
            votes = (
                int(mask[i, j])
                + int(mask[i, j + 1])
                + int(mask[i + 1, j])
                + int(mask[i + 1, j + 1])
            )
            if votes >= 2:
                cells[i, j] = True
            elif votes == 1 and mask[i, j]:
                cells[i, j] = True
    return cells


def build_four_color_lithophane(
    image_path: Path, spec: KeychainSpec
) -> tuple[list[MeshObject], Image.Image]:
    """
    CMYW 4-color lithophane for AMS:
      White（白）+ Cyan（青）+ Magenta（洋红）+ Yellow（黄）

    Photo is split by CMY ink strength; bright/low-chroma → White.
    Each filament is a lithophane relief object + shared base/rim in White.
    """
    nx, ny, xs, ys, body, solid = grid_and_body_masks(spec)
    rgb = prepare_color_image(image_path, nx, ny, contrast=spec.contrast)
    gray = prepare_image(image_path, nx, ny, contrast=spec.contrast, invert=spec.invert)
    labels, channels = rgb_to_cmyw_labels(rgb, body)

    litho_t = brightness_to_thickness(
        gray, spec.min_thickness_mm, spec.max_thickness_mm
    )
    base = spec.base_thickness_mm

    meshes: list[MeshObject] = []

    # White base + rim (always present — AMS slot White)
    white_rgb = CMYW_CHANNELS[0][2]
    base_top = np.where(solid, base + spec.max_thickness_mm, np.where(body, base, 0.0))
    base_tris = build_slab_mesh_triangles(
        xs, ys, base_top, z_bottom=0.0, active=body | solid, min_corners=2
    )
    if base_tris is not None:
        meshes.append(
            MeshObject(
                name="White_白_Base_Rim",
                triangles=base_tris,
                color_rgb=white_rgb,
            )
        )

    for idx, (en, zh, color) in enumerate(channels):
        mask = (labels == idx) & body & ~solid
        if not np.any(mask):
            continue
        top = np.where(mask, base + litho_t, 0.0)
        neigh = mask.copy()
        neigh[:-1, :] |= mask[1:, :]
        neigh[1:, :] |= mask[:-1, :]
        neigh[:, :-1] |= mask[:, 1:]
        neigh[:, 1:] |= mask[:, :-1]
        top = np.where(neigh & body & ~solid, np.maximum(top, base + litho_t), top)

        cell_mask = _cell_mask_for_label(labels, body, solid, idx)
        tris = build_slab_mesh_triangles(
            xs,
            ys,
            top,
            z_bottom=base,
            active=neigh & body & ~solid,
            min_corners=2,
            cell_mask=cell_mask,
        )
        if tris is None:
            continue
        # Avoid duplicating pure base-only white if no white relief pixels
        name = f"{en}_{zh}"
        if idx == 0:
            name = f"{en}_{zh}_Highlight"
        meshes.append(MeshObject(name=name, triangles=tris, color_rgb=color))

    preview = _cmyw_preview(rgb, labels, body, solid)
    return meshes, preview


def build_color_layer_art(
    image_path: Path, spec: KeychainSpec
) -> tuple[list[MeshObject], Image.Image]:
    """
    HueForge-style stacked color layers (dark → light), fixed layer height.
    Each layer is cumulative: includes this color and all lighter pixels above,
    so nothing floats in air.
    """
    layer_h = max(0.16, min(0.28, spec.min_thickness_mm * 0.25))
    n_colors = 4
    nx, ny, xs, ys, body, solid = grid_and_body_masks(spec)
    rgb = prepare_color_image(image_path, nx, ny, contrast=spec.contrast)
    labels, palette = quantize_colors(rgb, body, n_colors=n_colors)
    n_colors = len(palette)
    if n_colors == 0:
        raise RuntimeError("No colors found in image body.")

    # Sort colors dark → light for stacking
    order = sorted(range(n_colors), key=lambda i: _luminance(palette[i]))
    # rank[pixel] = stack index (0 = darkest)
    rank = np.full(labels.shape, -1, dtype=np.int32)
    for stack_i, color_idx in enumerate(order):
        rank[labels == color_idx] = stack_i

    base = spec.base_thickness_mm
    meshes: list[MeshObject] = []

    rim_h = base + n_colors * layer_h
    base_top = np.where(body | solid, base, 0.0)
    base_top = np.where(solid, rim_h, base_top)
    base_tris = build_slab_mesh_triangles(
        xs, ys, base_top, z_bottom=0.0, active=body | solid, min_corners=2
    )
    if base_tris is not None:
        meshes.append(
            MeshObject(name="Base_Rim", triangles=base_tris, color_rgb=(30, 30, 30))
        )

    for stack_i, color_idx in enumerate(order):
        color = palette[color_idx]
        # Cumulative: pixels with rank >= stack_i need this layer under them
        # (darkest layer covers all; lighter layers only sit on brighter pixels)
        mask = (rank >= stack_i) & body & ~solid
        if not np.any(mask):
            continue
        z0 = base + stack_i * layer_h
        z1 = z0 + layer_h
        top = np.where(mask, z1, 0.0)
        cell_mask = _cell_mask_from_bool(mask, solid)
        tris = build_slab_mesh_triangles(
            xs,
            ys,
            top,
            z_bottom=z0,
            active=mask,
            min_corners=2,
            cell_mask=cell_mask,
        )
        if tris is None:
            continue
        meshes.append(
            MeshObject(
                name=f"Layer_{stack_i + 1}",
                triangles=tris,
                color_rgb=color,
            )
        )

    preview = _color_preview(
        rgb, labels, palette, body, solid, mode="Color Layer Art", order=order
    )
    return meshes, preview


def export_color_3mf(
    image_path: Path,
    output_path: Path,
    spec: KeychainSpec,
    mode: str,
) -> tuple[Path, Image.Image]:
    if mode == "four_color":
        meshes, preview = build_four_color_lithophane(image_path, spec)
    elif mode == "layer_art":
        meshes, preview = build_color_layer_art(image_path, spec)
    else:
        raise ValueError(f"Unknown color mode: {mode}")
    if not meshes:
        raise RuntimeError("Color export produced no geometry — try another photo.")
    # Base alone is still a valid (if incomplete) export; prefer >=1 color when possible
    if len(meshes) < 2:
        raise RuntimeError(
            "Color export only produced the base plate — try a more colorful photo "
            "or lower Detail (px/mm)."
        )
    write_3mf(output_path, meshes)
    return output_path, preview


def _cmyw_preview(
    rgb: np.ndarray,
    labels: np.ndarray,
    body: np.ndarray,
    solid: np.ndarray,
) -> Image.Image:
    """Preview highlighting Cyan / Magenta / Yellow / White assignment."""
    quantized = np.zeros_like(rgb)
    for i, (_en, _zh, color) in enumerate(CMYW_CHANNELS):
        quantized[labels == i] = color
    quantized[~body] = 32
    quantized[solid] = (200, 200, 200)

    src = Image.fromarray(rgb, "RGB")
    qimg = Image.fromarray(quantized, "RGB")

    panel_h = 320
    h, w, _ = rgb.shape
    aspect = w / max(h, 1)
    panel_w = max(1, int(round(panel_h * aspect)))
    src = src.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
    qimg = qimg.resize((panel_w, panel_h), Image.Resampling.LANCZOS)

    swatch_h = 48
    pad = 16
    gap = 14
    total_w = max(pad * 2 + panel_w * 2 + gap, 720)
    total_h = pad * 2 + 28 + panel_h + swatch_h + 36
    canvas = Image.new("RGB", (total_w, total_h), (28, 27, 25))
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, pad), "Source", fill=(200, 198, 190))
    draw.text(
        (pad + panel_w + gap, pad),
        "CMYW split — Cyan青 + Magenta洋红 + Yellow黄 + White白",
        fill=(200, 198, 190),
    )
    y0 = pad + 28
    canvas.paste(src, (pad, y0))
    canvas.paste(qimg, (pad + panel_w + gap, y0))

    sw_y = y0 + panel_h + 12
    x = pad
    for en, zh, color in CMYW_CHANNELS:
        # High-contrast outline for White swatch
        outline = (90, 90, 90) if en != "White" else (160, 160, 160)
        draw.rectangle((x, sw_y, x + 36, sw_y + 28), fill=color, outline=outline, width=2)
        draw.text((x + 44, sw_y + 2), f"{en}", fill=(240, 238, 232))
        draw.text((x + 44, sw_y + 16), f"（{zh}）", fill=(180, 178, 170))
        x += 160

    draw.text(
        (pad, total_h - 22),
        "Bambu AMS: map each 3MF object to Cyan / Magenta / Yellow / White filament",
        fill=(150, 148, 140),
    )
    return canvas


def _color_preview(
    rgb: np.ndarray,
    labels: np.ndarray,
    palette: list[tuple[int, int, int]],
    body: np.ndarray,
    solid: np.ndarray,
    mode: str,
    order: list[int] | None = None,
) -> Image.Image:
    quantized = np.zeros_like(rgb)
    for i, c in enumerate(palette):
        quantized[labels == i] = c
    quantized[~body] = 32
    quantized[solid] = (60, 60, 65)

    src = Image.fromarray(rgb, "RGB")
    qimg = Image.fromarray(quantized, "RGB")

    panel_h = 320
    h, w, _ = rgb.shape
    aspect = w / max(h, 1)
    panel_w = max(1, int(round(panel_h * aspect)))
    src = src.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
    qimg = qimg.resize((panel_w, panel_h), Image.Resampling.LANCZOS)

    swatch_h = 36
    pad = 16
    gap = 14
    total_w = pad * 2 + panel_w * 2 + gap
    total_h = pad * 2 + 28 + panel_h + swatch_h + 28
    canvas = Image.new("RGB", (total_w, total_h), (28, 27, 25))
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, pad), "Source", fill=(200, 198, 190))
    draw.text((pad + panel_w + gap, pad), f"{mode} (AMS colors)", fill=(200, 198, 190))
    y0 = pad + 28
    canvas.paste(src, (pad, y0))
    canvas.paste(qimg, (pad + panel_w + gap, y0))

    seq = order if order is not None else list(range(len(palette)))
    sw_y = y0 + panel_h + 10
    x = pad
    for stack_i, ci in enumerate(seq):
        c = palette[ci]
        draw.rectangle((x, sw_y, x + 48, sw_y + 22), fill=c, outline=(120, 120, 120))
        draw.text((x + 52, sw_y + 4), f"T{stack_i + 1}", fill=(180, 180, 175))
        x += 90
    draw.text(
        (pad, total_h - 20),
        "Assign each object to an AMS filament in Bambu Studio",
        fill=(150, 148, 140),
    )
    return canvas
