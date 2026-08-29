# Lithophane Keychain Generator

**Rev 2.1** · © 2026 NovaForge Innovations LLC

Customer photo → **keychain / ornament / lamp** → shaped lithophane → **STL / 3MF** for [Bambu Studio](https://bambulab.com/en/download/studio).

Built for Etsy-style custom orders: load a photo, pick product type & print mode, export, print.

---

## Features

### Product types

| Product | Size | Hole | Use |
|---------|------|------|-----|
| **Keychain** | Ø45 mm | Ø4.5 mm | Etsy keyring orders |
| **Ornament / Photo** | Ø80 mm | Ø4.0 mm | Wall / tree ornament |
| **Lithophane Lamp** | 150 mm | none | LED base / lightbox |

Switching product type in the GUI auto-applies size, hole, rim, thickness, and shape presets (you can still tweak sliders).

| Print Mode | Output | Filament |
|------------|--------|----------|
| **White Lithophane** | `.stl` | Translucent white PETG / PLA |
| **4-Color Lithophane (CMYW)** | `.3mf` | **Cyan（青）+ Magenta（洋红）+ Yellow（黄）+ White（白）** |
| **Color Layer Art** | `.3mf` | 4 stacked AMS colors (dark → light) |

### Shapes
Circle · Oval · Rounded Square · Rectangle · Heart · Hexagon

---

## Requirements

- macOS (GUI / `.app`) or any OS with Python 3.11+
- Python 3.11+
- Dependencies: `numpy`, `Pillow`, `numpy-stl`

---

## Setup

```bash
cd "/path/to/key chain"
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## Run

### GUI (recommended)

```bash
source venv/bin/activate
python keychain.py
# or
python gui.py
```

### macOS App

```bash
./build_app.sh
open "Lithophane Keychain Generator.app"
```

The `.app` must stay next to `venv/` and `gui.py` in the project folder.

### CLI

```bash
# Keychain (default) → STL
python keychain.py photo.jpg --product keychain --mode white -o out.stl

# Ornament
python keychain.py photo.jpg --product ornament -o ornament.stl

# Lamp (no hole, larger)
python keychain.py photo.jpg --product lamp -o lamp.stl

# CMYW 4-color → 3MF
python keychain.py photo.jpg --mode four_color --shape heart -o out.3mf

# Color layer art → 3MF
python keychain.py photo.jpg --mode layer_art --product ornament

# Batch a folder
python keychain.py ./orders/ --batch --product keychain --mode white

python keychain.py --version
```

---

## Print Mode Notes

### White Lithophane → STL
Classic backlit lithophane: bright areas thinner, dark thicker.  
**Bambu tip:** translucent white · layer 0.08–0.12 mm · walls 2–3 · infill 100% · flat on bed or on-edge for sharper layers.

### 4-Color Lithophane (CMYW) → 3MF
Photo is split into **Cyan / Magenta / Yellow / White** regions for AMS.

| Object name (typical) | Filament |
|-----------------------|----------|
| `White_白_Base_Rim` | White |
| `White_白_Highlight` | White |
| `Cyan_青` | Cyan |
| `Magenta_洋红` | Magenta |
| `Yellow_黄` | Yellow |

In Bambu Studio: open the `.3mf` → assign each object to the matching AMS slot.

> **Note:** Regions are exclusive (strongest CMY ink wins; gray/bright → White). This is optimized for AMS paint-by-object, not full overlapping translucent CMY mixing.

### Color Layer Art → 3MF
HueForge-style stacked layers (dark → light), cumulative fill so nothing floats. Assign each `Layer_N` object to an AMS filament using the preview swatches.

---

## Project Layout

```
keychain.py      # Core geometry + CLI + pipeline
gui.py           # Tkinter GUI
color_modes.py   # CMYW + Color Layer Art → 3MF
export_3mf.py    # Multi-object 3MF writer
app_info.py      # Version / copyright
build_app.sh     # Build macOS .app
make_icon.py     # App icon
requirements.txt
stl_out/         # Default export folder (gitignored)
```

---

## GUI Workflow

1. **Open Photo…** — customer image  
2. Choose **Print Mode** (White / CMYW / Layer Art)  
3. Choose **Shape** and tune size / hole / thickness  
4. Confirm **Export path** (or Browse…)  
5. **Export STL** or **Export 3MF**  
6. Review preview → drag file into Bambu Studio  

---

## License / Copyright

```
Copyright © 2026 NovaForge Innovations LLC. All rights reserved.
Lithophane Keychain Generator — Rev 2.0
```

---

## Repository

https://github.com/jackyangsfo/lithophane-keychain
