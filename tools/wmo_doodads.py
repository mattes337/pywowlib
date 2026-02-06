#!/usr/bin/env python
"""
wmo_doodads.py — Extract doodad positions from WMO files in MPQ archives.

Lists all doodad models placed inside a WMO with their positions,
rotations, and scales.  Supports ADT-based maps where the WMO is placed
via MODF in ADT files (not just global WMO maps via WDT).

Coordinate systems:
  - WMO local:  doodad positions as stored in the WMO file (X/Z swapped vs ADT)
  - ADT world:  after applying MODF placement (position + rotation)
  - Server:     game coordinates (position_x/y/z in creature/gameobject tables)

  ADT->Server:  server_x = 17066.667 - adt_z
                server_y = 17066.667 - adt_x
                server_z = adt_y

  Note: WMO doodad local coords use a different axis convention — X and Z
  are swapped relative to the ADT system.  The tool handles this
  automatically when --placement or --wdt is used.

Usage:
  # Scan a map for WMO placements (finds --placement values)
  python pywowlib/tools/wmo_doodads.py scan --map-id 36

  # List all doodads (WMO-local coordinates)
  python pywowlib/tools/wmo_doodads.py list <wmo>

  # Full pipeline: WMO local -> ADT world -> server coordinates
  python pywowlib/tools/wmo_doodads.py list <wmo> -p 17718.3,29.8,17223.1,0,-91,0

  # Find doodads near a server position (e.g. player coords from .gps)
  python pywowlib/tools/wmo_doodads.py list <wmo> -p ... --near="-178,-459,56" -r 10

  # Output a doodad as gameobject.yaml snippet
  python pywowlib/tools/wmo_doodads.py go <wmo> 235 -p ... --guid 900001 --entry 90001 --map 36

  # Show doodad sets
  python pywowlib/tools/wmo_doodads.py sets <wmo>
"""

import argparse
import math
import os
import struct
import sys
from io import BytesIO

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_TOOLS_DIR))
sys.path.insert(0, _PROJECT_ROOT)

from pywowlib.world_builder.intermediate_format import MPQChain

# 32 tiles * 533.333... yards/tile
_MAP_HALF = 32.0 * 533.0 + 32.0 * (1.0 / 3.0)  # 17066.6667


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
# Binary helpers
# ---------------------------------------------------------------------------

def _read_chunk_header(f):
    raw = f.read(4)
    if len(raw) < 4:
        return None, 0
    try:
        magic = raw.decode('ascii')[::-1]
    except UnicodeDecodeError:
        return None, 0
    size_data = f.read(4)
    if len(size_data) < 4:
        return None, 0
    return magic, struct.unpack('<I', size_data)[0]


def _parse_string_table(data):
    strings = {}
    i, n = 0, len(data)
    while i < n:
        if data[i] == 0:
            i += 1
            continue
        start = i
        while i < n and data[i] != 0:
            i += 1
        try:
            s = data[start:i].decode('ascii')
        except UnicodeDecodeError:
            s = data[start:i].decode('latin-1')
        strings[start] = s
        i += 1
    return strings


# ---------------------------------------------------------------------------
# WMO root parsing
# ---------------------------------------------------------------------------

def parse_wmo_root(data):
    """Parse WMO root bytes.  Returns (name_strings, doodad_defs, doodad_sets)."""
    f = BytesIO(data)
    modn, modd, mods = {}, [], []

    while True:
        magic, size = _read_chunk_header(f)
        if magic is None:
            break
        if magic == 'MODN':
            modn = _parse_string_table(f.read(size))
        elif magic == 'MODD':
            for _ in range(size // 40):
                packed = struct.unpack('<I', f.read(4))[0]
                modd.append({
                    'name_ofs': packed & 0xFFFFFF,
                    'flags': (packed >> 24) & 0xFF,
                    'position': list(struct.unpack('<fff', f.read(12))),
                    'rotation': list(struct.unpack('<ffff', f.read(16))),
                    'scale': struct.unpack('<f', f.read(4))[0],
                    'color': list(struct.unpack('4B', f.read(4))),
                })
        elif magic == 'MODS':
            for _ in range(size // 32):
                name = f.read(20).rstrip(b'\x00').decode('ascii', errors='replace')
                start = struct.unpack('<I', f.read(4))[0]
                count = struct.unpack('<I', f.read(4))[0]
                f.read(4)
                mods.append({'name': name, 'start': start, 'count': count})
        else:
            f.seek(size, 1)

    for d in modd:
        d['name'] = modn.get(d['name_ofs'], '<unknown>')
    return modn, modd, mods


# ---------------------------------------------------------------------------
# WDT MODF parsing
# ---------------------------------------------------------------------------

def parse_wdt_modf(data):
    """Parse WDT for global WMO placement.  Returns dict or None."""
    f = BytesIO(data)
    mwmo = None

    while True:
        magic, size = _read_chunk_header(f)
        if magic is None:
            break
        if magic == 'MWMO' and size > 0:
            mwmo = f.read(size).rstrip(b'\x00').decode('ascii', errors='replace')
        elif magic == 'MODF' and size >= 64:
            f.read(8)  # name_id + unique_id
            pos = struct.unpack('<fff', f.read(12))
            rot = struct.unpack('<fff', f.read(12))
            f.read(size - 32)
            return {
                'wmo_path': mwmo,
                'position': list(pos),
                'rotation': list(rot),
            }
        else:
            f.seek(size, 1)
    return None


# ---------------------------------------------------------------------------
# Coordinate transforms
# ---------------------------------------------------------------------------

def _euler_to_matrix(rot_deg):
    """MODF Euler angles (degrees) -> 3x3 rotation matrix.
    Applied as: Rz * Ry * Rx  where (rx, ry, rz) = rot_deg.
    """
    rx, ry, rz = [math.radians(d) for d in rot_deg]
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return [
        [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
        [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
        [-sy,     cy * sx,                cy * cx               ],
    ]


def _apply_rotation(pos, matrix):
    x, y, z = pos
    return [
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z,
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z,
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z,
    ]


def _adt_to_server(adt_pos):
    """Convert ADT world coordinates to server coordinates."""
    return [
        _MAP_HALF - adt_pos[2],  # server_x = 17066.667 - adt_z
        _MAP_HALF - adt_pos[0],  # server_y = 17066.667 - adt_x
        adt_pos[1],              # server_z = adt_y
    ]


def _transform_doodad(local_pos, wmo_pos, rot_matrix):
    """WMO local -> ADT world -> server coordinates.

    WMO doodads use a coordinate system where X and Z are swapped
    relative to ADT world coordinates, so we swap them before
    applying the MODF rotation.
    """
    swapped = [local_pos[2], local_pos[1], local_pos[0]]
    rotated = _apply_rotation(swapped, rot_matrix)
    adt = [rotated[i] + wmo_pos[i] for i in range(3)]
    return _adt_to_server(adt)


def _distance_3d(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _quat_to_orientation(qx, qy, qz, qw):
    """Extract yaw from a quaternion."""
    siny = 2.0 * (qw * qz + qx * qy)
    cosy = 1.0 - 2.0 * (qy * qy + qz * qz)
    return math.atan2(siny, cosy)


def _short_name(path):
    base = os.path.basename(path)
    for ext in ('.MDX', '.mdx', '.M2', '.m2', '.MDL', '.mdl'):
        if base.endswith(ext):
            return base[:-len(ext)]
    return base


# ---------------------------------------------------------------------------
# Resolve placement
# ---------------------------------------------------------------------------

def _resolve_placement(mpq, args):
    """Returns (wmo_pos, wmo_rot_deg, has_placement)."""
    wmo_pos = [0.0, 0.0, 0.0]
    wmo_rot = [0.0, 0.0, 0.0]
    has_placement = False

    # --wdt: read from WDT global WMO
    if hasattr(args, 'wdt') and args.wdt:
        wdt_data = mpq.read_file(args.wdt)
        if wdt_data:
            modf = parse_wdt_modf(wdt_data)
            if modf:
                wmo_pos = modf['position']
                wmo_rot = modf['rotation']
                has_placement = True
                print("WDT placement: pos=({:.1f}, {:.1f}, {:.1f})  rot=({:.1f}, {:.1f}, {:.1f})".format(
                    *wmo_pos, *wmo_rot))
            else:
                print("WARNING: WDT has no MODF chunk")
        else:
            print("WARNING: WDT not found: {}".format(args.wdt))

    # --placement: explicit MODF values (px,py,pz,rx,ry,rz)
    if hasattr(args, 'placement') and args.placement:
        parts = [float(x) for x in args.placement.split(',')]
        wmo_pos = parts[0:3]
        wmo_rot = parts[3:6] if len(parts) >= 6 else [0.0, 0.0, 0.0]
        has_placement = True
        print("Placement: pos=({:.1f}, {:.1f}, {:.1f})  rot=({:.1f}, {:.1f}, {:.1f})".format(
            *wmo_pos, *wmo_rot))

    return wmo_pos, wmo_rot, has_placement


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(args):
    wow_root = args.wow_root or _get_wow_root()

    with MPQChain(wow_root) as mpq:
        wmo_data = mpq.read_file(args.wmo_path)
        if wmo_data is None:
            print("ERROR: WMO not found in MPQ: {}".format(args.wmo_path))
            sys.exit(1)

        _, modd, mods = parse_wmo_root(wmo_data)

        wmo_pos, wmo_rot, has_placement = _resolve_placement(mpq, args)
        rot_matrix = _euler_to_matrix(wmo_rot)

        # Build indexed list
        indexed = list(enumerate(modd))

        # Filter by doodad set
        if args.set is not None:
            if 0 <= args.set < len(mods):
                ds = mods[args.set]
                valid = set(range(ds['start'], ds['start'] + ds['count']))
                indexed = [(i, d) for i, d in indexed if i in valid]
            else:
                print("ERROR: Set {} does not exist (max {})".format(args.set, len(mods) - 1))
                sys.exit(1)

        # Filter by search term
        if args.search:
            term = args.search.lower()
            indexed = [(i, d) for i, d in indexed if term in d['name'].lower()]

        # Compute output positions
        for _, d in indexed:
            if has_placement:
                d['out_pos'] = _transform_doodad(d['position'], wmo_pos, rot_matrix)
            else:
                d['out_pos'] = list(d['position'])

        # Filter by proximity
        if args.near:
            near_pos = [float(x) for x in args.near.split(',')]
            indexed = [(i, d) for i, d in indexed
                       if _distance_3d(d['out_pos'], near_pos) <= args.radius]
            indexed.sort(key=lambda p: _distance_3d(p[1]['out_pos'], near_pos))

        if not indexed:
            print("No doodads found.")
            return

        label = "Server Position" if has_placement else "WMO Local Position"
        print("\n{:>4}  {:<35}  {:<35}  {:>5}".format('#', 'Model', label, 'Scale'))
        print('-' * 90)

        for idx, d in indexed:
            p = d['out_pos']
            name = _short_name(d['name'])
            print("{:4d}  {:<35}  ({:>8.2f}, {:>8.2f}, {:>8.2f})  {:>5.2f}".format(
                idx, name, p[0], p[1], p[2], d['scale']))

        print("\n{} doodad(s) shown (of {} total)".format(len(indexed), len(modd)))


def cmd_sets(args):
    wow_root = args.wow_root or _get_wow_root()

    with MPQChain(wow_root) as mpq:
        wmo_data = mpq.read_file(args.wmo_path)
        if wmo_data is None:
            print("ERROR: WMO not found: {}".format(args.wmo_path))
            sys.exit(1)

        _, modd, mods = parse_wmo_root(wmo_data)

        print("\n{:>4}  {:<30}  {:>6}  {:>6}".format('Set', 'Name', 'Start', 'Count'))
        print('-' * 55)
        for i, ds in enumerate(mods):
            print("{:4d}  {:<30}  {:>6}  {:>6}".format(
                i, ds['name'], ds['start'], ds['count']))
        print("\n{} set(s), {} doodad(s)".format(len(mods), len(modd)))


def _parse_adt_wmo_placements(data):
    """Parse MWMO + MODF from an ADT file.  Returns list of dicts."""
    f = BytesIO(data)
    mwmo_names = []
    modf_entries = []

    while True:
        magic, size = _read_chunk_header(f)
        if magic is None:
            break
        if magic == 'MWMO' and size > 0:
            raw = f.read(size)
            i, n = 0, len(raw)
            while i < n:
                if raw[i] == 0:
                    i += 1
                    continue
                start = i
                while i < n and raw[i] != 0:
                    i += 1
                mwmo_names.append(raw[start:i].decode('ascii', errors='replace'))
                i += 1
        elif magic == 'MODF' and size >= 64:
            for _ in range(size // 64):
                entry = f.read(64)
                name_id, unique_id = struct.unpack('<II', entry[:8])
                pos = list(struct.unpack('<fff', entry[8:20]))
                rot = list(struct.unpack('<fff', entry[20:32]))
                name = mwmo_names[name_id] if name_id < len(mwmo_names) else '<unknown>'
                modf_entries.append({
                    'name': name, 'pos': pos, 'rot': rot,
                    'unique_id': unique_id,
                })
        else:
            f.seek(size, 1)
    return modf_entries


def cmd_scan(args):
    """Scan ADT tiles for a map to find all WMO placements."""
    wow_root = args.wow_root or _get_wow_root()

    with MPQChain(wow_root) as mpq:
        # Find map directory from map ID using Map.dbc
        map_dir = args.map_dir
        if not map_dir:
            # Try to read Map.dbc to resolve map ID
            dbc_data = mpq.read_file('DBFilesClient\\Map.dbc')
            if dbc_data and args.map_id is not None:
                f = BytesIO(dbc_data)
                header = f.read(20)
                _, n_records, n_fields, rec_size, str_size = struct.unpack('<4sIIII', header)
                str_start = 20 + n_records * rec_size
                for _ in range(n_records):
                    rec_start = f.tell()
                    rec_id = struct.unpack('<I', f.read(4))[0]
                    if rec_id == args.map_id:
                        # Field 1 is InternalName string offset
                        name_ofs = struct.unpack('<I', f.read(4))[0]
                        f.seek(str_start + name_ofs)
                        chars = []
                        while True:
                            c = f.read(1)
                            if c == b'\x00' or not c:
                                break
                            chars.append(c)
                        map_dir = b''.join(chars).decode('ascii')
                        break
                    f.seek(rec_start + rec_size)

        if not map_dir:
            print("ERROR: Specify --map-dir or --map-id to identify the map")
            sys.exit(1)

        print("Map directory: {}".format(map_dir))
        base = 'World\\Maps\\{}\\{}'.format(map_dir, map_dir)

        # Scan all possible tiles
        all_wmos = {}
        for tx in range(64):
            for ty in range(64):
                path = '{}_{:d}_{:d}.adt'.format(base, tx, ty)
                data = mpq.read_file(path)
                if not data:
                    continue
                for e in _parse_adt_wmo_placements(data):
                    key = '{}|{}'.format(e['name'], e['unique_id'])
                    if key not in all_wmos:
                        e['tiles'] = []
                        all_wmos[key] = e
                    all_wmos[key]['tiles'].append('[{},{}]'.format(tx, ty))

        if not all_wmos:
            print("No WMO placements found.")
            return

        # Print results
        print("\n{} unique WMO placement(s):\n".format(len(all_wmos)))
        for _, w in sorted(all_wmos.items()):
            short = os.path.basename(w['name'])
            pos = w['pos']
            rot = w['rot']
            srv = _adt_to_server(pos)
            tiles = ' '.join(w['tiles'])
            print("  {}".format(short))
            print("    path: {}".format(w['name']))
            print("    placement: {:.1f},{:.1f},{:.1f},{:.1f},{:.1f},{:.1f}".format(
                pos[0], pos[1], pos[2], rot[0], rot[1], rot[2]))
            print("    server ~ ({:.0f}, {:.0f}, {:.0f})".format(srv[0], srv[1], srv[2]))
            print("    tiles: {}".format(tiles))
            print()


def cmd_gameobject(args):
    wow_root = args.wow_root or _get_wow_root()

    with MPQChain(wow_root) as mpq:
        wmo_data = mpq.read_file(args.wmo_path)
        if wmo_data is None:
            print("ERROR: WMO not found: {}".format(args.wmo_path))
            sys.exit(1)

        _, modd, _ = parse_wmo_root(wmo_data)
        wmo_pos, wmo_rot, has_placement = _resolve_placement(mpq, args)
        rot_matrix = _euler_to_matrix(wmo_rot)

        idx = args.index
        if idx < 0 or idx >= len(modd):
            print("ERROR: Index {} out of range (0-{})".format(idx, len(modd) - 1))
            sys.exit(1)

        d = modd[idx]
        if has_placement:
            pos = _transform_doodad(d['position'], wmo_pos, rot_matrix)
        else:
            pos = list(d['position'])

        qx, qy, qz, qw = d['rotation']
        orient = _quat_to_orientation(qx, qy, qz, qw)

        guid = args.guid or 900001
        entry = args.entry or 90001
        map_id = args.map or 0

        print("  # {} — doodad index {}".format(_short_name(d['name']), idx))
        print("  {}:".format(guid))
        print("    guid: {}".format(guid))
        print("    id: {}".format(entry))
        print("    map: {}".format(map_id))
        print("    zoneId: 0")
        print("    areaId: 0")
        print("    spawnMask: 1")
        print("    phaseMask: 1")
        print("    position_x: {:.1f}".format(pos[0]))
        print("    position_y: {:.1f}".format(pos[1]))
        print("    position_z: {:.1f}".format(pos[2]))
        print("    orientation: {:.4f}".format(orient))
        print("    rotation0: {:.4f}".format(qx))
        print("    rotation1: {:.4f}".format(qy))
        print("    rotation2: {:.4f}".format(qz))
        print("    rotation3: {:.4f}".format(qw))
        print("    spawntimesecs: 180")
        print("    animprogress: 100")
        print("    state: 1")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _add_placement_args(p):
    """Add common placement arguments to a subparser."""
    p.add_argument('--wdt', help='WDT path for global WMO placement')
    p.add_argument('--placement', '-p',
                   help='MODF placement: px,py,pz,rx,ry,rz (from ADT)')


def main():
    parser = argparse.ArgumentParser(
        description='Extract doodad positions from WMO files in MPQ archives')
    parser.add_argument('--wow-root', help='WoW client root (default: docker/.env)')

    sub = parser.add_subparsers(dest='command')

    # list
    p_list = sub.add_parser('list', help='List doodads')
    p_list.add_argument('wmo_path')
    p_list.add_argument('--search', '-s', help='Filter by model name')
    p_list.add_argument('--near', help='Filter near server position: x,y,z')
    p_list.add_argument('--radius', '-r', type=float, default=20.0)
    p_list.add_argument('--set', type=int, default=None, help='Doodad set index')
    _add_placement_args(p_list)

    # scan
    p_scan = sub.add_parser('scan', help='Scan ADT tiles for WMO placements')
    p_scan.add_argument('--map-id', type=int, help='Map ID (reads Map.dbc)')
    p_scan.add_argument('--map-dir', help='Map directory name (e.g. DeadminesInstance)')

    # sets
    p_sets = sub.add_parser('sets', help='List doodad sets')
    p_sets.add_argument('wmo_path')

    # go
    p_go = sub.add_parser('go', help='Output as gameobject.yaml')
    p_go.add_argument('wmo_path')
    p_go.add_argument('index', type=int, help='Doodad index')
    p_go.add_argument('--guid', type=int)
    p_go.add_argument('--entry', type=int)
    p_go.add_argument('--map', type=int)
    _add_placement_args(p_go)

    args = parser.parse_args()

    if args.command == 'list':
        cmd_list(args)
    elif args.command == 'scan':
        cmd_scan(args)
    elif args.command == 'sets':
        cmd_sets(args)
    elif args.command == 'go':
        cmd_gameobject(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
