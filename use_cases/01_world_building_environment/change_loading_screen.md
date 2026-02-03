# Change Loading Screen

## Overview

This guide covers every step required to create and register a custom loading
screen for a WoW WotLK 3.3.5a (build 12340) zone or dungeon using the
`pywowlib` world builder toolkit. By the end you will have:

- A custom loading screen image in **BLP** format (the WoW texture format)
- A **LoadingScreens.dbc** entry referencing the BLP file
- The **Map.dbc** record linked to the new loading screen
- Both standard (1024x768) and widescreen (2048x1536) variants
- Everything placed at the correct paths inside the **MPQ** archive
- Optional: procedurally generated loading screen art using the built-in
  artwork pipeline (zero manual art tools required)

---

## Prerequisites

| Requirement | Details |
|---|---|
| Python 3.8+ | Standard CPython distribution |
| pywowlib | Cloned and importable (`pip install -e .` from repo root) |
| Pillow | `pip install Pillow` -- required by artwork_pipeline and blp_converter |
| NumPy | `pip install numpy` -- required by artwork_pipeline |
| DBC files | A copy of `DBFilesClient/` from the WoW 3.3.5a client MPQ chain |
| MPQ tool | Native StormLib bindings or an external MPQ editor (ladik's MPQ Editor) |
| Image source | Either a custom PNG image or use the procedural generator |

> **Important**: Back up your DBC directory before running any injection
> functions. The `dbc_injector` module modifies DBC files in place.

---

## How WoW 3.3.5a Handles Loading Screens

When a player enters a zone, dungeon, or teleports between continents, the
client displays a loading screen. The chain of references is:

```
Map.dbc
  field 57: LoadingScreenID  -->  LoadingScreens.dbc
                                    field 2: FileName  -->  BLP file in MPQ
```

### LoadingScreens.dbc

Each record maps a unique ID to a BLP texture path. The client loads the
texture and renders it as a full-screen background while the zone data is
streamed from disk.

### BLP Texture Format

BLP (Blizzard Picture) is the proprietary texture format used by the WoW
client. Key characteristics:

- **BLP2** is the version used by WotLK 3.3.5a
- Supports DXT1, DXT3, DXT5 compression (GPU-native, fast decompression)
- Also supports uncompressed BGRA (larger files but no quality loss)
- Standard loading screen resolution: **1024 x 768** pixels
- Widescreen variant: **2048 x 1536** pixels (same aspect ratio, higher res)
- Files are placed under `Interface\Glues\LoadingScreens\` in the MPQ

### Widescreen Support

LoadingScreens.dbc has a `HasWideScreen` field (index 3). When set to `1`,
the client looks for a widescreen variant of the texture with a `_wide`
suffix. For example:

- Standard: `Interface\Glues\LoadingScreens\MyZone.blp`
- Widescreen: `Interface\Glues\LoadingScreens\MyZone_wide.blp`

If the widescreen variant is missing, the client scales the standard texture.

---

## Step-by-Step Walkthrough

### Step 1 -- Prepare Your Loading Screen Image

You have three options for creating the loading screen image:

#### Option A: Use an Existing PNG File

If you already have artwork, ensure it meets these specifications:

| Property | Standard | Widescreen |
|---|---|---|
| Width | 1024 px | 2048 px |
| Height | 768 px | 1536 px |
| Aspect ratio | 4:3 | 4:3 |
| Colour mode | RGB or RGBA | RGB or RGBA |
| Format | PNG (input) | PNG (input) |

```python
from PIL import Image

# Load and verify dimensions
img = Image.open(r"C:\MyMod\artwork\loading_screen.png")
print("Size:", img.size)    # Should be (1024, 768)
print("Mode:", img.mode)    # RGB or RGBA

# Resize if needed
if img.size != (1024, 768):
    img = img.resize((1024, 768), Image.LANCZOS)
    img.save(r"C:\MyMod\artwork\loading_screen_resized.png")
```

#### Option B: Procedurally Generate with artwork_pipeline

The `generate_loading_screen()` function creates a complete loading screen
image programmatically using a multi-layer composition pipeline. No external
art tools needed.

```python
from world_builder.artwork_pipeline import generate_loading_screen

# Generate a standard loading screen (1024x768)
standard_img = generate_loading_screen(
    zone_name="Tel Abim",
    theme='tropical',
    size=(1024, 768),
)

# Generate the widescreen variant (2048x1536)
widescreen_img = generate_loading_screen(
    zone_name="Tel Abim",
    theme='tropical',
    size=(2048, 1536),
)

# Save as PNG for inspection before BLP conversion
standard_img.save(r"C:\MyMod\artwork\TelAbim_loading.png")
widescreen_img.save(r"C:\MyMod\artwork\TelAbim_loading_wide.png")
```

##### Available Themes

The artwork pipeline ships with four built-in visual themes, each defining
a multi-layer composition (sky, background, midground, foreground, accent):

**`tropical`** -- Sunset sky gradient, island silhouette, palm trees, water
horizon, sun glow accent. Best for island and coastal zones.

| Layer | Style | Colour |
|---|---|---|
| sky | gradient | (255, 180, 100) to (100, 150, 200) |
| background | island_silhouette | (20, 60, 40) |
| midground | palm_trees | (40, 80, 50) |
| foreground | water_horizon | (50, 120, 180) |
| accent | sun_glow | (255, 200, 100) |

**`volcanic`** -- Dark red sky, mountain peak, lava flows, volcanic rocks,
fire glow. Best for volcanic and hellfire zones.

| Layer | Style | Colour |
|---|---|---|
| sky | gradient | (60, 40, 40) to (180, 80, 60) |
| background | mountain_peak | (80, 50, 40) |
| midground | lava_flows | (255, 100, 50) |
| foreground | volcanic_rocks | (60, 40, 30) |
| accent | fire_glow | (255, 150, 50) |

**`underground`** -- Solid dark background, cavern walls, titan pillars,
rocky ground, glowing energy crystals. Best for caves and dungeons.

| Layer | Style | Colour |
|---|---|---|
| sky | solid | (20, 20, 30) |
| background | cavern_walls | (40, 40, 50) |
| midground | titan_pillars | (60, 60, 80) |
| foreground | rocky_ground | (30, 30, 40) |
| accent | energy_crystals | (100, 150, 255) |

**`titan`** -- Blue-grey gradient, titan architecture, statues, floor tiles,
arcane lightning. Best for Ulduar-style mechanical/ancient zones.

| Layer | Style | Colour |
|---|---|---|
| sky | gradient | (40, 40, 60) to (100, 100, 140) |
| background | titan_architecture | (80, 80, 100) |
| midground | titan_statues | (100, 100, 120) |
| foreground | floor_tiles | (60, 60, 80) |
| accent | arcane_lightning | (150, 200, 255) |

##### Custom Layer Overrides

You can override individual layers while keeping the base theme:

```python
standard_img = generate_loading_screen(
    zone_name="Frozen Cavern",
    theme='underground',
    size=(1024, 768),
    custom_elements={
        # Override the accent layer for an icy blue glow
        'accent': ('energy_crystals', (150, 200, 255)),
        # Override the sky for a slightly brighter cavern
        'sky': ('solid', (30, 30, 50)),
    },
)
```

##### Layer Composition Order

The pipeline composites layers in this fixed order:

1. **sky** -- Base background layer (gradient or solid fill)
2. **background** -- Far distance silhouettes
3. **midground** -- Mid-distance detail elements
4. **foreground** -- Close-range environmental elements
5. **accent** -- Glow effects and atmospheric particles
6. **text** -- Zone name drawn centred near the top (10% from top edge)

Each layer is rendered as an RGBA image and alpha-composited onto the
accumulated result.

#### Option C: Import an Existing BLP or TGA File

If you have a BLP file from another mod or extracted from the client, you
can import it using `import_artwork_image()`:

```python
from world_builder.artwork_pipeline import import_artwork_image

# Import and validate dimensions
img = import_artwork_image(
    r"C:\extracted\Interface\Glues\LoadingScreens\LoadScreenStormwind.blp",
    target_type='loading_screen',
)
print("Imported:", img.size, img.mode)
# Logs a warning if dimensions do not match 1024x768
```

The function supports PNG, BLP, and TGA files. BLP files are internally
converted to PNG via the native BLP2PNG converter before opening with Pillow.

### Step 2 -- Convert to BLP Format

The WoW client requires textures in BLP format. The `blp_converter` module
provides two functions for this conversion.

#### convert_png_to_blp() -- File-to-File Conversion

```python
from world_builder.blp_converter import convert_png_to_blp

# Standard loading screen
convert_png_to_blp(
    png_path=r"C:\MyMod\artwork\TelAbim_loading.png",
    blp_path=r"C:\MyMod\output\TelAbim.blp",
    compression='dxt1',
)

# Widescreen variant
convert_png_to_blp(
    png_path=r"C:\MyMod\artwork\TelAbim_loading_wide.png",
    blp_path=r"C:\MyMod\output\TelAbim_wide.blp",
    compression='dxt1',
)
```

#### image_to_blp() -- In-Memory Conversion (PIL Image to Bytes)

When working with the artwork pipeline, you can skip the PNG intermediate
file entirely and convert the PIL Image directly to BLP bytes:

```python
from world_builder.blp_converter import image_to_blp
from world_builder.artwork_pipeline import generate_loading_screen

# Generate and convert in one step
standard_img = generate_loading_screen("Tel Abim", theme='tropical')
standard_blp_bytes = image_to_blp(standard_img, compression='dxt1')

widescreen_img = generate_loading_screen(
    "Tel Abim", theme='tropical', size=(2048, 1536))
widescreen_blp_bytes = image_to_blp(widescreen_img, compression='dxt1')

print("Standard BLP size:", len(standard_blp_bytes), "bytes")
print("Widescreen BLP size:", len(widescreen_blp_bytes), "bytes")
```

#### Compression Options

| Compression | Quality | File Size | Use Case |
|---|---|---|---|
| `dxt1` | Good, no alpha | Smallest (~0.5 MB for 1024x768) | Default; best for loading screens with no transparency |
| `dxt3` | Good, sharp alpha | Medium | Textures with hard alpha edges |
| `dxt5` | Good, smooth alpha | Medium | Textures with gradient alpha |
| `uncompressed` | Perfect | Largest (~3 MB for 1024x768) | Fallback when PNG2BLP native extension is unavailable |

**DXT1 is recommended** for loading screens because they are opaque images
(no alpha channel needed) and the compression artefacts are virtually invisible
at loading screen scale.

#### Native vs. Fallback Conversion

The `blp_converter` module uses two strategies:

1. **Native PNG2BLP extension** (preferred): Uses the compiled C++ `PNG2BLP`
   library for DXT compression. Produces optimal file sizes with mipmaps.
   Available when the native extension is built (`from blp import PNG2BLP`).

2. **Uncompressed fallback** (automatic): When the native extension is not
   available, the module falls back to a pure-Python BLP2 writer that
   produces uncompressed BGRA textures. Files are larger but perfectly valid.
   A warning is logged when the fallback is used.

```
# Fallback warning you might see:
# WARNING: PNG2BLP not available, using uncompressed fallback for 1024x768 image
```

#### Validating BLP Output

```python
from world_builder.blp_converter import validate_blp

result = validate_blp(r"C:\MyMod\output\TelAbim.blp")
print("Valid:", result['valid'])
print("Magic:", result['magic'])
print("Dimensions:", result['width'], "x", result['height'])
print("Compression:", result['compression'])
if result['errors']:
    for err in result['errors']:
        print("ERROR:", err)
```

The `validate_blp()` function checks:
- BLP2 magic header bytes (`BLP2`)
- Non-zero dimensions
- First mipmap offset within file bounds
- Pixel data exists beyond the 148-byte header

### Step 3 -- Register in LoadingScreens.dbc

Use `register_loading_screen()` to create a new entry in LoadingScreens.dbc
that maps an ID to the BLP texture path.

```python
from world_builder.dbc_injector import register_loading_screen

DBC_DIR = r"C:\Games\WoW335\DBFilesClient"

loadingscreen_id = register_loading_screen(
    dbc_dir=DBC_DIR,
    name="LoadScreenTelAbim",
    filename=r"Interface\Glues\LoadingScreens\TelAbim",
    has_widescreen=1,
)
print("LoadingScreen ID:", loadingscreen_id)
```

#### LoadingScreens.dbc Field Reference

| Index | Field | Type | Bytes | Description |
|---|---|---|---|---|
| 0 | ID | uint32 | 0--3 | Unique LoadingScreen identifier |
| 1 | Name | string | 4--7 | Offset into string block -- internal name (e.g. "LoadScreenTelAbim") |
| 2 | FileName | string | 8--11 | Offset into string block -- BLP path without extension (e.g. "Interface\\Glues\\LoadingScreens\\TelAbim") |
| 3 | HasWideScreen | uint32 | 12--15 | 0 = standard only, 1 = widescreen variant available |

**Total: 4 fields = 16 bytes per record**

#### Parameter Details

- **name**: A purely internal label for the loading screen. Convention is
  `"LoadScreen{ZoneName}"`. Stored in the DBC string block.
- **filename**: The BLP texture path within the MPQ archive, **without** the
  `.blp` extension. The client appends `.blp` automatically. For widescreen,
  the client appends `_wide.blp`. For example, if you set this to
  `"Interface\\Glues\\LoadingScreens\\TelAbim"`, the client will look for:
  - Standard: `Interface\Glues\LoadingScreens\TelAbim.blp`
  - Widescreen: `Interface\Glues\LoadingScreens\TelAbim_wide.blp`
- **has_widescreen**: Set to `1` if you provide a widescreen BLP variant.
  Set to `0` if you only have the standard resolution image (the client will
  stretch it on widescreen monitors).
- **loadingscreen_id**: Specific ID, or `None` for auto-assignment
  (`max_id + 1`). Custom IDs should start above retail ceiling (ID > 300).

### Step 4 -- Link to Map.dbc

The loading screen is displayed when entering the map. The link is established
through the `LoadingScreenID` field (index 57) in Map.dbc. If your map was
created using `register_map()` from the [Add New Zone](add_new_zone.md) guide,
the loading screen ID was already set during map registration.

If you need to update an existing Map.dbc entry to point to a new loading
screen, use the low-level `DBCInjector`:

```python
import struct
from world_builder.dbc_injector import DBCInjector

DBC_DIR = r"C:\Games\WoW335\DBFilesClient"
MAP_ID = 800                    # Your map ID
LOADINGSCREEN_ID = loadingscreen_id   # From Step 3

filepath = os.path.join(DBC_DIR, 'Map.dbc')
dbc = DBCInjector(filepath)

# Find and patch the Map record
for i, rec in enumerate(dbc.records):
    rec_id = struct.unpack_from('<I', rec, 0)[0]
    if rec_id == MAP_ID:
        buf = bytearray(rec)
        # LoadingScreenID is at field index 57 = byte offset 228
        struct.pack_into('<I', buf, 228, LOADINGSCREEN_ID)
        dbc.records[i] = bytes(buf)
        dbc.write(filepath)
        print("Map", MAP_ID, "now uses LoadingScreen", LOADINGSCREEN_ID)
        break
else:
    print("ERROR: Map ID", MAP_ID, "not found in Map.dbc")
```

#### Map.dbc LoadingScreenID Field

| Index | Field | Byte Offset | Description |
|---|---|---|---|
| 57 | LoadingScreenID | 228 | FK to LoadingScreens.dbc |

### Step 5 -- Place BLP Files in MPQ

The BLP files must be placed at the exact paths that match the `FileName`
field in LoadingScreens.dbc (with `.blp` extension appended).

#### Expected MPQ Directory Structure

```
patch-4.MPQ
  |
  +-- Interface/
  |    +-- Glues/
  |         +-- LoadingScreens/
  |              +-- TelAbim.blp            (1024x768 standard)
  |              +-- TelAbim_wide.blp       (2048x1536 widescreen)
  |
  +-- DBFilesClient/
       +-- LoadingScreens.dbc
       +-- Map.dbc                         (if Map.dbc was modified)
```

#### Packing with MPQPacker

```python
import os
from world_builder.mpq_packer import MPQPacker

DBC_DIR = r"C:\Games\WoW335\DBFilesClient"
OUTPUT_DIR = r"C:\MyMod\output"

packer = MPQPacker(OUTPUT_DIR, patch_name="patch-4.MPQ")

# Add BLP loading screen textures
with open(r"C:\MyMod\output\TelAbim.blp", "rb") as f:
    packer.add_file(
        r"Interface\Glues\LoadingScreens\TelAbim.blp",
        f.read(),
    )
with open(r"C:\MyMod\output\TelAbim_wide.blp", "rb") as f:
    packer.add_file(
        r"Interface\Glues\LoadingScreens\TelAbim_wide.blp",
        f.read(),
    )

# Add modified DBC files
for dbc_name in ["LoadingScreens", "Map"]:
    dbc_path = os.path.join(DBC_DIR, dbc_name + ".dbc")
    with open(dbc_path, "rb") as f:
        packer.add_dbc(dbc_name, f.read())

result = packer.build_mpq()
print("MPQ output:", result)
```

---

## Complete End-to-End Example

This example generates a loading screen procedurally, converts it to BLP,
registers it in DBC files, and packs everything into an MPQ structure.

```python
"""
Complete example: Create and register a custom loading screen
for a WoW 3.3.5a zone.
"""

import os
import struct
from world_builder.artwork_pipeline import generate_loading_screen
from world_builder.blp_converter import image_to_blp, validate_blp
from world_builder.dbc_injector import (
    DBCInjector,
    register_loading_screen,
)
from world_builder.mpq_packer import MPQPacker

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
DBC_DIR = r"C:\Games\WoW335\DBFilesClient"
OUTPUT_DIR = r"C:\MyMod\output"
ZONE_NAME = "TelAbim"
MAP_ID = 800
THEME = 'tropical'

# ------------------------------------------------------------------
# Step 1: Generate loading screen images procedurally
# ------------------------------------------------------------------
print("Generating loading screens...")

standard_img = generate_loading_screen(
    zone_name="Tel Abim",
    theme=THEME,
    size=(1024, 768),
)

widescreen_img = generate_loading_screen(
    zone_name="Tel Abim",
    theme=THEME,
    size=(2048, 1536),
)

# Optional: save PNG copies for preview
os.makedirs(OUTPUT_DIR, exist_ok=True)
standard_img.save(os.path.join(OUTPUT_DIR, "TelAbim_preview.png"))
widescreen_img.save(os.path.join(OUTPUT_DIR, "TelAbim_wide_preview.png"))

# ------------------------------------------------------------------
# Step 2: Convert to BLP format (in-memory)
# ------------------------------------------------------------------
print("Converting to BLP...")

standard_blp = image_to_blp(standard_img, compression='dxt1')
widescreen_blp = image_to_blp(widescreen_img, compression='dxt1')

# Validate the BLP output
for label, blp_data in [("Standard", standard_blp), ("Widescreen", widescreen_blp)]:
    result = validate_blp(blp_data)
    print("{}: valid={}, {}x{}, {} bytes".format(
        label, result['valid'], result['width'], result['height'],
        len(blp_data)))
    if result['errors']:
        for err in result['errors']:
            print("  ERROR:", err)

# ------------------------------------------------------------------
# Step 3: Register in LoadingScreens.dbc
# ------------------------------------------------------------------
print("Registering in LoadingScreens.dbc...")

loadingscreen_id = register_loading_screen(
    dbc_dir=DBC_DIR,
    name="LoadScreenTelAbim",
    filename=r"Interface\Glues\LoadingScreens\TelAbim",
    has_widescreen=1,
)
print("LoadingScreen ID:", loadingscreen_id)

# ------------------------------------------------------------------
# Step 4: Link to Map.dbc
# ------------------------------------------------------------------
print("Linking to Map.dbc...")

map_filepath = os.path.join(DBC_DIR, 'Map.dbc')
dbc = DBCInjector(map_filepath)

found = False
for i, rec in enumerate(dbc.records):
    rec_id = struct.unpack_from('<I', rec, 0)[0]
    if rec_id == MAP_ID:
        buf = bytearray(rec)
        struct.pack_into('<I', buf, 228, loadingscreen_id)  # field 57
        dbc.records[i] = bytes(buf)
        dbc.write(map_filepath)
        found = True
        print("Map", MAP_ID, "linked to LoadingScreen", loadingscreen_id)
        break

if not found:
    print("WARNING: Map ID", MAP_ID, "not found in Map.dbc")
    print("If this is a new map, use register_map() instead")

# ------------------------------------------------------------------
# Step 5: Pack into MPQ structure
# ------------------------------------------------------------------
print("Packing into MPQ...")

packer = MPQPacker(OUTPUT_DIR, patch_name="patch-4.MPQ")

# BLP loading screen textures
packer.add_file(
    r"Interface\Glues\LoadingScreens\TelAbim.blp",
    standard_blp,
)
packer.add_file(
    r"Interface\Glues\LoadingScreens\TelAbim_wide.blp",
    widescreen_blp,
)

# Modified DBC files
for dbc_name in ["LoadingScreens", "Map"]:
    dbc_path = os.path.join(DBC_DIR, dbc_name + ".dbc")
    with open(dbc_path, "rb") as f:
        packer.add_dbc(dbc_name, f.read())

result = packer.build_mpq()
print("Complete! Output:", result)
```

---

## Complete Workflow with generate_zone_artwork_bundle()

If you are creating a new zone from scratch, the
`generate_zone_artwork_bundle()` function generates ALL artwork in one call,
including the loading screen. This is the recommended approach when building
a complete zone.

```python
import numpy as np
from world_builder.artwork_pipeline import (
    generate_zone_artwork_bundle,
    SubzoneDefinition,
)

# Define subzones (required for world map generation)
subzones = [
    SubzoneDefinition(
        name="Palmbreak Shore",
        boundary=[(100, 100), (400, 100), (400, 300), (100, 300)],
        color=(180, 220, 120),
    ),
    SubzoneDefinition(
        name="Emerald Lagoon",
        boundary=[(400, 200), (600, 200), (600, 400), (400, 400)],
        color=(100, 200, 180),
    ),
]

# Generate a simple heightmap (or use TerrainSculptor output)
heightmap = np.random.rand(256, 256) * 0.3 + 0.2

# Generate ALL artwork in one call
results = generate_zone_artwork_bundle(
    zone_name="TelAbim",
    heightmap=heightmap,
    subzones=subzones,
    theme='tropical',
    output_dir=r"C:\MyMod\output",
    water_level=0.15,
    save_png=True,
)

# The results dict maps MPQ paths to PIL Images:
for mpq_path, img in results.items():
    print("{}: {}x{}".format(mpq_path, img.width, img.height))

# Expected output:
# Interface\WorldMap\TelAbim\TelAbim.blp: 1002x668
# Interface\WorldMap\TelAbim\PalmbreakShore_overlay.blp: 256x256
# Interface\WorldMap\TelAbim\EmeraldLagoon_overlay.blp: 256x256
# Interface\Glues\LoadingScreens\TelAbim.blp: 1024x768
# Interface\Glues\LoadingScreens\TelAbim_wide.blp: 2048x1536
```

The returned dictionary contains PIL Image objects keyed by their MPQ paths.
You can then convert them to BLP and pack them using `image_to_blp()` and
`MPQPacker`:

```python
from world_builder.blp_converter import image_to_blp
from world_builder.mpq_packer import MPQPacker

packer = MPQPacker(r"C:\MyMod\output")

for mpq_path, img in results.items():
    blp_bytes = image_to_blp(img, compression='dxt1')
    packer.add_file(mpq_path, blp_bytes)

packer.build_mpq()
```

---

## MPQ Path Reference

The artwork pipeline module provides helper functions that generate the
correct MPQ paths for all artwork types:

```python
from world_builder.artwork.mpq_paths import (
    loading_screen_blp_path,
    world_map_blp_path,
    subzone_overlay_blp_path,
    dungeon_map_blp_path,
)

# Loading screens
print(loading_screen_blp_path("TelAbim"))
# -> Interface\Glues\LoadingScreens\TelAbim.blp

print(loading_screen_blp_path("TelAbim", widescreen=True))
# -> Interface\Glues\LoadingScreens\TelAbim_wide.blp

# World map (for reference)
print(world_map_blp_path("TelAbim"))
# -> Interface\WorldMap\TelAbim\TelAbim.blp

# Subzone overlays (for reference)
print(subzone_overlay_blp_path("TelAbim", "Palmbreak Shore"))
# -> Interface\WorldMap\TelAbim\PalmbreakShore_overlay.blp

# Dungeon map (for reference)
print(dungeon_map_blp_path("Vault of Storms"))
# -> Interface\WorldMap\VaultOfStorms\VaultOfStorms.blp
```

Note that the `_sanitise_name()` helper strips spaces and special characters:
`"Vault of Storms"` becomes `"VaultOfStorms"`, `"Tel'Abim"` becomes
`"TelAbim"`.

---

## Replacing a Retail Loading Screen

To replace an existing zone's loading screen (e.g., giving Stormwind a new
look), you can create a new LoadingScreens.dbc entry and patch the existing
Map.dbc record.

```python
import os
import struct
from world_builder.artwork_pipeline import generate_loading_screen
from world_builder.blp_converter import image_to_blp
from world_builder.dbc_injector import DBCInjector, register_loading_screen
from world_builder.mpq_packer import MPQPacker

DBC_DIR = r"C:\Games\WoW335\DBFilesClient"

# Generate a new loading screen for Eastern Kingdoms (Map ID 0)
img = generate_loading_screen("Stormwind", theme='titan', size=(1024, 768))
img_wide = generate_loading_screen("Stormwind", theme='titan', size=(2048, 1536))

blp_standard = image_to_blp(img, compression='dxt1')
blp_wide = image_to_blp(img_wide, compression='dxt1')

# Register a new loading screen entry
ls_id = register_loading_screen(
    dbc_dir=DBC_DIR,
    name="LoadScreenStormwindCustom",
    filename=r"Interface\Glues\LoadingScreens\StormwindCustom",
    has_widescreen=1,
)

# Patch Eastern Kingdoms (Map ID 0) to use the new loading screen
map_path = os.path.join(DBC_DIR, 'Map.dbc')
dbc = DBCInjector(map_path)
for i, rec in enumerate(dbc.records):
    if struct.unpack_from('<I', rec, 0)[0] == 0:  # Map ID 0
        buf = bytearray(rec)
        struct.pack_into('<I', buf, 228, ls_id)
        dbc.records[i] = bytes(buf)
        dbc.write(map_path)
        break

# Pack into MPQ
packer = MPQPacker(r"C:\MyMod\output")
packer.add_file(r"Interface\Glues\LoadingScreens\StormwindCustom.blp", blp_standard)
packer.add_file(r"Interface\Glues\LoadingScreens\StormwindCustom_wide.blp", blp_wide)
for name in ["LoadingScreens", "Map"]:
    with open(os.path.join(DBC_DIR, name + ".dbc"), "rb") as f:
        packer.add_dbc(name, f.read())
packer.build_mpq()
```

---

## BLP2 Binary Format Reference

For debugging or building custom tools, here is the complete BLP2 header
layout as implemented by the `blp_converter` fallback writer:

```
Offset   Size    Field               Description
------   ----    -----               -----------
0        4       Magic               'BLP2' (4 ASCII bytes)
4        4       Type                1 = BLP2 format (uint32)
8        1       Compression         1=palettized, 2=DXT, 3=uncompressed (uint8)
9        1       AlphaDepth          0, 1, 4, or 8 bits (uint8)
10       1       AlphaType           0=DXT1, 1=DXT3, 7=DXT5, 8=uncompressed (uint8)
11       1       HasMips             0=no mipmaps, 1=has mipmaps (uint8)
12       4       Width               Image width in pixels (uint32)
16       4       Height              Image height in pixels (uint32)
20       64      MipmapOffsets[16]   Byte offsets to each mipmap level (16 x uint32)
84       64      MipmapSizes[16]     Byte sizes of each mipmap level (16 x uint32)
------
148 bytes total header

Pixel data starts at offset 148 (for single-mip uncompressed).
For DXT-compressed BLP files, the native PNG2BLP extension handles
mipmap generation and offset calculation automatically.
```

### Uncompressed Pixel Data

When compression type is 3 (uncompressed), pixel data is stored as raw
BGRA bytes (Blue, Green, Red, Alpha) at 4 bytes per pixel:

```
Total pixel data = width * height * 4 bytes
Byte order: B G R A B G R A B G R A ...
```

The fallback writer in `blp_converter.py` converts PIL RGBA pixels to BGRA
by swapping the R and B channels.

---

## Advanced: Batch Converting Loading Screens

The `batch_convert()` function converts an entire directory of PNG files to
BLP format:

```python
from world_builder.blp_converter import batch_convert

blp_files = batch_convert(
    input_dir=r"C:\MyMod\loading_screens_png",
    output_dir=r"C:\MyMod\loading_screens_blp",
    pattern="*.png",
)
print("Converted {} files:".format(len(blp_files)))
for path in blp_files:
    print(" ", path)
```

This is useful when generating loading screens for multiple zones at once.

---

## Common Pitfalls and Troubleshooting

### Loading Screen Does Not Appear

| Cause | Solution |
|---|---|
| Map.dbc not updated | Verify field 57 (LoadingScreenID) is set to the new LoadingScreens.dbc ID |
| LoadingScreens.dbc FileName wrong | Check the `filename` parameter does NOT include the `.blp` extension |
| BLP file not in MPQ | Verify the BLP is at exactly `Interface\Glues\LoadingScreens\{name}.blp` |
| Patch MPQ not loaded | Ensure the patch file name sorts after existing patches (`patch-4.MPQ` or later) |
| BLP validation fails | Run `validate_blp()` to check for header corruption |

### Widescreen Variant Not Used

| Cause | Solution |
|---|---|
| HasWideScreen = 0 | Set `has_widescreen=1` when calling `register_loading_screen()` |
| Missing _wide BLP | Add `{name}_wide.blp` alongside the standard BLP in the same MPQ directory |
| Wrong resolution | Widescreen BLP should be 2048x1536 (same 4:3 ratio, doubled) |

### BLP Appears Corrupted In-Game (Pink/Black Texture)

| Cause | Solution |
|---|---|
| Wrong BLP compression | Try `compression='uncompressed'` as a diagnostic step |
| DXT artefacts | Switch from `dxt1` to `dxt5` for images with fine detail |
| Dimensions not power of 2 | Loading screens (1024x768) are an exception to the power-of-2 rule; this is a standard WoW size |
| Truncated file | Verify the full BLP data was written to the MPQ (check file size) |

### register_loading_screen() Raises Error

| Error | Cause | Solution |
|---|---|---|
| `FileNotFoundError` | LoadingScreens.dbc not found in dbc_dir | Verify the path to your DBFilesClient directory |
| `AssertionError` on record size | DBC file is from wrong client version | Use DBC files from 3.3.5a build 12340 only |
| `struct.error` | Corrupted DBC file | Restore from backup and re-run |

---

## Validation Checklist

After completing all steps, verify your setup:

- [ ] Loading screen PNG/BLP visually looks correct (preview the PNG)
- [ ] `validate_blp()` reports `valid=True` for both standard and widescreen BLPs
- [ ] **LoadingScreens.dbc** contains the new record with correct `FileName` path
- [ ] **LoadingScreens.dbc** `HasWideScreen` is set to 1 (if providing widescreen)
- [ ] **Map.dbc** field 57 (`LoadingScreenID`) points to the new LoadingScreens ID
- [ ] Standard BLP is at `Interface\Glues\LoadingScreens\{name}.blp` in MPQ
- [ ] Widescreen BLP is at `Interface\Glues\LoadingScreens\{name}_wide.blp` in MPQ
- [ ] Patch MPQ is in the WoW `Data/` directory
- [ ] In-game: loading screen appears when entering the zone/instance
- [ ] In-game: widescreen monitors show the high-resolution variant

---

## Cross-References

- [Add New Zone (Exterior)](add_new_zone.md) -- Creating the Map.dbc entry
  that references the loading screen; includes artwork bundle generation
- [Add New Dungeon (Instance)](add_new_dungeon.md) -- Dungeons also use
  loading screens; the LoadingScreenID is set during `register_map()` with
  `instance_type=1`
- [Add Custom Music](add_custom_music.md) -- Audio and loading screens are
  often configured together when building a new zone
- [Update Zone Scenery](update_zone_scenery.md) -- Terrain modifications do
  not affect loading screens, but re-packing the MPQ may require including
  the modified DBC files
