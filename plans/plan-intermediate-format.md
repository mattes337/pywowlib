# Plan: Intermediate JSON Format for Zone/Dungeon Export/Import

## Overview

Add an export/import system that serializes WoW zones and dungeons to editable JSON files, and compiles them back to game-ready binary format. Also supports authoring new zones/dungeons from scratch.

**Design decisions (per user):**
- All data in JSON (including heightmaps, alpha maps, vertex arrays)
- Asset paths only (no texture/model copying)
- Auto-allocate new DBC IDs on import

## Existing Read Infrastructure (from READS.md)

All read functions from READS.md are now implemented. The exporter builds directly on these:

| Function | Module | Returns | Used By Exporter |
|----------|--------|---------|------------------|
| `read_wdt(filepath)` | `wdt_generator.py` | `{active_coords, mphd_flags, version}` | Tile discovery |
| `read_adt(filepath)` | `adt_composer.py` | `{tile_x/y, heightmap(129x129), texture_paths, splat_map, doodad/wmo_instances, m2/wmo_filenames, chunks(16x16)}` | Tile data |
| `read_dungeon(wmo_path)` | `dungeon_builder.py` | `{name, rooms[raw_mesh], portals, materials, lights, doodads}` | WMO dungeon data |
| `MPQExtractor.extract_map()` | `mpq_packer.py` | Extracts WDT + ADTs from MPQ to disk | Game data extraction |
| `DBCInjector.read()` | `dbc_injector.py` | Raw DBC records + string block | DBC metadata |

**Key gap:** `read_adt()` returns a 129x129 heightmap (outer vertices only, for `create_adt()` roundtrip) and per-chunk metadata (flags, area_id, position, holes). But it does **not** extract per-chunk normals, vertex colors, shadow maps, sound emitters, or the full 145-float MCVT. The exporter needs to access `ADTFile` directly for these fields alongside `read_adt()` output.

## Export Directory Structure

```
exports/
  zones/elwynn-forest/
    manifest.json              # Master: metadata, type, tile list, file refs
    map.json                   # Map.dbc record fields
    areas.json                 # AreaTable.dbc records for this map
    world_map.json             # WorldMapArea + WorldMapOverlay records
    atmosphere.json            # Light, ZoneMusic, SoundAmbience records
    tiles/
      32_48.json               # One file per ADT tile (heightmap, textures, placements, chunks)
      32_49.json
      ...
  dungeons/the-deadmines/
    manifest.json
    map.json
    areas.json
    dungeon.json               # LFGDungeons + DungeonEncounter + LoadingScreen + AreaTrigger
    wmo/
      root.json                # WMO header, materials, lights, doodads, portals, fog
      group_000.json           # WMO group: vertices, triangles, normals, UVs, batches, BSP
      group_001.json
    tiles/                     # Only if dungeon has outdoor ADT terrain
      ...
```

## New Files

All three files go in `world_builder/`:

### 1. `intermediate_format.py` - Schema helpers & ID allocation

```python
FORMAT_VERSION = "1.0.0"

def slugify(name: str) -> str           # "The Deadmines" -> "the-deadmines"
def load_json(filepath: str) -> dict
def save_json(filepath: str, data: dict, indent=2)
def validate_manifest(data: dict) -> list[str]  # returns error strings

class IDAllocator:
    """Scans existing DBC files and allocates next-free IDs."""
    def __init__(self, dbc_dir: str)
    def next_map_id(self) -> int
    def next_area_id(self) -> int
    def next_area_bit(self) -> int
    def next_worldmaparea_id(self) -> int
    def next_loading_screen_id(self) -> int
    def next_encounter_id(self) -> int
    def next_areatrigger_id(self) -> int
```

Uses `DBCInjector` to read each DBC and call `get_max_id()` / `find_max_field()`.

### 2. `zone_exporter.py` - Binary game files -> JSON

```python
class ZoneExporter:
    def __init__(self, game_data_dir, dbc_dir, output_base="exports")

    def export_zone(self, map_name, map_id) -> str       # returns manifest path
    def export_dungeon(self, map_name, map_id, wmo_path=None) -> str

    # Internal:
    def _export_map_record(self, map_id) -> dict
    def _export_area_records(self, map_id) -> list[dict]
    def _export_world_map_records(self, map_id) -> dict
    def _export_atmosphere_records(self, map_id) -> dict
    def _export_adt_tile(self, adt_filepath) -> dict
    def _export_dungeon_records(self, map_id) -> dict
```

**Key implementation details -- leveraging existing readers:**

- **WDT reading**: Call `read_wdt(filepath)` to get `active_coords` and `mphd_flags`. No custom parser needed.
- **ADT tile export**: Call `read_adt(filepath)` to get tile-level data (textures, m2/wmo filenames, doodad/wmo instances, 129x129 heightmap, per-chunk splat_map, per-chunk metadata). Then also load `ADTFile(filepath)` to extract per-chunk details not in `read_adt()`: full 145-float MCVT heightmaps, MCNR normals, MCLY texture layer flags/effect_id, MCSH shadow maps, MCCV vertex colors, sound emitters.
- **WMO dungeon export**: Call `read_dungeon(wmo_path)` to get rooms (raw_mesh with vertices/triangles/normals/uvs/face_materials), portals, materials, lights, doodads. The intermediate JSON maps directly to this dict structure.
- **MPQ extraction**: If source is an MPQ archive, use `MPQExtractor.extract_map(map_name, temp_dir)` to extract WDT+ADTs to disk first, then export from the extracted files.
- **DBC record unpacking**: Mirror the `_build_*_record()` functions in reverse. Each field is at `field_index * 4` bytes. Use `DBCInjector.get_record_field()` and `get_string()`.

### 3. `zone_importer.py` - JSON -> game-ready binary files

```python
class ZoneImporter:
    def __init__(self, export_dir, output_dir, dbc_dir=None)

    def import_zone(self) -> dict       # returns {map_id, area_ids, paths...}
    def import_dungeon(self) -> dict

    # Internal:
    def _allocate_ids(self, manifest) -> dict
    def _inject_dbc_records(self, manifest, id_map)
    def _build_wdt(self, manifest) -> bytes
    def _build_adt_tile(self, tile_json, id_map) -> bytes
    def _build_wmo(self, dungeon_json) -> dict
    def _pack_output(self, map_name, wdt, adts, wmo_files)
```

**Import strategy -- leveraging existing writers:**

- **ID allocation**: `IDAllocator` scans all DBCs, allocates new IDs. Builds `{original_id: new_id}` mapping.
- **DBC injection**: Calls existing `register_map()`, `register_area()`, `register_world_map_area()`, etc. from `dbc_injector.py` with values from JSON + remapped IDs.
- **WDT generation**: Call `create_wdt(active_coords, mphd_flags)` from `wdt_generator.py`.
- **ADT building**: Uses `create_adt(tile_x, tile_y, heightmap, texture_paths, splat_map, area_id)` for Milestone 1. The JSON tile data is transformed back into `create_adt()` input format (129x129 heightmap from per-chunk MCVT, splat_map from per-chunk alpha maps). For full fidelity (Milestone 2), construct `ADTFile` directly.
- **WMO dungeon building**: Transform JSON back into `read_dungeon()` dict format (rooms with `type: raw_mesh`), then pass to `build_dungeon()` which already supports `raw_mesh` room type. This gives roundtrip for free.
- **Area ID remapping**: Each ADT chunk stores an `area_id`. The importer replaces original area_ids with newly allocated ones.
- **Output packing**: Uses existing `MPQPacker` to organize into `World/Maps/{name}/` structure.

### 4. Update `world_builder/__init__.py` - Add convenience API

```python
from .zone_exporter import ZoneExporter
from .zone_importer import ZoneImporter
from .intermediate_format import create_zone_template, create_dungeon_template
```

Plus thin wrapper functions `export_zone()`, `import_zone()`, `export_dungeon()`, `import_dungeon()` following the `build_zone()` pattern.

## JSON Schemas (Key Files)

### manifest.json
```json
{
  "format_version": "1.0.0",
  "type": "zone|dungeon",
  "name": "Elwynn Forest",
  "slug": "elwynn-forest",
  "source": "export|authored",
  "original_ids": { "map_id": 0, "area_ids": [12, 87] },
  "mphd_flags": 128,
  "tiles": [ {"x": 32, "y": 48, "file": "tiles/32_48.json"} ],
  "files": { "map": "map.json", "areas": "areas.json", ... }
}
```

### tiles/32_48.json (per ADT)

Combines `read_adt()` output (tile-level) with direct `ADTFile` chunk access (per-chunk detail):

```json
{
  "tile_x": 32, "tile_y": 48,
  "textures": ["Tileset\\Elwynn\\ElwynnGrass01.blp"],
  "m2_models": ["World\\Azeroth\\Elwynn\\BushSmall01.m2"],
  "wmo_models": ["World\\wmo\\...\\Farm.wmo"],
  "doodad_placements": [
    {"model_index": 0, "unique_id": 12345, "position": [x,y,z], "rotation": [rx,ry,rz], "scale": 1024, "flags": 0}
  ],
  "wmo_placements": [
    {"model_index": 0, "unique_id": 67890, "position": [x,y,z], "rotation": [rx,ry,rz],
     "extents_min": [x,y,z], "extents_max": [x,y,z], "flags": 0, "doodad_set": 0, "name_set": 0, "scale": 1024}
  ],
  "chunks": [
    {
      "index_x": 0, "index_y": 0,
      "flags": 0, "area_id": 12, "holes": 0,
      "position": [17066.666, 17066.666, 0.0],
      "heightmap": [145 floats],
      "normals": [[nx,ny,nz], ... 145 triplets],
      "texture_layers": [
        {"texture_index": 0, "flags": 0, "effect_id": 0, "alpha_map": null},
        {"texture_index": 1, "flags": 256, "effect_id": 0, "alpha_map": [[64 ints], ...64 rows]}
      ],
      "shadow_map": null,
      "vertex_colors": null,
      "sound_emitters": []
    }
  ]
}
```

**Data source mapping:**
- `textures`, `m2_models`, `wmo_models` -- from `read_adt()` → `texture_paths`, `m2_filenames`, `wmo_filenames`
- `doodad_placements` -- from `read_adt()` → `doodad_instances` (remap `name_id` to `model_index`)
- `wmo_placements` -- from `read_adt()` → `wmo_instances` (remap `name_id` to `model_index`)
- `chunks[].flags/area_id/position/holes` -- from `read_adt()` → `chunks[row][col]`
- `chunks[].heightmap` -- from `ADTFile.mcnk[r][c].mcvt.height` (full 145 floats)
- `chunks[].normals` -- from `ADTFile.mcnk[r][c].mcnr.normals`
- `chunks[].texture_layers` -- from `ADTFile.mcnk[r][c].mcly.layers` + `mcal.layers`
- `chunks[].shadow_map` -- from `ADTFile.mcnk[r][c].mcsh`
- `chunks[].vertex_colors` -- from `ADTFile.mcnk[r][c].mccv`

### wmo/ (dungeon) -- maps directly from `read_dungeon()` output

**wmo/root.json**: Serializes `read_dungeon()` top-level fields:
- `materials[]` -- from `read_dungeon().materials` (texture1/2, shader, blend_mode, flags, colors)
- `portals[]` -- from `read_dungeon().portals` (vertices, plane, room refs)
- `lights[]` -- from `read_dungeon().lights` (type, color, position, intensity, attenuation)
- `doodad_sets[]` + `doodad_definitions[]` -- from `read_dungeon().doodads` (model, position, rotation, scale, color)
- `fog[]`, `skybox`, `ambient_color`, `bounding_box`

**wmo/group_NNN.json**: Serializes each `read_dungeon().rooms[]` entry:
- `vertices`, `triangles`, `normals`, `uvs` -- direct from `raw_mesh` room data
- `face_materials`, `bounds`, `center` -- direct from room dict
- `batches`, `bsp_nodes`, `vertex_colors`, `liquid` -- from `ADTFile` group-level access

### dungeon.json
LFGDungeons, DungeonEncounter, LoadingScreens, AreaTrigger DBC records -- from `DBCInjector` unpacking.

### atmosphere.json
Light, ZoneMusic, SoundAmbience DBC records -- from `DBCInjector` unpacking.

## Implementation Milestones

### Milestone 1: Zone roundtrip (export -> edit -> import)
- `intermediate_format.py`: Full implementation
- `zone_exporter.py`: `export_zone()` using `read_wdt()` + `read_adt()` + `ADTFile` + `DBCInjector`
- `zone_importer.py`: `import_zone()` using `create_wdt()` + `create_adt()` + `register_map/area()` + `MPQPacker`
- `__init__.py`: Add convenience wrappers
- Scope: Map.dbc, AreaTable.dbc, full ADT data (heightmaps, textures, alpha, doodads, WMOs per tile)

### Milestone 2: Full ADT fidelity + remaining DBC
- ADT import via direct `ADTFile` construction (preserves every field exactly)
- WorldMapArea, WorldMapOverlay, atmosphere (Light, ZoneMusic, SoundAmbience) DBC records

### Milestone 3: WMO dungeon support
- WMO export via `read_dungeon()` -> JSON serialization
- WMO import via JSON -> `build_dungeon()` with `raw_mesh` rooms (roundtrip already supported)
- LFGDungeons, DungeonEncounter, LoadingScreens, AreaTrigger DBC records
- `export_dungeon()` / `import_dungeon()`

### Milestone 4: Template generators + validation
- `create_zone_template()` - generates minimal valid JSON for a new zone
- `create_dungeon_template()` - generates minimal valid JSON for a new dungeon
- JSON schema validation
- Integration with `qa_validator.py`

## Critical Files to Modify/Create

| File | Action |
|------|--------|
| `world_builder/intermediate_format.py` | **Create** - Schema, validation, IDAllocator |
| `world_builder/zone_exporter.py` | **Create** - Export pipeline |
| `world_builder/zone_importer.py` | **Create** - Import pipeline |
| `world_builder/__init__.py` | **Modify** - Add imports + convenience functions |

**Existing read-side dependencies (no changes needed):**

| Function | File | Role in Export | Role in Import |
|----------|------|---------------|----------------|
| `read_wdt()` | `wdt_generator.py` | Get active tiles + flags | -- |
| `read_adt()` | `adt_composer.py` | Get tile-level data | -- |
| `ADTFile` | `adt_file.py` | Get per-chunk detail | -- |
| `read_dungeon()` | `dungeon_builder.py` | Get WMO data | -- |
| `MPQExtractor` | `mpq_packer.py` | Extract from MPQ | -- |
| `DBCInjector` | `dbc_injector.py` | Unpack DBC records | Inject DBC records |
| `create_wdt()` | `wdt_generator.py` | -- | Generate WDT |
| `create_adt()` | `adt_composer.py` | -- | Generate ADT |
| `build_dungeon()` | `dungeon_builder.py` | -- | Generate WMO (raw_mesh) |
| `register_map/area/...()` | `dbc_injector.py` | -- | Inject DBC records |
| `MPQPacker` | `mpq_packer.py` | -- | Pack output |

## Verification

1. **Export test**: Export a known zone (e.g. a single-tile custom zone built with `build_zone()`), verify all JSON files are written and contain expected data
2. **Roundtrip test**: Export -> import -> binary-compare the resulting ADT/WDT against originals
3. **Edit test**: Export, modify heightmap values in a tile JSON, import, verify the ADT reflects changes
4. **New zone test**: Create JSON from scratch (or via template), import, verify valid game files produced
5. **ID allocation test**: Import twice into the same DBC directory, verify no ID conflicts
