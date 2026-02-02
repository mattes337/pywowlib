"""
WDT grid file validator for WoW WotLK 3.3.5a.

Validates:
- Active tile flags match existing ADT files
- MPHD flags correctness
- MAIN chunk has 4096 entries (64x64)
- Tile grid gap detection
"""

import os
import struct

from ..qa_validator import ValidationResult, ValidationSeverity


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GRID_SIZE = 64
_GRID_TOTAL = _GRID_SIZE * _GRID_SIZE  # 4096

_MAGIC_MVER = b'REVM'
_MAGIC_MPHD = b'DHPM'
_MAGIC_MAIN = b'NIAM'

_MAIN_ENTRY_SIZE = 8   # uint32 flags + uint32 asyncId
_TILE_EXISTS_FLAG = 1
_CHUNK_HEADER_SIZE = 8


# ---------------------------------------------------------------------------
# WDT parser
# ---------------------------------------------------------------------------

def _parse_wdt(data):
    """Parse WDT chunks. Returns dict of chunk_magic -> chunk_data."""
    chunks = {}
    pos = 0
    while pos + _CHUNK_HEADER_SIZE <= len(data):
        magic = data[pos:pos + 4]
        size = struct.unpack_from('<I', data, pos + 4)[0]
        data_start = pos + _CHUNK_HEADER_SIZE
        data_end = data_start + size
        chunk_data = data[data_start:min(data_end, len(data))]
        chunks[magic] = chunk_data
        pos = data_end
    return chunks


def _get_active_tiles(main_data):
    """Extract set of (x, y) active tile coordinates from MAIN chunk."""
    active = set()
    for y in range(_GRID_SIZE):
        for x in range(_GRID_SIZE):
            idx = (y * _GRID_SIZE + x) * _MAIN_ENTRY_SIZE
            if idx + 4 <= len(main_data):
                flags = struct.unpack_from('<I', main_data, idx)[0]
                if flags & _TILE_EXISTS_FLAG:
                    active.add((x, y))
    return active


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _find_wdt_files(client_dir):
    """Find all WDT files under client_dir. Returns list of (name, path)."""
    wdt_files = []
    if not client_dir or not os.path.isdir(client_dir):
        return wdt_files

    for base in [client_dir, os.path.join(client_dir, "mpq_content")]:
        maps_root = os.path.join(base, "World", "Maps")
        if not os.path.isdir(maps_root):
            continue
        for map_name in os.listdir(maps_root):
            map_dir = os.path.join(maps_root, map_name)
            if not os.path.isdir(map_dir):
                continue
            wdt_path = os.path.join(map_dir, "{}.wdt".format(map_name))
            if os.path.isfile(wdt_path):
                wdt_files.append((map_name, map_dir, wdt_path))

    return wdt_files


def _find_adt_coords(map_dir, map_name):
    """Find all ADT tile coordinates in a map directory."""
    coords = set()
    for fname in os.listdir(map_dir):
        if not fname.lower().endswith('.adt'):
            continue
        parts = os.path.splitext(fname)[0].split('_')
        if len(parts) >= 3:
            try:
                tx = int(parts[-2])
                ty = int(parts[-1])
                coords.add((tx, ty))
            except ValueError:
                pass
    return coords


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_wdt_files(client_dir):
    """
    Validate all WDT files found under client_dir.

    Returns:
        List of ValidationResult objects.
    """
    results = []

    wdt_files = _find_wdt_files(client_dir)

    if not wdt_files:
        results.append(ValidationResult(
            check_id='WDT-001',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="No WDT files found to validate",
        ))
        return results

    for map_name, map_dir, wdt_path in wdt_files:
        try:
            with open(wdt_path, 'rb') as f:
                data = f.read()
        except IOError as exc:
            results.append(ValidationResult(
                check_id='WDT-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Cannot read WDT for {}: {}".format(map_name, exc),
            ))
            continue

        chunks = _parse_wdt(data)

        # WDT-001: Active tiles match existing ADT files
        main_data = chunks.get(_MAGIC_MAIN)
        if main_data is not None:
            active_tiles = _get_active_tiles(main_data)
            adt_coords = _find_adt_coords(map_dir, map_name)

            # Tiles flagged active but no ADT file
            flagged_no_file = active_tiles - adt_coords
            # ADT files exist but not flagged in WDT
            file_no_flag = adt_coords - active_tiles

            if not flagged_no_file and not file_no_flag:
                results.append(ValidationResult(
                    check_id='WDT-001',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="WDT {} active tiles match {} ADT files".format(
                        map_name, len(active_tiles)),
                ))
            else:
                issues = []
                if flagged_no_file:
                    issues.append("{} tiles flagged but no ADT".format(
                        len(flagged_no_file)))
                if file_no_flag:
                    issues.append("{} ADTs not flagged in WDT".format(
                        len(file_no_flag)))
                results.append(ValidationResult(
                    check_id='WDT-001',
                    severity=ValidationSeverity.ERROR,
                    passed=False,
                    message="WDT {} tile mismatch: {}".format(
                        map_name, '; '.join(issues)),
                    fix_suggestion="Regenerate WDT with correct tile list",
                ))
        else:
            results.append(ValidationResult(
                check_id='WDT-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="WDT {} missing MAIN chunk".format(map_name),
            ))
            active_tiles = set()

        # WDT-002: MPHD flags
        mphd_data = chunks.get(_MAGIC_MPHD)
        if mphd_data is not None and len(mphd_data) >= 4:
            flags = struct.unpack_from('<I', mphd_data, 0)[0]
            # 0x80 = big alpha (recommended for WotLK)
            if flags & 0x80:
                results.append(ValidationResult(
                    check_id='WDT-002',
                    severity=ValidationSeverity.WARNING,
                    passed=True,
                    message="WDT {} MPHD flags=0x{:X} (big alpha set)".format(
                        map_name, flags),
                ))
            else:
                results.append(ValidationResult(
                    check_id='WDT-002',
                    severity=ValidationSeverity.WARNING,
                    passed=False,
                    message="WDT {} MPHD flags=0x{:X} (big alpha "
                            "not set)".format(map_name, flags),
                    fix_suggestion="Set MPHD flags to include 0x80 "
                                   "for big alpha",
                ))
        else:
            results.append(ValidationResult(
                check_id='WDT-002',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="WDT {} missing or invalid MPHD chunk".format(
                    map_name),
            ))

        # WDT-003: MAIN has 4096 entries
        if main_data is not None:
            entry_count = len(main_data) // _MAIN_ENTRY_SIZE
            if entry_count == _GRID_TOTAL:
                results.append(ValidationResult(
                    check_id='WDT-003',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="WDT {} MAIN has {} entries".format(
                        map_name, entry_count),
                ))
            else:
                results.append(ValidationResult(
                    check_id='WDT-003',
                    severity=ValidationSeverity.ERROR,
                    passed=False,
                    message="WDT {} MAIN has {} entries, expected {}".format(
                        map_name, entry_count, _GRID_TOTAL),
                    fix_suggestion="Use correct WDT generation",
                ))

        # WDT-004: Check for gaps in tile grid
        if active_tiles and len(active_tiles) > 1:
            # Simple gap detection: check if any active tile is isolated
            # (no active neighbor in 4 cardinal directions)
            isolated = []
            for (x, y) in active_tiles:
                neighbors = [
                    (x - 1, y), (x + 1, y),
                    (x, y - 1), (x, y + 1),
                ]
                has_neighbor = any(n in active_tiles for n in neighbors)
                if not has_neighbor:
                    isolated.append((x, y))

            if not isolated:
                results.append(ValidationResult(
                    check_id='WDT-004',
                    severity=ValidationSeverity.WARNING,
                    passed=True,
                    message="WDT {} no isolated tiles in grid".format(
                        map_name),
                ))
            else:
                results.append(ValidationResult(
                    check_id='WDT-004',
                    severity=ValidationSeverity.WARNING,
                    passed=False,
                    message="WDT {} has {} isolated tiles: {}".format(
                        map_name, len(isolated), isolated[:5]),
                    fix_suggestion="Fill gaps or document intentional "
                                   "isolated tiles",
                ))
        elif active_tiles and len(active_tiles) == 1:
            # Single tile is fine
            results.append(ValidationResult(
                check_id='WDT-004',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="WDT {} has single tile (no gap check needed)".format(
                    map_name),
            ))

    return results
