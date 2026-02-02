"""
BLP texture converter for WoW WotLK 3.3.5a.

Provides convenience functions for converting PNG files and PIL Image objects
to BLP format. Uses the existing pywowlib PNG2BLP native extension for DXT
compression when available, and falls back to a minimal uncompressed BLP2
writer when the native extension is not built.

BLP2 uncompressed format (fallback writer):
  Header: 148 bytes
    - Magic 'BLP2'            4 bytes
    - Type (1=BLP2)           4 bytes (uint32)
    - Compression (3=raw)     1 byte
    - AlphaDepth (8)          1 byte
    - AlphaType (8)           1 byte
    - HasMips (0)             1 byte
    - Width                   4 bytes (uint32)
    - Height                  4 bytes (uint32)
    - MipmapOffsets[16]       64 bytes (16 * uint32)
    - MipmapSizes[16]         64 bytes (16 * uint32)
  Pixel data: width * height * 4 bytes (BGRA)

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
# BLP2 header layout constants (for uncompressed fallback writer)
# ---------------------------------------------------------------------------
_BLP2_MAGIC = b'BLP2'
_BLP2_HEADER_SIZE = 148
_BLP2_TYPE = 1           # BLP2 type identifier
_BLP2_COMP_RAW = 3       # compression type 3 = uncompressed ARGB
_BLP2_ALPHA_DEPTH = 8    # 8-bit alpha channel
_BLP2_ALPHA_TYPE = 8     # BGRA type
_BLP2_MIP_COUNT = 16     # mipmap offset/size array length


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def convert_png_to_blp(png_path, blp_path, compression='dxt1'):
    """
    Convert a PNG file to BLP format.

    Uses the native PNG2BLP extension for DXT compression when available.
    Falls back to uncompressed BLP2 writer via PIL if the native extension
    is not built.

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

    if compression == 'uncompressed' or not _HAS_PNG2BLP:
        # Use PIL-based uncompressed fallback
        if Image is None:
            raise RuntimeError(
                "Neither PNG2BLP native extension nor PIL is available. "
                "Build the native extensions or install Pillow."
            )
        pil_image = Image.open(io.BytesIO(png_data))
        blp_bytes = _image_to_blp_uncompressed(pil_image)
        if not _HAS_PNG2BLP and compression != 'uncompressed':
            log.warning(
                "PNG2BLP not available, using uncompressed fallback for %s",
                png_path,
            )
    else:
        blp_bytes = _convert_png_bytes(png_data, compression)

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
      2. Fall back to uncompressed BLP2 writer if PNG2BLP is unavailable

    Args:
        pil_image: PIL Image object. Will be converted to RGBA if needed.
        compression: Compression type: 'dxt1', 'dxt3', 'dxt5',
                     or 'uncompressed'. Default 'dxt1'.
                     Ignored when falling back to uncompressed writer.

    Returns:
        bytes: Complete BLP file content.

    Raises:
        RuntimeError: If PIL is not available and the image cannot be processed.
    """
    if pil_image.mode != 'RGBA':
        pil_image = pil_image.convert('RGBA')

    if compression == 'uncompressed' or not _HAS_PNG2BLP:
        if not _HAS_PNG2BLP and compression != 'uncompressed':
            log.warning(
                "PNG2BLP not available, using uncompressed fallback "
                "for %dx%d image",
                pil_image.width,
                pil_image.height,
            )
        return _image_to_blp_uncompressed(pil_image)

    # Save PIL Image to in-memory PNG, then pass raw bytes to PNG2BLP
    png_buf = io.BytesIO()
    pil_image.save(png_buf, format='PNG')
    png_bytes = png_buf.getvalue()

    return _convert_png_bytes(png_bytes, compression)


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
# Internal helpers
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


def _image_to_blp_uncompressed(image):
    """
    Minimal uncompressed BLP2 writer.

    Produces a valid BLP2 file with compression type 3 (raw BGRA pixels),
    no mipmaps. Used as a fallback when the native PNG2BLP extension is
    not available.

    The output is larger than DXT-compressed BLP files, but file size is
    acceptable for custom zone patches.

    Args:
        image: PIL Image object (will be converted to RGBA if needed).

    Returns:
        bytes: Complete BLP2 file content.
    """
    if image.mode != 'RGBA':
        image = image.convert('RGBA')

    width, height = image.size

    # --- Build 148-byte BLP2 header ---
    header = bytearray(_BLP2_HEADER_SIZE)

    # Magic: 'BLP2' (bytes 0-3)
    header[0:4] = _BLP2_MAGIC

    # Type: 1 = BLP2 (bytes 4-7, uint32)
    struct.pack_into('<I', header, 4, _BLP2_TYPE)

    # Compression: 3 = uncompressed (byte 8)
    struct.pack_into('<B', header, 8, _BLP2_COMP_RAW)

    # Alpha depth: 8 (byte 9)
    struct.pack_into('<B', header, 9, _BLP2_ALPHA_DEPTH)

    # Alpha type: 8 = BGRA (byte 10)
    struct.pack_into('<B', header, 10, _BLP2_ALPHA_TYPE)

    # HasMips: 0 (byte 11)
    struct.pack_into('<B', header, 11, 0)

    # Width (bytes 12-15, uint32)
    struct.pack_into('<I', header, 12, width)

    # Height (bytes 16-19, uint32)
    struct.pack_into('<I', header, 16, height)

    # Mipmap offsets (bytes 20-83, 16 uint32)
    # Only the first mipmap level has data, at offset = header size
    pixel_data_size = width * height * 4
    struct.pack_into('<I', header, 20, _BLP2_HEADER_SIZE)
    # Remaining 15 mipmap offsets stay zero (already initialized)

    # Mipmap sizes (bytes 84-147, 16 uint32)
    struct.pack_into('<I', header, 84, pixel_data_size)
    # Remaining 15 mipmap sizes stay zero (already initialized)

    # --- Convert RGBA pixels to BGRA ---
    rgba_pixels = image.tobytes()
    bgra_pixels = bytearray(len(rgba_pixels))
    for i in range(0, len(rgba_pixels), 4):
        bgra_pixels[i] = rgba_pixels[i + 2]      # B
        bgra_pixels[i + 1] = rgba_pixels[i + 1]  # G
        bgra_pixels[i + 2] = rgba_pixels[i]      # R
        bgra_pixels[i + 3] = rgba_pixels[i + 3]  # A

    return bytes(header) + bytes(bgra_pixels)
