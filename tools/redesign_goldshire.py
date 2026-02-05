"""
Goldshire Dark Forest Redesign Script

Generates a dramatic redesign of the Goldshire ADT tile (31, 49) using ML
terrain (CNN target + vertex relaxation) trained on real Azeroth heightmaps.
Falls back to procedural generation if the model file is unavailable.

Pipeline (ML terrain):
    extract neighbor edges -> generate_tile_ml() (Coons + CNN + relax)
    -> place WMOs with footprints -> flatten terrain -> export -> MPQ pack

Pipeline (fallback, no model):
    extract neighbor edges -> generate_tile_ml() (Coons + Laplacian only)
    -> place WMOs -> flatten -> export -> MPQ pack

Usage:
    python tools/redesign_goldshire.py
    python tools/redesign_goldshire.py --seed 777
    python tools/redesign_goldshire.py --no-copy

After running:
    1. The script copies patch-4.MPQ to the WoW Data directory
    2. Restart the WoW client
    3. Log in and travel to Goldshire in Elwynn Forest
    4. Terrain should be dark/gothic with Duskwood-style trees and ruins

To revert:
    Delete G:\\WoW AzerothCore\\Data\\patch-4.MPQ
"""

import argparse
import os
import struct
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from world_builder.zone_planner import plan_zone, preview_heightmap
from world_builder.world_state import WorldState


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TILE_X = 31
TILE_Y = 49
MAP_NAME = "Azeroth"
AREA_ID = 12  # Elwynn Forest

DEFAULT_SEED = 777
DEFAULT_WOW_DATA = "G:\\WoW AzerothCore\\Data"
DEFAULT_ADT_SOURCE = "G:\\WoW AzerothCore\\extracted\\World\\Maps\\Azeroth"

# The original Goldshire tile (31, 49) has absolute height range ~32-174,
# mean ~70. We rescale our generated terrain to match this range so the
# tile fits seamlessly into the surrounding Elwynn terrain.

# How many vertices inward from each edge to blend when pinning to neighbors.
# 32 of 129 = ~25% of the tile, gives a smooth transition.
EDGE_BLEND_VERTICES = 32

# ---------------------------------------------------------------------------
# Redesign landmarks -- dark gothic theme replacing Goldshire defaults
# ---------------------------------------------------------------------------

REDESIGN_LANDMARKS = [
    # Dense dark forest covering most of the tile
    {'type': 'forest', 'position': 'center', 'density': 'thick',
     'name': 'Darkwood Thicket'},
    # A cave entrance in the northeast
    {'type': 'cave', 'position': 'northeast', 'radius': 0.05,
     'name': 'Shadow Hollow'},
    # Ruined structures where the old village was
    {'type': 'ruins', 'position': (0.5, 0.6), 'radius': 0.07,
     'name': 'Forsaken Outpost'},
    # A dark pond replacing Crystal Lake
    {'type': 'pond', 'position': (0.3, 0.7), 'radius': 0.05,
     'name': 'Murky Pool'},
    # A cliff ridge along the northwest
    {'type': 'ridge', 'position': 'northwest', 'radius': 0.10,
     'name': 'Darkstone Ridge'},
]

# ---------------------------------------------------------------------------
# WMO building placements for the Forsaken Outpost village area
# ---------------------------------------------------------------------------

# Village center in normalised coords
_VILLAGE_CX = 0.5
_VILLAGE_CY = 0.6

# WMO models known to exist in 3.3.5a client, scattered around village center
WMO_PLACEMENTS = [
    {
        'wmo_path': 'World\\wmo\\Azeroth\\Buildings\\DuskwoodAbandoned_human_farm\\DuskwoodAbandoned_human_farm.wmo',
        'offset': (-0.03, -0.02),   # SW of village center
        'rotation': (0, 0, 15),
        'footprint': (20, 15),
        'name': 'Abandoned Farm (SW)',
    },
    {
        'wmo_path': 'World\\wmo\\Azeroth\\Buildings\\Duskwood_Human_Farm_Burnt\\DuskwoodFarmHouseburnt.wmo',
        'offset': (0.04, -0.01),    # SE of village center
        'rotation': (0, 0, 200),
        'footprint': (20, 15),
        'name': 'Burnt Farm (SE)',
    },
    {
        'wmo_path': 'World\\wmo\\Azeroth\\Buildings\\GuardTower\\GuardTower_destroyed.wmo',
        'offset': (0.0, 0.03),      # N of village center
        'rotation': (0, 0, 45),
        'footprint': (10, 10),
        'name': 'Destroyed Tower',
    },
    {
        'wmo_path': 'World\\wmo\\Azeroth\\Buildings\\DuskwoodAbandoned_Blacksmith\\DuskwoodAbandoned_Blacksmith.wmo',
        'offset': (-0.02, 0.02),    # NW of village center
        'rotation': (0, 0, 90),
        'footprint': (25, 20),
        'name': 'Abandoned Blacksmith',
    },
    {
        'wmo_path': 'World\\wmo\\Azeroth\\Buildings\\Duskwood_human_farm\\Duskwood_human_farm.wmo',
        'offset': (0.03, 0.03),     # NE of village center
        'rotation': (0, 0, 310),
        'footprint': (20, 15),
        'name': 'Dark Farm (NE)',
    },
]


# ---------------------------------------------------------------------------
# ADT heightmap extraction from MPQ
# ---------------------------------------------------------------------------

def _read_heightmap_from_adt_bytes(adt_bytes):
    """Parse raw ADT binary and extract 129x129 absolute heightmap.

    Reads MCNK base position.z and adds MCVT offsets to get true heights.
    """
    heightmap = np.zeros((129, 129), dtype=np.float64)
    data = adt_bytes
    mcnk_magic = b'KNCM'
    mcvt_magic = b'TVCM'

    chunk_idx = 0
    pos = 0
    while pos < len(data) - 8 and chunk_idx < 256:
        if data[pos:pos + 4] == mcnk_magic:
            mcnk_size = struct.unpack_from('<I', data, pos + 4)[0]
            mcnk_start = pos + 8

            chunk_row = chunk_idx // 16
            chunk_col = chunk_idx % 16

            # MCNK header position is at offset 0x68 (3 floats: x, y, z)
            base_z = struct.unpack_from('<f', data, mcnk_start + 0x70)[0]

            inner_pos = mcnk_start + 128
            mcnk_end = mcnk_start + mcnk_size

            while inner_pos < mcnk_end - 8:
                if data[inner_pos:inner_pos + 4] == mcvt_magic:
                    heights = struct.unpack_from('<145f', data, inner_pos + 8)
                    idx = 0
                    for irow in range(17):
                        if irow % 2 == 0:
                            orow = irow // 2
                            grow = chunk_row * 8 + orow
                            for col in range(9):
                                gcol = chunk_col * 8 + col
                                if grow < 129 and gcol < 129:
                                    heightmap[grow, gcol] = base_z + heights[idx]
                                idx += 1
                        else:
                            idx += 8
                    break
                inner_pos += 1

            chunk_idx += 1
            pos = mcnk_start + mcnk_size
        else:
            pos += 1

    return heightmap


def _extract_neighbor_edges(wow_data_dir, tile_x, tile_y):
    """Extract edge height arrays from neighboring tiles via MPQ.

    Searches patch-2, patch, common-2 (highest patch wins) for each
    neighbor ADT. Returns dict of edge arrays.

    Args:
        wow_data_dir: Path to WoW Data directory.
        tile_x, tile_y: Our tile coordinates.

    Returns:
        dict: Keys 'north', 'south', 'east', 'west' with 129-element
              numpy arrays. Missing neighbors are omitted.
    """
    try:
        import mpyq
    except ImportError:
        print("  WARNING: mpyq not installed, cannot extract neighbor edges")
        return {}

    # Neighbor tiles and which edge we need
    # neighbor -> (our_edge_name, neighbor_edge_selector)
    neighbor_map = {
        (tile_x, tile_y - 1): ('north', lambda hm: hm[128, :]),  # above
        (tile_x, tile_y + 1): ('south', lambda hm: hm[0, :]),    # below
        (tile_x - 1, tile_y): ('west', lambda hm: hm[:, 128]),   # left
        (tile_x + 1, tile_y): ('east', lambda hm: hm[:, 0]),     # right
    }

    # Search order: highest patch number wins (latest override)
    mpq_names = ['patch-3.MPQ', 'patch-2.MPQ', 'patch.MPQ', 'common-2.MPQ', 'common.MPQ']

    edges = {}

    for (nx, ny), (edge_name, selector) in neighbor_map.items():
        adt_internal = "World\\Maps\\Azeroth\\Azeroth_{:d}_{:d}.adt".format(nx, ny)
        adt_internal_lower = "world\\maps\\Azeroth\\Azeroth_{:d}_{:d}.adt".format(nx, ny)

        for mpq_name in mpq_names:
            mpq_path = os.path.join(wow_data_dir, mpq_name)
            if not os.path.isfile(mpq_path):
                continue
            try:
                archive = mpyq.MPQArchive(mpq_path)
                # Try both path casings
                adt_bytes = None
                for path_variant in [adt_internal, adt_internal_lower]:
                    try:
                        adt_bytes = archive.read_file(path_variant)
                        break
                    except Exception:
                        continue

                if adt_bytes:
                    hm = _read_heightmap_from_adt_bytes(adt_bytes)
                    edges[edge_name] = selector(hm)
                    print("  {} edge from ({}, {}) via {} "
                          "[min={:.1f} max={:.1f} mean={:.1f}]".format(
                              edge_name, nx, ny, mpq_name,
                              edges[edge_name].min(),
                              edges[edge_name].max(),
                              edges[edge_name].mean()))
                    break
            except Exception:
                continue

    return edges


def build_goldshire_redesign(output_dir, wow_data_dir=None, seed=DEFAULT_SEED,
                             adt_source=None):
    """Build a dark-forest redesigned Goldshire tile packed as patch-4.MPQ.

    Uses ML terrain (CNN target + vertex relaxation) when a trained model
    is available, otherwise falls back to Coons + Laplacian smoothing.
    Both paths produce terrain that seamlessly matches neighbor tile edges.

    Args:
        output_dir: Where to write intermediate and output files.
        wow_data_dir: Path to WoW Data directory. If provided, copies
                      the MPQ there automatically.
        seed: Random seed for reproducible procedural generation.
        adt_source: Path to extracted ADT directory for edge stitching
                    with neighboring tiles.

    Returns:
        str: Path to the generated patch-4.MPQ file.
    """
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("Goldshire Dark Forest Redesign (ML Terrain)")
    print("=" * 60)
    print("  Archetype:  dark_forest")
    print("  Seed:       {}".format(seed))
    print("  Tile:       ({}, {})".format(TILE_X, TILE_Y))

    # ------------------------------------------------------------------
    # Step 1: Plan zone with dark_forest archetype + custom landmarks
    # ------------------------------------------------------------------
    print("\n[1/5] Planning zone with {} landmarks...".format(
        len(REDESIGN_LANDMARKS)))
    for lm in REDESIGN_LANDMARKS:
        print("  - {}: {} at {}".format(
            lm.get('name', '(unnamed)'), lm['type'], lm['position']))

    zone_def = plan_zone(
        name="GoldshireRedesign",
        archetype='dark_forest',
        landmarks=REDESIGN_LANDMARKS,
        grid_size=(1, 1),
        base_coords=(TILE_X, TILE_Y),
        seed=seed,
        area_id_start=AREA_ID,
    )

    print("  Subzones generated: {}".format(len(zone_def.get('subzones', []))))
    for sz in zone_def.get('subzones', []):
        print("    - {} (area_id={}, terrain={})".format(
            sz.get('name', '?'), sz.get('area_id', 0),
            sz.get('terrain_type', '?')))

    # ------------------------------------------------------------------
    # Step 2: Create WorldState and extract neighbor edges
    # ------------------------------------------------------------------
    print("\n[2/5] Extracting neighbor edges from game data...")
    ws = WorldState()
    ws.base_coords = (TILE_X, TILE_Y)
    ws.grid_size = (1, 1)
    ws.map_name = MAP_NAME
    ws.zone_def = zone_def

    if adt_source:
        ws.set_adt_source(adt_source)

    # Extract neighbor edges from MPQ archives
    edge_arrays = _extract_neighbor_edges(
        wow_data_dir or DEFAULT_WOW_DATA, TILE_X, TILE_Y)

    if edge_arrays:
        all_edge_vals = np.concatenate(list(edge_arrays.values()))
        print("  Neighbor edge range: {:.1f} - {:.1f} (mean {:.1f})".format(
            float(all_edge_vals.min()), float(all_edge_vals.max()),
            float(all_edge_vals.mean())))
    else:
        print("  WARNING: No neighbor edges, using flat 70.0")
        edge_arrays = {
            'north': np.full(129, 70.0),
            'south': np.full(129, 70.0),
            'west': np.full(129, 70.0),
            'east': np.full(129, 70.0),
        }

    # ------------------------------------------------------------------
    # Step 3: Generate terrain using ML pipeline (CNN + relaxation)
    # ------------------------------------------------------------------
    print("\n[3/5] Generating terrain via ML pipeline (Coons + CNN + relax)...")
    gen = ws._get_terrain_generator()
    if gen.has_model:
        print("  CNN model loaded — using learned terrain features")
    else:
        print("  No CNN model — falling back to Coons + Laplacian smoothing")

    hm = ws.generate_tile_ml(TILE_X, TILE_Y, edge_arrays=edge_arrays)
    print("  Generated heightmap range: {:.1f} - {:.1f}".format(
        float(hm.min()), float(hm.max())))

    # Apply zone_def textures from the planner
    from world_builder.terrain_sculptor import TerrainSculptor
    sculptor = TerrainSculptor(zone_def)
    tex_result = sculptor.generate_textures({(TILE_X, TILE_Y): hm})
    tile_tex = tex_result['tile_data'].get((TILE_X, TILE_Y), {})
    tile_tex_paths = tile_tex.get('texture_paths', [])
    chunk_layers = tile_tex.get('chunk_layers', {})

    tex_freq = {}
    for cl in chunk_layers.values():
        for tid in cl.get('texture_ids', []):
            if tid is not None and tid < len(tile_tex_paths):
                path = tile_tex_paths[tid]
                tex_freq[path] = tex_freq.get(path, 0) + 1
    sorted_tex = sorted(tex_freq.items(), key=lambda x: -x[1])
    final_tex_paths = [t[0] for t in sorted_tex[:4]]
    if not final_tex_paths:
        final_tex_paths = ["Tileset\\Generic\\Black.blp"]

    ws.textures[(TILE_X, TILE_Y)] = {
        'texture_paths': final_tex_paths,
        'splat_map': None,
    }

    # Generate doodads from zone planner
    raw_doodads = sculptor.generate_doodads({(TILE_X, TILE_Y): hm})
    for d in raw_doodads:
        pos = d.get('position', (0, 0, 0))
        new_z = ws.get_height_at(pos[0], pos[1])
        ws.doodads.append({
            'model': d.get('model', d.get('model_path', '')),
            'position': (pos[0], pos[1], new_z),
            'rotation': d.get('rotation', (0, 0, 0)),
            'scale': d.get('scale', 1.0),
            'flags': d.get('flags', 0),
            'unique_id': ws._next_unique_id(),
            'footprint': None,
        })

    # Generate area IDs
    ws.area_ids = sculptor.generate_area_ids()

    print("  Doodads: {}".format(len(ws.doodads)))

    # ------------------------------------------------------------------
    # Step 4: Place WMO buildings with footprints -> terrain auto-flattened
    # ------------------------------------------------------------------
    print("\n[4/5] Placing WMO buildings at Forsaken Outpost...")
    wmo_count = 0
    for i, wmo_def in enumerate(WMO_PLACEMENTS):
        norm_x = _VILLAGE_CX + wmo_def['offset'][0]
        norm_y = _VILLAGE_CY + wmo_def['offset'][1]

        wx, wy = ws.norm_to_world(norm_x, norm_y)

        wmo = ws.add_wmo(
            model=wmo_def['wmo_path'],
            position=(wx, wy),
            rotation=wmo_def['rotation'],
            footprint=wmo_def.get('footprint'),
            unique_id=1000 + i,
        )

        wmo_count += 1
        print("  + {} at world ({:.0f}, {:.0f}, {:.1f})".format(
            wmo_def['name'], wmo['position'][0], wmo['position'][1],
            wmo['position'][2]))

    print("  Placed {} / {} WMO buildings".format(wmo_count, len(WMO_PLACEMENTS)))

    # Flatten terrain under all footprinted entities + re-stitch edges
    print("  Flattening terrain under buildings (blend_margin=4.0)...")
    ws.flatten_for_entities(blend_margin=4.0)
    print("  Terrain flattened and edges re-stitched")

    # ------------------------------------------------------------------
    # Step 5: Export and pack MPQ (only dirty tiles)
    # ------------------------------------------------------------------
    print("\n[5/5] Exporting and packing into patch-4.MPQ...")
    mpq_path = ws.pack_mpq(output_dir, "patch-4.MPQ",
                           wow_data_dir=wow_data_dir,
                           big_alpha=False)
    print("  Output: {}".format(mpq_path))
    print("  Dirty tiles exported: {}".format(len(ws._dirty_tiles)))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    pipeline = "CNN + relaxation" if gen.has_model else "Coons + Laplacian"
    print("  Pipeline:   edges -> {} -> WMOs -> flatten -> MPQ".format(pipeline))
    print("  Archetype:  dark_forest")
    print("  Seed:       {}".format(seed))
    print("  Map:        {} (Azeroth)".format(MAP_NAME))
    print("  Tile:       ({}, {})".format(TILE_X, TILE_Y))
    print("  Subzones:   {}".format(len(zone_def.get('subzones', []))))
    print("  Doodads:    {} placed".format(len(ws.doodads)))
    print("  WMOs:       {} placed".format(len(ws.wmos)))
    print("  Edges:      {} neighbors".format(len(edge_arrays)))

    if wow_data_dir:
        print("\n  TESTING INSTRUCTIONS:")
        print("  1. The patch has been copied to your WoW Data directory")
        print("  2. Restart the WoW client (ADT changes require restart)")
        print("  3. Log in and travel to Goldshire in Elwynn Forest")
        print("  4. Terrain should be dark/gothic: Duskwood trees, cobblestone,")
        print("     ruins, and a murky pool instead of Crystal Lake")
        print("  5. Buildings should sit on flattened terrain")
        print("  6. Tile edges should blend seamlessly with surrounding tiles")
        print("  7. To revert: delete G:\\WoW AzerothCore\\Data\\patch-4.MPQ")
    else:
        print("\n  To test: copy patch-4.MPQ to your WoW Data directory")
        print("  Then restart the WoW client and visit Goldshire")

    return mpq_path


def main():
    parser = argparse.ArgumentParser(
        description="Redesign Goldshire tile (31, 49) with dark_forest archetype"
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "output", "goldshire_redesign"),
        help="Output directory for generated files",
    )
    parser.add_argument(
        "--wow-data",
        default=DEFAULT_WOW_DATA,
        help="Path to WoW Data directory (for auto-copy)",
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Don't copy the MPQ to the WoW Data directory",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed for procedural generation (default: {})".format(
            DEFAULT_SEED),
    )
    parser.add_argument(
        "--adt-source",
        default=DEFAULT_ADT_SOURCE,
        help="Path to extracted Azeroth ADT directory for edge stitching",
    )

    args = parser.parse_args()

    wow_data = None if args.no_copy else args.wow_data
    adt_source = args.adt_source

    if wow_data and not os.path.isdir(wow_data):
        print("WARNING: WoW Data directory not found: {}".format(wow_data))
        print("         MPQ will be generated but not copied.")
        wow_data = None

    if adt_source and not os.path.isdir(adt_source):
        print("NOTE: ADT source directory not found: {}".format(adt_source))
        print("      Edge stitching will use internal averaging only.")
        adt_source = None

    build_goldshire_redesign(
        output_dir=args.output_dir,
        wow_data_dir=wow_data,
        seed=args.seed,
        adt_source=adt_source,
    )


if __name__ == "__main__":
    main()
