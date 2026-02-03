#!/usr/bin/env python
"""
DBC <-> JSON bidirectional converter for WoW 3.3.5a (WotLK) WDBC files.

Converts binary DBC files to human-readable JSON and back.
Uses DBD schema definitions (when available) for named fields and
type-aware decoding (int8/16/32, float, string, locstring).

Usage:
  python dbc_converter.py dbc2json <input.dbc> [-o output.json]
  python dbc_converter.py json2dbc <input.json> [-o output.dbc]
  python dbc_converter.py dbc2json --dir <dbc_dir> [-o output_dir]
"""

import struct
import json
import os
import sys
import math
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from world_builder.dbc_injector import DBCInjector

# ---------------------------------------------------------------------------
# WotLK locstring layout: 16 locale slots + 1 flags word = 17 uint32
# ---------------------------------------------------------------------------
_LOC_SLOT_COUNT = 17
_LOC_BYTE_SIZE = _LOC_SLOT_COUNT * 4  # 68 bytes
_LOC_LOCALES = [
    'enUS', 'koKR', 'frFR', 'deDE', 'enCN', 'enTW', 'esES', 'esMX',
    'ruRU', 'jaJP', 'ptPT', 'itIT', 'unk_12', 'unk_13', 'unk_14', 'unk_15',
]

# struct format strings and sizes for each scalar type
_SCALAR_FMT = {
    'int8': ('<b', 1), 'uint8': ('<B', 1),
    'int16': ('<h', 2), 'uint16': ('<H', 2),
    'int32': ('<i', 4), 'uint32': ('<I', 4),
    'float': ('<f', 4),
    'string': ('<I', 4),  # stored as uint32 offset into string block
}

# ---------------------------------------------------------------------------
# Try loading the DBD parser for schema-aware conversion
# ---------------------------------------------------------------------------
try:
    from wdbx.dbd_parser import parse_dbd_file, build_version_raw
    _HAS_DBD = True
except ImportError:
    _HAS_DBD = False


# ===================================================================
# Schema resolution
# ===================================================================

def _dbc_name_from_path(filepath):
    """Extract DBC table name from file path ('AreaTable.dbc' -> 'AreaTable')."""
    return os.path.splitext(os.path.basename(filepath))[0]


def _int_type_name(is_unsigned, byte_width):
    """Map (is_unsigned, byte_width) to a type name like 'uint8'."""
    prefix = 'u' if is_unsigned else ''
    bits = byte_width * 8
    return '{}int{}'.format(prefix, bits)


def _resolve_schema(dbc_name, build='3.3.5.12340'):
    """
    Resolve field schema from a .dbd definition file.

    Returns a list of logical fields, each with byte-level offsets::

        [{'name': str, 'type': str, 'byte_offset': int, 'byte_size': int,
          'elem_size': int, 'count': int}, ...]

    Types: 'uint8', 'int8', 'uint16', 'int16', 'uint32', 'int32',
           'float', 'string', 'locstring'
    Arrays have count > 1.
    Returns None when no DBD or no matching build definition is available.
    """
    if not _HAS_DBD:
        return None

    dbd_dir = os.path.join(PROJECT_ROOT, 'wdbx', 'dbd', 'definitions')
    dbd_path = os.path.join(dbd_dir, '{}.dbd'.format(dbc_name))

    if not os.path.isfile(dbd_path):
        return None

    try:
        dbd = parse_dbd_file(dbd_path)
    except Exception:
        return None

    # Find the build-matching definition
    target = build_version_raw(*(int(s) for s in build.split('.')))
    definition = None
    for _def in dbd.definitions:
        for _build in _def.builds:
            if not isinstance(_build, tuple):
                if str(_build) == build:
                    definition = _def
                    break
            elif _build[0] <= target <= _build[1]:
                definition = _def
                break
        else:
            continue
        break

    if definition is None:
        return None

    # Column name -> base type name
    columns = {col.name: col.type for col in dbd.columns}

    fields = []
    byte_offset = 0

    for entry in definition.entries:
        col_type = columns.get(entry.column, 'int')
        array_size = entry.array_size or 1

        if col_type == 'locstring':
            for i in range(array_size):
                name = entry.column if array_size == 1 else '{}[{}]'.format(entry.column, i)
                fields.append({
                    'name': name,
                    'type': 'locstring',
                    'byte_offset': byte_offset,
                    'byte_size': _LOC_BYTE_SIZE,
                    'elem_size': _LOC_BYTE_SIZE,
                    'count': 1,
                })
                byte_offset += _LOC_BYTE_SIZE

        elif col_type == 'string':
            elem_size = 4  # always a uint32 offset
            for i in range(array_size):
                name = entry.column if array_size == 1 else '{}[{}]'.format(entry.column, i)
                fields.append({
                    'name': name,
                    'type': 'string',
                    'byte_offset': byte_offset,
                    'byte_size': elem_size,
                    'elem_size': elem_size,
                    'count': 1,
                })
                byte_offset += elem_size

        elif col_type == 'float':
            elem_size = 4
            total = elem_size * array_size
            fields.append({
                'name': entry.column,
                'type': 'float',
                'byte_offset': byte_offset,
                'byte_size': total,
                'elem_size': elem_size,
                'count': array_size,
            })
            byte_offset += total

        else:  # int / uint
            # Determine byte width from int_width (bits) or default to 4
            if entry.int_width:
                elem_size = entry.int_width // 8
            else:
                elem_size = 4
            type_name = _int_type_name(entry.is_unsigned, elem_size)
            total = elem_size * array_size
            fields.append({
                'name': entry.column,
                'type': type_name,
                'byte_offset': byte_offset,
                'byte_size': total,
                'elem_size': elem_size,
                'count': array_size,
            })
            byte_offset += total

    return fields


def _fallback_schema(record_size):
    """Generate a generic schema treating the record as consecutive uint32 values."""
    count = record_size // 4
    fields = []
    for i in range(count):
        fields.append({
            'name': 'field_{}'.format(i),
            'type': 'uint32',
            'byte_offset': i * 4,
            'byte_size': 4,
            'elem_size': 4,
            'count': 1,
        })
    # Handle trailing bytes that don't fill a full uint32
    remainder = record_size % 4
    if remainder:
        fields.append({
            'name': 'field_{}_tail'.format(count),
            'type': 'uint8',
            'byte_offset': count * 4,
            'byte_size': remainder,
            'elem_size': 1,
            'count': remainder,
        })
    return fields


# ===================================================================
# Record reading / writing
# ===================================================================

def _safe_float(val):
    """Sanitise a float for JSON (NaN / Inf are not valid JSON)."""
    if math.isnan(val) or math.isinf(val):
        return 0.0
    return val


def _read_scalar(record_bytes, offset, type_name, dbc):
    """Read a single scalar value from *record_bytes* at *offset*."""
    if type_name == 'string':
        str_ofs = struct.unpack_from('<I', record_bytes, offset)[0]
        return dbc.get_string(str_ofs)
    if type_name == 'float':
        return _safe_float(struct.unpack_from('<f', record_bytes, offset)[0])
    fmt, _ = _SCALAR_FMT[type_name]
    return struct.unpack_from(fmt, record_bytes, offset)[0]


def _read_record(dbc, record_bytes, schema):
    """Decode one binary DBC record into a dict using *schema*."""
    result = {}

    for field in schema:
        offset = field['byte_offset']
        ftype = field['type']
        count = field['count']
        elem_size = field['elem_size']

        if ftype == 'locstring':
            locales = {}
            for i, locale_name in enumerate(_LOC_LOCALES):
                str_ofs = struct.unpack_from('<I', record_bytes, offset + i * 4)[0]
                locales[locale_name] = dbc.get_string(str_ofs)
            locales['_flags'] = struct.unpack_from('<I', record_bytes, offset + 16 * 4)[0]
            result[field['name']] = locales

        elif count > 1:
            result[field['name']] = [
                _read_scalar(record_bytes, offset + i * elem_size, ftype, dbc)
                for i in range(count)
            ]

        else:
            result[field['name']] = _read_scalar(record_bytes, offset, ftype, dbc)

    return result


def _write_scalar(buf, offset, type_name, value, string_adder):
    """Write a single scalar value into *buf* at *offset*."""
    if type_name == 'string':
        str_ofs = string_adder(value) if value else 0
        struct.pack_into('<I', buf, offset, str_ofs)
        return
    if type_name == 'float':
        struct.pack_into('<f', buf, offset, float(value))
        return
    fmt, _ = _SCALAR_FMT[type_name]
    struct.pack_into(fmt, buf, offset, int(value))


def _write_record(schema, record_dict, string_adder, record_size):
    """Encode a dict back into raw DBC record bytes."""
    buf = bytearray(record_size)

    for field in schema:
        offset = field['byte_offset']
        ftype = field['type']
        count = field['count']
        elem_size = field['elem_size']
        value = record_dict.get(field['name'])

        if value is None:
            continue

        if ftype == 'locstring':
            for i, locale_name in enumerate(_LOC_LOCALES):
                s = value.get(locale_name, '')
                str_ofs = string_adder(s) if s else 0
                struct.pack_into('<I', buf, offset + i * 4, str_ofs)
            flags = value.get('_flags', 0xFFFFFFFF)
            struct.pack_into('<I', buf, offset + 16 * 4, flags)

        elif count > 1:
            for i, val in enumerate(value):
                _write_scalar(buf, offset + i * elem_size, ftype, val, string_adder)

        else:
            _write_scalar(buf, offset, ftype, value, string_adder)

    return bytes(buf)


# ===================================================================
# Public conversion functions
# ===================================================================

def dbc_to_json(dbc_path, build='3.3.5.12340'):
    """Convert a DBC file to a JSON-serialisable dict."""
    dbc = DBCInjector(dbc_path)
    dbc_name = _dbc_name_from_path(dbc_path)

    # Resolve schema (prefer DBD, fall back to generic)
    schema = _resolve_schema(dbc_name, build)
    has_schema = schema is not None

    if has_schema:
        total_bytes = sum(f['byte_size'] for f in schema)
        if total_bytes != dbc.record_size:
            # Schema byte total doesn't match record size — fall back
            schema = None
            has_schema = False

    if not has_schema:
        schema = _fallback_schema(dbc.record_size)

    # Decode every record
    records = []
    for rec_bytes in dbc.records:
        records.append(_read_record(dbc, rec_bytes, schema))

    # Build portable schema description for the JSON
    schema_info = []
    for f in schema:
        entry = {'name': f['name'], 'type': f['type']}
        if f['count'] > 1 and f['type'] != 'locstring':
            entry['array_size'] = f['count']
        entry['byte_size'] = f['byte_size']
        schema_info.append(entry)

    return {
        '_meta': {
            'dbc_name': dbc_name,
            'build': build,
            'record_count': dbc.record_count,
            'field_count': dbc.field_count,
            'record_size': dbc.record_size,
            'has_named_schema': has_schema,
        },
        '_schema': schema_info,
        'records': records,
    }


def json_to_dbc(json_data, output_path):
    """Convert a JSON dict (as produced by *dbc_to_json*) back to a DBC file."""
    meta = json_data['_meta']
    schema_info = json_data['_schema']
    records_data = json_data['records']

    # Rebuild internal schema from the embedded _schema list
    schema = []
    byte_offset = 0
    for entry in schema_info:
        ftype = entry['type']
        byte_size = entry['byte_size']
        array_size = entry.get('array_size', None)

        if ftype == 'locstring':
            elem_size = _LOC_BYTE_SIZE
            count = 1
        elif array_size:
            elem_size = byte_size // array_size
            count = array_size
        else:
            elem_size = byte_size
            count = 1

        schema.append({
            'name': entry['name'],
            'type': ftype,
            'byte_offset': byte_offset,
            'byte_size': byte_size,
            'elem_size': elem_size,
            'count': count,
        })
        byte_offset += byte_size

    # Build the DBC
    dbc = DBCInjector()
    dbc.field_count = meta['field_count']
    dbc.record_size = meta['record_size']

    for rec_dict in records_data:
        rec_bytes = _write_record(schema, rec_dict, dbc.add_string, dbc.record_size)
        dbc.records.append(rec_bytes)

    dbc.write(output_path)
    return len(dbc.records)


def convert_directory(dbc_dir, output_dir, build='3.3.5.12340'):
    """Batch-convert every .dbc file in *dbc_dir* to JSON in *output_dir*."""
    os.makedirs(output_dir, exist_ok=True)

    results = {'converted': [], 'failed': []}

    for filename in sorted(os.listdir(dbc_dir)):
        if not filename.lower().endswith('.dbc'):
            continue

        dbc_path = os.path.join(dbc_dir, filename)
        json_name = os.path.splitext(filename)[0] + '.json'
        json_path = os.path.join(output_dir, json_name)

        try:
            data = dbc_to_json(dbc_path, build)
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            schema_type = 'named' if data['_meta']['has_named_schema'] else 'generic'
            results['converted'].append({
                'file': filename,
                'records': data['_meta']['record_count'],
                'fields': data['_meta']['field_count'],
                'schema': schema_type,
            })
            print("  OK  {:40s} {:>6} records  ({})".format(
                filename, data['_meta']['record_count'], schema_type))
        except Exception as e:
            results['failed'].append({'file': filename, 'error': str(e)})
            print("  FAIL  {:40s} -- {}".format(filename, e))

    return results


# ===================================================================
# CLI
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description='DBC <-> JSON converter for WoW 3.3.5a (WotLK) WDBC files')
    subparsers = parser.add_subparsers(dest='command')

    # -- dbc2json -------------------------------------------------------
    p_d2j = subparsers.add_parser('dbc2json', help='Convert DBC to JSON')
    p_d2j.add_argument('input', nargs='?', help='Input .dbc file')
    p_d2j.add_argument('-o', '--output', help='Output .json file (or directory with --dir)')
    p_d2j.add_argument('--dir', help='Batch-convert all .dbc files in a directory')
    p_d2j.add_argument('--build', default='3.3.5.12340',
                        help='Game build version (default: 3.3.5.12340)')

    # -- json2dbc -------------------------------------------------------
    p_j2d = subparsers.add_parser('json2dbc', help='Convert JSON back to DBC')
    p_j2d.add_argument('input', help='Input .json file')
    p_j2d.add_argument('-o', '--output', help='Output .dbc file')

    args = parser.parse_args()

    if args.command == 'dbc2json':
        if args.dir:
            output_dir = args.output or os.path.join(args.dir, 'json')
            print("Converting all .dbc files in: {}".format(args.dir))
            print("Output directory: {}\n".format(output_dir))
            results = convert_directory(args.dir, output_dir, args.build)
            named = sum(1 for r in results['converted'] if r['schema'] == 'named')
            generic = sum(1 for r in results['converted'] if r['schema'] == 'generic')
            print("\n{} converted ({} named schema, {} generic), {} failed".format(
                len(results['converted']), named, generic, len(results['failed'])))
        elif args.input:
            output = args.output or os.path.splitext(args.input)[0] + '.json'
            data = dbc_to_json(args.input, args.build)
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            schema_type = 'named' if data['_meta']['has_named_schema'] else 'generic'
            print("{} -> {} ({} records, {} schema)".format(
                args.input, output, data['_meta']['record_count'], schema_type))
        else:
            p_d2j.print_help()

    elif args.command == 'json2dbc':
        with open(args.input, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        output = args.output or os.path.splitext(args.input)[0] + '.dbc'
        count = json_to_dbc(json_data, output)
        print("{} -> {} ({} records)".format(args.input, count, output))

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
