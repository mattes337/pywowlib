#!/usr/bin/env python
"""
wmo_height.py — Query floor/ceiling heights inside WMO buildings.

Reads WMO geometry from the game client's MPQ archives and performs
vertical ray casting through collision triangles to find all floor
and ceiling surfaces at a given server (x, y) position.

For multi-floor buildings, returns heights for every level.
For outdoor points with no WMO, returns nothing (use terrain_height.py).

Coordinate pipeline:
  Server (x, y)
    → ADT world coords
    → inverse MODF transform → WMO local coords
    → check MOGI group bounding boxes
    → load matching group files → extract collision geometry
    → vertical ray cast → collect floor/ceiling heights
    → transform back to server Z

Usage:
  # Query heights inside Stormwind (map 0)
  python pywowlib/tools/wmo_height.py --map 0 -8465 332

  # Deadmines instance (global WMO map)
  python pywowlib/tools/wmo_height.py --map 36 -178 -459

  # JSON output
  python pywowlib/tools/wmo_height.py --map 0 --json -8465 332
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

MAP_HALF = 17066.66656
TILE_SIZE = 533.33333333

# Floor/ceiling classification threshold: dot product with local Y axis.
# > threshold → floor, < -threshold → ceiling
_NORMAL_THRESHOLD = 0.1


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

def _resolve_map_name(mpq, map_id):
    """Resolve map ID to internal directory name via Map.dbc."""
    dbc_data = mpq.read_file('DBFilesClient\\Map.dbc')
    if not dbc_data:
        return None
    _m, n_records, _nf, rec_size, _ss = struct.unpack_from('<4sIIII', dbc_data)
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
# Vector math
# ---------------------------------------------------------------------------

def _cross(a, b):
    return [a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0]]


def _dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _normalize(v):
    length = math.sqrt(_dot(v, v))
    if length < 1e-10:
        return [0, 0, 0]
    return [v[i] / length for i in range(3)]


# ---------------------------------------------------------------------------
# Coordinate transforms
# ---------------------------------------------------------------------------

def _euler_to_matrix(rot_deg):
    """MODF Euler angles (degrees) → 3x3 rotation matrix.

    Applied as Rz * Ry * Rx where (rx, ry, rz) = rot_deg.
    Matches the convention in wmo_doodads.py.
    """
    rx, ry, rz = [math.radians(d) for d in rot_deg]
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return [
        [cz*cy, cz*sy*sx - sz*cx, cz*sy*cx + sz*sx],
        [sz*cy, sz*sy*sx + cz*cx, sz*sy*cx - cz*sx],
        [-sy,   cy*sx,            cy*cx],
    ]


def _mat_apply(m, v):
    return [m[0][0]*v[0] + m[0][1]*v[1] + m[0][2]*v[2],
            m[1][0]*v[0] + m[1][1]*v[1] + m[1][2]*v[2],
            m[2][0]*v[0] + m[2][1]*v[1] + m[2][2]*v[2]]


def _mat_transpose(m):
    return [[m[0][0], m[1][0], m[2][0]],
            [m[0][1], m[1][1], m[2][1]],
            [m[0][2], m[1][2], m[2][2]]]


def server_to_wmo_local(server_x, server_y, server_z, wmo_pos, rot_matrix):
    """Transform a point from server coords to WMO local coords.

    Inverse of the forward transform:
      WMO local → swap X↔Z → rotate → add pos → ADT → server
    """
    # Server → ADT world
    adt = [MAP_HALF - server_y, server_z, MAP_HALF - server_x]
    # Subtract WMO position
    rel = [adt[i] - wmo_pos[i] for i in range(3)]
    # Inverse rotation (transpose for orthogonal matrix)
    inv = _mat_apply(_mat_transpose(rot_matrix), rel)
    # Unswap X↔Z
    return [inv[2], inv[1], inv[0]]


def wmo_local_to_server_z(local_pos, wmo_pos, rot_matrix):
    """Transform a WMO local point back to server coords, return server_z.

    Forward transform: swap X↔Z → rotate → add pos → ADT → server.
    """
    swapped = [local_pos[2], local_pos[1], local_pos[0]]
    rotated = _mat_apply(rot_matrix, swapped)
    adt_y = rotated[1] + wmo_pos[1]
    return adt_y  # server_z = adt_y


# ---------------------------------------------------------------------------
# Ray-triangle intersection (Möller–Trumbore)
# ---------------------------------------------------------------------------

def _ray_triangle(ray_origin, ray_dir, v0, v1, v2):
    """Möller–Trumbore ray-triangle intersection.

    Returns the ray parameter t (distance along ray) or None if no hit.
    """
    e1 = [v1[i] - v0[i] for i in range(3)]
    e2 = [v2[i] - v0[i] for i in range(3)]
    h = _cross(ray_dir, e2)
    a = _dot(e1, h)

    if -1e-8 < a < 1e-8:
        return None  # parallel to triangle

    f = 1.0 / a
    s = [ray_origin[i] - v0[i] for i in range(3)]
    u = f * _dot(s, h)
    if u < 0.0 or u > 1.0:
        return None

    q = _cross(s, e1)
    v = f * _dot(ray_dir, q)
    if v < 0.0 or u + v > 1.0:
        return None

    t = f * _dot(e2, q)
    return t if t > -1e6 else None  # allow negative t (ray goes both ways)


# ---------------------------------------------------------------------------
# WDT global WMO parsing
# ---------------------------------------------------------------------------

def _parse_wdt_modf(wdt_bytes):
    """Parse WDT for global WMO placement.  Returns dict or None."""
    pos = 0
    mwmo_name = None

    while pos < len(wdt_bytes) - 8:
        magic = wdt_bytes[pos:pos + 4][::-1]
        size = struct.unpack_from('<I', wdt_bytes, pos + 4)[0]

        if magic == b'MWMO' and size > 0:
            raw = wdt_bytes[pos + 8:pos + 8 + size]
            mwmo_name = raw.rstrip(b'\x00').decode('ascii', errors='replace')
        elif magic == b'MODF' and size >= 64:
            d = wdt_bytes[pos + 8:pos + 8 + 64]
            modf_pos = list(struct.unpack_from('<3f', d, 8))
            modf_rot = list(struct.unpack_from('<3f', d, 20))
            ext_min = list(struct.unpack_from('<3f', d, 32))
            ext_max = list(struct.unpack_from('<3f', d, 44))
            return {
                'name': mwmo_name or '<unknown>',
                'position': modf_pos,
                'rotation': modf_rot,
                'extents_min': ext_min,
                'extents_max': ext_max,
            }

        pos += 8 + size

    return None


# ---------------------------------------------------------------------------
# ADT MODF parsing (with rotation — more data than terrain_height.py)
# ---------------------------------------------------------------------------

def _parse_adt_modf(adt_bytes, server_x, server_y):
    """Parse MWMO + MODF from ADT, filter by 2D bounding box.

    Returns list of WMO dicts whose bounding box contains the query point.
    Each dict has: name, position, rotation, extents_min, extents_max.
    """
    wmo_names = []
    results = []
    pos = 0

    # Convert server coords to ADT world for bounding box check
    adt_qx = MAP_HALF - server_y
    adt_qz = MAP_HALF - server_x

    while pos < len(adt_bytes) - 8:
        magic = adt_bytes[pos:pos + 4][::-1]
        size = struct.unpack_from('<I', adt_bytes, pos + 4)[0]

        if magic == b'MWMO' and size > 0:
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

        elif magic == b'MODF' and size >= 64:
            n_entries = size // 64
            base = pos + 8
            for e in range(n_entries):
                ofs = base + e * 64
                name_id = struct.unpack_from('<I', adt_bytes, ofs)[0]
                modf_pos = list(struct.unpack_from('<3f', adt_bytes, ofs + 8))
                modf_rot = list(struct.unpack_from('<3f', adt_bytes, ofs + 20))
                ext_min = list(struct.unpack_from('<3f', adt_bytes, ofs + 32))
                ext_max = list(struct.unpack_from('<3f', adt_bytes, ofs + 44))

                # 2D bounding box check in ADT coords
                x_lo = min(ext_min[0], ext_max[0])
                x_hi = max(ext_min[0], ext_max[0])
                z_lo = min(ext_min[2], ext_max[2])
                z_hi = max(ext_min[2], ext_max[2])

                if x_lo <= adt_qx <= x_hi and z_lo <= adt_qz <= z_hi:
                    name = wmo_names[name_id] if name_id < len(wmo_names) else '<unknown>'
                    results.append({
                        'name': name,
                        'position': modf_pos,
                        'rotation': modf_rot,
                        'extents_min': ext_min,
                        'extents_max': ext_max,
                    })
            break  # MODF comes after MWMO, done with top-level chunks

        if magic == b'KNCM':
            break  # past top-level chunks

        pos += 8 + size

    return results


# ---------------------------------------------------------------------------
# Root WMO parsing (group info + names)
# ---------------------------------------------------------------------------

def _parse_root_wmo(root_bytes):
    """Parse root WMO file for group count, bounding boxes, and names.

    Returns dict with:
      n_groups: int
      groups: list of {bbox_min, bbox_max, flags}
      group_names: list of str
    """
    n_groups = 0
    groups = []
    group_names_raw = b''
    pos = 0

    while pos < len(root_bytes) - 8:
        magic = root_bytes[pos:pos + 4][::-1]
        size = struct.unpack_from('<I', root_bytes, pos + 4)[0]

        if magic == b'MOHD' and size >= 16:
            n_groups = struct.unpack_from('<I', root_bytes, pos + 8 + 4)[0]

        elif magic == b'MOGI':
            n_entries = size // 32
            for i in range(n_entries):
                ofs = pos + 8 + i * 32
                flags = struct.unpack_from('<I', root_bytes, ofs)[0]
                bb_min = list(struct.unpack_from('<3f', root_bytes, ofs + 4))
                bb_max = list(struct.unpack_from('<3f', root_bytes, ofs + 16))
                name_ofs = struct.unpack_from('<i', root_bytes, ofs + 28)[0]
                groups.append({
                    'bbox_min': bb_min,
                    'bbox_max': bb_max,
                    'flags': flags,
                    'name_offset': name_ofs,
                })

        elif magic == b'MOGN':
            group_names_raw = root_bytes[pos + 8:pos + 8 + size]

        pos += 8 + size

    # Resolve group names
    group_names = []
    for g in groups:
        name_ofs = g['name_offset']
        if 0 <= name_ofs < len(group_names_raw):
            end = group_names_raw.index(b'\x00', name_ofs)
            group_names.append(
                group_names_raw[name_ofs:end].decode('ascii', errors='replace'))
        else:
            group_names.append('')

    return {
        'n_groups': n_groups,
        'groups': groups,
        'group_names': group_names,
    }


# ---------------------------------------------------------------------------
# WMO group geometry parsing
# ---------------------------------------------------------------------------

def _parse_group_geometry(group_bytes):
    """Parse a WMO group file and extract collision geometry.

    Returns (vertices, triangles) where:
      vertices: list of (x, y, z) tuples
      triangles: list of (i0, i1, i2) index tuples (only collision-relevant)

    Returns (None, None) if parsing fails.
    """
    vertices = None
    indices = None
    materials = None

    # Find MOGP chunk (wraps all sub-chunks)
    pos = 0
    while pos < len(group_bytes) - 8:
        magic = group_bytes[pos:pos + 4][::-1]
        size = struct.unpack_from('<I', group_bytes, pos + 4)[0]

        if magic == b'MOGP':
            # Sub-chunks are inside MOGP, after a 68-byte group header
            inner = pos + 8 + 68
            end = pos + 8 + size

            while inner < end - 8:
                sub_magic = group_bytes[inner:inner + 4][::-1]
                sub_size = struct.unpack_from('<I', group_bytes, inner + 4)[0]

                if sub_magic == b'MOVT':
                    n_verts = sub_size // 12
                    vertices = []
                    for i in range(n_verts):
                        v = struct.unpack_from('<3f', group_bytes, inner + 8 + i * 12)
                        vertices.append(v)

                elif sub_magic == b'MOVI':
                    n_idx = sub_size // 2
                    indices = list(struct.unpack_from(
                        '<{}H'.format(n_idx), group_bytes, inner + 8))

                elif sub_magic == b'MOPY':
                    n_tri = sub_size // 2
                    materials = []
                    for i in range(n_tri):
                        flags = group_bytes[inner + 8 + i * 2]
                        mat_id = group_bytes[inner + 8 + i * 2 + 1]
                        materials.append((flags, mat_id))

                inner += 8 + sub_size
            break

        pos += 8 + size

    if vertices is None or indices is None:
        return None, None

    # Build triangle list, filtering by collision relevance
    n_tris = len(indices) // 3
    triangles = []

    for i in range(n_tris):
        i0, i1, i2 = indices[i*3], indices[i*3+1], indices[i*3+2]

        # Skip degenerate triangles
        if i0 == i1 or i1 == i2 or i0 == i2:
            continue
        if max(i0, i1, i2) >= len(vertices):
            continue

        # Filter: skip triangles with material 0xFF that lack collision flag
        if materials and i < len(materials):
            flags, mat_id = materials[i]
            if mat_id == 0xFF and not (flags & 0x08):
                continue

        triangles.append((i0, i1, i2))

    return vertices, triangles


# ---------------------------------------------------------------------------
# Main ray-cast query
# ---------------------------------------------------------------------------

def cast_wmo_rays(mpq, wmo_path, wmo_pos, wmo_rot, server_x, server_y):
    """Cast a vertical ray through a WMO at the given server position.

    Returns list of hit dicts:
      {z, type, group_idx, group_name, normal_y}
    where type is 'floor' or 'ceiling'.
    """
    rot_matrix = _euler_to_matrix(wmo_rot)
    rot_inv = _mat_transpose(rot_matrix)

    # Transform query point to WMO local (at reference height 0)
    local_ref = server_to_wmo_local(server_x, server_y, 0.0, wmo_pos, rot_matrix)

    # Transform vertical direction to WMO local
    # Server vertical = ADT (0, 1, 0); apply inverse rotation then unswap
    adt_up = [0.0, 1.0, 0.0]
    rot_up = _mat_apply(rot_inv, adt_up)
    local_dir = _normalize([rot_up[2], rot_up[1], rot_up[0]])

    # Ray origin: start far below in the local vertical direction
    ray_origin = [local_ref[i] - 5000.0 * local_dir[i] for i in range(3)]

    # Load root WMO
    root_data = mpq.read_file(wmo_path)
    if root_data is None:
        return []

    root_info = _parse_root_wmo(root_data)

    # Determine which groups to check (2D bounding box in WMO local)
    candidate_groups = []
    for gi, g in enumerate(root_info['groups']):
        bb_min = g['bbox_min']
        bb_max = g['bbox_max']

        # Check all three axes of the query point against group bbox.
        # For the ray direction axis, we accept any value (the ray spans it).
        # For the two perpendicular axes, the point must be inside.
        # With general rotations, all axes could contribute. Use a
        # conservative check: ensure the ray line intersects the AABB.
        # For most cases (yaw-only), local_dir ≈ (0,1,0), so check X and Z.
        in_x = bb_min[0] <= local_ref[0] <= bb_max[0]
        in_z = bb_min[2] <= local_ref[2] <= bb_max[2]

        if in_x and in_z:
            candidate_groups.append(gi)

    # Process each candidate group
    wmo_base = wmo_path.rsplit('.', 1)[0]  # remove .wmo extension
    hits = []

    for gi in candidate_groups:
        group_path = '{}_{:03d}.wmo'.format(wmo_base, gi)
        group_data = mpq.read_file(group_path)
        if group_data is None:
            continue

        vertices, triangles = _parse_group_geometry(group_data)
        if vertices is None:
            continue

        group_name = ''
        if gi < len(root_info['group_names']):
            group_name = root_info['group_names'][gi]

        # Ray-cast against all collision triangles
        for i0, i1, i2 in triangles:
            v0, v1, v2 = vertices[i0], vertices[i1], vertices[i2]

            t = _ray_triangle(ray_origin, local_dir, list(v0), list(v1), list(v2))
            if t is None:
                continue

            # Hit point in WMO local
            hit_local = [ray_origin[i] + t * local_dir[i] for i in range(3)]

            # Face normal in WMO local
            e1 = [v1[i] - v0[i] for i in range(3)]
            e2 = [v2[i] - v0[i] for i in range(3)]
            normal = _normalize(_cross(e1, e2))

            # The "up" direction in WMO local = local_dir
            normal_dot_up = _dot(normal, local_dir)

            if abs(normal_dot_up) < _NORMAL_THRESHOLD:
                continue  # wall — skip

            surface_type = 'floor' if normal_dot_up > 0 else 'ceiling'

            # Convert hit to server Z
            server_z = wmo_local_to_server_z(hit_local, wmo_pos, rot_matrix)

            hits.append({
                'z': server_z,
                'type': surface_type,
                'group_idx': gi,
                'group_name': group_name,
                'normal_y': normal_dot_up,
            })

    # Deduplicate close hits (multiple triangles on the same surface)
    hits.sort(key=lambda h: h['z'])
    deduped = []
    for h in hits:
        if deduped and abs(h['z'] - deduped[-1]['z']) < 0.5:
            # Keep the one with the stronger normal
            if abs(h['normal_y']) > abs(deduped[-1]['normal_y']):
                deduped[-1] = h
        else:
            deduped.append(h)

    return deduped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_wmo_heights(mpq, map_name, server_x, server_y):
    """Query all floor/ceiling heights at a server position.

    Checks both WDT global WMO and ADT-placed WMOs.  Searches the
    query tile plus its 8 neighbors so large WMOs that span tile
    boundaries are always found.

    Returns dict:
      wmos: list of {name, hits: [{z, type, group_idx, group_name}]}
      terrain_z: float or None (if terrain_height available)
      best_floor_z: float or None (floor closest to terrain)
    """
    result = {
        'x': server_x,
        'y': server_y,
        'wmos': [],
        'terrain_z': None,
        'best_floor_z': None,
        'error': None,
    }

    # Try terrain height
    try:
        from pywowlib.tools.terrain_height import query_height
        tr = query_height(mpq, map_name, server_x, server_y)
        result['terrain_z'] = tr.get('z')
    except Exception:
        pass

    # Check WDT for global WMO
    wdt_path = 'World\\Maps\\{}\\{}.wdt'.format(map_name, map_name)
    wdt_data = mpq.read_file(wdt_path)
    if wdt_data:
        global_modf = _parse_wdt_modf(wdt_data)
        if global_modf and global_modf['name']:
            hits = cast_wmo_rays(
                mpq, global_modf['name'],
                global_modf['position'], global_modf['rotation'],
                server_x, server_y)
            if hits:
                result['wmos'].append({
                    'name': os.path.basename(global_modf['name']),
                    'path': global_modf['name'],
                    'hits': hits,
                })

    # Check ADT MODF placements (query tile + 8 neighbors)
    center_ty = int(math.floor((MAP_HALF - server_x) / TILE_SIZE))
    center_tx = int(math.floor((MAP_HALF - server_y) / TILE_SIZE))
    seen_paths = {w['path'] for w in result['wmos']}

    for dy in range(-1, 2):
        for dx in range(-1, 2):
            tx = center_tx + dx
            ty = center_ty + dy
            if not (0 <= tx < 64 and 0 <= ty < 64):
                continue

            adt_path = 'World\\Maps\\{}\\{}_{:d}_{:d}.adt'.format(
                map_name, map_name, tx, ty)
            adt_data = mpq.read_file(adt_path)
            if not adt_data:
                continue

            modf_list = _parse_adt_modf(adt_data, server_x, server_y)
            for modf in modf_list:
                if modf['name'] in seen_paths:
                    continue

                hits = cast_wmo_rays(
                    mpq, modf['name'],
                    modf['position'], modf['rotation'],
                    server_x, server_y)
                if hits:
                    result['wmos'].append({
                        'name': os.path.basename(modf['name']),
                        'path': modf['name'],
                        'hits': hits,
                    })
                    seen_paths.add(modf['name'])

    # Find best floor: the floor closest to terrain height
    ref_z = result['terrain_z']
    all_floors = []
    for wmo in result['wmos']:
        for h in wmo['hits']:
            if h['type'] == 'floor':
                all_floors.append(h['z'])

    if all_floors:
        if ref_z is not None:
            result['best_floor_z'] = min(all_floors, key=lambda z: abs(z - ref_z))
        else:
            result['best_floor_z'] = min(all_floors)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_points(remaining):
    # Filter out '--' separator (used before negative coords)
    remaining = [t for t in remaining if t != '--']
    points = []
    i = 0
    while i < len(remaining):
        token = remaining[i]
        if ',' in token:
            parts = token.split(',')
            points.append((float(parts[0]), float(parts[1])))
            i += 1
        else:
            if i + 1 >= len(remaining):
                print("ERROR: Odd number of coordinates.", file=sys.stderr)
                sys.exit(1)
            points.append((float(token), float(remaining[i + 1])))
            i += 2
    return points


def main():
    parser = argparse.ArgumentParser(
        description='Query floor/ceiling heights inside WMO buildings',
        usage='%(prog)s [options] x y')

    parser.add_argument('--map', type=int, default=None,
                        help='Map ID (e.g. 0=Eastern Kingdoms, 36=Deadmines)')
    parser.add_argument('--map-name', default=None,
                        help='Map directory name (e.g. Azeroth)')
    parser.add_argument('--json', action='store_true',
                        help='JSON output')
    parser.add_argument('--wow-root',
                        help='WoW client root')

    args, remaining = parser.parse_known_args()

    if not remaining:
        parser.print_help()
        sys.exit(0)

    if args.map is None and args.map_name is None:
        print("ERROR: Specify --map <id> or --map-name <name>", file=sys.stderr)
        sys.exit(1)

    points = _parse_points(remaining)
    wow_root = args.wow_root or _get_wow_root()

    with MPQChain(wow_root) as mpq:
        map_name = args.map_name
        if map_name is None:
            map_name = _resolve_map_name(mpq, args.map)
            if map_name is None:
                print("ERROR: Could not resolve map ID {}".format(args.map),
                      file=sys.stderr)
                sys.exit(1)

        all_results = []
        for sx, sy in points:
            r = query_wmo_heights(mpq, map_name, sx, sy)
            all_results.append(r)

        if args.json:
            print(json.dumps(all_results, indent=2, default=str))
        else:
            for r in all_results:
                print("({:.1f}, {:.1f})".format(r['x'], r['y']))

                if r['terrain_z'] is not None:
                    print("  Terrain: z = {:.4f}".format(r['terrain_z']))

                if r['best_floor_z'] is not None:
                    print("  >> Best floor: z = {:.4f}".format(
                        r['best_floor_z']))

                if not r['wmos']:
                    print("  No WMO geometry at this point")
                    continue

                for wmo in r['wmos']:
                    print("  WMO: {}".format(wmo['name']))
                    all_hits = sorted(wmo['hits'], key=lambda h: h['z'])
                    for h in all_hits:
                        marker = 'FLOOR' if h['type'] == 'floor' else 'ceil'
                        best = ' *' if (h['type'] == 'floor'
                                        and r['best_floor_z'] is not None
                                        and abs(h['z'] - r['best_floor_z']) < 0.01
                                        ) else ''
                        group = h['group_name'] or 'group {}'.format(h['group_idx'])
                        print("    {:5s}  z = {:10.4f}  ({}){}".format(
                            marker, h['z'], group, best))


if __name__ == '__main__':
    main()
