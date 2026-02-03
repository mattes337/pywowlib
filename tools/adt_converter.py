#!/usr/bin/env python
"""
ADT <-> JSON bidirectional converter for WoW 3.3.5a (WotLK) terrain tiles.

Converts binary ADT (terrain tile) files to human-readable JSON and back.
Parses the chunk-based binary format directly using struct for zero
external dependencies.

Usage:
  python adt_converter.py adt2json <input.adt> [-o output.json]
  python adt_converter.py json2adt <input.json> [-o output.adt]
  python adt_converter.py adt2json --dir <adt_dir> [-o output_dir]
"""

import struct
import json
import os
import sys
import math
import argparse


# ---------------------------------------------------------------------------
# Binary helpers
# ---------------------------------------------------------------------------

def _read_u8(f):
    return struct.unpack('<B', f.read(1))[0]

def _read_u16(f):
    return struct.unpack('<H', f.read(2))[0]

def _read_i16(f):
    return struct.unpack('<h', f.read(2))[0]

def _read_u32(f):
    return struct.unpack('<I', f.read(4))[0]

def _read_i8(f):
    return struct.unpack('<b', f.read(1))[0]

def _read_f32(f):
    return struct.unpack('<f', f.read(4))[0]

def _read_vec3f(f):
    return list(struct.unpack('<3f', f.read(12)))

def _write_u8(f, v):
    f.write(struct.pack('<B', v & 0xFF))

def _write_u16(f, v):
    f.write(struct.pack('<H', v & 0xFFFF))

def _write_i16(f, v):
    f.write(struct.pack('<h', v))

def _write_u32(f, v):
    f.write(struct.pack('<I', v & 0xFFFFFFFF))

def _write_i8(f, v):
    f.write(struct.pack('<b', v))

def _write_f32(f, v):
    f.write(struct.pack('<f', v))

def _write_vec3f(f, v):
    f.write(struct.pack('<3f', *v))


def _safe_float(val):
    """Sanitise a float for JSON (NaN / Inf are not valid JSON)."""
    if math.isnan(val) or math.isinf(val):
        return 0.0
    return round(val, 6)


# ---------------------------------------------------------------------------
# Chunk header read/write
# ---------------------------------------------------------------------------

CHUNK_HEADER_SIZE = 8

def _read_chunk_header(f):
    """Read a chunk header: 4-byte reversed magic + uint32 size."""
    raw = f.read(4)
    if len(raw) < 4:
        return None, 0
    magic = raw.decode('ascii', errors='replace')
    size = _read_u32(f)
    return magic, size


def _write_chunk_header(f, magic, size):
    """Write a chunk header."""
    f.write(magic[:4].encode('ascii'))
    _write_u32(f, size)


# ---------------------------------------------------------------------------
# String block parsing (null-terminated strings)
# ---------------------------------------------------------------------------

def _parse_string_block(data):
    """Parse a null-terminated string block into a list of strings."""
    if not data:
        return []
    strings = []
    current = bytearray()
    for b in data:
        if b == 0:
            if current:
                strings.append(current.decode('ascii', errors='replace'))
                current = bytearray()
        else:
            current.append(b)
    # Trailing string without null terminator (unusual but handle it)
    if current:
        strings.append(current.decode('ascii', errors='replace'))
    return strings


def _build_string_block(strings):
    """Build a null-terminated string block from a list of strings."""
    if not strings:
        return b''
    parts = []
    for s in strings:
        parts.append(s.encode('ascii', errors='replace'))
        parts.append(b'\x00')
    return b''.join(parts)


def _build_offset_table(strings):
    """Build an offset table (MMID/MWID) for a string block."""
    offsets = []
    pos = 0
    for s in strings:
        offsets.append(pos)
        pos += len(s.encode('ascii', errors='replace')) + 1
    return offsets


# ---------------------------------------------------------------------------
# ADT -> JSON
# ---------------------------------------------------------------------------

def _read_mcnk_subchunks(f, mcnk_start, mcnk_data_size, mcnk_header):
    """Read MCNK sub-chunks and return parsed data dict."""
    result = {}

    # Offsets from the MCNK header (relative to mcnk_start, which is
    # the position of the MCNK chunk header, i.e. before the 'KNCM' magic)
    ofs_mcvt = mcnk_header['ofs_mcvt']
    ofs_mcnr = mcnk_header['ofs_mcnr']
    ofs_mcly = mcnk_header['ofs_mcly']
    ofs_mcrf = mcnk_header['ofs_mcrf']
    ofs_mcal = mcnk_header['ofs_mcal']
    ofs_mcsh = mcnk_header['ofs_mcsh']
    ofs_mcse = mcnk_header['ofs_mcse']
    ofs_mccv = mcnk_header['ofs_mccv']

    n_layers = mcnk_header['n_layers']
    n_doodad_refs = mcnk_header['n_doodad_refs']
    n_map_obj_refs = mcnk_header['n_map_obj_refs']
    n_sound_emitters = mcnk_header['n_sound_emitters']
    flags = mcnk_header['flags']
    size_mcal = mcnk_header['size_mcal']

    # MCVT - heightmap (145 floats)
    heightmap = [0.0] * 145
    if ofs_mcvt:
        f.seek(mcnk_start + ofs_mcvt)
        _read_chunk_header(f)  # TVCM + size
        heightmap = [_safe_float(_read_f32(f)) for _ in range(145)]
    result['heightmap'] = heightmap

    # MCNR - normals (145 * 3 int8)
    normals = [[0, 0, 127]] * 145
    if ofs_mcnr:
        f.seek(mcnk_start + ofs_mcnr)
        _read_chunk_header(f)  # RNCM + size
        normals = []
        for _ in range(145):
            nx = _read_i8(f)
            ny = _read_i8(f)
            nz = _read_i8(f)
            normals.append([nx, ny, nz])
        # 13 unknown bytes follow - skip
    result['normals'] = normals

    # MCLY - texture layers
    texture_layers = []
    if ofs_mcly and n_layers > 0:
        f.seek(mcnk_start + ofs_mcly)
        _, mcly_size = _read_chunk_header(f)  # YLCM + size
        layer_count = mcly_size // 16
        for _ in range(layer_count):
            tex_id = _read_u32(f)
            layer_flags = _read_u32(f)
            offset_in_mcal = _read_u32(f)
            effect_id = _read_u32(f)
            texture_layers.append({
                'texture_id': tex_id,
                'flags': layer_flags,
                'offset_in_mcal': offset_in_mcal,
                'effect_id': effect_id,
            })
    result['texture_layers'] = texture_layers

    # MCRF - doodad/object references
    doodad_refs = []
    object_refs = []
    if ofs_mcrf:
        f.seek(mcnk_start + ofs_mcrf)
        _read_chunk_header(f)  # FRCM + size
        doodad_refs = [_read_u32(f) for _ in range(n_doodad_refs)]
        object_refs = [_read_u32(f) for _ in range(n_map_obj_refs)]
    result['doodad_refs'] = doodad_refs
    result['object_refs'] = object_refs

    # MCAL - alpha maps (layers 1+ each have a 64x64 alpha)
    # We store raw alpha data for each layer for round-trip fidelity
    alpha_maps = []
    if ofs_mcal and n_layers > 1 and size_mcal > 0:
        f.seek(mcnk_start + ofs_mcal)
        _, mcal_chunk_size = _read_chunk_header(f)
        mcal_data_start = f.tell()
        # Read the entire MCAL data blob
        mcal_blob = f.read(mcal_chunk_size)

        # For each texture layer after the first, read its alpha data
        for i in range(1, len(texture_layers)):
            layer = texture_layers[i]
            layer_ofs = layer['offset_in_mcal']
            layer_flags = layer['flags']
            is_compressed = bool(layer_flags & (1 << 9))

            alpha_64x64 = [[0] * 64 for _ in range(64)]

            # Determine alpha type based on flags
            # highres = not broken. We assume highres for WotLK with
            # DO_NOT_FIX_ALPHA_MAP flag set.
            do_not_fix = bool(flags & (1 << 15))

            if is_compressed:
                # Compressed highres (4096 output values)
                alpha_flat = [0] * 4096
                blob_pos = layer_ofs
                out_pos = 0
                while out_pos < 4096 and blob_pos < len(mcal_blob):
                    cur_byte = mcal_blob[blob_pos]
                    blob_pos += 1
                    mode = bool(cur_byte >> 7)
                    count = cur_byte & 0x7F
                    if mode:  # fill
                        if blob_pos < len(mcal_blob):
                            fill_val = mcal_blob[blob_pos]
                            blob_pos += 1
                        else:
                            fill_val = 0
                        for _ in range(count):
                            if out_pos < 4096:
                                alpha_flat[out_pos] = fill_val
                                out_pos += 1
                    else:  # copy
                        for _ in range(count):
                            if out_pos < 4096 and blob_pos < len(mcal_blob):
                                alpha_flat[out_pos] = mcal_blob[blob_pos]
                                blob_pos += 1
                                out_pos += 1
                alpha_64x64 = [alpha_flat[r * 64:(r + 1) * 64] for r in range(64)]

            elif do_not_fix:
                # Uncompressed: check if highres (4096) or lowres (2048)
                # Highres if enough data remains
                remaining = len(mcal_blob) - layer_ofs
                if remaining >= 4096:
                    # Highres uncompressed (4096 bytes, 1 byte per pixel)
                    for r in range(64):
                        for c in range(64):
                            idx = layer_ofs + r * 64 + c
                            if idx < len(mcal_blob):
                                alpha_64x64[r][c] = mcal_blob[idx]
                else:
                    # Lowres uncompressed (2048 bytes, 4-bit per pixel)
                    alpha_flat = [0] * 4096
                    cur_pos = 0
                    for ii in range(2048):
                        idx = layer_ofs + ii
                        if idx >= len(mcal_blob):
                            break
                        cur_byte = mcal_blob[idx]
                        nibble1 = cur_byte & 0x0F
                        nibble2 = (cur_byte >> 4) & 0x0F
                        alpha_flat[ii + cur_pos] = nibble1 * 255 // 15
                        alpha_flat[ii + cur_pos + 1] = nibble2 * 255 // 15
                        cur_pos += 1
                    alpha_64x64 = [alpha_flat[r * 64:(r + 1) * 64] for r in range(64)]
            else:
                # "Broken" lowres (2048 bytes, needs last-row/col fix)
                alpha_flat = [0] * 4096
                cur_pos = 0
                for ii in range(2048):
                    idx = layer_ofs + ii
                    if idx >= len(mcal_blob):
                        break
                    cur_byte = mcal_blob[idx]
                    nibble1 = cur_byte & 0x0F
                    nibble2 = (cur_byte >> 4) & 0x0F
                    alpha_flat[ii + cur_pos] = nibble1 * 255 // 15
                    alpha_flat[ii + cur_pos + 1] = nibble2 * 255 // 15
                    cur_pos += 1
                alpha_64x64 = [alpha_flat[r * 64:(r + 1) * 64] for r in range(64)]
                # Apply broken fix
                for row in alpha_64x64:
                    row[63] = row[62]
                for c in range(64):
                    alpha_64x64[63][c] = alpha_64x64[62][c]

            alpha_maps.append(alpha_64x64)
    result['alpha_maps'] = alpha_maps

    # MCSH - shadow map (64x64 bit map = 512 bytes)
    shadow_map = None
    if (flags & 0x1) and ofs_mcsh:  # HAS_MCSH flag
        f.seek(mcnk_start + ofs_mcsh)
        _, mcsh_size = _read_chunk_header(f)
        if mcsh_size >= 512:
            shadow_flat = []
            for _ in range(512):
                b = _read_u8(f)
                for bit in range(8):
                    shadow_flat.append((b >> bit) & 1)
            shadow_map = [shadow_flat[r * 64:(r + 1) * 64] for r in range(64)]
    result['shadow_map'] = shadow_map

    # MCCV - vertex colors (145 * 4 uint8 BGRA)
    vertex_colors = None
    if (flags & 0x40) and ofs_mccv:  # HAS_MCCV flag
        f.seek(mcnk_start + ofs_mccv)
        _read_chunk_header(f)
        vertex_colors = []
        for _ in range(145):
            b = _read_u8(f)
            g = _read_u8(f)
            r = _read_u8(f)
            a = _read_u8(f)
            vertex_colors.append([r, g, b, a])
    result['vertex_colors'] = vertex_colors

    # MCSE - sound emitters
    sound_emitters = []
    if ofs_mcse and n_sound_emitters > 0:
        f.seek(mcnk_start + ofs_mcse)
        _read_chunk_header(f)
        for _ in range(n_sound_emitters):
            entry_id = _read_u32(f)
            pos = _read_vec3f(f)
            sz = _read_vec3f(f)
            sound_emitters.append({
                'entry_id': entry_id,
                'position': [_safe_float(v) for v in pos],
                'size': [_safe_float(v) for v in sz],
            })
    result['sound_emitters'] = sound_emitters

    return result


def _read_mcnk_header(f, mcnk_start):
    """
    Read the 128-byte MCNK header that follows the chunk header.
    Returns a dict with all header fields.
    """
    hdr = {}
    hdr['flags'] = _read_u32(f)
    hdr['index_x'] = _read_u32(f)
    hdr['index_y'] = _read_u32(f)
    hdr['n_layers'] = _read_u32(f)
    hdr['n_doodad_refs'] = _read_u32(f)
    hdr['ofs_mcvt'] = _read_u32(f)
    hdr['ofs_mcnr'] = _read_u32(f)
    hdr['ofs_mcly'] = _read_u32(f)
    hdr['ofs_mcrf'] = _read_u32(f)
    hdr['ofs_mcal'] = _read_u32(f)
    hdr['size_mcal'] = _read_u32(f)
    hdr['ofs_mcsh'] = _read_u32(f)
    hdr['size_mcsh'] = _read_u32(f)
    hdr['area_id'] = _read_u32(f)
    hdr['n_map_obj_refs'] = _read_u32(f)
    hdr['holes_low_res'] = _read_u16(f)
    hdr['unknown_but_used'] = _read_u16(f)

    # low_quality_texture_map: 8 rows, each row = 2 bytes = 8 nibble-pairs
    low_quality_tex = []
    for _ in range(8):
        row = []
        for _ in range(2):
            b = _read_u8(f)
            # 4 x 2-bit values per byte, LSB first
            row.append(b & 0x03)
            row.append((b >> 2) & 0x03)
            row.append((b >> 4) & 0x03)
            row.append((b >> 6) & 0x03)
        low_quality_tex.append(row)
    hdr['low_quality_texture_map'] = low_quality_tex

    # no_effect_doodad: 8 bytes, each byte = 8 bits
    no_effect_doodad = []
    for _ in range(8):
        b = _read_u8(f)
        row = []
        for bit in range(8):
            row.append((b >> bit) & 1)
        no_effect_doodad.append(row)
    hdr['no_effect_doodad'] = no_effect_doodad

    hdr['ofs_mcse'] = _read_u32(f)
    hdr['n_sound_emitters'] = _read_u32(f)
    hdr['ofs_mclq'] = _read_u32(f)
    hdr['size_liquid'] = _read_u32(f)
    hdr['position'] = [_safe_float(v) for v in struct.unpack('<3f', f.read(12))]
    hdr['ofs_mccv'] = _read_u32(f)
    hdr['ofs_mclv'] = _read_u32(f)
    hdr['unused'] = _read_u32(f)

    return hdr


def adt_to_json(adt_path):
    """Convert an ADT binary file to a JSON-serialisable dict."""
    filename = os.path.basename(adt_path)

    with open(adt_path, 'rb') as f:
        file_size = f.seek(0, 2)
        f.seek(0)

        # ---- MVER ----
        magic, size = _read_chunk_header(f)
        if magic != 'REVM':
            raise ValueError('Not a valid ADT file: expected REVM, got {}'.format(magic))
        version = _read_u32(f)

        # ---- MHDR ----
        magic, size = _read_chunk_header(f)
        if magic != 'RDHM':
            raise ValueError('Expected MHDR chunk, got {}'.format(magic))
        mhdr_data_start = f.tell()
        mhdr_flags = _read_u32(f)
        ofs_mcin = _read_u32(f)
        ofs_mtex = _read_u32(f)
        ofs_mmdx = _read_u32(f)
        ofs_mmid = _read_u32(f)
        ofs_mwmo = _read_u32(f)
        ofs_mwid = _read_u32(f)
        ofs_mddf = _read_u32(f)
        ofs_modf = _read_u32(f)
        ofs_mfbo = _read_u32(f)
        ofs_mh2o = _read_u32(f)
        ofs_mtxf = _read_u32(f)
        mamp_value = _read_u8(f)

        # ---- MCIN - chunk index (256 entries of 16 bytes) ----
        f.seek(mhdr_data_start + ofs_mcin)
        magic, size = _read_chunk_header(f)
        mcin_entries = []
        for _ in range(256):
            offset = _read_u32(f)
            sz = _read_u32(f)
            fl = _read_u32(f)
            async_id = _read_u32(f)
            mcin_entries.append({
                'offset': offset,
                'size': sz,
                'flags': fl,
                'async_id': async_id,
            })

        # ---- MTEX - textures ----
        f.seek(mhdr_data_start + ofs_mtex)
        magic, mtex_size = _read_chunk_header(f)
        mtex_data = f.read(mtex_size)
        textures = _parse_string_block(mtex_data)

        # ---- MMDX - M2 model filenames ----
        f.seek(mhdr_data_start + ofs_mmdx)
        magic, mmdx_size = _read_chunk_header(f)
        mmdx_data = f.read(mmdx_size)
        models = _parse_string_block(mmdx_data)

        # ---- MMID - M2 model offsets ----
        f.seek(mhdr_data_start + ofs_mmid)
        magic, mmid_size = _read_chunk_header(f)
        mmid_offsets = [_read_u32(f) for _ in range(mmid_size // 4)]

        # ---- MWMO - WMO filenames ----
        f.seek(mhdr_data_start + ofs_mwmo)
        magic, mwmo_size = _read_chunk_header(f)
        mwmo_data = f.read(mwmo_size)
        wmo_names = _parse_string_block(mwmo_data)

        # ---- MWID - WMO offsets ----
        f.seek(mhdr_data_start + ofs_mwid)
        magic, mwid_size = _read_chunk_header(f)
        mwid_offsets = [_read_u32(f) for _ in range(mwid_size // 4)]

        # ---- MDDF - doodad placements ----
        f.seek(mhdr_data_start + ofs_mddf)
        magic, mddf_size = _read_chunk_header(f)
        doodad_placements = []
        n_doodads = mddf_size // 36
        for _ in range(n_doodads):
            name_id = _read_u32(f)
            unique_id = _read_u32(f)
            pos = _read_vec3f(f)
            rot = _read_vec3f(f)
            scale = _read_u16(f)
            dd_flags = _read_u16(f)
            doodad_placements.append({
                'name_id': name_id,
                'unique_id': unique_id,
                'position': [_safe_float(v) for v in pos],
                'rotation': [_safe_float(v) for v in rot],
                'scale': scale,
                'flags': dd_flags,
            })

        # ---- MODF - WMO placements ----
        f.seek(mhdr_data_start + ofs_modf)
        magic, modf_size = _read_chunk_header(f)
        wmo_placements = []
        n_wmos = modf_size // 64
        for _ in range(n_wmos):
            name_id = _read_u32(f)
            unique_id = _read_u32(f)
            pos = _read_vec3f(f)
            rot = _read_vec3f(f)
            ext_min = _read_vec3f(f)
            ext_max = _read_vec3f(f)
            wmo_flags = _read_u16(f)
            doodad_set = _read_u16(f)
            name_set = _read_u16(f)
            wmo_scale = _read_u16(f)
            wmo_placements.append({
                'name_id': name_id,
                'unique_id': unique_id,
                'position': [_safe_float(v) for v in pos],
                'rotation': [_safe_float(v) for v in rot],
                'extents_min': [_safe_float(v) for v in ext_min],
                'extents_max': [_safe_float(v) for v in ext_max],
                'flags': wmo_flags,
                'doodad_set': doodad_set,
                'name_set': name_set,
                'scale': wmo_scale,
            })

        # ---- MFBO - flight bounds (optional) ----
        mfbo_data = None
        if ofs_mfbo and (mhdr_flags & 0x1):
            f.seek(mhdr_data_start + ofs_mfbo)
            magic, mfbo_size = _read_chunk_header(f)
            maximum = [[_read_i16(f) for _ in range(3)] for _ in range(3)]
            minimum = [[_read_i16(f) for _ in range(3)] for _ in range(3)]
            mfbo_data = {'maximum': maximum, 'minimum': minimum}

        # ---- MH2O - water data (optional, stored as raw bytes) ----
        mh2o_raw = None
        if ofs_mh2o:
            f.seek(mhdr_data_start + ofs_mh2o)
            magic, mh2o_size = _read_chunk_header(f)
            if mh2o_size > 0:
                mh2o_raw = list(f.read(mh2o_size))

        # ---- MTXF - texture flags (optional) ----
        mtxf_flags = None
        if ofs_mtxf:
            f.seek(mhdr_data_start + ofs_mtxf)
            magic, mtxf_size = _read_chunk_header(f)
            mtxf_flags = [_read_u32(f) for _ in range(mtxf_size // 4)]

        # ---- MCNK - terrain chunks (256 = 16x16) ----
        terrain_chunks = []
        for i in range(256):
            entry = mcin_entries[i]
            mcnk_start = entry['offset']
            f.seek(mcnk_start)

            magic, mcnk_size = _read_chunk_header(f)
            if magic != 'KNCM':
                raise ValueError(
                    'Expected MCNK chunk at offset {}, got {}'.format(
                        mcnk_start, magic))

            mcnk_header = _read_mcnk_header(f, mcnk_start)
            sub_data = _read_mcnk_subchunks(f, mcnk_start, mcnk_size, mcnk_header)

            chunk = {
                'index_x': mcnk_header['index_x'],
                'index_y': mcnk_header['index_y'],
                'flags': mcnk_header['flags'],
                'area_id': mcnk_header['area_id'],
                'holes_low_res': mcnk_header['holes_low_res'],
                'position': mcnk_header['position'],
                'n_layers': mcnk_header['n_layers'],
                'n_doodad_refs': mcnk_header['n_doodad_refs'],
                'n_map_obj_refs': mcnk_header['n_map_obj_refs'],
                'unknown_but_used': mcnk_header['unknown_but_used'],
                'low_quality_texture_map': mcnk_header['low_quality_texture_map'],
                'no_effect_doodad': mcnk_header['no_effect_doodad'],
                'size_mcal': mcnk_header['size_mcal'],
                'size_mcsh': mcnk_header['size_mcsh'],
                'size_liquid': mcnk_header['size_liquid'],
                'unused': mcnk_header['unused'],
                'heightmap': sub_data['heightmap'],
                'normals': sub_data['normals'],
                'texture_layers': sub_data['texture_layers'],
                'doodad_refs': sub_data['doodad_refs'],
                'object_refs': sub_data['object_refs'],
                'alpha_maps': sub_data['alpha_maps'],
                'shadow_map': sub_data['shadow_map'],
                'vertex_colors': sub_data['vertex_colors'],
                'sound_emitters': sub_data['sound_emitters'],
            }
            terrain_chunks.append(chunk)

    # Build output dict
    result = {
        '_meta': {
            'filename': filename,
            'version': version,
            'mhdr_flags': mhdr_flags,
            'mamp_value': mamp_value,
            'chunk_summary': {
                'textures': len(textures),
                'models': len(models),
                'wmo_names': len(wmo_names),
                'doodad_placements': len(doodad_placements),
                'wmo_placements': len(wmo_placements),
                'terrain_chunks': len(terrain_chunks),
            },
        },
        'textures': textures,
        'models': models,
        'wmo_names': wmo_names,
        'mmid_offsets': mmid_offsets,
        'mwid_offsets': mwid_offsets,
        'doodad_placements': doodad_placements,
        'wmo_placements': wmo_placements,
        'terrain_chunks': terrain_chunks,
    }

    if mfbo_data is not None:
        result['mfbo'] = mfbo_data
    if mh2o_raw is not None:
        result['mh2o_raw'] = mh2o_raw
    if mtxf_flags is not None:
        result['mtxf_flags'] = mtxf_flags

    return result


# ---------------------------------------------------------------------------
# JSON -> ADT
# ---------------------------------------------------------------------------

def _uint8_to_uint2_list_pack(vals):
    """Pack 4 x 2-bit values into a single byte, LSB first."""
    b = 0
    for i, v in enumerate(vals):
        b |= (v & 0x03) << (i * 2)
    return b

def _uint1_list_to_uint8_pack(vals):
    """Pack 8 x 1-bit values into a single byte, LSB first."""
    b = 0
    for i, v in enumerate(vals):
        b |= (v & 0x01) << i
    return b


def _compress_alpha_map(alpha_64x64):
    """Compress a 64x64 alpha map using the WoW RLE compression format.

    Returns bytes of compressed data.
    """
    alpha_flat = []
    for row in alpha_64x64:
        alpha_flat.extend(row)

    output = bytearray()
    pos = 0
    total = len(alpha_flat)

    while pos < total:
        # Look ahead: determine if fill or copy is better
        # Row boundary: compress per row of 64
        row_end = ((pos // 64) + 1) * 64
        if row_end > total:
            row_end = total

        # Try fill (run of same value)
        fill_val = alpha_flat[pos]
        fill_count = 0
        scan = pos
        while scan < row_end and alpha_flat[scan] == fill_val and fill_count < 127:
            fill_count += 1
            scan += 1

        if fill_count >= 2:
            # Use fill mode
            output.append(0x80 | fill_count)
            output.append(fill_val)
            pos += fill_count
        else:
            # Use copy mode - find how many to copy until we hit a run
            copy_start = pos
            copy_count = 0
            while pos < row_end and copy_count < 127:
                # Check if a run of 3+ starts here
                if pos + 2 < row_end:
                    if (alpha_flat[pos] == alpha_flat[pos + 1] ==
                            alpha_flat[pos + 2]):
                        break
                copy_count += 1
                pos += 1
            if copy_count > 0:
                output.append(copy_count)
                for i in range(copy_start, copy_start + copy_count):
                    output.append(alpha_flat[i])
            else:
                # Single value followed by a run
                output.append(1)
                output.append(alpha_flat[pos])
                pos += 1

    return bytes(output)


def _write_mcnk_subchunks(f, chunk_data, mcnk_abs_start):
    """Write all MCNK sub-chunks for a single terrain chunk.

    mcnk_abs_start is the absolute file position of the MCNK chunk header
    (the position of the 'KNCM' magic). All sub-chunk offsets in the MCNK
    header are relative to this position.

    Returns a dict of offsets for the sub-chunks relative to mcnk_abs_start.
    """
    offsets = {}

    # Reserve 128 bytes for the MCNK header (chunk header was already written)
    header_pos = f.tell()
    f.write(b'\x00' * 128)

    # ---- MCVT ----
    offsets['ofs_mcvt'] = f.tell() - mcnk_abs_start
    _write_chunk_header(f, 'TVCM', 580)
    for val in chunk_data['heightmap']:
        _write_f32(f, val)

    # ---- MCNR ----
    offsets['ofs_mcnr'] = f.tell() - mcnk_abs_start
    # MCNR data_size: 145*3 = 435 for header, but actual read includes
    # 13 unknown bytes. Header size is 435.
    _write_chunk_header(f, 'RNCM', 435)
    for n in chunk_data['normals']:
        _write_i8(f, n[0])
        _write_i8(f, n[1])
        _write_i8(f, n[2])
    # 13 unknown bytes (padding)
    f.write(b'\x00' * 13)

    # ---- MCLY ----
    offsets['ofs_mcly'] = f.tell() - mcnk_abs_start
    n_layers = chunk_data.get('n_layers', len(chunk_data.get('texture_layers', [])))
    texture_layers = chunk_data.get('texture_layers', [])
    _write_chunk_header(f, 'YLCM', len(texture_layers) * 16)

    # We need to know mcal offsets before writing MCLY, so we compute them
    # For now write placeholders and come back to fix offset_in_mcal
    mcly_pos = f.tell()
    for layer in texture_layers:
        _write_u32(f, layer['texture_id'])
        _write_u32(f, layer['flags'])
        _write_u32(f, layer.get('offset_in_mcal', 0))
        _write_u32(f, layer['effect_id'])

    # ---- MCRF ----
    offsets['ofs_mcrf'] = f.tell() - mcnk_abs_start
    doodad_refs = chunk_data.get('doodad_refs', [])
    object_refs = chunk_data.get('object_refs', [])
    mcrf_size = (len(doodad_refs) + len(object_refs)) * 4
    _write_chunk_header(f, 'FRCM', mcrf_size)
    for ref in doodad_refs:
        _write_u32(f, ref)
    for ref in object_refs:
        _write_u32(f, ref)

    # ---- MCSH (optional) ----
    flags = chunk_data.get('flags', 0)
    offsets['ofs_mcsh'] = 0
    offsets['size_mcsh'] = 0
    if (flags & 0x1) and chunk_data.get('shadow_map'):
        offsets['ofs_mcsh'] = f.tell() - mcnk_abs_start
        _write_chunk_header(f, 'HSCM', 512)
        sm = chunk_data['shadow_map']
        for r in range(64):
            for c in range(0, 64, 8):
                b = _uint1_list_to_uint8_pack(sm[r][c:c+8])
                _write_u8(f, b)
        offsets['size_mcsh'] = 512

    # ---- MCAL ----
    offsets['ofs_mcal'] = f.tell() - mcnk_abs_start
    alpha_maps = chunk_data.get('alpha_maps', [])
    mcal_start = f.tell()
    # Write chunk header placeholder - will update size
    _write_chunk_header(f, 'LACM', 0)
    mcal_data_start = f.tell()

    # Track actual offsets for each alpha layer for MCLY patching
    alpha_offsets = []
    for alpha_map in alpha_maps:
        alpha_offsets.append(f.tell() - mcal_data_start)
        # Determine compression from the corresponding layer flags
        layer_idx = len(alpha_offsets)  # 1-based (alpha layer i corresponds to texture layer i+1)
        if layer_idx < len(texture_layers):
            layer_flags = texture_layers[layer_idx]['flags']
        else:
            layer_flags = 0

        is_compressed = bool(layer_flags & (1 << 9))
        if is_compressed:
            compressed = _compress_alpha_map(alpha_map)
            f.write(compressed)
        else:
            # Check if highres or lowres based on DO_NOT_FIX_ALPHA_MAP flag
            do_not_fix = bool(flags & (1 << 15))
            if do_not_fix:
                # Highres uncompressed: 4096 bytes
                for row in alpha_map:
                    for val in row:
                        _write_u8(f, val)
            else:
                # Lowres: 2048 bytes (pack 2 pixels per byte)
                flat = []
                for row in alpha_map:
                    flat.extend(row)
                for i in range(0, 4096, 2):
                    nibble1 = flat[i] // (255 // 15) if flat[i] > 0 else 0
                    nibble2 = flat[i + 1] // (255 // 15) if flat[i + 1] > 0 else 0
                    _write_u8(f, nibble1 | (nibble2 << 4))

    mcal_end = f.tell()
    mcal_data_size = mcal_end - mcal_data_start
    # Patch MCAL header size
    f.seek(mcal_start + 4)  # skip magic
    _write_u32(f, mcal_data_size)
    f.seek(mcal_end)
    offsets['size_mcal'] = mcal_data_size

    # Patch MCLY offset_in_mcal values
    for i, ofs in enumerate(alpha_offsets):
        # texture_layers[i+1] corresponds to alpha_maps[i]
        layer_mcly_pos = mcly_pos + (i + 1) * 16 + 8  # +8 for tex_id + flags
        f.seek(layer_mcly_pos)
        _write_u32(f, ofs)
    f.seek(mcal_end)

    # ---- MCSE ----
    offsets['ofs_mcse'] = f.tell() - mcnk_abs_start
    sound_emitters = chunk_data.get('sound_emitters', [])
    _write_chunk_header(f, 'ESCM', len(sound_emitters) * 28)
    for se in sound_emitters:
        _write_u32(f, se['entry_id'])
        _write_vec3f(f, se['position'])
        _write_vec3f(f, se['size'])

    # ---- MCCV (optional) ----
    offsets['ofs_mccv'] = 0
    if (flags & 0x40) and chunk_data.get('vertex_colors'):
        offsets['ofs_mccv'] = f.tell() - mcnk_abs_start
        _write_chunk_header(f, 'VCCM', 580)
        for c in chunk_data['vertex_colors']:
            # stored as BGRA
            _write_u8(f, c[2])  # B
            _write_u8(f, c[1])  # G
            _write_u8(f, c[0])  # R
            _write_u8(f, c[3])  # A

    mcnk_end = f.tell()
    mcnk_total_data_size = mcnk_end - mcnk_abs_start - CHUNK_HEADER_SIZE
    offsets['mcnk_end'] = mcnk_end
    offsets['mcnk_data_size'] = mcnk_total_data_size

    # Now write the MCNK header at header_pos
    f.seek(header_pos)
    _write_u32(f, flags)
    _write_u32(f, chunk_data.get('index_x', 0))
    _write_u32(f, chunk_data.get('index_y', 0))
    _write_u32(f, n_layers)
    _write_u32(f, chunk_data.get('n_doodad_refs', len(doodad_refs)))
    _write_u32(f, offsets['ofs_mcvt'])
    _write_u32(f, offsets['ofs_mcnr'])
    _write_u32(f, offsets['ofs_mcly'])
    _write_u32(f, offsets['ofs_mcrf'])
    _write_u32(f, offsets['ofs_mcal'])
    _write_u32(f, offsets['size_mcal'])
    _write_u32(f, offsets['ofs_mcsh'])
    _write_u32(f, offsets['size_mcsh'])
    _write_u32(f, chunk_data.get('area_id', 0))
    _write_u32(f, chunk_data.get('n_map_obj_refs', len(object_refs)))
    _write_u16(f, chunk_data.get('holes_low_res', 0))
    _write_u16(f, chunk_data.get('unknown_but_used', 0))

    # low_quality_texture_map
    lqtm = chunk_data.get('low_quality_texture_map', [[0]*8 for _ in range(8)])
    for row in lqtm:
        _write_u8(f, _uint8_to_uint2_list_pack(row[0:4]))
        _write_u8(f, _uint8_to_uint2_list_pack(row[4:8]))

    # no_effect_doodad
    ned = chunk_data.get('no_effect_doodad', [[0]*8 for _ in range(8)])
    for row in ned:
        _write_u8(f, _uint1_list_to_uint8_pack(row))

    _write_u32(f, offsets['ofs_mcse'])
    _write_u32(f, chunk_data.get('n_sound_emitters', len(sound_emitters)))
    _write_u32(f, chunk_data.get('ofs_mclq', 0))
    _write_u32(f, chunk_data.get('size_liquid', 0))
    _write_vec3f(f, chunk_data.get('position', [0.0, 0.0, 0.0]))
    _write_u32(f, offsets['ofs_mccv'])
    _write_u32(f, 0)  # ofs_mclv - not supported
    _write_u32(f, chunk_data.get('unused', 0))

    f.seek(mcnk_end)
    return offsets


def json_to_adt(json_data, output_path):
    """Convert a JSON dict (as produced by adt_to_json) back to an ADT file."""
    meta = json_data['_meta']

    with open(output_path, 'wb') as f:
        # ---- MVER ----
        _write_chunk_header(f, 'REVM', 4)
        _write_u32(f, meta.get('version', 18))

        # ---- MHDR ----
        _write_chunk_header(f, 'RDHM', 54)
        mhdr_data_start = f.tell()
        # Write placeholder MHDR - we will come back and patch offsets
        f.write(b'\x00' * 54)

        # ---- MCIN - placeholder, will be patched ----
        ofs_mcin = f.tell() - mhdr_data_start
        _write_chunk_header(f, 'NICM', 256 * 16)
        mcin_pos = f.tell()
        f.write(b'\x00' * (256 * 16))

        # ---- MTEX ----
        ofs_mtex = f.tell() - mhdr_data_start
        textures = json_data.get('textures', [])
        mtex_blob = _build_string_block(textures)
        _write_chunk_header(f, 'XTEM', len(mtex_blob))
        f.write(mtex_blob)

        # ---- MMDX ----
        ofs_mmdx = f.tell() - mhdr_data_start
        models = json_data.get('models', [])
        mmdx_blob = _build_string_block(models)
        _write_chunk_header(f, 'XDMM', len(mmdx_blob))
        f.write(mmdx_blob)

        # ---- MMID ----
        ofs_mmid = f.tell() - mhdr_data_start
        mmid_offsets = json_data.get('mmid_offsets', _build_offset_table(models))
        _write_chunk_header(f, 'DIMM', len(mmid_offsets) * 4)
        for o in mmid_offsets:
            _write_u32(f, o)

        # ---- MWMO ----
        ofs_mwmo = f.tell() - mhdr_data_start
        wmo_names = json_data.get('wmo_names', [])
        mwmo_blob = _build_string_block(wmo_names)
        _write_chunk_header(f, 'OMWM', len(mwmo_blob))
        f.write(mwmo_blob)

        # ---- MWID ----
        ofs_mwid = f.tell() - mhdr_data_start
        mwid_offsets = json_data.get('mwid_offsets', _build_offset_table(wmo_names))
        _write_chunk_header(f, 'DIWM', len(mwid_offsets) * 4)
        for o in mwid_offsets:
            _write_u32(f, o)

        # ---- MDDF ----
        ofs_mddf = f.tell() - mhdr_data_start
        doodads = json_data.get('doodad_placements', [])
        _write_chunk_header(f, 'FDDM', len(doodads) * 36)
        for dd in doodads:
            _write_u32(f, dd['name_id'])
            _write_u32(f, dd['unique_id'])
            _write_vec3f(f, dd['position'])
            _write_vec3f(f, dd['rotation'])
            _write_u16(f, dd['scale'])
            _write_u16(f, dd['flags'])

        # ---- MODF ----
        ofs_modf = f.tell() - mhdr_data_start
        wmos = json_data.get('wmo_placements', [])
        _write_chunk_header(f, 'FDOM', len(wmos) * 64)
        for wmo in wmos:
            _write_u32(f, wmo['name_id'])
            _write_u32(f, wmo['unique_id'])
            _write_vec3f(f, wmo['position'])
            _write_vec3f(f, wmo['rotation'])
            _write_vec3f(f, wmo['extents_min'])
            _write_vec3f(f, wmo['extents_max'])
            _write_u16(f, wmo['flags'])
            _write_u16(f, wmo['doodad_set'])
            _write_u16(f, wmo['name_set'])
            _write_u16(f, wmo['scale'])

        # ---- MFBO (optional) ----
        ofs_mfbo = 0
        mhdr_flags = meta.get('mhdr_flags', 0)
        if 'mfbo' in json_data and (mhdr_flags & 0x1):
            ofs_mfbo = f.tell() - mhdr_data_start
            _write_chunk_header(f, 'OBFM', 36)
            mfbo = json_data['mfbo']
            for row in mfbo['maximum']:
                for v in row:
                    _write_i16(f, v)
            for row in mfbo['minimum']:
                for v in row:
                    _write_i16(f, v)

        # ---- MH2O (optional) ----
        ofs_mh2o = 0
        if 'mh2o_raw' in json_data:
            ofs_mh2o = f.tell() - mhdr_data_start
            mh2o_data = bytes(json_data['mh2o_raw'])
            _write_chunk_header(f, 'O2HM', len(mh2o_data))
            f.write(mh2o_data)

        # ---- MTXF (optional) ----
        ofs_mtxf = 0
        if 'mtxf_flags' in json_data:
            ofs_mtxf = f.tell() - mhdr_data_start
            mtxf = json_data['mtxf_flags']
            _write_chunk_header(f, 'FXTM', len(mtxf) * 4)
            for fl in mtxf:
                _write_u32(f, fl)

        # ---- MCNK chunks (256) ----
        terrain_chunks = json_data.get('terrain_chunks', [])
        mcnk_offsets = []  # (absolute_offset, total_size)
        for chunk_data in terrain_chunks:
            mcnk_abs_start = f.tell()
            _write_chunk_header(f, 'KNCM', 0)  # placeholder size
            sub_offsets = _write_mcnk_subchunks(f, chunk_data, mcnk_abs_start)
            # Patch MCNK chunk header size
            mcnk_data_size = sub_offsets['mcnk_data_size']
            f.seek(mcnk_abs_start + 4)  # skip magic
            _write_u32(f, mcnk_data_size)
            f.seek(sub_offsets['mcnk_end'])
            mcnk_offsets.append((mcnk_abs_start, mcnk_data_size + CHUNK_HEADER_SIZE))

        # ---- Patch MCIN entries ----
        f.seek(mcin_pos)
        for abs_ofs, total_size in mcnk_offsets:
            _write_u32(f, abs_ofs)
            _write_u32(f, total_size)
            _write_u32(f, 0)  # flags
            _write_u32(f, 0)  # async_id

        # ---- Patch MHDR ----
        f.seek(mhdr_data_start)
        _write_u32(f, mhdr_flags)
        _write_u32(f, ofs_mcin)
        _write_u32(f, ofs_mtex)
        _write_u32(f, ofs_mmdx)
        _write_u32(f, ofs_mmid)
        _write_u32(f, ofs_mwmo)
        _write_u32(f, ofs_mwid)
        _write_u32(f, ofs_mddf)
        _write_u32(f, ofs_modf)
        _write_u32(f, ofs_mfbo)
        _write_u32(f, ofs_mh2o)
        _write_u32(f, ofs_mtxf)
        _write_u8(f, meta.get('mamp_value', 0))


# ---------------------------------------------------------------------------
# Batch / directory conversion
# ---------------------------------------------------------------------------

def convert_directory(adt_dir, output_dir):
    """Batch-convert every .adt file in adt_dir to JSON in output_dir."""
    os.makedirs(output_dir, exist_ok=True)

    results = {'converted': [], 'failed': []}

    for filename in sorted(os.listdir(adt_dir)):
        if not filename.lower().endswith('.adt'):
            continue

        adt_path = os.path.join(adt_dir, filename)
        json_name = os.path.splitext(filename)[0] + '.json'
        json_path = os.path.join(output_dir, json_name)

        try:
            data = adt_to_json(adt_path)
            with open(json_path, 'w', encoding='utf-8') as jf:
                json.dump(data, jf, indent=2, ensure_ascii=False)

            summary = data['_meta']['chunk_summary']
            results['converted'].append({
                'file': filename,
                'textures': summary['textures'],
                'models': summary['models'],
                'chunks': summary['terrain_chunks'],
            })
            print("  OK  {:50s} {:>3} tex, {:>3} models, {:>3} chunks".format(
                filename, summary['textures'], summary['models'],
                summary['terrain_chunks']))
        except Exception as e:
            results['failed'].append({'file': filename, 'error': str(e)})
            print("  FAIL  {:50s} -- {}".format(filename, e))

    return results


# ---------------------------------------------------------------------------
# Round-trip test
# ---------------------------------------------------------------------------

def round_trip_test(adt_path):
    """ADT -> JSON -> ADT -> JSON, verify the two JSONs match."""
    import tempfile

    print("Round-trip test: {}".format(adt_path))

    # Step 1: ADT -> JSON1
    print("  Step 1: ADT -> JSON (pass 1)...")
    json1 = adt_to_json(adt_path)

    # Step 2: JSON1 -> ADT2
    with tempfile.NamedTemporaryFile(suffix='.adt', delete=False) as tmp:
        tmp_adt = tmp.name
    try:
        print("  Step 2: JSON -> ADT (rebuild)...")
        json_to_adt(json1, tmp_adt)

        # Step 3: ADT2 -> JSON2
        print("  Step 3: ADT -> JSON (pass 2)...")
        json2 = adt_to_json(tmp_adt)

        # Step 4: Compare JSON1 and JSON2
        print("  Step 4: Comparing JSON outputs...")
        # Compare key structural fields (skip _meta.filename since it differs)
        mismatches = []

        # Compare top-level lists
        for key in ['textures', 'models', 'wmo_names',
                     'doodad_placements', 'wmo_placements']:
            if json1.get(key) != json2.get(key):
                mismatches.append(key)

        # Compare terrain chunks - check key fields
        if len(json1.get('terrain_chunks', [])) != len(json2.get('terrain_chunks', [])):
            mismatches.append('terrain_chunks (count)')
        else:
            for i, (c1, c2) in enumerate(zip(json1['terrain_chunks'],
                                               json2['terrain_chunks'])):
                for field in ['index_x', 'index_y', 'flags', 'area_id',
                              'holes_low_res', 'n_layers',
                              'n_doodad_refs', 'n_map_obj_refs']:
                    if c1.get(field) != c2.get(field):
                        mismatches.append('chunk[{}].{}'.format(i, field))

                # Compare heightmaps with tolerance
                hm1 = c1.get('heightmap', [])
                hm2 = c2.get('heightmap', [])
                if len(hm1) == len(hm2):
                    for j, (h1, h2) in enumerate(zip(hm1, hm2)):
                        if abs(h1 - h2) > 0.01:
                            mismatches.append(
                                'chunk[{}].heightmap[{}]: {} vs {}'.format(
                                    i, j, h1, h2))
                            break
                else:
                    mismatches.append('chunk[{}].heightmap (length)'.format(i))

                # Compare texture layers
                tl1 = c1.get('texture_layers', [])
                tl2 = c2.get('texture_layers', [])
                if len(tl1) != len(tl2):
                    mismatches.append('chunk[{}].texture_layers (count)'.format(i))
                else:
                    for j, (l1, l2) in enumerate(zip(tl1, tl2)):
                        if l1.get('texture_id') != l2.get('texture_id'):
                            mismatches.append(
                                'chunk[{}].layer[{}].texture_id'.format(i, j))
                        if l1.get('effect_id') != l2.get('effect_id'):
                            mismatches.append(
                                'chunk[{}].layer[{}].effect_id'.format(i, j))

        if mismatches:
            print("  ROUND-TRIP DIFFERENCES ({} found):".format(len(mismatches)))
            for m in mismatches[:20]:
                print("    - {}".format(m))
            if len(mismatches) > 20:
                print("    ... and {} more".format(len(mismatches) - 20))
            return False
        else:
            print("  ROUND-TRIP OK: All key fields match.")
            return True

    finally:
        try:
            os.unlink(tmp_adt)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='ADT <-> JSON converter for WoW 3.3.5a (WotLK) terrain tiles')
    subparsers = parser.add_subparsers(dest='command')

    # -- adt2json -------------------------------------------------------
    p_a2j = subparsers.add_parser('adt2json', help='Convert ADT to JSON')
    p_a2j.add_argument('input', nargs='?', help='Input .adt file')
    p_a2j.add_argument('-o', '--output',
                       help='Output .json file (or directory with --dir)')
    p_a2j.add_argument('--dir',
                       help='Batch-convert all .adt files in a directory')
    p_a2j.add_argument('--round-trip', action='store_true',
                       help='Run round-trip verification after conversion')

    # -- json2adt -------------------------------------------------------
    p_j2a = subparsers.add_parser('json2adt', help='Convert JSON back to ADT')
    p_j2a.add_argument('input', help='Input .json file')
    p_j2a.add_argument('-o', '--output', help='Output .adt file')

    # -- roundtrip -------------------------------------------------------
    p_rt = subparsers.add_parser('roundtrip',
                                 help='Run ADT->JSON->ADT->JSON round-trip test')
    p_rt.add_argument('input', help='Input .adt file')

    args = parser.parse_args()

    if args.command == 'adt2json':
        if args.dir:
            output_dir = args.output or os.path.join(args.dir, 'json')
            print("Converting all .adt files in: {}".format(args.dir))
            print("Output directory: {}\n".format(output_dir))
            results = convert_directory(args.dir, output_dir)
            print("\n{} converted, {} failed".format(
                len(results['converted']), len(results['failed'])))
        elif args.input:
            output = args.output or os.path.splitext(args.input)[0] + '.json'
            data = adt_to_json(args.input)
            with open(output, 'w', encoding='utf-8') as jf:
                json.dump(data, jf, indent=2, ensure_ascii=False)
            summary = data['_meta']['chunk_summary']
            print("{} -> {} ({} textures, {} models, {} chunks)".format(
                args.input, output, summary['textures'],
                summary['models'], summary['terrain_chunks']))
            if args.round_trip:
                round_trip_test(args.input)
        else:
            p_a2j.print_help()

    elif args.command == 'json2adt':
        with open(args.input, 'r', encoding='utf-8') as jf:
            json_data = json.load(jf)
        output = args.output or os.path.splitext(args.input)[0] + '.adt'
        json_to_adt(json_data, output)
        n_chunks = len(json_data.get('terrain_chunks', []))
        print("{} -> {} ({} terrain chunks)".format(
            args.input, output, n_chunks))

    elif args.command == 'roundtrip':
        success = round_trip_test(args.input)
        sys.exit(0 if success else 1)

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
