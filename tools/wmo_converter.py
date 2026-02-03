#!/usr/bin/env python
"""
WMO <-> JSON bidirectional converter for World of Warcraft WMO files.

Converts binary WMO root and group files to human-readable JSON and back.
Auto-detects whether a file is a root WMO (header, materials, portals, doodads)
or a group WMO (geometry, BSP, batches) based on chunk content.

Usage:
  python wmo_converter.py wmo2json <input.wmo> [-o output.json]
  python wmo_converter.py json2wmo <input.json> [-o output.wmo]
  python wmo_converter.py wmo2json --dir <wmo_dir> [-o output_dir]
"""

import struct
import json
import os
import sys
import math
import argparse


# ---------------------------------------------------------------------------
# Low-level binary helpers
# ---------------------------------------------------------------------------

def _read_uint8(f, n=1):
    if n == 1:
        return struct.unpack('B', f.read(1))[0]
    return tuple(struct.unpack(str(n) + 'B', f.read(n)))


def _read_int8(f, n=1):
    if n == 1:
        return struct.unpack('b', f.read(1))[0]
    return tuple(struct.unpack(str(n) + 'b', f.read(n)))


def _read_uint16(f, n=1):
    if n == 1:
        return struct.unpack('<H', f.read(2))[0]
    return tuple(struct.unpack('<' + str(n) + 'H', f.read(2 * n)))


def _read_int16(f, n=1):
    if n == 1:
        return struct.unpack('<h', f.read(2))[0]
    return tuple(struct.unpack('<' + str(n) + 'h', f.read(2 * n)))


def _read_uint32(f, n=1):
    if n == 1:
        return struct.unpack('<I', f.read(4))[0]
    return tuple(struct.unpack('<' + str(n) + 'I', f.read(4 * n)))


def _read_int32(f, n=1):
    if n == 1:
        return struct.unpack('<i', f.read(4))[0]
    return tuple(struct.unpack('<' + str(n) + 'i', f.read(4 * n)))


def _read_float32(f, n=1):
    if n == 1:
        return struct.unpack('<f', f.read(4))[0]
    return tuple(struct.unpack('<' + str(n) + 'f', f.read(4 * n)))


def _read_vec3d(f):
    return list(struct.unpack('<fff', f.read(12)))


def _read_vec2d(f):
    return list(struct.unpack('<ff', f.read(8)))


def _write_uint8(f, val, n=1):
    if n == 1:
        f.write(struct.pack('B', val))
    else:
        f.write(struct.pack(str(n) + 'B', *val))


def _write_int8(f, val, n=1):
    if n == 1:
        f.write(struct.pack('b', val))
    else:
        f.write(struct.pack(str(n) + 'b', *val))


def _write_uint16(f, val, n=1):
    if n == 1:
        f.write(struct.pack('<H', val))
    else:
        f.write(struct.pack('<' + str(n) + 'H', *val))


def _write_int16(f, val, n=1):
    if n == 1:
        f.write(struct.pack('<h', val))
    else:
        f.write(struct.pack('<' + str(n) + 'h', *val))


def _write_uint32(f, val, n=1):
    if n == 1:
        f.write(struct.pack('<I', val))
    else:
        f.write(struct.pack('<' + str(n) + 'I', *val))


def _write_int32(f, val, n=1):
    if n == 1:
        f.write(struct.pack('<i', val))
    else:
        f.write(struct.pack('<' + str(n) + 'i', *val))


def _write_float32(f, val, n=1):
    if n == 1:
        f.write(struct.pack('<f', val))
    else:
        f.write(struct.pack('<' + str(n) + 'f', *val))


def _write_vec3d(f, v):
    f.write(struct.pack('<fff', *v))


def _write_vec2d(f, v):
    f.write(struct.pack('<ff', *v))


def _safe_float(val):
    """Sanitize a float for JSON (NaN / Inf are not valid JSON)."""
    if math.isnan(val) or math.isinf(val):
        return 0.0
    return val


def _safe_floats(vals):
    """Sanitize a sequence of floats."""
    return [_safe_float(v) for v in vals]


# ---------------------------------------------------------------------------
# Chunk I/O: 4-byte reversed magic + uint32 size + data
# ---------------------------------------------------------------------------

def _read_chunk_header(f):
    """Read a chunk header. Returns (magic_str, size) or (None, 0) at EOF."""
    raw = f.read(4)
    if len(raw) < 4:
        return None, 0
    try:
        magic = raw.decode('ascii')[::-1]
    except UnicodeDecodeError:
        return None, 0
    size = struct.unpack('<I', f.read(4))[0]
    return magic, size


def _write_chunk_header(f, magic, size):
    """Write a chunk header with reversed magic."""
    f.write(magic[::-1].encode('ascii'))
    f.write(struct.pack('<I', size))


# ---------------------------------------------------------------------------
# String table helpers
# ---------------------------------------------------------------------------

def _parse_string_table(data):
    """Parse a null-terminated string table into {offset: string} dict and ordered list."""
    strings = {}
    ordered = []
    i = 0
    n = len(data)
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
            try:
                s = data[start:i].decode('windows-1252')
            except UnicodeDecodeError:
                s = data[start:i].decode('latin-1')
        strings[start] = s
        ordered.append({'offset': start, 'string': s})
        i += 1  # skip null terminator
    return strings, ordered


def _build_string_table(entries):
    """Rebuild a string table bytearray from a list of {offset, string} entries.
    Returns (bytearray, {old_offset: new_offset} mapping).
    """
    if not entries:
        return bytearray(b'\x00'), {}

    # Sort by original offset
    sorted_entries = sorted(entries, key=lambda e: e['offset'])
    table = bytearray()
    offset_map = {}

    for entry in sorted_entries:
        old_ofs = entry['offset']
        # Pad to match original offset if possible, otherwise just append with alignment
        while len(table) < old_ofs:
            table.append(0)
        offset_map[old_ofs] = len(table)
        encoded = entry['string'].encode('ascii', errors='replace')
        table.extend(encoded)
        table.append(0)

    return table, offset_map


def _build_string_table_raw(entries):
    """Rebuild a raw string table preserving original offsets exactly."""
    if not entries:
        return bytearray(b'\x00')

    sorted_entries = sorted(entries, key=lambda e: e['offset'])
    # Determine total size needed
    last = sorted_entries[-1]
    end = last['offset'] + len(last['string'].encode('ascii', errors='replace')) + 1
    table = bytearray(end)

    for entry in sorted_entries:
        ofs = entry['offset']
        encoded = entry['string'].encode('ascii', errors='replace')
        table[ofs:ofs + len(encoded)] = encoded
        table[ofs + len(encoded)] = 0

    return table


# ---------------------------------------------------------------------------
# ROOT CHUNK PARSERS
# ---------------------------------------------------------------------------

def _parse_mver(f, size):
    return {'version': _read_uint32(f)}


def _parse_mohd(f, size):
    return {
        'n_materials': _read_uint32(f),
        'n_groups': _read_uint32(f),
        'n_portals': _read_uint32(f),
        'n_lights': _read_uint32(f),
        'n_models': _read_uint32(f),
        'n_doodads': _read_uint32(f),
        'n_sets': _read_uint32(f),
        'ambient_color': list(_read_uint8(f, 4)),
        'id': _read_uint32(f),
        'bounding_box_corner1': _safe_floats(_read_vec3d(f)),
        'bounding_box_corner2': _safe_floats(_read_vec3d(f)),
        'flags': _read_uint16(f),
        'n_lods': _read_uint16(f),
    }


def _parse_motx(f, size):
    """Texture name string table."""
    data = f.read(size)
    _, ordered = _parse_string_table(data)
    return {'_raw_hex': data.hex(), 'strings': ordered}


def _parse_momt(f, size):
    """Materials - each 64 bytes."""
    count = size // 64
    materials = []
    for _ in range(count):
        mat = {
            'flags': _read_uint32(f),
            'shader': _read_uint32(f),
            'blend_mode': _read_uint32(f),
            'texture1_ofs': _read_uint32(f),
            'emissive_color': list(_read_uint8(f, 4)),
            'sidn_emissive_color': list(_read_uint8(f, 4)),
            'texture2_ofs': _read_uint32(f),
            'diff_color': list(_read_uint8(f, 4)),
            'terrain_type': _read_uint32(f),
            'texture3_ofs': _read_uint32(f),
            'color3': list(_read_uint8(f, 4)),
            'tex3_flags': _read_uint32(f),
            'runtime_data': list(_read_uint32(f, 4)),
        }
        materials.append(mat)
    return materials


def _parse_mogn(f, size):
    """Group name string table."""
    data = f.read(size)
    _, ordered = _parse_string_table(data)
    return {'_raw_hex': data.hex(), 'strings': ordered}


def _parse_mogi(f, size):
    """Group info - each 32 bytes."""
    count = size // 32
    infos = []
    for _ in range(count):
        infos.append({
            'flags': _read_uint32(f),
            'bounding_box_corner1': _safe_floats(_read_vec3d(f)),
            'bounding_box_corner2': _safe_floats(_read_vec3d(f)),
            'name_ofs': _read_uint32(f),
        })
    return infos


def _parse_mosb(f, size):
    """Skybox path."""
    data = f.read(size)
    # strip null bytes
    text = data.rstrip(b'\x00').decode('ascii', errors='replace')
    return {'skybox': text, '_raw_hex': data.hex()}


def _parse_mopv(f, size):
    """Portal vertices - vec3D each (12 bytes)."""
    count = size // 12
    return [_safe_floats(_read_vec3d(f)) for _ in range(count)]


def _parse_mopt(f, size):
    """Portal info - each 20 bytes."""
    count = size // 20
    infos = []
    for _ in range(count):
        infos.append({
            'start_vertex': _read_uint16(f),
            'n_vertices': _read_uint16(f),
            'normal': _safe_floats(_read_vec3d(f)),
            'unknown': _safe_float(_read_float32(f)),
        })
    return infos


def _parse_mopr(f, size):
    """Portal relations - each 8 bytes."""
    count = size // 8
    relations = []
    for _ in range(count):
        relations.append({
            'portal_index': _read_uint16(f),
            'group_index': _read_uint16(f),
            'side': _read_int16(f),
            'padding': _read_uint16(f),
        })
    return relations


def _parse_movv(f, size):
    """Visible block vertices - vec3D each."""
    count = size // 12
    return [_safe_floats(_read_vec3d(f)) for _ in range(count)]


def _parse_movb(f, size):
    """Visible block batches - each 4 bytes."""
    count = size // 4
    batches = []
    for _ in range(count):
        batches.append({
            'start_vertex': _read_uint16(f),
            'n_vertices': _read_uint16(f),
        })
    return batches


def _parse_molt(f, size):
    """Lights - each 48 bytes."""
    count = size // 48
    lights = []
    for _ in range(count):
        lights.append({
            'light_type': _read_uint8(f),
            'type': _read_uint8(f),
            'use_attenuation': _read_uint8(f),
            'padding': _read_uint8(f),
            'color': list(_read_uint8(f, 4)),
            'position': _safe_floats(_read_vec3d(f)),
            'intensity': _safe_float(_read_float32(f)),
            'attenuation_start': _safe_float(_read_float32(f)),
            'attenuation_end': _safe_float(_read_float32(f)),
            'unknown1': _safe_float(_read_float32(f)),
            'unknown2': _safe_float(_read_float32(f)),
            'unknown3': _safe_float(_read_float32(f)),
            'unknown4': _safe_float(_read_float32(f)),
        })
    return lights


def _parse_mods(f, size):
    """Doodad sets - each 32 bytes."""
    count = size // 32
    sets = []
    for _ in range(count):
        name_raw = f.read(20)
        name = name_raw.rstrip(b'\x00').decode('ascii', errors='replace')
        sets.append({
            'name': name,
            'start_doodad': _read_uint32(f),
            'n_doodads': _read_uint32(f),
            'padding': _read_uint32(f),
        })
    return sets


def _parse_modn(f, size):
    """Doodad name string table."""
    data = f.read(size)
    _, ordered = _parse_string_table(data)
    return {'_raw_hex': data.hex(), 'strings': ordered}


def _parse_modd(f, size):
    """Doodad definitions - each 40 bytes."""
    count = size // 40
    defs = []
    for _ in range(count):
        packed = _read_uint32(f)
        name_ofs = packed & 0xFFFFFF
        flags = (packed >> 24) & 0xFF
        defs.append({
            'name_ofs': name_ofs,
            'flags': flags,
            'position': _safe_floats(_read_vec3d(f)),
            'rotation': _safe_floats(list(_read_float32(f, 4))),
            'scale': _safe_float(_read_float32(f)),
            'color': list(_read_uint8(f, 4)),
        })
    return defs


def _parse_mfog(f, size):
    """Fog definitions - each 48 bytes."""
    count = size // 48
    fogs = []
    for _ in range(count):
        fogs.append({
            'flags': _read_uint32(f),
            'position': _safe_floats(_read_vec3d(f)),
            'small_radius': _safe_float(_read_float32(f)),
            'big_radius': _safe_float(_read_float32(f)),
            'end_dist': _safe_float(_read_float32(f)),
            'start_factor': _safe_float(_read_float32(f)),
            'color1': list(_read_uint8(f, 4)),
            'end_dist2': _safe_float(_read_float32(f)),
            'start_factor2': _safe_float(_read_float32(f)),
            'color2': list(_read_uint8(f, 4)),
        })
    return fogs


def _parse_mcvp(f, size):
    """Convex volume planes - each 16 bytes (quaternion/4-float)."""
    count = size // 16
    return [_safe_floats(list(_read_float32(f, 4))) for _ in range(count)]


# ---------------------------------------------------------------------------
# GROUP CHUNK PARSERS
# ---------------------------------------------------------------------------

def _parse_mogp(f, size):
    """Group header - 68 bytes of fields, rest is sub-chunks."""
    return {
        'group_name_ofs': _read_uint32(f),
        'desc_group_name_ofs': _read_uint32(f),
        'flags': _read_uint32(f),
        'bounding_box_corner1': _safe_floats(_read_vec3d(f)),
        'bounding_box_corner2': _safe_floats(_read_vec3d(f)),
        'portal_start': _read_uint16(f),
        'portal_count': _read_uint16(f),
        'n_batches_a': _read_uint16(f),
        'n_batches_b': _read_uint16(f),
        'n_batches_c': _read_uint16(f),
        'n_batches_d': _read_uint16(f),
        'fog_indices': list(_read_uint8(f, 4)),
        'liquid_type': _read_uint32(f),
        'group_id': _read_uint32(f),
        'unknown1': _read_uint32(f),
        'unknown2': _read_uint32(f),
    }


def _parse_mopy(f, size):
    """Triangle materials - each 2 bytes."""
    count = size // 2
    mats = []
    for _ in range(count):
        mats.append({
            'flags': _read_uint8(f),
            'material_id': _read_uint8(f),
        })
    return mats


def _parse_movi(f, size):
    """Triangle indices - uint16 each."""
    count = size // 2
    return list(_read_uint16(f, count)) if count > 1 else ([_read_uint16(f)] if count == 1 else [])


def _parse_movt(f, size):
    """Vertices - vec3D each (12 bytes)."""
    count = size // 12
    return [_safe_floats(_read_vec3d(f)) for _ in range(count)]


def _parse_monr(f, size):
    """Normals - vec3D each (12 bytes)."""
    count = size // 12
    return [_safe_floats(_read_vec3d(f)) for _ in range(count)]


def _parse_motv(f, size):
    """Texture coordinates - 2 floats each (8 bytes)."""
    count = size // 8
    return [_safe_floats(_read_vec2d(f)) for _ in range(count)]


def _parse_moba(f, size):
    """Render batches - each 24 bytes."""
    count = size // 24
    batches = []
    for _ in range(count):
        batches.append({
            'bounding_box': list(_read_int16(f, 6)),
            'start_triangle': _read_uint32(f),
            'n_triangles': _read_uint16(f),
            'start_vertex': _read_uint16(f),
            'last_vertex': _read_uint16(f),
            'unknown': _read_uint8(f),
            'material_id': _read_uint8(f),
        })
    return batches


def _parse_molr(f, size):
    """Light references - int16 each."""
    count = size // 2
    return list(_read_int16(f, count)) if count > 1 else ([_read_int16(f)] if count == 1 else [])


def _parse_modr(f, size):
    """Doodad references - int16 each."""
    count = size // 2
    return list(_read_int16(f, count)) if count > 1 else ([_read_int16(f)] if count == 1 else [])


def _parse_mobn(f, size):
    """BSP nodes - each 16 bytes."""
    count = size // 16
    nodes = []
    for _ in range(count):
        nodes.append({
            'plane_type': _read_int16(f),
            'children': list(_read_int16(f, 2)),
            'num_faces': _read_uint16(f),
            'first_face': _read_uint32(f),
            'dist': _safe_float(_read_float32(f)),
        })
    return nodes


def _parse_mobr(f, size):
    """BSP face indices - uint16 each."""
    count = size // 2
    return list(_read_uint16(f, count)) if count > 1 else ([_read_uint16(f)] if count == 1 else [])


def _parse_mocv(f, size):
    """Vertex colors - 4 uint8 each."""
    count = size // 4
    return [list(_read_uint8(f, 4)) for _ in range(count)]


def _parse_mliq(f, size):
    """Liquid data."""
    start_pos = f.tell()
    x_verts = _read_uint32(f)
    y_verts = _read_uint32(f)
    x_tiles = _read_uint32(f)
    y_tiles = _read_uint32(f)
    position = _safe_floats(_read_vec3d(f))
    material_id = _read_uint16(f)

    vertex_count = x_verts * y_verts
    vertex_map = []
    for _ in range(vertex_count):
        # Read as both water and magma interpretation (overlapping union)
        raw_bytes = f.read(4)
        flow1, flow2, flow1_pct, filler = struct.unpack('4B', raw_bytes)
        u, v = struct.unpack('<hh', raw_bytes)
        height = _safe_float(_read_float32(f))
        vertex_map.append({
            'flow1': flow1, 'flow2': flow2,
            'flow1_pct': flow1_pct, 'filler': filler,
            'u': u, 'v': v,
            'height': height,
        })

    tile_count = x_tiles * y_tiles
    tile_flags = []
    for _ in range(tile_count):
        tile_flags.append(_read_uint8(f))

    return {
        'x_verts': x_verts, 'y_verts': y_verts,
        'x_tiles': x_tiles, 'y_tiles': y_tiles,
        'position': position,
        'material_id': material_id,
        'vertex_map': vertex_map,
        'tile_flags': tile_flags,
    }


# ---------------------------------------------------------------------------
# Raw chunk fallback (hex dump for unknown chunks)
# ---------------------------------------------------------------------------

def _parse_raw(f, size):
    """Read raw chunk data as hex string for unknown chunks."""
    data = f.read(size)
    return {'_hex': data.hex(), '_size': size}


# ---------------------------------------------------------------------------
# CHUNK DISPATCH TABLES
# ---------------------------------------------------------------------------

ROOT_PARSERS = {
    'MVER': _parse_mver,
    'MOHD': _parse_mohd,
    'MOTX': _parse_motx,
    'MOMT': _parse_momt,
    'MOGN': _parse_mogn,
    'MOGI': _parse_mogi,
    'MOSB': _parse_mosb,
    'MOPV': _parse_mopv,
    'MOPT': _parse_mopt,
    'MOPR': _parse_mopr,
    'MOVV': _parse_movv,
    'MOVB': _parse_movb,
    'MOLT': _parse_molt,
    'MODS': _parse_mods,
    'MODN': _parse_modn,
    'MODD': _parse_modd,
    'MFOG': _parse_mfog,
    'MCVP': _parse_mcvp,
}

GROUP_PARSERS = {
    'MVER': _parse_mver,
    'MOGP': _parse_mogp,
    'MOPY': _parse_mopy,
    'MOVI': _parse_movi,
    'MOVT': _parse_movt,
    'MONR': _parse_monr,
    'MOTV': _parse_motv,
    'MOBA': _parse_moba,
    'MOLR': _parse_molr,
    'MODR': _parse_modr,
    'MOBN': _parse_mobn,
    'MOBR': _parse_mobr,
    'MOCV': _parse_mocv,
    'MLIQ': _parse_mliq,
}


# ---------------------------------------------------------------------------
# ROOT CHUNK WRITERS
# ---------------------------------------------------------------------------

def _write_mver(f, data):
    buf = struct.pack('<I', data['version'])
    _write_chunk_header(f, 'MVER', len(buf))
    f.write(buf)


def _write_mohd(f, data):
    from io import BytesIO
    buf = BytesIO()
    _write_uint32(buf, data['n_materials'])
    _write_uint32(buf, data['n_groups'])
    _write_uint32(buf, data['n_portals'])
    _write_uint32(buf, data['n_lights'])
    _write_uint32(buf, data['n_models'])
    _write_uint32(buf, data['n_doodads'])
    _write_uint32(buf, data['n_sets'])
    _write_uint8(buf, tuple(data['ambient_color']), 4)
    _write_uint32(buf, data['id'])
    _write_vec3d(buf, data['bounding_box_corner1'])
    _write_vec3d(buf, data['bounding_box_corner2'])
    _write_uint16(buf, data['flags'])
    _write_uint16(buf, data['n_lods'])
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOHD', len(raw))
    f.write(raw)


def _write_motx(f, data):
    if isinstance(data, dict) and '_raw_hex' in data:
        raw = bytes.fromhex(data['_raw_hex'])
        _write_chunk_header(f, 'MOTX', len(raw))
        f.write(raw)
    else:
        entries = data['strings'] if isinstance(data, dict) else data
        table = _build_string_table_raw(entries)
        padding_needed = (16 - len(table) % 16) % 16
        if padding_needed == 0:
            padding_needed = 16
        table.extend(b'\x00' * padding_needed)
        _write_chunk_header(f, 'MOTX', len(table))
        f.write(table)


def _write_momt(f, data):
    from io import BytesIO
    buf = BytesIO()
    for mat in data:
        _write_uint32(buf, mat['flags'])
        _write_uint32(buf, mat['shader'])
        _write_uint32(buf, mat['blend_mode'])
        _write_uint32(buf, mat['texture1_ofs'])
        _write_uint8(buf, tuple(mat['emissive_color']), 4)
        _write_uint8(buf, tuple(mat['sidn_emissive_color']), 4)
        _write_uint32(buf, mat['texture2_ofs'])
        _write_uint8(buf, tuple(mat['diff_color']), 4)
        _write_uint32(buf, mat['terrain_type'])
        _write_uint32(buf, mat['texture3_ofs'])
        _write_uint8(buf, tuple(mat['color3']), 4)
        _write_uint32(buf, mat['tex3_flags'])
        _write_uint32(buf, tuple(mat['runtime_data']), 4)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOMT', len(raw))
    f.write(raw)


def _write_mogn(f, data):
    if isinstance(data, dict) and '_raw_hex' in data:
        raw = bytes.fromhex(data['_raw_hex'])
        _write_chunk_header(f, 'MOGN', len(raw))
        f.write(raw)
    else:
        entries = data['strings'] if isinstance(data, dict) else data
        table = _build_string_table_raw(entries)
        padding_needed = (4 - len(table) % 4) % 4
        table.extend(b'\x00' * padding_needed)
        _write_chunk_header(f, 'MOGN', len(table))
        f.write(table)


def _write_mogi(f, data):
    from io import BytesIO
    buf = BytesIO()
    for info in data:
        _write_uint32(buf, info['flags'])
        _write_vec3d(buf, info['bounding_box_corner1'])
        _write_vec3d(buf, info['bounding_box_corner2'])
        _write_uint32(buf, info['name_ofs'])
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOGI', len(raw))
    f.write(raw)


def _write_mosb(f, data):
    if isinstance(data, dict) and '_raw_hex' in data:
        raw = bytes.fromhex(data['_raw_hex'])
        _write_chunk_header(f, 'MOSB', len(raw))
        f.write(raw)
    else:
        text = data if isinstance(data, str) else (data.get('skybox', '') if isinstance(data, dict) else '')
        if not text:
            text = '\x00\x00\x00'
        encoded = text.encode('ascii')
        padding_needed = (4 - len(encoded) % 4) % 4
        if padding_needed == 0:
            padding_needed = 4
        total = len(encoded) + padding_needed
        _write_chunk_header(f, 'MOSB', total)
        f.write(encoded)
        f.write(b'\x00' * padding_needed)


def _write_mopv(f, data):
    from io import BytesIO
    buf = BytesIO()
    for v in data:
        _write_vec3d(buf, v)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOPV', len(raw))
    f.write(raw)


def _write_mopt(f, data):
    from io import BytesIO
    buf = BytesIO()
    for info in data:
        _write_uint16(buf, info['start_vertex'])
        _write_uint16(buf, info['n_vertices'])
        _write_vec3d(buf, info['normal'])
        _write_float32(buf, info['unknown'])
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOPT', len(raw))
    f.write(raw)


def _write_mopr(f, data):
    from io import BytesIO
    buf = BytesIO()
    for rel in data:
        _write_uint16(buf, rel['portal_index'])
        _write_uint16(buf, rel['group_index'])
        _write_int16(buf, rel['side'])
        _write_uint16(buf, rel['padding'])
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOPR', len(raw))
    f.write(raw)


def _write_movv(f, data):
    from io import BytesIO
    buf = BytesIO()
    for v in data:
        _write_vec3d(buf, v)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOVV', len(raw))
    f.write(raw)


def _write_movb(f, data):
    from io import BytesIO
    buf = BytesIO()
    for b in data:
        _write_uint16(buf, b['start_vertex'])
        _write_uint16(buf, b['n_vertices'])
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOVB', len(raw))
    f.write(raw)


def _write_molt(f, data):
    from io import BytesIO
    buf = BytesIO()
    for light in data:
        _write_uint8(buf, light['light_type'])
        _write_uint8(buf, light['type'])
        _write_uint8(buf, light['use_attenuation'])
        _write_uint8(buf, light['padding'])
        _write_uint8(buf, tuple(light['color']), 4)
        _write_vec3d(buf, light['position'])
        _write_float32(buf, light['intensity'])
        _write_float32(buf, light['attenuation_start'])
        _write_float32(buf, light['attenuation_end'])
        _write_float32(buf, light['unknown1'])
        _write_float32(buf, light['unknown2'])
        _write_float32(buf, light['unknown3'])
        _write_float32(buf, light['unknown4'])
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOLT', len(raw))
    f.write(raw)


def _write_mods(f, data):
    from io import BytesIO
    buf = BytesIO()
    for s in data:
        name_bytes = s['name'].ljust(20, '\0').encode('ascii')[:20]
        buf.write(name_bytes)
        _write_uint32(buf, s['start_doodad'])
        _write_uint32(buf, s['n_doodads'])
        _write_uint32(buf, s['padding'])
    raw = buf.getvalue()
    _write_chunk_header(f, 'MODS', len(raw))
    f.write(raw)


def _write_modn(f, data):
    if isinstance(data, dict) and '_raw_hex' in data:
        raw = bytes.fromhex(data['_raw_hex'])
        _write_chunk_header(f, 'MODN', len(raw))
        f.write(raw)
    else:
        entries = data['strings'] if isinstance(data, dict) else data
        table = _build_string_table_raw(entries)
        padding = len(table) % 4
        if padding > 0:
            table.extend(b'\x00' * (4 - padding))
        _write_chunk_header(f, 'MODN', len(table))
        f.write(table)


def _write_modd(f, data):
    from io import BytesIO
    buf = BytesIO()
    for d in data:
        packed = ((d['flags'] & 0xFF) << 24) | (d['name_ofs'] & 0xFFFFFF)
        _write_uint32(buf, packed)
        _write_vec3d(buf, d['position'])
        _write_float32(buf, tuple(d['rotation']), 4)
        _write_float32(buf, d['scale'])
        _write_uint8(buf, tuple(d['color']), 4)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MODD', len(raw))
    f.write(raw)


def _write_mfog(f, data):
    from io import BytesIO
    buf = BytesIO()
    for fog in data:
        _write_uint32(buf, fog['flags'])
        _write_vec3d(buf, fog['position'])
        _write_float32(buf, fog['small_radius'])
        _write_float32(buf, fog['big_radius'])
        _write_float32(buf, fog['end_dist'])
        _write_float32(buf, fog['start_factor'])
        _write_uint8(buf, tuple(fog['color1']), 4)
        _write_float32(buf, fog['end_dist2'])
        _write_float32(buf, fog['start_factor2'])
        _write_uint8(buf, tuple(fog['color2']), 4)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MFOG', len(raw))
    f.write(raw)


def _write_mcvp(f, data):
    from io import BytesIO
    buf = BytesIO()
    for plane in data:
        _write_float32(buf, tuple(plane), 4)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MCVP', len(raw))
    f.write(raw)


# ---------------------------------------------------------------------------
# GROUP CHUNK WRITERS
# ---------------------------------------------------------------------------

def _write_mogp(f, data, sub_chunks_data):
    """Write MOGP header + all sub-chunk data.
    The MOGP chunk size encompasses the header fields AND all sub-chunks.
    """
    from io import BytesIO

    # First write all sub-chunks into a buffer
    sub_buf = BytesIO()
    _write_group_sub_chunks(sub_buf, sub_chunks_data)
    sub_raw = sub_buf.getvalue()

    # MOGP header is 68 bytes of fields
    header_buf = BytesIO()
    _write_uint32(header_buf, data['group_name_ofs'])
    _write_uint32(header_buf, data['desc_group_name_ofs'])
    _write_uint32(header_buf, data['flags'])
    _write_vec3d(header_buf, data['bounding_box_corner1'])
    _write_vec3d(header_buf, data['bounding_box_corner2'])
    _write_uint16(header_buf, data['portal_start'])
    _write_uint16(header_buf, data['portal_count'])
    _write_uint16(header_buf, data['n_batches_a'])
    _write_uint16(header_buf, data['n_batches_b'])
    _write_uint16(header_buf, data['n_batches_c'])
    _write_uint16(header_buf, data['n_batches_d'])
    _write_uint8(header_buf, tuple(data['fog_indices']), 4)
    _write_uint32(header_buf, data['liquid_type'])
    _write_uint32(header_buf, data['group_id'])
    _write_uint32(header_buf, data['unknown1'])
    _write_uint32(header_buf, data['unknown2'])
    header_raw = header_buf.getvalue()

    total_size = len(header_raw) + len(sub_raw)
    _write_chunk_header(f, 'MOGP', total_size)
    f.write(header_raw)
    f.write(sub_raw)


def _write_mopy(f, data):
    from io import BytesIO
    buf = BytesIO()
    for m in data:
        _write_uint8(buf, m['flags'])
        _write_uint8(buf, m['material_id'])
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOPY', len(raw))
    f.write(raw)


def _write_movi(f, data):
    from io import BytesIO
    buf = BytesIO()
    for idx in data:
        _write_uint16(buf, idx)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOVI', len(raw))
    f.write(raw)


def _write_movt(f, data):
    from io import BytesIO
    buf = BytesIO()
    for v in data:
        _write_vec3d(buf, v)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOVT', len(raw))
    f.write(raw)


def _write_monr(f, data):
    from io import BytesIO
    buf = BytesIO()
    for n in data:
        _write_vec3d(buf, n)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MONR', len(raw))
    f.write(raw)


def _write_motv_group(f, data):
    from io import BytesIO
    buf = BytesIO()
    for uv in data:
        _write_vec2d(buf, uv)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOTV', len(raw))
    f.write(raw)


def _write_moba(f, data):
    from io import BytesIO
    buf = BytesIO()
    for b in data:
        _write_int16(buf, tuple(b['bounding_box']), 6)
        _write_uint32(buf, b['start_triangle'])
        _write_uint16(buf, b['n_triangles'])
        _write_uint16(buf, b['start_vertex'])
        _write_uint16(buf, b['last_vertex'])
        _write_uint8(buf, b['unknown'])
        _write_uint8(buf, b['material_id'])
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOBA', len(raw))
    f.write(raw)


def _write_molr_group(f, data):
    from io import BytesIO
    buf = BytesIO()
    for ref in data:
        _write_int16(buf, ref)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOLR', len(raw))
    f.write(raw)


def _write_modr_group(f, data):
    from io import BytesIO
    buf = BytesIO()
    for ref in data:
        _write_int16(buf, ref)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MODR', len(raw))
    f.write(raw)


def _write_mobn(f, data):
    from io import BytesIO
    buf = BytesIO()
    for node in data:
        _write_int16(buf, node['plane_type'])
        _write_int16(buf, tuple(node['children']), 2)
        _write_uint16(buf, node['num_faces'])
        _write_uint32(buf, node['first_face'])
        _write_float32(buf, node['dist'])
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOBN', len(raw))
    f.write(raw)


def _write_mobr(f, data):
    from io import BytesIO
    buf = BytesIO()
    for face in data:
        _write_uint16(buf, face)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOBR', len(raw))
    f.write(raw)


def _write_mocv(f, data):
    from io import BytesIO
    buf = BytesIO()
    for color in data:
        _write_uint8(buf, tuple(color), 4)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MOCV', len(raw))
    f.write(raw)


def _write_mliq(f, data):
    from io import BytesIO
    buf = BytesIO()
    _write_uint32(buf, data['x_verts'])
    _write_uint32(buf, data['y_verts'])
    _write_uint32(buf, data['x_tiles'])
    _write_uint32(buf, data['y_tiles'])
    _write_vec3d(buf, data['position'])
    _write_uint16(buf, data['material_id'])
    for vtx in data['vertex_map']:
        # Write water interpretation (flow bytes)
        _write_uint8(buf, vtx['flow1'])
        _write_uint8(buf, vtx['flow2'])
        _write_uint8(buf, vtx['flow1_pct'])
        _write_uint8(buf, vtx['filler'])
        _write_float32(buf, vtx['height'])
    for tf in data['tile_flags']:
        _write_uint8(buf, tf)
    raw = buf.getvalue()
    _write_chunk_header(f, 'MLIQ', len(raw))
    f.write(raw)


def _write_raw_chunk(f, magic, data):
    """Write a raw/unknown chunk from hex data."""
    raw = bytes.fromhex(data['_hex'])
    _write_chunk_header(f, magic, len(raw))
    f.write(raw)


def _write_group_sub_chunks(f, chunks_data):
    """Write all sub-chunks inside a MOGP."""
    # Ordered list of known group sub-chunks
    ordered_chunks = [
        'MOPY', 'MOVI', 'MOVT', 'MONR', 'MOTV', 'MOBA',
        'MOLR', 'MODR', 'MOBN', 'MOBR', 'MOCV', 'MLIQ',
    ]

    group_writers = {
        'MOPY': _write_mopy,
        'MOVI': _write_movi,
        'MOVT': _write_movt,
        'MONR': _write_monr,
        'MOTV': _write_motv_group,
        'MOBA': _write_moba,
        'MOLR': _write_molr_group,
        'MODR': _write_modr_group,
        'MOBN': _write_mobn,
        'MOBR': _write_mobr,
        'MOCV': _write_mocv,
        'MLIQ': _write_mliq,
    }

    for chunk_name in ordered_chunks:
        if chunk_name in chunks_data:
            chunk_val = chunks_data[chunk_name]
            if chunk_val is not None and chunk_val != [] and chunk_val != {}:
                group_writers[chunk_name](f, chunk_val)

    # Write MOTV2 / MOCV2 if present
    if 'MOTV2' in chunks_data and chunks_data['MOTV2']:
        _write_motv_group(f, chunks_data['MOTV2'])
    if 'MOCV2' in chunks_data and chunks_data['MOCV2']:
        _write_mocv(f, chunks_data['MOCV2'])

    # Write any unknown/raw chunks
    for key, val in chunks_data.items():
        if key not in ordered_chunks and key not in ('MOTV2', 'MOCV2'):
            if isinstance(val, dict) and '_hex' in val:
                _write_raw_chunk(f, key, val)


# ---------------------------------------------------------------------------
# WMO ROOT: read / write
# ---------------------------------------------------------------------------

def read_wmo_root(filepath):
    """Parse a WMO root file into a JSON-serializable dict."""
    chunks = {}
    chunk_order = []

    with open(filepath, 'rb') as f:
        while True:
            magic, size = _read_chunk_header(f)
            if magic is None:
                break

            parser = ROOT_PARSERS.get(magic)
            if parser:
                chunks[magic] = parser(f, size)
            else:
                # Unknown chunk - store raw
                chunks[magic] = _parse_raw(f, size)

            chunk_order.append(magic)

    # Resolve texture names in materials
    tex_lookup = {}
    if 'MOTX' in chunks:
        for entry in chunks['MOTX']['strings']:
            tex_lookup[entry['offset']] = entry['string']

    if 'MOMT' in chunks:
        for mat in chunks['MOMT']:
            mat['texture1'] = tex_lookup.get(mat['texture1_ofs'], '')
            mat['texture2'] = tex_lookup.get(mat['texture2_ofs'], '')
            mat['texture3'] = tex_lookup.get(mat['texture3_ofs'], '')

    # Resolve group names in group info
    grp_lookup = {}
    if 'MOGN' in chunks:
        for entry in chunks['MOGN']['strings']:
            grp_lookup[entry['offset']] = entry['string']

    if 'MOGI' in chunks:
        for info in chunks['MOGI']:
            info['name'] = grp_lookup.get(info['name_ofs'], '')

    # Resolve doodad names in definitions
    doodad_lookup = {}
    if 'MODN' in chunks:
        for entry in chunks['MODN']['strings']:
            doodad_lookup[entry['offset']] = entry['string']

    if 'MODD' in chunks:
        for d in chunks['MODD']:
            d['name'] = doodad_lookup.get(d['name_ofs'], '')

    result = {
        '_meta': {
            'type': 'wmo_root',
            'filename': os.path.basename(filepath),
            'chunk_order': chunk_order,
        },
    }

    # Add chunks in order
    for magic in chunk_order:
        result[magic] = chunks[magic]

    return result


def write_wmo_root(data, filepath):
    """Write a WMO root JSON dict back to a binary file."""
    root_writers = {
        'MVER': _write_mver,
        'MOHD': _write_mohd,
        'MOTX': _write_motx,
        'MOMT': _write_momt,
        'MOGN': _write_mogn,
        'MOGI': _write_mogi,
        'MOSB': _write_mosb,
        'MOPV': _write_mopv,
        'MOPT': _write_mopt,
        'MOPR': _write_mopr,
        'MOVV': _write_movv,
        'MOVB': _write_movb,
        'MOLT': _write_molt,
        'MODS': _write_mods,
        'MODN': _write_modn,
        'MODD': _write_modd,
        'MFOG': _write_mfog,
        'MCVP': _write_mcvp,
    }

    chunk_order = data['_meta']['chunk_order']

    with open(filepath, 'wb') as f:
        for magic in chunk_order:
            if magic not in data:
                continue
            chunk_data = data[magic]
            writer = root_writers.get(magic)
            if writer:
                writer(f, chunk_data)
            elif isinstance(chunk_data, dict) and '_hex' in chunk_data:
                _write_raw_chunk(f, magic, chunk_data)


# ---------------------------------------------------------------------------
# WMO GROUP: read / write
# ---------------------------------------------------------------------------

def read_wmo_group(filepath):
    """Parse a WMO group file into a JSON-serializable dict."""
    chunks = {}
    chunk_order = []
    motv_count = 0
    mocv_count = 0

    with open(filepath, 'rb') as f:
        while True:
            magic, size = _read_chunk_header(f)
            if magic is None:
                break

            # Handle MOGP specially: it contains a header + sub-chunks
            if magic == 'MOGP':
                mogp_end = f.tell() + size
                # Parse the 68-byte header
                chunks['MOGP'] = _parse_mogp(f, 68)
                chunk_order.append('MOGP')

                # Parse sub-chunks within the MOGP body
                while f.tell() < mogp_end:
                    sub_magic, sub_size = _read_chunk_header(f)
                    if sub_magic is None:
                        break

                    # Handle duplicate MOTV/MOCV chunks
                    actual_key = sub_magic
                    if sub_magic == 'MOTV':
                        motv_count += 1
                        if motv_count > 1:
                            actual_key = 'MOTV2'
                    elif sub_magic == 'MOCV':
                        mocv_count += 1
                        if mocv_count > 1:
                            actual_key = 'MOCV2'

                    parser = GROUP_PARSERS.get(sub_magic)
                    if parser:
                        chunks[actual_key] = parser(f, sub_size)
                    else:
                        chunks[actual_key] = _parse_raw(f, sub_size)
                    chunk_order.append(actual_key)

                continue

            # Non-MOGP chunks (MVER at the start)
            parser = GROUP_PARSERS.get(magic)
            if not parser:
                parser = ROOT_PARSERS.get(magic)
            if parser:
                chunks[magic] = parser(f, size)
            else:
                chunks[magic] = _parse_raw(f, size)
            chunk_order.append(magic)

    result = {
        '_meta': {
            'type': 'wmo_group',
            'filename': os.path.basename(filepath),
            'chunk_order': chunk_order,
        },
    }

    for key in chunk_order:
        result[key] = chunks[key]

    return result


def write_wmo_group(data, filepath):
    """Write a WMO group JSON dict back to a binary file."""
    chunk_order = data['_meta']['chunk_order']

    # Separate MVER from the rest; MOGP wraps all sub-chunks
    sub_chunk_keys = [k for k in chunk_order if k not in ('MVER', 'MOGP')]

    with open(filepath, 'wb') as f:
        # Write MVER
        if 'MVER' in data:
            _write_mver(f, data['MVER'])

        # Write MOGP with all sub-chunks
        if 'MOGP' in data:
            sub_chunks_data = {}
            for key in sub_chunk_keys:
                if key in data:
                    sub_chunks_data[key] = data[key]
            _write_mogp(f, data['MOGP'], sub_chunks_data)


# ---------------------------------------------------------------------------
# AUTO-DETECTION
# ---------------------------------------------------------------------------

def detect_wmo_type(filepath):
    """Detect whether a file is a WMO root or group file.
    Returns 'root', 'group', or 'unknown'.
    """
    with open(filepath, 'rb') as f:
        # Read through chunks looking for MOHD (root) or MOGP (group)
        while True:
            magic, size = _read_chunk_header(f)
            if magic is None:
                break
            if magic == 'MOHD':
                return 'root'
            if magic == 'MOGP':
                return 'group'
            f.seek(size, 1)  # skip chunk data
    return 'unknown'


# ---------------------------------------------------------------------------
# PUBLIC CONVERSION API
# ---------------------------------------------------------------------------

def wmo_to_json(wmo_path):
    """Convert a WMO file (root or group) to a JSON-serializable dict."""
    wmo_type = detect_wmo_type(wmo_path)
    if wmo_type == 'root':
        return read_wmo_root(wmo_path)
    elif wmo_type == 'group':
        return read_wmo_group(wmo_path)
    else:
        raise ValueError("Cannot detect WMO type for: {}".format(wmo_path))


def json_to_wmo(json_data, output_path):
    """Convert a JSON dict back to a binary WMO file."""
    wmo_type = json_data['_meta']['type']
    if wmo_type == 'wmo_root':
        write_wmo_root(json_data, output_path)
    elif wmo_type == 'wmo_group':
        write_wmo_group(json_data, output_path)
    else:
        raise ValueError("Unknown WMO type in JSON: {}".format(wmo_type))


def convert_directory(wmo_dir, output_dir):
    """Batch-convert all .wmo files in a directory to JSON."""
    os.makedirs(output_dir, exist_ok=True)

    results = {'converted': [], 'failed': []}

    for filename in sorted(os.listdir(wmo_dir)):
        if not filename.lower().endswith('.wmo'):
            continue

        wmo_path = os.path.join(wmo_dir, filename)
        json_name = os.path.splitext(filename)[0] + '.json'
        json_path = os.path.join(output_dir, json_name)

        try:
            data = wmo_to_json(wmo_path)
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            wmo_type = data['_meta']['type']
            results['converted'].append({
                'file': filename,
                'type': wmo_type,
                'chunks': len(data['_meta']['chunk_order']),
            })
            print("  OK  {:50s} {:>10s}  ({} chunks)".format(
                filename, wmo_type, len(data['_meta']['chunk_order'])))
        except Exception as e:
            results['failed'].append({'file': filename, 'error': str(e)})
            print("  FAIL  {:50s} -- {}".format(filename, e))

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='WMO <-> JSON converter for World of Warcraft WMO files')
    subparsers = parser.add_subparsers(dest='command')

    # -- wmo2json --
    p_w2j = subparsers.add_parser('wmo2json', help='Convert WMO to JSON')
    p_w2j.add_argument('input', nargs='?', help='Input .wmo file')
    p_w2j.add_argument('-o', '--output', help='Output .json file (or directory with --dir)')
    p_w2j.add_argument('--dir', help='Batch-convert all .wmo files in a directory')

    # -- json2wmo --
    p_j2w = subparsers.add_parser('json2wmo', help='Convert JSON back to WMO')
    p_j2w.add_argument('input', help='Input .json file')
    p_j2w.add_argument('-o', '--output', help='Output .wmo file')

    args = parser.parse_args()

    if args.command == 'wmo2json':
        if args.dir:
            output_dir = args.output or os.path.join(args.dir, 'json')
            print("Converting all .wmo files in: {}".format(args.dir))
            print("Output directory: {}\n".format(output_dir))
            results = convert_directory(args.dir, output_dir)
            roots = sum(1 for r in results['converted'] if r['type'] == 'wmo_root')
            groups = sum(1 for r in results['converted'] if r['type'] == 'wmo_group')
            print("\n{} converted ({} root, {} group), {} failed".format(
                len(results['converted']), roots, groups, len(results['failed'])))
        elif args.input:
            output = args.output or os.path.splitext(args.input)[0] + '.json'
            data = wmo_to_json(args.input)
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print("{} -> {} (type: {}, {} chunks)".format(
                args.input, output,
                data['_meta']['type'],
                len(data['_meta']['chunk_order'])))
        else:
            p_w2j.print_help()

    elif args.command == 'json2wmo':
        with open(args.input, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        output = args.output or os.path.splitext(args.input)[0] + '.wmo'
        json_to_wmo(json_data, output)
        print("{} -> {} (type: {})".format(
            args.input, output, json_data['_meta']['type']))

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
