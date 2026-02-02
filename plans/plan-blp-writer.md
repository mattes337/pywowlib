# BLP Converter: Pragmatic Implementation Plan

## Philosophy

**Wrap first, write only when necessary.** The artwork pipeline needs BLP generation, but we should leverage existing conversion tools where possible. Only write raw BLP bytes when the wrapper approach fails (e.g., converting PIL Image objects when PNG2BLP is unavailable).

## Scope

**Total implementation: ~150-200 lines**

Three components:
1. **PNG2BLP wrapper** (~30 lines) - thin wrapper around existing pywowlib capability
2. **PIL Image → BLP converter** (~80 lines) - memory to BLP via temp PNG + PNG2BLP
3. **Uncompressed BLP writer fallback** (~100 lines) - minimal BLP2 writer for when PNG2BLP unavailable

## What NOT to Build

- DXT1/DXT3/DXT5 encoder (use PNG2BLP)
- Mipmap generation chain
- Palette quantization
- Full BLP format specification coverage

PNG2BLP handles the hard stuff. We're only building convenience wrappers and a fallback writer.

---

## API Design

```python
# world_builder/blp_converter.py

from typing import Union, Optional
from pathlib import Path
from PIL import Image


def convert_png_to_blp(
    png_path: Union[str, Path],
    blp_path: Union[str, Path],
    compression: str = 'dxt1'
) -> None:
    """
    Convert PNG file to BLP using existing pywowlib PNG2BLP.

    Args:
        png_path: Input PNG file
        blp_path: Output BLP file
        compression: 'dxt1', 'dxt3', 'dxt5', 'uncompressed'

    Example:
        convert_png_to_blp('input.png', 'output.blp')
    """
    pass


def image_to_blp(
    pil_image: Image.Image,
    compression: str = 'dxt1'
) -> bytes:
    """
    Convert PIL Image object to BLP bytes.

    This is the key function for artwork pipeline which generates
    images in memory using Pillow.

    Strategy:
    1. Try PNG2BLP wrapper (save temp PNG → convert → cleanup)
    2. Fallback to uncompressed BLP writer if PNG2BLP unavailable

    Args:
        pil_image: PIL Image object (will be converted to RGBA)
        compression: 'dxt1' (ignored if fallback used)

    Returns:
        BLP file bytes

    Example:
        from PIL import Image
        img = Image.new('RGBA', (1024, 768), (0, 128, 0, 255))
        blp_bytes = image_to_blp(img)
    """
    pass


def batch_convert(
    input_dir: Union[str, Path],
    output_dir: Union[str, Path],
    pattern: str = '*.png'
) -> list[str]:
    """
    Convert directory of PNG files to BLP.

    Args:
        input_dir: Directory containing PNG files
        output_dir: Output directory for BLP files
        pattern: Glob pattern (default: '*.png')

    Returns:
        List of generated BLP file paths

    Example:
        blp_files = batch_convert('pngs/', 'blps/')
    """
    pass


def validate_blp(blp_data: Union[bytes, str, Path]) -> dict:
    """
    Basic BLP validation.

    Checks:
    - Magic header is 'BLP2'
    - Dimensions are present
    - File is not truncated (has data beyond header)

    Args:
        blp_data: BLP file path or bytes

    Returns:
        {
            'valid': bool,
            'magic': str,
            'width': int,
            'height': int,
            'errors': list[str]
        }

    Example:
        info = validate_blp('output.blp')
        if not info['valid']:
            print(f"Errors: {info['errors']}")
    """
    pass
```

---

## Implementation Details

### 1. PNG2BLP Wrapper (~30 lines)

```python
def convert_png_to_blp(png_path, blp_path, compression='dxt1'):
    """
    Thin wrapper around existing PNG2BLP.

    Implementation:
    1. Import PNG2BLP from blp module
    2. Call converter with parameters
    3. Write output to blp_path
    """
    from blp import PNG2BLP  # or wherever it lives

    converter = PNG2BLP()
    blp_bytes = converter.convert(
        png_path,
        compression=_map_compression(compression)
    )

    with open(blp_path, 'wb') as f:
        f.write(blp_bytes)


def batch_convert(input_dir, output_dir, pattern='*.png'):
    """
    Simple batch converter.

    Implementation:
    1. Glob for PNG files
    2. For each PNG, call convert_png_to_blp
    3. Return list of output paths
    """
    from pathlib import Path

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    results = []
    for png_file in input_path.glob(pattern):
        blp_file = output_path / f"{png_file.stem}.blp"
        convert_png_to_blp(png_file, blp_file)
        results.append(str(blp_file))

    return results
```

### 2. PIL Image → BLP Converter (~80 lines)

```python
def image_to_blp(pil_image, compression='dxt1'):
    """
    Convert PIL Image to BLP bytes.

    Strategy:
    1. Try wrapper approach first (temp PNG + PNG2BLP)
    2. If PNG2BLP unavailable, fall back to uncompressed writer

    The wrapper approach is preferred because it gives us DXT compression.
    The fallback is uncompressed but ensures we can always generate BLPs.
    """
    # Ensure RGBA
    if pil_image.mode != 'RGBA':
        pil_image = pil_image.convert('RGBA')

    # Try PNG2BLP wrapper approach
    try:
        return _image_to_blp_via_png2blp(pil_image, compression)
    except ImportError:
        # PNG2BLP not available, use uncompressed fallback
        return _image_to_blp_uncompressed(pil_image)


def _image_to_blp_via_png2blp(image, compression):
    """
    Convert via temporary PNG file.

    Implementation:
    1. Save PIL Image to temp PNG
    2. Call PNG2BLP on temp file
    3. Read BLP bytes
    4. Clean up temp file
    5. Return bytes
    """
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp_path = tmp.name
        image.save(tmp_path, 'PNG')

    try:
        from blp import PNG2BLP

        converter = PNG2BLP()
        blp_bytes = converter.convert(
            tmp_path,
            compression=_map_compression(compression)
        )
        return blp_bytes
    finally:
        os.unlink(tmp_path)


def _map_compression(compression_str):
    """Map friendly names to PNG2BLP constants."""
    # This depends on PNG2BLP API, adjust as needed
    return {
        'dxt1': 2,
        'dxt3': 2,
        'dxt5': 2,
        'uncompressed': 3
    }.get(compression_str.lower(), 2)
```

### 3. Uncompressed BLP Writer Fallback (~100 lines)

```python
def _image_to_blp_uncompressed(image):
    """
    Simple uncompressed BLP2 writer.

    Used only when PNG2BLP is unavailable. This is the MINIMUM viable
    BLP writer - no compression, no mipmaps, just raw BGRA pixels.

    BLP2 format:
    - Header: 148 bytes
    - Pixel data: width * height * 4 bytes (BGRA)

    Compression type 3 = uncompressed ARGB (simplest format)

    Implementation:
    1. Build BLP2 header (148 bytes)
    2. Convert RGBA pixels to BGRA
    3. Concatenate header + pixels
    4. Return bytes

    File size isn't critical for custom zone patches, so uncompressed
    is acceptable fallback.
    """
    import struct

    width, height = image.size

    # Ensure RGBA
    if image.mode != 'RGBA':
        image = image.convert('RGBA')

    # Build BLP2 header
    header = bytearray(148)

    # Magic: 'BLP2' (4 bytes)
    header[0:4] = b'BLP2'

    # Type: 3 = uncompressed (1 byte)
    struct.pack_into('<I', header, 4, 3)

    # Flags: 8 = has alpha (1 byte)
    struct.pack_into('<B', header, 8, 8)

    # Width (4 bytes)
    struct.pack_into('<I', header, 9, width)

    # Height (4 bytes)
    struct.pack_into('<I', header, 13, height)

    # Mipmap offsets (16 * 4 = 64 bytes)
    # Only first mipmap has data, rest are zero
    pixel_data_size = width * height * 4
    struct.pack_into('<I', header, 17, 148)  # First mipmap offset = header size
    # Rest of mipmap offsets are zero (already initialized)

    # Mipmap sizes (16 * 4 = 64 bytes)
    struct.pack_into('<I', header, 81, pixel_data_size)
    # Rest are zero

    # Convert RGBA to BGRA
    pixels = image.tobytes()
    bgra_pixels = bytearray(len(pixels))
    for i in range(0, len(pixels), 4):
        r, g, b, a = pixels[i:i+4]
        bgra_pixels[i] = b
        bgra_pixels[i+1] = g
        bgra_pixels[i+2] = r
        bgra_pixels[i+3] = a

    return bytes(header) + bytes(bgra_pixels)
```

### 4. Validation (~20 lines)

```python
def validate_blp(blp_data):
    """
    Basic BLP validation.

    Implementation:
    1. Read first 20 bytes
    2. Check magic = 'BLP2'
    3. Parse width/height
    4. Check data length >= header + minimal pixel data
    """
    import struct
    from pathlib import Path

    # Load bytes
    if isinstance(blp_data, (str, Path)):
        with open(blp_data, 'rb') as f:
            data = f.read()
    else:
        data = blp_data

    errors = []

    # Check minimum length
    if len(data) < 148:
        errors.append("File too short (< 148 bytes)")
        return {
            'valid': False,
            'magic': '',
            'width': 0,
            'height': 0,
            'errors': errors
        }

    # Check magic
    magic = data[0:4].decode('ascii', errors='ignore')
    if magic != 'BLP2':
        errors.append(f"Invalid magic: {magic} (expected BLP2)")

    # Parse dimensions
    width = struct.unpack_from('<I', data, 9)[0]
    height = struct.unpack_from('<I', data, 13)[0]

    # Check dimensions are reasonable
    if width == 0 or height == 0:
        errors.append(f"Invalid dimensions: {width}x{height}")

    # Check file has data beyond header
    if len(data) <= 148:
        errors.append("No pixel data after header")

    return {
        'valid': len(errors) == 0,
        'magic': magic,
        'width': width,
        'height': height,
        'errors': errors
    }
```

---

## Usage Examples

### Artwork Pipeline (Main Use Case)

```python
from world_builder.blp_converter import image_to_blp
from PIL import Image, ImageDraw

# Generate loading screen in memory
img = Image.new('RGBA', (1024, 768), (20, 80, 120, 255))
draw = ImageDraw.Draw(img)
draw.text((512, 384), "Tel'Abim", fill='white', anchor='mm')

# Convert to BLP (uses PNG2BLP if available, falls back to uncompressed)
blp_bytes = image_to_blp(img)

# Save to file
with open('LoadScreen_TelAbim.blp', 'wb') as f:
    f.write(blp_bytes)
```

### File Conversion

```python
from world_builder.blp_converter import convert_png_to_blp, batch_convert

# Single file
convert_png_to_blp('minimap.png', 'minimap.blp')

# Batch
blp_files = batch_convert('artwork_png/', 'artwork_blp/')
print(f"Converted {len(blp_files)} files")
```

### Validation

```python
from world_builder.blp_converter import validate_blp

info = validate_blp('output.blp')
if info['valid']:
    print(f"Valid BLP: {info['width']}x{info['height']}")
else:
    print(f"Invalid: {info['errors']}")
```

---

## Implementation Checklist

### Phase 1: Core Implementation (~2 days)

- [ ] Create `world_builder/blp_converter.py`
- [ ] Implement `convert_png_to_blp()` wrapper (~30 lines)
- [ ] Implement `batch_convert()` wrapper (~20 lines)
- [ ] Implement `image_to_blp()` with PNG2BLP path (~50 lines)
- [ ] Implement `_image_to_blp_uncompressed()` fallback (~100 lines)
- [ ] Implement `validate_blp()` (~20 lines)
- [ ] Write unit tests
  - Test PNG → BLP file conversion
  - Test PIL Image → BLP bytes (both paths)
  - Test batch conversion
  - Test validation
  - Test fallback when PNG2BLP unavailable

### Phase 2: Integration (~1 day)

- [ ] Integrate into artwork pipeline
- [ ] Test loading screen generation
- [ ] Test world map overlay generation
- [ ] Manual validation: load BLPs in WoW 3.3.5a client

### Phase 3: Documentation (~0.5 day)

- [ ] Document API with examples
- [ ] Add docstrings
- [ ] Note fallback behavior in comments

**Total: 3-4 days**

---

## Success Criteria

- [ ] Can convert PNG file to BLP file (via PNG2BLP)
- [ ] Can convert PIL Image to BLP bytes (via PNG2BLP)
- [ ] Fallback to uncompressed writer works when PNG2BLP unavailable
- [ ] Batch conversion processes directories correctly
- [ ] Validation catches invalid BLP files
- [ ] Generated BLPs load in WoW 3.3.5a client
- [ ] Temporary files cleaned up properly
- [ ] Module is <250 lines total

---

## Trade-offs

**Wrapper vs Full Encoder:**
- **Decision:** Wrap PNG2BLP for DXT compression, fallback to uncompressed writer
- **Rationale:** PNG2BLP does DXT correctly. Building DXT encoder from scratch = weeks of work. Uncompressed fallback ensures we can always generate BLPs even without PNG2BLP.
- **Trade-off:** Fallback BLPs are larger (no compression), but file size isn't critical for custom zone patches

**Temporary PNG File:**
- **Decision:** Save PIL Image to temp PNG, then convert
- **Rationale:** PNG2BLP expects file path, not bytes. Temp file overhead is negligible (<5ms).
- **Trade-off:** Extra disk I/O, but ensures compatibility with existing PNG2BLP

**No Mipmaps in Fallback:**
- **Decision:** Uncompressed fallback doesn't generate mipmaps
- **Rationale:** Mipmap generation is complex. For our use cases (loading screens, world maps), single mipmap level is sufficient.
- **Trade-off:** Slightly lower quality at distance, but acceptable for custom zones

---

## Future Enhancements

**If PNG2BLP accepts bytes:** Eliminate temp PNG file, pass Image as in-memory PNG bytes (~1 day)

**Progress callbacks:** Add progress reporting for batch conversion (~0.5 day)

**Mipmap generation in fallback:** Add simple mipmap chain generation (~1 day, but probably not needed)

---

## Notes

**Module location:** `world_builder/blp_converter.py`

**Dependencies:**
- `tempfile`, `os`, `struct`, `pathlib` (stdlib)
- `PIL` (Pillow - already dependency)
- `blp.PNG2BLP` (existing pywowlib module, soft dependency with fallback)

**Philosophy:**
- Keep it simple
- Wrap existing tools first
- Only write raw bytes when wrapping fails
- Uncompressed fallback is acceptable
- ~150-200 lines total is the goal

---

**Document Version:** 3.0 - Pragmatic Rewrite
**Date:** 2026-02-02
**Status:** Ready for Implementation
