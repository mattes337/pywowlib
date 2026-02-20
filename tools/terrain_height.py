#!/usr/bin/env python
"""
terrain_height.py — Query terrain height at server coordinates.

Reads ADT tiles from the game client's MPQ archives and returns the
exact terrain height at any server (x, y) position.  Uses triangle
interpolation on the ADT mesh for sub-yard accuracy.

Can also detect WMO buildings/objects at the given position.

Coordinate systems:
  Server (database):  position_x, position_y, position_z
  ADT world (MODF):   adt_x, adt_y (height), adt_z
  Conversion:
    adt_x = MAP_HALF - server_y
    adt_y = server_z
    adt_z = MAP_HALF - server_x

  MCNK header stores (pos_x, pos_y, pos_z) where:
    pos_x = MAP_HALF - tile_y * TILE_SIZE - chunk_row * CHUNK_SIZE  (≈ server_x)
    pos_y = MAP_HALF - tile_x * TILE_SIZE - chunk_col * CHUNK_SIZE  (≈ server_y)
    pos_z = base height

Usage:
  # Basic height query (Eastern Kingdoms, map 0)
  python pywowlib/tools/terrain_height.py -9462 -67 --map 0

  # With WMO detection
  python pywowlib/tools/terrain_height.py -9462 -67 --map 0 --wmo

  # Specify map by directory name instead of ID
  python pywowlib/tools/terrain_height.py -9462 -67 --map-name Azeroth

  # Multiple points (comma-separated x,y pairs)
  python pywowlib/tools/terrain_height.py -9462,-67 -8465,332 --map 0

  # JSON output for scripting
  python pywowlib/tools/terrain_height.py -9462 -67 --map 0 --json
"""

import argparse
import json
import math
import os
import struct
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_TOOLS_DIR))
sys.path.insert(0, _PROJECT_ROOT)

from pywowlib.world_builder.intermediate_format import MPQChain


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAP_HALF = 17066.66656            # 32 * 533.333... (half-world size)
TILE_SIZE = 533.33333333          # Yards per ADT tile
CHUNK_SIZE = TILE_SIZE / 16.0     # ~33.33 yards per sub-chunk
CELL_SIZE = CHUNK_SIZE / 8.0      # ~4.167 yards per cell

_MCNK_MAGIC = b'KNCM'
_MCVT_MAGIC = b'TVCM'
_MODF_MAGIC = b'FDOM'
_MWMO_MAGIC = b'OMWM'


# ---------------------------------------------------------------------------
# WoW client root
# ---------------------------------------------------------------------------

def _get_wow_root():
    root = os.environ.get('WOW_CLIENT_DATA')
    if root:
        return root
    env_path = os.path.join(_PROJECT_ROOT, 'docker', '.env')
    if os.path.isfile(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('WOW_CLIENT_DATA='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    return r'G:\WoW AzerothCore'


# ---------------------------------------------------------------------------
# Map name resolution
# ---------------------------------------------------------------------------

def resolve_map_name(mpq, map_id):
    """Resolve map ID to internal directory name via Map.dbc.

    Returns the map's InternalName string (e.g. 'Azeroth', 'Kalimdor',
    'DeadminesInstance') or None if not found.
    """
    dbc_data = mpq.read_file('DBFilesClient\\Map.dbc')
    if not dbc_data:
        return None

    _magic, n_records, _n_fields, rec_size, _str_size = struct.unpack_from(
        '<4sIIII', dbc_data, 0)
    str_start = 20 + n_records * rec_size

    pos = 20
    for _ in range(n_records):
        rec_id = struct.unpack_from('<I', dbc_data, pos)[0]
        if rec_id == map_id:
            name_ofs = struct.unpack_from('<I', dbc_data, pos + 4)[0]
            end = dbc_data.index(b'\x00', str_start + name_ofs)
            return dbc_data[str_start + name_ofs:end].decode('ascii')
        pos += rec_size

    return None


# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------

def server_to_tile(server_x, server_y):
    """Convert server coordinates to ADT tile indices.

    Returns (tile_x, tile_y) where tile indices are 0-63,
    or None if coordinates are outside the world bounds.

    The mapping:
      tile_y depends on server_x (north-south axis)
      tile_x depends on server_y (east-west axis)
    """
    tile_y = int(math.floor((MAP_HALF - server_x) / TILE_SIZE))
    tile_x = int(math.floor((MAP_HALF - server_y) / TILE_SIZE))

    if not (0 <= tile_x < 64 and 0 <= tile_y < 64):
        return None
    return tile_x, tile_y


def server_to_local(server_x, server_y, tile_x, tile_y):
    """Convert server coords to chunk indices and local position within chunk.

    Returns (chunk_row, chunk_col, local_x, local_y) where:
      chunk_row/col: 0-15 indices within the tile
      local_x/y: 0 to CHUNK_SIZE position within the chunk (yards)
    """
    # Position within tile (0 to TILE_SIZE)
    in_tile_x = MAP_HALF - server_x - tile_y * TILE_SIZE
    in_tile_y = MAP_HALF - server_y - tile_x * TILE_SIZE

    chunk_row = min(max(int(math.floor(in_tile_x / CHUNK_SIZE)), 0), 15)
    chunk_col = min(max(int(math.floor(in_tile_y / CHUNK_SIZE)), 0), 15)

    local_x = in_tile_x - chunk_row * CHUNK_SIZE
    local_y = in_tile_y - chunk_col * CHUNK_SIZE

    return chunk_row, chunk_col, local_x, local_y


# ---------------------------------------------------------------------------
# ADT height parsing
# ---------------------------------------------------------------------------

def parse_chunk_heights(adt_bytes, target_row, target_col):
    """Parse a specific MCNK chunk from raw ADT bytes.

    Iterates through MCNK chunks sequentially until reaching the target.

    Args:
        adt_bytes: Raw ADT file bytes.
        target_row: Chunk row (0-15).
        target_col: Chunk column (0-15).

    Returns:
        (base_z, heights_145) where base_z is the chunk's base height
        and heights_145 is a list of 145 relative height offsets,
        or (None, None) if not found.
    """
    target_idx = target_row * 16 + target_col
    chunk_idx = 0
    pos = 0
    data_len = len(adt_bytes)

    while pos < data_len - 8:
        if adt_bytes[pos:pos + 4] == _MCNK_MAGIC:
            mcnk_size = struct.unpack_from('<I', adt_bytes, pos + 4)[0]
            mcnk_start = pos + 8

            if chunk_idx == target_idx:
                # MCNK header: position is at offset 0x68 (3 floats: x, y, z)
                # pos_z (base height) is at 0x68 + 8 = 0x70
                base_z = struct.unpack_from('<f', adt_bytes, mcnk_start + 0x70)[0]

                # Find MCVT sub-chunk within this MCNK
                mcnk_end = mcnk_start + mcnk_size
                inner = mcnk_start + 128  # skip 128-byte MCNK header

                while inner < mcnk_end - 8:
                    if adt_bytes[inner:inner + 4] == _MCVT_MAGIC:
                        mcvt_size = struct.unpack_from('<I', adt_bytes, inner + 4)[0]
                        if mcvt_size >= 145 * 4:
                            heights = list(struct.unpack_from(
                                '<145f', adt_bytes, inner + 8))
                            return base_z, heights
                        break
                    inner += 1

                return base_z, None

            chunk_idx += 1
            pos = mcnk_start + mcnk_size
        else:
            pos += 1

    return None, None


# ---------------------------------------------------------------------------
# Triangle interpolation
# ---------------------------------------------------------------------------

def _bary_interp(px, py, x1, y1, h1, x2, y2, h2, x3, y3, h3):
    """Barycentric interpolation of height at (px, py) within a triangle."""
    denom = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(denom) < 1e-10:
        return (h1 + h2 + h3) / 3.0

    w1 = ((y2 - y3) * (px - x3) + (x3 - x2) * (py - y3)) / denom
    w2 = ((y3 - y1) * (px - x3) + (x1 - x3) * (py - y3)) / denom
    w3 = 1.0 - w1 - w2
    return w1 * h1 + w2 * h2 + w3 * h3


def interpolate_height(heights_145, base_z, local_x, local_y):
    """Interpolate terrain height using the WoW triangle mesh.

    Each MCNK chunk has 8x8 cells.  Each cell has 4 outer corner vertices
    and 1 inner center vertex, forming 4 triangles (fan from center).
    This function determines which triangle contains the query point and
    performs barycentric interpolation for exact height.

    The 145-value interleaved layout:
      Outer row r, col c: index = r * 17 + c       (r: 0-8, c: 0-8)
      Inner row r, col c: index = r * 17 + 9 + c   (r: 0-7, c: 0-7)

    Args:
        heights_145: 145 relative height offsets from MCVT.
        base_z: Chunk base height (MCNK position.z).
        local_x: Position within chunk, row direction (0 to CHUNK_SIZE).
        local_y: Position within chunk, col direction (0 to CHUNK_SIZE).

    Returns:
        Absolute terrain height (float).
    """
    # Normalize to [0, 8] (8 cells per chunk axis)
    nx = max(0.0, min(8.0, local_x / CHUNK_SIZE * 8.0))
    ny = max(0.0, min(8.0, local_y / CHUNK_SIZE * 8.0))

    cell_row = min(int(math.floor(nx)), 7)
    cell_col = min(int(math.floor(ny)), 7)

    # Fractional position within cell [0, 1]
    fx = nx - cell_row
    fy = ny - cell_col

    # Vertex heights (absolute)
    h_tl = heights_145[cell_row * 17 + cell_col] + base_z
    h_tr = heights_145[cell_row * 17 + cell_col + 1] + base_z
    h_bl = heights_145[(cell_row + 1) * 17 + cell_col] + base_z
    h_br = heights_145[(cell_row + 1) * 17 + cell_col + 1] + base_z
    h_c = heights_145[cell_row * 17 + 9 + cell_col] + base_z

    # Determine which of the 4 triangles contains (fx, fy).
    # The diagonals fy=fx (TL→BR) and fy=1-fx (TR→BL) divide the cell
    # into 4 triangles meeting at center (0.5, 0.5).
    below_d1 = fy < fx        # below TL→BR diagonal
    above_d2 = fy < 1.0 - fx  # above TR→BL diagonal

    if below_d1 and above_d2:
        # TOP triangle: TL(0,0) TR(1,0) C(0.5,0.5)
        return _bary_interp(fx, fy, 0, 0, h_tl, 1, 0, h_tr, 0.5, 0.5, h_c)
    elif below_d1:
        # RIGHT triangle: TR(1,0) BR(1,1) C(0.5,0.5)
        return _bary_interp(fx, fy, 1, 0, h_tr, 1, 1, h_br, 0.5, 0.5, h_c)
    elif above_d2:
        # LEFT triangle: BL(0,1) TL(0,0) C(0.5,0.5)
        return _bary_interp(fx, fy, 0, 1, h_bl, 0, 0, h_tl, 0.5, 0.5, h_c)
    else:
        # BOTTOM triangle: BR(1,1) BL(0,1) C(0.5,0.5)
        return _bary_interp(fx, fy, 1, 1, h_br, 0, 1, h_bl, 0.5, 0.5, h_c)


# ---------------------------------------------------------------------------
# WMO detection
# ---------------------------------------------------------------------------

def parse_wmo_placements(adt_bytes):
    """Parse MWMO + MODF from ADT bytes for WMO bounding-box checks.

    Returns a list of dicts with keys:
      name, position (adt coords), extents_min, extents_max
    """
    # Find MWMO string table
    wmo_names = []
    pos = 0
    data_len = len(adt_bytes)

    while pos < data_len - 8:
        magic = adt_bytes[pos:pos + 4]
        size = struct.unpack_from('<I', adt_bytes, pos + 4)[0]

        if magic == _MWMO_MAGIC and size > 0:
            raw = adt_bytes[pos + 8:pos + 8 + size]
            i = 0
            while i < len(raw):
                if raw[i] == 0:
                    i += 1
                    continue
                start = i
                while i < len(raw) and raw[i] != 0:
                    i += 1
                wmo_names.append(raw[start:i].decode('ascii', errors='replace'))
                i += 1

        elif magic == _MODF_MAGIC and size >= 64:
            entries = []
            n_entries = size // 64
            base = pos + 8
            for e in range(n_entries):
                ofs = base + e * 64
                name_id = struct.unpack_from('<I', adt_bytes, ofs)[0]
                modf_pos = struct.unpack_from('<3f', adt_bytes, ofs + 8)
                ext_min = struct.unpack_from('<3f', adt_bytes, ofs + 32)
                ext_max = struct.unpack_from('<3f', adt_bytes, ofs + 44)
                name = wmo_names[name_id] if name_id < len(wmo_names) else '<unknown>'
                entries.append({
                    'name': name,
                    'position': modf_pos,
                    'extents_min': ext_min,
                    'extents_max': ext_max,
                })
            return entries

        if magic == _MCNK_MAGIC:
            break  # past top-level chunks

        pos += 8 + size

    return []


def check_wmo_at_point(wmo_placements, server_x, server_y, terrain_z=None):
    """Check if any WMO bounding box contains the given server position.

    Converts server coords to ADT world coords for comparison against
    MODF bounding boxes.

    Args:
        wmo_placements: List from parse_wmo_placements().
        server_x, server_y: Server coordinates.
        terrain_z: Optional terrain height for vertical check.

    Returns:
        List of WMO dicts that contain the point (may be empty).
    """
    # Server → ADT world conversion
    adt_x = MAP_HALF - server_y
    adt_z = MAP_HALF - server_x

    hits = []
    for wmo in wmo_placements:
        emin = wmo['extents_min']
        emax = wmo['extents_max']

        # 2D check (X and Z in ADT coords)
        # ADT MODF extents: [0]=X, [1]=Y(height), [2]=Z
        x_min, x_max = min(emin[0], emax[0]), max(emin[0], emax[0])
        z_min, z_max = min(emin[2], emax[2]), max(emin[2], emax[2])

        if x_min <= adt_x <= x_max and z_min <= adt_z <= z_max:
            info = {
                'name': os.path.basename(wmo['name']),
                'path': wmo['name'],
                'x_range': (x_min, x_max),
                'z_range': (z_min, z_max),
                'y_range': (min(emin[1], emax[1]), max(emin[1], emax[1])),
            }
            # Vertical check if terrain height known
            if terrain_z is not None:
                y_min = min(emin[1], emax[1])
                y_max = max(emin[1], emax[1])
                info['height_inside'] = y_min <= terrain_z <= y_max
            hits.append(info)

    return hits


# ---------------------------------------------------------------------------
# Main query function (importable)
# ---------------------------------------------------------------------------

def query_height(mpq, map_name, server_x, server_y, check_wmo=False):
    """Query terrain height at a server (x, y) position.

    This is the main entry point, usable from other scripts:
        from pywowlib.tools.terrain_height import query_height, MPQChain
        with MPQChain(wow_root) as mpq:
            result = query_height(mpq, 'Azeroth', -9462, -67)
            print(result['z'])

    Args:
        mpq: An open MPQChain instance.
        map_name: Map internal directory name (e.g. 'Azeroth').
        server_x: Server X coordinate (position_x).
        server_y: Server Y coordinate (position_y).
        check_wmo: If True, also check for WMO presence.

    Returns:
        dict with keys:
          z: float terrain height (or None if ADT not found)
          tile: (tile_x, tile_y) tuple
          chunk: (chunk_row, chunk_col) tuple
          error: error message string (or None)
          wmo: list of WMO hits (only if check_wmo=True)
    """
    result = {
        'x': server_x,
        'y': server_y,
        'z': None,
        'tile': None,
        'chunk': None,
        'error': None,
        'wmo': [],
    }

    # Convert to tile
    tile = server_to_tile(server_x, server_y)
    if tile is None:
        result['error'] = 'Coordinates out of world bounds'
        return result

    tile_x, tile_y = tile
    result['tile'] = (tile_x, tile_y)

    # Load ADT
    adt_path = 'World\\Maps\\{}\\{}_{:d}_{:d}.adt'.format(
        map_name, map_name, tile_x, tile_y)
    adt_bytes = mpq.read_file(adt_path)
    if adt_bytes is None:
        result['error'] = 'ADT not found: {}'.format(adt_path)
        return result

    # Find chunk and local position
    chunk_row, chunk_col, local_x, local_y = server_to_local(
        server_x, server_y, tile_x, tile_y)
    result['chunk'] = (chunk_row, chunk_col)

    # Parse heights
    base_z, heights = parse_chunk_heights(adt_bytes, chunk_row, chunk_col)
    if heights is None:
        result['error'] = 'Could not parse height data from chunk ({}, {})'.format(
            chunk_row, chunk_col)
        return result

    # Interpolate
    result['z'] = interpolate_height(heights, base_z, local_x, local_y)

    # WMO check
    if check_wmo:
        placements = parse_wmo_placements(adt_bytes)
        result['wmo'] = check_wmo_at_point(
            placements, server_x, server_y, result['z'])

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_points(args):
    """Parse coordinate arguments into (x, y) pairs.

    Supports:
      terrain_height.py -9462 -67 --map 0           (two positional args)
      terrain_height.py -9462,-67 -8465,332 --map 0 (comma-separated pairs)
    """
    points = []
    raw = args.coords

    if not raw:
        return points

    i = 0
    while i < len(raw):
        token = raw[i]
        if ',' in token:
            parts = token.split(',')
            points.append((float(parts[0]), float(parts[1])))
            i += 1
        else:
            if i + 1 >= len(raw):
                print("ERROR: Odd number of coordinates. "
                      "Use 'x y' pairs or 'x,y' format.", file=sys.stderr)
                sys.exit(1)
            points.append((float(token), float(raw[i + 1])))
            i += 2

    return points


def main():
    parser = argparse.ArgumentParser(
        description='Query terrain height at server coordinates from MPQ files',
        usage='%(prog)s [options] x y [x y ...]\n'
              '       %(prog)s [options] x,y [x,y ...]')

    parser.add_argument('--map', type=int, default=None,
                        help='Map ID (e.g. 0=Eastern Kingdoms, 1=Kalimdor)')
    parser.add_argument('--map-name', default=None,
                        help='Map directory name (e.g. Azeroth, Kalimdor)')
    parser.add_argument('--wmo', action='store_true',
                        help='Also check for WMO objects at each point')
    parser.add_argument('--json', action='store_true',
                        help='Output results as JSON')
    parser.add_argument('--wow-root',
                        help='WoW client root (default: from docker/.env)')

    # Parse known args first, treat remainder as coordinates.
    # This avoids argparse rejecting negative numbers like -9462.
    args, remaining = parser.parse_known_args()
    args.coords = remaining

    if not args.coords:
        parser.print_help()
        sys.exit(0)

    if args.map is None and args.map_name is None:
        print("ERROR: Specify --map <id> or --map-name <name>", file=sys.stderr)
        sys.exit(1)

    points = _parse_points(args)
    if not points:
        print("ERROR: No valid coordinates provided", file=sys.stderr)
        sys.exit(1)

    wow_root = args.wow_root or _get_wow_root()

    with MPQChain(wow_root) as mpq:
        # Resolve map name
        map_name = args.map_name
        if map_name is None:
            map_name = resolve_map_name(mpq, args.map)
            if map_name is None:
                print("ERROR: Could not resolve map ID {} to directory name".format(
                    args.map), file=sys.stderr)
                sys.exit(1)

        results = []
        for sx, sy in points:
            result = query_height(mpq, map_name, sx, sy, check_wmo=args.wmo)
            results.append(result)

        # Output
        if args.json:
            print(json.dumps(results, indent=2, default=str))
        else:
            for r in results:
                if r['error']:
                    print("({:.1f}, {:.1f})  ERROR: {}".format(
                        r['x'], r['y'], r['error']))
                    continue

                print("({:.1f}, {:.1f})  z = {:.4f}  tile=({},{})  chunk=({},{})".format(
                    r['x'], r['y'], r['z'],
                    r['tile'][0], r['tile'][1],
                    r['chunk'][0], r['chunk'][1]))

                if r['wmo']:
                    for wmo in r['wmo']:
                        inside = ""
                        if 'height_inside' in wmo:
                            inside = " (height {})".format(
                                "INSIDE" if wmo['height_inside'] else "outside")
                        print("  WMO: {}{}".format(wmo['name'], inside))
                        print("       height range: {:.1f} - {:.1f}".format(
                            wmo['y_range'][0], wmo['y_range'][1]))
                elif args.wmo:
                    print("  WMO: none")


if __name__ == '__main__':
    main()
