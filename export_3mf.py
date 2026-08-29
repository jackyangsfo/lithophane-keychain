"""
Minimal multi-object 3MF writer for Bambu Studio / AMS color assignment.
Copyright © 2026 NovaForge Innovations LLC.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np


@dataclass
class MeshObject:
    name: str
    triangles: np.ndarray  # (N, 3, 3) float64
    color_rgb: tuple[int, int, int] = (200, 200, 200)


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0"
    Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def _fmt(v: float) -> str:
    return f"{v:.5f}".rstrip("0").rstrip(".") if abs(v) >= 1e-9 else "0"


def _mesh_to_object_xml(obj_id: int, mesh: MeshObject, material_index: int) -> str:
    tris = np.asarray(mesh.triangles, dtype=np.float64)
    if tris.size == 0:
        raise ValueError(f"Mesh '{mesh.name}' has no triangles")

    flat = tris.reshape(-1, 3)
    rounded = np.round(flat, 5)
    uniq, inv = np.unique(rounded, axis=0, return_inverse=True)
    faces = inv.reshape(-1, 3)

    verts_xml = "\n".join(
        f'          <vertex x="{_fmt(x)}" y="{_fmt(y)}" z="{_fmt(z)}"/>'
        for x, y, z in uniq
    )
    tris_xml = "\n".join(
        f'          <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces
    )
    name = escape(mesh.name)
    return f"""      <object id="{obj_id}" name="{name}" type="model" pid="1" pindex="{material_index}">
        <mesh>
          <vertices>
{verts_xml}
          </vertices>
          <triangles>
{tris_xml}
          </triangles>
        </mesh>
      </object>"""


def write_3mf(path: Path, meshes: list[MeshObject]) -> Path:
    """Write a multi-object 3MF. Each mesh becomes a separate printable object."""
    if not meshes:
        raise ValueError("No meshes to write")

    # 3MF material extension: m:basematerials + displaycolor #RRGGBBAA
    basematerials = []
    for m in meshes:
        r, g, b = m.color_rgb
        hex_color = f"#{r:02X}{g:02X}{b:02X}FF"
        basematerials.append(
            f'        <m:base name="{escape(m.name)}" displaycolor="{hex_color}"/>'
        )
    materials_xml = "\n".join(basematerials)

    objects_xml = "\n".join(
        _mesh_to_object_xml(i + 1, m, i) for i, m in enumerate(meshes)
    )
    items_xml = "\n".join(
        f'      <item objectid="{i + 1}"/>' for i in range(len(meshes))
    )

    model = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter"
  xml:lang="en-US"
  xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
  xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">
  <metadata name="Application">Lithophane Keychain Generator Rev 2.0</metadata>
  <metadata name="Copyright">Copyright (c) 2026 NovaForge Innovations LLC</metadata>
  <resources>
    <m:basematerials id="1">
{materials_xml}
    </m:basematerials>
{objects_xml}
  </resources>
  <build>
{items_xml}
  </build>
</model>
"""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", RELS)
        zf.writestr("3D/3dmodel.model", model)
    return path
