"""
BLP texture file validator for WoW WotLK 3.3.5a.

Validates:
- BLP2 magic header
- Dimensions are powers of 2
- Mipmap offsets/sizes
- File not truncated
- Compression type check
"""

import os
import struct

from ..qa_validator import ValidationResult, ValidationSeverity


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BLP2_MAGIC = b'BLP2'
_BLP_HEADER_SIZE = 148  # BLP2 header size (without palette)

# Valid BLP dimensions (powers of 2)
_VALID_DIMENSIONS = {1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096}

# Compression types
_COMPRESS_JPEG = 0
_COMPRESS_PALETTE = 1
_COMPRESS_DXT = 2

# Alpha encoding
_ALPHA_DXT1 = 0
_ALPHA_DXT3 = 1
_ALPHA_DXT5 = 7

_MAX_MIPMAPS = 16


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _find_blp_files(client_dir):
    """Find all BLP files under client_dir."""
    blp_files = []
    if not client_dir or not os.path.isdir(client_dir):
        return blp_files

    for root, _dirs, files in os.walk(client_dir):
        for fname in files:
            if fname.lower().endswith('.blp'):
                blp_files.append(os.path.join(root, fname))

    return blp_files


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_blp_files(client_dir):
    """
    Validate all BLP files found under client_dir.

    Returns:
        List of ValidationResult objects.
    """
    results = []

    blp_files = _find_blp_files(client_dir)

    if not blp_files:
        results.append(ValidationResult(
            check_id='BLP-001',
            severity=ValidationSeverity.INFO,
            passed=True,
            message="No BLP files found to validate",
        ))
        return results

    for blp_path in blp_files:
        fname = os.path.basename(blp_path)

        try:
            with open(blp_path, 'rb') as f:
                data = f.read()
        except IOError as exc:
            results.append(ValidationResult(
                check_id='BLP-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="Cannot read BLP {}: {}".format(fname, exc),
            ))
            continue

        # BLP-001: Magic header
        if len(data) < 4:
            results.append(ValidationResult(
                check_id='BLP-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="BLP {} too small ({} bytes)".format(
                    fname, len(data)),
                fix_suggestion="Regenerate with PNG2BLP",
            ))
            continue

        magic = data[0:4]
        if magic == _BLP2_MAGIC:
            results.append(ValidationResult(
                check_id='BLP-001',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="BLP {} magic header BLP2 verified".format(fname),
            ))
        else:
            results.append(ValidationResult(
                check_id='BLP-001',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="BLP {} bad magic: {!r}".format(fname, magic),
                fix_suggestion="Regenerate with PNG2BLP",
            ))
            continue

        if len(data) < _BLP_HEADER_SIZE:
            results.append(ValidationResult(
                check_id='BLP-004',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="BLP {} header truncated ({} bytes)".format(
                    fname, len(data)),
                fix_suggestion="Check PNG2BLP conversion logs",
            ))
            continue

        # Parse header fields
        compression = struct.unpack_from('<I', data, 4)[0]
        alpha_depth = struct.unpack_from('<I', data, 8)[0]
        alpha_encoding = struct.unpack_from('<I', data, 12)[0]
        has_mipmaps = struct.unpack_from('<I', data, 16)[0]
        width = struct.unpack_from('<I', data, 20)[0]
        height = struct.unpack_from('<I', data, 24)[0]

        # Mipmap offsets (16 entries at offset 28)
        mip_offsets = []
        for mi in range(_MAX_MIPMAPS):
            off = struct.unpack_from('<I', data, 28 + mi * 4)[0]
            mip_offsets.append(off)

        # Mipmap sizes (16 entries at offset 92)
        mip_sizes = []
        for mi in range(_MAX_MIPMAPS):
            sz = struct.unpack_from('<I', data, 92 + mi * 4)[0]
            mip_sizes.append(sz)

        # BLP-002: Dimensions are powers of 2
        w_ok = width in _VALID_DIMENSIONS
        h_ok = height in _VALID_DIMENSIONS
        if w_ok and h_ok:
            results.append(ValidationResult(
                check_id='BLP-002',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="BLP {} dimensions {}x{} valid".format(
                    fname, width, height),
            ))
        else:
            results.append(ValidationResult(
                check_id='BLP-002',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="BLP {} dimensions {}x{} not power of 2".format(
                    fname, width, height),
                fix_suggestion="Resize source PNG before conversion",
            ))

        # BLP-003: Mipmap offsets/sizes valid
        mip_ok = True
        active_mips = 0
        for mi in range(_MAX_MIPMAPS):
            if mip_offsets[mi] == 0 and mip_sizes[mi] == 0:
                break
            active_mips += 1
            if mip_offsets[mi] + mip_sizes[mi] > len(data):
                mip_ok = False

        if mip_ok:
            results.append(ValidationResult(
                check_id='BLP-003',
                severity=ValidationSeverity.WARNING,
                passed=True,
                message="BLP {} has {} valid mipmaps".format(
                    fname, active_mips),
            ))
        else:
            results.append(ValidationResult(
                check_id='BLP-003',
                severity=ValidationSeverity.WARNING,
                passed=False,
                message="BLP {} has invalid mipmap offsets/sizes".format(
                    fname),
                fix_suggestion="Regenerate with proper mipmaps",
            ))

        # BLP-004: File not truncated
        # Check that the last active mipmap's data fits within file
        max_end = 0
        for mi in range(active_mips):
            end = mip_offsets[mi] + mip_sizes[mi]
            if end > max_end:
                max_end = end

        if max_end <= len(data):
            results.append(ValidationResult(
                check_id='BLP-004',
                severity=ValidationSeverity.ERROR,
                passed=True,
                message="BLP {} size {} bytes, data ends at {}".format(
                    fname, len(data), max_end),
            ))
        else:
            results.append(ValidationResult(
                check_id='BLP-004',
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="BLP {} truncated: needs {} bytes, has {}".format(
                    fname, max_end, len(data)),
                fix_suggestion="Check PNG2BLP conversion logs",
            ))

        # BLP-005: Compression type
        compress_name = {
            _COMPRESS_JPEG: "JPEG",
            _COMPRESS_PALETTE: "Palette",
            _COMPRESS_DXT: "DXT",
        }.get(compression, "Unknown({})".format(compression))

        if compression in (_COMPRESS_JPEG, _COMPRESS_PALETTE, _COMPRESS_DXT):
            results.append(ValidationResult(
                check_id='BLP-005',
                severity=ValidationSeverity.INFO,
                passed=True,
                message="BLP {} compression: {}".format(
                    fname, compress_name),
            ))
        else:
            results.append(ValidationResult(
                check_id='BLP-005',
                severity=ValidationSeverity.INFO,
                passed=False,
                message="BLP {} unknown compression type: {}".format(
                    fname, compression),
                fix_suggestion="Use DXT1/DXT3/DXT5 or uncompressed",
            ))

    return results
