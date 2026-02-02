"""
ADT (Aderan Terrain) tile generator for WoW WotLK 3.3.5a.

Generates valid ADT binary files containing terrain heightmaps, normals,
and texture layers. This is a standalone generator using struct.pack
directly, mirroring the approach of wdt_generator.py.

ADT file structure:
  1. MVER  - Version (18)
  2. MHDR  - Header with relative offsets to all top-level chunks
  3. MCIN  - 256 entries with absolute file offsets to each MCNK
  4. MTEX  - Texture filenames as null-terminated string block
  5. MMDX  - Empty M2 model string block
  6. MMID  - Empty M2 offset table
  7. MWMO  - Empty WMO string block
  8. MWID  - Empty WMO offset table
  9. MDDF  - Empty doodad placement definitions
  10. MODF - Empty WMO placement definitions
  11. 256x MCNK sub-chunks (16x16 grid)

All chunk magics are reversed in the binary (e.g. MVER -> 'REVM').
All multi-byte integers are little-endian.
"""

import struct
import math
from io import BytesIO


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TILE_SIZE = 5533.333333333        # Yards per ADT tile
CHUNK_SIZE = TILE_SIZE / 16.0     # ~345.83 yards per sub-chunk
MAP_SIZE_MIN = -17066.66656
MAP_SIZE_MAX = 17066.66657

_ADT_VERSION = 18
_GRID_SIZE = 64                   # WDT grid dimension (for validation)
_CHUNKS_PER_SIDE = 16             # Sub-chunks per side of an ADT tile
_TOTAL_CHUNKS = _CHUNKS_PER_SIDE * _CHUNKS_PER_SIDE  # 256

# MCVT: 9 outer rows interleaved with 8 inner rows
# 9*9 outer + 8*8 inner = 81 + 64 = 145 height values
_OUTER_STRIDE = 9
_INNER_STRIDE = 8
_HEIGHTS_PER_CHUNK = 145
_NORMALS_PER_CHUNK = 145
_NORMALS_PADDING = 13             # Padding bytes after MCNR data

_MCNK_HEADER_SIZE = 128          # Fixed MCNK header before sub-chunks
_CHUNK_HEADER_SIZE = 8            # 4-byte magic + 4-byte uint32 size
_MCVT_DATA_SIZE = _HEIGHTS_PER_CHUNK * 4   # 145 float32 = 580 bytes
_MCNR_DATA_SIZE = _NORMALS_PER_CHUNK * 3   # 145 * 3 int8 = 435 bytes
_MCLY_ENTRY_SIZE = 16             # Per-layer entry in MCLY
_MCAL_LAYER_SIZE = 4096           # Highres uncompressed alpha (64*64 bytes)

# Reversed chunk magics (WoW convention: stored reversed in file)
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
_MAGIC_MCRF = b'FRCM'
_MAGIC_MCAL = b'LACM'
_MAGIC_MCSH = b'HSCM'
_MAGIC_MCSE = b'ESCM'

# Default texture when none provided
_DEFAULT_TEXTURE = "Tileset\\Generic\\Black.blp"


# ---------------------------------------------------------------------------
# Low-level write helpers
# ---------------------------------------------------------------------------

def _write_chunk_header(buf, magic, data_size):
    """Write a chunk header: 4-byte reversed magic + uint32 data size."""
    buf.write(magic)
    buf.write(struct.pack('<I', data_size))


def _pack_chunk(magic, data):
    """Return bytes for a complete chunk (header + data)."""
    return magic + struct.pack('<I', len(data)) + data


# ---------------------------------------------------------------------------
# Heightmap helpers
# ---------------------------------------------------------------------------

def _bilinear_sample(heightmap, row_f, col_f, n_rows, n_cols):
    """Sample a heightmap at fractional coordinates using bilinear interpolation."""
    r0 = int(row_f)
    c0 = int(col_f)
    r1 = min(r0 + 1, n_rows - 1)
    c1 = min(c0 + 1, n_cols - 1)

    fr = row_f - r0
    fc = col_f - c0

    v00 = heightmap[r0][c0]
    v01 = heightmap[r0][c1]
    v10 = heightmap[r1][c0]
    v11 = heightmap[r1][c1]

    return (v00 * (1 - fr) * (1 - fc)
            + v01 * (1 - fr) * fc
            + v10 * fr * (1 - fc)
            + v11 * fr * fc)


def _compute_chunk_heights(heightmap, chunk_row, chunk_col):
    """
    Extract 145 interleaved height values for a single MCNK sub-chunk.

    The interleaved grid pattern per chunk is:
      Row 0: 9 outer vertices (indices 0..8)
      Row 1: 8 inner vertices (offset by half a cell)
      Row 2: 9 outer vertices
      ...
      Row 16: 9 outer vertices
    Total: 9*9 + 8*8 = 81 + 64 = 145

    If heightmap is None, returns 145 zeros (flat terrain).

    The heightmap is resampled so that each ADT tile covers the full
    input heightmap. The returned values are heights relative to 0
    (the MCNK base height is set to 0 so MCVT values are absolute
    world heights).
    """
    if heightmap is None:
        return [0.0] * _HEIGHTS_PER_CHUNK

    n_rows = len(heightmap)
    n_cols = len(heightmap[0]) if n_rows > 0 else 0

    if n_rows < 2 or n_cols < 2:
        return [0.0] * _HEIGHTS_PER_CHUNK

    heights = []

    # Total outer vertices across entire tile: 16*8+1 = 129 per axis
    # But we treat each chunk independently with 9 outer and 8 inner rows/cols.
    # The chunk covers a fraction of the heightmap.
    # chunk_row/chunk_col range 0..15.

    for row_idx in range(17):  # 0..16 interleaved rows
        if row_idx % 2 == 0:
            # Outer row: 9 vertices
            n_verts = _OUTER_STRIDE
            for col_idx in range(n_verts):
                # Map vertex to heightmap coordinates
                # Global vertex position within the tile's outer grid (129x129)
                global_r = chunk_row * 8 + row_idx // 2
                global_c = chunk_col * 8 + col_idx
                # Scale to heightmap
                hr = global_r / 128.0 * (n_rows - 1)
                hc = global_c / 128.0 * (n_cols - 1)
                heights.append(_bilinear_sample(heightmap, hr, hc, n_rows, n_cols))
        else:
            # Inner row: 8 vertices (offset by half a cell)
            n_verts = _INNER_STRIDE
            for col_idx in range(n_verts):
                global_r = chunk_row * 8 + row_idx // 2 + 0.5
                global_c = chunk_col * 8 + col_idx + 0.5
                hr = global_r / 128.0 * (n_rows - 1)
                hc = global_c / 128.0 * (n_cols - 1)
                heights.append(_bilinear_sample(heightmap, hr, hc, n_rows, n_cols))

    return heights


def _compute_normals(heights_145):
    """
    Compute 145 normals from the interleaved height values.

    Uses a simple finite-difference approach:
      nx = left_height - right_height
      ny = up_height - down_height
      nz = 8.0  (scaling factor for reasonable normal steepness)
    Then normalize the vector to length 127 (int8 range).

    For perfectly flat terrain all normals are (0, 0, 127).

    Returns a list of 145 (nx, ny, nz) tuples as signed int8 values.
    """
    # Build a lookup grid so we can index by (row_in_chunk, col_in_chunk).
    # The interleaved layout:
    #   row_idx 0  -> outer row 0: 9 values  (indices 0..8)
    #   row_idx 1  -> inner row 0: 8 values  (indices 0..7)
    #   row_idx 2  -> outer row 1: 9 values
    #   ...
    #   row_idx 16 -> outer row 8: 9 values
    # We store them in a dict keyed by (interleaved_row, col).

    grid = {}
    idx = 0
    for row_idx in range(17):
        if row_idx % 2 == 0:
            stride = _OUTER_STRIDE
        else:
            stride = _INNER_STRIDE
        for col_idx in range(stride):
            grid[(row_idx, col_idx)] = heights_145[idx]
            idx += 1

    normals = []
    idx = 0
    for row_idx in range(17):
        if row_idx % 2 == 0:
            stride = _OUTER_STRIDE
        else:
            stride = _INNER_STRIDE

        for col_idx in range(stride):
            h_center = grid[(row_idx, col_idx)]

            # Get neighboring heights, clamping at edges
            if col_idx > 0:
                h_left = grid[(row_idx, col_idx - 1)]
            else:
                h_left = h_center

            if col_idx < stride - 1:
                h_right = grid[(row_idx, col_idx + 1)]
            else:
                h_right = h_center

            if row_idx > 0:
                # Previous row might have different stride
                prev_stride = _OUTER_STRIDE if (row_idx - 1) % 2 == 0 else _INNER_STRIDE
                prev_col = min(col_idx, prev_stride - 1)
                h_up = grid[(row_idx - 1, prev_col)]
            else:
                h_up = h_center

            if row_idx < 16:
                next_stride = _OUTER_STRIDE if (row_idx + 1) % 2 == 0 else _INNER_STRIDE
                next_col = min(col_idx, next_stride - 1)
                h_down = grid[(row_idx + 1, next_col)]
            else:
                h_down = h_center

            nx = h_left - h_right
            ny = h_up - h_down
            nz = 8.0

            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            if length > 0.0:
                scale = 127.0 / length
                inx = max(-127, min(127, int(round(nx * scale))))
                iny = max(-127, min(127, int(round(ny * scale))))
                inz = max(-127, min(127, int(round(nz * scale))))
            else:
                inx, iny, inz = 0, 0, 127

            normals.append((inx, iny, inz))
            idx += 1

    return normals


# ---------------------------------------------------------------------------
# MTEX builder
# ---------------------------------------------------------------------------

def _build_mtex_data(texture_paths):
    """Build the MTEX string block: null-terminated texture paths concatenated."""
    buf = BytesIO()
    for path in texture_paths:
        buf.write(path.encode('ascii'))
        buf.write(b'\x00')
    return buf.getvalue()


# ---------------------------------------------------------------------------
# MCNK sub-chunk builder
# ---------------------------------------------------------------------------

def _build_mcnk(chunk_row, chunk_col, tile_x, tile_y,
                 heightmap, texture_paths, splat_map, area_id):
    """
    Build a single MCNK sub-chunk (header + all interior sub-chunks).

    Returns the complete MCNK bytes including its chunk header.
    """
    n_layers = len(texture_paths) if texture_paths else 1

    # Compute heights and normals
    heights = _compute_chunk_heights(heightmap, chunk_row, chunk_col)
    normals = _compute_normals(heights)

    # -- Build interior sub-chunks into a buffer to calculate offsets --
    interior = BytesIO()

    # MCVT (heights)
    mcvt_offset = interior.tell()
    _write_chunk_header(interior, _MAGIC_MCVT, _MCVT_DATA_SIZE)
    for h in heights:
        interior.write(struct.pack('<f', h))

    # MCNR (normals) - data size is 435 (145*3), plus 13 padding bytes
    mcnr_offset = interior.tell()
    _write_chunk_header(interior, _MAGIC_MCNR, _MCNR_DATA_SIZE)
    for nx, ny, nz in normals:
        interior.write(struct.pack('<bbb', nx, ny, nz))
    # 13 bytes padding after MCNR data (included in MCNK size but not MCNR size)
    interior.write(b'\x00' * _NORMALS_PADDING)

    # MCLY (texture layers)
    mcly_offset = interior.tell()
    mcly_data_size = n_layers * _MCLY_ENTRY_SIZE
    _write_chunk_header(interior, _MAGIC_MCLY, mcly_data_size)

    # Calculate alpha map offsets for layers > 0
    alpha_offset_in_mcal = 0
    for layer_idx in range(n_layers):
        texture_id = layer_idx  # Index into MTEX string block
        flags = 0
        offset_in_mcal = 0
        effect_id = 0

        if layer_idx > 0:
            flags = 0x100  # use_alpha_map flag
            offset_in_mcal = alpha_offset_in_mcal
            alpha_offset_in_mcal += _MCAL_LAYER_SIZE

        interior.write(struct.pack('<IIII', texture_id, flags, offset_in_mcal, effect_id))

    # MCRF (doodad/object references) - empty
    mcrf_offset = interior.tell()
    _write_chunk_header(interior, _MAGIC_MCRF, 0)

    # MCAL (alpha maps) - only for layers > 0
    mcal_offset = interior.tell()
    n_alpha_layers = max(0, n_layers - 1)
    mcal_data_size = n_alpha_layers * _MCAL_LAYER_SIZE
    _write_chunk_header(interior, _MAGIC_MCAL, mcal_data_size)

    for layer_idx in range(1, n_layers):
        if splat_map is not None and layer_idx in splat_map:
            alpha_data = splat_map[layer_idx]
            for row in range(64):
                for col in range(64):
                    val = alpha_data[row][col] if row < len(alpha_data) and col < len(alpha_data[row]) else 0
                    interior.write(struct.pack('<B', max(0, min(255, int(val)))))
        else:
            # Default: fully opaque for this layer
            interior.write(b'\xff' * _MCAL_LAYER_SIZE)

    # MCSH (shadow map) - empty, not present (flag not set)
    # We skip MCSH entirely since we don't set the HAS_MCSH flag.

    # MCSE (sound emitters) - empty
    mcse_offset = interior.tell()
    _write_chunk_header(interior, _MAGIC_MCSE, 0)

    interior_data = interior.getvalue()
    interior_size = len(interior_data)

    # -- Build the 128-byte MCNK header --
    # All sub-chunk offsets in the MCNK header are relative to the start of
    # the MCNK chunk (i.e., the position of the MCNK magic bytes), and they
    # include the 8-byte MCNK chunk header + 128-byte MCNK header prefix.
    base_offset = _CHUNK_HEADER_SIZE + _MCNK_HEADER_SIZE

    # Chunk world position
    pos_x = MAP_SIZE_MAX - (tile_y * TILE_SIZE) - (chunk_row * CHUNK_SIZE)
    pos_y = MAP_SIZE_MAX - (tile_x * TILE_SIZE) - (chunk_col * CHUNK_SIZE)
    pos_z = 0.0  # Base height; MCVT values are relative to this

    mcnk_hdr = BytesIO()

    # flags (uint32) - DO_NOT_FIX_ALPHA_MAP set (0x8000) for highres alpha
    mcnk_flags = 0x8000
    mcnk_hdr.write(struct.pack('<I', mcnk_flags))

    # index_x, index_y (uint32 each)
    mcnk_hdr.write(struct.pack('<II', chunk_col, chunk_row))

    # n_layers (uint32)
    mcnk_hdr.write(struct.pack('<I', n_layers))

    # n_doodad_refs (uint32)
    mcnk_hdr.write(struct.pack('<I', 0))

    # ofs_mcvt, ofs_mcnr (uint32 each) - relative to MCNK start
    mcnk_hdr.write(struct.pack('<II',
                               base_offset + mcvt_offset,
                               base_offset + mcnr_offset))

    # ofs_mcly (uint32)
    mcnk_hdr.write(struct.pack('<I', base_offset + mcly_offset))

    # ofs_mcrf (uint32)
    mcnk_hdr.write(struct.pack('<I', base_offset + mcrf_offset))

    # ofs_mcal (uint32)
    mcnk_hdr.write(struct.pack('<I', base_offset + mcal_offset))

    # size_mcal (uint32)
    mcnk_hdr.write(struct.pack('<I', mcal_data_size))

    # ofs_mcsh (uint32) - 0 (no shadow map)
    mcnk_hdr.write(struct.pack('<I', 0))

    # size_mcsh (uint32)
    mcnk_hdr.write(struct.pack('<I', 0))

    # area_id (uint32)
    mcnk_hdr.write(struct.pack('<I', area_id))

    # n_map_obj_refs (uint32)
    mcnk_hdr.write(struct.pack('<I', 0))

    # holes_low_res (uint16)
    mcnk_hdr.write(struct.pack('<H', 0))

    # unknown_but_used (uint16)
    mcnk_hdr.write(struct.pack('<H', 0))

    # low_quality_texture_map: 8 rows, 2 bytes each = 16 bytes
    mcnk_hdr.write(b'\x00' * 16)

    # no_effect_doodad: 8 bytes
    mcnk_hdr.write(b'\x00' * 8)

    # ofs_mcse (uint32)
    mcnk_hdr.write(struct.pack('<I', base_offset + mcse_offset))

    # n_sound_emitters (uint32)
    mcnk_hdr.write(struct.pack('<I', 0))

    # ofs_mclq (uint32) - 0 (no liquid)
    mcnk_hdr.write(struct.pack('<I', 0))

    # size_liquid (uint32)
    mcnk_hdr.write(struct.pack('<I', 0))

    # position: 3 floats (x, y, z)
    mcnk_hdr.write(struct.pack('<fff', pos_x, pos_y, pos_z))

    # ofs_mccv (uint32) - 0 (no vertex colors)
    mcnk_hdr.write(struct.pack('<I', 0))

    # ofs_mclv (uint32) - 0
    mcnk_hdr.write(struct.pack('<I', 0))

    # unused (uint32)
    mcnk_hdr.write(struct.pack('<I', 0))

    mcnk_header_data = mcnk_hdr.getvalue()
    assert len(mcnk_header_data) == _MCNK_HEADER_SIZE, \
        "MCNK header must be exactly {} bytes, got {}".format(
            _MCNK_HEADER_SIZE, len(mcnk_header_data))

    # Total MCNK data size (what goes in the chunk header's size field)
    # = 128-byte MCNK header + all interior sub-chunk data
    mcnk_data_size = _MCNK_HEADER_SIZE + interior_size

    # Assemble final MCNK chunk
    result = BytesIO()
    _write_chunk_header(result, _MAGIC_MCNK, mcnk_data_size)
    result.write(mcnk_header_data)
    result.write(interior_data)

    return result.getvalue()


# ---------------------------------------------------------------------------
# Top-level ADT assembly
# ---------------------------------------------------------------------------

def create_adt(tile_x, tile_y, heightmap=None, texture_paths=None,
               splat_map=None, area_id=0):
    """
    Generate a valid ADT binary file for WoW WotLK 3.3.5a.

    Args:
        tile_x: Tile X coordinate (0-63).
        tile_y: Tile Y coordinate (0-63).
        heightmap: Optional 2D list of heights [row][col]. Any size;
                   will be bilinearly resampled to fit the tile grid.
                   If None, produces flat terrain at height 0.
        texture_paths: List of texture path strings (max 4).
                       Example: ["Tileset\\\\Grass\\\\GrassLight01.blp"]
                       Defaults to a single black texture.
        splat_map: Optional dict mapping texture_index (int) to a 2D
                   list [64][64] of alpha values (0-255) for layers > 0.
                   Layer 0 is always the base and has no alpha map.
        area_id: Area ID applied to all 256 sub-chunks.

    Returns:
        bytes: Complete ADT file content ready for writing to disk.

    Raises:
        ValueError: If tile coordinates are out of range or more than
                    4 texture paths are given.
    """
    if not (0 <= tile_x < _GRID_SIZE and 0 <= tile_y < _GRID_SIZE):
        raise ValueError(
            "Tile coordinate ({}, {}) out of range. "
            "Valid range is 0..63 for both x and y.".format(tile_x, tile_y))

    if texture_paths is None:
        texture_paths = [_DEFAULT_TEXTURE]

    if len(texture_paths) > 4:
        raise ValueError(
            "Maximum 4 texture layers supported, got {}.".format(len(texture_paths)))

    if len(texture_paths) == 0:
        texture_paths = [_DEFAULT_TEXTURE]

    # -- Phase 1: Build all 256 MCNK sub-chunks and record their sizes --
    mcnk_blobs = []
    for row in range(_CHUNKS_PER_SIDE):
        for col in range(_CHUNKS_PER_SIDE):
            blob = _build_mcnk(row, col, tile_x, tile_y,
                               heightmap, texture_paths, splat_map, area_id)
            mcnk_blobs.append(blob)

    # -- Phase 2: Build top-level chunks before MCNK --

    # MVER
    mver_data = struct.pack('<I', _ADT_VERSION)

    # MTEX
    mtex_data = _build_mtex_data(texture_paths)

    # MMDX, MMID, MWMO, MWID, MDDF, MODF - all empty
    empty_data = b''

    # MHDR: 14 uint32 fields = 56 bytes data
    #   flags, ofs_mcin, ofs_mtex, ofs_mmdx, ofs_mmid, ofs_mwmo, ofs_mwid,
    #   ofs_mddf, ofs_modf, ofs_mfbo, ofs_mh2o, ofs_mtxf, mamp_value(uint8),
    #   padding(3 bytes)
    # But the existing code writes: flags(4) + 11 offsets(44) + mamp_value(1)
    # = 49 bytes. The actual MHDR data size in the original code is 54 bytes
    # (see adt_chunks.py MHDR.data_size = 54). However looking at the write
    # method it writes: 1 uint32 (flags) + 11 uint32 (offsets) + 1 uint8 =
    # 4 + 44 + 1 = 49 bytes. The declared size is 54, so there are 5 padding
    # bytes. Let's match the standard 64-byte MHDR (flags + 11 offsets +
    # 3 unused uint32 = 14 uint32 = 56 bytes) which is more common.
    # Actually, re-reading the WoWDev wiki: MHDR is flags(4) + 11 offsets(44)
    # + padding(8) = 56 bytes on the wiki, or sometimes listed as 64 bytes.
    # The existing codebase uses data_size=54 but only writes 49 bytes which
    # is inconsistent. For maximum compatibility let's use the standard
    # 64-byte MHDR (16 uint32 fields, unused ones = 0).
    _MHDR_DATA_SIZE = 64
    _MCIN_DATA_SIZE = _TOTAL_CHUNKS * 16  # 256 * 16 = 4096

    # Calculate file layout to determine MHDR offsets.
    # MHDR offsets are relative to the end of MHDR's chunk header
    # (i.e., relative to the start of MHDR data).
    # File layout:
    #   [MVER chunk]
    #   [MHDR chunk]           <- mhdr_data_start = after MHDR chunk header
    #   [MCIN chunk]
    #   [MTEX chunk]
    #   [MMDX chunk]
    #   [MMID chunk]
    #   [MWMO chunk]
    #   [MWID chunk]
    #   [MDDF chunk]
    #   [MODF chunk]
    #   [MCNK x 256]

    mver_total = _CHUNK_HEADER_SIZE + len(mver_data)         # 12
    mhdr_total = _CHUNK_HEADER_SIZE + _MHDR_DATA_SIZE        # 8 + 64 = 72
    mcin_total = _CHUNK_HEADER_SIZE + _MCIN_DATA_SIZE        # 8 + 4096 = 4104
    mtex_total = _CHUNK_HEADER_SIZE + len(mtex_data)
    mmdx_total = _CHUNK_HEADER_SIZE + 0
    mmid_total = _CHUNK_HEADER_SIZE + 0
    mwmo_total = _CHUNK_HEADER_SIZE + 0
    mwid_total = _CHUNK_HEADER_SIZE + 0
    mddf_total = _CHUNK_HEADER_SIZE + 0
    modf_total = _CHUNK_HEADER_SIZE + 0

    # Absolute file positions
    pos_mver = 0
    pos_mhdr = pos_mver + mver_total
    mhdr_data_start = pos_mhdr + _CHUNK_HEADER_SIZE  # This is the reference base for MHDR offsets

    pos_mcin = pos_mhdr + mhdr_total
    pos_mtex = pos_mcin + mcin_total
    pos_mmdx = pos_mtex + mtex_total
    pos_mmid = pos_mmdx + mmdx_total
    pos_mwmo = pos_mmid + mmid_total
    pos_mwid = pos_mwmo + mwmo_total
    pos_mddf = pos_mwid + mwid_total
    pos_modf = pos_mddf + mddf_total

    # First MCNK starts after MODF
    pos_first_mcnk = pos_modf + modf_total

    # MHDR offsets (relative to mhdr_data_start)
    ofs_mcin = pos_mcin - mhdr_data_start
    ofs_mtex = pos_mtex - mhdr_data_start
    ofs_mmdx = pos_mmdx - mhdr_data_start
    ofs_mmid = pos_mmid - mhdr_data_start
    ofs_mwmo = pos_mwmo - mhdr_data_start
    ofs_mwid = pos_mwid - mhdr_data_start
    ofs_mddf = pos_mddf - mhdr_data_start
    ofs_modf = pos_modf - mhdr_data_start
    ofs_mfbo = 0   # Not present
    ofs_mh2o = 0   # Not present
    ofs_mtxf = 0   # Not present

    # Build MHDR data (16 uint32 = 64 bytes)
    mhdr_flags = 0
    mhdr_data = struct.pack('<16I',
                            mhdr_flags,
                            ofs_mcin,
                            ofs_mtex,
                            ofs_mmdx,
                            ofs_mmid,
                            ofs_mwmo,
                            ofs_mwid,
                            ofs_mddf,
                            ofs_modf,
                            ofs_mfbo,
                            ofs_mh2o,
                            ofs_mtxf,
                            0, 0, 0, 0)  # padding / unused fields

    # Calculate MCIN entries (absolute file positions for each MCNK)
    mcin_entries = []
    current_mcnk_pos = pos_first_mcnk
    for i in range(_TOTAL_CHUNKS):
        mcnk_size = len(mcnk_blobs[i])
        mcin_entries.append((current_mcnk_pos, mcnk_size, 0, 0))
        current_mcnk_pos += mcnk_size

    # Build MCIN data
    mcin_data = BytesIO()
    for offset, size, flags, async_id in mcin_entries:
        mcin_data.write(struct.pack('<IIII', offset, size, flags, async_id))
    mcin_data = mcin_data.getvalue()

    # -- Phase 3: Assemble the complete file --
    buf = BytesIO()

    # MVER
    _write_chunk_header(buf, _MAGIC_MVER, len(mver_data))
    buf.write(mver_data)

    # MHDR
    _write_chunk_header(buf, _MAGIC_MHDR, _MHDR_DATA_SIZE)
    buf.write(mhdr_data)

    # MCIN
    _write_chunk_header(buf, _MAGIC_MCIN, _MCIN_DATA_SIZE)
    buf.write(mcin_data)

    # MTEX
    _write_chunk_header(buf, _MAGIC_MTEX, len(mtex_data))
    buf.write(mtex_data)

    # MMDX (empty)
    _write_chunk_header(buf, _MAGIC_MMDX, 0)

    # MMID (empty)
    _write_chunk_header(buf, _MAGIC_MMID, 0)

    # MWMO (empty)
    _write_chunk_header(buf, _MAGIC_MWMO, 0)

    # MWID (empty)
    _write_chunk_header(buf, _MAGIC_MWID, 0)

    # MDDF (empty)
    _write_chunk_header(buf, _MAGIC_MDDF, 0)

    # MODF (empty)
    _write_chunk_header(buf, _MAGIC_MODF, 0)

    # Verify alignment before writing MCNKs
    assert buf.tell() == pos_first_mcnk, \
        "Expected MCNK start at {}, but file position is {}".format(
            pos_first_mcnk, buf.tell())

    # Write all 256 MCNK sub-chunks
    for blob in mcnk_blobs:
        buf.write(blob)

    return buf.getvalue()


def write_adt(filepath, tile_x, tile_y, **kwargs):
    """
    Write an ADT file to disk.

    Args:
        filepath: Output file path (string or path-like object).
        tile_x: Tile X coordinate (0-63).
        tile_y: Tile Y coordinate (0-63).
        **kwargs: Additional arguments passed to create_adt
                  (heightmap, texture_paths, splat_map, area_id).

    Raises:
        ValueError: If tile coordinates are out of range or too many textures.
    """
    data = create_adt(tile_x, tile_y, **kwargs)
    with open(filepath, 'wb') as f:
        f.write(data)
