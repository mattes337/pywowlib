"""
Zone Generation Script - Build a playable WoW zone from a JSON spec.

Reads a Zone Specification JSON (produced by an AI agent or written by hand)
and runs the full pipeline to produce a patch MPQ loadable by the 3.3.5a client.

Pipeline:
    1. Load and validate ZoneSpec from JSON
    2. Convert features -> zone_planner landmarks
    3. plan_zone() -> zone_def
    4. WorldState.from_zone_def() -> initial world (heightmaps, textures, doodads)
    5. Resolve buildings via WMOCatalog
    6. Place WMOs via WorldState.add_wmo()
    7. Generate ML terrain (or procedural fallback)
    8. Flatten terrain under buildings
    9. Export and pack MPQ
   10. Optionally copy to WoW Data directory

Usage:
    python tools/generate_zone.py spec.json
    python tools/generate_zone.py spec.json --output output/my_zone
    python tools/generate_zone.py spec.json --wow-data "G:\\WoW AzerothCore\\Data"
    python tools/generate_zone.py spec.json --no-copy --no-ml
"""

import argparse
import os
import struct
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from world_builder.zone_spec import ZoneSpec
from world_builder.zone_planner import plan_zone
from world_builder.world_state import WorldState
from world_builder.wmo_catalog import WMOCatalog


# ---------------------------------------------------------------------------
# Client path resolution
# ---------------------------------------------------------------------------


def _get_client_path():
    """Get WoW client path from env var, docker/.env, or hardcoded default."""
    path = os.environ.get('WOW_CLIENT_DATA')
    if path:
        return path
    # pywowlib/tools/generate_zone.py -> pywowlib/tools -> pywowlib -> project root
    project_root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    env_file = os.path.join(project_root, 'docker', '.env')
    if os.path.isfile(env_file):
        with open(env_file, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('WOW_CLIENT_DATA='):
                    return line.split('=', 1)[1].strip()
    return 'G:/WoW AzerothCore'


DEFAULT_WOW_DATA = os.path.join(_get_client_path(), "Data")


# ---------------------------------------------------------------------------
# Neighbor edge extraction (reused from redesign_goldshire.py)
# ---------------------------------------------------------------------------

def _read_heightmap_from_adt_bytes(adt_bytes):
    """Parse raw ADT binary and extract 129x129 absolute heightmap."""
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


def _extract_grid_neighbor_edges(wow_data_dir, base_coords, grid_size):
    """Extract boundary edge arrays for an entire tile grid.

    For a multi-tile grid, we only need the external boundary edges
    (tiles adjacent to the grid but not in the grid).

    Args:
        wow_data_dir: Path to WoW Data directory.
        base_coords: (bx, by) of grid origin.
        grid_size: (gw, gh) grid dimensions in tiles.

    Returns:
        dict with keys 'north', 'south', 'east', 'west' mapping to
        dicts of {tile_coord: np.array(129)}.  Returns {} if mpyq
        is unavailable.
    """
    try:
        import mpyq
    except ImportError:
        print("  WARNING: mpyq not installed, cannot extract neighbor edges")
        return {}

    bx, by = base_coords
    gw, gh = grid_size

    mpq_names = ['patch-3.MPQ', 'patch-2.MPQ', 'patch.MPQ',
                 'common-2.MPQ', 'common.MPQ']
    edges = {}

    # North boundary: tiles at y = by - 1
    for tx in range(bx, bx + gw):
        ny = by - 1
        edge = _extract_single_edge(wow_data_dir, mpq_names, tx, ny,
                                    lambda hm: hm[128, :])
        if edge is not None:
            edges.setdefault('north', {})[tx] = edge

    # South boundary: tiles at y = by + gh
    for tx in range(bx, bx + gw):
        ny = by + gh
        edge = _extract_single_edge(wow_data_dir, mpq_names, tx, ny,
                                    lambda hm: hm[0, :])
        if edge is not None:
            edges.setdefault('south', {})[tx] = edge

    # West boundary: tiles at x = bx - 1
    for ty in range(by, by + gh):
        nx = bx - 1
        edge = _extract_single_edge(wow_data_dir, mpq_names, nx, ty,
                                    lambda hm: hm[:, 128])
        if edge is not None:
            edges.setdefault('west', {})[ty] = edge

    # East boundary: tiles at x = bx + gw
    for ty in range(by, by + gh):
        nx = bx + gw
        edge = _extract_single_edge(wow_data_dir, mpq_names, nx, ty,
                                    lambda hm: hm[:, 0])
        if edge is not None:
            edges.setdefault('east', {})[ty] = edge

    return edges


def _extract_single_edge(wow_data_dir, mpq_names, tile_x, tile_y, selector):
    """Extract one edge array from a neighbor tile via MPQ.

    Returns:
        np.array(129) or None.
    """
    try:
        import mpyq
    except ImportError:
        return None

    adt_internal = "World\\Maps\\Azeroth\\Azeroth_{:d}_{:d}.adt".format(
        tile_x, tile_y)
    adt_internal_lower = "world\\maps\\Azeroth\\Azeroth_{:d}_{:d}.adt".format(
        tile_x, tile_y)

    for mpq_name in mpq_names:
        mpq_path = os.path.join(wow_data_dir, mpq_name)
        if not os.path.isfile(mpq_path):
            continue
        try:
            archive = mpyq.MPQArchive(mpq_path)
            adt_bytes = None
            for path_variant in [adt_internal, adt_internal_lower]:
                try:
                    adt_bytes = archive.read_file(path_variant)
                    break
                except Exception:
                    continue
            if adt_bytes:
                hm = _read_heightmap_from_adt_bytes(adt_bytes)
                return selector(hm)
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Main generation pipeline
# ---------------------------------------------------------------------------

def generate_zone(spec_path, output_dir=None, wow_data=None,
                  adt_source=None, copy=True, use_ml=True,
                  map_name="Azeroth"):
    """Full zone generation pipeline from spec JSON.

    Args:
        spec_path: Path to zone specification JSON file.
        output_dir: Output directory. Auto-derived from spec name if None.
        wow_data: Path to WoW Data directory for MPQ copy + edge extraction.
        adt_source: Path to extracted ADT directory for edge stitching.
        copy: If True and wow_data provided, copy MPQ to WoW Data.
        use_ml: If True, use ML terrain generation (falls back gracefully).
        map_name: Map name for ADT packing (default "Azeroth").
                  Must match the client's map name to override existing tiles.

    Returns:
        str: Path to the generated patch-4.MPQ file.
    """
    # ------------------------------------------------------------------
    # Step 1: Load and validate spec
    # ------------------------------------------------------------------
    print("=" * 60)
    print("Zone Generation Pipeline")
    print("=" * 60)

    print("\n[1/7] Loading zone specification...")
    spec = ZoneSpec.from_json(spec_path)
    print("  Name:      {}".format(spec.name))
    print("  Archetype: {}".format(spec.archetype))
    print("  Grid:      {}x{}".format(*spec.grid_size))
    print("  Base:      ({}, {})".format(*spec.base_coords))
    print("  Seed:      {}".format(spec.seed))
    print("  Features:  {}".format(len(spec.features)))
    print("  Buildings: {}".format(len(spec.buildings)))

    if output_dir is None:
        safe_name = spec.name.lower().replace(' ', '_').replace("'", '')
        output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "output", safe_name)
    os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 2: Convert features to landmarks and plan zone
    # ------------------------------------------------------------------
    print("\n[2/7] Planning zone...")
    landmarks = spec.to_landmarks()
    for lm in landmarks:
        print("  - {} ({}) at {}".format(
            lm.get('name', '(unnamed)'), lm['type'], lm['position']))

    zone_def = plan_zone(
        name=spec.name,
        archetype=spec.archetype,
        landmarks=landmarks,
        grid_size=spec.grid_size,
        sea_level=spec.sea_level,
        seed=spec.seed,
        base_coords=spec.base_coords,
    )
    print("  Subzones: {}".format(len(zone_def.get('subzones', []))))

    # ------------------------------------------------------------------
    # Step 3: Create WorldState
    # ------------------------------------------------------------------
    print("\n[3/7] Creating WorldState from zone definition...")
    ws = WorldState.from_zone_def(zone_def, adt_source=adt_source)
    # Override map_name so ADTs are packed under the correct map directory
    # (e.g. World\Maps\Azeroth\Azeroth_31_49.adt instead of zone name)
    ws.map_name = map_name
    print("  Map name:   {}".format(ws.map_name))
    print("  Heightmaps: {} tiles".format(len(ws.heightmaps)))
    print("  Doodads:    {}".format(len(ws.doodads)))

    # ------------------------------------------------------------------
    # Step 4: ML terrain (optional, replaces procedural heightmaps)
    # ------------------------------------------------------------------
    if use_ml:
        print("\n[4/7] Generating ML terrain...")
        # Extract external edges if game data available
        external_edges = None
        if wow_data and os.path.isdir(wow_data):
            print("  Extracting neighbor edges from game data...")
            raw_edges = _extract_grid_neighbor_edges(
                wow_data, spec.base_coords, spec.grid_size)
            if raw_edges:
                # For single-tile grids, flatten to simple dict
                bx, by = spec.base_coords
                gw, gh = spec.grid_size
                if gw == 1 and gh == 1:
                    external_edges = {}
                    for direction, tile_edges in raw_edges.items():
                        for edge_arr in tile_edges.values():
                            external_edges[direction] = edge_arr
                            break
                else:
                    external_edges = raw_edges
                edge_count = sum(len(v) for v in raw_edges.values())
                print("  Extracted {} boundary edges".format(edge_count))

        gen = ws._get_terrain_generator()
        if gen.has_model:
            print("  CNN model loaded - using learned terrain features")
        else:
            print("  No CNN model - falling back to Coons + Laplacian")

        # For single tile, use generate_tile_ml; for grid use generate_grid_ml
        gw, gh = spec.grid_size
        if gw == 1 and gh == 1:
            bx, by = spec.base_coords
            hm = ws.generate_tile_ml(bx, by, edge_arrays=external_edges)
            print("  Heightmap range: {:.1f} - {:.1f}".format(
                float(hm.min()), float(hm.max())))
        else:
            ws.generate_grid_ml(external_edges=external_edges)
            print("  Generated {}x{} tile grid".format(gw, gh))

        # Re-apply textures from zone_def since ML overwrites heightmaps
        from world_builder.terrain_sculptor import TerrainSculptor
        sculptor = TerrainSculptor(zone_def)
        tex_result = sculptor.generate_textures(ws.heightmaps)
        for tile_key, tile_tex in tex_result.get('tile_data', {}).items():
            tex_paths = tile_tex.get('texture_paths', [])
            chunk_layers = tile_tex.get('chunk_layers', {})
            # Pick top 4 most-used textures
            tex_freq = {}
            for cl in chunk_layers.values():
                for tid in cl.get('texture_ids', []):
                    if tid is not None and tid < len(tex_paths):
                        path = tex_paths[tid]
                        tex_freq[path] = tex_freq.get(path, 0) + 1
            sorted_tex = sorted(tex_freq.items(), key=lambda x: -x[1])
            final_paths = [t[0] for t in sorted_tex[:4]]
            if not final_paths:
                final_paths = ["Tileset\\Generic\\Black.blp"]
            ws.textures[tile_key] = {
                'texture_paths': final_paths,
                'splat_map': None,
            }

        # Re-generate doodads on new terrain
        raw_doodads = sculptor.generate_doodads(ws.heightmaps)
        ws.doodads = []
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

        # Re-generate area IDs
        ws.area_ids = sculptor.generate_area_ids()
        print("  Doodads regenerated: {}".format(len(ws.doodads)))
    else:
        print("\n[4/7] Skipping ML terrain (--no-ml)")

    # ------------------------------------------------------------------
    # Step 5: Resolve buildings via WMO catalog
    # ------------------------------------------------------------------
    print("\n[5/7] Resolving buildings...")
    catalog = WMOCatalog()
    default_style = spec.style.get('building_style', 'human_elwynn')
    resolved = catalog.resolve_all(spec.buildings, default_style)
    print("  Resolved {} / {} buildings".format(
        len(resolved), len(spec.buildings)))

    # ------------------------------------------------------------------
    # Step 6: Place WMOs
    # ------------------------------------------------------------------
    print("\n[6/7] Placing WMO buildings...")
    for i, bld in enumerate(resolved):
        pos = bld['position']
        if isinstance(pos, str):
            from world_builder.zone_spec import _normalise_position
            nx, ny = _normalise_position(pos)
        elif isinstance(pos, (list, tuple)):
            nx, ny = float(pos[0]), float(pos[1])
        else:
            continue

        wx, wy = ws.norm_to_world(nx, ny)
        rotation = bld.get('rotation', 0)

        wmo = ws.add_wmo(
            model=bld['wmo_path'],
            position=(wx, wy),
            rotation=(0, 0, rotation),
            footprint=bld['footprint'],
        )
        bld_name = bld.get('name', bld['type'])
        print("  + {} at world ({:.0f}, {:.0f}, {:.1f})".format(
            bld_name, wmo['position'][0], wmo['position'][1],
            wmo['position'][2]))

    # Flatten terrain under buildings
    if resolved:
        print("  Flattening terrain under {} buildings...".format(len(resolved)))
        ws.flatten_for_entities(blend_margin=4.0)

    # Resample Z for all entities after flattening changed the heightmap
    print("  Resampling entity Z positions on final terrain...")
    for d in ws.doodads:
        pos = d.get('position', (0, 0, 0))
        new_z = ws.get_height_at(pos[0], pos[1])
        d['position'] = (pos[0], pos[1], new_z)
    for w in ws.wmos:
        pos = w.get('position', (0, 0, 0))
        new_z = ws.get_height_at(pos[0], pos[1])
        w['position'] = (pos[0], pos[1], new_z)

    # ------------------------------------------------------------------
    # Step 7: Export and pack MPQ
    # ------------------------------------------------------------------
    print("\n[7/7] Exporting and packing into patch-4.MPQ...")
    wow_data_copy = wow_data if (copy and wow_data) else None
    mpq_path = ws.pack_mpq(output_dir, "patch-4.MPQ",
                           wow_data_dir=wow_data_copy,
                           big_alpha=False)
    print("  Output: {}".format(mpq_path))

    # Summary
    print("\n" + "=" * 60)
    print("GENERATION COMPLETE")
    print("=" * 60)
    print("  Zone:       {}".format(spec.name))
    print("  Archetype:  {}".format(spec.archetype))
    print("  Grid:       {}x{}".format(*spec.grid_size))
    print("  Subzones:   {}".format(len(zone_def.get('subzones', []))))
    print("  Doodads:    {}".format(len(ws.doodads)))
    print("  WMOs:       {}".format(len(ws.wmos)))
    print("  Output:     {}".format(mpq_path))

    if wow_data_copy:
        print("\n  Patch copied to WoW Data directory.")
        print("  Restart the WoW client to load the new zone.")
    else:
        print("\n  Copy patch-4.MPQ to your WoW Data directory to test.")

    return mpq_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a WoW zone from a JSON specification"
    )
    parser.add_argument(
        "spec",
        help="Path to zone specification JSON file",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output directory (default: output/<zone_name>)",
    )
    parser.add_argument(
        "--wow-data",
        default=DEFAULT_WOW_DATA,
        help="Path to WoW Data directory",
    )
    parser.add_argument(
        "--adt-source",
        default=None,
        help="Path to extracted ADT directory for edge stitching",
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Don't copy the MPQ to the WoW Data directory",
    )
    parser.add_argument(
        "--no-ml",
        action="store_true",
        help="Skip ML terrain, use only procedural generation",
    )
    parser.add_argument(
        "--map-name",
        default="Azeroth",
        help="Map name for ADT packing (default: Azeroth)",
    )

    args = parser.parse_args()

    if not os.path.isfile(args.spec):
        print("ERROR: Spec file not found: {}".format(args.spec))
        sys.exit(1)

    wow_data = args.wow_data
    if wow_data and not os.path.isdir(wow_data):
        print("WARNING: WoW Data directory not found: {}".format(wow_data))
        print("         MPQ will be generated but not copied.")
        wow_data = None

    generate_zone(
        spec_path=args.spec,
        output_dir=args.output,
        wow_data=wow_data,
        adt_source=args.adt_source,
        copy=not args.no_copy,
        use_ml=not args.no_ml,
        map_name=args.map_name,
    )


if __name__ == "__main__":
    main()
