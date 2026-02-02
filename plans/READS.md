# Plan: Add Read/Import Capabilities to world_builder Modules

## Current State

| Module | Has Read? | Notes |
|--------|-----------|-------|
| `dbc_injector.py` | YES | Full `read()` method for DBC files |
| `blp_converter.py` | YES | BLP2PNG in parent library |
| `minimap_pipeline.py` | YES | `import_minimap_tiles()` |
| `qa_validator.py` | N/A | Validation-only (fine as-is) |
| `wdt_generator.py` | NO | No reader exists anywhere |
| `adt_composer.py` | NO | Parent has `ADTFile` reader at `adt_file.py` |
| `dungeon_builder.py` | NO | Parent has `WMOFile` reader at `wmo_file.py` |
| `mpq_packer.py` | NO | Parent has `MPQFile` at `archives/mpq/__init__.py` |
| `sql_generator.py` | NO | Text format, regex-parseable |
| `script_generator.py` | NO | Lua text, regex-parseable |
| `spell_registry.py` | NO | Can import from JSON/Lua |
| `terrain_sculptor.py` | NO | Can import heightmap from ADT data |
| `artwork_pipeline.py` | NO | Can import existing images |

## Changes (9 files to modify)

### 1. `wdt_generator.py` -- Add `read_wdt()` (~60 lines)
- Parse MVER, MPHD, MAIN chunks using struct
- Return `{'active_coords': [(x,y),...], 'mphd_flags': int, 'version': int}`
- Roundtrips directly into `create_wdt(active_coords, mphd_flags)`

### 2. `adt_composer.py` -- Add `read_adt()` (~120 lines)
- Use parent `ADTFile` to parse binary ADT
- Reconstruct 129x129 heightmap from 16x16 MCNK grid (145 verts each)
- Extract texture paths from MTEX, alpha maps from MCAL, doodad/WMO instances from MDDF/MODF
- Return dict matching `create_adt()` input format for roundtripping

### 3. `dungeon_builder.py` -- Add `read_dungeon()` (~180 lines)
- Use parent `WMOFile` to parse WMO root + groups
- Extract rooms as raw vertex/triangle/normal/UV data per group
- Extract portals, materials, lights, doodads
- Return dungeon definition dict; rooms use `'type': 'raw_mesh'` since we can't reverse-engineer primitives
- Add `raw_mesh` handling to WMO assembler so imported geometry roundtrips

### 4. `mpq_packer.py` -- Add `MPQExtractor` class + `extract_map()` (~120 lines)
- `list_files(pattern=None)` -- list archive contents, optional glob filter
- `read_file(internal_path)` -- read file to bytes
- `extract_file(internal_path, output_path)` -- extract to disk
- `extract_map(map_name, output_dir)` -- extract WDT + all ADTs for a map
- Uses parent `MPQFile` (StormLib wrapper) with same `_HAS_STORM` guard pattern

### 5. `sql_generator.py` -- Add `import_sql()` + `_SQLParser` (~150 lines)
- Regex-parse INSERT INTO statements from .sql files
- Handle `--` comments, `/* */` blocks, escaped quotes, NULL
- Map table columns back to builder dict keys (reverse of generation)
- Return `{'items': [...], 'creatures': [...], 'quests': [...], 'gameobjects': [...], 'spawns': [...]}`

### 6. `script_generator.py` -- Add `import_lua_script()` (~80 lines)
- Extract `SPELL_NAME = 12345` constants via regex
- Extract `RegisterCreatureEvent(entry, event, ...)` hooks
- Extract timer intervals from `RegisterEvent` calls
- Return `{'spell_constants': {}, 'boss_entries': [], 'events': [], 'instance_data': {}}`

### 7. `spell_registry.py` -- Add `import_from_json()` + `import_from_lua()` (~60 lines)
- `import_from_json(filepath)` -- reverse of `export_json_config()`, re-registers all spells
- `import_from_lua(filepath)` -- parse `SPELL_NAME = 12345` lines, infer boss grouping from comments

### 8. `terrain_sculptor.py` -- Add `import_heightmap_from_adt()` + `import_texture_rules_from_adt()` (~80 lines)
- `import_heightmap_from_adt(filepath)` -- calls `adt_composer.read_adt()`, returns numpy 129x129 array
- `import_texture_rules_from_adt(filepath)` -- statistical inference of elevation/slope painting rules from alpha map correlation

### 9. `artwork_pipeline.py` -- Add `import_artwork_image()` (~50 lines)
- Load PNG/BLP/TGA images via Pillow (BLP via parent library BLP2PNG)
- Validate dimensions against target type (world_map, loading_screen, etc.)
- Return PIL Image in RGBA mode

### 10. `__init__.py` -- Add imports for all new read/import functions

## Implementation Order (respects dependencies)

1. `wdt_generator.py` (no deps, simplest, validates pattern)
2. `adt_composer.py` (uses parent ADTFile)
3. `mpq_packer.py` (uses parent MPQFile, enables game data extraction)
4. `dungeon_builder.py` (uses parent WMOFile, most complex)
5. `spell_registry.py` (no deps, simple parsing)
6. `sql_generator.py` (no deps, regex parsing)
7. `script_generator.py` (benefits from spell_registry being done)
8. `terrain_sculptor.py` (depends on adt_composer.read_adt)
9. `artwork_pipeline.py` (standalone, simple)

## Execution Strategy
- Group into 3 parallel agents:
  - Agent A: wdt_generator + adt_composer + terrain_sculptor (ADT chain)
  - Agent B: dungeon_builder + mpq_packer + artwork_pipeline (binary formats)
  - Agent C: sql_generator + script_generator + spell_registry (text formats)
- Final pass: update `__init__.py` with new imports

## Verification
- Each read function should roundtrip: `read_X() -> modify -> write_X()` produces valid output
- Test with synthetic data where real game files unavailable
- Verify parent library imports work (ADTFile, WMOFile, MPQFile)
