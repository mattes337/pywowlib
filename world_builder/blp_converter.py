"""
BLP texture converter for WoW WotLK 3.3.5a.

Provides convenience functions for converting between BLP and PNG/PIL Image:
  - PNG/PIL -> BLP (write): native PNG2BLP DXT when available, pure-Python
    DXT1/DXT5 compression fallback, or uncompressed BGRA fallback.
  - BLP -> PNG/PIL (read): pure-Python BLP2 reader supporting DXT1, DXT3,
    DXT5 compressed and uncompressed BGRA textures.

BLP2 header layout (148 bytes):
    - Magic 'BLP2'            4 bytes
    - Type (1=BLP2)           4 bytes (uint32)
    - Compression             1 byte  (1/2=DXT, 3=raw)
    - AlphaDepth              1 byte
    - AlphaType               1 byte  (0=DXT1, 1=DXT3, 7=DXT5)
    - HasMips                 1 byte
    - Width                   4 bytes (uint32)
    - Height                  4 bytes (uint32)
    - MipmapOffsets[16]       64 bytes (16 * uint32)
    - MipmapSizes[16]         64 bytes (16 * uint32)

PNG2BLP native API (when available):
  BlpFromPng(png_bytes, size) -> converter object
  converter.create_blp_dxt_in_memory(mipmaps, dxt_format) -> bytes
  converter.create_blp_uncompressed_in_memory(mipmaps) -> bytes
"""

import struct
import os
import io
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Try to import the PNG2BLP native extension.
_HAS_PNG2BLP = False
try:
    from blp import PNG2BLP as BlpFromPng
    _HAS_PNG2BLP = True
except Exception:
    BlpFromPng = None

# Try to import PIL for image handling.
try:
    from PIL import Image
except ImportError:
    Image = None

# ---------------------------------------------------------------------------
# DXT format constants (matching native Png2Blp.h)
# ---------------------------------------------------------------------------
_FORMAT_DXT1 = 0
_FORMAT_DXT3 = 1
_FORMAT_DXT5 = 2

# Friendly name -> native constant mapping
_COMPRESSION_MAP = {
    'dxt1': _FORMAT_DXT1,
    'dxt3': _FORMAT_DXT3,
    'dxt5': _FORMAT_DXT5,
}

# ---------------------------------------------------------------------------
# BLP2 header layout constants
# ---------------------------------------------------------------------------
_BLP2_MAGIC = b'BLP2'
_BLP2_HEADER_SIZE = 148
_BLP2_TYPE = 1           # BLP2 type identifier
_BLP2_COMP_DXT = 2       # compression type 2 = DXTC
_BLP2_COMP_RAW = 3       # compression type 3 = uncompressed ARGB
_BLP2_ALPHA_DEPTH = 8    # 8-bit alpha channel
_BLP2_ALPHA_TYPE = 8     # BGRA type
_BLP2_MIP_COUNT = 16     # mipmap offset/size array length

# BLPPixelFormat values (stored at header offset 0x0A / 10)
# These define how pixel data is encoded
_BLP2_PIXEL_DXT1 = 0
_BLP2_PIXEL_DXT3 = 1
_BLP2_PIXEL_ARGB8888 = 2
_BLP2_PIXEL_ARGB1555 = 3
_BLP2_PIXEL_ARGB4444 = 4
_BLP2_PIXEL_RGB565 = 5
_BLP2_PIXEL_A8 = 6
_BLP2_PIXEL_DXT5 = 7
_BLP2_PIXEL_UNSPECIFIED = 8

# Legacy aliases for backward compatibility
_BLP2_ALPHA_DXT1 = 0
_BLP2_ALPHA_DXT3 = 1
_BLP2_ALPHA_DXT5 = 7

# Compression type name mapping for info display
_COMPRESSION_NAMES = {
    1: 'Palette',
    2: 'DXT',
    3: 'Uncompressed ARGB8888',
}

_ALPHA_TYPE_NAMES = {
    0: 'DXT1',
    1: 'DXT3',
    2: 'ARGB8888',
    3: 'ARGB1555',
    4: 'ARGB4444',
    5: 'RGB565',
    6: 'A8',
    7: 'DXT5',
    8: 'Unspecified',
}


# ---------------------------------------------------------------------------
# Public API -- BLP Reader
# ---------------------------------------------------------------------------

def read_blp(blp_path_or_data):
    """
    Read a BLP2 file and return a PIL Image object.

    Supports DXT1, DXT3, DXT5 compressed textures and uncompressed BGRA.
    Only the first (full-resolution) mipmap level is decoded.

    Args:
        blp_path_or_data: File path (str/Path) or raw bytes.

    Returns:
        PIL.Image.Image: RGBA image.

    Raises:
        RuntimeError: If PIL is not available.
        ValueError: If the file is not a valid BLP2 file or uses an
                     unsupported compression format.
    """
    if Image is None:
        raise RuntimeError("PIL (Pillow) is required for read_blp")

    if isinstance(blp_path_or_data, (str, Path)):
        with open(str(blp_path_or_data), 'rb') as f:
            data = f.read()
    else:
        data = bytes(blp_path_or_data)

    if len(data) < _BLP2_HEADER_SIZE:
        raise ValueError(
            "File too short for BLP2 header: {} bytes".format(len(data))
        )

    # Parse header
    magic = data[0:4]
    if magic != _BLP2_MAGIC:
        raise ValueError(
            "Invalid BLP magic: {!r} (expected {!r})".format(magic, _BLP2_MAGIC)
        )

    compression = struct.unpack_from('<B', data, 8)[0]
    alpha_depth = struct.unpack_from('<B', data, 9)[0]
    alpha_type = struct.unpack_from('<B', data, 10)[0]
    width = struct.unpack_from('<I', data, 12)[0]
    height = struct.unpack_from('<I', data, 16)[0]

    # Read mipmap 0 offset and size
    mip0_offset = struct.unpack_from('<I', data, 20)[0]
    mip0_size = struct.unpack_from('<I', data, 84)[0]

    if mip0_offset == 0 or mip0_size == 0:
        raise ValueError("BLP2 file has no mipmap 0 data")

    if mip0_offset + mip0_size > len(data):
        raise ValueError(
            "Mipmap 0 data extends beyond file: offset={}, size={}, "
            "file_size={}".format(mip0_offset, mip0_size, len(data))
        )

    mip_data = data[mip0_offset:mip0_offset + mip0_size]

    # Decode based on compression type (colorEncoding)
    # compression 1 = COLOR_PALETTE (indexed with 256-color palette)
    # compression 2 = COLOR_DXT (DXTC compressed)
    # compression 3 = COLOR_ARGB8888 (uncompressed ARGB8888)
    
    if compression == 1:
        # Palette-based: read 256-color palette after header, then indexed pixels
        palette_offset = _BLP2_HEADER_SIZE
        palette = []
        for i in range(256):
            b = data[palette_offset + i * 4]
            g = data[palette_offset + i * 4 + 1]
            r = data[palette_offset + i * 4 + 2]
            a = data[palette_offset + i * 4 + 3] if alpha_depth > 0 else 255
            palette.append((r, g, b, a))
        pixels = _decode_palette(mip_data, width, height, palette, alpha_depth, data, mip0_offset, mip0_size)
        
    elif compression == 2:
        # DXTC compressed - preferredFormat indicates DXT type
        if alpha_type == _BLP2_PIXEL_DXT1:
            pixels = _decode_dxt1(mip_data, width, height)
        elif alpha_type == _BLP2_PIXEL_DXT3:
            pixels = _decode_dxt3(mip_data, width, height)
        elif alpha_type == _BLP2_PIXEL_DXT5:
            pixels = _decode_dxt5(mip_data, width, height)
        elif alpha_type == _BLP2_PIXEL_ARGB8888:
            # Some files have compression=2 but ARGB8888 pixel format
            pixels = _decode_uncompressed(mip_data, width, height)
        elif alpha_type == _BLP2_PIXEL_UNSPECIFIED:
            # Unspecified format with compression=2, try to determine from data size
            expected_dxt1 = ((width + 3) // 4) * ((height + 3) // 4) * 8
            expected_dxt5 = ((width + 3) // 4) * ((height + 3) // 4) * 16
            expected_raw = width * height * 4
            
            if mip0_size == expected_dxt1:
                pixels = _decode_dxt1(mip_data, width, height)
            elif mip0_size == expected_dxt5:
                pixels = _decode_dxt5(mip_data, width, height)
            elif mip0_size >= expected_raw:
                pixels = _decode_uncompressed(mip_data, width, height)
            else:
                # Default to DXT1 if we can't determine
                pixels = _decode_dxt1(mip_data, width, height)
        else:
            raise ValueError(
                "Unsupported pixel format: {} for compression 2".format(alpha_type)
            )
            
    elif compression == 3 or compression == _BLP2_COMP_RAW:
        # Uncompressed ARGB8888
        pixels = _decode_uncompressed(mip_data, width, height)
    else:
        raise ValueError(
            "Unsupported BLP2 compression type: {}".format(compression)
        )

    image = Image.frombytes('RGBA', (width, height), bytes(pixels))
    return image


def read_blp_info(blp_path_or_data):
    """
    Read BLP2 header information without decoding pixel data.

    Args:
        blp_path_or_data: File path (str/Path) or raw bytes.

    Returns:
        dict: Header fields including magic, compression, dimensions,
              alpha info, mipmap count, and total file size.
    """
    if isinstance(blp_path_or_data, (str, Path)):
        with open(str(blp_path_or_data), 'rb') as f:
            data = f.read()
    else:
        data = bytes(blp_path_or_data)

    if len(data) < _BLP2_HEADER_SIZE:
        return {'valid': False, 'error': 'File too short', 'file_size': len(data)}

    magic = data[0:4]
    blp_type = struct.unpack_from('<I', data, 4)[0]
    compression = struct.unpack_from('<B', data, 8)[0]
    alpha_depth = struct.unpack_from('<B', data, 9)[0]
    alpha_type = struct.unpack_from('<B', data, 10)[0]
    has_mips = struct.unpack_from('<B', data, 11)[0]
    width = struct.unpack_from('<I', data, 12)[0]
    height = struct.unpack_from('<I', data, 16)[0]

    # Count mipmaps with nonzero size
    mip_count = 0
    for i in range(_BLP2_MIP_COUNT):
        mip_size = struct.unpack_from('<I', data, 84 + i * 4)[0]
        if mip_size > 0:
            mip_count += 1
        else:
            break

    # Determine compression name
    comp_name = _COMPRESSION_NAMES.get(compression, 'Unknown ({})'.format(compression))
    if compression in (1, 2):
        alpha_name = _ALPHA_TYPE_NAMES.get(alpha_type, 'Unknown ({})'.format(alpha_type))
        comp_name = alpha_name
    else:
        alpha_name = _ALPHA_TYPE_NAMES.get(alpha_type, 'Unknown ({})'.format(alpha_type))

    return {
        'valid': magic == _BLP2_MAGIC,
        'magic': magic.decode('ascii', errors='replace'),
        'type': blp_type,
        'compression': compression,
        'compression_name': comp_name,
        'alpha_depth': alpha_depth,
        'alpha_type': alpha_type,
        'alpha_type_name': alpha_name,
        'has_mips': has_mips,
        'width': width,
        'height': height,
        'mipmap_count': mip_count,
        'file_size': len(data),
    }


def convert_blp_to_png(blp_path, png_path):
    """
    Convert a BLP file to PNG using the pure-Python reader.

    Args:
        blp_path: Input BLP file path (str or Path).
        png_path: Output PNG file path (str or Path).

    Raises:
        FileNotFoundError: If the input BLP file does not exist.
    """
    blp_path = str(blp_path)
    png_path = str(png_path)

    if not os.path.isfile(blp_path):
        raise FileNotFoundError("BLP file not found: {}".format(blp_path))

    image = read_blp(blp_path)
    os.makedirs(os.path.dirname(os.path.abspath(png_path)), exist_ok=True)
    image.save(png_path, 'PNG')

    log.info("Converted %s -> %s (%dx%d)", blp_path, png_path,
             image.width, image.height)


def batch_convert_blp_to_png(input_dir, output_dir, pattern='*.blp'):
    """
    Convert a directory of BLP files to PNG format.

    Args:
        input_dir: Directory containing BLP files (str or Path).
        output_dir: Output directory for PNG files (str or Path).
        pattern: Glob pattern for input files. Default '*.blp'.

    Returns:
        list: Paths to the generated PNG files (as strings).
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    results = []
    for blp_file in sorted(input_path.glob(pattern)):
        png_file = output_path / "{}.png".format(blp_file.stem)
        try:
            convert_blp_to_png(str(blp_file), str(png_file))
            results.append(str(png_file))
        except Exception:
            log.exception("Failed to convert %s", blp_file)

    log.info(
        "Batch converted %d BLP files from %s to %s",
        len(results), input_dir, output_dir,
    )
    return results


# ---------------------------------------------------------------------------
# Public API -- BLP Writer (PNG/PIL -> BLP)
# ---------------------------------------------------------------------------

def convert_png_to_blp(png_path, blp_path, compression='dxt1'):
    """
    Convert a PNG file to BLP format.

    Uses the native PNG2BLP extension for DXT compression when available.
    Falls back to pure-Python DXT or uncompressed BLP2 writer via PIL if
    the native extension is not built.

    Args:
        png_path: Input PNG file path (str or Path).
        blp_path: Output BLP file path (str or Path).
        compression: Compression type: 'dxt1', 'dxt3', 'dxt5',
                     or 'uncompressed'. Default 'dxt1'.

    Raises:
        FileNotFoundError: If the input PNG file does not exist.
        RuntimeError: If neither PNG2BLP nor PIL is available.
    """
    png_path = str(png_path)
    blp_path = str(blp_path)

    if not os.path.isfile(png_path):
        raise FileNotFoundError("PNG file not found: {}".format(png_path))

    with open(png_path, 'rb') as f:
        png_data = f.read()

    if _HAS_PNG2BLP and compression != 'uncompressed':
        blp_bytes = _convert_png_bytes(png_data, compression)
    else:
        # Use PIL-based fallback (pure-Python DXT or uncompressed)
        if Image is None:
            raise RuntimeError(
                "Neither PNG2BLP native extension nor PIL is available. "
                "Build the native extensions or install Pillow."
            )
        pil_image = Image.open(io.BytesIO(png_data))
        blp_bytes = image_to_blp(pil_image, compression)

    os.makedirs(os.path.dirname(os.path.abspath(blp_path)), exist_ok=True)
    with open(blp_path, 'wb') as f:
        f.write(blp_bytes)

    log.info("Converted %s -> %s (%d bytes)", png_path, blp_path, len(blp_bytes))


def image_to_blp(pil_image, compression='dxt1'):
    """
    Convert a PIL Image object to BLP file bytes.

    This is the primary function for the artwork pipeline which generates
    images in memory using Pillow.

    Strategy:
      1. Try native PNG2BLP (save Image as in-memory PNG bytes, pass to native)
      2. Fall back to pure-Python DXT compression for dxt1/dxt5
      3. Fall back to uncompressed BLP2 writer for other cases

    Args:
        pil_image: PIL Image object. Will be converted to RGBA if needed.
        compression: Compression type: 'dxt1', 'dxt3', 'dxt5',
                     or 'uncompressed'. Default 'dxt1'.

    Returns:
        bytes: Complete BLP file content.

    Raises:
        RuntimeError: If PIL is not available and the image cannot be processed.
    """
    if pil_image.mode != 'RGBA':
        pil_image = pil_image.convert('RGBA')

    # Try native PNG2BLP first (for all DXT formats)
    if _HAS_PNG2BLP and compression != 'uncompressed':
        png_buf = io.BytesIO()
        pil_image.save(png_buf, format='PNG')
        png_bytes = png_buf.getvalue()
        return _convert_png_bytes(png_bytes, compression)

    # Pure-Python fallback
    comp_lower = compression.lower() if isinstance(compression, str) else compression
    if comp_lower == 'dxt1':
        if not _HAS_PNG2BLP:
            log.info(
                "PNG2BLP not available, using pure-Python DXT1 for %dx%d image",
                pil_image.width, pil_image.height,
            )
        return _image_to_blp_dxt1(pil_image)
    elif comp_lower == 'dxt5':
        if not _HAS_PNG2BLP:
            log.info(
                "PNG2BLP not available, using pure-Python DXT5 for %dx%d image",
                pil_image.width, pil_image.height,
            )
        return _image_to_blp_dxt5(pil_image)
    elif comp_lower == 'dxt3':
        # DXT3 not implemented in pure-Python, fall back to uncompressed
        log.warning(
            "Pure-Python DXT3 not available, using uncompressed fallback "
            "for %dx%d image",
            pil_image.width, pil_image.height,
        )
        return _image_to_blp_uncompressed(pil_image)
    else:
        # 'uncompressed' or unknown -> uncompressed
        return _image_to_blp_uncompressed(pil_image)


def batch_convert(input_dir, output_dir, pattern='*.png'):
    """
    Convert a directory of PNG files to BLP format.

    Args:
        input_dir: Directory containing PNG files (str or Path).
        output_dir: Output directory for BLP files (str or Path).
        pattern: Glob pattern for input files. Default '*.png'.

    Returns:
        list: Paths to the generated BLP files (as strings).
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    results = []
    for png_file in sorted(input_path.glob(pattern)):
        blp_file = output_path / "{}.blp".format(png_file.stem)
        try:
            convert_png_to_blp(str(png_file), str(blp_file))
            results.append(str(blp_file))
        except Exception:
            log.exception("Failed to convert %s", png_file)

    log.info(
        "Batch converted %d/%d files from %s to %s",
        len(results),
        len(list(input_path.glob(pattern))),
        input_dir,
        output_dir,
    )
    return results


def validate_blp(blp_data):
    """
    Basic BLP file validation.

    Checks magic header, dimensions, and that pixel data exists beyond
    the header.

    Args:
        blp_data: BLP file bytes, or a file path (str or Path) to read.

    Returns:
        dict: {
            'valid': bool,
            'magic': str,
            'width': int,
            'height': int,
            'compression': int,
            'errors': list of str,
        }
    """
    if isinstance(blp_data, (str, Path)):
        with open(str(blp_data), 'rb') as f:
            data = f.read()
    else:
        data = blp_data

    result = {
        'valid': False,
        'magic': '',
        'width': 0,
        'height': 0,
        'compression': 0,
        'errors': [],
    }

    # Check minimum length for header
    if len(data) < _BLP2_HEADER_SIZE:
        result['errors'].append(
            "File too short: {} bytes (need at least {})".format(
                len(data), _BLP2_HEADER_SIZE
            )
        )
        return result

    # Check magic
    magic = data[0:4]
    result['magic'] = magic.decode('ascii', errors='replace')
    if magic != _BLP2_MAGIC:
        result['errors'].append(
            "Invalid magic: {!r} (expected {!r})".format(magic, _BLP2_MAGIC)
        )

    # Parse compression (offset 8, uint8)
    compression = struct.unpack_from('<B', data, 8)[0]
    result['compression'] = compression

    # Parse dimensions (offset 12 and 16, uint32)
    width = struct.unpack_from('<I', data, 12)[0]
    height = struct.unpack_from('<I', data, 16)[0]
    result['width'] = width
    result['height'] = height

    if width == 0 or height == 0:
        result['errors'].append(
            "Invalid dimensions: {}x{}".format(width, height)
        )

    # Check that at least the first mipmap offset points to data
    if len(data) > 20:
        first_mip_offset = struct.unpack_from('<I', data, 20)[0]
        if first_mip_offset > 0 and first_mip_offset >= len(data):
            result['errors'].append(
                "First mipmap offset ({}) beyond file size ({})".format(
                    first_mip_offset, len(data)
                )
            )

    # Check file has data beyond header
    if len(data) <= _BLP2_HEADER_SIZE:
        result['errors'].append("No pixel data after header")

    result['valid'] = len(result['errors']) == 0
    return result


# ---------------------------------------------------------------------------
# Internal helpers -- DXT decompression (BLP reader)
# ---------------------------------------------------------------------------

def _decode_rgb565(value):
    """Decode a 16-bit RGB565 value to (r, g, b) tuple with 8-bit channels."""
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    # Expand to 8-bit: replicate high bits into low bits
    r = (r << 3) | (r >> 2)
    g = (g << 2) | (g >> 4)
    b = (b << 3) | (b >> 2)
    return (r, g, b)


def _decode_dxt1_block(block_data, offset):
    """
    Decode a single DXT1 4x4 block (8 bytes) into 16 RGBA pixels.

    Args:
        block_data: Raw bytes containing the block.
        offset: Starting byte offset of the block.

    Returns:
        list: 16 (r, g, b, a) tuples, row-major order (y=0..3, x=0..3).
    """
    c0_val = struct.unpack_from('<H', block_data, offset)[0]
    c1_val = struct.unpack_from('<H', block_data, offset + 2)[0]

    r0, g0, b0 = _decode_rgb565(c0_val)
    r1, g1, b1 = _decode_rgb565(c1_val)

    # Build color table
    if c0_val > c1_val:
        # 4-color mode (opaque)
        colors = [
            (r0, g0, b0, 255),
            (r1, g1, b1, 255),
            ((2 * r0 + r1 + 1) // 3, (2 * g0 + g1 + 1) // 3,
             (2 * b0 + b1 + 1) // 3, 255),
            ((r0 + 2 * r1 + 1) // 3, (g0 + 2 * g1 + 1) // 3,
             (b0 + 2 * b1 + 1) // 3, 255),
        ]
    else:
        # 3-color + transparent mode
        colors = [
            (r0, g0, b0, 255),
            (r1, g1, b1, 255),
            ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255),
            (0, 0, 0, 0),
        ]

    # Decode 2-bit indices (4 bytes = 16 pixels)
    pixels = []
    for row in range(4):
        bits = block_data[offset + 4 + row]
        for col in range(4):
            idx = (bits >> (col * 2)) & 0x03
            pixels.append(colors[idx])

    return pixels


def _decode_dxt1_block_opaque(block_data, offset):
    """
    Decode a DXT1 color block always using 4-color opaque mode.
    Used as the color sub-block inside DXT3 and DXT5 blocks.

    Returns:
        list: 16 (r, g, b) tuples.
    """
    c0_val = struct.unpack_from('<H', block_data, offset)[0]
    c1_val = struct.unpack_from('<H', block_data, offset + 2)[0]

    r0, g0, b0 = _decode_rgb565(c0_val)
    r1, g1, b1 = _decode_rgb565(c1_val)

    # Always 4-color opaque mode for DXT3/DXT5 color sub-block
    colors = [
        (r0, g0, b0),
        (r1, g1, b1),
        ((2 * r0 + r1 + 1) // 3, (2 * g0 + g1 + 1) // 3,
         (2 * b0 + b1 + 1) // 3),
        ((r0 + 2 * r1 + 1) // 3, (g0 + 2 * g1 + 1) // 3,
         (b0 + 2 * b1 + 1) // 3),
    ]

    rgb_pixels = []
    for row in range(4):
        bits = block_data[offset + 4 + row]
        for col in range(4):
            idx = (bits >> (col * 2)) & 0x03
            rgb_pixels.append(colors[idx])

    return rgb_pixels


def _decode_dxt3_block(block_data, offset):
    """
    Decode a single DXT3 4x4 block (16 bytes) into 16 RGBA pixels.

    Layout:
      Bytes 0-7:  explicit 4-bit alpha for 16 pixels
      Bytes 8-15: DXT1 color block (always 4-color opaque)
    """
    # Decode explicit alpha (8 bytes -> 16 x 4-bit values)
    alphas = []
    for i in range(8):
        byte_val = block_data[offset + i]
        # Low nibble first, then high nibble
        alphas.append((byte_val & 0x0F) * 17)  # 0x0F * 17 = 255
        alphas.append(((byte_val >> 4) & 0x0F) * 17)

    # Decode color block (offset+8)
    rgb_pixels = _decode_dxt1_block_opaque(block_data, offset + 8)

    # Combine
    pixels = []
    for i in range(16):
        r, g, b = rgb_pixels[i]
        pixels.append((r, g, b, alphas[i]))

    return pixels


def _decode_dxt5_block(block_data, offset):
    """
    Decode a single DXT5 4x4 block (16 bytes) into 16 RGBA pixels.

    Layout:
      Bytes 0-1:  alpha0, alpha1 reference values
      Bytes 2-7:  3-bit alpha indices (48 bits for 16 pixels)
      Bytes 8-15: DXT1 color block (always 4-color opaque)
    """
    alpha0 = block_data[offset]
    alpha1 = block_data[offset + 1]

    # Build alpha lookup table
    if alpha0 > alpha1:
        alpha_table = [
            alpha0,
            alpha1,
            (6 * alpha0 + 1 * alpha1 + 3) // 7,
            (5 * alpha0 + 2 * alpha1 + 3) // 7,
            (4 * alpha0 + 3 * alpha1 + 3) // 7,
            (3 * alpha0 + 4 * alpha1 + 3) // 7,
            (2 * alpha0 + 5 * alpha1 + 3) // 7,
            (1 * alpha0 + 6 * alpha1 + 3) // 7,
        ]
    else:
        alpha_table = [
            alpha0,
            alpha1,
            (4 * alpha0 + 1 * alpha1 + 2) // 5,
            (3 * alpha0 + 2 * alpha1 + 2) // 5,
            (2 * alpha0 + 3 * alpha1 + 2) // 5,
            (1 * alpha0 + 4 * alpha1 + 2) // 5,
            0,
            255,
        ]

    # Decode 3-bit alpha indices (6 bytes = 48 bits for 16 pixels)
    # Pack the 6 bytes into a 48-bit integer (little-endian)
    alpha_bits = 0
    for i in range(6):
        alpha_bits |= block_data[offset + 2 + i] << (8 * i)

    alphas = []
    for i in range(16):
        idx = (alpha_bits >> (3 * i)) & 0x07
        alphas.append(alpha_table[idx])

    # Decode color block (offset+8)
    rgb_pixels = _decode_dxt1_block_opaque(block_data, offset + 8)

    # Combine
    pixels = []
    for i in range(16):
        r, g, b = rgb_pixels[i]
        pixels.append((r, g, b, alphas[i]))

    return pixels


def _decode_dxt1(mip_data, width, height):
    """Decode DXT1 compressed data to RGBA pixel bytes."""
    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    pixels = bytearray(width * height * 4)

    for by in range(block_h):
        for bx in range(block_w):
            block_offset = (by * block_w + bx) * 8
            if block_offset + 8 > len(mip_data):
                break
            block_pixels = _decode_dxt1_block(mip_data, block_offset)

            for py in range(4):
                for px in range(4):
                    ix = bx * 4 + px
                    iy = by * 4 + py
                    if ix < width and iy < height:
                        r, g, b, a = block_pixels[py * 4 + px]
                        out_idx = (iy * width + ix) * 4
                        pixels[out_idx] = r
                        pixels[out_idx + 1] = g
                        pixels[out_idx + 2] = b
                        pixels[out_idx + 3] = a

    return pixels


def _decode_dxt3(mip_data, width, height):
    """Decode DXT3 compressed data to RGBA pixel bytes."""
    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    pixels = bytearray(width * height * 4)

    for by in range(block_h):
        for bx in range(block_w):
            block_offset = (by * block_w + bx) * 16
            if block_offset + 16 > len(mip_data):
                break
            block_pixels = _decode_dxt3_block(mip_data, block_offset)

            for py in range(4):
                for px in range(4):
                    ix = bx * 4 + px
                    iy = by * 4 + py
                    if ix < width and iy < height:
                        r, g, b, a = block_pixels[py * 4 + px]
                        out_idx = (iy * width + ix) * 4
                        pixels[out_idx] = r
                        pixels[out_idx + 1] = g
                        pixels[out_idx + 2] = b
                        pixels[out_idx + 3] = a

    return pixels


def _decode_dxt5(mip_data, width, height):
    """Decode DXT5 compressed data to RGBA pixel bytes."""
    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    pixels = bytearray(width * height * 4)

    for by in range(block_h):
        for bx in range(block_w):
            block_offset = (by * block_w + bx) * 16
            if block_offset + 16 > len(mip_data):
                break
            block_pixels = _decode_dxt5_block(mip_data, block_offset)

            for py in range(4):
                for px in range(4):
                    ix = bx * 4 + px
                    iy = by * 4 + py
                    if ix < width and iy < height:
                        r, g, b, a = block_pixels[py * 4 + px]
                        out_idx = (iy * width + ix) * 4
                        pixels[out_idx] = r
                        pixels[out_idx + 1] = g
                        pixels[out_idx + 2] = b
                        pixels[out_idx + 3] = a

    return pixels


def _decode_palette(mip_data, width, height, palette, alpha_depth, full_data, mip_offset, mip_size):
    """
    Decode palette-indexed pixel data to RGBA bytes.
    
    The mip_data contains indices into the 256-color palette.
    Alpha data follows the index data if alpha_depth > 0.
    """
    num_pixels = width * height
    pixels = bytearray(num_pixels * 4)
    
    # Each pixel is a 1-byte index into the palette
    for i in range(min(num_pixels, len(mip_data))):
        idx = mip_data[i]
        r, g, b, a = palette[idx]
        pixels[i * 4] = r
        pixels[i * 4 + 1] = g
        pixels[i * 4 + 2] = b
        pixels[i * 4 + 3] = a
    
    # Handle separate alpha data if present
    if alpha_depth > 0:
        alpha_offset = num_pixels  # Alpha data starts after index data
        if alpha_depth == 8:
            # One byte per pixel for alpha
            for i in range(min(num_pixels, len(mip_data) - alpha_offset)):
                if alpha_offset + i < len(mip_data):
                    pixels[i * 4 + 3] = mip_data[alpha_offset + i]
        elif alpha_depth == 1:
            # 1 bit per pixel, packed 8 per byte
            for i in range(num_pixels):
                byte_idx = alpha_offset + (i // 8)
                if byte_idx < len(mip_data):
                    bit_idx = i % 8
                    alpha = 255 if (mip_data[byte_idx] >> bit_idx) & 1 else 0
                    pixels[i * 4 + 3] = alpha
        elif alpha_depth == 4:
            # 4 bits per pixel, packed 2 per byte
            for i in range(num_pixels):
                byte_idx = alpha_offset + (i // 2)
                if byte_idx < len(mip_data):
                    if i % 2 == 0:
                        alpha = (mip_data[byte_idx] & 0x0F) * 17  # 0-15 -> 0-255
                    else:
                        alpha = ((mip_data[byte_idx] >> 4) & 0x0F) * 17
                    pixels[i * 4 + 3] = alpha
    
    return pixels


def _decode_uncompressed(mip_data, width, height):
    """Decode uncompressed BGRA pixel data to RGBA bytes."""
    expected = width * height * 4
    pixels = bytearray(expected)

    count = min(len(mip_data), expected)
    for i in range(0, count, 4):
        if i + 3 < count:
            pixels[i] = mip_data[i + 2]      # R <- B
            pixels[i + 1] = mip_data[i + 1]  # G
            pixels[i + 2] = mip_data[i]      # B <- R
            pixels[i + 3] = mip_data[i + 3]  # A

    return pixels


# ---------------------------------------------------------------------------
# Internal helpers -- DXT compression (BLP writer, pure-Python fallback)
# ---------------------------------------------------------------------------

def _encode_rgb565(r, g, b):
    """Encode 8-bit RGB to a 16-bit RGB565 value."""
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _generate_mipmaps(image):
    """
    Generate a mipmap chain from a PIL Image by halving dimensions.

    Each level is half the width and height of the previous level,
    down to a minimum of 1x1.

    Args:
        image: PIL RGBA Image.

    Returns:
        list: List of PIL Image objects [level0, level1, ...].
    """
    mipmaps = [image]
    w, h = image.size
    current = image

    while w > 1 or h > 1:
        w = max(w // 2, 1)
        h = max(h // 2, 1)
        current = current.resize((w, h), Image.LANCZOS)
        mipmaps.append(current)

    return mipmaps


def _compress_dxt1_block(block_rgba):
    """
    Compress a 4x4 block of RGBA pixels to DXT1 (8 bytes).

    Uses a simple min/max RGB endpoint selection.

    Args:
        block_rgba: list of 16 (r, g, b, a) tuples.

    Returns:
        bytes: 8-byte DXT1 compressed block.
    """
    # Find min and max RGB across all pixels
    min_r, min_g, min_b = 255, 255, 255
    max_r, max_g, max_b = 0, 0, 0

    for r, g, b, a in block_rgba:
        if r < min_r:
            min_r = r
        if g < min_g:
            min_g = g
        if b < min_b:
            min_b = b
        if r > max_r:
            max_r = r
        if g > max_g:
            max_g = g
        if b > max_b:
            max_b = b

    c0_565 = _encode_rgb565(max_r, max_g, max_b)
    c1_565 = _encode_rgb565(min_r, min_g, min_b)

    # Ensure c0 > c1 for 4-color opaque mode
    if c0_565 == c1_565:
        # All pixels same color -- trivial block
        return struct.pack('<HH', c0_565, c1_565) + b'\x00\x00\x00\x00'

    if c0_565 < c1_565:
        c0_565, c1_565 = c1_565, c0_565
        max_r, max_g, max_b, min_r, min_g, min_b = (
            min_r, min_g, min_b, max_r, max_g, max_b
        )

    # Decode endpoints back to 8-bit for index calculation
    r0, g0, b0 = _decode_rgb565(c0_565)
    r1, g1, b1 = _decode_rgb565(c1_565)

    # Build palette
    palette = [
        (r0, g0, b0),
        (r1, g1, b1),
        ((2 * r0 + r1 + 1) // 3, (2 * g0 + g1 + 1) // 3,
         (2 * b0 + b1 + 1) // 3),
        ((r0 + 2 * r1 + 1) // 3, (g0 + 2 * g1 + 1) // 3,
         (b0 + 2 * b1 + 1) // 3),
    ]

    # Calculate indices for each pixel (closest color in palette)
    index_bytes = bytearray(4)
    for row in range(4):
        byte_val = 0
        for col in range(4):
            r, g, b, a = block_rgba[row * 4 + col]
            best_idx = 0
            best_dist = 0x7FFFFFFF
            for ci, (pr, pg, pb) in enumerate(palette):
                dr = r - pr
                dg = g - pg
                db = b - pb
                dist = dr * dr + dg * dg + db * db
                if dist < best_dist:
                    best_dist = dist
                    best_idx = ci
            byte_val |= (best_idx << (col * 2))
        index_bytes[row] = byte_val

    return struct.pack('<HH', c0_565, c1_565) + bytes(index_bytes)


def _compress_dxt5_alpha_block(block_rgba):
    """
    Compress the alpha channel of a 4x4 block to DXT5 alpha format (8 bytes).

    Args:
        block_rgba: list of 16 (r, g, b, a) tuples.

    Returns:
        bytes: 8-byte DXT5 alpha block.
    """
    # Find min and max alpha
    min_a = 255
    max_a = 0
    for _, _, _, a in block_rgba:
        if a < min_a:
            min_a = a
        if a > max_a:
            max_a = a

    alpha0 = max_a
    alpha1 = min_a

    # Build alpha table (8-entry)
    if alpha0 > alpha1:
        alpha_table = [
            alpha0,
            alpha1,
            (6 * alpha0 + 1 * alpha1 + 3) // 7,
            (5 * alpha0 + 2 * alpha1 + 3) // 7,
            (4 * alpha0 + 3 * alpha1 + 3) // 7,
            (3 * alpha0 + 4 * alpha1 + 3) // 7,
            (2 * alpha0 + 5 * alpha1 + 3) // 7,
            (1 * alpha0 + 6 * alpha1 + 3) // 7,
        ]
    elif alpha0 == alpha1:
        alpha_table = [alpha0, alpha1, alpha0, alpha0,
                       alpha0, alpha0, 0, 255]
    else:
        alpha_table = [
            alpha0,
            alpha1,
            (4 * alpha0 + 1 * alpha1 + 2) // 5,
            (3 * alpha0 + 2 * alpha1 + 2) // 5,
            (2 * alpha0 + 3 * alpha1 + 2) // 5,
            (1 * alpha0 + 4 * alpha1 + 2) // 5,
            0,
            255,
        ]

    # Compute 3-bit indices for each pixel
    indices = []
    for _, _, _, a in block_rgba:
        best_idx = 0
        best_dist = 0x7FFFFFFF
        for ti, ta in enumerate(alpha_table):
            dist = abs(a - ta)
            if dist < best_dist:
                best_dist = dist
                best_idx = ti
        indices.append(best_idx)

    # Pack 16 x 3-bit indices into 48 bits (6 bytes)
    alpha_bits = 0
    for i, idx in enumerate(indices):
        alpha_bits |= (idx << (3 * i))

    # Pack: alpha0, alpha1, then 6 bytes of index bits
    result = bytearray(8)
    result[0] = alpha0
    result[1] = alpha1
    for i in range(6):
        result[2 + i] = (alpha_bits >> (8 * i)) & 0xFF

    return bytes(result)


def _get_block_pixels(image, bx, by, width, height):
    """
    Extract a 4x4 block of RGBA pixels from a PIL Image.

    Pads with edge pixels when the block extends beyond image bounds.

    Args:
        image: PIL RGBA Image (or raw pixel bytes accessed via getpixel).
        bx: Block x index (in 4-pixel units).
        by: Block y index (in 4-pixel units).
        width: Image width.
        height: Image height.

    Returns:
        list: 16 (r, g, b, a) tuples in row-major order.
    """
    block = []
    for py in range(4):
        for px in range(4):
            ix = min(bx * 4 + px, width - 1)
            iy = min(by * 4 + py, height - 1)
            block.append(image.getpixel((ix, iy)))
    return block


def _image_to_blp_dxt1(image):
    """
    Compress a PIL RGBA image to BLP2 with DXT1 compression and mipmaps.

    Args:
        image: PIL Image (RGBA).

    Returns:
        bytes: Complete BLP2 file content.
    """
    if image.mode != 'RGBA':
        image = image.convert('RGBA')

    mipmaps = _generate_mipmaps(image)
    mip_blobs = []

    for mip_img in mipmaps:
        w, h = mip_img.size
        block_w = (w + 3) // 4
        block_h = (h + 3) // 4
        blocks = bytearray()

        for by in range(block_h):
            for bx in range(block_w):
                block_rgba = _get_block_pixels(mip_img, bx, by, w, h)
                blocks.extend(_compress_dxt1_block(block_rgba))

        mip_blobs.append(bytes(blocks))

    return _build_blp2_dxt(image.size[0], image.size[1],
                           _BLP2_ALPHA_DXT1, 0, mip_blobs)


def _image_to_blp_dxt5(image):
    """
    Compress a PIL RGBA image to BLP2 with DXT5 compression and mipmaps.

    Args:
        image: PIL Image (RGBA).

    Returns:
        bytes: Complete BLP2 file content.
    """
    if image.mode != 'RGBA':
        image = image.convert('RGBA')

    mipmaps = _generate_mipmaps(image)
    mip_blobs = []

    for mip_img in mipmaps:
        w, h = mip_img.size
        block_w = (w + 3) // 4
        block_h = (h + 3) // 4
        blocks = bytearray()

        for by in range(block_h):
            for bx in range(block_w):
                block_rgba = _get_block_pixels(mip_img, bx, by, w, h)
                alpha_block = _compress_dxt5_alpha_block(block_rgba)
                color_block = _compress_dxt1_block(block_rgba)
                blocks.extend(alpha_block)
                blocks.extend(color_block)

        mip_blobs.append(bytes(blocks))

    return _build_blp2_dxt(image.size[0], image.size[1],
                           _BLP2_ALPHA_DXT5, 8, mip_blobs)


def _build_blp2_dxt(width, height, alpha_type, alpha_depth, mip_blobs):
    """
    Build a complete BLP2 file with DXT-compressed mipmap data.

    Args:
        width: Image width.
        height: Image height.
        alpha_type: Alpha type code (0=DXT1, 1=DXT3, 7=DXT5).
        alpha_depth: Alpha bit depth (0 for DXT1, 8 for DXT5).
        mip_blobs: List of compressed mipmap data blobs.

    Returns:
        bytes: Complete BLP2 file.
    """
    header = bytearray(_BLP2_HEADER_SIZE)

    header[0:4] = _BLP2_MAGIC
    struct.pack_into('<I', header, 4, _BLP2_TYPE)
    struct.pack_into('<B', header, 8, _BLP2_COMP_DXT)
    struct.pack_into('<B', header, 9, alpha_depth)
    struct.pack_into('<B', header, 10, alpha_type)
    struct.pack_into('<B', header, 11, 1 if len(mip_blobs) > 1 else 0)
    struct.pack_into('<I', header, 12, width)
    struct.pack_into('<I', header, 16, height)

    # Calculate mipmap offsets and sizes
    current_offset = _BLP2_HEADER_SIZE
    mip_count = min(len(mip_blobs), _BLP2_MIP_COUNT)

    for i in range(mip_count):
        struct.pack_into('<I', header, 20 + i * 4, current_offset)
        struct.pack_into('<I', header, 84 + i * 4, len(mip_blobs[i]))
        current_offset += len(mip_blobs[i])

    # Assemble file
    result = bytearray(header)
    for i in range(mip_count):
        result.extend(mip_blobs[i])

    return bytes(result)


# ---------------------------------------------------------------------------
# Internal helpers -- Native PNG2BLP
# ---------------------------------------------------------------------------

def _convert_png_bytes(png_bytes, compression):
    """
    Convert raw PNG file bytes to BLP bytes using the native PNG2BLP extension.

    Args:
        png_bytes: Raw PNG file content as bytes.
        compression: Compression type string ('dxt1', 'dxt3', 'dxt5').

    Returns:
        bytes: BLP file content.

    Raises:
        ImportError: If PNG2BLP is not available.
        ValueError: If compression type is unknown.
    """
    if not _HAS_PNG2BLP:
        raise ImportError("PNG2BLP native extension is not available")

    converter = BlpFromPng(png_bytes, len(png_bytes))

    dxt_format = _COMPRESSION_MAP.get(compression.lower())
    if dxt_format is not None:
        # Note: the Cython binding has a naming quirk where the 2-arg
        # create_blp_paletted_in_memory(mipmaps, dxtFormat) actually
        # calls createBlpDxtInMemory under the hood (shadowed overload).
        return converter.create_blp_paletted_in_memory(True, dxt_format)
    elif compression.lower() == 'uncompressed':
        return converter.create_blp_uncompressed_in_memory(True)
    else:
        raise ValueError("Unknown compression type: {!r}".format(compression))


# ---------------------------------------------------------------------------
# Internal helpers -- Uncompressed BLP writer
# ---------------------------------------------------------------------------

def _image_to_blp_uncompressed(image, with_mipmaps=False):
    """
    Uncompressed BLP2 writer.

    Produces a valid BLP2 file with compression type 3 (raw BGRA pixels).
    Optionally generates mipmaps.

    Args:
        image: PIL Image object (will be converted to RGBA if needed).
        with_mipmaps: If True, generate mipmap chain. Default False.

    Returns:
        bytes: Complete BLP2 file content.
    """
    if image.mode != 'RGBA':
        image = image.convert('RGBA')

    width, height = image.size

    if with_mipmaps:
        mip_images = _generate_mipmaps(image)
    else:
        mip_images = [image]

    # Convert each mipmap level to BGRA bytes
    mip_blobs = []
    for mip_img in mip_images:
        rgba_pixels = mip_img.tobytes()
        bgra_pixels = bytearray(len(rgba_pixels))
        for i in range(0, len(rgba_pixels), 4):
            bgra_pixels[i] = rgba_pixels[i + 2]      # B
            bgra_pixels[i + 1] = rgba_pixels[i + 1]  # G
            bgra_pixels[i + 2] = rgba_pixels[i]      # R
            bgra_pixels[i + 3] = rgba_pixels[i + 3]  # A
        mip_blobs.append(bytes(bgra_pixels))

    # Build header
    header = bytearray(_BLP2_HEADER_SIZE)
    header[0:4] = _BLP2_MAGIC
    struct.pack_into('<I', header, 4, _BLP2_TYPE)
    struct.pack_into('<B', header, 8, _BLP2_COMP_RAW)
    struct.pack_into('<B', header, 9, _BLP2_ALPHA_DEPTH)
    struct.pack_into('<B', header, 10, _BLP2_ALPHA_TYPE)
    struct.pack_into('<B', header, 11, 1 if len(mip_blobs) > 1 else 0)
    struct.pack_into('<I', header, 12, width)
    struct.pack_into('<I', header, 16, height)

    # Calculate mipmap offsets and sizes
    current_offset = _BLP2_HEADER_SIZE
    mip_count = min(len(mip_blobs), _BLP2_MIP_COUNT)

    for i in range(mip_count):
        struct.pack_into('<I', header, 20 + i * 4, current_offset)
        struct.pack_into('<I', header, 84 + i * 4, len(mip_blobs[i]))
        current_offset += len(mip_blobs[i])

    # Assemble file
    result = bytearray(header)
    for i in range(mip_count):
        result.extend(mip_blobs[i])

    return bytes(result)
