#!/usr/bin/env python3
"""Generate a simple .icns icon for the macOS app bundle."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw


def _make_icon_image(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    # Warm charcoal disc (keychain)
    draw.ellipse(
        (pad, pad, size - pad - 1, size - pad - 1),
        fill=(42, 40, 36, 255),
        outline=(210, 180, 120, 255),
        width=max(1, size // 28),
    )
    # Lithophane glow area
    glow = pad + size // 5
    draw.ellipse(
        (glow, glow, size - glow - 1, size - glow - 1),
        fill=(235, 220, 185, 230),
    )
    # Keyring hole near top
    hr = max(2, size // 12)
    cx, cy = size // 2, pad + hr + size // 14
    draw.ellipse(
        (cx - hr, cy - hr, cx + hr, cy + hr),
        fill=(28, 27, 25, 255),
        outline=(210, 180, 120, 255),
        width=max(1, size // 40),
    )
    return img


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def image_to_png_bytes(img: Image.Image) -> bytes:
    img = img.convert("RGBA")
    w, h = img.size
    raw = b"".join(b"\x00" + img.crop((0, y, w, y + 1)).tobytes() for y in range(h))
    compressed = zlib.compress(raw, 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def write_icns(path: Path) -> None:
    # icns types that accept PNG payloads
    entries = [
        ("ic07", 128),
        ("ic08", 256),
        ("ic09", 512),
        ("ic10", 1024),  # 512@2x
        ("ic11", 32),    # 16@2x
        ("ic12", 64),    # 32@2x
        ("ic13", 256),   # 128@2x
        ("ic14", 512),   # 256@2x
    ]
    chunks: list[bytes] = []
    for tag, size in entries:
        png = image_to_png_bytes(_make_icon_image(size))
        chunks.append(tag.encode("ascii") + struct.pack(">I", 8 + len(png)) + png)
    body = b"".join(chunks)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def main() -> None:
    root = Path(__file__).resolve().parent
    out = root / "assets" / "AppIcon.icns"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_icns(out)
    # Also keep a PNG preview
    _make_icon_image(512).save(root / "assets" / "AppIcon.png")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
