#!/usr/bin/env python
"""
WDT <-> JSON bidirectional converter for WoW 3.3.5a (WotLK) WDT files.

Converts binary WDT (World Data Table) files to human-readable JSON and back.
Uses the existing read_wdt() and create_wdt() functions from wdt_generator.

Usage:
  python wdt_converter.py wdt2json <input.wdt> [-o output.json]
  python wdt_converter.py json2wdt <input.json> [-o output.wdt]
  python wdt_converter.py wdt2json --dir <wdt_dir> [-o output_dir]
"""

import json
import os
import sys
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from world_builder.wdt_generator import read_wdt, create_wdt

# Grid dimensions matching wdt_generator
_GRID_SIZE = 64


# ===================================================================
# Grid visualization
# ===================================================================

def _build_grid_visual(active_coords):
    """
    Build a 64-line ASCII art grid showing active tiles.

    '.' = empty tile, '#' = active tile.
    Each line represents one row (y value), columns are x values.
    """
    active_set = set((x, y) for x, y in active_coords)
    lines = []
    for y in range(_GRID_SIZE):
        row = ''
        for x in range(_GRID_SIZE):
            row += '#' if (x, y) in active_set else '.'
        lines.append(row)
    return lines


# ===================================================================
# Public conversion functions
# ===================================================================

def wdt_to_json(wdt_path):
    """Convert a WDT file to a JSON-serialisable dict."""
    wdt_data = read_wdt(wdt_path)

    active_coords = wdt_data['active_coords']
    mphd_flags = wdt_data['mphd_flags']
    version = wdt_data['version']

    # Convert list of tuples to list of [x, y] lists for JSON
    active_tiles = [[x, y] for x, y in active_coords]

    # Build ASCII grid visualization
    grid_visual = _build_grid_visual(active_coords)

    filename = os.path.basename(wdt_path)

    return {
        '_meta': {
            'filename': filename,
            'version': version,
            'mphd_flags': mphd_flags,
            'tile_count': len(active_tiles),
        },
        'mphd_flags': mphd_flags,
        'active_tiles': active_tiles,
        'grid_visual': grid_visual,
    }


def json_to_wdt(json_data):
    """
    Convert a JSON dict (as produced by wdt_to_json) back to WDT bytes.

    Returns:
        bytes: Complete WDT file content.
    """
    mphd_flags = json_data.get('mphd_flags', 0)
    active_tiles = json_data.get('active_tiles', [])

    # Convert [x, y] lists back to (x, y) tuples
    active_coords = [(tile[0], tile[1]) for tile in active_tiles]

    return create_wdt(active_coords, mphd_flags)


def convert_directory(wdt_dir, output_dir):
    """Batch-convert every .wdt file in wdt_dir to JSON in output_dir."""
    os.makedirs(output_dir, exist_ok=True)

    results = {'converted': [], 'failed': []}

    for filename in sorted(os.listdir(wdt_dir)):
        if not filename.lower().endswith('.wdt'):
            continue

        wdt_path = os.path.join(wdt_dir, filename)
        json_name = os.path.splitext(filename)[0] + '.json'
        json_path = os.path.join(output_dir, json_name)

        try:
            data = wdt_to_json(wdt_path)
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            results['converted'].append({
                'file': filename,
                'tiles': data['_meta']['tile_count'],
                'mphd_flags': data['_meta']['mphd_flags'],
            })
            print("  OK  {:40s} {:>4} tiles  (flags=0x{:X})".format(
                filename, data['_meta']['tile_count'],
                data['_meta']['mphd_flags']))
        except Exception as e:
            results['failed'].append({'file': filename, 'error': str(e)})
            print("  FAIL  {:40s} -- {}".format(filename, e))

    return results


# ===================================================================
# CLI
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description='WDT <-> JSON converter for WoW 3.3.5a (WotLK) WDT files')
    subparsers = parser.add_subparsers(dest='command')

    # -- wdt2json -------------------------------------------------------
    p_w2j = subparsers.add_parser('wdt2json', help='Convert WDT to JSON')
    p_w2j.add_argument('input', nargs='?', help='Input .wdt file')
    p_w2j.add_argument('-o', '--output',
                       help='Output .json file (or directory with --dir)')
    p_w2j.add_argument('--dir',
                       help='Batch-convert all .wdt files in a directory')

    # -- json2wdt -------------------------------------------------------
    p_j2w = subparsers.add_parser('json2wdt', help='Convert JSON back to WDT')
    p_j2w.add_argument('input', help='Input .json file')
    p_j2w.add_argument('-o', '--output', help='Output .wdt file')

    args = parser.parse_args()

    if args.command == 'wdt2json':
        if args.dir:
            output_dir = args.output or os.path.join(args.dir, 'json')
            print("Converting all .wdt files in: {}".format(args.dir))
            print("Output directory: {}\n".format(output_dir))
            results = convert_directory(args.dir, output_dir)
            print("\n{} converted, {} failed".format(
                len(results['converted']), len(results['failed'])))
        elif args.input:
            output = args.output or os.path.splitext(args.input)[0] + '.json'
            data = wdt_to_json(args.input)
            with open(output, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print("{} -> {} ({} tiles, flags=0x{:X})".format(
                args.input, output,
                data['_meta']['tile_count'],
                data['_meta']['mphd_flags']))
        else:
            p_w2j.print_help()

    elif args.command == 'json2wdt':
        with open(args.input, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        output = args.output or os.path.splitext(args.input)[0] + '.wdt'
        wdt_bytes = json_to_wdt(json_data)
        with open(output, 'wb') as f:
            f.write(wdt_bytes)
        tile_count = len(json_data.get('active_tiles', []))
        print("{} -> {} ({} tiles)".format(args.input, output, tile_count))

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
