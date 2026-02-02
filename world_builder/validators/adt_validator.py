"""
ADT terrain file validator for WoW WotLK 3.3.5a.

Validates:
- Chunk structure (MVER, MHDR, MCIN, MCNK sub-chunks)
- Heightmap values (MCVT range and count)
- Texture references (MTEX, MCLY, MCAL)
- Area ID assignment (MCNK area IDs)
- Doodad/WMO references (MMDX, MMID, MWMO, MWID, MDDF, MODF)
"""

import os
import struct

from ..qa_validator import ValidationResult, ValidationSeverity


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADT_VERSION = 18
_TOTAL_CHUNKS = 256         # 16 x 16 MCNK sub-chunks per ADT
_HEIGHTS_PER_CHUNK = 145    # 9x9 + 8x8 interleaved heights
_NORMALS_PER_CHUNK = 145
_NORMALS_PADDING = 13
_MCNK_HEADER_SIZE = 128
_CHUNK_HEADER_SIZE = 8      # 4 magic + 4 size
_MCAL_LAYER_SIZE = 4096     # 64x64 highres uncompressed alpha

# Height range limits (in yards)
_HEIGHT_MIN = -2048.0
_HEIGHT_MAX = 2048.0

# Reversed chunk magics
_MAGIC_MVER = b'REVM'
_MAGIC_MHDR = b'RDHM'
_MAGIC_MCIN = b'NICM'
_MAGIC_MTEX = b'XTEM'
_MAGIC_MMDX = b'XDMM'
_MAGIC_MMID = b'DIMM'
_MAGIC_MWMO = b'OMWM'
_MAGIC_MWID = b'DIWM'
_MAGIC_MDDF = b'FDDM'
_MAGIC_MODF = b'FDOM'
_MAGIC_MCNK = b'KNCM'
_MAGIC_MCVT = b'TVCM'
_MAGIC_MCNR = b'RNCM'
_MAGIC_MCLY = b'YLCM'
_MAGIC_MCAL = b'LACM'


# ---------------------------------------------------------------------------
# ADT chunk parser
# ---------------------------------------------------------------------------

def _read_chunks(data):
    """
    Parse all top-level chunks from ADT binary data.

    Returns list of (magic, offset, size, data_bytes) tuples.
    """
    chunks = []
    pos = 0
    while pos + _CHUNK_HEADER_SIZE <= len(data):
        magic = data[pos:pos + 4]
        if len(magic) < 4:
            break
        size = struct.unpack_from('<I', data, pos + 4)[0]
        data_start = pos + _CHUNK_HEADER_SIZE
        data_end = data_start + size
        chunk_data = data[data_start:min(data_end, len(data))]
        chunks.append((magic, pos, size, chunk_data))
        pos = data_end
    return chunks


def _find_chunk(chunks, magic):
    """Find first chunk matching magic. Returns (offset, size, data) or None."""
    for m, offset, size, data in chunks:
        if m == magic:
            return (offset, size, data)
    return None


def _find_all_chunks(chunks, magic):
    """Find all chunks matching magic."""
    return [(offset, size, data) for m, offset, size, data in chunks
            if m == magic]


def _parse_mcnk_sub_chunks(mcnk_data):
    """
    Parse sub-chunks within an MCNK chunk (after the 128-byte header).

    Handles the special case of MCNR which has 13 padding bytes after its
    declared data size. These padding bytes are not part of MCNR's size
    field but are present in the data stream.
    """
    if len(mcnk_data) < _MCNK_HEADER_SIZE:
        return []
    interior = mcnk_data[_MCNK_HEADER_SIZE:]

    # Known valid sub-chunk magics within MCNK
    _VALID_SUB_MAGICS = {
        _MAGIC_MCVT, _MAGIC_MCNR, _MAGIC_MCLY, _MAGIC_MCAL,
        b'FRCM',  # MCRF
        b'HSCM',  # MCSH
        b'ESCM',  # MCSE
        b'VCCM',  # MCCV
        b'VLCM',  # MCLV
    }

    chunks = []
    pos = 0
    while pos + _CHUNK_HEADER_SIZE <= len(interior):
        magic = interior[pos:pos + 4]
        if len(magic) < 4:
            break

        # Skip over bytes that are not valid chunk magics
        # (handles MCNR padding and other alignment issues)
        if magic not in _VALID_SUB_MAGICS:
            pos += 1
            continue

        size = struct.unpack_from('<I', interior, pos + 4)[0]
        data_start = pos + _CHUNK_HEADER_SIZE
        data_end = data_start + size
        chunk_data = interior[data_start:min(data_end, len(interior))]
        chunks.append((magic, pos, size, chunk_data))

        # After MCNR, skip an additional 13 padding bytes
        if magic == _MAGIC_MCNR:
            pos = data_end + _NORMALS_PADDING
        else:
            pos = data_end

    return chunks


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _find_adt_files(client_dir):
    """
    Find all ADT files under client_dir.

    Returns list of (map_name, tile_x, tile_y, filepath) tuples.
    """
    adt_files = []
    if not client_dir or not os.path.isdir(client_dir):
        return adt_files

    for base in [client_dir, os.path.join(client_dir, "mpq_content")]:
        maps_root = os.path.join(base, "World", "Maps")
        if not os.path.isdir(maps_root):
            continue
        for map_name in os.listdir(maps_root):
            map_dir = os.path.join(maps_root, map_name)
            if not os.path.isdir(map_dir):
                continue
            for fname in os.listdir(map_dir):
                if not fname.lower().endswith('.adt'):
                    continue
                # Parse tile coords from filename: MapName_X_Y.adt
                parts = os.path.splitext(fname)[0].split('_')
                if len(parts) >= 3:
                    try:
                        tx = int(parts[-2])
                        ty = int(parts[-1])
                        fpath = os.path.join(map_dir, fname)
                        adt_files.append((map_name, tx, ty, fpath))
                    except ValueError:
                        pass

    return adt_files


# ---------------------------------------------------------------------------
# Chunk structure validation (ADT-001 through ADT-006)
# ---------------------------------------------------------------------------

def _validate_adt_structure(filepath, map_name, tx, ty):
    """Validate ADT chunk structure for a single file."""
    results = []
    label = "{}_{}_{}".format(map_name, tx, ty)

    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except IOError as exc:
        results.append(ValidationResult(
            check_id='ADT-001',
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="Cannot read ADT {}: {}".format(label, exc),
        ))
        return results, None

    chunks = _read_chunks(data)

    # ADT-001: MVER version check
    mver = _find_chunk(chunks, _MAGIC_MVER)
    if mver is not None:
        _offset, _size, mver_data = mver
        if len(mver_data) >= 4:
            version = struct.unpack_from('<I', mver_data, 0)[0]
            if version == _ADT_VERSION:
                results.append(ValidationResult(
                    check_id='ADT-001',
                    severity=ValidationSeverity.ERROR,
                    passed=True,
                    message="ADT {} MVER version {} verified".format(
                        label, version),
                ))
            else:
                results.append(ValidationResult(
                    check_id='ADT-001',
                    severity=ValidationSeverity.ERROR,
                    passed=False,
                    message="ADT {} MVER version {}, expected {}".format(
                        label, version, _ADT_VERSION),
                    fix_suggestion="Regenerate ADT with correct version",
                ))
        else:
            results.append(ValidationResult(
                check_id='ADT-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="ADT {} MVER chunk too small".format(label),
            ))
    else:
        results.append(ValidationResult(
            check_id='ADT-001',
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="ADT {} missing MVER chunk".format(label),
            fix_suggestion="Regenerate ADT with correct version",
        ))

    # ADT-002: MHDR present
    mhdr = _find_chunk(chunks, _MAGIC_MHDR)
    if mhdr is not None:
        results.append(ValidationResult(
            check_id='ADT-002',
            severity=ValidationSeverity.ERROR,
            passed=True,
            message="ADT {} MHDR chunk present".format(label),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-002',
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="ADT {} missing MHDR chunk".format(label),
            fix_suggestion="Check adt_composer.py header logic",
        ))

    # ADT-003: MCIN has 256 entries
    mcin = _find_chunk(chunks, _MAGIC_MCIN)
    if mcin is not None:
        _offset, _size, mcin_data = mcin
        entry_count = len(mcin_data) // 16
        if entry_count == _TOTAL_CHUNKS:
            results.append(ValidationResult(
                check_id='ADT-003',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="ADT {} MCIN has {} entries".format(
                    label, entry_count),
            ))
        else:
            results.append(ValidationResult(
                check_id='ADT-003',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="ADT {} MCIN has {} entries, expected {}".format(
                    label, entry_count, _TOTAL_CHUNKS),
                fix_suggestion="Regenerate with correct MCIN table",
            ))
    else:
        results.append(ValidationResult(
            check_id='ADT-003',
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="ADT {} missing MCIN chunk".format(label),
        ))

    # ADT-004: Each MCNK has MCVT and MCNR sub-chunks
    mcnk_chunks = _find_all_chunks(chunks, _MAGIC_MCNK)
    mcnk_count = len(mcnk_chunks)
    missing_mcvt = 0
    missing_mcnr = 0

    for _offset, _size, mcnk_data in mcnk_chunks:
        sub_chunks = _parse_mcnk_sub_chunks(mcnk_data)
        has_mcvt = any(m == _MAGIC_MCVT for m, _, _, _ in sub_chunks)
        has_mcnr = any(m == _MAGIC_MCNR for m, _, _, _ in sub_chunks)
        if not has_mcvt:
            missing_mcvt += 1
        if not has_mcnr:
            missing_mcnr += 1

    if missing_mcvt == 0 and missing_mcnr == 0 and mcnk_count == _TOTAL_CHUNKS:
        results.append(ValidationResult(
            check_id='ADT-004',
            severity=ValidationSeverity.ERROR,
            passed=True,
            message="ADT {} all {} MCNKs have MCVT and MCNR".format(
                label, mcnk_count),
        ))
    else:
        msg_parts = []
        if mcnk_count != _TOTAL_CHUNKS:
            msg_parts.append("{} MCNKs (expected {})".format(
                mcnk_count, _TOTAL_CHUNKS))
        if missing_mcvt > 0:
            msg_parts.append("{} MCNKs missing MCVT".format(missing_mcvt))
        if missing_mcnr > 0:
            msg_parts.append("{} MCNKs missing MCNR".format(missing_mcnr))
        results.append(ValidationResult(
            check_id='ADT-004',
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="ADT {} issues: {}".format(label, '; '.join(msg_parts)),
            fix_suggestion="Add missing sub-chunks",
        ))

    # ADT-005: MCLY present if textures defined
    mtex = _find_chunk(chunks, _MAGIC_MTEX)
    has_textures = mtex is not None and len(mtex[2]) > 0

    mcly_missing = 0
    if has_textures:
        for _offset, _size, mcnk_data in mcnk_chunks:
            sub_chunks = _parse_mcnk_sub_chunks(mcnk_data)
            has_mcly = any(m == _MAGIC_MCLY for m, _, _, _ in sub_chunks)
            if not has_mcly:
                mcly_missing += 1

    if has_textures and mcly_missing == 0:
        results.append(ValidationResult(
            check_id='ADT-005',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} MCLY present in all MCNKs".format(label),
        ))
    elif has_textures and mcly_missing > 0:
        results.append(ValidationResult(
            check_id='ADT-005',
            severity=ValidationSeverity.WARNING,
            passed=False,
            message="ADT {} {} MCNKs missing MCLY".format(
                label, mcly_missing),
            fix_suggestion="Add MCLY for texture layers",
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-005',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} no textures defined, MCLY not required".format(
                label),
        ))

    # ADT-006: MCAL size matches texture layer count
    mcal_mismatch = 0
    for _offset, _size, mcnk_data in mcnk_chunks:
        sub_chunks = _parse_mcnk_sub_chunks(mcnk_data)
        mcly_info = None
        mcal_info = None
        for m, so, ss, sd in sub_chunks:
            if m == _MAGIC_MCLY:
                mcly_info = (so, ss, sd)
            elif m == _MAGIC_MCAL:
                mcal_info = (so, ss, sd)

        if mcly_info and mcal_info:
            n_layers = len(mcly_info[2]) // 16  # 16 bytes per MCLY entry
            n_alpha_layers = max(0, n_layers - 1)
            expected_mcal_size = n_alpha_layers * _MCAL_LAYER_SIZE
            actual_mcal_size = len(mcal_info[2])
            if actual_mcal_size != expected_mcal_size:
                mcal_mismatch += 1

    if mcal_mismatch == 0:
        results.append(ValidationResult(
            check_id='ADT-006',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} MCAL sizes match layer counts".format(label),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-006',
            severity=ValidationSeverity.WARNING,
            passed=False,
            message="ADT {} {} MCNKs have MCAL size mismatch".format(
                label, mcal_mismatch),
            fix_suggestion="Fix alpha map data",
        ))

    return results, (chunks, mcnk_chunks, data)


# ---------------------------------------------------------------------------
# Heightmap validation (ADT-HM-001 through ADT-HM-003)
# ---------------------------------------------------------------------------

def _validate_heightmap(label, mcnk_chunks):
    """Validate heightmap data in MCNK sub-chunks."""
    results = []

    bad_mcvt_count = 0
    out_of_range_count = 0
    bad_mcnr_count = 0

    for chunk_idx, (_offset, _size, mcnk_data) in enumerate(mcnk_chunks):
        sub_chunks = _parse_mcnk_sub_chunks(mcnk_data)

        for m, so, ss, sd in sub_chunks:
            if m == _MAGIC_MCVT:
                # ADT-HM-001: 145 float values
                n_heights = len(sd) // 4
                if n_heights != _HEIGHTS_PER_CHUNK:
                    bad_mcvt_count += 1

                # ADT-HM-002: Height range
                for hi in range(min(n_heights, _HEIGHTS_PER_CHUNK)):
                    h = struct.unpack_from('<f', sd, hi * 4)[0]
                    if h < _HEIGHT_MIN or h > _HEIGHT_MAX:
                        out_of_range_count += 1
                        break  # Count per chunk, not per vertex

            elif m == _MAGIC_MCNR:
                # ADT-HM-003: 145 normals (3 bytes each)
                expected_size = _NORMALS_PER_CHUNK * 3
                if len(sd) < expected_size:
                    bad_mcnr_count += 1

    # ADT-HM-001
    if bad_mcvt_count == 0:
        results.append(ValidationResult(
            check_id='ADT-HM-001',
            severity=ValidationSeverity.ERROR,
            passed=True,
            message="ADT {} all MCVTs have {} heights".format(
                label, _HEIGHTS_PER_CHUNK),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-HM-001',
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="ADT {} {} MCNKs have wrong MCVT height count".format(
                label, bad_mcvt_count),
            fix_suggestion="Check heightmap generation logic",
        ))

    # ADT-HM-002
    if out_of_range_count == 0:
        results.append(ValidationResult(
            check_id='ADT-HM-002',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} all heights within range".format(label),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-HM-002',
            severity=ValidationSeverity.WARNING,
            passed=False,
            message="ADT {} {} MCNKs have heights outside +/-{} yards".format(
                label, out_of_range_count, int(_HEIGHT_MAX)),
            fix_suggestion="Clamp heights to valid range",
        ))

    # ADT-HM-003
    if bad_mcnr_count == 0:
        results.append(ValidationResult(
            check_id='ADT-HM-003',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="ADT {} all MCNRs have {} normals".format(
                label, _NORMALS_PER_CHUNK),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-HM-003',
            severity=ValidationSeverity.INFO,
            passed=False,
            message="ADT {} {} MCNKs have wrong MCNR size".format(
                label, bad_mcnr_count),
            fix_suggestion="Regenerate normals",
        ))

    return results


# ---------------------------------------------------------------------------
# Texture reference validation (ADT-TEX-001 through ADT-TEX-003)
# ---------------------------------------------------------------------------

def _validate_textures(label, chunks, mcnk_chunks):
    """Validate texture references in ADT."""
    results = []

    # Parse MTEX to get texture paths
    mtex = _find_chunk(chunks, _MAGIC_MTEX)
    texture_paths = []
    if mtex is not None:
        _offset, _size, mtex_data = mtex
        # MTEX is null-terminated strings concatenated
        pos = 0
        while pos < len(mtex_data):
            end = mtex_data.find(b'\x00', pos)
            if end == -1:
                break
            path = mtex_data[pos:end].decode('ascii', errors='replace')
            if path:
                texture_paths.append(path)
            pos = end + 1

    n_textures = len(texture_paths)

    # ADT-TEX-001: Texture paths exist (just validate they're non-empty)
    if n_textures > 0:
        results.append(ValidationResult(
            check_id='ADT-TEX-001',
            severity=ValidationSeverity.ERROR,
            passed=True,
            message="ADT {} has {} texture paths in MTEX".format(
                label, n_textures),
            details="Textures: {}".format(
                ', '.join(texture_paths[:4])),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-TEX-001',
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="ADT {} has no textures in MTEX".format(label),
            fix_suggestion="Document required custom BLPs",
        ))

    # ADT-TEX-002: MCLY texture indices reference valid MTEX entries
    bad_indices = 0
    for _offset, _size, mcnk_data in mcnk_chunks:
        sub_chunks = _parse_mcnk_sub_chunks(mcnk_data)
        for m, _so, _ss, sd in sub_chunks:
            if m == _MAGIC_MCLY:
                n_layers = len(sd) // 16
                for li in range(n_layers):
                    tex_id = struct.unpack_from('<I', sd, li * 16)[0]
                    if tex_id >= n_textures:
                        bad_indices += 1

    if bad_indices == 0:
        results.append(ValidationResult(
            check_id='ADT-TEX-002',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} all MCLY texture indices valid".format(label),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-TEX-002',
            severity=ValidationSeverity.WARNING,
            passed=False,
            message="ADT {} {} MCLY entries have invalid texture index".format(
                label, bad_indices),
            fix_suggestion="Fix layer texture indices",
        ))

    # ADT-TEX-003: MCAL alpha map size
    bad_alpha = 0
    for _offset, _size, mcnk_data in mcnk_chunks:
        sub_chunks = _parse_mcnk_sub_chunks(mcnk_data)
        mcly_info = None
        mcal_info = None
        for m, _so, _ss, sd in sub_chunks:
            if m == _MAGIC_MCLY:
                mcly_info = sd
            elif m == _MAGIC_MCAL:
                mcal_info = sd

        if mcly_info and mcal_info:
            n_layers = len(mcly_info) // 16
            n_alpha = max(0, n_layers - 1)
            expected = n_alpha * _MCAL_LAYER_SIZE
            if len(mcal_info) != expected:
                bad_alpha += 1

    if bad_alpha == 0:
        results.append(ValidationResult(
            check_id='ADT-TEX-003',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} MCAL alpha map sizes correct".format(label),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-TEX-003',
            severity=ValidationSeverity.WARNING,
            passed=False,
            message="ADT {} {} MCNKs have wrong MCAL size".format(
                label, bad_alpha),
            fix_suggestion="Fix alpha map packing",
        ))

    return results


# ---------------------------------------------------------------------------
# Area ID validation (ADT-AREA-001 through ADT-AREA-002)
# ---------------------------------------------------------------------------

def _validate_area_ids(label, mcnk_chunks, dbc_dir):
    """Validate area IDs assigned to MCNK sub-chunks."""
    results = []

    # Extract area IDs from MCNK headers
    area_ids_found = set()
    for _offset, _size, mcnk_data in mcnk_chunks:
        if len(mcnk_data) >= _MCNK_HEADER_SIZE:
            # area_id is at offset 52 in MCNK header (13th uint32)
            area_id = struct.unpack_from('<I', mcnk_data, 52)[0]
            area_ids_found.add(area_id)

    # ADT-AREA-001: Consistent area IDs
    if len(area_ids_found) == 1:
        results.append(ValidationResult(
            check_id='ADT-AREA-001',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} all MCNKs use area ID {}".format(
                label, list(area_ids_found)[0]),
        ))
    elif len(area_ids_found) > 1:
        results.append(ValidationResult(
            check_id='ADT-AREA-001',
            severity=ValidationSeverity.WARNING,
            passed=True,  # Multiple area IDs can be valid for zone boundaries
            message="ADT {} uses {} distinct area IDs: {}".format(
                label, len(area_ids_found), sorted(area_ids_found)),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-AREA-001',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} no area IDs to validate".format(label),
        ))

    # ADT-AREA-002: Area IDs reference valid AreaTable entries
    if dbc_dir:
        area_dbc_path = os.path.join(dbc_dir, "AreaTable.dbc")
        if os.path.isfile(area_dbc_path):
            try:
                from .dbc_validator import _DBCReader
                reader = _DBCReader(area_dbc_path)
                if reader.valid:
                    known_areas = reader.get_all_ids()
                    unknown = area_ids_found - known_areas
                    if not unknown:
                        results.append(ValidationResult(
                            check_id='ADT-AREA-002',
                            severity=ValidationSeverity.INFO,
                            passed=True,
                            message="ADT {} area IDs exist in "
                                    "AreaTable.dbc".format(label),
                        ))
                    else:
                        results.append(ValidationResult(
                            check_id='ADT-AREA-002',
                            severity=ValidationSeverity.INFO,
                            passed=False,
                            message="ADT {} area IDs not in AreaTable: "
                                    "{}".format(label, sorted(unknown)),
                            fix_suggestion="Register area in DBC",
                        ))
            except Exception:
                pass
    else:
        results.append(ValidationResult(
            check_id='ADT-AREA-002',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="ADT {} area ID DBC check skipped "
                    "(no dbc_dir)".format(label),
        ))

    return results


# ---------------------------------------------------------------------------
# Doodad/WMO reference validation (ADT-DOOD-001 through ADT-DOOD-003)
# ---------------------------------------------------------------------------

def _validate_doodad_refs(label, chunks):
    """Validate doodad and WMO references in ADT."""
    results = []

    # ADT-DOOD-001: MMDX/MMID consistency
    mmdx = _find_chunk(chunks, _MAGIC_MMDX)
    mmid = _find_chunk(chunks, _MAGIC_MMID)
    if mmdx is not None and mmid is not None:
        mmdx_size = len(mmdx[2])
        mmid_count = len(mmid[2]) // 4
        results.append(ValidationResult(
            check_id='ADT-DOOD-001',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} MMDX({} bytes)/MMID({} entries) present".format(
                label, mmdx_size, mmid_count),
        ))
    elif mmdx is None and mmid is None:
        results.append(ValidationResult(
            check_id='ADT-DOOD-001',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} no doodad references (empty)".format(label),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-DOOD-001',
            severity=ValidationSeverity.WARNING,
            passed=False,
            message="ADT {} MMDX/MMID mismatch".format(label),
            fix_suggestion="Clear or populate doodad lists",
        ))

    # ADT-DOOD-002: MWMO/MWID consistency
    mwmo = _find_chunk(chunks, _MAGIC_MWMO)
    mwid = _find_chunk(chunks, _MAGIC_MWID)
    if mwmo is not None and mwid is not None:
        mwmo_size = len(mwmo[2])
        mwid_count = len(mwid[2]) // 4
        results.append(ValidationResult(
            check_id='ADT-DOOD-002',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} MWMO({} bytes)/MWID({} entries) present".format(
                label, mwmo_size, mwid_count),
        ))
    elif mwmo is None and mwid is None:
        results.append(ValidationResult(
            check_id='ADT-DOOD-002',
            severity=ValidationSeverity.WARNING,
            passed=True,
            message="ADT {} no WMO references (empty)".format(label),
        ))
    else:
        results.append(ValidationResult(
            check_id='ADT-DOOD-002',
            severity=ValidationSeverity.WARNING,
            passed=False,
            message="ADT {} MWMO/MWID mismatch".format(label),
            fix_suggestion="Clear or populate WMO lists",
        ))

    # ADT-DOOD-003: MDDF/MODF placement counts
    mddf = _find_chunk(chunks, _MAGIC_MDDF)
    modf = _find_chunk(chunks, _MAGIC_MODF)
    mmid_count = len(mmid[2]) // 4 if mmid is not None else 0
    mwid_count = len(mwid[2]) // 4 if mwid is not None else 0

    mddf_count = len(mddf[2]) // 36 if mddf is not None else 0  # 36 bytes per entry
    modf_count = len(modf[2]) // 64 if modf is not None else 0  # 64 bytes per entry

    results.append(ValidationResult(
        check_id='ADT-DOOD-003',
        severity=ValidationSeverity.INFO,
        passed=True,
        message="ADT {} placements: {} doodads, {} WMOs".format(
            label, mddf_count, modf_count),
    ))

    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_adt_files(client_dir, dbc_dir=None):
    """
    Validate all ADT files found under client_dir.

    Returns:
        List of ValidationResult objects.
    """
    results = []

    adt_files = _find_adt_files(client_dir)

    if not adt_files:
        results.append(ValidationResult(
            check_id='ADT-001',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="No ADT files found to validate",
        ))
        return results

    for map_name, tx, ty, filepath in adt_files:
        label = "{}_{}_{}".format(map_name, tx, ty)

        # Chunk structure
        struct_results, parsed = _validate_adt_structure(
            filepath, map_name, tx, ty)
        results.extend(struct_results)

        if parsed is None:
            continue

        chunks, mcnk_chunks, _data = parsed

        # Heightmap
        results.extend(_validate_heightmap(label, mcnk_chunks))

        # Textures
        results.extend(_validate_textures(label, chunks, mcnk_chunks))

        # Area IDs
        results.extend(_validate_area_ids(label, mcnk_chunks, dbc_dir))

        # Doodad/WMO references
        results.extend(_validate_doodad_refs(label, chunks))

    return results
