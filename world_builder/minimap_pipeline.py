"""
Minimap tile conversion pipeline for WoW WotLK 3.3.5a.

Imports minimap tiles exported from Noggit (BLP/TGA/PNG), converts them to
BLP format, validates naming conventions, and generates the md5translate.trs
file required by the WoW client.

Minimap tiles live at:
    Textures\\Minimap\\{MapName}\\map{XX}_{YY}.blp

The primary workflow is to import Noggit-exported tiles via
import_minimap_tiles().  A simple fallback (generate_test_minimaps) fills
tiles with solid colours derived from ADT texture data for rapid prototyping
without requiring a Noggit export.
"""

import glob
import hashlib
import os
import re
import struct
import tempfile
import logging

log = logging.getLogger(__name__)

# Minimap tile dimensions expected by the WoW client.
_TILE_SIZE = 256

# Valid tile coordinate range (WoW uses a 64x64 grid).
_COORD_MIN = 0
_COORD_MAX = 63

# Regex for the expected tile filename: mapXX_YY.ext
_TILE_RE = re.compile(r'^map(\d{2})_(\d{2})\.(blp|tga|png)$', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_tile_naming(filename):
    """
    Validate that *filename* matches the ``mapXX_YY.ext`` pattern.

    Returns:
        tuple: (tile_x, tile_y)

    Raises:
        ValueError: If the filename does not match or coords are out of range.
    """
    match = _TILE_RE.match(filename)
    if not match:
        raise ValueError(
            "Invalid tile filename: {}. "
            "Expected format: mapXX_YY.ext (e.g. map32_32.blp)".format(filename)
        )

    tile_x = int(match.group(1))
    tile_y = int(match.group(2))

    if not (_COORD_MIN <= tile_x <= _COORD_MAX
            and _COORD_MIN <= tile_y <= _COORD_MAX):
        raise ValueError(
            "Tile coordinates out of range: ({}, {})".format(tile_x, tile_y)
        )

    return (tile_x, tile_y)


def _detect_tile_format(file_path):
    """
    Detect whether *file_path* is a BLP, TGA, or PNG by reading magic bytes.

    Returns:
        str: ``'BLP'``, ``'TGA'``, or ``'PNG'``.

    Raises:
        ValueError: If the format cannot be determined.
    """
    with open(file_path, 'rb') as f:
        magic = f.read(4)

    if magic[:4] == b'BLP2':
        return 'BLP'
    if magic[:4] == b'\x89PNG':
        return 'PNG'
    # TGA has no fixed magic.  Noggit exports uncompressed (type 2) or
    # unmapped (type 0) TGA files; the first two bytes are typically 0x00.
    if magic[:2] in (b'\x00\x00', b'\x00\x02'):
        return 'TGA'

    raise ValueError("Unknown tile format: {}".format(file_path))


def _convert_to_blp(image_path):
    """
    Convert a TGA or PNG tile to BLP bytes using the pywowlib PNG2BLP
    Cython extension.  TGA files are first converted to PNG via PIL.

    Returns:
        bytes: Raw BLP file content.
    """
    fmt = _detect_tile_format(image_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        # PNG2BLP needs PNG input data
        if fmt == 'TGA':
            from PIL import Image
            img = Image.open(image_path)
            png_path = os.path.join(tmpdir, "tile.png")
            img.save(png_path, "PNG")
        else:
            png_path = image_path

        with open(png_path, 'rb') as f:
            png_data = f.read()

        from blp import PNG2BLP
        converter = PNG2BLP(png_data, len(png_data))
        blp_bytes = converter.create_blp_dxt_in_memory(False, 1)  # DXT1, no mipmaps

    return blp_bytes


def _generate_md5translate(blp_data, map_name):
    """
    Generate the contents of ``md5translate.trs``.

    Format (one line per tile, Windows line endings)::

        MapName\\mapXX_YY.blp;MD5HASH

    Returns:
        str: File content ready to be encoded and written.
    """
    lines = []
    for (tile_x, tile_y), blp_bytes in sorted(blp_data.items()):
        md5_hash = hashlib.md5(blp_bytes).hexdigest()
        filename = "map{:02d}_{:02d}.blp".format(tile_x, tile_y)
        line = "{}\\{};{}".format(map_name, filename, md5_hash)
        lines.append(line)

    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def import_minimap_tiles(export_dir, map_name, wdt_data=None):
    """
    Import minimap tiles from a Noggit export directory.

    Scans *export_dir* for files matching ``map*_*.*``, validates their
    names, converts non-BLP files to BLP, and generates md5translate.trs.

    Args:
        export_dir: Directory containing exported tiles (BLP/TGA/PNG).
        map_name:   Map directory name (e.g. ``"TelAbim"``).
        wdt_data:   Optional WDT bytes for completeness validation.
                    If provided, active tiles are cross-checked.

    Returns:
        dict: {
            'blp_data':       {(x, y): bytes, ...},
            'md5translate':   str,
            'missing_tiles':  [(x, y), ...],
        }

    Raises:
        FileNotFoundError: If *export_dir* does not exist.
        ValueError:        If any tile has invalid naming or format.
    """
    if not os.path.isdir(export_dir):
        raise FileNotFoundError(
            "Export directory not found: {}".format(export_dir)
        )

    tile_files = glob.glob(os.path.join(export_dir, "map*_*.*"))
    if not tile_files:
        log.warning("No tile files found in %s", export_dir)

    blp_data = {}
    for tile_file in tile_files:
        basename = os.path.basename(tile_file)
        tile_x, tile_y = _validate_tile_naming(basename)

        fmt = _detect_tile_format(tile_file)
        if fmt == 'BLP':
            with open(tile_file, 'rb') as f:
                blp_bytes = f.read()
        else:
            blp_bytes = _convert_to_blp(tile_file)

        blp_data[(tile_x, tile_y)] = blp_bytes
        log.info("Imported tile (%d, %d) from %s [%s]",
                 tile_x, tile_y, basename, fmt)

    # Validate against WDT active tiles if provided
    missing_tiles = []
    if wdt_data and len(wdt_data) > 24:
        # WDT MAIN chunk: 64x64 grid of 8-byte entries starting after
        # the MPHD header.  Each entry has a uint32 flags field; flag 1
        # means the tile exists.  This is a best-effort check.
        try:
            active = _extract_wdt_active_tiles(wdt_data)
            missing_tiles = [t for t in active if t not in blp_data]
            if missing_tiles:
                log.warning("Missing minimap tiles for active WDT entries: %s",
                            missing_tiles)
        except Exception:
            log.debug("Could not parse WDT for tile validation", exc_info=True)

    md5translate = _generate_md5translate(blp_data, map_name)

    return {
        'blp_data': blp_data,
        'md5translate': md5translate,
        'missing_tiles': missing_tiles,
    }


def generate_test_minimaps(adt_data_dict, texture_color_map=None):
    """
    Generate simple solid-colour minimap tiles for testing.

    This is a fallback when no Noggit export is available.  Each tile is
    filled with a single colour derived from its first texture path.
    Quality is intentionally minimal -- just enough to verify the pipeline.

    Args:
        adt_data_dict:    Dict mapping ``(tile_x, tile_y)`` to a dict with
                          a ``'texture_paths'`` key (list of str).
        texture_color_map: Optional dict mapping texture path (str) to an
                           ``(R, G, B)`` tuple.  If ``None``, all tiles
                           default to neutral grey ``(128, 128, 128)``.

    Returns:
        dict: ``{(tile_x, tile_y): blp_bytes, ...}``
    """
    if texture_color_map is None:
        texture_color_map = {}

    blp_data = {}
    for (tile_x, tile_y), adt_info in adt_data_dict.items():
        tex_paths = adt_info.get('texture_paths', [])

        if tex_paths and tex_paths[0] in texture_color_map:
            colour = texture_color_map[tex_paths[0]]
        else:
            colour = (128, 128, 128)

        blp_bytes = _solid_colour_blp(colour)
        blp_data[(tile_x, tile_y)] = blp_bytes

    return blp_data


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------

def _solid_colour_blp(rgb):
    """
    Create a minimal uncompressed BLP2 file (256x256) filled with *rgb*.

    Builds the BLP in memory without any external dependency (no PIL,
    no PNG2BLP).  Uses encoding 1 (uncompressed) with a 256-colour palette.

    Returns:
        bytes: Raw BLP2 file data.
    """
    width = _TILE_SIZE
    height = _TILE_SIZE
    pixel_count = width * height
    r, g, b = rgb

    # BLP2 header: 160 bytes
    # magic(4) type(4) encoding(4) alphaDepth(4) alphaEncoding(4)
    # hasMips(4) width(4) height(4) mipOffsets(4*16) mipSizes(4*16)
    _HEADER_SIZE = 160
    header = bytearray()
    header += b'BLP2'
    header += struct.pack('<I', 1)   # type: 1 = BLP2
    header += struct.pack('<I', 1)   # encoding: 1 = uncompressed (paletted)
    header += struct.pack('<I', 0)   # alphaDepth: 0
    header += struct.pack('<I', 0)   # alphaEncoding: 0
    header += struct.pack('<I', 0)   # hasMips: 0
    header += struct.pack('<I', width)
    header += struct.pack('<I', height)

    # Palette follows header: 256 BGRA entries = 1024 bytes
    data_offset = _HEADER_SIZE + 1024

    # mipOffsets[0] = data_offset, rest = 0
    mip_offsets = [0] * 16
    mip_offsets[0] = data_offset
    for off in mip_offsets:
        header += struct.pack('<I', off)

    # mipSizes[0] = pixel_count, rest = 0
    mip_sizes = [0] * 16
    mip_sizes[0] = pixel_count
    for sz in mip_sizes:
        header += struct.pack('<I', sz)

    assert len(header) == _HEADER_SIZE

    # Palette: 256 BGRA entries, index 0 = our colour
    palette = bytearray(1024)
    palette[0] = b  # Blue
    palette[1] = g  # Green
    palette[2] = r  # Red
    palette[3] = 255  # Alpha

    # Pixel data: all indices = 0 (pointing to palette entry 0)
    pixels = bytes(pixel_count)  # all zeros

    return bytes(header) + bytes(palette) + pixels


def _extract_wdt_active_tiles(wdt_data):
    """
    Parse WDT bytes and return a list of ``(x, y)`` tuples for active tiles.

    Searches for the MAIN chunk and reads the 64x64 flag grid.
    """
    # Find MAIN chunk by scanning for the tag
    main_tag = b'MAIN'
    idx = wdt_data.find(main_tag)
    if idx == -1:
        return []

    # Skip tag (4) and size (4) to reach the 64x64 grid of 8-byte entries
    grid_start = idx + 8
    active = []
    for y in range(64):
        for x in range(64):
            entry_offset = grid_start + (y * 64 + x) * 8
            if entry_offset + 4 > len(wdt_data):
                break
            flags = struct.unpack_from('<I', wdt_data, entry_offset)[0]
            if flags & 1:
                active.append((x, y))

    return active
