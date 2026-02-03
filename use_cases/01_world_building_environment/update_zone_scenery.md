# Update Zone Scenery

## Overview

This guide covers how to modify the terrain, textures, doodads, and WMOs of an
existing WoW WotLK 3.3.5a zone using the `pywowlib` world builder toolkit.
Rather than creating a zone from scratch, you read existing ADT tiles, modify
their data in Python, and write the changes back -- either to a new patch MPQ
or in place.

Typical use cases:

- Reshape terrain (raise hills, flatten areas, carve rivers)
- Swap ground textures (replace grass with snow, sand with lava)
- Import heightmap data from one ADT into another
- Analyze and replicate texture painting rules from retail zones
- Re-pack modified tiles into an MPQ patch

---

## Prerequisites

| Requirement | Details |
|---|---|
| Python 3.8+ | Standard CPython |
| pywowlib | Cloned and importable |
| NumPy | `pip install numpy` -- required by terrain_sculptor |
| Extracted ADT files | Use MPQExtractor or external MPQ tool to extract tiles |
| DBC files | Copy of `DBFilesClient/` (only if changing area IDs or textures) |

---

## Step-by-Step Walkthrough

### Step 1 -- Extract Existing ADT Files

Before modifying a zone you need the raw ADT files on disk. Use the
`MPQExtractor` class or an external tool.

#### Using MPQExtractor

```python
from world_builder.mpq_packer import MPQExtractor, extract_map

# Extract all files for a specific map
extracted = extract_map(
    mpq_path=r"C:\WoW335\Data\common.MPQ",
    map_name="Azeroth",
    output_dir=r"C:\extracted",
)

for internal_path, disk_path in extracted.items():
    print("Extracted:", internal_path, "->", disk_path)
```

#### Extract Individual Files

```python
with MPQExtractor(r"C:\WoW335\Data\common.MPQ") as extractor:
    # List available map files
    map_files = extractor.list_files("World/Maps/Azeroth/*.adt")
    print("Found", len(map_files), "ADT files")

    # Extract a specific tile
    extractor.extract_file(
        "World\\Maps\\Azeroth\\Azeroth_32_48.adt",
        r"C:\extracted\Azeroth_32_48.adt"
    )

    # Extract a specific DBC
    extractor.extract_dbc("AreaTable", r"C:\extracted")
```

---

### Step 2 -- Read an Existing ADT

The `read_adt()` function parses a binary ADT file and returns all terrain data
in a Python dict:

```python
from world_builder.adt_composer import read_adt

adt_data = read_adt(
    filepath=r"C:\extracted\Azeroth_32_48.adt",
    highres=False,             # Set True if WDT has MPHD flag 0x4
)

print("Tile coordinates:", adt_data['tile_x'], adt_data['tile_y'])
print("Textures:", adt_data['texture_paths'])
print("Area ID:", adt_data['area_id'])
print("Heightmap shape: {}x{}".format(
    len(adt_data['heightmap']), len(adt_data['heightmap'][0])))
print("Doodad instances:", len(adt_data['doodad_instances']))
print("WMO instances:", len(adt_data['wmo_instances']))
print("M2 filenames:", adt_data['m2_filenames'])
print("WMO filenames:", adt_data['wmo_filenames'])
```

#### Returned Data Structure

```python
{
    'tile_x': int,                    # Tile X coordinate (0-63)
    'tile_y': int,                    # Tile Y coordinate (0-63)
    'heightmap': [[float]*129]*129,   # 129x129 elevation values
    'texture_paths': [str, ...],      # Texture BLP paths from MTEX
    'splat_map': {                    # Per-chunk alpha maps
        layer_idx: {
            (chunk_row, chunk_col): [[int]*64]*64,
            ...
        },
    },
    'area_id': int,                   # Default area ID (from chunk 0,0)
    'doodad_instances': [             # MDDF entries
        {
            'name_id': int,
            'unique_id': int,
            'position': (x, y, z),
            'rotation': (x, y, z),
            'scale': int,
            'flags': int,
        },
        ...
    ],
    'wmo_instances': [                # MODF entries
        {
            'name_id': int,
            'unique_id': int,
            'position': (x, y, z),
            'rotation': (x, y, z),
            'extents_min': (x, y, z),
            'extents_max': (x, y, z),
            'flags': int,
            'doodad_set': int,
            'name_set': int,
            'scale': int,
        },
        ...
    ],
    'm2_filenames': [str, ...],       # M2 model paths from MMDX
    'wmo_filenames': [str, ...],      # WMO paths from MWMO
    'chunks': [[dict]*16]*16,         # Raw per-chunk MCNK data
}
```

---

### Step 3 -- Modify the Heightmap

The heightmap is a 129x129 list of float values. Each value is the terrain
height in game yards. You can modify it directly:

#### 3a -- Flatten an Area

```python
import copy

# Work on a copy to preserve the original
modified_heightmap = copy.deepcopy(adt_data['heightmap'])

# Flatten a 20x20 vertex region in the center to height 50.0
for row in range(55, 75):
    for col in range(55, 75):
        modified_heightmap[row][col] = 50.0
```

#### 3b -- Raise a Hill

```python
import math

center_row, center_col = 64, 64
hill_radius = 30
hill_height = 40.0

for row in range(129):
    for col in range(129):
        dist = math.sqrt((row - center_row)**2 + (col - center_col)**2)
        if dist < hill_radius:
            # Smooth cosine falloff
            t = dist / hill_radius
            added_height = hill_height * 0.5 * (1.0 + math.cos(math.pi * t))
            modified_heightmap[row][col] += added_height
```

#### 3c -- Carve a River Channel

```python
import math

river_depth = 8.0
river_width = 10  # vertices

for row in range(129):
    # Sinusoidal river path
    river_center = 64 + int(15 * math.sin(row * 0.05))

    for col in range(129):
        dist = abs(col - river_center)
        if dist < river_width:
            t = dist / river_width
            # Smooth V-shaped channel
            depth = river_depth * (1.0 - t * t)
            modified_heightmap[row][col] -= depth
```

---

### Step 4 -- Import a Heightmap from Another ADT

The `import_heightmap_from_adt()` function reads an existing ADT file and
returns a NumPy array suitable for terrain analysis and transplantation:

```python
from world_builder.terrain_sculptor import import_heightmap_from_adt
import numpy as np

# Import heightmap from a retail zone tile
source_heightmap = import_heightmap_from_adt(
    r"C:\extracted\Northrend_31_30.adt"
)

print("Shape:", source_heightmap.shape)       # (129, 129)
print("Height range: {:.1f} to {:.1f}".format(
    float(np.min(source_heightmap)),
    float(np.max(source_heightmap)),
))

# Use the imported heightmap directly in a new ADT
from world_builder.adt_composer import create_adt

new_adt = create_adt(
    tile_x=32,
    tile_y=32,
    heightmap=source_heightmap.tolist(),  # Convert numpy to list-of-lists
    texture_paths=["Tileset\\Generic\\Grass01.blp"],
    area_id=5000,
)
```

#### Blend Two Heightmaps

```python
import numpy as np

source_a = import_heightmap_from_adt(r"C:\extracted\Tile_A.adt")
source_b = import_heightmap_from_adt(r"C:\extracted\Tile_B.adt")

# Linear blend: 70% from A, 30% from B
blended = 0.7 * source_a + 0.3 * source_b

# Or use a mask for spatial blending
mask = np.zeros((129, 129), dtype=np.float64)
for r in range(129):
    for c in range(129):
        # Left half from A, right half from B, smooth transition
        t = c / 128.0
        mask[r, c] = t

blended = source_a * (1.0 - mask) + source_b * mask
```

---

### Step 5 -- Swap Textures

#### 5a -- Replace a Texture Path

```python
# Simple texture swap: replace grass with snow
modified_textures = list(adt_data['texture_paths'])

for i, tex in enumerate(modified_textures):
    if "Grass" in tex:
        modified_textures[i] = "Tileset\\Generic\\Snow01.blp"

print("New textures:", modified_textures)
```

#### 5b -- Add a New Texture Layer

If the tile has fewer than 4 textures, you can add an additional layer with
its own alpha map:

```python
# Original has 2 textures; add a third (rock on steep slopes)
modified_textures = list(adt_data['texture_paths'])
modified_textures.append("Tileset\\Generic\\Rock01.blp")

# Create alpha map for the new layer (64x64)
import math
rock_alpha = [[0] * 64 for _ in range(64)]
for r in range(64):
    for c in range(64):
        # Map alpha cell to heightmap coordinates
        hr = int(r * 128 / 63)
        hc = int(c * 128 / 63)
        h = modified_heightmap[hr][hc]
        # Rock above elevation 60
        if h > 60.0:
            rock_alpha[r][c] = min(255, int((h - 60.0) * 5))

new_layer_idx = len(modified_textures) - 1
```

---

### Step 6 -- Import Texture Rules from Existing ADTs

The `import_texture_rules_from_adt()` function analyzes the correlation between
alpha maps, elevation, and slope in an existing ADT to infer painting rules:

```python
from world_builder.terrain_sculptor import import_texture_rules_from_adt

rules = import_texture_rules_from_adt(
    r"C:\extracted\Northrend_31_30.adt"
)

print("Textures:", rules['texture_paths'])

print("\nElevation rules:")
for rule in rules['elevation_rules']:
    print("  {}: {:.1f} - {:.1f}".format(
        rule['texture'],
        rule['min_elevation'],
        rule['max_elevation'],
    ))

print("\nSlope rules:")
for rule in rules['slope_rules']:
    print("  {}: {:.1f} - {:.1f} degrees".format(
        rule['texture'],
        rule['min_slope'],
        rule['max_slope'],
    ))
```

#### Returned Structure

```python
{
    'texture_paths': ['Sand.blp', 'Grass.blp', 'Rock.blp'],
    'elevation_rules': [
        {'texture': 'Sand.blp',  'min_elevation': -5.0, 'max_elevation': 120.0},
        {'texture': 'Grass.blp', 'min_elevation': 2.1,  'max_elevation': 45.3},
        {'texture': 'Rock.blp',  'min_elevation': 30.5, 'max_elevation': 98.7},
    ],
    'slope_rules': [
        {'texture': 'Sand.blp',  'min_slope': 0.0,  'max_slope': 42.1},
        {'texture': 'Grass.blp', 'min_slope': 0.5,  'max_slope': 15.2},
        {'texture': 'Rock.blp',  'min_slope': 12.3, 'max_slope': 65.8},
    ],
}
```

These rules can be used to automatically texture-paint a new heightmap in the
style of the source zone:

```python
# Apply the inferred rules to create alpha maps for a new heightmap
import numpy as np
from world_builder.terrain_sculptor import calculate_slope

hm_array = np.array(modified_heightmap, dtype=np.float64)
slope_array = calculate_slope(hm_array)

# Use elevation_rules[1] (Grass) to generate an alpha map
grass_rule = rules['elevation_rules'][1]
min_e = grass_rule['min_elevation']
max_e = grass_rule['max_elevation']

grass_alpha = [[0] * 64 for _ in range(64)]
for r in range(64):
    for c in range(64):
        hr = int(r * 128 / 63)
        hc = int(c * 128 / 63)
        h = hm_array[hr, hc]
        if min_e <= h <= max_e:
            # Normalize within the elevation range
            t = (h - min_e) / max(max_e - min_e, 1.0)
            grass_alpha[r][c] = int(t * 200)
```

---

### Step 7 -- Write the Modified ADT

After modifying the heightmap and/or textures, write a new ADT:

```python
from world_builder.adt_composer import create_adt, write_adt

# Create new ADT bytes with modified data
new_adt_data = create_adt(
    tile_x=adt_data['tile_x'],
    tile_y=adt_data['tile_y'],
    heightmap=modified_heightmap,
    texture_paths=modified_textures,
    splat_map={
        1: grass_alpha,       # Layer 1 alpha
        # Add more layers as needed
    },
    area_id=adt_data['area_id'],
)

# Write directly to disk
write_adt(
    filepath=r"C:\output\modified_tile.adt",
    tile_x=adt_data['tile_x'],
    tile_y=adt_data['tile_y'],
    heightmap=modified_heightmap,
    texture_paths=modified_textures,
    area_id=adt_data['area_id'],
)
```

---

### Step 8 -- Using TerrainSculptor for Procedural Modifications

For more sophisticated terrain changes, use the TerrainSculptor primitives
on imported heightmaps:

```python
from world_builder.terrain_sculptor import (
    island, plateau, volcano, valley, ridge
)
import numpy as np

# Start with the imported heightmap
hm = import_heightmap_from_adt(r"C:\extracted\MyZone_32_32.adt")

# Add an island feature to the existing terrain
island_feature = island(
    size=(129, 129),
    center=(0.3, 0.7),        # Normalised position
    radius=0.15,
    elevation=40.0,
    falloff=0.3,
)
hm = hm + island_feature

# Add a ridge connecting two points
ridge_feature = ridge(
    size=(129, 129),
    start=(0.1, 0.2),
    end=(0.8, 0.6),
    width=0.05,
    height=25.0,
    falloff=0.2,
)
hm = hm + ridge_feature

# Carve a valley
valley_feature = valley(
    size=(129, 129),
    center=(0.6, 0.3),
    radius=0.1,
    depth=15.0,
    falloff=0.3,
)
hm = hm + valley_feature

# Write the modified heightmap
new_adt = create_adt(
    tile_x=32,
    tile_y=32,
    heightmap=hm.tolist(),
    texture_paths=["Tileset\\Generic\\Grass01.blp"],
    area_id=5000,
)
```

---

### Step 9 -- Re-Pack into MPQ

```python
from world_builder.mpq_packer import MPQPacker
from world_builder.wdt_generator import read_wdt, create_wdt

OUTPUT_DIR = r"C:\output\scenery_patch"
MAP_NAME = "Azeroth"

# Read the existing WDT to get active tiles
wdt_info = read_wdt(r"C:\extracted\World\Maps\Azeroth\Azeroth.wdt")

# Recreate the WDT (unchanged)
wdt_data = create_wdt(
    active_coords=wdt_info['active_coords'],
    mphd_flags=wdt_info['mphd_flags'],
)

# Pack only the modified tiles
packer = MPQPacker(OUTPUT_DIR)
packer.add_wdt(MAP_NAME, wdt_data)

# Add modified ADT
packer.add_adt(MAP_NAME, 32, 48, new_adt_data)

output = packer.build_directory()
print("Patch content at:", output)
```

---

### Step 10 -- Batch Processing Multiple Tiles

For large-scale scenery updates, process multiple tiles in a loop:

```python
import os
from world_builder.adt_composer import read_adt, create_adt
from world_builder.terrain_sculptor import import_heightmap_from_adt
import numpy as np

EXTRACTED_DIR = r"C:\extracted\World\Maps\Azeroth"
TILES_TO_MODIFY = [(32, 48), (32, 49), (33, 48), (33, 49)]

modified_tiles = {}

for tx, ty in TILES_TO_MODIFY:
    adt_path = os.path.join(
        EXTRACTED_DIR,
        "Azeroth_{:d}_{:d}.adt".format(tx, ty)
    )

    if not os.path.isfile(adt_path):
        print("Skipping missing tile:", adt_path)
        continue

    # Read existing data
    adt = read_adt(adt_path)
    hm = np.array(adt['heightmap'], dtype=np.float64)

    # Apply modification: raise everything by 10 yards
    hm += 10.0

    # Swap first texture to snow
    textures = list(adt['texture_paths'])
    if textures:
        textures[0] = "Tileset\\Generic\\Snow01.blp"

    # Regenerate ADT
    new_data = create_adt(
        tile_x=tx,
        tile_y=ty,
        heightmap=hm.tolist(),
        texture_paths=textures,
        area_id=adt['area_id'],
    )
    modified_tiles[(tx, ty)] = new_data
    print("Modified tile ({}, {})".format(tx, ty))

# Pack all modified tiles
packer = MPQPacker(OUTPUT_DIR)
for (tx, ty), data in modified_tiles.items():
    packer.add_adt("Azeroth", tx, ty, data)

packer.build_directory()
```

---

## Common Pitfalls and Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `ImportError: Parent library ADTFile is required` | `adt_file.py` not importable | Ensure pywowlib is installed (`pip install -e .`) |
| Heights look wrong after round-trip | MCVT values are relative to MCNK base height | `read_adt()` handles this; check your heightmap ranges |
| Alpha maps look blocky | Using nearest-neighbour upsampling | Install scipy for bilinear upsampling in TexturePainter |
| Textures reset to black | Empty texture_paths list | Always provide at least one texture path |
| Tile appears in wrong location | Wrong tile_x/tile_y passed to create_adt | Verify coordinates match the WDT grid |
| Client crashes on modified tile | Corrupted MCIN offsets | Ensure you use create_adt() which computes offsets correctly |
| Splat map ignored | Layer index 0 in splat_map | Layer 0 is always full coverage; alpha maps start at layer 1 |

---

## Validation Steps

1. **Round-trip test**: Read an ADT with `read_adt()`, pass its data directly
   to `create_adt()`, write the result, then read it again and compare:

```python
original = read_adt(r"C:\extracted\tile.adt")

regenerated = create_adt(
    tile_x=original['tile_x'],
    tile_y=original['tile_y'],
    heightmap=original['heightmap'],
    texture_paths=original['texture_paths'][:4],
    area_id=original['area_id'],
)

# Read the regenerated data
import tempfile, os
tmp = os.path.join(tempfile.gettempdir(), "test_roundtrip.adt")
with open(tmp, 'wb') as f:
    f.write(regenerated)

roundtripped = read_adt(tmp)
print("Tile coords match:",
      original['tile_x'] == roundtripped['tile_x'],
      original['tile_y'] == roundtripped['tile_y'])
print("Texture count:",
      len(original['texture_paths']), "->",
      len(roundtripped['texture_paths']))
```

2. **Visual inspection**: Open modified ADTs in Noggit or a similar map editor
   to visually verify terrain changes before deploying to a live server.

3. **Height range check**: After modifying heights, verify they stay within
   reasonable bounds:

```python
import numpy as np
hm = np.array(modified_heightmap)
print("Min height:", np.min(hm))
print("Max height:", np.max(hm))
print("Mean height:", np.mean(hm))
assert np.min(hm) > -500.0, "Heights below -500 may cause rendering issues"
assert np.max(hm) < 2000.0, "Heights above 2000 may cause rendering issues"
```

---

## Cross-References

- [Add New Zone](add_new_zone.md) -- Create a zone from scratch instead of
  modifying existing terrain
- [Add Custom Music](add_custom_music.md) -- Add sound to modified zones
- [Change Loading Screen](change_loading_screen.md) -- Update the loading
  screen for a modified zone
- [Add New Dungeon](add_new_dungeon.md) -- Place a dungeon entrance in the
  modified zone
