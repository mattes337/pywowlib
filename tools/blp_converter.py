#!/usr/bin/env python
"""
BLP <-> PNG bidirectional converter for WoW 3.3.5a (WotLK) textures.

Converts BLP2 texture files to PNG and back. Supports DXT1, DXT3, DXT5
compressed textures and uncompressed BGRA. Uses pure-Python DXT codec
with optional native PNG2BLP acceleration.

Usage:
  python blp_converter.py blp2png <input.blp> [-o output.png]
  python blp_converter.py png2blp <input.png> [-o output.blp] [--compression dxt1]
  python blp_converter.py blp2png --dir <blp_dir> [-o output_dir]
  python blp_converter.py png2blp --dir <png_dir> [-o output_dir] [--compression dxt1]
  python blp_converter.py info <input.blp>
"""

import os
import sys
import argparse

# Add the project root to sys.path so we can import world_builder
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from world_builder.blp_converter import (
    read_blp,
    read_blp_info,
    convert_blp_to_png,
    convert_png_to_blp,
    batch_convert_blp_to_png,
    batch_convert,
    image_to_blp,
)


# ---------------------------------------------------------------------------
# BLP -> PNG conversion
# ---------------------------------------------------------------------------

def cmd_blp2png(args):
    """Handle the blp2png subcommand."""
    if args.dir:
        output_dir = args.output or os.path.join(args.dir, 'png')
        print("Converting all .blp files in: {}".format(args.dir))
        print("Output directory: {}\n".format(output_dir))

        blp_dir = args.dir
        if not os.path.isdir(blp_dir):
            print("ERROR: Directory not found: {}".format(blp_dir))
            sys.exit(1)

        converted = 0
        failed = 0
        for filename in sorted(os.listdir(blp_dir)):
            if not filename.lower().endswith('.blp'):
                continue

            blp_path = os.path.join(blp_dir, filename)
            png_name = os.path.splitext(filename)[0] + '.png'
            png_path = os.path.join(output_dir, png_name)

            try:
                convert_blp_to_png(blp_path, png_path)
                info = read_blp_info(blp_path)
                print("  OK  {:50s} {}x{} {}".format(
                    filename, info['width'], info['height'],
                    info.get('compression_name', '?')))
                converted += 1
            except Exception as e:
                print("  FAIL  {:50s} -- {}".format(filename, e))
                failed += 1

        print("\n{} converted, {} failed".format(converted, failed))

    elif args.input:
        blp_path = args.input
        output = args.output or os.path.splitext(blp_path)[0] + '.png'

        info = read_blp_info(blp_path)
        convert_blp_to_png(blp_path, output)

        print("{} -> {} ({}x{}, {})".format(
            blp_path, output,
            info['width'], info['height'],
            info.get('compression_name', '?')))

    else:
        print("ERROR: Provide an input file or --dir for batch mode.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# PNG -> BLP conversion
# ---------------------------------------------------------------------------

def cmd_png2blp(args):
    """Handle the png2blp subcommand."""
    compression = args.compression or 'dxt1'

    if args.dir:
        output_dir = args.output or os.path.join(args.dir, 'blp')
        print("Converting all .png files in: {}".format(args.dir))
        print("Output directory: {}".format(output_dir))
        print("Compression: {}\n".format(compression))

        png_dir = args.dir
        if not os.path.isdir(png_dir):
            print("ERROR: Directory not found: {}".format(png_dir))
            sys.exit(1)

        os.makedirs(output_dir, exist_ok=True)

        converted = 0
        failed = 0
        for filename in sorted(os.listdir(png_dir)):
            if not filename.lower().endswith('.png'):
                continue

            png_path = os.path.join(png_dir, filename)
            blp_name = os.path.splitext(filename)[0] + '.blp'
            blp_path = os.path.join(output_dir, blp_name)

            try:
                convert_png_to_blp(png_path, blp_path, compression)
                blp_size = os.path.getsize(blp_path)
                print("  OK  {:50s} -> {} ({} bytes)".format(
                    filename, blp_name, blp_size))
                converted += 1
            except Exception as e:
                print("  FAIL  {:50s} -- {}".format(filename, e))
                failed += 1

        print("\n{} converted, {} failed".format(converted, failed))

    elif args.input:
        png_path = args.input
        output = args.output or os.path.splitext(png_path)[0] + '.blp'

        convert_png_to_blp(png_path, output, compression)

        blp_size = os.path.getsize(output)
        print("{} -> {} ({} bytes, compression: {})".format(
            png_path, output, blp_size, compression))

    else:
        print("ERROR: Provide an input file or --dir for batch mode.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# BLP info display
# ---------------------------------------------------------------------------

def cmd_info(args):
    """Handle the info subcommand."""
    blp_path = args.input

    if not os.path.isfile(blp_path):
        print("ERROR: File not found: {}".format(blp_path))
        sys.exit(1)

    info = read_blp_info(blp_path)

    if not info.get('valid', False):
        print("ERROR: Not a valid BLP2 file: {}".format(
            info.get('error', 'invalid magic')))
        sys.exit(1)

    print("File:        {}".format(blp_path))
    print("Magic:       {}".format(info['magic']))
    print("Type:        {}".format(info['type']))
    print("Dimensions:  {}x{}".format(info['width'], info['height']))
    print("Compression: {} (type={})".format(
        info['compression_name'], info['compression']))
    print("Alpha:       depth={}, type={} ({})".format(
        info['alpha_depth'], info['alpha_type'],
        info['alpha_type_name']))
    print("Has mipmaps: {}".format('Yes' if info['has_mips'] else 'No'))
    print("Mipmap count:{}".format(info['mipmap_count']))
    print("File size:   {} bytes".format(info['file_size']))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='BLP <-> PNG converter for WoW 3.3.5a (WotLK) textures')
    subparsers = parser.add_subparsers(dest='command')

    # -- blp2png -------------------------------------------------------
    p_b2p = subparsers.add_parser('blp2png', help='Convert BLP to PNG')
    p_b2p.add_argument('input', nargs='?', help='Input .blp file')
    p_b2p.add_argument('-o', '--output',
                       help='Output .png file (or directory with --dir)')
    p_b2p.add_argument('--dir',
                       help='Batch-convert all .blp files in a directory')

    # -- png2blp -------------------------------------------------------
    p_p2b = subparsers.add_parser('png2blp', help='Convert PNG to BLP')
    p_p2b.add_argument('input', nargs='?', help='Input .png file')
    p_p2b.add_argument('-o', '--output',
                       help='Output .blp file (or directory with --dir)')
    p_p2b.add_argument('--dir',
                       help='Batch-convert all .png files in a directory')
    p_p2b.add_argument('--compression', choices=['dxt1', 'dxt3', 'dxt5', 'raw'],
                       default='dxt1',
                       help='Compression format (default: dxt1)')

    # -- info ----------------------------------------------------------
    p_info = subparsers.add_parser('info', help='Show BLP header information')
    p_info.add_argument('input', help='Input .blp file')

    args = parser.parse_args()

    if args.command == 'blp2png':
        cmd_blp2png(args)
    elif args.command == 'png2blp':
        # Map 'raw' to 'uncompressed' for the internal API
        if args.compression == 'raw':
            args.compression = 'uncompressed'
        cmd_png2blp(args)
    elif args.command == 'info':
        cmd_info(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
