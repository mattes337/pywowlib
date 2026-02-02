This is a "deep dive" technical roadmap to transforming `pywowlib` into a headless World-Compiler for WotLK (3.3.5a).

This plan assumes you have forked `pywowlib` and are ready to add new modules.

### 📁 Project Structure for the Fork — DONE

Create a new directory `pywowlib/world_builder/` to house these new "Writer" modules. Do not clutter the existing `file_formats` parsers.

```text
pywowlib/
├── file_formats/      # (Existing readers)
├── world_builder/     # (NEW: The Writer Engine)
│   ├── __init__.py        # build_zone() integration API
│   ├── dbc_injector.py    # Handles Map.dbc / AreaTable.dbc
│   ├── wdt_generator.py   # Creates the World Grid
│   ├── adt_composer.py    # The complex Terrain Logic
│   └── mpq_packer.py     # Final build step

```

**Status:** All files created and verified.

---

### Phase 1: The WDT Generator (The Grid) — DONE

The client crashes if the WDT doesn't match the ADT files present. You need a script that accepts a list of active coordinates and generates the bitmask.

**Technical Goal:** Create a valid `MapName.wdt` with a `MAIN` chunk.
**Implementation Detail:**

* **Chunk:** `MAIN` (4096 entries of 8 bytes).
* **Flags:** Set `flag = 1` (Active) for every tile you intend to build.

**Implemented in:** `world_builder/wdt_generator.py`
* `create_wdt(active_coords, mphd_flags=0)` — returns bytes
* `write_wdt(filepath, active_coords, mphd_flags=0)` — writes to disk
* Generates MVER + MPHD + MAIN + MWMO chunks
* Validated: 32,836 bytes for a 3-tile map

---

### Phase 2: The ADT Composer (The Terrain Engine) — DONE

This is the hardest part. You must mathematically convert a 2D height array into WoW's "Interleaved" format.

#### Step 2a: Heightmap to MCVT — DONE

WoW does not use a simple square grid. It uses an **interleaved grid** of 9x9 (outer) and 8x8 (inner) vertices per chunk.

* **Formula:** Interpolates standard heightmap to fit the 145-float array.
* **Scale:** Heights are in game yards, relative to chunk base position.

#### Step 2b: Normals (MCNR) — DONE

If you don't generate this, the terrain will be unlit (full bright) or pitch black.

* **Algorithm:** For every vertex, computes finite-difference gradients and normalizes to `(-127, 127)`.
* **Output:** `MCNR` chunk: 435 bytes (3 bytes per vertex × 145 vertices) + 13 padding bytes.

#### Step 2c: Texturing (MCLY & MCAL) — DONE

WotLK allows 4 textures per chunk.

* **MCLY (Layers):** Defines which textures are used (e.g., `Dirt`, `Grass`, `Rock`, `Snow`).
* **MCAL (Alpha):** 64×64 highres uncompressed alpha maps (4096 bytes per layer).
* **Splat Map Support:** Input dict mapping `texture_index -> 2D alpha array`.

**Implemented in:** `world_builder/adt_composer.py`
* `create_adt(tile_x, tile_y, heightmap=None, texture_paths=None, splat_map=None, area_id=0)` — returns bytes
* `write_adt(filepath, tile_x, tile_y, **kwargs)` — writes to disk
* Full ADT structure: MVER, MHDR, MCIN, MTEX, MMDX, MMID, MWMO, MWID, MDDF, MODF, 256× MCNK
* Each MCNK contains: MCVT, MCNR, MCLY, MCRF, MCAL
* Validated: ~318 KB for a flat terrain tile

---

### Phase 3: The DBC Injector — DONE

`pywowlib` can read WDBX, but for 3.3.5a you must strictly adhere to the column structure or the client will crash.

* **Map.dbc schema:** 66 fields × 4 bytes = 264 bytes per record
* **AreaTable.dbc schema:** 52 fields × 4 bytes = 208 bytes per record
* **Implementation:** Standalone binary DBC reader/writer that works without DBD definitions

**Implemented in:** `world_builder/dbc_injector.py`
* `DBCInjector` class — low-level DBC read/write with string block management
* `register_map(dbc_dir, map_name, map_id=None, instance_type=0)` — inject into Map.dbc
* `register_area(dbc_dir, area_name, map_id, area_id=None, parent_area_id=0)` — inject into AreaTable.dbc

---

### Phase 4: Integration (The Agent API) — DONE

Exposes a high-level API for your AI Agent to call.

**Implemented in:** `world_builder/__init__.py` + `world_builder/mpq_packer.py`

```python
from world_builder import build_zone

result = build_zone(
    name="NewZone",
    output_dir="./output",
    coords=[(32, 32), (32, 33)],
    heightmap=None,           # Optional 2D height array
    texture_paths=["Tileset\\Grass\\GrassLight01.blp"],
    dbc_dir="./DBFilesClient", # Optional: inject into DBC files
    mphd_flags=0x80,
)

# result = {
#     'map_id': 800,          # Assigned map ID (if dbc_dir provided)
#     'area_id': 5001,        # Assigned area ID
#     'wdt_path': '...',      # Path to generated WDT
#     'adt_paths': ['...'],   # Paths to generated ADTs
#     'output_dir': '...',    # Output directory
# }
```

**MPQ Packer:** `MPQPacker` class collects files and writes the correct `World\Maps\{name}\` directory structure. Attempts StormLib MPQ creation if available, otherwise outputs a directory tree for external MPQ tools.

---

### 🛠️ Required Tooling Assessment

You do **not** need extra compiled tools (like C++ extractors) if you implement the above correctly in Python. `pywowlib` handles the binary IO.

**Missing Piece:** You will need **ImageMagick** or **Pillow** (Python lib) to handle the `BLP` (Texture) conversion if you plan to import custom textures. For standard WoW textures, you just reference them by string path (e.g., `Tileset\Expansion02\Tundra\TundraGrass.blp`).

### Bugfix: Restored ChunkHeader

During implementation, discovered that the `ChunkHeader` class had been accidentally removed from `file_formats/wow_common_types.py` (along with `StringBlockChunk`). Both classes have been restored from git history — they are required by `file_formats/adt_chunks.py` and `adt_file.py`.

### Smoke Test Results

All modules pass integration testing:
- WDT generation: 32,836 bytes (MVER+MPHD+MAIN+MWMO)
- ADT generation: ~318 KB per tile (256 MCNK sub-chunks with heights, normals, textures)
- DBC injection: reads/writes binary DBC with string block management
- MPQ packing: correct directory structure output
- `build_zone()`: end-to-end pipeline verified
