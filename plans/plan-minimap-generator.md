# Plan: Minimap Tile Conversion Pipeline for pywowlib world_builder

## 1. Overview

This plan documents the minimap tile **CONVERSION PIPELINE** implementation for pywowlib's world_builder module (WoW WotLK 3.3.5a).

### 1.1 Philosophy: Conversion Only, Not Generation

**Core principle**: The user exports minimap tiles from Noggit manually. The agent handles the file conversion pipeline.

**User quote**: "the minimap or map generation is fine since I only need to open the map and take it."

**Translation**: Minimap generation is a ONE-CLICK operation in Noggit. There is no automation value in reimplementing what Noggit already does perfectly.

### 1.2 What to AUTOMATE

1. **Import pipeline** - Accept minimap tile images from a directory (exported from Noggit as BLP/TGA/PNG)
2. **Format conversion** - Convert non-BLP tiles to BLP using existing PNG2BLP
3. **Naming convention** - Ensure tiles follow `map{XX}_{YY}.blp` naming (2-digit zero-padded coords)
4. **MPQ path placement** - Place at `Textures\Minimap\{MapName}\map{XX}_{YY}.blp`
5. **Completeness check** - Cross-check against WDT active tiles to ensure no missing minimap tiles
6. **md5translate.trs** - Generate the MD5 hash translation file if needed

### 1.3 What Stays MANUAL

- Opening Noggit, viewing the map, exporting minimap tiles
- This is literally a menu click in Noggit

### 1.4 Simple Fallback (Testing Only)

If no Noggit export is available for rapid prototyping: generate basic solid-color minimap tiles from ADT texture data.

**Characteristics**:
- ~50 lines of code
- "Good enough for testing" quality
- NOT a real minimap generator
- Just fills tiles with representative texture colors

### 1.5 API Example

```python
from world_builder.minimap_pipeline import import_minimap_tiles

# Primary: import Noggit exports
import_minimap_tiles(
    export_dir='./noggit_export/minimaps/',
    map_name='TelAbim',
    output_packer=mpq_packer,
)

# Fallback: basic test tiles
from world_builder.minimap_pipeline import generate_test_minimaps
generate_test_minimaps(adt_data_dict, map_name='TelAbim', output_dir='./output/')
```

**Target module size**: ~100-150 lines total

---

## 2. Architecture

### 2.1 New Module: `world_builder/minimap_pipeline.py`

**Single responsibility**: Convert exported minimap tiles to WoW MPQ format

**Target size**: ~100-150 lines total

### 2.2 Primary API: Import Pipeline

```python
def import_minimap_tiles(export_dir, map_name, wdt_data=None):
    """
    Import minimap tiles from Noggit export directory.

    Args:
        export_dir: Path to directory containing exported minimap tiles
                    (BLP, TGA, or PNG format)
        map_name: Map directory name (e.g. "TelAbim")
        wdt_data: Optional WDT data dict for validation (ensure all active tiles present)

    Returns:
        dict: {
            'blp_data': {(tile_x, tile_y): blp_bytes, ...},
            'md5translate': str,  # Contents of md5translate.trs file
            'missing_tiles': [(x, y), ...],  # Tiles in WDT but missing minimaps
        }

    Raises:
        ValueError: If tiles have invalid naming or format
        FileNotFoundError: If export_dir doesn't exist
    """
```

### 2.3 Fallback API: Simple Test Tiles

```python
def generate_test_minimaps(adt_data_dict, texture_color_map):
    """
    Generate SIMPLE colored minimap tiles for testing (NOT production quality).

    This is a fallback when not using Noggit. Just fills tiles with
    representative texture colors - no relief shading, no compositing.

    Args:
        adt_data_dict: Dict mapping (tile_x, tile_y) to dict with keys:
            - 'texture_paths': List of texture path strings
        texture_color_map: Dict mapping texture path (str) -> RGB tuple (0-255)

    Returns:
        dict: {(tile_x, tile_y): blp_bytes, ...}

    Implementation:
        - Read ADT texture paths → map to representative colors
        - Fill 256x256 image per tile with dominant texture color
        - Convert to BLP

    Target: ~50 lines, simple and fast
    """
```

### 2.4 Helper Functions

```python
def _detect_tile_format(file_path):
    """Detect if file is BLP, TGA, or PNG by magic bytes."""

def _convert_to_blp(image_path):
    """Convert TGA/PNG to BLP using PNG2BLP."""

def _validate_tile_naming(filename):
    """
    Validate that filename matches map{XX}_{YY}.ext pattern.
    Returns (tile_x, tile_y) or raises ValueError.
    """

def _generate_md5translate(tile_dict, map_name):
    """
    Generate md5translate.trs content.
    Format: one line per tile, "MapName\\filename;hash"
    Example: "TelAbim\\map32_32.blp;a1b2c3d4e5f6..."
    """
```

---

## 3. Implementation Details

### 3.1 Import Pipeline Workflow

```python
def import_minimap_tiles(export_dir, map_name, wdt_data=None):
    # Step 1: Scan export directory for tile files
    tile_files = glob.glob(os.path.join(export_dir, "map*_*.*"))

    # Step 2: Process each tile
    blp_data = {}
    for tile_file in tile_files:
        # Validate naming
        basename = os.path.basename(tile_file)
        tile_x, tile_y = _validate_tile_naming(basename)

        # Detect format
        fmt = _detect_tile_format(tile_file)

        # Convert to BLP if needed
        if fmt == 'BLP':
            with open(tile_file, 'rb') as f:
                blp_bytes = f.read()
        else:
            blp_bytes = _convert_to_blp(tile_file)

        blp_data[(tile_x, tile_y)] = blp_bytes

    # Step 3: Validate completeness against WDT
    missing_tiles = []
    if wdt_data:
        active_tiles = _get_active_tiles_from_wdt(wdt_data)
        missing_tiles = [t for t in active_tiles if t not in blp_data]

    # Step 4: Generate md5translate.trs
    md5translate = _generate_md5translate(blp_data, map_name)

    return {
        'blp_data': blp_data,
        'md5translate': md5translate,
        'missing_tiles': missing_tiles,
    }
```

### 3.2 Format Detection

```python
def _detect_tile_format(file_path):
    """Detect format by magic bytes."""
    with open(file_path, 'rb') as f:
        magic = f.read(4)

    if magic[:4] == b'BLP2':
        return 'BLP'
    elif magic[:2] in (b'\x00\x00', b'\x00\x02'):
        return 'TGA'
    elif magic[:4] == b'\x89PNG':
        return 'PNG'
    else:
        raise ValueError(f"Unknown file format: {file_path}")
```

### 3.3 BLP Conversion

```python
def _convert_to_blp(image_path):
    """Convert TGA/PNG to BLP using PNG2BLP."""
    from blp import PNG2BLP
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # PNG2BLP requires PNG input
        png_path = image_path
        if _detect_tile_format(image_path) == 'TGA':
            from PIL import Image
            img = Image.open(image_path)
            png_path = os.path.join(tmpdir, "temp.png")
            img.save(png_path, "PNG")

        # Convert PNG→BLP
        blp_path = os.path.join(tmpdir, "temp.blp")
        converter = PNG2BLP()
        converter.convert(png_path, blp_path, generate_mipmaps=False)

        with open(blp_path, 'rb') as f:
            return f.read()
```

### 3.4 Naming Validation

```python
def _validate_tile_naming(filename):
    """
    Validate map{XX}_{YY}.ext pattern.
    Returns (tile_x, tile_y) tuple.
    """
    import re

    pattern = r'^map(\d{2})_(\d{2})\.(blp|tga|png)$'
    match = re.match(pattern, filename, re.IGNORECASE)

    if not match:
        raise ValueError(f"Invalid tile filename: {filename}. "
                        "Expected format: mapXX_YY.ext (e.g., map32_32.blp)")

    tile_x = int(match.group(1))
    tile_y = int(match.group(2))

    if not (0 <= tile_x < 64 and 0 <= tile_y < 64):
        raise ValueError(f"Tile coordinates out of range: ({tile_x}, {tile_y})")

    return (tile_x, tile_y)
```

### 3.5 md5translate.trs Generation

```python
def _generate_md5translate(blp_data, map_name):
    """
    Generate md5translate.trs content.

    Format (one line per tile):
        MapName\mapXX_YY.blp;MD5HASH
    """
    import hashlib

    lines = []
    for (tile_x, tile_y), blp_bytes in sorted(blp_data.items()):
        md5_hash = hashlib.md5(blp_bytes).hexdigest()
        filename = f"map{tile_x:02d}_{tile_y:02d}.blp"
        line = f"{map_name}\\{filename};{md5_hash}"
        lines.append(line)

    return "\r\n".join(lines) + "\r\n"  # Windows line endings
```

### 3.6 Fallback: Simple Test Tiles

```python
def generate_test_minimaps(adt_data_dict, texture_color_map):
    """
    Generate SIMPLE colored minimap tiles for testing.

    Algorithm:
        1. For each ADT tile:
           a. Get dominant texture color (layer 0)
           b. Fill 256x256 image with that color
        2. Convert to BLP

    Target: ~50 lines, NOT production quality
    """
    from PIL import Image

    blp_data = {}

    for (tile_x, tile_y), adt_data in adt_data_dict.items():
        texture_paths = adt_data.get('texture_paths', [])

        # Get base color from first texture
        if len(texture_paths) == 0:
            base_color = (128, 128, 128)  # Neutral gray fallback
        else:
            base_color = texture_color_map.get(texture_paths[0], (128, 128, 128))

        # Create simple solid-color image
        img = Image.new('RGB', (256, 256), base_color)

        # Convert to BLP
        blp_bytes = _image_to_blp(img)
        blp_data[(tile_x, tile_y)] = blp_bytes

    return blp_data


def _image_to_blp(image):
    """Convert PIL Image to BLP bytes using PNG2BLP."""
    from blp import PNG2BLP
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        png_path = os.path.join(tmpdir, "temp.png")
        blp_path = os.path.join(tmpdir, "temp.blp")

        image.save(png_path, "PNG")

        converter = PNG2BLP()
        converter.convert(png_path, blp_path, generate_mipmaps=False)

        with open(blp_path, 'rb') as f:
            return f.read()
```

---

## 4. Integration with build_zone() Pipeline

### 4.1 Modified `world_builder/__init__.py`

```python
def build_zone(name, output_dir, coords=None, heightmap=None, texture_paths=None,
               splat_map=None, area_id=0, dbc_dir=None, mphd_flags=0x80,
               minimap_export_dir=None, texture_color_map=None):
    """
    High-level API to build a complete custom zone.

    New Args:
        minimap_export_dir: Path to Noggit minimap export directory.
                            If None, generates simple fallback test tiles.
        texture_color_map: Dict mapping texture path -> RGB tuple for fallback minimap.
    """
    # ... existing code for DBC, WDT, ADT ...

    # Phase 5: Process minimap tiles
    from .minimap_pipeline import import_minimap_tiles, generate_test_minimaps

    if minimap_export_dir:
        # Primary workflow: Import from Noggit export
        result = import_minimap_tiles(minimap_export_dir, name, wdt_data=wdt_data)
        minimap_blps = result['blp_data']
        md5translate = result['md5translate']

        if result['missing_tiles']:
            print(f"Warning: Missing minimap tiles: {result['missing_tiles']}")
    else:
        # Fallback workflow: Generate simple test tiles
        adt_data_dict = {
            (x, y): {'texture_paths': texture_paths}
            for x, y in coords
        }

        if texture_color_map is None:
            texture_color_map = _generate_default_color_map(texture_paths)

        minimap_blps = generate_test_minimaps(adt_data_dict, texture_color_map)
        md5translate = _generate_md5translate(minimap_blps, name)

    # Phase 6: Pack into MPQ structure
    packer = MPQPacker(output_dir)
    packer.add_wdt(name, wdt_data)
    for (x, y), data in adt_files.items():
        packer.add_adt(name, x, y, data)

    # Add minimap tiles to MPQ
    for (x, y), blp_data in minimap_blps.items():
        minimap_path = f"Textures\\Minimap\\{name}\\map{x:02d}_{y:02d}.blp"
        packer.add_file(minimap_path, blp_data)

    # Add md5translate.trs
    md5translate_path = f"Textures\\Minimap\\{name}\\md5translate.trs"
    packer.add_file(md5translate_path, md5translate.encode('utf-8'))

    output_path = packer.build_directory()

    result['minimap_paths'] = [
        os.path.join(output_path, "Textures", "Minimap", name, f"map{x:02d}_{y:02d}.blp")
        for x, y in coords
    ]

    return result
```

### 4.2 Default Color Map (for Fallback)

```python
def _generate_default_color_map(texture_paths):
    """Generate default color map from texture paths (for testing fallback)."""
    defaults = {
        r'grass': (100, 140, 70),
        r'dirt': (120, 90, 60),
        r'rock': (90, 85, 80),
        r'sand': (210, 190, 150),
        r'snow': (240, 245, 250),
        r'water': (50, 100, 150),
    }

    color_map = {}
    for path in texture_paths:
        path_lower = path.lower()
        matched = False
        for pattern, color in defaults.items():
            if pattern in path_lower:
                color_map[path] = color
                matched = True
                break
        if not matched:
            color_map[path] = (128, 128, 128)  # Neutral gray

    return color_map
```

---

## 5. Usage Examples

### 5.1 Primary Workflow: Import from Noggit

```python
from world_builder import build_zone

# User has exported minimap tiles from Noggit
result = build_zone(
    name="TelAbim",
    output_dir="./output",
    coords=[(31, 31), (31, 32), (32, 31), (32, 32)],
    heightmap=heightmap_data,
    texture_paths=texture_paths,
    minimap_export_dir="./noggit_exports/telabim_minimaps",  # Noggit exports here
    dbc_dir="./DBFilesClient",
)

print("Minimap tiles imported and packed:")
for path in result['minimap_paths']:
    print(f"  {path}")
```

### 5.2 Fallback Workflow: Simple Test Tiles

```python
from world_builder import build_zone

# No Noggit export, generate simple test tiles
texture_color_map = {
    "Tileset\\Tropical\\TropicalBeach.blp": (220, 200, 150),
    "Tileset\\Tropical\\TropicalGrass.blp": (70, 130, 50),
}

result = build_zone(
    name="TelAbim",
    output_dir="./output",
    coords=[(31, 31), (31, 32), (32, 31), (32, 32)],
    heightmap=heightmap_data,
    texture_paths=list(texture_color_map.keys()),
    texture_color_map=texture_color_map,
    minimap_export_dir=None,  # Triggers fallback generation
    dbc_dir="./DBFilesClient",
)

print("Simple test minimap tiles generated")
```

---

## 6. Testing Approach

### 6.1 Unit Tests

```python
# tests/test_minimap_pipeline.py
import unittest
from world_builder.minimap_pipeline import (
    _validate_tile_naming,
    _detect_tile_format,
    _generate_md5translate,
)

class TestMinimapPipeline(unittest.TestCase):

    def test_validate_tile_naming_valid(self):
        self.assertEqual(_validate_tile_naming("map32_32.blp"), (32, 32))
        self.assertEqual(_validate_tile_naming("map00_00.tga"), (0, 0))
        self.assertEqual(_validate_tile_naming("map63_63.png"), (63, 63))

    def test_validate_tile_naming_invalid(self):
        with self.assertRaises(ValueError):
            _validate_tile_naming("minimap32_32.blp")  # Wrong prefix
        with self.assertRaises(ValueError):
            _validate_tile_naming("map32_32")  # No extension
        with self.assertRaises(ValueError):
            _validate_tile_naming("map64_32.blp")  # Out of range

    def test_generate_md5translate(self):
        blp_data = {
            (32, 32): b'fake_blp_data_1',
            (32, 33): b'fake_blp_data_2',
        }

        md5translate = _generate_md5translate(blp_data, "TestMap")

        self.assertIn("TestMap\\map32_32.blp;", md5translate)
        self.assertIn("TestMap\\map32_33.blp;", md5translate)
        self.assertTrue(md5translate.endswith("\r\n"))
```

### 6.2 Integration Test

```python
def test_import_minimap_tiles_integration():
    """Test importing minimap tiles from directory."""
    import tempfile
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create fake exported tiles
        for x, y in [(32, 32), (32, 33)]:
            img = Image.new('RGB', (256, 256), (100, 150, 200))
            img_path = os.path.join(tmpdir, f"map{x:02d}_{y:02d}.png")
            img.save(img_path, "PNG")

        # Import tiles
        result = import_minimap_tiles(tmpdir, "TestMap")

        # Verify
        assert (32, 32) in result['blp_data']
        assert (32, 33) in result['blp_data']
        assert len(result['blp_data']) == 2
        assert result['blp_data'][(32, 32)].startswith(b'BLP2')
        assert 'TestMap\\map32_32.blp' in result['md5translate']
```

---

## 7. Performance & Scope

### 7.1 Expected Performance

- Import pipeline: ~100-200ms per tile (format detection + conversion if needed)
- Fallback generation: ~50-100ms per tile (simple coloring + BLP conversion)
- For a 9-tile zone: ~1-2 seconds total

### 7.2 Module Scope

- Target: ~100-150 lines total
- Primary function (import_minimap_tiles): ~40 lines
- Fallback function (generate_test_minimaps): ~50 lines
- Helper functions: ~60 lines

---

## 8. Implementation Checklist

### Phase 1: Core Pipeline
- [ ] Create `world_builder/minimap_pipeline.py`
- [ ] Implement `_validate_tile_naming()`
- [ ] Implement `_detect_tile_format()`
- [ ] Implement `_convert_to_blp()`
- [ ] Implement `_generate_md5translate()`
- [ ] Implement `import_minimap_tiles()`

### Phase 2: Fallback Generator
- [ ] Implement `generate_test_minimaps()`
- [ ] Implement `_image_to_blp()`

### Phase 3: Integration
- [ ] Modify `world_builder/__init__.py`
- [ ] Add `minimap_export_dir` parameter to `build_zone()`
- [ ] Add `texture_color_map` parameter
- [ ] Implement `_generate_default_color_map()`
- [ ] Update MPQPacker calls to include minimap files and md5translate.trs

### Phase 4: Testing
- [ ] Write unit tests for naming validation
- [ ] Write unit tests for format detection
- [ ] Write unit tests for md5translate generation
- [ ] Write integration test for import pipeline
- [ ] Write integration test for fallback generator
- [ ] Test with real Noggit export

### Phase 5: Documentation
- [ ] Add docstrings to all functions
- [ ] Document Noggit export workflow
- [ ] Add usage examples

---

## 9. Success Criteria

1. **Pipeline works**: Can import Noggit-exported tiles (BLP/TGA/PNG) and pack into MPQ
2. **Validation works**: Catches invalid naming, missing tiles, wrong formats
3. **md5translate.trs generated correctly**: WoW client can read the file
4. **Fallback works**: Can generate simple test tiles for rapid prototyping
5. **Module is small**: ~100-150 lines total, simple and maintainable
6. **Integration clean**: Seamlessly integrated into `build_zone()` pipeline

---

## 10. Key Simplifications

### 10.1 What This Plan Does NOT Include

- **No procedural generation**: No heightmap-based relief shading
- **No texture compositing**: No blending multiple textures per tile
- **No advanced algorithms**: No gradient computation, no lighting simulation
- **No quality targets**: Fallback is "good enough for testing" only

### 10.2 Why This Approach

User feedback: "the minimap or map generation is fine since I only need to open the map and take it."

Translation: Noggit already does minimap generation perfectly. The agent's job is to handle file conversion, not reimplementation.

**Result**: A simple ~100-150 line conversion pipeline instead of a complex procedural generator.

---

## End of Plan

This plan documents a lightweight minimap tile CONVERSION PIPELINE focused exclusively on file handling. The primary workflow leverages Noggit's built-in export capabilities (a single menu click). The fallback provides simple solid-color test tiles for rapid prototyping without requiring Noggit.
