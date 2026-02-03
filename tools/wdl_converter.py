#!/usr/bin/env python
"""
WDL <-> JSON bidirectional converter for WoW 3.3.5a (WotLK) WDL files.

WDL (World Data Low-res) files contain low-resolution terrain heightmaps
used for the flight-view camera in WoW. Each file covers a 64x64 tile grid
with an outer 17x17 and inner 16x16 heightmap per active tile.

Chunks (magics reversed in binary per WoW convention):
  MVER - File version (uint32, should be 18)
  MWMO - WMO name strings (null-terminated, often absent)
  MWID - WMO file data IDs (uint32 array, often absent)
  MODF - WMO placement entries (64 bytes each, often absent)
  MAOF - Map area offset table: 64x64 uint32 offsets to MARE chunks
  MARE - Map area heightmap: outer 17x17 int16 + inner 16x16 int16
  MAHO - Map area hole mask: 16 x uint16 (32 bytes), follows each MARE

Usage:
  python wdl_converter.py wdl2json <input.wdl> [-o output.json]
  python wdl_converter.py json2wdl <input.json> [-o output.wdl]
  python wdl_converter.py wdl2json --dir <wdl_dir> [-o output_dir]
"""

import struct
import json
import os
import sys
import argparse
from io import BytesIO

# ---------------------------------------------------------------------------
# Chunk magics (reversed per WoW convention)
# ---------------------------------------------------------------------------
_MAGIC_MVER = b'REVM'
_MAGIC_MWMO = b'OMWM'
_MAGIC_MWID = b'DIWM'
_MAGIC_MODF = b'FDOM'
_MAGIC_MAOF = b'FOAM'
_MAGIC_MARE = b'ERAM'
_MAGIC_MAHO = b'OHAM'

# Grid dimensions
_GRID_SIZE = 64
_GRID_TOTAL = _GRID_SIZE * _GRID_SIZE  # 4096

# MARE heightmap dimensions
_OUTER_ROWS = 17
_OUTER_COLS = 17
_OUTER_COUNT = _OUTER_ROWS * _OUTER_COLS  # 289
_INNER_ROWS = 16
_INNER_COLS = 16
_INNER_COUNT = _INNER_ROWS * _INNER_COLS  # 256
_MARE_DATA_SIZE = (_OUTER_COUNT + _INNER_COUNT) * 2  # 1090 bytes

# MAHO hole mask
_MAHO_DATA_SIZE = 32  # 16 x uint16

# MODF entry size
_MODF_ENTRY_SIZE = 64

# Expected WDL version
_WDL_VERSION = 18


# ===================================================================
# Reading helpers
# ===================================================================

def _read_chunk_header(data, pos):
    """Read a chunk header at position. Returns (magic, size, data_start)."""
    if pos + 8 > len(data):
        return None, 0, pos
    magic = data[pos:pos + 4]
    size = struct.unpack_from('<I', data, pos + 4)[0]
    return magic, size, pos + 8


def _read_null_terminated_strings(raw_bytes):
    """Split a block of null-terminated strings into a list."""
    if not raw_bytes:
        return []
    strings = []
    current = bytearray()
    for b in raw_bytes:
        if b == 0:
            if current:
                strings.append(current.decode('utf-8', errors='replace'))
                current = bytearray()
        else:
            current.append(b)
    if current:
        strings.append(current.decode('utf-8', errors='replace'))
    return strings


def _read_modf_entry(data, offset):
    """Parse one 64-byte MODF (WMO placement) entry."""
    vals = struct.unpack_from('<II3f3f6f4H', data, offset)
    return {
        'name_id': vals[0],
        'unique_id': vals[1],
        'position': list(vals[2:5]),
        'rotation': list(vals[5:8]),
        'extent_lo': list(vals[8:11]),
        'extent_hi': list(vals[11:14]),
        'flags': vals[14],
        'doodad_set': vals[15],
        'name_set': vals[16],
        'scale': vals[17],
    }


def _read_mare(data, offset):
    """Read a MARE chunk at the given offset. Returns (outer, inner) arrays."""
    magic, size, data_start = _read_chunk_header(data, offset)
    if magic != _MAGIC_MARE:
        return None, None
    if size < _MARE_DATA_SIZE:
        return None, None

    outer_raw = struct.unpack_from('<{}h'.format(_OUTER_COUNT), data, data_start)
    inner_raw = struct.unpack_from('<{}h'.format(_INNER_COUNT), data,
                                   data_start + _OUTER_COUNT * 2)

    # Convert to 2D arrays (row-major)
    outer = []
    for r in range(_OUTER_ROWS):
        start = r * _OUTER_COLS
        outer.append(list(outer_raw[start:start + _OUTER_COLS]))

    inner = []
    for r in range(_INNER_ROWS):
        start = r * _INNER_COLS
        inner.append(list(inner_raw[start:start + _INNER_COLS]))

    return outer, inner


def _read_maho(data, offset):
    """Read a MAHO chunk at offset, return list of 16 uint16 hole masks."""
    magic, size, data_start = _read_chunk_header(data, offset)
    if magic != _MAGIC_MAHO:
        return None
    if size < _MAHO_DATA_SIZE:
        return None
    return list(struct.unpack_from('<16H', data, data_start))


# ===================================================================
# WDL -> JSON
# ===================================================================

def wdl_to_json(wdl_path):
    """Parse a WDL binary file and return a JSON-serialisable dict."""
    with open(wdl_path, 'rb') as f:
        data = f.read()

    filename = os.path.basename(wdl_path)
    result = {
        '_meta': {
            'filename': filename,
            'file_size': len(data),
            'version': None,
            'chunks': [],
        },
        'version': None,
        'wmo_names': [],
        'wmo_ids': [],
        'wmo_placements': [],
        'tiles': {},
        'holes': {},
    }

    # First pass: read all top-level chunks and build summary
    pos = 0
    maof_offsets = None

    while pos + 8 <= len(data):
        magic, size, data_start = _read_chunk_header(data, pos)
        if magic is None:
            break

        readable = magic[::-1].decode('ascii', errors='replace')
        result['_meta']['chunks'].append({
            'magic': readable,
            'offset': pos,
            'size': size,
        })

        if magic == _MAGIC_MVER:
            version = struct.unpack_from('<I', data, data_start)[0]
            result['version'] = version
            result['_meta']['version'] = version

        elif magic == _MAGIC_MWMO:
            raw = data[data_start:data_start + size]
            result['wmo_names'] = _read_null_terminated_strings(raw)

        elif magic == _MAGIC_MWID:
            count = size // 4
            if count > 0:
                result['wmo_ids'] = list(
                    struct.unpack_from('<{}I'.format(count), data, data_start))

        elif magic == _MAGIC_MODF:
            count = size // _MODF_ENTRY_SIZE
            placements = []
            for i in range(count):
                entry = _read_modf_entry(data, data_start + i * _MODF_ENTRY_SIZE)
                placements.append(entry)
            result['wmo_placements'] = placements

        elif magic == _MAGIC_MAOF:
            maof_offsets = list(
                struct.unpack_from('<{}I'.format(_GRID_TOTAL), data, data_start))

        # MARE and MAHO are parsed below via MAOF offsets
        pos = data_start + size

    # Second pass: use MAOF offsets to read MARE/MAHO per tile
    if maof_offsets is not None:
        tile_count = 0
        for idx, offset in enumerate(maof_offsets):
            if offset == 0:
                continue

            y = idx // _GRID_SIZE
            x = idx % _GRID_SIZE
            key = "{}_{}".format(x, y)

            outer, inner = _read_mare(data, offset)
            if outer is None:
                continue

            result['tiles'][key] = {
                'x': x,
                'y': y,
                'outer': outer,
                'inner': inner,
            }
            tile_count += 1

            # Check for MAHO immediately after MARE
            mare_magic, mare_size, mare_data_start = _read_chunk_header(data, offset)
            maho_offset = mare_data_start + mare_size
            if maho_offset + 8 <= len(data):
                hole_mask = _read_maho(data, maho_offset)
                if hole_mask is not None:
                    # Only store non-zero hole masks
                    if any(v != 0 for v in hole_mask):
                        result['holes'][key] = hole_mask

        result['_meta']['tile_count'] = tile_count

    # Remove empty optional sections for cleaner output
    if not result['wmo_names']:
        del result['wmo_names']
    if not result['wmo_ids']:
        del result['wmo_ids']
    if not result['wmo_placements']:
        del result['wmo_placements']
    if not result['holes']:
        del result['holes']

    return result


# ===================================================================
# JSON -> WDL
# ===================================================================

def _write_chunk(buf, magic, chunk_data):
    """Write a complete chunk (header + data) to a BytesIO buffer."""
    buf.write(magic)
    buf.write(struct.pack('<I', len(chunk_data)))
    buf.write(chunk_data)


def _build_null_terminated_block(strings):
    """Build a null-terminated string block from a list of strings."""
    if not strings:
        return b''
    parts = []
    for s in strings:
        parts.append(s.encode('utf-8') + b'\x00')
    return b''.join(parts)


def _build_modf_entry(entry):
    """Pack one MODF entry into 64 bytes."""
    pos = entry['position']
    rot = entry['rotation']
    ext_lo = entry['extent_lo']
    ext_hi = entry['extent_hi']
    return struct.pack('<II3f3f6f4H',
                       entry['name_id'], entry['unique_id'],
                       pos[0], pos[1], pos[2],
                       rot[0], rot[1], rot[2],
                       ext_lo[0], ext_lo[1], ext_lo[2],
                       ext_hi[0], ext_hi[1], ext_hi[2],
                       entry['flags'], entry['doodad_set'],
                       entry['name_set'], entry['scale'])


def _build_mare_data(tile):
    """Build 1090-byte MARE data from tile outer/inner arrays."""
    outer = tile['outer']
    inner = tile['inner']

    outer_flat = []
    for row in outer:
        outer_flat.extend(row)

    inner_flat = []
    for row in inner:
        inner_flat.extend(row)

    return (struct.pack('<{}h'.format(_OUTER_COUNT), *outer_flat) +
            struct.pack('<{}h'.format(_INNER_COUNT), *inner_flat))


def json_to_wdl(json_data, output_path):
    """Convert a JSON dict (as produced by wdl_to_json) back to a WDL file."""
    buf = BytesIO()

    version = json_data.get('version', _WDL_VERSION)

    # 1. MVER
    _write_chunk(buf, _MAGIC_MVER, struct.pack('<I', version))

    # 2. MWMO (optional)
    wmo_names = json_data.get('wmo_names', [])
    if wmo_names:
        _write_chunk(buf, _MAGIC_MWMO, _build_null_terminated_block(wmo_names))

    # 3. MWID (optional)
    wmo_ids = json_data.get('wmo_ids', [])
    if wmo_ids:
        _write_chunk(buf, _MAGIC_MWID,
                     struct.pack('<{}I'.format(len(wmo_ids)), *wmo_ids))

    # 4. MODF (optional)
    wmo_placements = json_data.get('wmo_placements', [])
    if wmo_placements:
        modf_data = b''.join(_build_modf_entry(e) for e in wmo_placements)
        _write_chunk(buf, _MAGIC_MODF, modf_data)

    # 5. MAOF - placeholder, will be filled after writing MARE/MAHO
    maof_pos = buf.tell()
    maof_data = bytearray(_GRID_TOTAL * 4)
    _write_chunk(buf, _MAGIC_MAOF, bytes(maof_data))

    # 6. MARE + MAHO per tile
    tiles = json_data.get('tiles', {})
    holes = json_data.get('holes', {})

    # Sort tiles by grid index for deterministic output
    tile_keys_sorted = sorted(tiles.keys(),
                              key=lambda k: (tiles[k]['y'], tiles[k]['x']))

    offsets = {}
    for key in tile_keys_sorted:
        tile = tiles[key]
        x = tile['x']
        y = tile['y']
        idx = y * _GRID_SIZE + x

        # Record the offset where MARE chunk starts
        offsets[idx] = buf.tell()

        # Write MARE
        mare_data = _build_mare_data(tile)
        _write_chunk(buf, _MAGIC_MARE, mare_data)

        # Write MAHO (always present in original files, zeros if no holes)
        hole_mask = holes.get(key, [0] * 16)
        maho_data = struct.pack('<16H', *hole_mask)
        _write_chunk(buf, _MAGIC_MAHO, maho_data)

    # 7. Go back and fill in MAOF offsets
    for idx, offset in offsets.items():
        struct.pack_into('<I', maof_data, idx * 4, offset)

    # Rewrite MAOF chunk data (skip header = magic + size = 8 bytes)
    current_pos = buf.tell()
    buf.seek(maof_pos + 8)  # skip MAOF chunk header
    buf.write(bytes(maof_data))
    buf.seek(current_pos)

    # Write output
    result_data = buf.getvalue()
    with open(output_path, 'wb') as f:
        f.write(result_data)

    return len(tiles)


# ===================================================================
# Batch conversion
# ===================================================================

def convert_directory(wdl_dir, output_dir):
    """Batch-convert every .wdl file in wdl_dir to JSON in output_dir."""
    os.makedirs(output_dir, exist_ok=True)
    results = {'converted': [], 'failed': []}

    for filename in sorted(os.listdir(wdl_dir)):
        if not filename.lower().endswith('.wdl'):
            continue

        wdl_path = os.path.join(wdl_dir, filename)
        json_name = os.path.splitext(filename)[0] + '.json'
        json_path = os.path.join(output_dir, json_name)

        try:
            data = wdl_to_json(wdl_path)
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            tile_count = data['_meta'].get('tile_count', 0)
            results['converted'].append({
                'file': filename,
                'tiles': tile_count,
                'version': data.get('version'),
            })
            print("  OK  {:40s} {:>4} tiles".format(filename, tile_count))
        except Exception as e:
            results['failed'].append({'file': filename, 'error': str(e)})
            print("  FAIL  {:40s} -- {}".format(filename, e))

    return results


# ===================================================================
# CLI
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description='WDL <-> JSON converter for WoW 3.3.5a (WotLK) WDL files')
    subparsers = parser.add_subparsers(dest='command')

    # -- wdl2json -------------------------------------------------------
    p_w2j = subparsers.add_parser('wdl2json', help='Convert WDL to JSON')
    p_w2j.add_argument('input', nargs='?', help='Input .wdl file')
    p_w2j.add_argument('-o', '--output',
                       help='Output .json file (or directory with --dir)')
    p_w2j.add_argument('--dir',
                       help='Batch-convert all .wdl files in a directory')

    # -- json2wdl -------------------------------------------------------
    p_j2w = subparsers.add_parser('json2wdl', help='Convert JSON back to WDL')
    p_j2w.add_argument('input', help='Input .json file')
    p_j2w.add_argument('-o', '--output', help='Output .wdl file')

    args = parser.parse_args()

    if args.command == 'wdl2json':
        if args.dir:
            output_dir = args.output or os.path.join(args.dir, 'json')
            print("Converting all .wdl files in: {}".format(args.dir))
            print("Output directory: {}\n".format(output_dir))
            results = convert_directory(args.dir, output_dir)
            print("\n{} converted, {} failed".format(
                len(results['converted']), len(results['failed'])))
        elif args.input:
            output = args.output or os.path.splitext(args.input)[0] + '.json'
            data = wdl_to_json(args.input)
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tile_count = data['_meta'].get('tile_count', 0)
            print("{} -> {} ({} tiles, version {})".format(
                args.input, output, tile_count, data.get('version')))
        else:
            p_w2j.print_help()

    elif args.command == 'json2wdl':
        with open(args.input, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        output = args.output or os.path.splitext(args.input)[0] + '.wdl'
        count = json_to_wdl(json_data, output)
        print("{} -> {} ({} tiles)".format(args.input, output, count))

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
