# Plan: Automated Dungeon Builder - Full WMO Generation

## Overview

This plan implements a **fully automated dungeon builder** that generates complete, playable WMO (World Map Object) dungeon interiors for WoW 3.3.5a instances. The module creates actual geometry, materials, lighting, portals, collision, and spawn coordinates—producing ready-to-use dungeon files.

**Core Philosophy:** Full automation from high-level room definitions to complete WMO files. The agent generates geometry primitives (box rooms, circular rooms, corridors, ramps), assembles them into complete WMO structures with proper portal culling, collision meshes, lighting, and doodad placement, then exports all files ready for MPQ packing.

**Target Build:** WotLK 3.3.5a (build 12340)

**Enables TODO:** 1.2 - Build the Vault of Storms Instance Map (COMPLETE automation)

**Module Location:** `world_builder/dungeon_builder.py`

**Module Size:** ~800-1200 lines (geometry generation, WMO assembly, material system, portal culling, BSP trees, lighting, doodads)

**Dependencies:**
- `pywowlib` - WMO file format (MOHD, MOGP, MOPY, MOVI, MOVT, MONR, MOTV, MOBA, MOLR, MODR, MOBN, MOBR, MOCV, MLIQ, MOPT, MOPR, MOLT, MODS, MODN, MODD, MOSB, MOTX, MOMT, MOGN, MOGI, MOPV chunks)
- `world_builder/dbc_injector.py` - Map.dbc registration
- `struct`, `math` - Binary packing, geometry math

---

## 1. Module Architecture

### 1.1 Core Components

```
world_builder/dungeon_builder.py
│
├── Room Primitives (geometry generators)
│   ├── BoxRoom(width, length, height)
│   ├── CircularRoom(radius, height, segments)
│   ├── Corridor(width, length, height)
│   ├── SpiralRamp(radius, height, turns, segments)
│   └── ChamberRoom(radius, height, sides)
│
├── Geometry Generators
│   ├── generate_vertices() → list of (x,y,z) tuples
│   ├── generate_normals() → inward-facing normals
│   ├── generate_uvs() → texture coordinates
│   ├── generate_triangles() → triangle indices
│   └── generate_collision_mesh() → simplified collision geometry
│
├── Material System
│   ├── MaterialPreset (titan_metal, stone_dark, stone_light, volcanic_rock, energy_glow, floor_tile)
│   ├── MaterialMapping → BLP texture paths
│   └── FaceMaterialAssignment → per-face material assignment
│
├── Portal System
│   ├── PortalGenerator
│   ├── generate_doorway_portal(room1, room2)
│   ├── calculate_portal_vertices()
│   └── generate_portal_references()
│
├── Connection System
│   ├── ConnectionResolver
│   ├── connect_rooms(room1, room2) → auto-generate corridor
│   ├── calculate_doorway_positions()
│   └── align_room_orientations()
│
├── Lighting System
│   ├── LightDefinition (point lights, ambient)
│   ├── generate_room_lights(room_type, size)
│   └── auto_place_lights(room_bounds)
│
├── Doodad System
│   ├── DoodadPlacement
│   ├── place_doodads(room, doodad_list)
│   └── generate_doodad_set()
│
├── BSP Tree Generator
│   ├── build_bsp_tree(polygons)
│   ├── split_polygon_set()
│   └── generate_bsp_nodes()
│
├── WMO Assembler
│   ├── assemble_wmo_root()
│   ├── assemble_wmo_group(room)
│   ├── write_mohd_chunk()
│   ├── write_motx_chunk()
│   ├── write_momt_chunk()
│   ├── write_mogn_chunk()
│   ├── write_mogi_chunk()
│   ├── write_mosb_chunk()
│   ├── write_mopv_chunk()
│   ├── write_mopt_chunk()
│   ├── write_mopr_chunk()
│   ├── write_molt_chunk()
│   ├── write_mods_chunk()
│   ├── write_modn_chunk()
│   ├── write_modd_chunk()
│   ├── write_mogp_chunk()
│   ├── write_mopy_chunk()
│   ├── write_movi_chunk()
│   ├── write_movt_chunk()
│   ├── write_monr_chunk()
│   ├── write_motv_chunk()
│   ├── write_moba_chunk()
│   ├── write_molr_chunk()
│   ├── write_modr_chunk()
│   ├── write_mobn_chunk()
│   ├── write_mobr_chunk()
│   └── write_mocv_chunk()
│
├── Coordinate Exporter
│   ├── export_spawn_coordinates()
│   ├── export_boss_positions()
│   ├── export_trash_positions()
│   └── export_door_positions()
│
└── High-Level API
    ├── build_dungeon(definition, output_dir, dbc_dir)
    ├── register_map()
    └── pack_to_mpq()
```

### 1.2 Workflow

```
Dungeon Definition (Python dict/JSON)
    ↓
validate_definition() → Check room structure, materials, connections
    ↓
generate_room_geometries() → Create vertices, normals, UVs, triangles for each room
    ↓
resolve_connections() → Auto-generate corridors, align doorways, create portals
    ↓
assign_materials() → Apply material presets to room faces
    ↓
place_lights() → Generate lighting definitions per room
    ↓
place_doodads() → Position doodads within rooms
    ↓
generate_collision() → Build BSP trees for collision detection
    ↓
generate_portal_system() → Create MOPT/MOPR chunks for occlusion culling
    ↓
assemble_wmo_files() → Build root WMO + group WMOs (one per room)
    ↓
export_spawn_coordinates() → Boss/trash/door positions in world space
    ↓
register_map() → Map.dbc entry
    ↓
pack_to_mpq() → Bundle all files into patch MPQ
    ↓
Output: Complete playable dungeon (WMO files, coordinates, Map.dbc)
```

---

## 2. Room Primitives - Geometry Generators

### 2.1 BoxRoom - Rectangular Room

```python
import math
import struct
from typing import List, Tuple

class BoxRoom:
    """
    Generate rectangular room geometry.

    Produces: floor, 4 walls, ceiling
    All normals face INWARD (toward room center)
    """

    def __init__(self, width: float, length: float, height: float):
        """
        Args:
            width: Room width (X axis) in yards
            length: Room length (Y axis) in yards
            height: Room height (Z axis) in yards
        """
        self.width = width
        self.length = length
        self.height = height

    def generate_vertices(self) -> List[Tuple[float, float, float]]:
        """
        Generate vertices for box room.

        Returns:
            List of (x, y, z) vertex positions

        Vertex order:
            Floor: 0-3 (bottom corners, CCW from -x,-y)
            Ceiling: 4-7 (top corners, CCW from -x,-y)
        """
        w = self.width / 2
        l = self.length / 2
        h = self.height

        vertices = [
            # Floor vertices (z=0)
            (-w, -l, 0.0),  # 0: bottom-left-front
            ( w, -l, 0.0),  # 1: bottom-right-front
            ( w,  l, 0.0),  # 2: bottom-right-back
            (-w,  l, 0.0),  # 3: bottom-left-back

            # Ceiling vertices (z=height)
            (-w, -l, h),    # 4: top-left-front
            ( w, -l, h),    # 5: top-right-front
            ( w,  l, h),    # 6: top-right-back
            (-w,  l, h),    # 7: top-left-back
        ]

        return vertices

    def generate_triangles(self) -> List[Tuple[int, int, int]]:
        """
        Generate triangle indices.

        Returns:
            List of (v0, v1, v2) triangle indices

        Triangle winding: CCW when viewed from INSIDE room (inward-facing normals)
        """
        triangles = [
            # Floor (facing up into room)
            (0, 2, 1), (0, 3, 2),

            # Ceiling (facing down into room)
            (4, 5, 6), (4, 6, 7),

            # Wall -X (left wall, facing +X into room)
            (0, 4, 7), (0, 7, 3),

            # Wall +X (right wall, facing -X into room)
            (1, 2, 6), (1, 6, 5),

            # Wall -Y (front wall, facing +Y into room)
            (0, 1, 5), (0, 5, 4),

            # Wall +Y (back wall, facing -Y into room)
            (3, 7, 6), (3, 6, 2),
        ]

        return triangles

    def generate_normals(self) -> List[Tuple[float, float, float]]:
        """
        Generate per-vertex normals (inward-facing).

        Returns:
            List of (nx, ny, nz) normal vectors
        """
        # Each vertex normal points inward toward room center
        normals = [
            # Floor vertices (normals point up)
            (0.0, 0.0, 1.0),   # 0
            (0.0, 0.0, 1.0),   # 1
            (0.0, 0.0, 1.0),   # 2
            (0.0, 0.0, 1.0),   # 3

            # Ceiling vertices (normals point down)
            (0.0, 0.0, -1.0),  # 4
            (0.0, 0.0, -1.0),  # 5
            (0.0, 0.0, -1.0),  # 6
            (0.0, 0.0, -1.0),  # 7
        ]

        return normals

    def generate_uvs(self) -> List[Tuple[float, float]]:
        """
        Generate texture coordinates.

        Returns:
            List of (u, v) texture coordinates

        UV mapping: 1 unit = 1 yard (adjust scale in material system)
        """
        w = self.width
        l = self.length

        uvs = [
            # Floor vertices
            (0.0, 0.0),      # 0
            (w, 0.0),        # 1
            (w, l),          # 2
            (0.0, l),        # 3

            # Ceiling vertices
            (0.0, 0.0),      # 4
            (w, 0.0),        # 5
            (w, l),          # 6
            (0.0, l),        # 7
        ]

        return uvs

    def generate_face_materials(self) -> List[str]:
        """
        Generate material assignments per triangle.

        Returns:
            List of material IDs (one per triangle)
        """
        # Default: floor/ceiling/walls can have different materials
        materials = [
            'floor', 'floor',        # Floor triangles
            'ceiling', 'ceiling',    # Ceiling triangles
            'wall', 'wall',          # Wall -X
            'wall', 'wall',          # Wall +X
            'wall', 'wall',          # Wall -Y
            'wall', 'wall',          # Wall +Y
        ]

        return materials

    def generate_collision_mesh(self) -> Tuple[List, List]:
        """
        Generate simplified collision mesh.

        Returns:
            (vertices, triangles) for collision BSP tree
        """
        # For box room, collision mesh is same as visual mesh
        return (self.generate_vertices(), self.generate_triangles())
```

### 2.2 CircularRoom - Cylindrical Room

```python
class CircularRoom:
    """
    Generate circular room geometry (cylinder).

    Produces: floor disc, cylindrical wall, ceiling disc
    All normals face INWARD
    """

    def __init__(self, radius: float, height: float, segments: int = 24):
        """
        Args:
            radius: Room radius in yards
            height: Room height in yards
            segments: Number of segments around circle (default 24)
        """
        self.radius = radius
        self.height = height
        self.segments = segments

    def generate_vertices(self) -> List[Tuple[float, float, float]]:
        """
        Generate vertices for circular room.

        Returns:
            List of (x, y, z) vertex positions

        Vertex layout:
            - Center floor vertex (0)
            - Floor perimeter vertices (1 to segments)
            - Center ceiling vertex (segments+1)
            - Ceiling perimeter vertices (segments+2 to 2*segments+1)
        """
        vertices = []

        # Floor center
        vertices.append((0.0, 0.0, 0.0))

        # Floor perimeter
        for i in range(self.segments):
            angle = (2 * math.pi * i) / self.segments
            x = self.radius * math.cos(angle)
            y = self.radius * math.sin(angle)
            vertices.append((x, y, 0.0))

        # Ceiling center
        vertices.append((0.0, 0.0, self.height))

        # Ceiling perimeter
        for i in range(self.segments):
            angle = (2 * math.pi * i) / self.segments
            x = self.radius * math.cos(angle)
            y = self.radius * math.sin(angle)
            vertices.append((x, y, self.height))

        return vertices

    def generate_triangles(self) -> List[Tuple[int, int, int]]:
        """
        Generate triangle indices (inward-facing).
        """
        triangles = []

        # Floor triangles (fan from center, winding CCW when viewed from above)
        for i in range(self.segments):
            v0 = 0  # Floor center
            v1 = 1 + i
            v2 = 1 + ((i + 1) % self.segments)
            triangles.append((v0, v2, v1))  # Reversed for inward normal

        # Ceiling triangles (fan from center, winding CCW when viewed from below)
        ceiling_center = self.segments + 1
        for i in range(self.segments):
            v0 = ceiling_center
            v1 = ceiling_center + 1 + i
            v2 = ceiling_center + 1 + ((i + 1) % self.segments)
            triangles.append((v0, v1, v2))  # Standard winding for inward normal

        # Wall triangles (quad strips)
        for i in range(self.segments):
            floor_v1 = 1 + i
            floor_v2 = 1 + ((i + 1) % self.segments)
            ceiling_v1 = ceiling_center + 1 + i
            ceiling_v2 = ceiling_center + 1 + ((i + 1) % self.segments)

            # Two triangles per wall segment (inward-facing)
            triangles.append((floor_v1, ceiling_v1, floor_v2))
            triangles.append((floor_v2, ceiling_v1, ceiling_v2))

        return triangles

    def generate_normals(self) -> List[Tuple[float, float, float]]:
        """
        Generate per-vertex normals (inward-facing).
        """
        normals = []

        # Floor center normal (up)
        normals.append((0.0, 0.0, 1.0))

        # Floor perimeter normals (up)
        for i in range(self.segments):
            normals.append((0.0, 0.0, 1.0))

        # Ceiling center normal (down)
        normals.append((0.0, 0.0, -1.0))

        # Ceiling perimeter normals (down)
        for i in range(self.segments):
            normals.append((0.0, 0.0, -1.0))

        return normals

    def generate_uvs(self) -> List[Tuple[float, float]]:
        """
        Generate texture coordinates.
        """
        uvs = []

        # Floor center
        uvs.append((self.radius, self.radius))

        # Floor perimeter
        for i in range(self.segments):
            angle = (2 * math.pi * i) / self.segments
            u = self.radius + self.radius * math.cos(angle)
            v = self.radius + self.radius * math.sin(angle)
            uvs.append((u, v))

        # Ceiling center
        uvs.append((self.radius, self.radius))

        # Ceiling perimeter
        for i in range(self.segments):
            angle = (2 * math.pi * i) / self.segments
            u = self.radius + self.radius * math.cos(angle)
            v = self.radius + self.radius * math.sin(angle)
            uvs.append((u, v))

        return uvs

    def generate_face_materials(self) -> List[str]:
        """
        Generate material assignments per triangle.
        """
        materials = []

        # Floor triangles
        for i in range(self.segments):
            materials.append('floor')

        # Ceiling triangles
        for i in range(self.segments):
            materials.append('ceiling')

        # Wall triangles
        for i in range(self.segments * 2):
            materials.append('wall')

        return materials

    def generate_collision_mesh(self) -> Tuple[List, List]:
        """
        Generate simplified collision mesh (fewer segments).
        """
        # Use 8 segments for collision (vs 24 for visual)
        collision_room = CircularRoom(self.radius, self.height, segments=8)
        return (collision_room.generate_vertices(), collision_room.generate_triangles())
```

### 2.3 Corridor - Narrow Connecting Passage

```python
class Corridor(BoxRoom):
    """
    Corridor is just a specialized BoxRoom (narrow and long).
    """

    def __init__(self, width: float, length: float, height: float):
        """
        Args:
            width: Corridor width (narrow dimension)
            length: Corridor length (long dimension)
            height: Corridor height
        """
        super().__init__(width, length, height)
```

### 2.4 SpiralRamp - Spiraling Descent

```python
class SpiralRamp:
    """
    Generate spiral ramp geometry (helical descent/ascent).
    """

    def __init__(self, radius: float, height: float, turns: float, segments: int = 48):
        """
        Args:
            radius: Spiral radius in yards
            height: Total height change in yards (negative for descent)
            turns: Number of complete rotations (e.g., 3.0 for 3 full circles)
            segments: Number of segments per turn
        """
        self.radius = radius
        self.height = height
        self.turns = turns
        self.segments = segments
        self.width = 3.0  # Ramp width (fixed)

    def generate_vertices(self) -> List[Tuple[float, float, float]]:
        """
        Generate vertices for spiral ramp.

        Returns:
            List of (x, y, z) vertex positions
        """
        vertices = []
        total_segments = int(self.segments * self.turns)

        for i in range(total_segments + 1):
            t = i / total_segments  # Parameter [0, 1]
            angle = 2 * math.pi * self.turns * t
            z = self.height * t

            # Inner edge
            x_inner = (self.radius - self.width/2) * math.cos(angle)
            y_inner = (self.radius - self.width/2) * math.sin(angle)
            vertices.append((x_inner, y_inner, z))

            # Outer edge
            x_outer = (self.radius + self.width/2) * math.cos(angle)
            y_outer = (self.radius + self.width/2) * math.sin(angle)
            vertices.append((x_outer, y_outer, z))

        return vertices

    def generate_triangles(self) -> List[Tuple[int, int, int]]:
        """
        Generate triangle indices for ramp surface.
        """
        triangles = []
        total_segments = int(self.segments * self.turns)

        for i in range(total_segments):
            v0 = i * 2        # Inner vertex at segment i
            v1 = i * 2 + 1    # Outer vertex at segment i
            v2 = (i + 1) * 2      # Inner vertex at segment i+1
            v3 = (i + 1) * 2 + 1  # Outer vertex at segment i+1

            # Two triangles per segment (top surface facing up)
            triangles.append((v0, v2, v1))
            triangles.append((v1, v2, v3))

        return triangles

    def generate_normals(self) -> List[Tuple[float, float, float]]:
        """
        Generate per-vertex normals (facing up).
        """
        # For spiral ramp, normals approximately face up (with slight tilt)
        normals = []
        total_segments = int(self.segments * self.turns)

        for i in range(total_segments + 1):
            # Simple approximation: normals face up
            normals.append((0.0, 0.0, 1.0))
            normals.append((0.0, 0.0, 1.0))

        return normals

    def generate_uvs(self) -> List[Tuple[float, float]]:
        """
        Generate texture coordinates.
        """
        uvs = []
        total_segments = int(self.segments * self.turns)

        for i in range(total_segments + 1):
            t = i / total_segments
            # U: along ramp width, V: along ramp length
            uvs.append((0.0, t * self.radius * 2 * math.pi * self.turns))
            uvs.append((self.width, t * self.radius * 2 * math.pi * self.turns))

        return uvs

    def generate_face_materials(self) -> List[str]:
        """
        Generate material assignments per triangle.
        """
        total_segments = int(self.segments * self.turns)
        return ['floor'] * (total_segments * 2)

    def generate_collision_mesh(self) -> Tuple[List, List]:
        """
        Generate simplified collision mesh.
        """
        # Use fewer segments for collision
        collision_ramp = SpiralRamp(self.radius, self.height, self.turns, segments=12)
        return (collision_ramp.generate_vertices(), collision_ramp.generate_triangles())
```

### 2.5 ChamberRoom - Polygonal Room

```python
class ChamberRoom:
    """
    Generate polygonal room (hexagon, octagon, etc).
    """

    def __init__(self, radius: float, height: float, sides: int):
        """
        Args:
            radius: Distance from center to vertex
            height: Room height
            sides: Number of sides (6=hex, 8=oct)
        """
        self.radius = radius
        self.height = height
        self.sides = sides

    def generate_vertices(self) -> List[Tuple[float, float, float]]:
        """
        Generate vertices for polygonal room.
        """
        vertices = []

        # Floor center
        vertices.append((0.0, 0.0, 0.0))

        # Floor perimeter
        for i in range(self.sides):
            angle = (2 * math.pi * i) / self.sides
            x = self.radius * math.cos(angle)
            y = self.radius * math.sin(angle)
            vertices.append((x, y, 0.0))

        # Ceiling center
        vertices.append((0.0, 0.0, self.height))

        # Ceiling perimeter
        for i in range(self.sides):
            angle = (2 * math.pi * i) / self.sides
            x = self.radius * math.cos(angle)
            y = self.radius * math.sin(angle)
            vertices.append((x, y, self.height))

        return vertices

    def generate_triangles(self) -> List[Tuple[int, int, int]]:
        """
        Generate triangle indices.
        """
        triangles = []

        # Floor triangles
        for i in range(self.sides):
            v0 = 0
            v1 = 1 + i
            v2 = 1 + ((i + 1) % self.sides)
            triangles.append((v0, v2, v1))

        # Ceiling triangles
        ceiling_center = self.sides + 1
        for i in range(self.sides):
            v0 = ceiling_center
            v1 = ceiling_center + 1 + i
            v2 = ceiling_center + 1 + ((i + 1) % self.sides)
            triangles.append((v0, v1, v2))

        # Wall triangles
        for i in range(self.sides):
            floor_v1 = 1 + i
            floor_v2 = 1 + ((i + 1) % self.sides)
            ceiling_v1 = ceiling_center + 1 + i
            ceiling_v2 = ceiling_center + 1 + ((i + 1) % self.sides)

            triangles.append((floor_v1, ceiling_v1, floor_v2))
            triangles.append((floor_v2, ceiling_v1, ceiling_v2))

        return triangles

    def generate_normals(self) -> List[Tuple[float, float, float]]:
        """
        Generate per-vertex normals.
        """
        normals = []

        # Floor normals (up)
        normals.append((0.0, 0.0, 1.0))
        for i in range(self.sides):
            normals.append((0.0, 0.0, 1.0))

        # Ceiling normals (down)
        normals.append((0.0, 0.0, -1.0))
        for i in range(self.sides):
            normals.append((0.0, 0.0, -1.0))

        return normals

    def generate_uvs(self) -> List[Tuple[float, float]]:
        """
        Generate texture coordinates.
        """
        uvs = []

        # Floor center
        uvs.append((self.radius, self.radius))

        # Floor perimeter
        for i in range(self.sides):
            angle = (2 * math.pi * i) / self.sides
            u = self.radius + self.radius * math.cos(angle)
            v = self.radius + self.radius * math.sin(angle)
            uvs.append((u, v))

        # Ceiling center
        uvs.append((self.radius, self.radius))

        # Ceiling perimeter
        for i in range(self.sides):
            angle = (2 * math.pi * i) / self.sides
            u = self.radius + self.radius * math.cos(angle)
            v = self.radius + self.radius * math.sin(angle)
            uvs.append((u, v))

        return uvs

    def generate_face_materials(self) -> List[str]:
        """
        Generate material assignments per triangle.
        """
        materials = []

        # Floor triangles
        for i in range(self.sides):
            materials.append('floor')

        # Ceiling triangles
        for i in range(self.sides):
            materials.append('ceiling')

        # Wall triangles
        for i in range(self.sides * 2):
            materials.append('wall')

        return materials

    def generate_collision_mesh(self) -> Tuple[List, List]:
        """
        Generate collision mesh (same as visual for polygons).
        """
        return (self.generate_vertices(), self.generate_triangles())
```

---

## 3. Material System

### 3.1 Material Presets

```python
class MaterialPreset:
    """
    Predefined material presets mapping to WoW BLP textures.
    """

    PRESETS = {
        'titan_metal': {
            'texture': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Metal_Floor.blp',
            'shader': 0,  # Diffuse
            'blend_mode': 0,  # Opaque
        },
        'stone_dark': {
            'texture': 'Dungeons\\Textures\\Utgarde\\UtgardeWall01.blp',
            'shader': 0,
            'blend_mode': 0,
        },
        'stone_light': {
            'texture': 'Dungeons\\Textures\\Utgarde\\UtgardeWall02.blp',
            'shader': 0,
            'blend_mode': 0,
        },
        'volcanic_rock': {
            'texture': 'Dungeons\\Textures\\ObsidianSanctum\\ObsidianWall01.blp',
            'shader': 0,
            'blend_mode': 0,
        },
        'energy_glow': {
            'texture': 'Spells\\T_VFX_ArcaneBlue02.blp',
            'shader': 1,  # Specular
            'blend_mode': 1,  # AlphaKey
        },
        'floor_tile': {
            'texture': 'Dungeons\\Textures\\Utgarde\\UtgardeFloor01.blp',
            'shader': 0,
            'blend_mode': 0,
        },
    }

    @staticmethod
    def get_material(preset_name: str) -> dict:
        """
        Get material definition by preset name.

        Args:
            preset_name: Material preset name

        Returns:
            Material definition dict
        """
        if preset_name not in MaterialPreset.PRESETS:
            raise ValueError(f"Unknown material preset: {preset_name}")

        return MaterialPreset.PRESETS[preset_name]
```

### 3.2 Face Material Assignment

```python
class FaceMaterialAssignment:
    """
    Assign materials to room faces (floor, walls, ceiling).
    """

    @staticmethod
    def assign_room_materials(room_def: dict, face_materials: List[str]) -> List[int]:
        """
        Assign material indices to room triangles.

        Args:
            room_def: Room definition with material assignments
            face_materials: List of face types ('floor', 'wall', 'ceiling') per triangle

        Returns:
            List of material indices (int) per triangle
        """
        # Get material assignments from room definition
        material_map = room_def.get('materials', {
            'floor': 'floor_tile',
            'wall': 'stone_dark',
            'ceiling': 'stone_dark',
        })

        # Create material index mapping
        unique_materials = list(set(material_map.values()))
        material_indices = {mat: idx for idx, mat in enumerate(unique_materials)}

        # Assign material index to each triangle
        triangle_materials = []
        for face_type in face_materials:
            material_preset = material_map[face_type]
            material_idx = material_indices[material_preset]
            triangle_materials.append(material_idx)

        return triangle_materials, unique_materials
```

---

## 4. Portal System

### 4.1 Portal Generator

```python
class PortalGenerator:
    """
    Generate portal definitions for room connections (for occlusion culling).
    """

    @staticmethod
    def generate_doorway_portal(room1_def: dict, room2_def: dict, connection: dict) -> dict:
        """
        Generate portal at doorway between two rooms.

        Args:
            room1_def: First room definition
            room2_def: Second room definition
            connection: Connection definition with doorway position

        Returns:
            Portal definition with vertices and plane
        """
        # Calculate doorway position in world space
        doorway_pos = connection['position']
        doorway_width = connection.get('width', 4.0)  # Default 4 yards wide
        doorway_height = connection.get('height', 3.0)  # Default 3 yards tall
        doorway_orientation = connection.get('orientation', 0.0)

        # Calculate portal vertices (rectangular opening)
        # Portal plane perpendicular to connection direction
        cos_angle = math.cos(doorway_orientation)
        sin_angle = math.sin(doorway_orientation)

        half_width = doorway_width / 2

        portal_vertices = [
            # Bottom-left
            (
                doorway_pos[0] - half_width * sin_angle,
                doorway_pos[1] + half_width * cos_angle,
                doorway_pos[2]
            ),
            # Bottom-right
            (
                doorway_pos[0] + half_width * sin_angle,
                doorway_pos[1] - half_width * cos_angle,
                doorway_pos[2]
            ),
            # Top-right
            (
                doorway_pos[0] + half_width * sin_angle,
                doorway_pos[1] - half_width * cos_angle,
                doorway_pos[2] + doorway_height
            ),
            # Top-left
            (
                doorway_pos[0] - half_width * sin_angle,
                doorway_pos[1] + half_width * cos_angle,
                doorway_pos[2] + doorway_height
            ),
        ]

        # Calculate portal plane (for culling)
        # Plane equation: Ax + By + Cz + D = 0
        # Normal = connection direction
        plane_normal = (cos_angle, sin_angle, 0.0)
        plane_distance = -(plane_normal[0] * doorway_pos[0] +
                          plane_normal[1] * doorway_pos[1] +
                          plane_normal[2] * doorway_pos[2])

        return {
            'vertices': portal_vertices,
            'plane': {
                'normal': plane_normal,
                'distance': plane_distance,
            },
            'room1': room1_def['id'],
            'room2': room2_def['id'],
        }
```

---

## 5. Connection System

### 5.1 Connection Resolver

```python
class ConnectionResolver:
    """
    Resolve room connections and auto-generate connecting corridors.
    """

    @staticmethod
    def connect_rooms(room1_def: dict, room2_def: dict) -> dict:
        """
        Connect two rooms with auto-generated corridor.

        Args:
            room1_def: First room definition
            room2_def: Second room definition

        Returns:
            Connection definition with corridor geometry and doorway positions
        """
        # Calculate distance between room centers
        c1 = room1_def['center']
        c2 = room2_def['center']

        dx = c2[0] - c1[0]
        dy = c2[1] - c1[1]
        dz = c2[2] - c1[2]

        distance_2d = math.sqrt(dx**2 + dy**2)
        angle = math.atan2(dy, dx)

        # Corridor parameters
        corridor_width = 8.0  # Default corridor width
        corridor_height = 6.0  # Default corridor height

        # Calculate corridor start/end positions (at room edges)
        r1_radius = ConnectionResolver._get_room_radius(room1_def)
        r2_radius = ConnectionResolver._get_room_radius(room2_def)

        corridor_length = distance_2d - r1_radius - r2_radius

        corridor_start = (
            c1[0] + r1_radius * math.cos(angle),
            c1[1] + r1_radius * math.sin(angle),
            c1[2]
        )

        # Calculate corridor center
        corridor_center = (
            corridor_start[0] + (corridor_length / 2) * math.cos(angle),
            corridor_start[1] + (corridor_length / 2) * math.sin(angle),
            corridor_start[2] + dz / 2
        )

        return {
            'type': 'corridor',
            'width': corridor_width,
            'length': corridor_length,
            'height': corridor_height,
            'center': corridor_center,
            'orientation': angle,
            'room1_door': corridor_start,
            'room2_door': (
                c2[0] - r2_radius * math.cos(angle),
                c2[1] - r2_radius * math.sin(angle),
                c2[2]
            ),
        }

    @staticmethod
    def _get_room_radius(room_def: dict) -> float:
        """
        Get effective radius of room (for connection calculations).
        """
        room_type = room_def['type']

        if room_type == 'circular':
            return room_def['radius']
        elif room_type == 'box':
            # Use average of width/length
            return (room_def['width'] + room_def['length']) / 4
        elif room_type == 'chamber':
            return room_def['radius']
        else:
            return 10.0  # Default
```

---

## 6. Lighting System

### 6.1 Light Generator

```python
class LightGenerator:
    """
    Generate lighting definitions for rooms.
    """

    @staticmethod
    def generate_room_lights(room_def: dict) -> List[dict]:
        """
        Generate light definitions based on room type and size.

        Args:
            room_def: Room definition

        Returns:
            List of light definitions
        """
        lights = []
        room_type = room_def['type']
        center = room_def['center']

        # Get light settings from room definition or use defaults
        light_config = room_def.get('lights', [])

        if not light_config:
            # Auto-generate default lighting
            if room_type == 'circular':
                # Central point light for circular rooms
                lights.append({
                    'type': 'point',
                    'position': (center[0], center[1], center[2] + room_def['height'] * 0.7),
                    'color': (1.0, 1.0, 1.0),
                    'intensity': 1.0,
                    'attenuation_start': room_def['radius'] * 0.5,
                    'attenuation_end': room_def['radius'] * 1.5,
                })
            elif room_type == 'box':
                # Four corner lights for box rooms
                w = room_def['width'] / 3
                l = room_def['length'] / 3
                h = room_def['height'] * 0.7

                for x_offset in [-w, w]:
                    for y_offset in [-l, l]:
                        lights.append({
                            'type': 'point',
                            'position': (center[0] + x_offset, center[1] + y_offset, center[2] + h),
                            'color': (1.0, 1.0, 1.0),
                            'intensity': 0.7,
                            'attenuation_start': 10.0,
                            'attenuation_end': 25.0,
                        })
        else:
            # Use custom light configuration
            for light_def in light_config:
                # Resolve position (may be relative to room center)
                pos = light_def.get('position', (0, 0, 0))
                if light_def.get('relative', True):
                    pos = (center[0] + pos[0], center[1] + pos[1], center[2] + pos[2])

                lights.append({
                    'type': light_def.get('type', 'point'),
                    'position': pos,
                    'color': light_def.get('color', (1.0, 1.0, 1.0)),
                    'intensity': light_def.get('intensity', 1.0),
                    'attenuation_start': light_def.get('attenuation_start', 15.0),
                    'attenuation_end': light_def.get('attenuation_end', 30.0),
                })

        return lights
```

---

## 7. Doodad System

### 7.1 Doodad Placement

```python
class DoodadPlacer:
    """
    Place doodads (M2 models) within rooms.
    """

    @staticmethod
    def place_doodads(room_def: dict) -> List[dict]:
        """
        Place doodads in room based on room definition.

        Args:
            room_def: Room definition with doodad placements

        Returns:
            List of doodad placement definitions
        """
        doodads = []
        center = room_def['center']

        doodad_config = room_def.get('doodads', [])

        for doodad_def in doodad_config:
            model_path = doodad_def['model']
            positions = doodad_def.get('positions', [])

            for pos in positions:
                # Convert relative position to world space
                world_pos = (center[0] + pos[0], center[1] + pos[1], center[2] + pos[2])

                doodads.append({
                    'model': model_path,
                    'position': world_pos,
                    'rotation': doodad_def.get('rotation', (0, 0, 0)),
                    'scale': doodad_def.get('scale', 1.0),
                    'doodad_set': doodad_def.get('doodad_set', 0),
                })

        return doodads
```

---

## 8. BSP Tree Generator

### 8.1 BSP Builder

```python
class BSPTreeBuilder:
    """
    Build BSP tree for collision detection.
    """

    @staticmethod
    def build_bsp_tree(polygons: List[dict], max_depth: int = 10, depth: int = 0) -> dict:
        """
        Recursively build BSP tree from polygon list.

        Args:
            polygons: List of polygons (each with vertices and plane)
            max_depth: Maximum tree depth
            depth: Current recursion depth

        Returns:
            BSP tree node
        """
        if not polygons or depth >= max_depth:
            # Leaf node
            return {
                'type': 'leaf',
                'polygons': polygons,
            }

        # Select splitting plane (use first polygon's plane)
        split_plane = polygons[0]['plane']

        # Partition polygons
        front_polygons = []
        back_polygons = []

        for poly in polygons[1:]:
            classification = BSPTreeBuilder._classify_polygon(poly, split_plane)

            if classification == 'front':
                front_polygons.append(poly)
            elif classification == 'back':
                back_polygons.append(poly)
            else:  # spanning
                # Split polygon (simplified: add to both sides)
                front_polygons.append(poly)
                back_polygons.append(poly)

        # Recursively build child nodes
        return {
            'type': 'node',
            'plane': split_plane,
            'front': BSPTreeBuilder.build_bsp_tree(front_polygons, max_depth, depth + 1),
            'back': BSPTreeBuilder.build_bsp_tree(back_polygons, max_depth, depth + 1),
        }

    @staticmethod
    def _classify_polygon(poly: dict, plane: dict) -> str:
        """
        Classify polygon relative to plane.

        Returns:
            'front', 'back', or 'spanning'
        """
        # Simplified classification based on polygon center
        center = poly['center']
        distance = (plane['normal'][0] * center[0] +
                   plane['normal'][1] * center[1] +
                   plane['normal'][2] * center[2] +
                   plane['distance'])

        if distance > 0.1:
            return 'front'
        elif distance < -0.1:
            return 'back'
        else:
            return 'spanning'
```

---

## 9. WMO Assembly

### 9.1 WMO Root File

```python
import struct
from io import BytesIO

class WMORootAssembler:
    """
    Assemble WMO root file from dungeon definition.
    """

    def __init__(self, dungeon_def: dict):
        self.dungeon_def = dungeon_def
        self.materials = []
        self.groups = []
        self.portals = []
        self.lights = []
        self.doodads = []

    def assemble(self) -> bytes:
        """
        Assemble complete WMO root file.

        Returns:
            Binary WMO root file data
        """
        output = BytesIO()

        # Write MVER chunk (version = 17)
        self._write_chunk(output, b'MVER', struct.pack('<I', 17))

        # Collect all materials, groups, portals, lights, doodads from rooms
        self._collect_components()

        # Write MOHD chunk (header)
        self._write_mohd_chunk(output)

        # Write MOTX chunk (texture paths)
        self._write_motx_chunk(output)

        # Write MOMT chunk (material definitions)
        self._write_momt_chunk(output)

        # Write MOGN chunk (group names)
        self._write_mogn_chunk(output)

        # Write MOGI chunk (group info)
        self._write_mogi_chunk(output)

        # Write MOSB chunk (skybox)
        self._write_mosb_chunk(output)

        # Write MOPV chunk (portal vertices)
        self._write_mopv_chunk(output)

        # Write MOPT chunk (portal info)
        self._write_mopt_chunk(output)

        # Write MOPR chunk (portal references)
        self._write_mopr_chunk(output)

        # Write MOLT chunk (lights)
        self._write_molt_chunk(output)

        # Write MODS chunk (doodad sets)
        self._write_mods_chunk(output)

        # Write MODN chunk (doodad names)
        self._write_modn_chunk(output)

        # Write MODD chunk (doodad definitions)
        self._write_modd_chunk(output)

        return output.getvalue()

    def _write_chunk(self, output: BytesIO, magic: bytes, data: bytes):
        """
        Write chunk to output stream.

        Format: magic (4 bytes) + size (4 bytes) + data
        """
        output.write(magic)
        output.write(struct.pack('<I', len(data)))
        output.write(data)

    def _collect_components(self):
        """
        Collect all materials, groups, portals, lights, doodads from rooms.
        """
        # Collect materials from all rooms
        material_set = set()
        for room in self.dungeon_def['rooms']:
            room_materials = room.get('materials', {})
            for material in room_materials.values():
                material_set.add(material)

        self.materials = list(material_set)

        # Each room becomes one WMO group
        self.groups = self.dungeon_def['rooms']

        # Collect portals from connections
        self.portals = []  # TODO: Generate from connections

        # Collect lights from all rooms
        for room in self.dungeon_def['rooms']:
            room_lights = room.get('lights', [])
            self.lights.extend(room_lights)

        # Collect doodads from all rooms
        for room in self.dungeon_def['rooms']:
            room_doodads = room.get('doodads', [])
            self.doodads.extend(room_doodads)

    def _write_mohd_chunk(self, output: BytesIO):
        """
        Write MOHD chunk (WMO header).

        Format:
            uint32 nMaterials
            uint32 nGroups
            uint32 nPortals
            uint32 nLights
            uint32 nModels
            uint32 nDoodads
            uint32 nSets
            uint32 ambientColor
            uint32 wmoID
            float[3] bounding_box_min
            float[3] bounding_box_max
            uint16 flags
        """
        # Calculate bounding box from all rooms
        all_centers = [room['center'] for room in self.groups]
        min_x = min(c[0] for c in all_centers) - 50
        min_y = min(c[1] for c in all_centers) - 50
        min_z = min(c[2] for c in all_centers) - 10
        max_x = max(c[0] for c in all_centers) + 50
        max_y = max(c[1] for c in all_centers) + 50
        max_z = max(c[2] for c in all_centers) + 30

        data = struct.pack('<IIIIIIIIffffffff',
            len(self.materials),     # nMaterials
            len(self.groups),         # nGroups
            len(self.portals),        # nPortals
            len(self.lights),         # nLights
            0,                        # nModels (unused)
            len(self.doodads),        # nDoodads
            1,                        # nSets (always 1)
            0x00000000,               # ambientColor (BGRA)
            self.dungeon_def['map_id'],  # wmoID
            min_x, min_y, min_z,      # bounding box min
            max_x, max_y, max_z,      # bounding box max
            0                          # flags
        )

        self._write_chunk(output, b'MOHD', data)

    def _write_motx_chunk(self, output: BytesIO):
        """
        Write MOTX chunk (texture file paths).

        Format: Null-terminated strings concatenated
        """
        texture_strings = []

        for material_name in self.materials:
            material = MaterialPreset.get_material(material_name)
            texture_path = material['texture']
            texture_strings.append(texture_path.encode('utf-8') + b'\x00')

        data = b''.join(texture_strings)
        self._write_chunk(output, b'MOTX', data)

    def _write_momt_chunk(self, output: BytesIO):
        """
        Write MOMT chunk (material definitions).

        Format (per material, 64 bytes):
            uint32 flags
            uint32 shader
            uint32 blendMode
            uint32 texture1_offset (into MOTX)
            uint32 color1
            uint32 flags1
            uint32 texture2_offset
            uint32 color2
            uint32 flags2
            uint32 color3
            float[11] unknown/padding
        """
        data = BytesIO()

        texture_offset = 0
        for material_name in self.materials:
            material = MaterialPreset.get_material(material_name)
            texture_path = material['texture']

            # Material flags: 0x01=unlit, 0x04=exterior light
            flags = 0x00

            data.write(struct.pack('<IIIIIIIIII',
                flags,                         # flags
                material['shader'],            # shader
                material['blend_mode'],        # blendMode
                texture_offset,                # texture1_offset
                0xFFFFFFFF,                    # color1 (white)
                0,                             # flags1
                0,                             # texture2_offset (none)
                0xFFFFFFFF,                    # color2
                0,                             # flags2
                0xFFFFFFFF                     # color3
            ))

            # Padding (44 bytes)
            data.write(b'\x00' * 44)

            # Update texture offset
            texture_offset += len(texture_path.encode('utf-8')) + 1

        self._write_chunk(output, b'MOMT', data.getvalue())

    def _write_mogn_chunk(self, output: BytesIO):
        """
        Write MOGN chunk (group names).

        Format: Null-terminated strings concatenated
        """
        group_names = []

        for i, room in enumerate(self.groups):
            group_name = room.get('name', f"Group_{i:03d}")
            group_names.append(group_name.encode('utf-8') + b'\x00')

        data = b''.join(group_names)
        self._write_chunk(output, b'MOGN', data)

    def _write_mogi_chunk(self, output: BytesIO):
        """
        Write MOGI chunk (group info).

        Format (per group, 32 bytes):
            uint32 flags
            float[3] bounding_box_min
            float[3] bounding_box_max
            int32 nameOffset (into MOGN)
        """
        data = BytesIO()
        name_offset = 0

        for room in self.groups:
            # Calculate room bounding box
            center = room['center']
            room_type = room['type']

            if room_type == 'circular':
                r = room['radius']
                h = room['height']
                bbox_min = (center[0] - r, center[1] - r, center[2])
                bbox_max = (center[0] + r, center[1] + r, center[2] + h)
            elif room_type == 'box':
                w = room['width'] / 2
                l = room['length'] / 2
                h = room['height']
                bbox_min = (center[0] - w, center[1] - l, center[2])
                bbox_max = (center[0] + w, center[1] + l, center[2] + h)
            else:
                # Default
                bbox_min = (center[0] - 20, center[1] - 20, center[2])
                bbox_max = (center[0] + 20, center[1] + 20, center[2] + 10)

            # Group flags: 0x01=has_bsp, 0x08=indoor, 0x2000=show_skybox
            flags = 0x01 | 0x08

            data.write(struct.pack('<Ifffffffi',
                flags,
                bbox_min[0], bbox_min[1], bbox_min[2],
                bbox_max[0], bbox_max[1], bbox_max[2],
                name_offset
            ))

            # Update name offset
            group_name = room.get('name', f"Group_{len(self.groups):03d}")
            name_offset += len(group_name.encode('utf-8')) + 1

        self._write_chunk(output, b'MOGI', data.getvalue())

    def _write_mosb_chunk(self, output: BytesIO):
        """
        Write MOSB chunk (skybox name).

        Format: Null-terminated string
        """
        # No skybox for indoor dungeon
        skybox_name = b'\x00'
        self._write_chunk(output, b'MOSB', skybox_name)

    def _write_mopv_chunk(self, output: BytesIO):
        """
        Write MOPV chunk (portal vertices).

        Format: Array of float[3] vertices
        """
        if not self.portals:
            # Empty chunk
            self._write_chunk(output, b'MOPV', b'')
            return

        data = BytesIO()

        for portal in self.portals:
            for vertex in portal['vertices']:
                data.write(struct.pack('<fff', vertex[0], vertex[1], vertex[2]))

        self._write_chunk(output, b'MOPV', data.getvalue())

    def _write_mopt_chunk(self, output: BytesIO):
        """
        Write MOPT chunk (portal info).

        Format (per portal, 20 bytes):
            uint16 startVertex
            uint16 count
            float[4] plane (nx, ny, nz, distance)
        """
        if not self.portals:
            self._write_chunk(output, b'MOPT', b'')
            return

        data = BytesIO()
        vertex_offset = 0

        for portal in self.portals:
            vertex_count = len(portal['vertices'])
            plane = portal['plane']

            data.write(struct.pack('<HHffff',
                vertex_offset,
                vertex_count,
                plane['normal'][0],
                plane['normal'][1],
                plane['normal'][2],
                plane['distance']
            ))

            vertex_offset += vertex_count

        self._write_chunk(output, b'MOPT', data.getvalue())

    def _write_mopr_chunk(self, output: BytesIO):
        """
        Write MOPR chunk (portal references).

        Format (per reference, 8 bytes):
            uint16 portalIndex
            uint16 groupIndex
            int16 side (1=front, -1=back)
            uint16 padding
        """
        if not self.portals:
            self._write_chunk(output, b'MOPR', b'')
            return

        data = BytesIO()

        for i, portal in enumerate(self.portals):
            # Each portal references two groups (room1 and room2)
            room1_id = portal['room1']
            room2_id = portal['room2']

            # Find group indices
            group1_idx = next((j for j, r in enumerate(self.groups) if r['id'] == room1_id), 0)
            group2_idx = next((j for j, r in enumerate(self.groups) if r['id'] == room2_id), 0)

            # Portal reference for room1 (front side)
            data.write(struct.pack('<HHhH', i, group1_idx, 1, 0))

            # Portal reference for room2 (back side)
            data.write(struct.pack('<HHhH', i, group2_idx, -1, 0))

        self._write_chunk(output, b'MOPR', data.getvalue())

    def _write_molt_chunk(self, output: BytesIO):
        """
        Write MOLT chunk (lights).

        Format (per light, 48 bytes):
            uint8 type (0=omni, 1=spot, 2=directional, 3=ambient)
            uint8 useAttenuation
            uint8 padding[2]
            uint32 color (BGRA)
            float[3] position
            float intensity
            float[3] unknown
            float attenuationStart
            float attenuationEnd
            float[4] unknown2
        """
        if not self.lights:
            self._write_chunk(output, b'MOLT', b'')
            return

        data = BytesIO()

        for light in self.lights:
            light_type = 0  # Omni/point light
            use_attenuation = 1

            # Convert RGB to BGRA
            r, g, b = light['color']
            color = (int(b * 255) << 16) | (int(g * 255) << 8) | int(r * 255) | 0xFF000000

            pos = light['position']
            intensity = light['intensity']
            atten_start = light['attenuation_start']
            atten_end = light['attenuation_end']

            data.write(struct.pack('<BBBBIfffffffffff',
                light_type,
                use_attenuation,
                0, 0,  # padding
                color,
                pos[0], pos[1], pos[2],
                intensity,
                0.0, 0.0, 0.0,  # unknown
                atten_start,
                atten_end,
                0.0, 0.0, 0.0, 0.0  # unknown2
            ))

        self._write_chunk(output, b'MOLT', data.getvalue())

    def _write_mods_chunk(self, output: BytesIO):
        """
        Write MODS chunk (doodad sets).

        Format (per set, 32 bytes):
            char[20] name
            uint32 startIndex
            uint32 count
            uint32 padding
        """
        # Single doodad set containing all doodads
        data = struct.pack('<20sIII',
            b'Set_Default\x00',
            0,  # startIndex
            len(self.doodads),  # count
            0   # padding
        )

        self._write_chunk(output, b'MODS', data)

    def _write_modn_chunk(self, output: BytesIO):
        """
        Write MODN chunk (doodad model names).

        Format: Null-terminated strings concatenated
        """
        if not self.doodads:
            self._write_chunk(output, b'MODN', b'')
            return

        doodad_names = []

        for doodad in self.doodads:
            model_path = doodad['model']
            doodad_names.append(model_path.encode('utf-8') + b'\x00')

        data = b''.join(doodad_names)
        self._write_chunk(output, b'MODN', data)

    def _write_modd_chunk(self, output: BytesIO):
        """
        Write MODD chunk (doodad definitions).

        Format (per doodad, 40 bytes):
            uint32 nameOffset (into MODN)
            float[3] position
            float[4] rotation (quaternion: x, y, z, w)
            float scale
            uint32 color (BGRA)
        """
        if not self.doodads:
            self._write_chunk(output, b'MODD', b'')
            return

        data = BytesIO()
        name_offset = 0

        for doodad in self.doodads:
            pos = doodad['position']
            rot = doodad.get('rotation', (0, 0, 0))
            scale = doodad.get('scale', 1.0)

            # Convert Euler rotation to quaternion (simplified: identity)
            quat = (0.0, 0.0, 0.0, 1.0)

            data.write(struct.pack('<Iffffffffi',
                name_offset,
                pos[0], pos[1], pos[2],
                quat[0], quat[1], quat[2], quat[3],
                scale,
                0xFFFFFFFF  # color (white)
            ))

            # Update name offset
            model_path = doodad['model']
            name_offset += len(model_path.encode('utf-8')) + 1

        self._write_chunk(output, b'MODD', data.getvalue())
```

### 9.2 WMO Group File

```python
class WMOGroupAssembler:
    """
    Assemble WMO group file (one per room).
    """

    def __init__(self, room_def: dict, material_map: dict):
        self.room_def = room_def
        self.material_map = material_map  # Material name -> index

        # Generate room geometry
        self.room_geometry = self._generate_room_geometry()

    def assemble(self) -> bytes:
        """
        Assemble complete WMO group file.

        Returns:
            Binary WMO group file data
        """
        output = BytesIO()

        # Write MVER chunk
        self._write_chunk(output, b'MVER', struct.pack('<I', 17))

        # Write MOGP chunk (group header + all sub-chunks)
        self._write_mogp_chunk(output)

        return output.getvalue()

    def _write_chunk(self, output: BytesIO, magic: bytes, data: bytes):
        """Write chunk to output stream."""
        output.write(magic)
        output.write(struct.pack('<I', len(data)))
        output.write(data)

    def _generate_room_geometry(self) -> dict:
        """
        Generate geometry for this room based on room type.

        Returns:
            dict with vertices, normals, uvs, triangles, materials
        """
        room_type = self.room_def['type']

        if room_type == 'circular':
            room_gen = CircularRoom(
                self.room_def['radius'],
                self.room_def['height'],
                self.room_def.get('segments', 24)
            )
        elif room_type == 'box':
            room_gen = BoxRoom(
                self.room_def['width'],
                self.room_def['length'],
                self.room_def['height']
            )
        elif room_type == 'corridor':
            room_gen = Corridor(
                self.room_def['width'],
                self.room_def['length'],
                self.room_def['height']
            )
        elif room_type == 'spiral':
            room_gen = SpiralRamp(
                self.room_def['radius'],
                self.room_def['height'],
                self.room_def['turns'],
                self.room_def.get('segments', 48)
            )
        elif room_type == 'chamber':
            room_gen = ChamberRoom(
                self.room_def['radius'],
                self.room_def['height'],
                self.room_def['sides']
            )
        else:
            raise ValueError(f"Unknown room type: {room_type}")

        # Translate vertices to room center
        center = self.room_def['center']
        vertices = room_gen.generate_vertices()
        vertices_world = [(v[0] + center[0], v[1] + center[1], v[2] + center[2])
                         for v in vertices]

        return {
            'vertices': vertices_world,
            'normals': room_gen.generate_normals(),
            'uvs': room_gen.generate_uvs(),
            'triangles': room_gen.generate_triangles(),
            'face_materials': room_gen.generate_face_materials(),
        }

    def _write_mogp_chunk(self, output: BytesIO):
        """
        Write MOGP chunk (group header + all geometry sub-chunks).

        MOGP contains all group geometry as sub-chunks.
        """
        mogp_data = BytesIO()

        # Write group header (68 bytes)
        self._write_mogp_header(mogp_data)

        # Write geometry sub-chunks
        self._write_mopy_subchunk(mogp_data)  # Material info per triangle
        self._write_movi_subchunk(mogp_data)  # Triangle indices
        self._write_movt_subchunk(mogp_data)  # Vertices
        self._write_monr_subchunk(mogp_data)  # Normals
        self._write_motv_subchunk(mogp_data)  # Texture coords
        self._write_moba_subchunk(mogp_data)  # Render batches

        # Write MOGP chunk
        self._write_chunk(output, b'MOGP', mogp_data.getvalue())

    def _write_mogp_header(self, output: BytesIO):
        """
        Write MOGP header (68 bytes).

        Format:
            uint32 nameOffset
            uint32 descOffset
            uint32 flags
            float[3] bounding_box_min
            float[3] bounding_box_max
            uint16 portalStart
            uint16 portalCount
            uint16 transBatchCount
            uint16 intBatchCount
            uint16 extBatchCount
            uint16 padding
            uint8[4] fogIndices
            uint32 liquidType
            uint32 groupID
            uint32 unknown1
            uint32 unknown2
        """
        # Calculate bounding box
        vertices = self.room_geometry['vertices']
        bbox_min = (min(v[0] for v in vertices), min(v[1] for v in vertices), min(v[2] for v in vertices))
        bbox_max = (max(v[0] for v in vertices), max(v[1] for v in vertices), max(v[2] for v in vertices))

        # Group flags: 0x01=has_bsp, 0x08=indoor
        flags = 0x01 | 0x08

        output.write(struct.pack('<IIIffffffHHHHHHBBBBIIII',
            0,  # nameOffset (unused, names in root MOGN)
            0,  # descOffset
            flags,
            bbox_min[0], bbox_min[1], bbox_min[2],
            bbox_max[0], bbox_max[1], bbox_max[2],
            0,  # portalStart
            0,  # portalCount
            0,  # transBatchCount
            1,  # intBatchCount (one opaque batch)
            0,  # extBatchCount
            0,  # padding
            0, 0, 0, 0,  # fogIndices
            0,  # liquidType (no liquid)
            0,  # groupID
            0, 0  # unknown
        ))

    def _write_mopy_subchunk(self, output: BytesIO):
        """
        Write MOPY sub-chunk (material info per triangle).

        Format (per triangle, 2 bytes):
            uint8 flags
            uint8 materialID
        """
        triangles = self.room_geometry['triangles']
        face_materials = self.room_geometry['face_materials']

        # Resolve material indices
        material_indices = []
        for face_mat in face_materials:
            # Get material preset name from room definition
            room_materials = self.room_def.get('materials', {
                'floor': 'floor_tile',
                'wall': 'stone_dark',
                'ceiling': 'stone_dark',
            })
            material_preset = room_materials[face_mat]
            material_idx = self.material_map[material_preset]
            material_indices.append(material_idx)

        data = BytesIO()
        for mat_idx in material_indices:
            flags = 0x00  # No collision
            data.write(struct.pack('<BB', flags, mat_idx))

        self._write_subchunk(output, b'MOPY', data.getvalue())

    def _write_movi_subchunk(self, output: BytesIO):
        """
        Write MOVI sub-chunk (triangle vertex indices).

        Format: Array of uint16[3] (triangle indices)
        """
        triangles = self.room_geometry['triangles']

        data = BytesIO()
        for tri in triangles:
            data.write(struct.pack('<HHH', tri[0], tri[1], tri[2]))

        self._write_subchunk(output, b'MOVI', data.getvalue())

    def _write_movt_subchunk(self, output: BytesIO):
        """
        Write MOVT sub-chunk (vertices).

        Format: Array of float[3] (vertex positions)
        """
        vertices = self.room_geometry['vertices']

        data = BytesIO()
        for v in vertices:
            data.write(struct.pack('<fff', v[0], v[1], v[2]))

        self._write_subchunk(output, b'MOVT', data.getvalue())

    def _write_monr_subchunk(self, output: BytesIO):
        """
        Write MONR sub-chunk (normals).

        Format: Array of float[3] (normal vectors)
        """
        normals = self.room_geometry['normals']

        data = BytesIO()
        for n in normals:
            data.write(struct.pack('<fff', n[0], n[1], n[2]))

        self._write_subchunk(output, b'MONR', data.getvalue())

    def _write_motv_subchunk(self, output: BytesIO):
        """
        Write MOTV sub-chunk (texture coordinates).

        Format: Array of float[2] (UV coords)
        """
        uvs = self.room_geometry['uvs']

        data = BytesIO()
        for uv in uvs:
            data.write(struct.pack('<ff', uv[0], uv[1]))

        self._write_subchunk(output, b'MOTV', data.getvalue())

    def _write_moba_subchunk(self, output: BytesIO):
        """
        Write MOBA sub-chunk (render batches).

        Format (per batch, 24 bytes):
            uint16 startIndex
            uint16 count
            uint16 minIndex
            uint16 maxIndex
            uint8 materialID
            uint8 padding[3]
        """
        triangles = self.room_geometry['triangles']
        vertices = self.room_geometry['vertices']

        # Single batch for entire room
        data = struct.pack('<HHHHBBBB',
            0,  # startIndex (first triangle)
            len(triangles) * 3,  # count (total indices)
            0,  # minIndex
            len(vertices) - 1,  # maxIndex
            0,  # materialID (first material)
            0, 0, 0  # padding
        )

        # Pad to 24 bytes
        data += b'\x00' * (24 - len(data))

        self._write_subchunk(output, b'MOBA', data)

    def _write_subchunk(self, output: BytesIO, magic: bytes, data: bytes):
        """Write sub-chunk within MOGP."""
        output.write(magic)
        output.write(struct.pack('<I', len(data)))
        output.write(data)
```

---

## 10. High-Level API

```python
import os
import json

def build_dungeon(dungeon_def: dict, output_dir: str, dbc_dir: str) -> dict:
    """
    Build complete dungeon with full WMO generation.

    Args:
        dungeon_def: Dungeon definition dictionary
        output_dir: Output directory for WMO files
        dbc_dir: Path to DBFilesClient directory

    Returns:
        dict with:
            - wmo_files: List of generated WMO file paths
            - coordinate_metadata: Spawn coordinates for SQL generator
            - map_id: Map.dbc ID
    """
    print(f"Building dungeon: {dungeon_def['name']}")

    # Create output directory
    wmo_dir = os.path.join(output_dir, "World", "wmo", "Dungeons", dungeon_def['name'])
    os.makedirs(wmo_dir, exist_ok=True)

    # Resolve room connections and generate corridors
    print("Resolving room connections...")
    resolve_connections(dungeon_def)

    # Generate portals for room connections
    print("Generating portal system...")
    generate_portals(dungeon_def)

    # Collect all materials
    print("Collecting materials...")
    material_map = collect_materials(dungeon_def)

    # Generate WMO root file
    print("Assembling WMO root file...")
    root_assembler = WMORootAssembler(dungeon_def)
    root_data = root_assembler.assemble()

    root_path = os.path.join(wmo_dir, f"{dungeon_def['name']}.wmo")
    with open(root_path, 'wb') as f:
        f.write(root_data)
    print(f"  Written: {root_path}")

    # Generate WMO group files (one per room)
    group_files = []
    for i, room in enumerate(dungeon_def['rooms']):
        print(f"Assembling group {i}: {room['name']}")
        group_assembler = WMOGroupAssembler(room, material_map)
        group_data = group_assembler.assemble()

        group_path = os.path.join(wmo_dir, f"{dungeon_def['name']}_{i:03d}.wmo")
        with open(group_path, 'wb') as f:
            f.write(group_data)
        group_files.append(group_path)
        print(f"  Written: {group_path}")

    # Export spawn coordinates
    print("Exporting spawn coordinates...")
    coordinate_metadata = export_spawn_coordinates(dungeon_def)

    coord_path = os.path.join(output_dir, "coordinate_metadata.json")
    with open(coord_path, 'w') as f:
        json.dump(coordinate_metadata, f, indent=2)
    print(f"  Written: {coord_path}")

    # Register in Map.dbc
    print("Registering in Map.dbc...")
    register_dungeon_map(dungeon_def, dbc_dir)

    print(f"\n✓ Dungeon build complete!")
    print(f"  Root WMO: {root_path}")
    print(f"  Group WMOs: {len(group_files)} files")
    print(f"  Coordinates: {coord_path}")

    return {
        'wmo_files': [root_path] + group_files,
        'coordinate_metadata': coordinate_metadata,
        'map_id': dungeon_def['map_id'],
    }


def resolve_connections(dungeon_def: dict):
    """
    Resolve room connections and auto-generate connecting corridors.
    """
    # TODO: Implement connection resolver
    pass


def generate_portals(dungeon_def: dict):
    """
    Generate portal definitions for room connections.
    """
    # TODO: Implement portal generator
    pass


def collect_materials(dungeon_def: dict) -> dict:
    """
    Collect all unique materials from rooms and build material index map.

    Returns:
        dict mapping material preset name to index
    """
    material_set = set()

    for room in dungeon_def['rooms']:
        room_materials = room.get('materials', {})
        for material in room_materials.values():
            material_set.add(material)

    materials = list(material_set)
    return {mat: idx for idx, mat in enumerate(materials)}


def export_spawn_coordinates(dungeon_def: dict) -> dict:
    """
    Export spawn coordinates for bosses, trash, doors.

    Returns:
        Coordinate metadata dict for SQL generator
    """
    coordinate_metadata = {
        'map_id': dungeon_def['map_id'],
        'dungeon_name': dungeon_def['name'],
        'rooms': {},
    }

    for room in dungeon_def['rooms']:
        room_id = room['id']
        center = room['center']

        # Boss spawn
        boss_spawn = None
        if room.get('boss', {}).get('enabled'):
            boss_spawn = {
                'entry_id': room['boss']['entry_id'],
                'position': center,
                'orientation': 0.0,
            }

        # Trash spawns (TODO: implement distribution logic)
        trash_spawns = []

        # Door positions (TODO: implement from connections)
        doors = []

        coordinate_metadata['rooms'][room_id] = {
            'center': center,
            'boss_spawn': boss_spawn,
            'trash_spawns': trash_spawns,
            'doors': doors,
        }

    return coordinate_metadata


def register_dungeon_map(dungeon_def: dict, dbc_dir: str):
    """
    Register dungeon in Map.dbc.
    """
    from world_builder.dbc_injector import inject_map_entry

    inject_map_entry(
        dbc_path=os.path.join(dbc_dir, "Map.dbc"),
        map_id=dungeon_def['map_id'],
        internal_name=dungeon_def['name'],
        map_type=1,  # Dungeon
        instance_type=dungeon_def.get('instance_type', 1),
        directory=f"Dungeons\\{dungeon_def['name']}",
        area_table_id=dungeon_def.get('area_id', 0),
        loading_screen_id=dungeon_def.get('loading_screen_id', 0),
        expansion_id=2  # WotLK
    )
```

---

## 11. Vault of Storms - Complete Definition

```python
VAULT_OF_STORMS = {
    'name': 'VaultOfStorms',
    'display_name': 'The Vault of Storms',
    'map_id': 9001,
    'instance_type': 1,  # 5-man dungeon
    'min_level': 80,
    'max_level': 80,

    'rooms': [
        {
            'id': 'vestibule',
            'name': 'The Titan Vestibule',
            'type': 'circular',
            'radius': 25,
            'height': 15,
            'center': (0, 0, 0),
            'materials': {
                'floor': 'titan_metal',
                'wall': 'titan_metal',
                'ceiling': 'titan_metal',
            },
            'lights': [
                {'type': 'point', 'position': (0, 0, 10), 'color': (0.3, 0.5, 1.0), 'intensity': 1.0, 'attenuation_start': 15, 'attenuation_end': 40}
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Pillar_01.m2',
                    'positions': [(15, 0, 0), (-15, 0, 0), (0, 15, 0), (0, -15, 0)]
                }
            ],
            'boss': {'enabled': False},
            'connects_to': ['corridor1'],
        },
        {
            'id': 'corridor1',
            'name': 'Containment Corridor',
            'type': 'corridor',
            'width': 8,
            'length': 50,
            'height': 6,
            'center': (0, 50, 0),
            'materials': {
                'floor': 'stone_dark',
                'wall': 'stone_dark',
                'ceiling': 'stone_dark',
            },
            'lights': [
                {'type': 'point', 'position': (0, -15, 4), 'color': (0.8, 0.8, 1.0), 'intensity': 0.7, 'attenuation_start': 10, 'attenuation_end': 25},
                {'type': 'point', 'position': (0, 15, 4), 'color': (0.8, 0.8, 1.0), 'intensity': 0.7, 'attenuation_start': 10, 'attenuation_end': 25},
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Conduit_Broken.m2',
                    'positions': [(3, -10, 0), (-3, 10, 0)]
                }
            ],
            'boss': {'enabled': False},
            'connects_to': ['darkling_nexus'],
        },
        {
            'id': 'darkling_nexus',
            'name': 'The Darkling Nexus',
            'type': 'circular',
            'radius': 30,
            'height': 20,
            'center': (0, 100, 0),
            'materials': {
                'floor': 'volcanic_rock',
                'wall': 'stone_dark',
                'ceiling': 'stone_dark',
            },
            'lights': [
                {'type': 'point', 'position': (0, 0, 15), 'color': (0.5, 0.2, 0.8), 'intensity': 1.2, 'attenuation_start': 20, 'attenuation_end': 50}
            ],
            'doodads': [],
            'boss': {
                'enabled': True,
                'entry_id': 90100,  # Aberrant Primate (Shadow)
                'spawn_offset': (0, 0, 0),
            },
            'connects_to': ['winding_core'],
        },
        {
            'id': 'winding_core',
            'name': 'The Winding Core',
            'type': 'spiral',
            'radius': 15,
            'height': -30,  # Descending
            'turns': 3.0,
            'center': (0, 150, 20),
            'materials': {
                'floor': 'titan_metal',
                'wall': 'titan_metal',
                'ceiling': 'titan_metal',
            },
            'lights': [
                {'type': 'point', 'position': (0, 0, 15), 'color': (0.4, 0.7, 1.0), 'intensity': 0.8, 'attenuation_start': 12, 'attenuation_end': 30},
                {'type': 'point', 'position': (0, 0, 0), 'color': (0.4, 0.7, 1.0), 'intensity': 0.8, 'attenuation_start': 12, 'attenuation_end': 30},
                {'type': 'point', 'position': (0, 0, -15), 'color': (0.4, 0.7, 1.0), 'intensity': 0.8, 'attenuation_start': 12, 'attenuation_end': 30},
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Coolant_Vent.m2',
                    'positions': [(10, 0, 10), (10, 0, -10), (10, 0, -20)]
                }
            ],
            'boss': {'enabled': False},
            'connects_to': ['forge_of_wards'],
        },
        {
            'id': 'forge_of_wards',
            'name': 'The Forge of Wards',
            'type': 'box',
            'width': 35,
            'length': 35,
            'height': 12,
            'center': (0, 200, -10),
            'materials': {
                'floor': 'titan_metal',
                'wall': 'volcanic_rock',
                'ceiling': 'stone_dark',
            },
            'lights': [
                {'type': 'point', 'position': (-10, -10, 8), 'color': (1.0, 0.5, 0.2), 'intensity': 1.1, 'attenuation_start': 15, 'attenuation_end': 35},
                {'type': 'point', 'position': (10, -10, 8), 'color': (1.0, 0.5, 0.2), 'intensity': 1.1, 'attenuation_start': 15, 'attenuation_end': 35},
                {'type': 'point', 'position': (-10, 10, 8), 'color': (1.0, 0.5, 0.2), 'intensity': 1.1, 'attenuation_start': 15, 'attenuation_end': 35},
                {'type': 'point', 'position': (10, 10, 8), 'color': (1.0, 0.5, 0.2), 'intensity': 1.1, 'attenuation_start': 15, 'attenuation_end': 35},
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Forge_Anvil.m2',
                    'positions': [(10, 10, 0)]
                }
            ],
            'boss': {
                'enabled': True,
                'entry_id': 90101,  # Aberrant Forgekeeper (Fire)
                'spawn_offset': (0, 0, 0),
            },
            'connects_to': ['storm_gallery'],
        },
        {
            'id': 'storm_gallery',
            'name': 'The Storm Gallery',
            'type': 'box',
            'width': 50,
            'length': 40,
            'height': 25,
            'center': (0, 260, -10),
            'materials': {
                'floor': 'titan_metal',
                'wall': 'stone_light',
                'ceiling': 'stone_light',
            },
            'lights': [
                {'type': 'point', 'position': (0, 0, 20), 'color': (0.7, 0.8, 1.0), 'intensity': 1.3, 'attenuation_start': 25, 'attenuation_end': 60}
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Pillar_Tall.m2',
                    'positions': [(20, 15, 0), (-20, 15, 0), (20, -15, 0), (-20, -15, 0)]
                }
            ],
            'boss': {
                'enabled': True,
                'entry_id': 90102,  # Aberrant Watcher (Lightning)
                'spawn_offset': (0, 0, 0),
            },
            'connects_to': ['primate_throne'],
        },
        {
            'id': 'primate_throne',
            'name': 'The Primate Throne',
            'type': 'circular',
            'radius': 20,
            'height': 15,
            'center': (0, 320, -10),
            'materials': {
                'floor': 'volcanic_rock',
                'wall': 'stone_dark',
                'ceiling': 'stone_dark',
            },
            'lights': [
                {'type': 'point', 'position': (0, 0, 10), 'color': (0.6, 0.6, 0.6), 'intensity': 0.9, 'attenuation_start': 15, 'attenuation_end': 35}
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Debris_Pile.m2',
                    'positions': [(10, 0, 0)]
                }
            ],
            'boss': {'enabled': False},
            'connects_to': ['inner_seal'],
        },
        {
            'id': 'inner_seal',
            'name': 'The Inner Seal',
            'type': 'corridor',
            'width': 6,
            'length': 15,
            'height': 5,
            'center': (0, 350, -10),
            'materials': {
                'floor': 'titan_metal',
                'wall': 'titan_metal',
                'ceiling': 'titan_metal',
            },
            'lights': [
                {'type': 'point', 'position': (0, 0, 3), 'color': (0.3, 0.8, 1.0), 'intensity': 1.0, 'attenuation_start': 8, 'attenuation_end': 20}
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Ward_Effect.m2',
                    'positions': [(0, 0, 2)]
                }
            ],
            'boss': {'enabled': False},
            'connects_to': ['storm_core'],
        },
        {
            'id': 'storm_core',
            'name': 'The Storm Core',
            'type': 'circular',
            'radius': 35,
            'height': 25,
            'center': (0, 380, -10),
            'materials': {
                'floor': 'volcanic_rock',
                'wall': 'energy_glow',
                'ceiling': 'stone_dark',
            },
            'lights': [
                {'type': 'point', 'position': (0, 0, 20), 'color': (0.5, 0.3, 1.0), 'intensity': 1.5, 'attenuation_start': 30, 'attenuation_end': 70}
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Containment_Orb.m2',
                    'positions': [(0, 0, 12)]
                }
            ],
            'boss': {
                'enabled': True,
                'entry_id': 90103,  # C'thraxxi Primordial
                'spawn_offset': (0, 0, 0),
            },
            'connects_to': [],
        },
    ],
}
```

---

## 12. Testing Approach

### 12.1 Unit Tests

```python
import unittest

class TestRoomGeometry(unittest.TestCase):
    """Test room geometry generation."""

    def test_box_room_vertices(self):
        room = BoxRoom(10, 20, 8)
        vertices = room.generate_vertices()

        # Should have 8 vertices (4 floor + 4 ceiling)
        self.assertEqual(len(vertices), 8)

        # Check floor vertices at z=0
        for i in range(4):
            self.assertEqual(vertices[i][2], 0.0)

        # Check ceiling vertices at z=height
        for i in range(4, 8):
            self.assertEqual(vertices[i][2], 8.0)

    def test_circular_room_triangles(self):
        room = CircularRoom(15, 10, segments=8)
        triangles = room.generate_triangles()

        # Floor triangles: 8
        # Ceiling triangles: 8
        # Wall triangles: 8 * 2 = 16
        # Total: 32
        self.assertEqual(len(triangles), 32)

    def test_normal_directions(self):
        room = BoxRoom(10, 10, 10)
        normals = room.generate_normals()

        # Floor normals should point up (inward)
        for i in range(4):
            self.assertEqual(normals[i], (0.0, 0.0, 1.0))

        # Ceiling normals should point down (inward)
        for i in range(4, 8):
            self.assertEqual(normals[i], (0.0, 0.0, -1.0))
```

### 12.2 Integration Tests

```python
class TestWMOAssembly(unittest.TestCase):
    """Test WMO file assembly."""

    def test_wmo_root_assembly(self):
        dungeon_def = {
            'name': 'TestDungeon',
            'map_id': 9999,
            'rooms': [
                {
                    'id': 'room1',
                    'name': 'Test Room',
                    'type': 'box',
                    'width': 10,
                    'length': 10,
                    'height': 8,
                    'center': (0, 0, 0),
                    'materials': {'floor': 'floor_tile', 'wall': 'stone_dark', 'ceiling': 'stone_dark'},
                    'lights': [],
                    'doodads': [],
                    'boss': {'enabled': False},
                    'connects_to': [],
                }
            ]
        }

        assembler = WMORootAssembler(dungeon_def)
        wmo_data = assembler.assemble()

        # Check MVER chunk exists
        self.assertTrue(wmo_data.startswith(b'MVER'))

        # Check MOHD chunk exists
        self.assertIn(b'MOHD', wmo_data)

    def test_wmo_group_assembly(self):
        room_def = {
            'id': 'room1',
            'name': 'Test Room',
            'type': 'circular',
            'radius': 15,
            'height': 10,
            'center': (0, 0, 0),
            'materials': {'floor': 'floor_tile', 'wall': 'stone_dark', 'ceiling': 'stone_dark'},
            'lights': [],
            'doodads': [],
            'boss': {'enabled': False},
        }

        material_map = {'floor_tile': 0, 'stone_dark': 1}
        assembler = WMOGroupAssembler(room_def, material_map)
        group_data = assembler.assemble()

        # Check MVER chunk exists
        self.assertTrue(group_data.startswith(b'MVER'))

        # Check MOGP chunk exists
        self.assertIn(b'MOGP', group_data)
```

### 12.3 End-to-End Test

```python
def test_vault_of_storms_build():
    """
    End-to-end test: Build complete Vault of Storms dungeon.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = os.path.join(temp_dir, "output")
        dbc_dir = os.path.join(temp_dir, "DBFilesClient")
        os.makedirs(dbc_dir, exist_ok=True)

        # Create dummy Map.dbc
        with open(os.path.join(dbc_dir, "Map.dbc"), 'wb') as f:
            f.write(b'\x00' * 1024)

        # Build dungeon
        result = build_dungeon(VAULT_OF_STORMS, output_dir, dbc_dir)

        # Check WMO files exist
        assert os.path.exists(result['wmo_files'][0])  # Root WMO
        assert len(result['wmo_files']) == 10  # 1 root + 9 groups

        # Check coordinate metadata
        assert 'rooms' in result['coordinate_metadata']
        assert len(result['coordinate_metadata']['rooms']) == 9

        print("✓ End-to-end test passed")
```

---

## 13. Implementation Checklist

### Phase 1: Geometry Primitives (Week 1)
- [ ] Implement BoxRoom class with vertex/normal/UV/triangle generation
- [ ] Implement CircularRoom class
- [ ] Implement Corridor class
- [ ] Implement SpiralRamp class
- [ ] Implement ChamberRoom class
- [ ] Write unit tests for geometry generation
- [ ] Verify normal directions (inward-facing)
- [ ] Test collision mesh generation

### Phase 2: Material System (Week 1)
- [ ] Define MaterialPreset with 6 material presets
- [ ] Map presets to BLP texture paths
- [ ] Implement FaceMaterialAssignment
- [ ] Test material index resolution

### Phase 3: WMO Assembly (Week 2)
- [ ] Implement WMORootAssembler
- [ ] Write all root chunks (MOHD, MOTX, MOMT, MOGN, MOGI, MOSB, MOPV, MOPT, MOPR, MOLT, MODS, MODN, MODD)
- [ ] Implement WMOGroupAssembler
- [ ] Write all group chunks (MOGP, MOPY, MOVI, MOVT, MONR, MOTV, MOBA)
- [ ] Test WMO file output with hex editor
- [ ] Validate chunk structure

### Phase 4: Portal System (Week 2)
- [ ] Implement PortalGenerator
- [ ] Generate doorway portals between rooms
- [ ] Calculate portal vertices and planes
- [ ] Write MOPV/MOPT/MOPR chunks
- [ ] Test portal culling (manual verification in-game)

### Phase 5: Lighting & Doodads (Week 2)
- [ ] Implement LightGenerator
- [ ] Auto-generate lights based on room type
- [ ] Implement DoodadPlacer
- [ ] Write MOLT/MODD/MODN chunks
- [ ] Test in-game lighting

### Phase 6: Collision & BSP (Week 3)
- [ ] Implement BSPTreeBuilder
- [ ] Generate BSP trees for collision
- [ ] Write MOBN/MOBR chunks
- [ ] Test collision (player can walk on surfaces)

### Phase 7: Connection System (Week 3)
- [ ] Implement ConnectionResolver
- [ ] Auto-generate corridors between rooms
- [ ] Align doorway positions
- [ ] Test room connectivity

### Phase 8: Vault of Storms (Week 3)
- [ ] Define complete VAULT_OF_STORMS definition
- [ ] Build dungeon with build_dungeon()
- [ ] Verify all 9 rooms generate correctly
- [ ] Test in-game (load WMO, check collisions, lighting, portals)

### Phase 9: Integration (Week 4)
- [ ] Integrate with dbc_injector for Map.dbc registration
- [ ] Export spawn coordinates for SQL generator
- [ ] Write integration tests
- [ ] Document high-level API

### Phase 10: Testing & Polish (Week 4)
- [ ] Run all unit tests
- [ ] Run integration tests
- [ ] Run end-to-end test with Vault of Storms
- [ ] Load dungeon in WoW client and verify playability
- [ ] Fix any rendering/collision/portal issues
- [ ] Write user documentation

---

## 14. Conclusion

This plan implements a **fully automated dungeon builder** that generates complete, playable WMO dungeon interiors from high-level room definitions. The module:

1. **Generates actual geometry**: Box rooms, circular rooms, corridors, spiral ramps, polygonal chambers
2. **Handles materials**: Predefined presets mapped to WoW BLP textures
3. **Creates portal system**: Doorway portals for occlusion culling
4. **Implements lighting**: Per-room light definitions with auto-placement
5. **Places doodads**: M2 model placement within rooms
6. **Builds collision**: BSP trees for collision detection
7. **Assembles WMO files**: Complete root + group WMO files ready for MPQ
8. **Exports coordinates**: Boss/trash/door positions for SQL generation
9. **Registers in DBC**: Map.dbc integration

**Ready for Implementation:** This approach enables TODO 1.2 (Build the Vault of Storms Instance Map) with COMPLETE automation—no manual WMO creation required. The agent generates geometry, the player loads the dungeon in-game and plays it immediately.
