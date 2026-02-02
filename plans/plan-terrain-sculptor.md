# Plan: Fully Automated Terrain Sculptor for WoW 3.3.5a

## Executive Summary

This plan details a **fully automated terrain sculptor** that generates complete, playable ADT terrain data without any manual intervention in Noggit. The module procedurally generates heightmaps, textures, doodad/WMO placements, water planes, and area IDs, producing game-ready map data.

**Philosophy**: Full automation from high-level zone definition to complete ADT files. The entire terrain generation pipeline is code-driven and reproducible.

**Key Feature**: Zone definition → Procedural generation → Complete ADT/WDT data ready for MPQ packing

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Core Systems](#core-systems)
3. [Module Design](#module-design)
4. [Component Specifications](#component-specifications)
5. [Tel'Abim Example](#telabim-example)
6. [Implementation Checklist](#implementation-checklist)
7. [Dependencies](#dependencies)
8. [Testing Strategy](#testing-strategy)

---

## Architecture Overview

### Fully Automated Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│  INPUT: Zone Definition Dict                                 │
│  ├─ Subzone definitions (10 subzones for Tel'Abim)          │
│  ├─ Terrain primitive compositions (island, volcano, etc.)  │
│  ├─ Texture rules (elevation, slope, subzone-based)         │
│  ├─ Doodad scatter rules (density, filtering)               │
│  └─ WMO placement coordinates                               │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  PROCEDURAL GENERATION ENGINE                                │
│  ├─ Heightmap Generator (noise + primitives)                │
│  ├─ Texture Painter (rule-based layer assignment)           │
│  ├─ Doodad Placement Engine (Poisson disk + filtering)      │
│  ├─ WMO Placement Engine (coordinate-based)                 │
│  ├─ Water Plane Generator (elevation-based)                 │
│  └─ Area ID Stamper (subzone boundaries)                    │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  OUTPUT: Complete ADT Data                                   │
│  ├─ Heightmaps (MCVT chunks)                                │
│  ├─ Texture layers + alpha maps (MCLY + MCAL)               │
│  ├─ Doodad placements (MDDF)                                │
│  ├─ WMO placements (MODF)                                   │
│  ├─ Water planes (MH2O)                                     │
│  ├─ Area IDs (MCNK headers)                                 │
│  └─ Complete WDT file                                       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  INTEGRATION: adt_composer + build_zone()                    │
│  └─ Ready for MPQ packing                                   │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
Zone Definition Dict
    │
    ├─► Heightmap Generator ──► 2D float arrays (per ADT tile)
    │       │
    │       └─► Noise generation (Perlin/Simplex)
    │       └─► Primitive composition (island, volcano, plateau, etc.)
    │       └─► Blending and masking
    │
    ├─► Texture Painter ──► Texture layer definitions + alpha maps
    │       │
    │       └─► Elevation-based rules (sand → grass → rock)
    │       └─► Slope-based rules (steep = rock)
    │       └─► Subzone-based overrides
    │       └─► Noise variation (break up uniform areas)
    │
    ├─► Doodad Placement Engine ──► MDDF placement list
    │       │
    │       └─► Poisson disk sampling (natural distribution)
    │       └─► Slope/elevation filtering
    │       └─► Subzone density rules
    │
    ├─► WMO Placement Engine ──► MODF placement list
    │       │
    │       └─► Explicit coordinate placement
    │       └─► Rotation and scale
    │
    ├─► Water Plane Generator ──► MH2O chunk data
    │       │
    │       └─► Region-based water placement
    │       └─► Elevation assignment
    │
    └─► Area ID Stamper ──► MCNK area ID assignments
            │
            └─► Subzone boundary polygons
            └─► Point-in-polygon tests per chunk
```

---

## Core Systems

### 1. Procedural Heightmap Generation

**Purpose**: Generate complete terrain heightmaps from composable terrain primitives and noise functions.

**Approach**: Noise-based terrain with weighted primitive composition.

**Terrain Primitives**:

```python
# Each primitive returns a 2D heightmap array
def island(size, center, radius, elevation, falloff=0.3):
    """
    Raised landmass with coastal falloff to sea level.

    Parameters:
        size: (width, height) in vertices
        center: (x, y) normalized coordinates (0-1)
        radius: Normalized radius (0-1)
        elevation: Height at center
        falloff: Falloff curve steepness (0-1)

    Returns:
        2D array with smooth circular elevation profile
    """

def plateau(size, bounds, elevation, edge_steepness=5.0):
    """
    Flat elevated area with cliff edges.

    Parameters:
        size: (width, height) in vertices
        bounds: (x_min, y_min, x_max, y_max) normalized (0-1)
        elevation: Plateau height
        edge_steepness: Cliff slope steepness

    Returns:
        2D array with sharp-edged flat plateau
    """

def volcano(size, center, base_radius, peak_height, caldera_radius, caldera_depth):
    """
    Volcanic cone with caldera depression.

    Parameters:
        size: (width, height) in vertices
        center: (x, y) normalized coordinates (0-1)
        base_radius: Base radius (normalized)
        peak_height: Maximum elevation at rim
        caldera_radius: Inner caldera radius (normalized)
        caldera_depth: Depth of caldera depression

    Returns:
        2D array with volcanic cone + central depression
    """

def valley(size, center, radius, depth):
    """
    Sunken area / basin.

    Returns:
        2D array with inverted elevation (negative heights)
    """

def ridge(size, start, end, width, height, falloff=0.2):
    """
    Linear elevated feature (mountain ridge, cliff line).

    Parameters:
        start, end: (x, y) normalized endpoints
        width: Ridge width (normalized)
        height: Ridge elevation
        falloff: Edge falloff steepness

    Returns:
        2D array with linear elevated feature
    """
```

**Composition Algorithm**:

```python
def compose_heightmap(zone_def, tile_x, tile_y):
    """
    Generate heightmap for one ADT tile by composing primitives.

    Algorithm:
        1. Start with base elevation (sea level)
        2. For each subzone definition:
            a. Generate primitive heightmap
            b. Generate subzone mask (boundary blending)
            c. Weighted addition: result += primitive * mask * weight
        3. Add noise detail (break up uniform areas)
        4. Clamp to valid range (0-2000 yards)

    Returns:
        2D array (129x129) with final heightmap
    """
```

**Blending Masks**:

```python
def generate_mask(size, center, radius, shape='circle', falloff=0.2):
    """
    Generate 2D mask for primitive blending.

    Shapes:
        - circle: Radial distance falloff
        - ellipse: Anisotropic radial falloff
        - polygon: Custom boundary with falloff

    Falloff:
        - 0.0: Hard edge (step function)
        - 0.5: Smooth blend (smoothstep)
        - 1.0: Very gradual (cosine interpolation)

    Returns:
        2D array with values 0.0 (outside) to 1.0 (inside)
    """
```

---

### 2. Procedural Texture Painting

**Purpose**: Automatically assign texture layers and generate alpha maps based on terrain properties.

**Rule-Based System**:

```python
class TexturePaintingRules:
    """
    Multi-layer texture assignment based on:
        - Elevation (shore → lowland → mountain)
        - Slope (flat → steep)
        - Subzone identity (desert, jungle, volcanic, etc.)
        - Noise variation (break up uniform areas)
    """

    def __init__(self, zone_def):
        self.zone_def = zone_def
        self.texture_db = load_texture_database()  # WoW texture paths

    def assign_textures(self, heightmap, slope_map, subzone_map):
        """
        Assign texture layers per vertex.

        Algorithm:
            1. For each vertex (x, y):
                a. Get elevation = heightmap[x, y]
                b. Get slope = slope_map[x, y]
                c. Get subzone = subzone_map[x, y]

                d. Apply rule cascade:
                    - Subzone override (highest priority)
                    - Slope rule (rock on steep slopes)
                    - Elevation rule (sand → grass → rock → snow)
                    - Noise variation (break up uniformity)

                e. Output: 4 texture layers + 4 alpha maps (per vertex)

        Returns:
            {
                'texture_paths': [path1, path2, path3, path4],
                'alpha_maps': [array1, array2, array3, array4]  # 64x64 per chunk
            }
        """
```

**Example Rules**:

```python
# Elevation-based texture rules
ELEVATION_RULES = [
    {'range': (-10, 2), 'texture': 'Tileset/Generic/Sand01.blp'},      # Shore
    {'range': (2, 50), 'texture': 'Tileset/Generic/Grass01.blp'},     # Lowland
    {'range': (50, 120), 'texture': 'Tileset/Generic/Rock01.blp'},    # Mountain
    {'range': (120, 300), 'texture': 'Tileset/Generic/Snow01.blp'},   # Peak
]

# Slope-based texture rules
SLOPE_RULES = [
    {'range': (0, 15), 'texture': None},  # Flat, use elevation rule
    {'range': (15, 45), 'texture': 'Tileset/Generic/Rock01.blp'},  # Steep
    {'range': (45, 90), 'texture': 'Tileset/Generic/Cliff01.blp'}, # Cliff
]

# Subzone-based overrides (highest priority)
SUBZONE_OVERRIDES = {
    'Mortuga Harbor': {
        'base': 'Tileset/Generic/Sand01.blp',
        'detail': 'Tileset/Generic/Dirt01.blp',
    },
    'Scorched Ascent': {
        'base': 'Tileset/Generic/Lava01.blp',
        'detail': 'Tileset/Generic/Rock_Volcanic01.blp',
    },
}
```

**Alpha Map Generation**:

```python
def generate_alpha_map(heightmap, rule_func, noise_scale=5.0):
    """
    Generate per-layer alpha map (0-255 coverage).

    Algorithm:
        1. Apply rule function to get base coverage (0.0-1.0)
        2. Add Perlin noise variation (break up uniform areas)
        3. Smooth with Gaussian blur (natural transitions)
        4. Quantize to 0-255 (WoW alpha map format)

    Returns:
        2D array (64x64 per MCNK chunk) with alpha values
    """
```

---

### 3. Doodad/WMO Placement Engine

**Purpose**: Automatically place M2 doodads (trees, rocks, vegetation) and WMOs (structures) across the terrain.

**Doodad Scatter System**:

```python
class DoodadScatterEngine:
    """
    Automated doodad placement using Poisson disk sampling.
    """

    def __init__(self, zone_def, heightmap):
        self.zone_def = zone_def
        self.heightmap = heightmap
        self.doodad_db = load_doodad_database()  # WoW M2 paths

    def scatter_doodads(self, subzone):
        """
        Scatter doodads in subzone using Poisson disk sampling.

        Algorithm:
            1. Define subzone boundary polygon
            2. Poisson disk sampling (natural distribution):
                - Min distance between doodads (prevents clustering)
                - Random jitter for natural look
            3. For each candidate position:
                a. Check elevation (no underwater, not too high)
                b. Check slope (no trees on cliffs)
                c. Check subzone rules (density, allowed models)
                d. Sample heightmap for Z coordinate
                e. Add random rotation (0-360 degrees)
                f. Add random scale variation (0.8-1.2)
            4. Output MDDF entry

        Returns:
            List of MDDF entries:
            [
                {
                    'model': 'World/Expansion01/Doodads/Generic/Palms/PalmTree01.m2',
                    'position': (x, y, z),
                    'rotation': (pitch, yaw, roll),
                    'scale': 1.0,
                    'flags': 0
                },
                ...
            ]
        """
```

**Poisson Disk Sampling**:

```python
def poisson_disk_sampling(boundary, min_distance, max_attempts=30):
    """
    Generate natural-looking point distribution.

    Algorithm (Bridson's algorithm):
        1. Start with random seed point
        2. Maintain active list of candidates
        3. For each active point:
            a. Generate k candidate points (annulus around active point)
            b. Check if candidate is valid:
                - Distance > min_distance from all existing points
                - Inside boundary polygon
            c. If valid, add to active list and output
        4. Repeat until active list empty

    Returns:
        List of (x, y) coordinates
    """
```

**Filtering Rules**:

```python
DOODAD_FILTERS = {
    'elevation': {
        'min': -5.0,   # No placement below sea level
        'max': 200.0,  # No placement above peaks
    },
    'slope': {
        'max': 35.0,   # No trees on cliffs (degrees)
    },
    'water_distance': {
        'min': 2.0,    # Keep doodads away from water edge
    },
}
```

**WMO Placement System**:

```python
class WMOPlacementEngine:
    """
    Explicit WMO placement at defined coordinates.
    """

    def place_wmos(self, subzone):
        """
        Place WMOs (buildings, ruins, structures) at specified coordinates.

        Algorithm:
            1. For each WMO definition in subzone:
                a. Use explicit (x, y) coordinates
                b. Sample heightmap for Z coordinate (ground placement)
                c. Apply rotation (usually snapped to cardinal directions)
                d. Apply scale
                e. Output MODF entry

        Returns:
            List of MODF entries:
            [
                {
                    'model': 'World/wmo/KulTiras/Human/8KT_PiratePort.wmo',
                    'position': (x, y, z),
                    'rotation': (pitch, yaw, roll),
                    'scale': 1.0,
                    'doodad_set': 0,
                    'flags': 0
                },
                ...
            ]
        """
```

---

### 4. Subzone Area ID Assignment

**Purpose**: Stamp area IDs into MCNK chunks based on subzone boundary polygons.

**Algorithm**:

```python
def stamp_area_ids(adt_data, subzone_boundaries):
    """
    Assign area IDs to MCNK chunks based on chunk center position.

    Algorithm:
        1. For each ADT tile:
            a. For each MCNK chunk (16x16 grid = 256 chunks):
                - Calculate chunk center world coordinates
                - Test which subzone polygon contains this point
                - Assign area_id to MCNK header

    Point-in-polygon test:
        - Ray casting algorithm (standard computational geometry)

    Overlap handling:
        - Priority: smallest subzone (most specific)
        - Fallback: parent zone area ID
    """
```

---

### 5. Water Plane Placement

**Purpose**: Automatically place water planes at specified elevations and regions.

**Algorithm**:

```python
def generate_water_planes(zone_def):
    """
    Generate MH2O chunk data for water planes.

    Types:
        - Ocean: Global water plane at sea level (z = 0.0)
        - Rivers: Linear water segments following paths
        - Lakes: Localized water planes in basins
        - Lava: High-temperature liquid at volcanic areas

    Algorithm:
        1. For each water definition in zone:
            a. Define boundary region (polygon or full tile)
            b. Set water type (ocean, river, lake, lava)
            c. Set elevation (Z coordinate)
            d. Set flags (fishable, swimable, etc.)
            e. Generate MH2O chunk data

    Returns:
        MH2O chunk data per ADT tile
    """
```

---

## Module Design

### File Structure

```
world_builder/
├── __init__.py                     (existing)
├── wdt_generator.py                (existing)
├── adt_composer.py                 (existing - EXTEND)
├── dbc_injector.py                 (existing)
├── mpq_packer.py                   (existing)
├── terrain_sculptor.py             (NEW - main facade API)
├── procedural/                     (NEW - procedural generation)
│   ├── __init__.py
│   ├── noise.py                    (Perlin/Simplex noise)
│   ├── primitives.py               (Terrain primitives)
│   ├── compositing.py              (Heightmap blending)
│   ├── texture_painter.py          (Rule-based texture assignment)
│   ├── doodad_scatter.py           (Poisson disk sampling)
│   ├── wmo_placement.py            (WMO coordinate placement)
│   └── water_generator.py          (Water plane generation)
├── assets/                         (NEW - asset databases)
│   ├── __init__.py
│   ├── textures.py                 (WoW texture paths reference)
│   ├── doodads.py                  (Common M2 model paths)
│   └── wmos.py                     (Common WMO paths)
└── utils/                          (NEW - utility functions)
    ├── __init__.py
    ├── coordinates.py              (Coordinate conversion)
    ├── geometry.py                 (Polygon operations, ray casting)
    └── sampling.py                 (Poisson disk, noise sampling)
```

### Estimated Module Size

- `terrain_sculptor.py`: ~300-400 lines (main API)
- `procedural/noise.py`: ~150-200 lines (noise functions)
- `procedural/primitives.py`: ~300-400 lines (5+ primitives)
- `procedural/compositing.py`: ~200-300 lines (blending, masks)
- `procedural/texture_painter.py`: ~400-500 lines (rule system, alpha maps)
- `procedural/doodad_scatter.py`: ~300-400 lines (Poisson sampling, filtering)
- `procedural/wmo_placement.py`: ~150-200 lines (coordinate placement)
- `procedural/water_generator.py`: ~150-200 lines (MH2O generation)
- `assets/`: ~300-400 lines (asset databases)
- `utils/`: ~200-300 lines (geometry, sampling)
- **Total new code**: ~2,500-3,500 lines

### Class Hierarchy

```python
# terrain_sculptor.py (Main API)

class TerrainSculptor:
    """
    Main facade class for automated terrain generation.
    """
    def __init__(self, zone_definition: dict)
    def generate_heightmaps(self) -> dict[tuple, np.ndarray]
    def generate_textures(self, heightmaps) -> dict
    def generate_doodads(self, heightmaps) -> list[dict]
    def generate_wmos(self, heightmaps) -> list[dict]
    def generate_water(self) -> dict
    def generate_area_ids(self) -> dict
    def export_to_adt_composer(self) -> dict

def sculpt_zone(zone_def: dict) -> dict:
    """
    High-level API - single function to generate complete zone.

    Returns:
        Complete ADT data ready for adt_composer integration
    """


# procedural/primitives.py

class TerrainPrimitive:
    """Base class for terrain primitives."""
    def generate(self, size: tuple[int, int]) -> np.ndarray

class Island(TerrainPrimitive):
    """Raised landmass with coastal falloff."""

class Plateau(TerrainPrimitive):
    """Flat elevated area with cliffs."""

class Volcano(TerrainPrimitive):
    """Volcanic cone with caldera."""

class Valley(TerrainPrimitive):
    """Sunken basin."""

class Ridge(TerrainPrimitive):
    """Linear elevated feature."""


# procedural/texture_painter.py

class TexturePainter:
    """Rule-based texture layer assignment."""
    def __init__(self, zone_def: dict, texture_rules: dict)
    def paint_textures(self, heightmap, slope_map, subzone_map) -> dict
    def generate_alpha_maps(self, texture_assignments) -> dict


# procedural/doodad_scatter.py

class DoodadScatterEngine:
    """Poisson disk-based doodad placement."""
    def __init__(self, zone_def: dict, heightmap: np.ndarray)
    def scatter_subzone(self, subzone: dict) -> list[dict]
    def filter_placement(self, position, rules) -> bool


# procedural/wmo_placement.py

class WMOPlacementEngine:
    """Coordinate-based WMO placement."""
    def __init__(self, zone_def: dict, heightmap: np.ndarray)
    def place_wmos(self, subzone: dict) -> list[dict]
```

### Data Structures

```python
# Zone definition input format (COMPLETE)
ZoneDefinition = {
    'name': str,                    # Zone name
    'grid_size': tuple[int, int],   # (width, height) in ADT tiles
    'base_coords': tuple[int, int], # Starting (x, y) tile coordinates
    'sea_level': float,             # Base water elevation
    'seed': int,                    # Random seed for reproducibility

    'subzones': list[SubzoneDefinition],

    'global_water': {               # Optional global water plane
        'elevation': float,
        'type': str,                # 'ocean', 'lava', etc.
    },
}

SubzoneDefinition = {
    'name': str,                    # Subzone name
    'area_id': int,                 # DBC AreaTable ID

    # Boundary definition
    'center': tuple[float, float],  # Normalized (0-1) position
    'radius': float,                # Normalized (0-1) radius
    'shape': str,                   # 'circle', 'ellipse', 'polygon'
    'polygon': list[tuple[float, float]],  # Optional polygon vertices
    'falloff': float,               # Boundary blending (0-1)

    # Terrain definition
    'terrain_type': str,            # 'island', 'volcano', 'plateau', 'valley', 'ridge', 'noise'
    'elevation': tuple[float, float],      # (min, max) height
    'terrain_params': dict,         # Type-specific parameters
    'noise_params': dict,           # Optional noise overlay
    'weight': float,                # Blending weight (default 1.0)

    # Texture definition
    'textures': list[str],          # Texture layer paths (priority order)
    'texture_rules': dict,          # Override global texture rules

    # Doodad definition
    'doodads': dict[str, float],    # {model_name: density}
    'doodad_filters': dict,         # Slope, elevation, etc. filters

    # WMO definition
    'structures': list[{            # Explicit WMO placements
        'model': str,               # WMO path
        'position': tuple[float, float],  # (x, y) normalized coords
        'rotation': tuple[float, float, float],  # (pitch, yaw, roll) degrees
        'scale': float,
        'doodad_set': int,
    }],

    # Water definition
    'water': list[{                 # Local water planes
        'elevation': float,
        'type': str,
        'boundary': list[tuple[float, float]],  # Polygon
    }],
}

# Output data structure (for adt_composer integration)
TerrainData = {
    'heightmaps': dict[tuple[int, int], np.ndarray],  # {(x, y): heightmap_array}

    'textures': {
        'texture_paths': list[str],           # Global texture list
        'layers': dict[tuple[int, int], list[{  # Per-tile layer assignments
            'texture_id': int,                # Index into texture_paths
            'alpha_map': np.ndarray,          # 64x64 per chunk
        }]],
    },

    'doodads': list[{               # MDDF entries
        'model': str,
        'position': tuple[float, float, float],
        'rotation': tuple[float, float, float],
        'scale': float,
        'flags': int,
    }],

    'wmos': list[{                  # MODF entries
        'model': str,
        'position': tuple[float, float, float],
        'rotation': tuple[float, float, float],
        'scale': float,
        'doodad_set': int,
        'flags': int,
    }],

    'water': dict[tuple[int, int], bytes],  # {(x, y): MH2O_chunk_data}

    'area_ids': dict[tuple[int, int, int, int], int],  # {(tile_x, tile_y, chunk_x, chunk_y): area_id}
}
```

---

## Component Specifications

### 1. Heightmap Generation (Detailed)

**Location**: `world_builder/procedural/primitives.py`, `world_builder/procedural/compositing.py`

#### Noise Implementation

```python
# procedural/noise.py

class SimplexNoise:
    """
    Simplex noise implementation (Perlin-like).

    Features:
        - Seeded random generation (reproducible)
        - 2D noise function
        - Octave/fBm support (fractal Brownian motion)
    """

    def __init__(self, seed: int = 0):
        """Initialize with random seed."""
        self.perm = self._generate_permutation(seed)

    def noise2d(self, x: float, y: float) -> float:
        """
        Generate 2D Simplex noise at (x, y).

        Returns: float in range [-1.0, 1.0]
        """

    def octave_noise2d(self, x: float, y: float, octaves: int = 4,
                       persistence: float = 0.5, lacunarity: float = 2.0) -> float:
        """
        Generate fractal Brownian motion (fBm) noise.

        Parameters:
            octaves: Number of noise layers
            persistence: Amplitude decay per octave (0-1)
            lacunarity: Frequency increase per octave (>1)

        Returns: float (range depends on octaves)
        """
```

#### Primitive Implementations

```python
# procedural/primitives.py

def island(size: tuple[int, int], center: tuple[float, float],
           radius: float, elevation: float, falloff: float = 0.3) -> np.ndarray:
    """
    Generate raised landmass with coastal falloff.

    Algorithm:
        1. Create distance field from center (radial)
        2. Normalize distances (0 at center, 1 at radius)
        3. Apply smoothstep falloff curve:
            height(d) = elevation * smoothstep(1 - d / radius)
        4. Return heightmap array

    Returns:
        2D array (size) with smooth radial elevation
    """
    width, height = size
    cx, cy = center

    # Create coordinate grid
    y_coords, x_coords = np.ogrid[0:height, 0:width]
    x_norm = x_coords / width
    y_norm = y_coords / height

    # Distance from center
    dist = np.sqrt((x_norm - cx)**2 + (y_norm - cy)**2)

    # Smoothstep falloff
    t = np.clip((radius - dist) / (radius * falloff), 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)  # smoothstep

    return elevation * t


def plateau(size: tuple[int, int], bounds: tuple[float, float, float, float],
            elevation: float, edge_steepness: float = 5.0) -> np.ndarray:
    """
    Generate flat elevated plateau with steep edges.

    Algorithm:
        1. Define rectangular boundary
        2. Calculate distance to boundary edge
        3. Apply steep sigmoid falloff at edges
        4. Return heightmap with sharp-edged plateau

    Returns:
        2D array with flat top and steep sides
    """
    width, height = size
    x_min, y_min, x_max, y_max = bounds

    y_coords, x_coords = np.ogrid[0:height, 0:width]
    x_norm = x_coords / width
    y_norm = y_coords / height

    # Distance to boundary (minimum distance to any edge)
    dist_x = np.minimum(x_norm - x_min, x_max - x_norm)
    dist_y = np.minimum(y_norm - y_min, y_max - y_norm)
    dist = np.minimum(dist_x, dist_y)

    # Sigmoid falloff (steep edges)
    t = 1.0 / (1.0 + np.exp(-edge_steepness * (dist - 0.05)))

    return elevation * t


def volcano(size: tuple[int, int], center: tuple[float, float],
            base_radius: float, peak_height: float,
            caldera_radius: float, caldera_depth: float) -> np.ndarray:
    """
    Generate volcanic cone with caldera depression.

    Algorithm:
        1. Create radial distance field
        2. Outer cone: Linear slope from base to peak
            height(r) = peak_height * (1 - r / base_radius)
        3. Caldera depression: Negative height inside caldera
            height(r) = -caldera_depth * (1 - r / caldera_radius) [if r < caldera_radius]
        4. Smooth transition between cone and caldera

    Returns:
        2D array with volcanic profile
    """
    width, height = size
    cx, cy = center

    y_coords, x_coords = np.ogrid[0:height, 0:width]
    x_norm = x_coords / width
    y_norm = y_coords / height

    dist = np.sqrt((x_norm - cx)**2 + (y_norm - cy)**2)

    # Outer cone
    cone = np.maximum(0, peak_height * (1 - dist / base_radius))

    # Caldera depression
    caldera_mask = dist < caldera_radius
    caldera = np.where(caldera_mask,
                       -caldera_depth * (1 - dist / caldera_radius),
                       0)

    return cone + caldera


def valley(size: tuple[int, int], center: tuple[float, float],
           radius: float, depth: float, falloff: float = 0.3) -> np.ndarray:
    """
    Generate sunken basin (inverted island).

    Algorithm:
        Same as island(), but negative elevation

    Returns:
        2D array with depression
    """
    return -island(size, center, radius, depth, falloff)


def ridge(size: tuple[int, int], start: tuple[float, float],
          end: tuple[float, float], width: float, height: float,
          falloff: float = 0.2) -> np.ndarray:
    """
    Generate linear elevated feature.

    Algorithm:
        1. Calculate perpendicular distance from each point to line segment
        2. Apply smoothstep falloff based on distance from line
        3. Return heightmap with ridge profile

    Returns:
        2D array with linear elevated feature
    """
    w, h = size
    sx, sy = start
    ex, ey = end

    y_coords, x_coords = np.ogrid[0:h, 0:w]
    x_norm = x_coords / w
    y_norm = y_coords / h

    # Vector from start to end
    dx = ex - sx
    dy = ey - sy
    line_length = np.sqrt(dx**2 + dy**2)

    # Project points onto line, calculate perpendicular distance
    # (Point-to-line distance formula)
    t = ((x_norm - sx) * dx + (y_norm - sy) * dy) / (line_length**2)
    t = np.clip(t, 0, 1)  # Clamp to segment

    proj_x = sx + t * dx
    proj_y = sy + t * dy

    dist = np.sqrt((x_norm - proj_x)**2 + (y_norm - proj_y)**2)

    # Smoothstep falloff
    t = np.clip((width - dist) / (width * falloff), 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)

    return height * t
```

#### Composition System

```python
# procedural/compositing.py

def compose_heightmaps(zone_def: dict, tile_x: int, tile_y: int) -> np.ndarray:
    """
    Generate heightmap for one ADT tile by composing primitives.

    Algorithm:
        1. Initialize base heightmap at sea level
        2. For each subzone:
            a. Generate primitive heightmap
            b. Generate blending mask
            c. Weighted addition: base += primitive * mask * weight
        3. Add global noise detail (small-scale variation)
        4. Clamp to valid range

    Returns:
        2D array (129x129) with final heightmap
    """
    size = (129, 129)  # WoW ADT vertex resolution
    heightmap = np.full(size, zone_def.get('sea_level', 0.0), dtype=np.float32)

    for subzone in zone_def['subzones']:
        # Generate primitive
        terrain_type = subzone['terrain_type']
        if terrain_type == 'island':
            primitive = island(size, subzone['center'], subzone['radius'],
                              subzone['elevation'][1], subzone.get('falloff', 0.3))
        elif terrain_type == 'plateau':
            primitive = plateau(size, subzone['bounds'], subzone['elevation'][1],
                               subzone.get('edge_steepness', 5.0))
        elif terrain_type == 'volcano':
            params = subzone['terrain_params']
            primitive = volcano(size, subzone['center'], subzone['radius'],
                               subzone['elevation'][1], params['caldera_radius'],
                               params['caldera_depth'])
        # ... other types

        # Generate mask
        mask = generate_mask(size, subzone['center'], subzone['radius'],
                            subzone.get('shape', 'circle'),
                            subzone.get('falloff', 0.2))

        # Composite
        weight = subzone.get('weight', 1.0)
        heightmap += primitive * mask * weight

    # Add noise detail
    noise = SimplexNoise(seed=zone_def.get('seed', 0))
    noise_layer = np.zeros(size)
    for y in range(size[0]):
        for x in range(size[1]):
            noise_layer[y, x] = noise.octave_noise2d(x * 0.1, y * 0.1, octaves=3)

    heightmap += noise_layer * 2.0  # Small variation

    # Clamp to valid range (WoW: 0-2000 yards typically)
    heightmap = np.clip(heightmap, -500, 2000)

    return heightmap


def generate_mask(size: tuple[int, int], center: tuple[float, float],
                 radius: float, shape: str = 'circle',
                 falloff: float = 0.2) -> np.ndarray:
    """
    Generate 2D blending mask.

    Shapes:
        - circle: Radial distance
        - polygon: Custom boundary

    Returns:
        2D array with values 0.0 (outside) to 1.0 (inside)
    """
    width, height = size
    cx, cy = center

    y_coords, x_coords = np.ogrid[0:height, 0:width]
    x_norm = x_coords / width
    y_norm = y_coords / height

    if shape == 'circle':
        dist = np.sqrt((x_norm - cx)**2 + (y_norm - cy)**2)
        t = np.clip((radius - dist) / (radius * falloff), 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)  # smoothstep

    # ... polygon support

    return np.ones(size)
```

---

### 2. Texture Painting (Detailed)

**Location**: `world_builder/procedural/texture_painter.py`

```python
class TexturePainter:
    """
    Rule-based texture layer assignment and alpha map generation.
    """

    def __init__(self, zone_def: dict):
        self.zone_def = zone_def
        self.noise = SimplexNoise(seed=zone_def.get('seed', 0))

    def paint_textures(self, heightmap: np.ndarray,
                      tile_x: int, tile_y: int) -> dict:
        """
        Generate texture layers and alpha maps for one ADT tile.

        Algorithm:
            1. Calculate slope map from heightmap
            2. Generate subzone map (which subzone each vertex belongs to)
            3. For each MCNK chunk (16x16 in ADT):
                a. Sample heightmap and slope
                b. Apply rule cascade (subzone → slope → elevation → noise)
                c. Assign up to 4 texture layers
                d. Generate alpha maps (64x64 per chunk)
            4. Return texture data structure

        Returns:
            {
                'texture_paths': [path1, path2, ...],
                'chunks': [
                    {
                        'layers': [tex_id1, tex_id2, tex_id3, tex_id4],
                        'alpha_maps': [array1, array2, array3, array4]
                    },
                    ... (256 chunks)
                ]
            }
        """
        # Calculate slope map
        slope_map = self._calculate_slope(heightmap)

        # Generate subzone map
        subzone_map = self._generate_subzone_map(heightmap.shape, tile_x, tile_y)

        # Process each chunk
        chunks = []
        for chunk_y in range(16):
            for chunk_x in range(16):
                chunk_data = self._paint_chunk(
                    heightmap, slope_map, subzone_map,
                    chunk_x, chunk_y
                )
                chunks.append(chunk_data)

        # Collect unique textures
        texture_paths = self._collect_textures(chunks)

        return {
            'texture_paths': texture_paths,
            'chunks': chunks
        }

    def _calculate_slope(self, heightmap: np.ndarray) -> np.ndarray:
        """
        Calculate slope (in degrees) from heightmap.

        Algorithm:
            1. Compute gradients (dx, dy) using numpy.gradient
            2. Calculate slope angle: arctan(sqrt(dx^2 + dy^2))
            3. Convert to degrees

        Returns:
            2D array with slope values (degrees)
        """
        dy, dx = np.gradient(heightmap)
        slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
        slope_deg = np.degrees(slope_rad)
        return slope_deg

    def _generate_subzone_map(self, size: tuple[int, int],
                             tile_x: int, tile_y: int) -> np.ndarray:
        """
        Generate subzone identity map (which subzone each vertex belongs to).

        Algorithm:
            For each vertex, test which subzone polygon contains it.

        Returns:
            2D array with subzone indices (or -1 if no subzone)
        """
        subzone_map = np.full(size, -1, dtype=np.int32)

        for idx, subzone in enumerate(self.zone_def['subzones']):
            mask = generate_mask(size, subzone['center'], subzone['radius'],
                                subzone.get('shape', 'circle'), falloff=0.0)
            subzone_map[mask > 0.5] = idx

        return subzone_map

    def _paint_chunk(self, heightmap, slope_map, subzone_map,
                    chunk_x: int, chunk_y: int) -> dict:
        """
        Paint one MCNK chunk (9x9 vertices, 8x8 quads).

        Algorithm:
            1. Sample heightmap, slope, subzone for chunk area
            2. Apply texture selection rules (cascade):
                a. Check subzone override (highest priority)
                b. Check slope rule (steep = rock)
                c. Check elevation rule (shore → lowland → mountain)
                d. Add noise variation
            3. Generate up to 4 texture layers
            4. Generate alpha maps (64x64) for each layer

        Returns:
            {
                'layers': [tex_id1, tex_id2, tex_id3, tex_id4],
                'alpha_maps': [array1, array2, array3, array4]
            }
        """
        # Sample chunk data
        vert_x = chunk_x * 8
        vert_y = chunk_y * 8
        chunk_heightmap = heightmap[vert_y:vert_y+9, vert_x:vert_x+9]
        chunk_slope = slope_map[vert_y:vert_y+9, vert_x:vert_x+9]
        chunk_subzone = subzone_map[vert_y:vert_y+9, vert_x:vert_x+9]

        # Rule cascade
        layers = []
        alpha_maps = []

        # Layer 0: Base texture (always full coverage)
        base_texture = self._select_base_texture(
            chunk_heightmap, chunk_slope, chunk_subzone
        )
        layers.append(base_texture)
        alpha_maps.append(np.full((64, 64), 255, dtype=np.uint8))

        # Layer 1: Slope override (rock on steep areas)
        if np.max(chunk_slope) > 15.0:
            rock_texture = 'Tileset/Generic/Rock01.blp'
            layers.append(rock_texture)
            alpha_maps.append(self._generate_slope_alpha(chunk_slope, threshold=15.0))

        # Layer 2: Detail variation (noise-based)
        detail_texture = self._select_detail_texture(chunk_heightmap)
        layers.append(detail_texture)
        alpha_maps.append(self._generate_noise_alpha(chunk_x, chunk_y, scale=0.5))

        # Layer 3: Additional detail
        # ...

        # Pad to 4 layers
        while len(layers) < 4:
            layers.append(None)
            alpha_maps.append(np.zeros((64, 64), dtype=np.uint8))

        return {
            'layers': layers[:4],
            'alpha_maps': alpha_maps[:4]
        }

    def _select_base_texture(self, heightmap, slope, subzone_map) -> str:
        """
        Select base texture using rule cascade.

        Priority:
            1. Subzone override
            2. Elevation rule
        """
        avg_elevation = np.mean(heightmap)
        primary_subzone = np.bincount(subzone_map.flatten() + 1).argmax() - 1

        # Subzone override
        if primary_subzone >= 0:
            subzone = self.zone_def['subzones'][primary_subzone]
            if 'textures' in subzone and len(subzone['textures']) > 0:
                return subzone['textures'][0]

        # Elevation rule
        if avg_elevation < 2:
            return 'Tileset/Generic/Sand01.blp'
        elif avg_elevation < 50:
            return 'Tileset/Generic/Grass01.blp'
        elif avg_elevation < 120:
            return 'Tileset/Generic/Rock01.blp'
        else:
            return 'Tileset/Generic/Snow01.blp'

    def _generate_slope_alpha(self, slope_map: np.ndarray,
                             threshold: float = 15.0) -> np.ndarray:
        """
        Generate alpha map based on slope.

        Algorithm:
            1. Upsample slope to 64x64 (from 9x9)
            2. Normalize: alpha = (slope - threshold) / 10.0
            3. Clamp to 0-255

        Returns:
            64x64 alpha map
        """
        from scipy.ndimage import zoom

        # Upsample to 64x64
        alpha_map = zoom(slope_map, 64 / slope_map.shape[0], order=1)

        # Normalize
        alpha_map = (alpha_map - threshold) / 10.0
        alpha_map = np.clip(alpha_map * 255, 0, 255).astype(np.uint8)

        return alpha_map

    def _generate_noise_alpha(self, chunk_x: int, chunk_y: int,
                             scale: float = 0.5) -> np.ndarray:
        """
        Generate alpha map using Perlin noise.

        Algorithm:
            1. Sample noise at 64x64 resolution
            2. Normalize to 0-255

        Returns:
            64x64 alpha map
        """
        alpha_map = np.zeros((64, 64), dtype=np.uint8)

        for y in range(64):
            for x in range(64):
                nx = (chunk_x * 64 + x) * scale
                ny = (chunk_y * 64 + y) * scale
                noise_val = self.noise.octave_noise2d(nx, ny, octaves=2)
                alpha = int((noise_val + 1.0) * 127.5)  # Normalize to 0-255
                alpha_map[y, x] = np.clip(alpha, 0, 255)

        return alpha_map
```

---

### 3. Doodad Placement (Detailed)

**Location**: `world_builder/procedural/doodad_scatter.py`

```python
# utils/sampling.py

def poisson_disk_sampling(boundary_polygon: list[tuple[float, float]],
                         min_distance: float,
                         max_attempts: int = 30) -> list[tuple[float, float]]:
    """
    Bridson's Poisson disk sampling algorithm.

    Generates evenly-spaced points with natural variation.

    Algorithm:
        1. Start with random seed point inside boundary
        2. Maintain active list (candidates for spawning neighbors)
        3. For each active point:
            a. Generate k candidates in annulus (min_distance to 2*min_distance)
            b. Check if candidate is valid:
                - Distance > min_distance from all existing points
                - Inside boundary polygon
            c. If valid, add to output and active list
            d. If no valid candidates after k attempts, remove from active
        4. Repeat until active list empty

    Returns:
        List of (x, y) coordinates
    """
    import random
    from scipy.spatial import cKDTree

    # ... implementation

    return points


# procedural/doodad_scatter.py

class DoodadScatterEngine:
    """
    Automated doodad placement using Poisson disk sampling.
    """

    def __init__(self, zone_def: dict, heightmaps: dict[tuple, np.ndarray]):
        self.zone_def = zone_def
        self.heightmaps = heightmaps  # {(tile_x, tile_y): heightmap}
        self.doodad_db = self._load_doodad_database()

    def scatter_all(self) -> list[dict]:
        """
        Scatter doodads across entire zone.

        Returns:
            List of MDDF entries
        """
        mddf_entries = []

        for subzone in self.zone_def['subzones']:
            if 'doodads' in subzone:
                entries = self.scatter_subzone(subzone)
                mddf_entries.extend(entries)

        return mddf_entries

    def scatter_subzone(self, subzone: dict) -> list[dict]:
        """
        Scatter doodads in one subzone.

        Algorithm:
            1. Define subzone boundary polygon (world coordinates)
            2. For each doodad type in subzone['doodads']:
                a. Calculate min_distance from density
                b. Poisson disk sampling → candidate positions
                c. For each candidate:
                    - Sample heightmap for Z coordinate
                    - Apply filters (elevation, slope, water distance)
                    - If valid, create MDDF entry
            3. Return all MDDF entries

        Returns:
            List of MDDF entries
        """
        mddf_entries = []

        # Convert subzone boundary to world coordinates
        boundary = self._get_world_boundary(subzone)

        # For each doodad type
        for model_name, density in subzone.get('doodads', {}).items():
            # Calculate min_distance from density (doodads per square yard)
            area = self._calculate_polygon_area(boundary)
            target_count = int(area * density)
            min_distance = np.sqrt(area / (target_count * np.pi))

            # Poisson disk sampling
            positions = poisson_disk_sampling(boundary, min_distance)

            # Filter and create MDDF entries
            for x, y in positions:
                if self._is_valid_placement(x, y, subzone):
                    z = self._sample_heightmap(x, y)
                    rotation = self._random_rotation()
                    scale = self._random_scale(0.8, 1.2)

                    mddf_entries.append({
                        'model': self.doodad_db[model_name],
                        'position': (x, y, z),
                        'rotation': rotation,
                        'scale': scale,
                        'flags': 0
                    })

        return mddf_entries

    def _is_valid_placement(self, x: float, y: float, subzone: dict) -> bool:
        """
        Apply placement filters.

        Filters:
            - Elevation range (no underwater, not too high)
            - Slope threshold (no trees on cliffs)
            - Water distance (keep away from water edge)

        Returns:
            True if valid placement
        """
        z = self._sample_heightmap(x, y)
        slope = self._sample_slope(x, y)

        filters = subzone.get('doodad_filters', {})

        # Elevation filter
        if 'elevation' in filters:
            elev_min = filters['elevation'].get('min', -1000)
            elev_max = filters['elevation'].get('max', 2000)
            if not (elev_min <= z <= elev_max):
                return False

        # Slope filter
        if 'slope' in filters:
            slope_max = filters['slope'].get('max', 35.0)
            if slope > slope_max:
                return False

        # Water distance filter
        if 'water_distance' in filters:
            water_dist = self._distance_to_water(x, y)
            min_dist = filters['water_distance'].get('min', 2.0)
            if water_dist < min_dist:
                return False

        return True

    def _sample_heightmap(self, x: float, y: float) -> float:
        """
        Sample heightmap at world coordinates.

        Algorithm:
            1. Convert world coords to tile + local coords
            2. Bilinear interpolation in heightmap array

        Returns:
            Z elevation
        """
        # Convert world to tile coordinates
        tile_x, tile_y, local_x, local_y = self._world_to_tile_coords(x, y)

        # Get heightmap
        heightmap = self.heightmaps.get((tile_x, tile_y))
        if heightmap is None:
            return 0.0

        # Bilinear interpolation
        # ...

        return z

    def _random_rotation(self) -> tuple[float, float, float]:
        """
        Generate random rotation (mostly around Z axis).

        Returns:
            (pitch, yaw, roll) in degrees
        """
        import random
        return (0.0, random.uniform(0, 360), 0.0)

    def _random_scale(self, min_scale: float, max_scale: float) -> float:
        """Generate random scale variation."""
        import random
        return random.uniform(min_scale, max_scale)
```

---

### 4. High-Level API

```python
# terrain_sculptor.py

def sculpt_zone(zone_def: dict) -> dict:
    """
    High-level API - generate complete zone terrain data.

    Args:
        zone_def: Zone definition dict (see ZoneDefinition structure)

    Returns:
        TerrainData dict ready for adt_composer integration

    Example:
        from world_builder.terrain_sculptor import sculpt_zone
        from world_builder.build_zone import build_zone

        terrain_data = sculpt_zone(TELABIM_ZONE)
        build_zone(TELABIM_ZONE, terrain_data)
    """
    sculptor = TerrainSculptor(zone_def)

    # Generate all terrain components
    heightmaps = sculptor.generate_heightmaps()
    textures = sculptor.generate_textures(heightmaps)
    doodads = sculptor.generate_doodads(heightmaps)
    wmos = sculptor.generate_wmos(heightmaps)
    water = sculptor.generate_water()
    area_ids = sculptor.generate_area_ids()

    return {
        'heightmaps': heightmaps,
        'textures': textures,
        'doodads': doodads,
        'wmos': wmos,
        'water': water,
        'area_ids': area_ids,
    }


class TerrainSculptor:
    """
    Main facade class for automated terrain generation.
    """

    def __init__(self, zone_definition: dict):
        self.zone_def = zone_definition
        self.grid_size = zone_definition['grid_size']
        self.base_coords = zone_definition['base_coords']

    def generate_heightmaps(self) -> dict[tuple[int, int], np.ndarray]:
        """
        Generate heightmaps for all ADT tiles in zone.

        Returns:
            {(tile_x, tile_y): heightmap_array (129x129)}
        """
        heightmaps = {}

        for ty in range(self.grid_size[1]):
            for tx in range(self.grid_size[0]):
                tile_x = self.base_coords[0] + tx
                tile_y = self.base_coords[1] + ty

                heightmap = compose_heightmaps(self.zone_def, tile_x, tile_y)
                heightmaps[(tile_x, tile_y)] = heightmap

        return heightmaps

    def generate_textures(self, heightmaps: dict) -> dict:
        """
        Generate texture layers and alpha maps.

        Returns:
            {
                'texture_paths': list[str],
                'layers': {(tile_x, tile_y): chunk_data_list}
            }
        """
        painter = TexturePainter(self.zone_def)

        layers = {}
        all_textures = set()

        for (tile_x, tile_y), heightmap in heightmaps.items():
            tile_data = painter.paint_textures(heightmap, tile_x, tile_y)
            layers[(tile_x, tile_y)] = tile_data['chunks']
            all_textures.update(tile_data['texture_paths'])

        return {
            'texture_paths': list(all_textures),
            'layers': layers
        }

    def generate_doodads(self, heightmaps: dict) -> list[dict]:
        """
        Generate doodad placements (MDDF).
        """
        scatter_engine = DoodadScatterEngine(self.zone_def, heightmaps)
        return scatter_engine.scatter_all()

    def generate_wmos(self, heightmaps: dict) -> list[dict]:
        """
        Generate WMO placements (MODF).
        """
        wmo_engine = WMOPlacementEngine(self.zone_def, heightmaps)
        return wmo_engine.place_all()

    def generate_water(self) -> dict:
        """
        Generate water plane data (MH2O).
        """
        water_generator = WaterGenerator(self.zone_def)
        return water_generator.generate_all()

    def generate_area_ids(self) -> dict:
        """
        Generate area ID assignments per MCNK chunk.
        """
        area_ids = {}

        for ty in range(self.grid_size[1]):
            for tx in range(self.grid_size[0]):
                tile_x = self.base_coords[0] + tx
                tile_y = self.base_coords[1] + ty

                for chunk_y in range(16):
                    for chunk_x in range(16):
                        area_id = self._get_chunk_area_id(
                            tile_x, tile_y, chunk_x, chunk_y
                        )
                        area_ids[(tile_x, tile_y, chunk_x, chunk_y)] = area_id

        return area_ids

    def _get_chunk_area_id(self, tile_x: int, tile_y: int,
                          chunk_x: int, chunk_y: int) -> int:
        """
        Determine which subzone a chunk belongs to.

        Algorithm:
            1. Calculate chunk center world coordinates
            2. Test against all subzone polygons
            3. Return area_id of smallest containing subzone (most specific)
        """
        # Calculate chunk center
        center_x, center_y = self._chunk_center_coords(
            tile_x, tile_y, chunk_x, chunk_y
        )

        # Find containing subzone
        smallest_subzone = None
        smallest_area = float('inf')

        for subzone in self.zone_def['subzones']:
            if self._point_in_subzone(center_x, center_y, subzone):
                area = self._calculate_subzone_area(subzone)
                if area < smallest_area:
                    smallest_area = area
                    smallest_subzone = subzone

        if smallest_subzone:
            return smallest_subzone['area_id']
        else:
            return 0  # Default area ID
```

---

## Tel'Abim Example

### Complete Zone Definition (All 10 Subzones)

```python
# examples/telabim_zone_definition.py

TELABIM_ZONE = {
    'name': 'TelAbim',
    'grid_size': (4, 4),           # 4x4 ADT tiles
    'base_coords': (30, 30),       # Starting at tile (30, 30)
    'sea_level': 0.0,              # Ocean at 0 yards elevation
    'seed': 42,                    # Reproducible generation

    'global_water': {
        'elevation': 0.0,
        'type': 'ocean',
    },

    'subzones': [
        # 1. Mortuga (Pirate town on northwest coast)
        {
            'name': 'Mortuga',
            'area_id': 9002,
            'center': (0.25, 0.75),
            'radius': 0.12,
            'shape': 'circle',
            'falloff': 0.15,

            'terrain_type': 'island',
            'elevation': (0, 8),
            'weight': 1.0,

            'textures': [
                'Tileset/Generic/Sand01.blp',
                'Tileset/Generic/Dirt_DustyGrey.blp',
            ],

            'doodads': {
                'palm_tree': 0.02,      # 0.02 per sq yard = sparse
                'barrel': 0.005,
                'crate': 0.003,
            },
            'doodad_filters': {
                'elevation': {'min': 1, 'max': 10},
                'slope': {'max': 20},
            },

            'structures': [
                {
                    'model': 'World/wmo/KulTiras/Human/8KT_PiratePort.wmo',
                    'position': (0.25, 0.75),  # Normalized coords
                    'rotation': (0, 0, 0),
                    'scale': 1.0,
                    'doodad_set': 0,
                },
                {
                    'model': 'World/wmo/KulTiras/Human/8KT_Tavern01.wmo',
                    'position': (0.26, 0.76),
                    'rotation': (0, 45, 0),
                    'scale': 1.0,
                    'doodad_set': 0,
                },
            ],
        },

        # 2. Palmbreak Shore (East coast beach)
        {
            'name': 'Palmbreak Shore',
            'area_id': 9003,
            'center': (0.7, 0.5),
            'radius': 0.15,
            'shape': 'circle',
            'falloff': 0.2,

            'terrain_type': 'island',
            'elevation': (0, 15),
            'weight': 1.0,

            'textures': [
                'Tileset/Generic/Sand01.blp',
                'Tileset/Generic/Grass_DarkJungle01.blp',
            ],

            'doodads': {
                'palm_tree': 0.05,      # Dense palm groves
                'palm_tree_bent': 0.02,
                'jungle_bush': 0.04,
                'shipwreck_debris': 0.001,  # Rare
            },
            'doodad_filters': {
                'elevation': {'min': -2, 'max': 20},
                'slope': {'max': 25},
                'water_distance': {'min': 1.0},
            },

            'water': [
                {
                    'elevation': 0.0,
                    'type': 'ocean',
                    'boundary': 'inherit',  # Use subzone boundary
                },
            ],
        },

        # 3. Banana Grove (Flat jungle clearing)
        {
            'name': 'Banana Grove',
            'area_id': 9004,
            'center': (0.35, 0.6),
            'radius': 0.1,
            'shape': 'circle',
            'falloff': 0.1,

            'terrain_type': 'noise',
            'elevation': (10, 25),
            'weight': 1.0,
            'noise_params': {
                'scale': 30.0,
                'octaves': 3,
                'persistence': 0.4,
                'lacunarity': 2.0,
            },

            'textures': [
                'Tileset/Generic/Grass_DarkJungle01.blp',
                'Tileset/Generic/Dirt_Jungle.blp',
            ],

            'doodads': {
                'banana_tree': 0.08,    # Very dense
                'jungle_vine': 0.06,
                'jungle_fern': 0.1,
                'gorilla_skull': 0.0001,  # Flavor detail
            },
            'doodad_filters': {
                'elevation': {'min': 8, 'max': 30},
                'slope': {'max': 15},
            },
        },

        # 4. The Tangle (Dense jungle, uneven ground)
        {
            'name': 'The Tangle',
            'area_id': 9005,
            'center': (0.45, 0.5),
            'radius': 0.2,
            'shape': 'circle',
            'falloff': 0.25,

            'terrain_type': 'noise',
            'elevation': (15, 60),
            'weight': 1.2,
            'noise_params': {
                'scale': 50.0,
                'octaves': 5,
                'persistence': 0.5,
                'lacunarity': 2.5,
            },

            'textures': [
                'Tileset/Generic/Grass_DarkJungle01.blp',
                'Tileset/Generic/Rock_JungleMossy.blp',
                'Tileset/Generic/Dirt_Jungle.blp',
            ],

            'doodads': {
                'jungle_tree_large': 0.06,
                'jungle_tree_small': 0.08,
                'jungle_vine_hanging': 0.1,
                'jungle_fern': 0.15,
                'jungle_mushroom': 0.05,
                'rock_jungle': 0.03,
            },
            'doodad_filters': {
                'elevation': {'min': 10, 'max': 80},
                'slope': {'max': 40},
            },
        },

        # 5. Darkling Hollow (Sunken basin, dark/corrupted)
        {
            'name': 'Darkling Hollow',
            'area_id': 9006,
            'center': (0.5, 0.3),
            'radius': 0.08,
            'shape': 'circle',
            'falloff': 0.2,

            'terrain_type': 'valley',
            'elevation': (-10, 5),
            'weight': 1.0,

            'textures': [
                'Tileset/Generic/Dirt_Muddy.blp',
                'Tileset/Generic/Grass_Dead.blp',
                'Tileset/Generic/Rock_DarkMossy.blp',
            ],

            'doodads': {
                'dead_tree': 0.04,
                'dead_bush': 0.06,
                'mushroom_corrupt': 0.08,
                'bone_pile': 0.002,
            },
            'doodad_filters': {
                'elevation': {'min': -15, 'max': 10},
                'slope': {'max': 30},
            },

            'water': [
                {
                    'elevation': -5.0,
                    'type': 'swamp',
                    'boundary': 'inherit',
                },
            ],
        },

        # 6. Blacktide Cove (Coastal caves, tidal pools)
        {
            'name': 'Blacktide Cove',
            'area_id': 9007,
            'center': (0.15, 0.5),
            'radius': 0.1,
            'shape': 'circle',
            'falloff': 0.15,

            'terrain_type': 'ridge',
            'elevation': (0, 30),
            'weight': 1.0,
            'terrain_params': {
                'start': (0.12, 0.45),
                'end': (0.18, 0.55),
                'width': 0.05,
            },

            'textures': [
                'Tileset/Generic/Rock_Coastal.blp',
                'Tileset/Generic/Sand_Wet.blp',
            ],

            'doodads': {
                'rock_coastal': 0.05,
                'seaweed': 0.08,
                'shell': 0.01,
            },
            'doodad_filters': {
                'elevation': {'min': -5, 'max': 35},
                'slope': {'max': 45},
            },

            'structures': [
                {
                    'model': 'World/wmo/Generic/Cave_Coastal01.wmo',
                    'position': (0.15, 0.5),
                    'rotation': (0, 90, 0),
                    'scale': 1.0,
                    'doodad_set': 0,
                },
            ],
        },

        # 7. Tal'Zan Plateau (Elevated Zandalari ruins)
        {
            'name': "Tal'Zan Plateau",
            'area_id': 9008,
            'center': (0.2, 0.65),
            'radius': 0.15,
            'shape': 'circle',
            'falloff': 0.05,  # Sharp cliffs

            'terrain_type': 'plateau',
            'elevation': (80, 120),
            'weight': 1.0,
            'terrain_params': {
                'bounds': (0.15, 0.58, 0.25, 0.72),
                'edge_steepness': 8.0,
            },

            'textures': [
                'Tileset/Generic/Rock_Zandalari.blp',
                'Tileset/Generic/Stone_Tiled01.blp',
            ],

            'doodads': {
                'rock_pillar': 0.01,
                'grass_sparse': 0.03,
            },
            'doodad_filters': {
                'elevation': {'min': 75, 'max': 125},
                'slope': {'max': 10},  # Flat plateau only
            },

            'structures': [
                {
                    'model': 'World/wmo/Zandalar/Ruins/ZD_Temple01.wmo',
                    'position': (0.2, 0.65),
                    'rotation': (0, 0, 0),
                    'scale': 1.0,
                    'doodad_set': 0,
                },
                {
                    'model': 'World/wmo/Zandalar/Ruins/ZD_Pillar01.wmo',
                    'position': (0.19, 0.64),
                    'rotation': (0, 45, 0),
                    'scale': 1.0,
                    'doodad_set': 0,
                },
            ],
        },

        # 8. Bilgewater Dig (Excavated mine, goblin machinery)
        {
            'name': 'Bilgewater Dig',
            'area_id': 9009,
            'center': (0.55, 0.7),
            'radius': 0.08,
            'shape': 'circle',
            'falloff': 0.1,

            'terrain_type': 'valley',
            'elevation': (5, 20),
            'weight': 0.8,

            'textures': [
                'Tileset/Generic/Rock_Brown.blp',
                'Tileset/Generic/Dirt_Brown.blp',
            ],

            'doodads': {
                'goblin_crate': 0.01,
                'goblin_barrel_explosive': 0.005,
                'mining_cart': 0.002,
                'rock_rubble': 0.05,
            },
            'doodad_filters': {
                'elevation': {'min': 0, 'max': 25},
                'slope': {'max': 35},
            },

            'structures': [
                {
                    'model': 'World/wmo/Goblin/MiningShaft01.wmo',
                    'position': (0.55, 0.7),
                    'rotation': (0, 180, 0),
                    'scale': 1.0,
                    'doodad_set': 0,
                },
                {
                    'model': 'World/wmo/Goblin/Drill01.wmo',
                    'position': (0.56, 0.71),
                    'rotation': (0, 270, 0),
                    'scale': 1.0,
                    'doodad_set': 0,
                },
            ],
        },

        # 9. Scorched Ascent (Volcanic slope, barren, lava flows)
        {
            'name': 'Scorched Ascent',
            'area_id': 9010,
            'center': (0.5, 0.15),
            'radius': 0.15,
            'shape': 'circle',
            'falloff': 0.2,

            'terrain_type': 'volcano',
            'elevation': (50, 180),
            'weight': 1.2,
            'terrain_params': {
                'base_radius': 0.15,
                'peak_height': 180,
                'caldera_radius': 0.05,
                'caldera_depth': 40,
            },

            'textures': [
                'Tileset/Generic/Rock_Volcanic.blp',
                'Tileset/Generic/Lava_Cracks.blp',
            ],

            'doodads': {
                'rock_volcanic': 0.04,
                'lava_geyser': 0.001,  # Rare
                'ash_pile': 0.02,
            },
            'doodad_filters': {
                'elevation': {'min': 40, 'max': 190},
                'slope': {'max': 50},
            },

            'water': [
                {
                    'elevation': 150.0,
                    'type': 'lava',
                    'boundary': 'caldera',  # Inside caldera only
                },
            ],
        },

        # 10. Mount Abari Caldera (Volcanic crater summit, Titan Gate)
        {
            'name': 'Mount Abari Caldera',
            'area_id': 9011,
            'center': (0.5, 0.1),
            'radius': 0.06,
            'shape': 'circle',
            'falloff': 0.1,

            'terrain_type': 'plateau',
            'elevation': (140, 150),
            'weight': 1.0,
            'terrain_params': {
                'bounds': (0.47, 0.08, 0.53, 0.12),
                'edge_steepness': 10.0,
            },

            'textures': [
                'Tileset/Generic/Rock_Volcanic_Dark.blp',
                'Tileset/Generic/Stone_Titan.blp',
            ],

            'doodads': {
                'rock_volcanic': 0.02,
                'titan_rune_stone': 0.0005,  # Very rare
            },
            'doodad_filters': {
                'elevation': {'min': 135, 'max': 155},
                'slope': {'max': 15},
            },

            'structures': [
                {
                    'model': 'World/wmo/Ulduar/UL_TitanGate01.wmo',
                    'position': (0.5, 0.1),
                    'rotation': (0, 0, 0),
                    'scale': 0.8,
                    'doodad_set': 0,
                },
            ],

            'water': [
                {
                    'elevation': 148.0,
                    'type': 'lava',
                    'boundary': [(0.49, 0.09), (0.51, 0.09), (0.51, 0.11), (0.49, 0.11)],
                },
            ],
        },
    ],
}
```

### Usage Example

```python
# examples/build_telabim_automated.py

from world_builder.terrain_sculptor import sculpt_zone
from world_builder.adt_composer import ADTComposer
from world_builder.wdt_generator import generate_wdt
from world_builder.mpq_packer import pack_zone_to_mpq
from examples.telabim_zone_definition import TELABIM_ZONE

def build_telabim():
    """
    Build complete Tel'Abim zone using fully automated pipeline.
    """
    print("=== Tel'Abim Automated Zone Generation ===\n")

    # Step 1: Generate terrain data
    print("[1/5] Generating terrain data...")
    terrain_data = sculpt_zone(TELABIM_ZONE)
    print(f"  - Generated {len(terrain_data['heightmaps'])} heightmaps")
    print(f"  - Generated {len(terrain_data['textures']['texture_paths'])} unique textures")
    print(f"  - Placed {len(terrain_data['doodads'])} doodads")
    print(f"  - Placed {len(terrain_data['wmos'])} WMOs")

    # Step 2: Compose ADT files
    print("\n[2/5] Composing ADT files...")
    composer = ADTComposer(TELABIM_ZONE, terrain_data)
    adt_files = composer.compose_all()
    print(f"  - Generated {len(adt_files)} ADT files")

    # Step 3: Generate WDT
    print("\n[3/5] Generating WDT...")
    wdt_data = generate_wdt(TELABIM_ZONE)
    print("  - WDT generated")

    # Step 4: Pack to MPQ
    print("\n[4/5] Packing to MPQ...")
    mpq_path = pack_zone_to_mpq(
        zone_name='TelAbim',
        adt_files=adt_files,
        wdt_data=wdt_data,
        output_path='./output/patch-TelAbim.mpq'
    )
    print(f"  - MPQ packed: {mpq_path}")

    # Step 5: Summary
    print("\n[5/5] Complete!")
    print(f"\nTel'Abim zone is ready to play!")
    print(f"  - Install: Copy {mpq_path} to your WoW/Data folder")
    print(f"  - Teleport: .go xyz {TELABIM_ZONE['base_coords'][0] * 533.33} {TELABIM_ZONE['base_coords'][1] * 533.33} 0")

if __name__ == '__main__':
    build_telabim()
```

---

## Implementation Checklist

### Phase 1: Core Infrastructure

- [ ] **1.1** Create `world_builder/procedural/` package structure
  - [ ] `__init__.py`
  - [ ] `noise.py` (Simplex noise implementation)
  - [ ] `primitives.py` (terrain primitives)
  - [ ] `compositing.py` (heightmap blending)
  - [ ] `texture_painter.py` (rule-based texture system)
  - [ ] `doodad_scatter.py` (Poisson disk sampling)
  - [ ] `wmo_placement.py` (coordinate-based placement)
  - [ ] `water_generator.py` (MH2O generation)

- [ ] **1.2** Create `world_builder/assets/` package
  - [ ] `__init__.py`
  - [ ] `textures.py` (WoW texture paths)
  - [ ] `doodads.py` (M2 model paths)
  - [ ] `wmos.py` (WMO paths)

- [ ] **1.3** Create `world_builder/utils/` package
  - [ ] `__init__.py`
  - [ ] `coordinates.py` (coordinate conversion)
  - [ ] `geometry.py` (point-in-polygon, area calculation)
  - [ ] `sampling.py` (Poisson disk algorithm)

### Phase 2: Noise and Primitives

- [ ] **2.1** Implement `SimplexNoise` class (`noise.py`)
  - [ ] `__init__()` with seed support
  - [ ] `noise2d()` method
  - [ ] `octave_noise2d()` (fBm)

- [ ] **2.2** Implement terrain primitives (`primitives.py`)
  - [ ] `island()` - raised landmass
  - [ ] `plateau()` - flat elevated area
  - [ ] `volcano()` - cone with caldera
  - [ ] `valley()` - sunken basin
  - [ ] `ridge()` - linear feature

- [ ] **2.3** Implement compositing (`compositing.py`)
  - [ ] `compose_heightmaps()` - main composition function
  - [ ] `generate_mask()` - blending masks
  - [ ] `add_noise_detail()` - small-scale variation

### Phase 3: Texture Painting

- [ ] **3.1** Implement `TexturePainter` class (`texture_painter.py`)
  - [ ] `__init__()` with zone definition
  - [ ] `paint_textures()` - main entry point
  - [ ] `_calculate_slope()` - slope map generation
  - [ ] `_generate_subzone_map()` - subzone identity
  - [ ] `_paint_chunk()` - per-chunk texture assignment
  - [ ] `_select_base_texture()` - rule cascade
  - [ ] `_generate_slope_alpha()` - slope-based alpha
  - [ ] `_generate_noise_alpha()` - noise-based alpha

### Phase 4: Doodad and WMO Placement

- [ ] **4.1** Implement Poisson disk sampling (`utils/sampling.py`)
  - [ ] `poisson_disk_sampling()` - Bridson's algorithm

- [ ] **4.2** Implement `DoodadScatterEngine` (`doodad_scatter.py`)
  - [ ] `__init__()` with zone definition and heightmaps
  - [ ] `scatter_all()` - scatter across entire zone
  - [ ] `scatter_subzone()` - scatter in one subzone
  - [ ] `_is_valid_placement()` - filter by slope/elevation/water
  - [ ] `_sample_heightmap()` - bilinear interpolation
  - [ ] `_random_rotation()`, `_random_scale()`

- [ ] **4.3** Implement `WMOPlacementEngine` (`wmo_placement.py`)
  - [ ] `__init__()` with zone definition and heightmaps
  - [ ] `place_all()` - place all WMOs
  - [ ] `place_wmos()` - place WMOs in subzone
  - [ ] `_sample_heightmap()` - ground placement

### Phase 5: Water and Area IDs

- [ ] **5.1** Implement `WaterGenerator` (`water_generator.py`)
  - [ ] `__init__()` with zone definition
  - [ ] `generate_all()` - generate all water planes
  - [ ] `_generate_mh2o_chunk()` - MH2O binary data

- [ ] **5.2** Implement area ID stamping (`terrain_sculptor.py`)
  - [ ] `generate_area_ids()` method
  - [ ] `_get_chunk_area_id()` - point-in-polygon test
  - [ ] `_point_in_subzone()` - polygon test

### Phase 6: Main API

- [ ] **6.1** Implement `TerrainSculptor` class (`terrain_sculptor.py`)
  - [ ] `__init__()` with zone definition
  - [ ] `generate_heightmaps()` - orchestrate heightmap generation
  - [ ] `generate_textures()` - orchestrate texture painting
  - [ ] `generate_doodads()` - orchestrate doodad scatter
  - [ ] `generate_wmos()` - orchestrate WMO placement
  - [ ] `generate_water()` - orchestrate water generation
  - [ ] `generate_area_ids()` - orchestrate area ID stamping

- [ ] **6.2** Implement high-level API
  - [ ] `sculpt_zone()` function

### Phase 7: Integration with adt_composer

- [ ] **7.1** Extend `adt_composer.py` to accept terrain_data
  - [ ] Accept heightmaps dict
  - [ ] Accept texture layers + alpha maps
  - [ ] Accept MDDF entries
  - [ ] Accept MODF entries
  - [ ] Accept MH2O data
  - [ ] Accept area IDs

- [ ] **7.2** Implement `ADTComposer` class
  - [ ] `__init__()` with zone definition and terrain data
  - [ ] `compose_all()` - generate all ADT files
  - [ ] `_compose_adt()` - generate one ADT file
  - [ ] `_write_mcvt()` - heightmap chunk
  - [ ] `_write_mcly()` - texture layers
  - [ ] `_write_mcal()` - alpha maps
  - [ ] `_write_mddf()` - doodad placements
  - [ ] `_write_modf()` - WMO placements
  - [ ] `_write_mh2o()` - water planes
  - [ ] `_write_mcnk_area_id()` - area ID stamping

### Phase 8: Asset Databases

- [ ] **8.1** Create texture database (`assets/textures.py`)
  - [ ] Standard WoW texture paths (sand, grass, rock, snow, etc.)
  - [ ] Lookup by terrain type

- [ ] **8.2** Create doodad database (`assets/doodads.py`)
  - [ ] Common M2 model paths (trees, rocks, plants)
  - [ ] Lookup by name

- [ ] **8.3** Create WMO database (`assets/wmos.py`)
  - [ ] Common WMO paths (buildings, ruins, caves)
  - [ ] Lookup by name

### Phase 9: Tel'Abim Example

- [ ] **9.1** Create Tel'Abim zone definition
  - [ ] `examples/telabim_zone_definition.py`
  - [ ] All 10 subzones defined
  - [ ] Terrain primitives configured
  - [ ] Texture rules configured
  - [ ] Doodad/WMO placements configured

- [ ] **9.2** Create build script
  - [ ] `examples/build_telabim_automated.py`
  - [ ] Full pipeline from zone definition to MPQ

### Phase 10: Testing

- [ ] **10.1** Unit tests
  - [ ] Noise generation
  - [ ] Primitive generation
  - [ ] Compositing
  - [ ] Poisson disk sampling
  - [ ] Point-in-polygon tests

- [ ] **10.2** Integration tests
  - [ ] Full pipeline test (small zone)
  - [ ] ADT format validation
  - [ ] WDT format validation

- [ ] **10.3** Visual validation
  - [ ] Export heightmaps as PNG for inspection
  - [ ] Export texture maps for inspection
  - [ ] In-game testing (if possible)

### Phase 11: Documentation

- [ ] **11.1** API documentation
  - [ ] Docstrings for all public classes and methods
  - [ ] Zone definition format reference
  - [ ] Examples for each primitive type

- [ ] **11.2** User guide
  - [ ] Quick start guide
  - [ ] Zone definition guide
  - [ ] Troubleshooting guide

---

## Dependencies

### Python Standard Library

- `struct` (binary packing) - already used
- `math` (trigonometry) - already used
- `io.BytesIO` (buffer manipulation) - already used
- `os` (file operations) - already used
- `json` (coordinate export)
- `random` (seeded random generation)

### Third-Party Libraries

**Required**:

- `numpy` - Array operations, heightmap manipulation
  - Install: `pip install numpy`

- `Pillow` - PNG export (for debugging/inspection)
  - Install: `pip install Pillow`

- `scipy` - Interpolation, image processing (zoom, Gaussian blur)
  - Install: `pip install scipy`

**Optional**:

- `opensimplex` - Fast Simplex noise implementation
  - Install: `pip install opensimplex`
  - Fallback: Pure Python SimplexNoise in `procedural/noise.py`

### Installation

```bash
# Required
pip install numpy Pillow scipy

# Optional (recommended for faster noise generation)
pip install opensimplex
```

---

## Testing Strategy

### Unit Tests

**Test Coverage**:

1. **Noise generation** (`test_noise.py`)
   - Verify seeded reproducibility
   - Verify output range [-1, 1]
   - Verify octave noise scaling

2. **Primitives** (`test_primitives.py`)
   - Verify island shape (radial falloff)
   - Verify plateau shape (flat top, steep edges)
   - Verify volcano shape (cone + caldera)
   - Verify valley shape (inverted island)
   - Verify ridge shape (linear feature)

3. **Compositing** (`test_compositing.py`)
   - Verify mask generation (circle, polygon)
   - Verify weighted addition
   - Verify clamping to valid range

4. **Texture painting** (`test_texture_painter.py`)
   - Verify rule cascade (subzone → slope → elevation)
   - Verify alpha map generation
   - Verify chunk coverage (256 chunks per ADT)

5. **Doodad scatter** (`test_doodad_scatter.py`)
   - Verify Poisson disk sampling (min distance)
   - Verify placement filtering (slope, elevation)
   - Verify MDDF format

6. **Geometry utils** (`test_geometry.py`)
   - Verify point-in-polygon (ray casting)
   - Verify polygon area calculation
   - Verify coordinate conversions

### Integration Tests

1. **Full pipeline** (`test_full_pipeline.py`)
   - Small test zone (1x1 ADT)
   - Verify all data structures generated
   - Verify ADT format validity

2. **ADT format validation** (`test_adt_format.py`)
   - Verify MCNK chunk structure
   - Verify MCVT heightmap format
   - Verify MCLY/MCAL texture format
   - Verify MDDF/MODF placement format

### Visual Validation

1. **Heightmap export** - Export heightmaps as 16-bit PNG
   - Visual inspection of terrain shape
   - Verify smooth blending between subzones

2. **Texture map export** - Export alpha maps as grayscale PNG
   - Verify texture transitions
   - Verify noise variation

3. **In-game testing** (if available)
   - Build test zone MPQ
   - Load in WoW 3.3.5a client
   - Verify terrain, textures, doodads, WMOs in-game

---

## Conclusion

This plan provides a **fully automated terrain sculptor** that generates complete, playable ADT terrain from high-level zone definitions. The system uses procedural generation techniques (noise, primitives, rule-based systems, Poisson sampling) to create natural-looking terrain, textures, and object placements without any manual intervention.

**Key Features**:

1. **Procedural heightmap generation** - Composable terrain primitives (island, volcano, plateau, etc.)
2. **Rule-based texture painting** - Multi-layer assignment with alpha maps
3. **Automated doodad placement** - Poisson disk sampling with filtering
4. **Explicit WMO placement** - Coordinate-based structure placement
5. **Water plane generation** - MH2O chunk data
6. **Area ID stamping** - Subzone boundary polygons

**Integration**:

- Output data structure designed for seamless integration with existing `adt_composer.py`
- Extends `build_zone()` workflow
- Complete pipeline from zone definition to MPQ file

**Estimated Implementation Time**:

- **Phase 1-3 (Infrastructure + Heightmaps + Textures)**: 4-5 days
- **Phase 4-5 (Doodads + Water + Area IDs)**: 3-4 days
- **Phase 6-7 (API + Integration)**: 2-3 days
- **Phase 8-9 (Assets + Tel'Abim Example)**: 2-3 days
- **Phase 10-11 (Testing + Documentation)**: 2-3 days

**Total**: ~13-18 days for full implementation including complete Tel'Abim example with all 10 subzones.

**Example Usage**:

```python
from world_builder.terrain_sculptor import sculpt_zone
from examples.telabim_zone_definition import TELABIM_ZONE

# Generate complete terrain data
terrain_data = sculpt_zone(TELABIM_ZONE)

# Returns complete ADT data ready for adt_composer
# No Noggit required - fully automated!
```
