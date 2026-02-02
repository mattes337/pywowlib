# Plan: Fully Automated Procedural Artwork Generation Pipeline

## Overview

This plan defines a **fully automated procedural artwork generation pipeline** that generates ALL visual assets for a WoW 3.3.5a zone WITHOUT any manual art tools. Every asset is generated programmatically using Python Pillow (PIL) with algorithms for terrain visualization, stylized compositions, and text rendering.

**Status**: Implementation Plan
**Priority**: High (blocks full zone automation)
**Dependencies**:
- `plan-blp-writer.md` (BLP file creation)
- `plan-minimap-generator.md` (minimap tiles from ADT)
- Python Pillow library (image manipulation)
- NumPy (heightmap processing)
- SciPy (edge detection, morphological operations)

**Scope**:
- World map art (procedural zone overview illustrations)
- Subzone discovery overlays (9 per zone, procedurally generated)
- Loading screen art (procedural scenic compositions)
- Dungeon map overlays (procedural floor plans)

**Out of Scope**:
- Minimap tiles (covered by plan-minimap-generator.md)
- 3D model textures
- Character/NPC artwork
- UI elements beyond maps

---

## Architecture

### Module Structure

```
world_builder/
├── artwork_pipeline.py          # Main module (public API)
├── artwork/
│   ├── __init__.py
│   ├── world_map.py            # World map art generator
│   ├── subzone_overlays.py     # Subzone discovery overlays
│   ├── loading_screens.py      # Loading screen art
│   ├── dungeon_maps.py         # Dungeon map overlays
│   ├── color_palettes.py       # Terrain theme color schemes
│   ├── image_effects.py        # Reusable effects (gradients, relief, etc)
│   ├── text_rendering.py       # Label and text overlay utilities
│   └── mpq_paths.py            # MPQ path generation
└── tests/
    └── test_artwork_pipeline.py
```

### Data Flow

```
Input Data (heightmap, subzones, theme)
    ↓
Procedural Image Generation (Pillow algorithms)
    ↓
Composition & Effects (gradients, relief, labels)
    ↓
BLP Conversion (via plan-blp-writer.md)
    ↓
MPQ Packaging
    ↓
WoW Client Display
```

---

## 1. World Map Art Generator

### Purpose
Procedurally generate the stylized zone overview illustration shown when opening the map UI (WorldMapArea). Creates a top-down artistic representation from heightmap data.

### Input
```python
@dataclass
class WorldMapInput:
    heightmap: np.ndarray              # 2D heightmap (0.0-1.0 normalized)
    subzones: List[SubzoneDefinition]  # Subzone boundaries and metadata
    water_level: float                 # Z coordinate for water surface
    size: Tuple[int, int]              # Output resolution (default 1002x668)
    zone_name: str                     # For metadata
    color_palette: Optional[ColorPalette] = None  # Theme colors
```

### Procedural Generation Algorithm

#### Step 1: Terrain Base Layer Generation
```python
def generate_terrain_base(heightmap: np.ndarray, water_level: float,
                         color_palette: ColorPalette) -> Image.Image:
    """
    Procedurally generate color-coded terrain from heightmap.

    Algorithm:
    1. Resample heightmap to output size
    2. For each pixel, map height to terrain color:
       - Below water_level: interpolate deep blue → shallow blue
       - water_level to +0.1: beach (sandy yellow)
       - 0.1 to 0.4: lowland (green vegetation)
       - 0.4 to 0.6: midland (darker green/brown)
       - 0.6 to 0.8: highland (grey rock)
       - 0.8 to 1.0: peak (white/snow)
    3. Apply bilinear interpolation for smooth color transitions
    """
    from PIL import Image
    from scipy.ndimage import zoom

    # Resample heightmap to output size
    scale_y = size[1] / heightmap.shape[0]
    scale_x = size[0] / heightmap.shape[1]
    resampled = zoom(heightmap, (scale_y, scale_x), order=1)

    # Create RGB image
    img = Image.new('RGB', size)
    pixels = img.load()

    for y in range(size[1]):
        for x in range(size[0]):
            height = resampled[y, x]
            color = interpolate_terrain_color(height, water_level, color_palette)
            pixels[x, y] = color

    return img
```

#### Step 2: Subzone Color Overlay
```python
def apply_subzone_colors(base_img: Image.Image,
                        subzones: List[SubzoneDefinition],
                        world_bounds: Tuple[float, float, float, float]) -> Image.Image:
    """
    Overlay subzone characteristic colors with transparency.

    Algorithm:
    1. Create transparent RGBA layer
    2. For each subzone:
       - Convert world coordinates to pixel coordinates
       - Draw filled polygon with subzone color at 40% opacity
    3. Alpha composite onto base image
    """
    from PIL import Image, ImageDraw

    overlay = Image.new('RGBA', base_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for subzone in subzones:
        # Convert world coordinates to map pixels
        polygon = world_coords_to_map_pixels(subzone.boundary, world_bounds, base_img.size)
        color_rgba = subzone.color_theme + (102,)  # 40% alpha (102/255)
        draw.polygon(polygon, fill=color_rgba)

    return Image.alpha_composite(base_img.convert('RGBA'), overlay)
```

#### Step 3: Relief Shading (Hillshading)
```python
def apply_relief_shading(img: Image.Image, heightmap: np.ndarray,
                        light_angle: float = 315, intensity: float = 0.4) -> Image.Image:
    """
    Apply procedural relief shading for depth perception.

    Algorithm (Hillshading):
    1. Calculate heightmap gradients (dx, dy) using Sobel filter
    2. Compute slope and aspect from gradients
    3. Calculate shading: dot product of surface normal with light direction
       - Light from NW (315°) at 45° elevation (WoW standard)
    4. Normalize shading to 0-255 grayscale
    5. Apply as multiply blend at specified intensity
    """
    import numpy as np
    from PIL import Image, ImageChops
    from scipy.ndimage import sobel

    # Calculate gradients
    dx = sobel(heightmap, axis=1)
    dy = sobel(heightmap, axis=0)

    # Calculate slope and aspect
    slope = np.arctan(np.sqrt(dx**2 + dy**2))
    aspect = np.arctan2(-dx, dy)

    # Light direction (azimuth=315°, altitude=45°)
    azimuth_rad = np.radians(light_angle)
    altitude_rad = np.radians(45)

    # Hillshading formula
    shading = (np.cos(altitude_rad) * np.cos(slope) +
               np.sin(altitude_rad) * np.sin(slope) *
               np.cos(azimuth_rad - aspect))

    # Normalize to 0-255
    shading = ((shading + 1) / 2 * 255).astype(np.uint8)

    # Resize to match image
    from scipy.ndimage import zoom
    scale_y = img.size[1] / shading.shape[0]
    scale_x = img.size[0] / shading.shape[1]
    shading_resized = zoom(shading, (scale_y, scale_x), order=1)

    # Convert to PIL image
    shading_img = Image.fromarray(shading_resized, mode='L').convert('RGB')

    # Multiply blend
    result = ImageChops.multiply(img, shading_img)

    # Mix with original based on intensity
    return Image.blend(img, result, intensity)
```

#### Step 4: Coastline Effects (Procedural)
```python
def add_coastline_effects(img: Image.Image, heightmap: np.ndarray,
                         water_level: float) -> Image.Image:
    """
    Procedurally enhance water edges with borders and foam.

    Algorithm:
    1. Detect coastline: pixels where height ≈ water_level (±0.05)
    2. Generate dark water edge (1-2 pixels inward from coast)
    3. Generate foam line (1 pixel on land side of coast)
    4. Alpha composite onto image
    """
    from scipy.ndimage import binary_dilation, binary_erosion

    # Detect coastline (boolean mask)
    water_mask = heightmap <= water_level
    land_mask = heightmap > water_level

    # Dilate water mask to find edge
    water_dilated = binary_dilation(water_mask, iterations=2)
    coastline_edge = water_dilated & land_mask  # Land pixels adjacent to water

    # Erode land mask to find foam line
    land_eroded = binary_erosion(land_mask, iterations=1)
    foam_line = land_mask & ~land_eroded

    # Resize masks to image size
    from scipy.ndimage import zoom
    scale_y = img.size[1] / coastline_edge.shape[0]
    scale_x = img.size[0] / coastline_edge.shape[1]

    edge_resized = zoom(coastline_edge.astype(np.uint8), (scale_y, scale_x), order=0)
    foam_resized = zoom(foam_line.astype(np.uint8), (scale_y, scale_x), order=0)

    # Create overlay
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay_pixels = overlay.load()

    for y in range(img.size[1]):
        for x in range(img.size[0]):
            if edge_resized[y, x] > 0:
                overlay_pixels[x, y] = (0, 40, 80, 180)  # Dark blue edge
            elif foam_resized[y, x] > 0:
                overlay_pixels[x, y] = (200, 220, 240, 120)  # White foam

    return Image.alpha_composite(img.convert('RGBA'), overlay)
```

#### Step 5: Subzone Labels (Procedural Text)
```python
def add_subzone_labels(img: Image.Image, subzones: List[SubzoneDefinition],
                      world_bounds: Tuple[float, float, float, float]) -> Image.Image:
    """
    Procedurally add text labels at subzone centroids.

    Algorithm:
    1. Calculate centroid of each subzone polygon
    2. Convert centroid to pixel coordinates
    3. Render text with outline (draw outline in 8 directions, then fill)
    4. Use fallback font if WoW font unavailable
    """
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(img)

    # Load font (with fallback)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/georgia.ttf", size=18)
    except:
        font = ImageFont.load_default()

    for subzone in subzones:
        # Calculate centroid
        centroid = calculate_polygon_centroid(subzone.boundary)
        pixel = world_coords_to_map_pixels([centroid], world_bounds, img.size)[0]

        # Draw text with black outline (WoW style)
        text = subzone.name
        text_color = (255, 255, 220)  # Pale yellow
        outline_color = (0, 0, 0)

        # Draw outline (8 directions)
        for offset_x in [-1, 0, 1]:
            for offset_y in [-1, 0, 1]:
                if offset_x != 0 or offset_y != 0:
                    draw.text((pixel[0] + offset_x, pixel[1] + offset_y),
                             text, font=font, fill=outline_color)

        # Draw main text
        draw.text(pixel, text, font=font, fill=text_color)

    return img
```

### Output
```python
@dataclass
class WorldMapOutput:
    image: Image.Image          # Pillow image object (RGB/RGBA)
    blp_path: str               # MPQ path: Interface/WorldMap/{ZoneName}/{ZoneName}.blp
    size: Tuple[int, int]       # Actual output dimensions (1002x668)
```

### Tel'Abim Procedural Example
```python
from world_builder.artwork_pipeline import generate_world_map
from world_builder.artwork.color_palettes import PALETTES

# Tropical island color palette
telabim_palette = PALETTES['tropical']  # Predefined tropical colors

# Subzone definitions with characteristic colors
telabim_subzones = [
    SubzoneDefinition(
        name="Palmbreak Shore",
        boundary=[(x1, y1), ...],  # World coordinates
        color_theme=(240, 220, 180),  # Sandy beach
    ),
    SubzoneDefinition(
        name="The Banana Grove",
        boundary=[...],
        color_theme=(120, 200, 80),  # Bright jungle green
    ),
    # ... 7 more subzones
]

# Generate world map (fully procedural)
world_map_img = generate_world_map(
    heightmap=telabim_heightmap,  # 2D numpy array
    subzones=telabim_subzones,
    water_level=0.0,
    size=(1002, 668),
    zone_name="TelAbim",
    color_palette=telabim_palette,
)

# Output: Pillow Image with stylized zone overview
# - Color-coded terrain by elevation
# - Subzone color overlays
# - Relief shading for depth
# - Coastline effects
# - Subzone name labels
```

---

## 2. Subzone Discovery Overlays

### Purpose
Procedurally generate colored overlay textures revealed when a player discovers a subzone (WorldMapOverlay.dbc entries). Each overlay is a silhouette of the subzone boundary with characteristic color.

### Input
```python
@dataclass
class SubzoneOverlayInput:
    subzone: SubzoneDefinition      # Single subzone to generate overlay for
    world_map_bounds: Tuple[float, float, float, float]  # (left, right, top, bottom)
    padding: int = 10               # Pixels to add around subzone boundary
```

### Procedural Generation Algorithm

#### Step 1: Boundary Extraction
```python
def extract_subzone_boundary(subzone: SubzoneDefinition,
                            world_bounds: Tuple[float, float, float, float],
                            padding: int = 10) -> Tuple[Tuple[int, int, int, int], List[Tuple[int, int]]]:
    """
    Convert subzone world coordinates to pixel coordinates.

    Algorithm:
    1. Convert each boundary point from world coords to normalized (0-1)
    2. Calculate bounding box (min/max x/y)
    3. Add padding to bounding box
    4. Return bbox and pixel polygon
    """
    pixels = []
    for wx, wy in subzone.boundary:
        # Normalize to 0-1
        nx = (wx - world_bounds[0]) / (world_bounds[1] - world_bounds[0])
        ny = (wy - world_bounds[2]) / (world_bounds[3] - world_bounds[2])
        pixels.append((nx, ny))

    # Calculate bounding box
    min_x = min(p[0] for p in pixels)
    max_x = max(p[0] for p in pixels)
    min_y = min(p[1] for p in pixels)
    max_y = max(p[1] for p in pixels)

    # Convert to pixel coordinates with padding
    width = int((max_x - min_x) * 1002) + padding * 2
    height = int((max_y - min_y) * 668) + padding * 2

    bbox = (0, 0, width, height)

    # Translate pixels to local coordinates
    local_pixels = [
        (int((p[0] - min_x) * 1002) + padding,
         int((p[1] - min_y) * 668) + padding)
        for p in pixels
    ]

    return bbox, local_pixels
```

#### Step 2: Silhouette Mask Generation
```python
def create_subzone_silhouette(pixels: List[Tuple[int, int]],
                             size: Tuple[int, int]) -> Image.Image:
    """
    Procedurally create silhouette mask of subzone shape.

    Algorithm:
    1. Create grayscale image (black background)
    2. Draw filled polygon using boundary pixels
    3. Return binary mask (0=outside, 255=inside)
    """
    from PIL import Image, ImageDraw

    mask = Image.new('L', size, 0)  # Grayscale
    draw = ImageDraw.Draw(mask)
    draw.polygon(pixels, fill=255)

    return mask
```

#### Step 3: Color and Texture Application
```python
def apply_overlay_style(mask: Image.Image,
                       subzone: SubzoneDefinition) -> Image.Image:
    """
    Apply subzone color with transparency and subtle texture noise.

    Algorithm:
    1. Create RGBA image
    2. For each pixel in mask:
       - If inside (mask > 0), apply subzone color with 70% opacity
       - Add random noise (±10) to RGB for texture variation
    3. Return styled overlay
    """
    import random
    from PIL import Image

    img = Image.new('RGBA', mask.size, (0, 0, 0, 0))
    mask_pixels = mask.load()
    img_pixels = img.load()

    r_base, g_base, b_base = subzone.color_theme
    alpha = 180  # 70% opacity

    for y in range(mask.size[1]):
        for x in range(mask.size[0]):
            if mask_pixels[x, y] > 0:
                # Add subtle texture noise
                noise = random.randint(-10, 10)
                r = max(0, min(255, r_base + noise))
                g = max(0, min(255, g_base + noise))
                b = max(0, min(255, b_base + noise))
                img_pixels[x, y] = (r, g, b, alpha)

    return img
```

#### Step 4: Border Glow Effects
```python
def add_border_effects(img: Image.Image, mask: Image.Image) -> Image.Image:
    """
    Add subtle glowing border to overlay edge.

    Algorithm:
    1. Detect edges: dilate mask, subtract original (morphological edge)
    2. Draw white glow pixels at edges with 50% opacity
    3. Alpha composite onto overlay
    """
    from scipy.ndimage import binary_dilation
    import numpy as np
    from PIL import Image

    # Convert mask to boolean array
    mask_array = np.array(mask) > 128

    # Detect edges (dilate - original)
    dilated = binary_dilation(mask_array, iterations=1)
    edges = dilated & ~mask_array

    # Create border overlay
    border = Image.new('RGBA', img.size, (0, 0, 0, 0))
    border_pixels = border.load()

    for y in range(edges.shape[0]):
        for x in range(edges.shape[1]):
            if edges[y, x]:
                border_pixels[x, y] = (255, 255, 255, 128)  # White glow, 50% opacity

    return Image.alpha_composite(img, border)
```

### Output
```python
@dataclass
class SubzoneOverlayOutput:
    image: Image.Image              # Pillow RGBA image (variable size)
    blp_path: str                   # Interface/WorldMap/{ZoneName}/{SubzoneName}_overlay.blp
    map_position: Tuple[int, int]   # Top-left corner on world map
    size: Tuple[int, int]           # Overlay dimensions
```

### Tel'Abim Procedural Example
```python
from world_builder.artwork_pipeline import generate_subzone_overlays

# Generate all 9 subzone overlays procedurally
overlays = generate_subzone_overlays(
    subzones=telabim_subzones,
    world_map_bounds=(-5000, 5000, -5000, 5000),
)

# Output: Dictionary of 9 RGBA images
# - "Palmbreak Shore": 140x80 px colored silhouette
# - "The Banana Grove": 180x120 px colored silhouette
# - ... (7 more overlays)
# Each with characteristic color, texture noise, and glowing border
```

---

## 3. Loading Screen Art Generator

### Purpose
Procedurally generate scenic landscape compositions displayed when entering a zone or dungeon. Theme-based layered composition using programmatic drawing.

### Input
```python
@dataclass
class LoadingScreenInput:
    zone_name: str                  # Display text
    theme: str                      # 'tropical', 'volcanic', 'underground', 'titan'
    size: Tuple[int, int]           # (1024, 768) or (2048, 1536) widescreen
    custom_elements: Optional[Dict] = None  # Override composition
```

### Procedural Generation Algorithm

#### Step 1: Theme-Based Layer Composition
```python
# Predefined composition recipes per theme
LOADING_SCREEN_THEMES = {
    'tropical': {
        'sky': ('gradient', (255, 180, 100), (100, 150, 200)),  # Sunset gradient
        'background': ('island_silhouette', (20, 60, 40)),      # Dark island
        'midground': ('palm_trees', (40, 80, 50)),              # Tree silhouettes
        'foreground': ('water_horizon', (50, 120, 180)),        # Ocean
        'accent': ('sun_glow', (255, 200, 100)),                # Sun glow
    },
    'volcanic': {
        'sky': ('gradient', (60, 40, 40), (180, 80, 60)),       # Dark red sky
        'background': ('mountain_peak', (80, 50, 40)),          # Volcanic peak
        'midground': ('lava_flows', (255, 100, 50)),            # Orange lava
        'foreground': ('volcanic_rocks', (60, 40, 30)),         # Black rocks
        'accent': ('fire_glow', (255, 150, 50)),                # Orange glow
    },
    'underground': {
        'sky': ('solid', (20, 20, 30)),                         # Dark ceiling
        'background': ('cavern_walls', (40, 40, 50)),           # Stone walls
        'midground': ('titan_pillars', (60, 60, 80)),           # Stone pillars
        'foreground': ('rocky_ground', (30, 30, 40)),           # Dark ground
        'accent': ('energy_crystals', (100, 150, 255)),         # Blue crystals
    },
    'titan': {
        'sky': ('gradient', (40, 40, 60), (100, 100, 140)),     # Blue-grey sky
        'background': ('titan_architecture', (80, 80, 100)),    # Stone structures
        'midground': ('titan_statues', (100, 100, 120)),        # Statue silhouettes
        'foreground': ('floor_tiles', (60, 60, 80)),            # Tiled floor
        'accent': ('arcane_lightning', (150, 200, 255)),        # Lightning effect
    },
}

def generate_loading_screen_composition(theme: str, size: Tuple[int, int]) -> Image.Image:
    """
    Layer-by-layer procedural composition.

    Algorithm:
    1. Get theme recipe
    2. Generate each layer (sky → background → midground → foreground → accent)
    3. Composite layers using alpha blending
    """
    layers_spec = LOADING_SCREEN_THEMES[theme]
    img = Image.new('RGB', size, (0, 0, 0))

    for layer_name in ['sky', 'background', 'midground', 'foreground', 'accent']:
        layer_spec = layers_spec[layer_name]
        layer_img = generate_layer(layer_spec, size)
        img = alpha_blend_layer(img, layer_img)

    return img
```

#### Step 2: Sky Generation (Procedural Gradients)
```python
def generate_sky_gradient(size: Tuple[int, int],
                         top_color: Tuple[int, int, int],
                         bottom_color: Tuple[int, int, int]) -> Image.Image:
    """
    Generate vertical gradient sky.

    Algorithm:
    1. For each row y, calculate interpolation factor t = y / height
    2. Interpolate color: color = top * (1-t) + bottom * t
    3. Fill entire row with interpolated color
    """
    from PIL import Image

    img = Image.new('RGB', size)
    pixels = img.load()

    for y in range(size[1]):
        t = y / size[1]  # 0 at top, 1 at bottom
        r = int(top_color[0] * (1-t) + bottom_color[0] * t)
        g = int(top_color[1] * (1-t) + bottom_color[1] * t)
        b = int(top_color[2] * (1-t) + bottom_color[2] * t)
        color = (r, g, b)

        for x in range(size[0]):
            pixels[x, y] = color

    return img
```

#### Step 3: Silhouette Generation (Procedural Shapes)
```python
def generate_island_silhouette(size: Tuple[int, int],
                              color: Tuple[int, int, int]) -> Image.Image:
    """
    Procedurally generate island landmass with volcanic peak.

    Algorithm:
    1. Generate curved base using Bezier curve
    2. Add volcanic peak (triangle at center)
    3. Fill shapes with color
    """
    from PIL import Image, ImageDraw

    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Island base (curved bottom half)
    base_points = [
        (0, size[1]),  # Bottom-left
        (size[0] * 0.2, size[1] * 0.7),  # Left curve
        (size[0] * 0.5, size[1] * 0.6),  # Center low
        (size[0] * 0.8, size[1] * 0.7),  # Right curve
        (size[0], size[1]),  # Bottom-right
    ]
    draw.polygon(base_points, fill=color)

    # Volcanic peak (triangle)
    peak_points = [
        (size[0] * 0.45, size[1] * 0.6),  # Left base
        (size[0] * 0.5, size[1] * 0.3),   # Peak
        (size[0] * 0.55, size[1] * 0.6),  # Right base
    ]
    draw.polygon(peak_points, fill=color)

    return img


def generate_palm_tree_silhouettes(size: Tuple[int, int],
                                   color: Tuple[int, int, int]) -> Image.Image:
    """
    Procedurally generate 3-5 palm tree silhouettes.

    Algorithm:
    1. Randomly position 3-5 trees across width
    2. For each tree:
       - Draw trunk (narrow rectangle)
       - Draw fronds (ellipses radiating from top)
    """
    import random
    from PIL import Image, ImageDraw

    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    num_trees = random.randint(3, 5)

    for i in range(num_trees):
        # Position
        x = (i + 1) * size[0] // (num_trees + 1)
        y_base = size[1] - random.randint(50, 150)
        height = random.randint(100, 150)

        # Trunk
        trunk_width = 8
        draw.rectangle(
            [x - trunk_width//2, y_base - height, x + trunk_width//2, y_base],
            fill=color
        )

        # Fronds (5-7 ellipses)
        for angle in range(0, 360, 50):
            rad = math.radians(angle)
            frond_x = x + int(math.cos(rad) * 40)
            frond_y = y_base - height + int(math.sin(rad) * 40)
            draw.ellipse(
                [frond_x-30, frond_y-10, frond_x+30, frond_y+10],
                fill=color
            )

    return img


def generate_titan_architecture(size: Tuple[int, int],
                                color: Tuple[int, int, int]) -> Image.Image:
    """
    Procedurally generate geometric titan structures.

    Algorithm:
    1. Draw large rectangular pillars (3-4)
    2. Draw arched tops
    3. Draw connecting beams
    """
    from PIL import Image, ImageDraw

    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 3 pillars
    for i in range(3):
        x = (i + 1) * size[0] // 4
        width = 60
        height = size[1] * 0.8

        # Pillar body
        draw.rectangle(
            [x - width//2, size[1] - height, x + width//2, size[1]],
            fill=color
        )

        # Arch top
        draw.arc(
            [x - width, size[1] - height - 50, x + width, size[1] - height + 50],
            start=0, end=180, fill=color, width=10
        )

    # Connecting beam
    draw.rectangle(
        [size[0] * 0.1, size[1] - size[1] * 0.8,
         size[0] * 0.9, size[1] - size[1] * 0.8 + 20],
        fill=color
    )

    return img
```

#### Step 4: Glow Effects (Procedural)
```python
def add_radial_glow(img: Image.Image, center: Tuple[int, int],
                   color: Tuple[int, int, int], radius: int,
                   falloff: float = 2.0) -> Image.Image:
    """
    Add radial gradient glow effect.

    Algorithm:
    1. For each pixel, calculate distance from center
    2. Calculate intensity: (1 - distance/radius)^falloff
    3. Blend glow color with background based on intensity
    """
    import math
    from PIL import Image

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay_pixels = overlay.load()

    cx, cy = center

    for y in range(img.size[1]):
        for x in range(img.size[0]):
            distance = math.sqrt((x - cx)**2 + (y - cy)**2)

            if distance < radius:
                t = 1 - (distance / radius)
                intensity = t ** falloff
                alpha = int(intensity * 200)
                overlay_pixels[x, y] = color + (alpha,)

    return Image.alpha_composite(img.convert('RGBA'), overlay)


def add_lightning_arcs(img: Image.Image, color: Tuple[int, int, int],
                      branches: int = 8) -> Image.Image:
    """
    Add branching lightning pattern.

    Algorithm:
    1. Choose random start points at top
    2. For each branch:
       - Draw jagged line downward with random offsets
       - Subdivide with smaller branches
    3. Apply glow effect around lines
    """
    import random
    from PIL import Image, ImageDraw

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for _ in range(branches):
        x = random.randint(0, img.size[0])
        y = 0

        # Main branch
        points = [(x, y)]
        while y < img.size[1]:
            x += random.randint(-30, 30)
            y += random.randint(50, 100)
            points.append((x, y))

        # Draw with glow
        for i in range(len(points) - 1):
            draw.line([points[i], points[i+1]], fill=color + (200,), width=3)

    return Image.alpha_composite(img.convert('RGBA'), overlay)
```

#### Step 5: Zone Name Text Overlay
```python
def add_zone_name_text(img: Image.Image, zone_name: str) -> Image.Image:
    """
    Add zone name with WoW-style formatting.

    Algorithm:
    1. Load large serif font (Georgia fallback)
    2. Calculate centered position (10% from top)
    3. Draw text with shadow and outline
    """
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(img)

    # Load font
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/georgia.ttf", size=72)
    except:
        font = ImageFont.load_default()

    # Calculate position (centered, top)
    bbox = draw.textbbox((0, 0), zone_name, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (img.size[0] - text_width) // 2
    y = img.size[1] // 10

    # Draw shadow (offset 4 pixels down-right)
    draw.text((x + 4, y + 4), zone_name, font=font, fill=(0, 0, 0))

    # Draw outline (8 directions)
    for offset_x in [-2, 0, 2]:
        for offset_y in [-2, 0, 2]:
            if offset_x != 0 or offset_y != 0:
                draw.text((x + offset_x, y + offset_y), zone_name,
                         font=font, fill=(100, 80, 50))

    # Draw main text
    draw.text((x, y), zone_name, font=font, fill=(255, 240, 200))

    return img
```

### Output
```python
@dataclass
class LoadingScreenOutput:
    image: Image.Image                  # Pillow RGB image
    blp_path: str                       # Interface/Glues/LoadingScreens/{ZoneName}.blp
    size: Tuple[int, int]               # (1024, 768) or (2048, 1536)
```

### Tel'Abim Procedural Example
```python
from world_builder.artwork_pipeline import generate_loading_screen

# Tropical theme with palm trees and sunset
loading_img = generate_loading_screen(
    zone_name="Tel'Abim",
    theme='tropical',
    size=(1024, 768),
)

# Output: Pillow Image with layered composition
# - Sunset gradient sky (orange → blue)
# - Island silhouette (dark green)
# - Palm tree silhouettes (3-5 trees)
# - Sun glow effect (orange radial gradient)
# - Zone name text "Tel'Abim" centered top
```

### Vault of Storms Procedural Example
```python
# Titan theme with architecture and lightning
loading_img = generate_loading_screen(
    zone_name="The Vault of Storms",
    theme='titan',
    size=(1024, 768),
)

# Output: Pillow Image with layered composition
# - Blue-grey gradient sky
# - Titan pillar and arch silhouettes
# - Statue silhouettes in midground
# - Tiled floor pattern
# - Branching arcane lightning (8 bolts)
# - Zone name text centered top
```

---

## 4. Dungeon Map Overlay Generator

### Purpose
Procedurally generate top-down floor plan views for dungeon instances. Renders room layout with boss markers and entrance indicator.

### Input
```python
@dataclass
class DungeonMapInput:
    layout: DungeonLayout               # Room definitions and connections
    boss_positions: List[Tuple[str, Tuple[float, float]]]  # (name, coords)
    entrance_position: Tuple[float, float]
    size: Tuple[int, int]               # Output resolution (512x512)
    dungeon_name: str
```

### Procedural Generation Algorithm

#### Step 1: Room Layout Rendering
```python
def render_room_layout(layout: DungeonLayout, size: Tuple[int, int]) -> Image.Image:
    """
    Procedurally draw dungeon rooms as colored rectangles.

    Algorithm:
    1. Calculate scale factor (world coords → pixels)
    2. For each room:
       - Convert bounds to pixel rectangle
       - Fill with color based on room type:
         * corridor: dark grey (40, 40, 40)
         * chamber: medium grey (80, 80, 80)
         * boss_room: dark red (100, 40, 40)
       - Draw border (light grey outline)
       - Add room name text (if chamber/boss)
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new('RGB', size, (0, 0, 0))  # Black background
    draw = ImageDraw.Draw(img)

    # Calculate scale
    all_x = [r.bounds[0] for r in layout.rooms] + [r.bounds[1] for r in layout.rooms]
    all_y = [r.bounds[2] for r in layout.rooms] + [r.bounds[3] for r in layout.rooms]
    world_width = max(all_x) - min(all_x)
    world_height = max(all_y) - min(all_y)
    scale = min(size[0] / world_width, size[1] / world_height) * 0.9

    # Room colors by type
    room_colors = {
        'corridor': (40, 40, 40),
        'chamber': (80, 80, 80),
        'boss_room': (100, 40, 40),
    }

    # Load font
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size=12)
    except:
        font = ImageFont.load_default()

    # Draw rooms
    for room in layout.rooms:
        # Convert world bounds to pixels
        x1 = int((room.bounds[0] - min(all_x)) * scale)
        x2 = int((room.bounds[1] - min(all_x)) * scale)
        y1 = int((room.bounds[2] - min(all_y)) * scale)
        y2 = int((room.bounds[3] - min(all_y)) * scale)

        rect = [x1, y1, x2, y2]

        # Fill room
        color = room_colors.get(room.type, (60, 60, 60))
        draw.rectangle(rect, fill=color, outline=(120, 120, 120), width=2)

        # Add label (if important room)
        if room.type in ['chamber', 'boss_room']:
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            draw.text((cx, cy), room.name, font=font, fill=(200, 200, 200), anchor='mm')

    return img
```

#### Step 2: Connection Rendering
```python
def render_connections(img: Image.Image, layout: DungeonLayout, scale: float,
                      offset: Tuple[float, float]) -> Image.Image:
    """
    Draw corridor lines connecting rooms.

    Algorithm:
    1. For each connection:
       - Find closest points on room edges
       - Draw line between points (grey, 4px width)
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)

    for conn in layout.connections:
        room_a = layout.rooms[conn.room_a_id]
        room_b = layout.rooms[conn.room_b_id]

        # Calculate room centers
        cx_a = ((room_a.bounds[0] + room_a.bounds[1]) / 2 - offset[0]) * scale
        cy_a = ((room_a.bounds[2] + room_a.bounds[3]) / 2 - offset[1]) * scale
        cx_b = ((room_b.bounds[0] + room_b.bounds[1]) / 2 - offset[0]) * scale
        cy_b = ((room_b.bounds[2] + room_b.bounds[3]) / 2 - offset[1]) * scale

        # Draw connection line
        draw.line([(cx_a, cy_a), (cx_b, cy_b)], fill=(80, 80, 80), width=4)

    return img
```

#### Step 3: Boss Markers (Procedural Icons)
```python
def add_boss_markers(img: Image.Image, boss_positions: List[Tuple[str, Tuple[float, float]]],
                    scale: float, offset: Tuple[float, float]) -> Image.Image:
    """
    Mark boss locations with red circles and 'B' text.

    Algorithm:
    1. For each boss:
       - Convert world coords to pixels
       - Draw red circle (radius 12)
       - Draw white 'B' text centered
       - Draw boss name label next to circle
    """
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", size=14)
        label_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size=10)
    except:
        font = label_font = ImageFont.load_default()

    for boss_name, (wx, wy) in boss_positions:
        # Convert to pixels
        px = int((wx - offset[0]) * scale)
        py = int((wy - offset[1]) * scale)

        # Draw red circle
        radius = 12
        bbox = [px - radius, py - radius, px + radius, py + radius]
        draw.ellipse(bbox, fill=(180, 0, 0), outline=(255, 255, 255), width=2)

        # Draw 'B'
        draw.text((px, py), 'B', font=font, fill=(255, 255, 255), anchor='mm')

        # Draw boss name
        draw.text((px + radius + 5, py), boss_name, font=label_font, fill=(220, 220, 220))

    return img
```

#### Step 4: Entrance Marker (Procedural Arrow)
```python
def add_entrance_marker(img: Image.Image, entrance: Tuple[float, float],
                       scale: float, offset: Tuple[float, float]) -> Image.Image:
    """
    Mark entrance with green arrow.

    Algorithm:
    1. Convert world coords to pixels
    2. Draw down-pointing arrow (3 vertices)
    3. Fill green, outline white
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)

    # Convert to pixels
    px = int((entrance[0] - offset[0]) * scale)
    py = int((entrance[1] - offset[1]) * scale)

    # Arrow points (down-pointing)
    arrow = [
        (px, py + 15),      # Tip
        (px - 10, py - 5),  # Left wing
        (px + 10, py - 5),  # Right wing
    ]

    draw.polygon(arrow, fill=(0, 200, 0), outline=(255, 255, 255), width=2)

    return img
```

### Output
```python
@dataclass
class DungeonMapOutput:
    image: Image.Image                      # Pillow RGB image
    blp_path: str                           # Interface/WorldMap/{DungeonName}/{DungeonName}.blp
    size: Tuple[int, int]                   # (512, 512)
```

### Vault of Storms Procedural Example
```python
from world_builder.artwork_pipeline import generate_dungeon_map
from world_builder.artwork.dungeon_maps import DungeonLayout, Room, Connection

# Define dungeon layout
vault_layout = DungeonLayout(
    rooms=[
        Room(id=0, name="Entrance Hall", type='corridor',
             bounds=(400, 600, 400, 600)),
        Room(id=1, name="Storm Chamber", type='chamber',
             bounds=(800, 1200, 800, 1200)),
        Room(id=2, name="Lightning Conduit", type='corridor',
             bounds=(1000, 1100, 1400, 1800)),
        Room(id=3, name="Titan Archive", type='chamber',
             bounds=(1400, 1800, 1600, 2000)),
        Room(id=4, name="Thunderking's Sanctum", type='boss_room',
             bounds=(1400, 2000, 2200, 2800)),
    ],
    connections=[
        Connection(room_a_id=0, room_b_id=1),
        Connection(room_a_id=1, room_b_id=2),
        Connection(room_a_id=2, room_b_id=3),
        Connection(room_a_id=3, room_b_id=4),
    ],
)

# Generate dungeon map procedurally
dungeon_map_img = generate_dungeon_map(
    layout=vault_layout,
    boss_positions=[("Thunderking Nalak", (1700, 2500))],
    entrance_position=(500, 500),
    size=(512, 512),
    dungeon_name="VaultOfStorms",
)

# Output: Pillow Image with floor plan
# - 5 colored rooms (grey/red)
# - 4 connection lines (grey)
# - Red boss marker with 'B' and name label
# - Green entrance arrow
```

---

## 5. Color Palettes Module

### Purpose
Define terrain theme color schemes for consistent procedural artwork generation.

```python
# artwork/color_palettes.py

@dataclass
class ColorPalette:
    """Color scheme for a terrain theme. All RGB tuples (0-255)."""
    deep_water: Tuple[int, int, int]
    shallow_water: Tuple[int, int, int]
    beach: Tuple[int, int, int]
    lowland: Tuple[int, int, int]
    midland: Tuple[int, int, int]
    highland: Tuple[int, int, int]
    peak: Tuple[int, int, int]
    vegetation: Optional[Tuple[int, int, int]] = None
    snow: Optional[Tuple[int, int, int]] = None

PALETTES = {
    'tropical': ColorPalette(
        deep_water=(0, 50, 100),
        shallow_water=(50, 120, 180),
        beach=(210, 190, 140),
        lowland=(80, 140, 60),      # Jungle green
        midland=(60, 100, 40),      # Dark jungle
        highland=(120, 100, 80),    # Rocky brown
        peak=(140, 120, 100),       # Mountain grey
        vegetation=(100, 180, 70),
    ),
    'volcanic': ColorPalette(
        deep_water=(0, 50, 100),
        shallow_water=(50, 120, 180),
        beach=(80, 70, 60),
        lowland=(100, 80, 60),
        midland=(140, 100, 70),
        highland=(180, 120, 80),
        peak=(220, 80, 40),         # Red volcanic
    ),
    'temperate': ColorPalette(
        deep_water=(20, 60, 120),
        shallow_water=(60, 130, 180),
        beach=(180, 170, 140),
        lowland=(100, 150, 80),
        midland=(80, 120, 60),
        highland=(120, 110, 90),
        peak=(180, 180, 190),
        snow=(240, 240, 250),
    ),
    'arctic': ColorPalette(
        deep_water=(20, 40, 80),
        shallow_water=(80, 120, 160),
        beach=(200, 210, 220),
        lowland=(220, 230, 240),
        midland=(200, 210, 220),
        highland=(180, 190, 200),
        peak=(240, 250, 255),
        snow=(250, 250, 255),
    ),
}

def interpolate_terrain_color(height: float, water_level: float,
                              palette: ColorPalette) -> Tuple[int, int, int]:
    """
    Map height value to terrain color from palette.

    Height ranges:
    - height < water_level: water (deep → shallow)
    - water_level to +0.1: beach
    - 0.1 to 0.4: lowland
    - 0.4 to 0.6: midland
    - 0.6 to 0.8: highland
    - 0.8 to 1.0: peak (with optional snow)
    """
    if height < water_level:
        # Water gradient
        t = max(0, (height - (water_level - 0.2)) / 0.2)
        return interpolate_color(palette.deep_water, palette.shallow_water, t)
    elif height < water_level + 0.1:
        return palette.beach
    elif height < 0.4:
        t = (height - (water_level + 0.1)) / (0.4 - water_level - 0.1)
        return interpolate_color(palette.beach, palette.lowland, t)
    elif height < 0.6:
        t = (height - 0.4) / 0.2
        return interpolate_color(palette.lowland, palette.midland, t)
    elif height < 0.8:
        t = (height - 0.6) / 0.2
        return interpolate_color(palette.midland, palette.highland, t)
    else:
        t = (height - 0.8) / 0.2
        if palette.snow and height > 0.9:
            return interpolate_color(palette.peak, palette.snow, (height - 0.9) / 0.1)
        return interpolate_color(palette.highland, palette.peak, t)
```

---

## 6. High-Level Public API

```python
# world_builder/artwork_pipeline.py

"""
Fully automated procedural artwork generation pipeline for WoW 3.3.5a zones.

Generates ALL visual assets programmatically using Python Pillow:
- World map art (stylized zone overviews)
- Subzone discovery overlays (9 per zone)
- Loading screen art (scenic compositions)
- Dungeon map overlays (floor plans)

Zero manual art tools required. AI agent can generate complete zone artwork.
"""

from typing import List, Dict, Tuple, Optional
import numpy as np
from PIL import Image


def generate_world_map(
    heightmap: np.ndarray,
    subzones: List['SubzoneDefinition'],
    water_level: float = 0.0,
    size: Tuple[int, int] = (1002, 668),
    zone_name: str = "Zone",
    color_palette: Optional['ColorPalette'] = None,
) -> Image.Image:
    """
    Procedurally generate world map art (zone overview illustration).

    Generates:
    - Color-coded terrain from heightmap
    - Subzone color overlays (40% opacity)
    - Relief shading (hillshading)
    - Coastline effects (edges, foam)
    - Subzone name labels

    Args:
        heightmap: 2D terrain heightmap (0.0-1.0 normalized)
        subzones: List of subzone definitions with boundaries
        water_level: Z coordinate for water surface
        size: Output resolution (1002x668 standard)
        zone_name: Zone name for metadata
        color_palette: Custom color palette (auto-detect if None)

    Returns:
        Pillow Image object (RGB/RGBA)
    """
    pass


def generate_subzone_overlays(
    subzones: List['SubzoneDefinition'],
    world_map_bounds: Tuple[float, float, float, float],
    padding: int = 10,
) -> Dict[str, Image.Image]:
    """
    Procedurally generate subzone discovery overlays.

    Generates for each subzone:
    - Colored silhouette (70% opacity)
    - Subtle texture noise
    - Glowing border effect
    - Variable size (tight bounding box + padding)

    Args:
        subzones: List of subzone definitions
        world_map_bounds: (left, right, top, bottom) world coordinates
        padding: Pixels around subzone boundary

    Returns:
        Dictionary mapping subzone names to RGBA images
    """
    pass


def generate_loading_screen(
    zone_name: str,
    theme: str = 'tropical',
    size: Tuple[int, int] = (1024, 768),
    custom_elements: Optional[Dict] = None,
) -> Image.Image:
    """
    Procedurally generate loading screen art (scenic composition).

    Generates theme-based layered composition:
    - Sky layer (gradient or solid)
    - Background silhouettes (islands, mountains, architecture)
    - Midground elements (trees, statues, lava)
    - Foreground elements (water, rocks, floor)
    - Accent effects (sun glow, lightning, fire)
    - Zone name text overlay

    Themes: 'tropical', 'volcanic', 'underground', 'titan'

    Args:
        zone_name: Display text
        theme: Visual theme
        size: (1024, 768) or (2048, 1536) widescreen
        custom_elements: Override composition elements

    Returns:
        Pillow Image object (RGB)
    """
    pass


def generate_dungeon_map(
    layout: 'DungeonLayout',
    boss_positions: List[Tuple[str, Tuple[float, float]]],
    entrance_position: Tuple[float, float],
    size: Tuple[int, int] = (512, 512),
    dungeon_name: str = "Dungeon",
) -> Image.Image:
    """
    Procedurally generate dungeon map overlay (floor plan).

    Generates:
    - Room layout (colored rectangles by type)
    - Connection corridors (grey lines)
    - Boss markers (red circles with 'B')
    - Entrance marker (green arrow)

    Args:
        layout: Dungeon room definitions and connections
        boss_positions: List of (boss_name, (x, y)) tuples
        entrance_position: (x, y) entrance coordinates
        size: Output resolution (512x512 typical)
        dungeon_name: Dungeon name for metadata

    Returns:
        Pillow Image object (RGB)
    """
    pass


def generate_zone_artwork_bundle(
    zone_name: str,
    heightmap: np.ndarray,
    subzones: List['SubzoneDefinition'],
    theme: str = 'tropical',
    output_dir: str = ".",
) -> Dict[str, str]:
    """
    Generate ALL artwork for a zone in one call (FULL AUTOMATION).

    Generates:
    - World map art (1 BLP)
    - Subzone overlays (9 BLPs)
    - Loading screen standard (1 BLP)
    - Loading screen widescreen (1 BLP)

    Total: 12 procedurally generated artwork assets

    Args:
        zone_name: Zone name
        heightmap: Terrain heightmap
        subzones: List of 9 subzone definitions
        theme: Loading screen theme
        output_dir: Base output directory

    Returns:
        Dictionary of generated file paths
    """
    pass
```

---

## 7. Complete Tel'Abim Example (Full Automation)

```python
from world_builder.artwork_pipeline import generate_zone_artwork_bundle
from world_builder.artwork.color_palettes import PALETTES

# Tel'Abim subzone definitions
telabim_subzones = [
    SubzoneDefinition(
        name="Palmbreak Shore",
        boundary=[(x1, y1), (x2, y2), ...],  # World coordinates
        color_theme=(240, 220, 180),  # Sandy beach
    ),
    SubzoneDefinition(
        name="The Banana Grove",
        boundary=[...],
        color_theme=(120, 200, 80),  # Bright jungle green
    ),
    SubzoneDefinition(
        name="The Tangle",
        boundary=[...],
        color_theme=(60, 100, 40),  # Dark jungle
    ),
    SubzoneDefinition(
        name="Mortuga",
        boundary=[...],
        color_theme=(150, 130, 100),  # Town brown/grey
    ),
    SubzoneDefinition(
        name="The Darkling Hollow",
        boundary=[...],
        color_theme=(80, 60, 100),  # Purple/dark
    ),
    SubzoneDefinition(
        name="Tal'Zan Plateau",
        boundary=[...],
        color_theme=(140, 120, 100),  # Grey/brown rock
    ),
    SubzoneDefinition(
        name="The Scorched Ascent",
        boundary=[...],
        color_theme=(200, 100, 60),  # Orange/red volcanic
    ),
    SubzoneDefinition(
        name="The Caldera",
        boundary=[...],
        color_theme=(220, 80, 40),  # Red volcanic
    ),
    SubzoneDefinition(
        name="Storm King's Rest",
        boundary=[...],
        color_theme=(100, 100, 140),  # Blue/grey stone
    ),
]

# FULL AUTOMATION: Generate all artwork procedurally
paths = generate_zone_artwork_bundle(
    zone_name="TelAbim",
    heightmap=telabim_heightmap,  # From terrain generator
    subzones=telabim_subzones,
    theme='tropical',
    output_dir="D:/Test/wow-pywowlib/output",
)

# Generated files (12 total, all procedural):
# - Interface/WorldMap/TelAbim/TelAbim.blp (world map)
# - Interface/WorldMap/TelAbim/PalmbreakShore_overlay.blp
# - Interface/WorldMap/TelAbim/TheBananaGrove_overlay.blp
# - Interface/WorldMap/TelAbim/TheTangle_overlay.blp
# - Interface/WorldMap/TelAbim/Mortuga_overlay.blp
# - Interface/WorldMap/TelAbim/TheDarklingHollow_overlay.blp
# - Interface/WorldMap/TelAbim/TalZanPlateau_overlay.blp
# - Interface/WorldMap/TelAbim/TheScorchedAscent_overlay.blp
# - Interface/WorldMap/TelAbim/TheCaldera_overlay.blp
# - Interface/WorldMap/TelAbim/StormKingsRest_overlay.blp
# - Interface/Glues/LoadingScreens/TelAbim.blp (1024x768)
# - Interface/Glues/LoadingScreens/TelAbim_wide.blp (2048x1536)
```

---

## 8. Complete Vault of Storms Example (Full Automation)

```python
from world_builder.artwork_pipeline import generate_loading_screen, generate_dungeon_map
from world_builder.artwork.dungeon_maps import DungeonLayout, Room, Connection
from world_builder.blp_writer import save_artwork_as_blp

# Vault of Storms dungeon layout
vault_layout = DungeonLayout(
    rooms=[
        Room(id=0, name="Entrance Hall", type='corridor',
             bounds=(400, 600, 400, 600)),
        Room(id=1, name="Storm Chamber", type='chamber',
             bounds=(800, 1200, 800, 1200)),
        Room(id=2, name="Lightning Conduit", type='corridor',
             bounds=(1000, 1100, 1400, 1800)),
        Room(id=3, name="Titan Archive", type='chamber',
             bounds=(1400, 1800, 1600, 2000)),
        Room(id=4, name="Thunderking's Sanctum", type='boss_room',
             bounds=(1400, 2000, 2200, 2800)),
    ],
    connections=[
        Connection(room_a_id=0, room_b_id=1),
        Connection(room_a_id=1, room_b_id=2),
        Connection(room_a_id=2, room_b_id=3),
        Connection(room_a_id=3, room_b_id=4),
    ],
)

# FULL AUTOMATION: Generate loading screen procedurally
loading_img = generate_loading_screen(
    zone_name="The Vault of Storms",
    theme='titan',  # Titan architecture theme
    size=(1024, 768),
)
save_artwork_as_blp(
    loading_img,
    "Interface/Glues/LoadingScreens/VaultOfStorms.blp",
    format='DXT1'
)

# FULL AUTOMATION: Generate dungeon map procedurally
dungeon_map_img = generate_dungeon_map(
    layout=vault_layout,
    boss_positions=[("Thunderking Nalak", (1700, 2500))],
    entrance_position=(500, 500),
    size=(512, 512),
    dungeon_name="VaultOfStorms",
)
save_artwork_as_blp(
    dungeon_map_img,
    "Interface/WorldMap/VaultOfStorms/VaultOfStorms.blp",
    format='DXT1'
)

# Generated files (2 total, all procedural):
# - Interface/Glues/LoadingScreens/VaultOfStorms.blp
#   * Blue-grey gradient sky
#   * Titan pillar/arch silhouettes
#   * Statue silhouettes
#   * Branching arcane lightning
#   * "The Vault of Storms" text
# - Interface/WorldMap/VaultOfStorms/VaultOfStorms.blp
#   * 5 colored rooms (grey/red)
#   * 4 connection lines
#   * Red boss marker "Thunderking Nalak"
#   * Green entrance arrow
```

---

## 9. Implementation Checklist

### Phase 1: Core Infrastructure (Week 1)
- [ ] Create module structure (artwork/ subdirectory)
- [ ] Implement `color_palettes.py` with 4+ predefined palettes
- [ ] Implement `image_effects.py`:
  - [ ] Linear/radial gradients
  - [ ] Relief shading (hillshading algorithm)
  - [ ] Texture noise
  - [ ] Edge detection (morphological)
- [ ] Implement `text_rendering.py`:
  - [ ] Text with outline (8-direction)
  - [ ] Text with shadow
  - [ ] Font loading with fallback
- [ ] Implement `mpq_paths.py` (path generation functions)
- [ ] Write unit tests for utilities
- [ ] Integrate with `blp_writer.py`

### Phase 2: World Map Generator (Week 2)
- [ ] Implement `world_map.py`:
  - [ ] Terrain base layer (heightmap → color)
  - [ ] Subzone color overlay system
  - [ ] Relief shading integration
  - [ ] Coastline detection and effects
  - [ ] Subzone label rendering
  - [ ] WorldMapGenerator class
- [ ] Write unit tests (color distribution, output size)
- [ ] Generate Tel'Abim world map for visual testing

### Phase 3: Subzone Overlays (Week 2)
- [ ] Implement `subzone_overlays.py`:
  - [ ] Boundary extraction and bounding box
  - [ ] Silhouette mask generation (polygon fill)
  - [ ] Color application with texture noise
  - [ ] Border glow effects (morphological)
  - [ ] SubzoneOverlayGenerator class
- [ ] Write unit tests (alpha channel, size)
- [ ] Generate all 9 Tel'Abim overlays

### Phase 4: Loading Screens (Week 3)
- [ ] Implement `loading_screens.py`:
  - [ ] Theme composition system (4 themes)
  - [ ] Sky layer (gradients, solid)
  - [ ] Silhouette generators:
    - [ ] Island silhouette (Bezier curves)
    - [ ] Palm tree silhouettes
    - [ ] Mountain peaks
    - [ ] Titan architecture (pillars, arches)
    - [ ] Cavern walls
  - [ ] Glow effects:
    - [ ] Radial glow (sun, fire)
    - [ ] Lightning arcs (branching)
  - [ ] Zone name text overlay
  - [ ] LoadingScreenGenerator class
- [ ] Write unit tests (theme outputs, size)
- [ ] Generate Tel'Abim (tropical) and Vault (titan) loading screens

### Phase 5: Dungeon Maps (Week 3)
- [ ] Implement `dungeon_maps.py`:
  - [ ] Room layout rendering (colored rectangles)
  - [ ] Connection rendering (lines)
  - [ ] Boss markers (circles, text)
  - [ ] Entrance marker (arrow)
  - [ ] DungeonMapGenerator class
- [ ] Write unit tests (layout accuracy)
- [ ] Generate Vault of Storms dungeon map

### Phase 6: Public API (Week 4)
- [ ] Implement `artwork_pipeline.py`:
  - [ ] `generate_world_map()` high-level function
  - [ ] `generate_subzone_overlays()` high-level function
  - [ ] `generate_loading_screen()` high-level function
  - [ ] `generate_dungeon_map()` high-level function
  - [ ] `generate_zone_artwork_bundle()` batch processor
- [ ] BLP conversion integration
- [ ] MPQ path integration
- [ ] Documentation and examples

### Phase 7: Testing (Week 4)
- [ ] Complete unit test coverage (90%+)
- [ ] Visual inspection tests
- [ ] BLP format validation tests
- [ ] Tel'Abim complete example (12 assets)
- [ ] Vault of Storms complete example (2 assets)
- [ ] Performance profiling

### Phase 8: Documentation (Week 5)
- [ ] API documentation (docstrings)
- [ ] Usage examples in README
- [ ] Algorithm documentation
- [ ] Integration guide
- [ ] Troubleshooting guide

---

## 10. Success Criteria

1. **Full Automation**: Zero manual art tools required. AI agent generates all assets.

2. **Functional Completeness**:
   - All 4 generators implemented (world map, overlays, loading, dungeon)
   - Tel'Abim generates 12 unique artwork assets procedurally
   - Vault of Storms generates 2 unique artwork assets procedurally
   - All outputs are valid BLP format

3. **Visual Quality**:
   - World maps are recognizable stylized zone overviews
   - Subzone overlays align with world map
   - Loading screens have scenic composition layers
   - Dungeon maps are clear floor plans

4. **Integration**:
   - Seamless integration with plan-blp-writer.md
   - Correct MPQ paths for all asset types
   - Compatible with world_builder pipeline

5. **Code Quality**:
   - 90%+ unit test coverage
   - Clear API documentation
   - Type hints throughout
   - Performance < 30s per zone

---

## Dependencies

### Required Python Packages
```
Pillow>=10.0.0          # Image manipulation (procedural generation)
numpy>=1.24.0           # Heightmap processing
scipy>=1.10.0           # Edge detection, morphological operations
```

### Installation
```bash
pip install Pillow numpy scipy
```

---

## Notes

### Design Decisions

1. **Pillow for all generation**: PIL provides drawing primitives, color management, text rendering
2. **Procedural algorithms**: Gradients, silhouettes, hillshading all implemented programmatically
3. **Theme-based loading screens**: Predefined layer recipes for 4 themes (tropical, volcanic, underground, titan)
4. **No manual art**: Every pixel generated by Python code
5. **Fallback fonts**: Use system fonts when WoW fonts unavailable

### Known Limitations

1. **Visual quality**: Procedural art cannot match hand-painted quality (acceptable for automation)
2. **Fixed compositions**: Loading screens use predefined layer structures
3. **No 3D rendering**: All 2D drawing primitives (adequate for top-down maps)
4. **Text rendering basic**: Pillow text rendering simpler than WoW's custom font system

---

**Plan Status**: Ready for Implementation
**Estimated Effort**: 5 weeks (1 developer)
**Risk Level**: Medium (visual quality requirements)
**Automation Level**: 100% (zero manual art tools)
