# Add New Zone (Exterior)

## Overview

This guide walks through every step required to create a fully functional custom
exterior zone for World of Warcraft WotLK 3.3.5a (build 12340) using the
`pywowlib` world builder toolkit. By the end you will have:

- A new map registered in **Map.dbc**
- An area entry in **AreaTable.dbc** (with ambient sound, music, and lighting)
- World map artwork entries in **WorldMapArea.dbc** and **WorldMapOverlay.dbc**
- A loading screen registered in **LoadingScreens.dbc**
- A valid **WDT** file declaring which ADT tiles exist
- One or more **ADT** terrain tiles with heightmaps, textures, and alpha-blended
  splat maps
- Procedural terrain generated via the **TerrainSculptor** pipeline (islands,
  plateaus, volcanos, valleys, ridges, noise)
- Everything packed into the correct **MPQ** directory structure
- Server-side **SQL** for `instance_template` / `access_requirement`
- Guidance on vmap/mmap extraction for collision and pathing

---

## Prerequisites

| Requirement | Details |
|---|---|
| Python 3.8+ | Standard CPython distribution |
| pywowlib | Cloned and importable (`pip install -e .` from repo root) |
| NumPy | `pip install numpy` -- required by TerrainSculptor |
| Pillow | `pip install Pillow` -- required by artwork_pipeline / blp_converter |
| Jinja2 | `pip install jinja2` -- required by script_generator (optional for zones) |
| SciPy | `pip install scipy` -- optional, improves alpha map upsampling |
| DBC files | A copy of `DBFilesClient/` from the WoW 3.3.5a client MPQ chain |
| MPQ tool | Either native StormLib bindings or an external MPQ editor (ladik's MPQ Editor) |
| Server | AzerothCore or TrinityCore 3.3.5a with Eluna (for SQL / scripting) |

> **Important**: Back up your DBC directory before running any injection
> functions. The `dbc_injector` module modifies DBC files in place.

---

## Step-by-Step Walkthrough

### Step 1 -- Choose IDs and Coordinates

Every custom zone needs unique IDs that do not collide with retail data or other
custom content. The convention for custom WotLK content is to start IDs above
the retail ceiling:

| Resource | Retail ceiling (approx.) | Safe custom range |
|---|---|---|
| Map ID | 724 | 800+ |
| Area ID | 4395 | 5000+ |
| Loading screen ID | 131 | 200+ |
| WorldMapArea ID | 502 | 600+ |
| WorldMapOverlay ID | 3600 | 4000+ |
| ZoneMusic ID | 504 | 600+ |
| SoundAmbience ID | 808 | 900+ |
| Light ID | 2662 | 3000+ |

For tile coordinates, `(32, 32)` is the map center -- the safest default for a
single-tile zone. Multi-tile zones expand outward: for a 3x3 grid you would use
`base_coords=(31, 31)` with tiles spanning (31,31) through (33,33).

```python
# Configuration -- adjust these for your project
MAP_NAME       = "TelAbim"
MAP_ID         = 800
AREA_ID        = 5000
LOADING_ID     = 200
WMA_ID         = 600
WMO_OVERLAY_ID = 4000
ZONE_MUSIC_ID  = 600
AMBIENCE_ID    = 900
LIGHT_ID       = 3000

# Tile grid
BASE_X, BASE_Y = 32, 32          # Center tile
GRID_W, GRID_H = 1, 1            # 1x1 tile (single ADT)
COORDS = [(BASE_X, BASE_Y)]      # Active tile list

DBC_DIR    = r"C:\WoW335\DBFilesClient"
OUTPUT_DIR = r"C:\WoW335\patch_output"
```

---

### Step 2 -- Register the Map in Map.dbc

**Map.dbc** is the master registry of all maps (continents, instances, arenas,
battlegrounds). Each record is 264 bytes / 66 fields.

#### Map.dbc Field Reference

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | ID | uint32 | Unique map identifier |
| 1 | Directory | string | Internal folder name under `World\Maps\` |
| 2 | InstanceType | uint32 | 0=open world, 1=party dungeon, 2=raid, 3=pvp, 4=arena |
| 3 | Flags | uint32 | Map flags (usually 0 for custom) |
| 4 | PVP | uint32 | 0=PvE, 1=PvP |
| 5-21 | MapName_lang | locstring | Display name (17 uint32: 8 locale slots + 8 unused + 1 mask) |
| 22 | AreaTableID | uint32 | Default area (FK to AreaTable.dbc) |
| 57 | LoadingScreenID | uint32 | FK to LoadingScreens.dbc |
| 63 | ExpansionID | uint32 | 0=Classic, 1=TBC, 2=WotLK |
| 65 | MaxPlayers | uint32 | 0=unlimited (open world), 5/10/25 for instances |

#### Python Code

```python
from world_builder.dbc_injector import register_map

map_id = register_map(
    dbc_dir=DBC_DIR,
    map_name=MAP_NAME,         # Used as both Directory and MapName_lang
    map_id=MAP_ID,             # Explicit ID; pass None for auto
    instance_type=0,           # 0 = open world exterior
)

print("Registered Map ID:", map_id)
```

**What happens internally**: `register_map` opens `Map.dbc`, reads its header,
appends a new 264-byte record with the supplied values, adds the map name
string to the DBC string block, and writes the modified file back to disk.
The `Directory` field must exactly match the folder name used in the WDT/ADT
path (`World\Maps\TelAbim\TelAbim.wdt`).

---

### Step 3 -- Register the Area in AreaTable.dbc

**AreaTable.dbc** defines zones and sub-zones. Each area entry specifies its
parent zone, ambient sound, music, and lighting references. The record is 144
bytes / 36 fields.

#### AreaTable.dbc Field Reference

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | ID | uint32 | Unique area identifier |
| 1 | ContinentID | uint32 | FK to Map.dbc |
| 2 | ParentAreaID | uint32 | 0 for top-level zone; parent area ID for sub-zones |
| 3 | AreaBit | uint32 | Must be unique across all areas (auto-assigned) |
| 4 | Flags | uint32 | Area flags (e.g., 0x40=sanctuary) |
| 7 | AmbienceID | uint32 | FK to SoundAmbience.dbc |
| 8 | ZoneMusic | uint32 | FK to ZoneMusic.dbc |
| 10 | ExplorationLevel | uint32 | Recommended level for exploration XP |
| 11-27 | AreaName_lang | locstring | Display name |
| 35 | LightID | uint32 | FK to Light.dbc |

#### Python Code

```python
from world_builder.dbc_injector import register_area

area_id = register_area(
    dbc_dir=DBC_DIR,
    area_name=MAP_NAME,        # Display name
    map_id=MAP_ID,             # ContinentID
    area_id=AREA_ID,           # Explicit; pass None for auto
    parent_area_id=0,          # 0 = top-level zone
    ambience_id=0,             # Will update later after SoundAmbience registration
    zone_music=0,              # Will update later after ZoneMusic registration
    light_id=0,                # Will update later after Light registration
)

print("Registered Area ID:", area_id)
```

---

### Step 4 -- Register the World Map Area in WorldMapArea.dbc

**WorldMapArea.dbc** controls how the zone appears on the world map (the
interface panel opened with `M`). Without this entry the player sees a blank
map.

#### WorldMapArea.dbc Field Reference

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | ID | uint32 | Unique world map area identifier |
| 1 | MapID | uint32 | FK to Map.dbc |
| 2 | AreaID | uint32 | FK to AreaTable.dbc |
| 3 | AreaName | string | Internal name |
| 4 | LocLeft | float | Left boundary (world X coordinate) |
| 5 | LocRight | float | Right boundary |
| 6 | LocTop | float | Top boundary (world Y coordinate) |
| 7 | LocBottom | float | Bottom boundary |
| 8 | DisplayMapID | int32 | -1 = use own map |
| 10 | ParentWorldMapID | int32 | -1 = top-level |

The boundary coordinates define the visible extent of the zone on the map. For
a single tile at (32, 32) the world-space bounds are approximately:

```
LocLeft   = MAP_SIZE_MAX - (BASE_Y + 1) * TILE_SIZE  (lower X)
LocRight  = MAP_SIZE_MAX - BASE_Y * TILE_SIZE         (upper X)
LocTop    = MAP_SIZE_MAX - (BASE_X + 1) * TILE_SIZE  (lower Y)
LocBottom = MAP_SIZE_MAX - BASE_X * TILE_SIZE         (upper Y)
```

#### Python Code

```python
from world_builder.dbc_injector import register_world_map_area
from world_builder.adt_composer import MAP_SIZE_MAX, TILE_SIZE

# Compute boundary coordinates for tile (32, 32)
loc_left   = MAP_SIZE_MAX - (BASE_Y + GRID_H) * TILE_SIZE
loc_right  = MAP_SIZE_MAX - BASE_Y * TILE_SIZE
loc_top    = MAP_SIZE_MAX - (BASE_X + GRID_W) * TILE_SIZE
loc_bottom = MAP_SIZE_MAX - BASE_X * TILE_SIZE

wma_id = register_world_map_area(
    dbc_dir=DBC_DIR,
    area_name=MAP_NAME,
    map_id=MAP_ID,
    area_id=AREA_ID,
    worldmaparea_id=WMA_ID,
    loc_left=loc_left,
    loc_right=loc_right,
    loc_top=loc_top,
    loc_bottom=loc_bottom,
    display_map_id=-1,         # Display on its own map
    parent_worldmap_id=-1,     # Top-level entry
)

print("Registered WorldMapArea ID:", wma_id)
```

---

### Step 5 -- Register World Map Overlays in WorldMapOverlay.dbc

Overlays are the sub-region textures revealed as the player explores. Each
overlay maps to one or more AreaTable entries and renders a BLP texture on top
of the base map.

#### WorldMapOverlay.dbc Field Reference

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | ID | uint32 | Unique overlay identifier |
| 1 | MapAreaID | uint32 | FK to WorldMapArea.dbc |
| 2-5 | AreaID[4] | uint32[4] | Up to 4 AreaTable IDs this overlay covers |
| 8 | TextureName | string | BLP path (without extension in some builds) |
| 9 | TextureWidth | uint32 | Texture width in pixels |
| 10 | TextureHeight | uint32 | Texture height in pixels |

#### Python Code

```python
from world_builder.dbc_injector import register_world_map_overlay

overlay_id = register_world_map_overlay(
    dbc_dir=DBC_DIR,
    map_area_id=WMA_ID,
    texture_name="Interface\\WorldMap\\{}\\{}1".format(MAP_NAME, MAP_NAME),
    worldmapoverlay_id=WMO_OVERLAY_ID,
    area_ids=[AREA_ID],
    texture_width=512,
    texture_height=512,
    hit_rect_bottom=512,
    hit_rect_right=512,
)

print("Registered WorldMapOverlay ID:", overlay_id)
```

---

### Step 6 -- Register the Loading Screen in LoadingScreens.dbc

The loading screen is displayed while the zone loads. It references a BLP
texture stored in `Interface\Glues\LoadingScreens\`.

#### LoadingScreens.dbc Field Reference

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | ID | uint32 | Unique loading screen identifier |
| 1 | Name | string | Internal name (e.g., "LoadScreenTelAbim") |
| 2 | FileName | string | BLP path (relative to MPQ root) |
| 3 | HasWideScreen | uint32 | 0=standard only, 1=has widescreen variant |

#### Python Code

```python
from world_builder.dbc_injector import register_loading_screen

ls_filename = "Interface\\Glues\\LoadingScreens\\LoadScreen{}.blp".format(MAP_NAME)

ls_id = register_loading_screen(
    dbc_dir=DBC_DIR,
    name="LoadScreen{}".format(MAP_NAME),
    filename=ls_filename,
    loadingscreen_id=LOADING_ID,
    has_widescreen=1,
)

print("Registered LoadingScreen ID:", ls_id)
```

> After registering the loading screen you need to **link it to the map**.
> The `register_map` function accepts a `loading_screen_id` parameter. If you
> already registered the map without it, you can manually patch Map.dbc field
> index 57 (LoadingScreenID) using the `DBCInjector` class. See
> [change_loading_screen.md](change_loading_screen.md) for details.

---

### Step 7 -- Generate the WDT File

The **WDT** (World Data Table) is a binary file that declares which of the
64x64 possible ADT tiles actually exist. It consists of four chunks:

1. **MVER** -- version (always 18 for WotLK)
2. **MPHD** -- header flags
3. **MAIN** -- 64x64 grid of tile presence flags (8 bytes per entry)
4. **MWMO** -- world map object (empty for terrain-only maps)

#### MPHD Flags

| Value | Meaning |
|---|---|
| 0x00 | No special flags |
| 0x04 | Use highres alpha maps |
| 0x80 | Big alpha (WotLK standard -- recommended) |

#### Python Code

```python
from world_builder.wdt_generator import create_wdt

wdt_data = create_wdt(
    active_coords=COORDS,      # [(32, 32)] for a single tile
    mphd_flags=0x80,           # Big alpha (WotLK standard)
)

print("WDT size:", len(wdt_data), "bytes")
print("Active tiles:", len(COORDS))
```

**Validation**: `create_wdt` raises `ValueError` if any coordinate is outside
the 0-63 range.

---

### Step 8 -- Create ADT Terrain Tiles

Each ADT file contains the actual terrain data for one tile: heightmaps,
normals, texture layers, and alpha maps. The file is ~200-300 KB per tile
depending on texture count.

#### ADT File Structure

```
MVER  - Version (18)
MHDR  - Header with offsets to all top-level chunks (64 bytes)
MCIN  - 256 entries pointing to each MCNK sub-chunk (4096 bytes)
MTEX  - Null-terminated texture path string block
MMDX  - M2 model filename block (empty for basic tiles)
MMID  - M2 offset table (empty)
MWMO  - WMO filename block (empty)
MWID  - WMO offset table (empty)
MDDF  - Doodad placement definitions (empty)
MODF  - WMO placement definitions (empty)
256x MCNK - 16x16 grid of terrain sub-chunks
```

Each MCNK sub-chunk contains:

- **MCVT**: 145 height values (9x9 outer + 8x8 inner interleaved grid)
- **MCNR**: 145 normal vectors (int8 x/y/z per vertex)
- **MCLY**: Texture layer definitions (up to 4 layers, 16 bytes each)
- **MCAL**: Alpha maps (64x64 bytes per layer, layers 1-3 only)
- **MCRF**: Doodad/object references (empty)
- **MCSE**: Sound emitters (empty)

#### 8a -- Flat Terrain (Simplest Case)

```python
from world_builder.adt_composer import create_adt

adt_data = create_adt(
    tile_x=BASE_X,
    tile_y=BASE_Y,
    heightmap=None,            # None = flat terrain at height 0
    texture_paths=[
        "Tileset\\Generic\\Grass01.blp",
    ],
    splat_map=None,            # No alpha blending needed for single texture
    area_id=AREA_ID,
)

print("ADT size:", len(adt_data), "bytes")
```

#### 8b -- Custom Heightmap

The heightmap is a 2D list of floats (any resolution -- it gets bilinearly
resampled to fit the tile). Heights are in game yards.

```python
import math

# Generate a simple sine-wave heightmap (64x64 input resolution)
heightmap = []
for row in range(64):
    row_data = []
    for col in range(64):
        h = 20.0 * math.sin(row * 0.1) * math.cos(col * 0.1)
        row_data.append(h)
    heightmap.append(row_data)

adt_data = create_adt(
    tile_x=BASE_X,
    tile_y=BASE_Y,
    heightmap=heightmap,
    texture_paths=[
        "Tileset\\Generic\\Grass01.blp",     # Layer 0: base
        "Tileset\\Generic\\Rock01.blp",      # Layer 1: overlay
    ],
    splat_map={
        1: [[128] * 64 for _ in range(64)],  # 50% opacity everywhere
    },
    area_id=AREA_ID,
)
```

#### 8c -- Multi-Texture Splat Map

Up to 4 texture layers are supported per MCNK sub-chunk. Layer 0 is always the
base (full coverage, no alpha map). Layers 1-3 each have a 64x64 alpha map
(values 0-255).

```python
import random

# Four-texture setup with procedural alpha blending
texture_paths = [
    "Tileset\\Generic\\Sand01.blp",      # Layer 0: beach sand (base)
    "Tileset\\Generic\\Grass01.blp",     # Layer 1: grass
    "Tileset\\Generic\\Rock01.blp",      # Layer 2: rock
    "Tileset\\Generic\\Snow01.blp",      # Layer 3: snow
]

# Build alpha maps: grass where elevation > 5, rock where slope > 30 deg,
# snow above elevation 80
splat_grass = [[0] * 64 for _ in range(64)]
splat_rock  = [[0] * 64 for _ in range(64)]
splat_snow  = [[0] * 64 for _ in range(64)]

for r in range(64):
    for c in range(64):
        # Sample the heightmap at this alpha cell
        hr = int(r * (len(heightmap) - 1) / 63)
        hc = int(c * (len(heightmap[0]) - 1) / 63)
        h = heightmap[hr][hc]

        if h > 5.0:
            splat_grass[r][c] = min(255, int((h - 5.0) * 10))
        if h > 40.0:
            splat_rock[r][c] = min(255, int((h - 40.0) * 5))
        if h > 80.0:
            splat_snow[r][c] = min(255, int((h - 80.0) * 8))

splat_map = {
    1: splat_grass,
    2: splat_rock,
    3: splat_snow,
}

adt_data = create_adt(
    tile_x=BASE_X,
    tile_y=BASE_Y,
    heightmap=heightmap,
    texture_paths=texture_paths,
    splat_map=splat_map,
    area_id=AREA_ID,
)
```

---

### Step 9 -- Terrain Sculpting with Zone Definitions

For production-quality terrain, use the **TerrainSculptor** pipeline. It accepts
a declarative zone definition and produces heightmaps, texture layers, doodad
placements, WMO placements, water planes, and area IDs automatically.

#### Zone Definition Schema

```python
zone_definition = {
    'name': 'TelAbim',
    'grid_size': (3, 3),               # 3x3 ADT tiles
    'base_coords': (31, 31),           # Starting tile coordinate
    'sea_level': 0.0,                  # Ocean surface height
    'seed': 42,                        # Reproducible noise seed

    'global_water': {
        'elevation': 0.0,
        'type': 'ocean',               # 'ocean', 'lake', 'lava', 'swamp'
    },

    'subzones': [
        {
            'name': 'Tel Abim Coast',
            'area_id': 5001,
            'center': (0.5, 0.5),      # Normalised (0-1) within zone
            'radius': 0.4,
            'shape': 'circle',         # 'circle' or 'polygon'
            'falloff': 0.3,            # Edge blending width
            'terrain_type': 'island',  # 'island','plateau','volcano',
                                       # 'valley','ridge','noise'
            'elevation': (0, 60),      # (min, max) height range
            'weight': 1.0,             # Blending weight
            'textures': [
                "Tileset\\Generic\\Sand01.blp",
                "Tileset\\Generic\\Grass01.blp",
            ],
            'doodads': {
                "World\\Doodads\\Trees\\PalmTree01.m2": 0.001,  # density
                "World\\Doodads\\Rocks\\RockSmall01.m2": 0.002,
            },
            'doodad_filters': {
                'elevation': {'min': 2.0, 'max': 100.0},
                'slope': {'max': 35.0},
                'water_distance': {'min': 2.0},
            },
            'structures': [
                {
                    'model': "World\\wmo\\Buildings\\Human_Farm.wmo",
                    'position': (0.5, 0.4),    # Normalised
                    'rotation': (0.0, 45.0, 0.0),
                    'scale': 1.0,
                },
            ],
        },
        {
            'name': 'Tel Abim Volcano',
            'area_id': 5002,
            'center': (0.3, 0.7),
            'radius': 0.15,
            'terrain_type': 'volcano',
            'elevation': (0, 120),
            'terrain_params': {
                'caldera_radius': 0.05,
                'caldera_depth': 20.0,
            },
            'textures': [
                "Tileset\\Generic\\Rock01.blp",
                "Tileset\\Generic\\Cliff01.blp",
            ],
            'water': [
                {
                    'elevation': 95.0,
                    'type': 'lava',
                    'boundary': 'caldera',
                },
            ],
        },
    ],
}
```

#### Terrain Primitives Reference

| Primitive | Function | Parameters |
|---|---|---|
| `island` | Raised landmass with coastal falloff | center, radius, elevation, falloff |
| `plateau` | Flat top with steep cliff edges | bounds, elevation, edge_steepness |
| `volcano` | Cone with inner caldera depression | center, base_radius, peak_height, caldera_radius, caldera_depth |
| `valley` | Inverted island (sunken basin) | center, radius, depth, falloff |
| `ridge` | Linear elevated feature | start, end, width, height, falloff |
| `noise` | Pure procedural Simplex noise | scale, octaves, persistence, lacunarity |

#### Running the Full Pipeline

```python
from world_builder.terrain_sculptor import (
    TerrainSculptor, sculpt_zone, sculpt_for_adt_composer
)

# Option A: Get raw sculpted data
sculpted = sculpt_zone(zone_definition)
# Returns: heightmaps, textures, doodads, wmos, water, area_ids

# Option B: Get data formatted for adt_composer (recommended)
tile_data = sculpt_for_adt_composer(zone_definition)

# tile_data is a dict keyed by (tile_x, tile_y), each value containing:
#   heightmap, texture_paths, splat_map, area_id, area_id_map,
#   doodads, wmos, water

# Option C: Use the class directly for fine-grained control
sculptor = TerrainSculptor(zone_definition)
heightmaps = sculptor.generate_heightmaps()
textures = sculptor.generate_textures(heightmaps)
doodads = sculptor.generate_doodads(heightmaps)
wmos = sculptor.generate_wmos(heightmaps)
water = sculptor.generate_water()
area_ids = sculptor.generate_area_ids()
```

#### Creating ADTs from Sculpted Data

```python
from world_builder.adt_composer import create_adt

all_adt_data = {}
for (tile_x, tile_y), td in tile_data.items():
    adt_bytes = create_adt(
        tile_x=tile_x,
        tile_y=tile_y,
        heightmap=td['heightmap'],
        texture_paths=td['texture_paths'],
        splat_map=td['splat_map'],
        area_id=td['area_id'],
    )
    all_adt_data[(tile_x, tile_y)] = adt_bytes

print("Generated", len(all_adt_data), "ADT tiles")
```

---

### Step 10 -- Generate Artwork Assets

#### World Map Artwork

```python
from world_builder.artwork_pipeline import (
    generate_world_map, generate_zone_artwork_bundle,
    generate_loading_screen
)
from world_builder.artwork_pipeline import SubzoneDefinition
import numpy as np

# Normalise the heightmap for the world map renderer (expects 0.0-1.0)
hm = np.array(tile_data[(32, 32)]['heightmap'], dtype=np.float64)
hm_norm = (hm - hm.min()) / max(hm.max() - hm.min(), 1.0)

# Define subzones for the artwork renderer
art_subzones = [
    SubzoneDefinition(
        name="Tel Abim Coast",
        boundary=[(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)],
        color=(120, 180, 80),
    ),
]

world_map_img = generate_world_map(
    heightmap=hm_norm,
    subzones=art_subzones,
    water_level=0.0,
    size=(1002, 668),
    zone_name=MAP_NAME,
)
```

#### Complete Artwork Bundle (One Call)

```python
bundle = generate_zone_artwork_bundle(
    zone_name=MAP_NAME,
    heightmap=hm_norm,
    subzones=art_subzones,
    theme='tropical',          # 'tropical', 'volcanic', 'underground', 'titan'
    output_dir=OUTPUT_DIR,
    water_level=0.0,
    save_png=True,
)

# bundle is a dict mapping MPQ path -> PIL Image
for mpq_path in bundle:
    print("Generated:", mpq_path)
```

---

### Step 11 -- Pack into MPQ Directory Structure

```python
from world_builder.mpq_packer import MPQPacker
from world_builder.wdt_generator import create_wdt

# Regenerate WDT for multi-tile grid
all_coords = list(all_adt_data.keys())
wdt_data = create_wdt(all_coords, mphd_flags=0x80)

# Create packer
packer = MPQPacker(OUTPUT_DIR, patch_name="patch-4.MPQ")

# Add WDT
packer.add_wdt(MAP_NAME, wdt_data)

# Add all ADTs
for (tx, ty), adt_bytes in all_adt_data.items():
    packer.add_adt(MAP_NAME, tx, ty, adt_bytes)

# Add modified DBC files
import os
for dbc_name in ['Map', 'AreaTable', 'WorldMapArea', 'WorldMapOverlay',
                  'LoadingScreens', 'ZoneMusic', 'SoundAmbience', 'Light']:
    dbc_path = os.path.join(DBC_DIR, '{}.dbc'.format(dbc_name))
    if os.path.isfile(dbc_path):
        with open(dbc_path, 'rb') as f:
            packer.add_dbc(dbc_name, f.read())

# Build directory structure (or MPQ if StormLib is available)
output_path = packer.build_directory()
# or: output_path = packer.build_mpq()

print("MPQ content written to:", output_path)
```

#### MPQ File Placement

The resulting directory structure mirrors what goes inside `patch-4.MPQ`:

```
mpq_content/
  World/
    Maps/
      TelAbim/
        TelAbim.wdt
        TelAbim_32_32.adt
  DBFilesClient/
    Map.dbc
    AreaTable.dbc
    WorldMapArea.dbc
    WorldMapOverlay.dbc
    LoadingScreens.dbc
  Interface/
    WorldMap/
      TelAbim/
        TelAbim1.blp          (world map overlay)
    Glues/
      LoadingScreens/
        LoadScreenTelAbim.blp (standard loading screen)
        LoadScreenTelAbimWide.blp (widescreen variant)
```

---

### Step 12 -- High-Level One-Call API

For the simplest possible workflow, use `build_zone()` which orchestrates
everything automatically:

```python
from world_builder import build_zone

result = build_zone(
    name=MAP_NAME,
    output_dir=OUTPUT_DIR,
    coords=COORDS,
    heightmap=heightmap,       # Or None for flat
    texture_paths=[
        "Tileset\\Generic\\Grass01.blp",
        "Tileset\\Generic\\Rock01.blp",
    ],
    splat_map={1: [[128]*64 for _ in range(64)]},
    area_id=AREA_ID,
    dbc_dir=DBC_DIR,           # Pass None to skip DBC registration
    mphd_flags=0x80,
)

print("Map ID:", result['map_id'])
print("Area ID:", result['area_id'])
print("WDT path:", result['wdt_path'])
print("ADT paths:", result['adt_paths'])
print("Output dir:", result['output_dir'])
```

---

### Step 13 -- Server-Side SQL

The server needs database entries to know about the new map. For an open-world
zone the key tables are:

#### `instance_template`

Not required for open-world zones (InstanceType=0). Required only for instances
(InstanceType >= 1). Skip this for exterior zones.

#### `access_requirement`

Controls who can enter the map. For an open-world zone with no restrictions:

```sql
-- Allow unrestricted access to the new zone
DELETE FROM `access_requirement` WHERE `mapId` = 800;
INSERT INTO `access_requirement` (`mapId`, `difficulty`, `level_min`, `level_max`,
    `item_level`, `item`, `item2`, `quest_done_A`, `quest_done_H`,
    `completed_achievement`, `quest_failed_text`, `comment`)
VALUES
(800, 0, 0, 0, 0, 0, 0, 0, 0, 0, '', 'TelAbim - No requirements');
```

#### Area trigger for zone teleportation

If you want an NPC or portal to teleport players to the new zone:

```sql
-- Create an area trigger teleport entry
-- (areatrigger_id must match an AreaTrigger.dbc entry)
DELETE FROM `areatrigger_teleport` WHERE `ID` = 9000;
INSERT INTO `areatrigger_teleport` (`ID`, `target_map`, `target_position_x`,
    `target_position_y`, `target_position_z`, `target_orientation`, `name`)
VALUES
(9000, 800, 0.0, 0.0, 10.0, 0.0, 'Portal to TelAbim');
```

#### Teleport command for testing

```sql
-- GM teleport bookmark
DELETE FROM `game_tele` WHERE `id` = 9000;
INSERT INTO `game_tele` (`id`, `position_x`, `position_y`, `position_z`,
    `orientation`, `map`, `name`)
VALUES
(9000, 0.0, 0.0, 10.0, 0.0, 800, 'TelAbim');
```

---

### Step 14 -- Collision and Pathing (vmap/mmap)

The WoW client renders terrain from ADT files, but the server needs separate
collision (vmap) and pathfinding (mmap) data.

#### VMap Extraction

1. Place your custom `patch-4.MPQ` in the WoW `Data/` directory
2. Run the vmap extractor: `./vmap4extractor` from the server tools
3. Run the vmap assembler: `./vmap4assembler`
4. Copy the resulting `vmaps/` directory to your server

#### MMap Generation

1. After vmap extraction, run: `./mmaps_generator`
2. This produces `mmaps/` directory with pathfinding meshes
3. Copy to your server

> **Note**: For a single custom ADT tile, vmap/mmap generation takes only a few
> seconds. For large multi-tile zones it can take several minutes.

---

## Common Pitfalls and Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| Client crashes on zone load | Map.dbc Directory field mismatch | Ensure Map.dbc Directory matches WDT folder name exactly |
| Black terrain | Missing or invalid texture BLP | Verify texture paths in MTEX block point to real BLP files in MPQ |
| Invisible terrain (fall through) | Missing vmap data | Run vmap extractor/assembler with your patch MPQ |
| No minimap | Missing minimap tiles | Use `minimap_pipeline.generate_test_minimaps()` |
| Map shows blank | Missing WorldMapArea.dbc entry | Register with `register_world_map_area()` |
| No zone name on screen | Missing AreaTable.dbc entry | Register with `register_area()` |
| Tile coord out of range | x or y outside 0-63 | Use coordinates within valid WDT grid |
| More than 4 textures | ADT limit per MCNK | Use at most 4 texture layers |

---

## Validation Steps

1. **DBC validation**: Open modified DBC files in a DBC editor (e.g., WDBX
   Editor) and verify the new records appear with correct field values.

2. **Binary validation**: Use `read_wdt()` and `read_adt()` to round-trip the
   generated files:

```python
from world_builder.wdt_generator import read_wdt
from world_builder.adt_composer import read_adt

# Verify WDT
wdt_info = read_wdt(os.path.join(output_path, "World", "Maps",
                                  MAP_NAME, "{}.wdt".format(MAP_NAME)))
print("WDT version:", wdt_info['version'])
print("Active tiles:", wdt_info['active_coords'])
print("MPHD flags:", hex(wdt_info['mphd_flags']))

# Verify ADT
adt_path = os.path.join(output_path, "World", "Maps",
                         MAP_NAME, "{}_32_32.adt".format(MAP_NAME))
adt_info = read_adt(adt_path)
print("Tile coords:", adt_info['tile_x'], adt_info['tile_y'])
print("Textures:", adt_info['texture_paths'])
print("Area ID:", adt_info['area_id'])
```

3. **In-game verification**: Log into a GM account and teleport:
   `.tele TelAbim` (after adding the `game_tele` SQL entry).

---

## Cross-References

- [Add Custom Music](add_custom_music.md) -- Register ZoneMusic and
  SoundAmbience for this zone
- [Change Loading Screen](change_loading_screen.md) -- Create and register a
  custom loading screen BLP
- [Update Zone Scenery](update_zone_scenery.md) -- Modify existing zone
  terrain and textures
- [Add New Dungeon](add_new_dungeon.md) -- Create an instanced dungeon within
  or alongside this zone
