"""
WDT (World Data Table) file generator for WoW WotLK 3.3.5a.

Generates valid WDT binary files that define which ADT tiles exist on a map.
This is a standalone generator using struct.pack directly.

WDT chunk order:
  1. MVER  - Version chunk (version 18)
  2. MPHD  - Map header flags
  3. MAIN  - 64x64 tile presence grid
  4. MWMO  - World map object (empty for terrain-only maps)

All chunk magics are reversed in the binary file (e.g. 'REVM' for MVER).
All integers are unsigned 32-bit little-endian.
"""

import logging
import struct
from io import BytesIO

log = logging.getLogger(__name__)


# Grid dimensions
_GRID_SIZE = 64
_GRID_TOTAL = _GRID_SIZE * _GRID_SIZE  # 4096 entries

# Chunk magic strings (reversed per WoW convention)
_MAGIC_MVER = b'REVM'
_MAGIC_MPHD = b'DHPM'
_MAGIC_MAIN = b'NIAM'
_MAGIC_MWMO = b'OMWM'

# Fixed sizes
_MVER_DATA_SIZE = 4                       # 1 uint32 (version)
_MPHD_DATA_SIZE = 32                      # 8 uint32 fields
_MAIN_ENTRY_SIZE = 8                      # uint32 flags + uint32 asyncId
_MAIN_DATA_SIZE = _GRID_TOTAL * _MAIN_ENTRY_SIZE  # 32768 bytes
_MWMO_DATA_SIZE = 0                       # empty for terrain-only maps

# WDT version for WotLK 3.3.5a
_WDT_VERSION = 18

# MAIN entry flag indicating an ADT tile exists at this coordinate
_TILE_EXISTS_FLAG = 1


def _write_chunk_header(buf, magic, data_size):
    """Write a chunk header (4-byte magic + uint32 size)."""
    buf.write(magic)
    buf.write(struct.pack('<I', data_size))


def _write_mver(buf):
    """Write MVER chunk: file version = 18."""
    _write_chunk_header(buf, _MAGIC_MVER, _MVER_DATA_SIZE)
    buf.write(struct.pack('<I', _WDT_VERSION))


def _write_mphd(buf, flags):
    """Write MPHD chunk: map header with flags and 7 padding zeros."""
    _write_chunk_header(buf, _MAGIC_MPHD, _MPHD_DATA_SIZE)
    buf.write(struct.pack('<I', flags))
    buf.write(struct.pack('<7I', 0, 0, 0, 0, 0, 0, 0))


def _write_main(buf, active_coords):
    """
    Write MAIN chunk: 64x64 tile presence grid.

    Each entry is 8 bytes (uint32 flags + uint32 asyncId).
    Index into the grid is y * 64 + x (row-major).
    Active tiles get flags=1, inactive tiles get flags=0.
    asyncId is always 0.
    """
    active_set = set(active_coords)

    _write_chunk_header(buf, _MAGIC_MAIN, _MAIN_DATA_SIZE)

    for y in range(_GRID_SIZE):
        for x in range(_GRID_SIZE):
            flags = _TILE_EXISTS_FLAG if (x, y) in active_set else 0
            buf.write(struct.pack('<II', flags, 0))


def _write_mwmo(buf):
    """Write MWMO chunk: empty world map object chunk."""
    _write_chunk_header(buf, _MAGIC_MWMO, _MWMO_DATA_SIZE)


def create_wdt(active_coords, mphd_flags=0):
    """
    Generate a valid WDT binary file for WoW WotLK 3.3.5a.

    Args:
        active_coords: list of (x, y) tuples where 0 <= x, y < 64.
            Each tuple marks a map tile that has a corresponding ADT file.
        mphd_flags: MPHD flags value. Common values:
            0x0  - no special flags
            0x4  - use highres alpha maps
            0x80 - big alpha (WotLK standard)

    Returns:
        bytes: Complete WDT file content ready to be written to disk.

    Raises:
        ValueError: If any coordinate is outside the valid 0..63 range.
    """
    for x, y in active_coords:
        if not (0 <= x < _GRID_SIZE and 0 <= y < _GRID_SIZE):
            raise ValueError(
                "Tile coordinate ({}, {}) out of range. "
                "Valid range is 0..63 for both x and y.".format(x, y)
            )

    buf = BytesIO()

    _write_mver(buf)
    _write_mphd(buf, mphd_flags)
    _write_main(buf, active_coords)
    _write_mwmo(buf)

    return buf.getvalue()


def write_wdt(filepath, active_coords, mphd_flags=0):
    """
    Write a WDT file to disk.

    Args:
        filepath: Output file path (string or path-like object).
        active_coords: list of (x, y) tuples where 0 <= x, y < 64.
        mphd_flags: MPHD flags value (see create_wdt for details).

    Raises:
        ValueError: If any coordinate is outside the valid 0..63 range.
    """
    data = create_wdt(active_coords, mphd_flags)
    with open(filepath, 'wb') as f:
        f.write(data)


def read_wdt(filepath):
    """
    Read a WDT binary file and extract tile presence data.

    Parses MVER, MPHD, and MAIN chunks to determine which ADT tiles
    are active on the map. The returned data can be passed directly
    to create_wdt() for roundtripping.

    Args:
        filepath: Path to the WDT file (string or path-like object).

    Returns:
        dict: {
            'active_coords': list of (x, y) tuples for active tiles,
            'mphd_flags': int with MPHD flags value,
            'version': int with file version (should be 18),
        }

    Raises:
        ValueError: If the file cannot be parsed or has an invalid version.
    """
    with open(filepath, 'rb') as f:
        data = f.read()

    buf = BytesIO(data)
    version = None
    mphd_flags = 0
    active_coords = []

    while buf.tell() < len(data):
        chunk_start = buf.tell()

        # Read chunk header: 4-byte magic + uint32 size
        magic_bytes = buf.read(4)
        if len(magic_bytes) < 4:
            break
        size_bytes = buf.read(4)
        if len(size_bytes) < 4:
            break

        chunk_size = struct.unpack('<I', size_bytes)[0]
        chunk_data_start = buf.tell()

        if magic_bytes == _MAGIC_MVER:
            if chunk_size < _MVER_DATA_SIZE:
                raise ValueError(
                    "MVER chunk too small: {} bytes".format(chunk_size))
            version = struct.unpack('<I', buf.read(4))[0]
            if version != _WDT_VERSION:
                raise ValueError(
                    "Unsupported WDT version: {}. Expected {}.".format(
                        version, _WDT_VERSION))
            log.debug("WDT version: %d", version)

        elif magic_bytes == _MAGIC_MPHD:
            if chunk_size < 4:
                raise ValueError(
                    "MPHD chunk too small: {} bytes".format(chunk_size))
            mphd_flags = struct.unpack('<I', buf.read(4))[0]
            log.debug("MPHD flags: 0x%X", mphd_flags)

        elif magic_bytes == _MAGIC_MAIN:
            expected_size = _MAIN_DATA_SIZE
            if chunk_size < expected_size:
                raise ValueError(
                    "MAIN chunk too small: {} bytes, expected {}".format(
                        chunk_size, expected_size))

            for y in range(_GRID_SIZE):
                for x in range(_GRID_SIZE):
                    entry_data = buf.read(_MAIN_ENTRY_SIZE)
                    if len(entry_data) < _MAIN_ENTRY_SIZE:
                        raise ValueError(
                            "Unexpected end of MAIN chunk at tile ({}, {})".format(
                                x, y))
                    flags, async_id = struct.unpack('<II', entry_data)
                    if flags & _TILE_EXISTS_FLAG:
                        active_coords.append((x, y))

            log.debug("Found %d active tiles", len(active_coords))

        # Advance past the chunk data regardless of which chunk it was
        buf.seek(chunk_data_start + chunk_size)

    if version is None:
        raise ValueError("No MVER chunk found in WDT file")

    return {
        'active_coords': active_coords,
        'mphd_flags': mphd_flags,
        'version': version,
    }
