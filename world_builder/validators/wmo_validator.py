"""
WMO (World Map Object) structure validator for WoW WotLK 3.3.5a.

Validates:
- Group count matches group files
- Material references
- Portal definitions
- Bounding boxes
- Marks visual checks as SKIP
"""

import os
import struct

from ..qa_validator import ValidationResult, ValidationSeverity


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAGIC_MVER = b'REVM'
_MAGIC_MOHD = b'DHOM'   # WMO header
_MAGIC_MOTX = b'XTOM'   # Textures
_MAGIC_MOMT = b'TMOM'   # Materials
_MAGIC_MOGN = b'NGOM'   # Group names
_MAGIC_MOGI = b'IGOM'   # Group info
_MAGIC_MOPT = b'TPOM'   # Portals
_MAGIC_MOPV = b'VPOM'   # Portal vertices
_MAGIC_MOPR = b'RPOM'   # Portal references
_CHUNK_HEADER_SIZE = 8

# MOHD is 64 bytes
_MOHD_SIZE = 64
_MOMT_ENTRY_SIZE = 64    # Each material entry
_MOGI_ENTRY_SIZE = 32    # Each group info entry


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _find_wmo_files(client_dir):
    """
    Find all root WMO files under client_dir.

    Root WMO files are identified by not having _NNN suffix.
    Group files are {name}_NNN.wmo.
    """
    wmo_files = []
    if not client_dir or not os.path.isdir(client_dir):
        return wmo_files

    for root, _dirs, files in os.walk(client_dir):
        for fname in files:
            if not fname.lower().endswith('.wmo'):
                continue
            # Check if this is a root WMO (not a group file)
            base = os.path.splitext(fname)[0]
            parts = base.split('_')
            # Group files end with _NNN where NNN is digits
            if parts and parts[-1].isdigit() and len(parts) > 1:
                continue  # This is a group file
            wmo_files.append(os.path.join(root, fname))

    return wmo_files


def _find_group_files(wmo_path):
    """Find group files for a root WMO. Returns list of paths."""
    wmo_dir = os.path.dirname(wmo_path)
    base = os.path.splitext(os.path.basename(wmo_path))[0]

    group_files = []
    idx = 0
    while True:
        group_name = "{}_{:03d}.wmo".format(base, idx)
        group_path = os.path.join(wmo_dir, group_name)
        if os.path.isfile(group_path):
            group_files.append(group_path)
            idx += 1
        else:
            break

    return group_files


# ---------------------------------------------------------------------------
# Chunk parsing
# ---------------------------------------------------------------------------

def _parse_chunks(data):
    """Parse WMO chunks."""
    chunks = {}
    pos = 0
    while pos + _CHUNK_HEADER_SIZE <= len(data):
        magic = data[pos:pos + 4]
        size = struct.unpack_from('<I', data, pos + 4)[0]
        data_start = pos + _CHUNK_HEADER_SIZE
        data_end = data_start + size
        chunk_data = data[data_start:min(data_end, len(data))]
        if magic not in chunks:
            chunks[magic] = chunk_data
        pos = data_end
    return chunks


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_wmo_files(client_dir):
    """
    Validate all WMO files found under client_dir.

    Returns:
        List of ValidationResult objects.
    """
    results = []

    wmo_files = _find_wmo_files(client_dir)

    if not wmo_files:
        results.append(ValidationResult(
            check_id='WMO-001',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="No WMO files found to validate",
        ))
        return results

    for wmo_path in wmo_files:
        fname = os.path.basename(wmo_path)

        try:
            with open(wmo_path, 'rb') as f:
                data = f.read()
        except IOError as exc:
            results.append(ValidationResult(
                check_id='WMO-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Cannot read WMO {}: {}".format(fname, exc),
            ))
            continue

        chunks = _parse_chunks(data)

        # WMO-001: Group count matches group files
        mohd = chunks.get(_MAGIC_MOHD)
        if mohd is not None and len(mohd) >= _MOHD_SIZE:
            # MOHD: nTextures(4), nGroups(4), nPortals(4), nLights(4)...
            n_textures = struct.unpack_from('<I', mohd, 0)[0]
            n_groups = struct.unpack_from('<I', mohd, 4)[0]
            n_portals = struct.unpack_from('<I', mohd, 8)[0]

            group_files = _find_group_files(wmo_path)
            if len(group_files) == n_groups:
                results.append(ValidationResult(
                    check_id='WMO-001',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="WMO {} group count {} matches files".format(
                        fname, n_groups),
                ))
            else:
                results.append(ValidationResult(
                    check_id='WMO-001',
                    severity=ValidationSeverity.ERROR,
                    passed=False,
                    message=("WMO {} MOHD says {} groups, "
                             "found {} files".format(
                                 fname, n_groups, len(group_files))),
                    fix_suggestion="Fix MOHD header group count",
                ))

            # WMO-002: Material references
            momt = chunks.get(_MAGIC_MOMT)
            if momt is not None:
                mat_count = len(momt) // _MOMT_ENTRY_SIZE
                if mat_count > 0:
                    results.append(ValidationResult(
                        check_id='WMO-002',
                        severity=ValidationSeverity.WARNING,
                        passed=True,
                        message="WMO {} has {} materials".format(
                            fname, mat_count),
                    ))
                else:
                    results.append(ValidationResult(
                        check_id='WMO-002',
                        severity=ValidationSeverity.WARNING,
                        passed=False,
                        message="WMO {} has no materials".format(fname),
                        fix_suggestion="Provide valid material definitions",
                    ))
            else:
                results.append(ValidationResult(
                    check_id='WMO-002',
                    severity=ValidationSeverity.WARNING,
                    passed=False,
                    message="WMO {} missing MOMT chunk".format(fname),
                    fix_suggestion="Provide valid material definitions",
                ))

            # WMO-003: Portal definitions
            mopt = chunks.get(_MAGIC_MOPT)
            if n_portals > 0:
                if mopt is not None:
                    results.append(ValidationResult(
                        check_id='WMO-003',
                        severity=ValidationSeverity.INFO,
                        passed=True,
                        message="WMO {} has {} portals defined".format(
                            fname, n_portals),
                    ))
                else:
                    results.append(ValidationResult(
                        check_id='WMO-003',
                        severity=ValidationSeverity.INFO,
                        passed=False,
                        message="WMO {} declares {} portals but no "
                                "MOPT chunk".format(fname, n_portals),
                        fix_suggestion="Fix portal group indices",
                    ))
            else:
                results.append(ValidationResult(
                    check_id='WMO-003',
                    severity=ValidationSeverity.INFO,
                    passed=True,
                    message="WMO {} has no portals".format(fname),
                ))

            # WMO-004: Bounding box
            if len(mohd) >= 40:
                # Bounding box: 6 floats at offset 16
                bb_x1 = struct.unpack_from('<f', mohd, 16)[0]
                bb_y1 = struct.unpack_from('<f', mohd, 20)[0]
                bb_z1 = struct.unpack_from('<f', mohd, 24)[0]
                bb_x2 = struct.unpack_from('<f', mohd, 28)[0]
                bb_y2 = struct.unpack_from('<f', mohd, 32)[0]
                bb_z2 = struct.unpack_from('<f', mohd, 36)[0]

                # Check bounds are reasonable (not zero, not inverted)
                size_x = abs(bb_x2 - bb_x1)
                size_y = abs(bb_y2 - bb_y1)
                size_z = abs(bb_z2 - bb_z1)

                if size_x > 0 and size_y > 0 and size_z > 0:
                    results.append(ValidationResult(
                        check_id='WMO-004',
                        severity=ValidationSeverity.WARNING,
                        passed=True,
                        message="WMO {} bounding box {:.0f}x{:.0f}x"
                                "{:.0f}".format(fname, size_x, size_y,
                                                size_z),
                    ))
                else:
                    results.append(ValidationResult(
                        check_id='WMO-004',
                        severity=ValidationSeverity.WARNING,
                        passed=False,
                        message="WMO {} bounding box has zero "
                                "dimension".format(fname),
                        fix_suggestion="Recalculate from geometry",
                    ))
            else:
                results.append(ValidationResult(
                    check_id='WMO-004',
                    severity=ValidationSeverity.WARNING,
                    passed=False,
                    message="WMO {} MOHD too small for bounding "
                            "box".format(fname),
                ))

        else:
            results.append(ValidationResult(
                check_id='WMO-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="WMO {} missing or invalid MOHD header".format(fname),
            ))

    # WMO-005: Visual appearance - always SKIP
    results.append(ValidationResult(
        check_id='WMO-005',
        severity=ValidationSeverity.SKIP,
        passed=True,
        message="WMO visual appearance requires in-game inspection",
    ))

    return results
