"""
Dungeon Builder - WMO dungeon geometry generator for WoW WotLK 3.3.5a.

Generates complete WMO (World Map Object) dungeon files from high-level room
definitions. Produces actual geometry, materials, lighting, portals, collision,
and spawn coordinates -- ready-to-use dungeon files for MPQ packing.

WMO file structure:
  Root file (.wmo): Contains global dungeon data (materials, portals, lights,
      doodads, group info). Chunks: MVER, MOHD, MOTX, MOMT, MOGN, MOGI,
      MOSB, MOPV, MOPT, MOPR, MOLT, MODS, MODN, MODD.
  Group files (_NNN.wmo): One per room/group. Contains geometry and collision.
      Chunks: MVER, MOGP (with sub-chunks: MOPY, MOVI, MOVT, MONR, MOTV,
      MOBA, MOBN, MOBR).

All chunk magics are stored as-is (NOT reversed, unlike ADT files).
All multi-byte integers are little-endian.

Target build: WotLK 3.3.5a (build 12340)
"""

import struct
import math
import os
import json
import logging
from io import BytesIO

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WMO version constant
# ---------------------------------------------------------------------------
_WMO_VERSION = 17

# ---------------------------------------------------------------------------
# Chunk header size
# ---------------------------------------------------------------------------
_CHUNK_HEADER_SIZE = 8  # 4-byte magic + 4-byte uint32 size

# ---------------------------------------------------------------------------
# MOGP header size (fixed)
# ---------------------------------------------------------------------------
_MOGP_HEADER_SIZE = 68


# ===========================================================================
# Low-level write helpers
# ===========================================================================

def _write_chunk(buf, magic, data):
    """Write a chunk: 4-byte magic + uint32 data size + data bytes."""
    buf.write(magic)
    buf.write(struct.pack('<I', len(data)))
    buf.write(data)


def _pack_chunk(magic, data):
    """Return bytes for a complete chunk (header + data)."""
    return magic + struct.pack('<I', len(data)) + data


# ===========================================================================
# Room Primitives - Geometry Generators
# ===========================================================================

class BoxRoom(object):
    """
    Generate rectangular room geometry.

    Produces: floor, 4 walls, ceiling.
    All normals face INWARD (toward room center).
    """

    def __init__(self, width, length, height):
        """
        Args:
            width: Room width (X axis) in yards.
            length: Room length (Y axis) in yards.
            height: Room height (Z axis) in yards.
        """
        self.width = width
        self.length = length
        self.height = height

    def generate_vertices(self):
        """
        Generate vertices for box room.

        Returns:
            List of (x, y, z) vertex positions.

        Vertex order:
            Floor: 0-3 (bottom corners, CCW from -x,-y)
            Ceiling: 4-7 (top corners, CCW from -x,-y)
        """
        w = self.width / 2.0
        l = self.length / 2.0
        h = self.height

        vertices = [
            # Floor vertices (z=0)
            (-w, -l, 0.0),   # 0: bottom-left-front
            ( w, -l, 0.0),   # 1: bottom-right-front
            ( w,  l, 0.0),   # 2: bottom-right-back
            (-w,  l, 0.0),   # 3: bottom-left-back
            # Ceiling vertices (z=height)
            (-w, -l, h),     # 4: top-left-front
            ( w, -l, h),     # 5: top-right-front
            ( w,  l, h),     # 6: top-right-back
            (-w,  l, h),     # 7: top-left-back
        ]

        return vertices

    def generate_triangles(self):
        """
        Generate triangle indices.

        Returns:
            List of (v0, v1, v2) triangle indices.

        Triangle winding: CCW when viewed from INSIDE room (inward-facing normals).
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

    def generate_normals(self):
        """
        Generate per-vertex normals (inward-facing).

        Returns:
            List of (nx, ny, nz) normal vectors.
        """
        normals = [
            # Floor vertices (normals point up)
            (0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
            (0.0, 0.0, 1.0),
            # Ceiling vertices (normals point down)
            (0.0, 0.0, -1.0),
            (0.0, 0.0, -1.0),
            (0.0, 0.0, -1.0),
            (0.0, 0.0, -1.0),
        ]

        return normals

    def generate_uvs(self):
        """
        Generate texture coordinates.

        Returns:
            List of (u, v) texture coordinates.
            UV mapping: 1 unit = 1 yard.
        """
        w = self.width
        l = self.length

        uvs = [
            # Floor vertices
            (0.0, 0.0),
            (w, 0.0),
            (w, l),
            (0.0, l),
            # Ceiling vertices
            (0.0, 0.0),
            (w, 0.0),
            (w, l),
            (0.0, l),
        ]

        return uvs

    def generate_face_materials(self):
        """
        Generate material assignments per triangle.

        Returns:
            List of material zone names (one per triangle).
        """
        materials = [
            'floor', 'floor',        # Floor triangles
            'ceiling', 'ceiling',    # Ceiling triangles
            'wall', 'wall',          # Wall -X
            'wall', 'wall',          # Wall +X
            'wall', 'wall',          # Wall -Y
            'wall', 'wall',          # Wall +Y
        ]

        return materials

    def generate_collision_mesh(self):
        """
        Generate simplified collision mesh.

        Returns:
            (vertices, triangles) for collision BSP tree.
        """
        return (self.generate_vertices(), self.generate_triangles())


class CircularRoom(object):
    """
    Generate circular room geometry (cylinder).

    Produces: floor disc, cylindrical wall, ceiling disc.
    All normals face INWARD.
    """

    def __init__(self, radius, height, segments=24):
        """
        Args:
            radius: Room radius in yards.
            height: Room height in yards.
            segments: Number of segments around circle (default 24).
        """
        self.radius = radius
        self.height = height
        self.segments = segments

    def generate_vertices(self):
        """
        Generate vertices for circular room.

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
            angle = (2.0 * math.pi * i) / self.segments
            x = self.radius * math.cos(angle)
            y = self.radius * math.sin(angle)
            vertices.append((x, y, 0.0))

        # Ceiling center
        vertices.append((0.0, 0.0, self.height))

        # Ceiling perimeter
        for i in range(self.segments):
            angle = (2.0 * math.pi * i) / self.segments
            x = self.radius * math.cos(angle)
            y = self.radius * math.sin(angle)
            vertices.append((x, y, self.height))

        return vertices

    def generate_triangles(self):
        """Generate triangle indices (inward-facing)."""
        triangles = []

        # Floor triangles (fan from center)
        for i in range(self.segments):
            v0 = 0  # Floor center
            v1 = 1 + i
            v2 = 1 + ((i + 1) % self.segments)
            triangles.append((v0, v2, v1))  # Reversed for inward normal

        # Ceiling triangles (fan from center)
        ceiling_center = self.segments + 1
        for i in range(self.segments):
            v0 = ceiling_center
            v1 = ceiling_center + 1 + i
            v2 = ceiling_center + 1 + ((i + 1) % self.segments)
            triangles.append((v0, v1, v2))

        # Wall triangles (quad strips)
        for i in range(self.segments):
            floor_v1 = 1 + i
            floor_v2 = 1 + ((i + 1) % self.segments)
            ceiling_v1 = ceiling_center + 1 + i
            ceiling_v2 = ceiling_center + 1 + ((i + 1) % self.segments)

            triangles.append((floor_v1, ceiling_v1, floor_v2))
            triangles.append((floor_v2, ceiling_v1, ceiling_v2))

        return triangles

    def generate_normals(self):
        """Generate per-vertex normals (inward-facing)."""
        normals = []

        # Floor center normal (up)
        normals.append((0.0, 0.0, 1.0))

        # Floor perimeter normals (up)
        for _i in range(self.segments):
            normals.append((0.0, 0.0, 1.0))

        # Ceiling center normal (down)
        normals.append((0.0, 0.0, -1.0))

        # Ceiling perimeter normals (down)
        for _i in range(self.segments):
            normals.append((0.0, 0.0, -1.0))

        return normals

    def generate_uvs(self):
        """Generate texture coordinates."""
        uvs = []

        # Floor center
        uvs.append((self.radius, self.radius))

        # Floor perimeter
        for i in range(self.segments):
            angle = (2.0 * math.pi * i) / self.segments
            u = self.radius + self.radius * math.cos(angle)
            v = self.radius + self.radius * math.sin(angle)
            uvs.append((u, v))

        # Ceiling center
        uvs.append((self.radius, self.radius))

        # Ceiling perimeter
        for i in range(self.segments):
            angle = (2.0 * math.pi * i) / self.segments
            u = self.radius + self.radius * math.cos(angle)
            v = self.radius + self.radius * math.sin(angle)
            uvs.append((u, v))

        return uvs

    def generate_face_materials(self):
        """Generate material assignments per triangle."""
        materials = []

        # Floor triangles
        for _i in range(self.segments):
            materials.append('floor')

        # Ceiling triangles
        for _i in range(self.segments):
            materials.append('ceiling')

        # Wall triangles (2 per segment)
        for _i in range(self.segments * 2):
            materials.append('wall')

        return materials

    def generate_collision_mesh(self):
        """Generate simplified collision mesh (fewer segments)."""
        collision_room = CircularRoom(self.radius, self.height, segments=8)
        return (collision_room.generate_vertices(), collision_room.generate_triangles())


class Corridor(BoxRoom):
    """
    Corridor is a specialized BoxRoom (narrow and long).
    """

    def __init__(self, width, length, height):
        """
        Args:
            width: Corridor width (narrow dimension).
            length: Corridor length (long dimension).
            height: Corridor height.
        """
        super(Corridor, self).__init__(width, length, height)


class SpiralRamp(object):
    """
    Generate spiral ramp geometry (helical descent/ascent).
    """

    def __init__(self, radius, height, turns, segments=48):
        """
        Args:
            radius: Spiral radius in yards.
            height: Total height change in yards (negative for descent).
            turns: Number of complete rotations.
            segments: Number of segments per turn.
        """
        self.radius = radius
        self.height = height
        self.turns = turns
        self.segments = segments
        self.width = 3.0  # Ramp width (fixed)

    def generate_vertices(self):
        """Generate vertices for spiral ramp."""
        vertices = []
        total_segments = int(self.segments * self.turns)

        for i in range(total_segments + 1):
            t = float(i) / total_segments
            angle = 2.0 * math.pi * self.turns * t
            z = self.height * t

            # Inner edge
            x_inner = (self.radius - self.width / 2.0) * math.cos(angle)
            y_inner = (self.radius - self.width / 2.0) * math.sin(angle)
            vertices.append((x_inner, y_inner, z))

            # Outer edge
            x_outer = (self.radius + self.width / 2.0) * math.cos(angle)
            y_outer = (self.radius + self.width / 2.0) * math.sin(angle)
            vertices.append((x_outer, y_outer, z))

        return vertices

    def generate_triangles(self):
        """Generate triangle indices for ramp surface."""
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

    def generate_normals(self):
        """Generate per-vertex normals (facing up)."""
        normals = []
        total_segments = int(self.segments * self.turns)

        for _i in range(total_segments + 1):
            normals.append((0.0, 0.0, 1.0))
            normals.append((0.0, 0.0, 1.0))

        return normals

    def generate_uvs(self):
        """Generate texture coordinates."""
        uvs = []
        total_segments = int(self.segments * self.turns)

        for i in range(total_segments + 1):
            t = float(i) / total_segments
            v_coord = t * self.radius * 2.0 * math.pi * self.turns
            uvs.append((0.0, v_coord))
            uvs.append((self.width, v_coord))

        return uvs

    def generate_face_materials(self):
        """Generate material assignments per triangle."""
        total_segments = int(self.segments * self.turns)
        return ['floor'] * (total_segments * 2)

    def generate_collision_mesh(self):
        """Generate simplified collision mesh."""
        collision_ramp = SpiralRamp(self.radius, self.height, self.turns, segments=12)
        return (collision_ramp.generate_vertices(), collision_ramp.generate_triangles())


class ChamberRoom(object):
    """
    Generate polygonal room (hexagon, octagon, etc).
    """

    def __init__(self, radius, height, sides):
        """
        Args:
            radius: Distance from center to vertex.
            height: Room height.
            sides: Number of sides (6=hex, 8=oct).
        """
        self.radius = radius
        self.height = height
        self.sides = sides

    def generate_vertices(self):
        """Generate vertices for polygonal room."""
        vertices = []

        # Floor center
        vertices.append((0.0, 0.0, 0.0))

        # Floor perimeter
        for i in range(self.sides):
            angle = (2.0 * math.pi * i) / self.sides
            x = self.radius * math.cos(angle)
            y = self.radius * math.sin(angle)
            vertices.append((x, y, 0.0))

        # Ceiling center
        vertices.append((0.0, 0.0, self.height))

        # Ceiling perimeter
        for i in range(self.sides):
            angle = (2.0 * math.pi * i) / self.sides
            x = self.radius * math.cos(angle)
            y = self.radius * math.sin(angle)
            vertices.append((x, y, self.height))

        return vertices

    def generate_triangles(self):
        """Generate triangle indices."""
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

    def generate_normals(self):
        """Generate per-vertex normals."""
        normals = []

        # Floor normals (up)
        normals.append((0.0, 0.0, 1.0))
        for _i in range(self.sides):
            normals.append((0.0, 0.0, 1.0))

        # Ceiling normals (down)
        normals.append((0.0, 0.0, -1.0))
        for _i in range(self.sides):
            normals.append((0.0, 0.0, -1.0))

        return normals

    def generate_uvs(self):
        """Generate texture coordinates."""
        uvs = []

        # Floor center
        uvs.append((self.radius, self.radius))

        # Floor perimeter
        for i in range(self.sides):
            angle = (2.0 * math.pi * i) / self.sides
            u = self.radius + self.radius * math.cos(angle)
            v = self.radius + self.radius * math.sin(angle)
            uvs.append((u, v))

        # Ceiling center
        uvs.append((self.radius, self.radius))

        # Ceiling perimeter
        for i in range(self.sides):
            angle = (2.0 * math.pi * i) / self.sides
            u = self.radius + self.radius * math.cos(angle)
            v = self.radius + self.radius * math.sin(angle)
            uvs.append((u, v))

        return uvs

    def generate_face_materials(self):
        """Generate material assignments per triangle."""
        materials = []

        # Floor triangles
        for _i in range(self.sides):
            materials.append('floor')

        # Ceiling triangles
        for _i in range(self.sides):
            materials.append('ceiling')

        # Wall triangles (2 per side)
        for _i in range(self.sides * 2):
            materials.append('wall')

        return materials

    def generate_collision_mesh(self):
        """Generate collision mesh (same as visual for polygons)."""
        return (self.generate_vertices(), self.generate_triangles())


# ===========================================================================
# Material System
# ===========================================================================

class MaterialPreset(object):
    """
    Predefined material presets mapping to WoW BLP textures.
    """

    PRESETS = {
        'titan_metal': {
            'texture': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Metal_Floor.blp',
            'shader': 0,        # Diffuse
            'blend_mode': 0,    # Opaque
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
            'shader': 1,        # Specular
            'blend_mode': 1,    # AlphaKey
        },
        'floor_tile': {
            'texture': 'Dungeons\\Textures\\Utgarde\\UtgardeFloor01.blp',
            'shader': 0,
            'blend_mode': 0,
        },
    }

    @staticmethod
    def get_material(preset_name):
        """
        Get material definition by preset name.

        Args:
            preset_name: Material preset name.

        Returns:
            Material definition dict.

        Raises:
            ValueError: If preset name is unknown.
        """
        if preset_name not in MaterialPreset.PRESETS:
            raise ValueError("Unknown material preset: {}".format(preset_name))

        return MaterialPreset.PRESETS[preset_name]


class FaceMaterialAssignment(object):
    """
    Assign materials to room faces (floor, walls, ceiling).
    """

    @staticmethod
    def assign_room_materials(room_def, face_materials):
        """
        Assign material indices to room triangles.

        Args:
            room_def: Room definition with material assignments.
            face_materials: List of face types ('floor', 'wall', 'ceiling')
                per triangle.

        Returns:
            (triangle_materials, unique_materials):
                triangle_materials: List of material indices (int) per triangle.
                unique_materials: Ordered list of unique material preset names.
        """
        material_map = room_def.get('materials', {
            'floor': 'floor_tile',
            'wall': 'stone_dark',
            'ceiling': 'stone_dark',
        })

        # Build ordered unique material list (deterministic order)
        unique_materials = []
        seen = set()
        for face_type in ['floor', 'wall', 'ceiling']:
            mat = material_map.get(face_type, 'stone_dark')
            if mat not in seen:
                unique_materials.append(mat)
                seen.add(mat)

        material_indices = {mat: idx for idx, mat in enumerate(unique_materials)}

        # Assign material index to each triangle
        triangle_materials = []
        for face_type in face_materials:
            material_preset = material_map.get(face_type, 'stone_dark')
            material_idx = material_indices[material_preset]
            triangle_materials.append(material_idx)

        return triangle_materials, unique_materials


# ===========================================================================
# Portal System
# ===========================================================================

class PortalGenerator(object):
    """
    Generate portal definitions for room connections (for occlusion culling).
    """

    @staticmethod
    def generate_doorway_portal(room1_def, room2_def, connection):
        """
        Generate portal at doorway between two rooms.

        Args:
            room1_def: First room definition.
            room2_def: Second room definition.
            connection: Connection definition with doorway position.

        Returns:
            Portal definition dict with vertices and plane.
        """
        doorway_pos = connection['position']
        doorway_width = connection.get('width', 4.0)
        doorway_height = connection.get('height', 3.0)
        doorway_orientation = connection.get('orientation', 0.0)

        cos_angle = math.cos(doorway_orientation)
        sin_angle = math.sin(doorway_orientation)
        half_width = doorway_width / 2.0

        portal_vertices = [
            (
                doorway_pos[0] - half_width * sin_angle,
                doorway_pos[1] + half_width * cos_angle,
                doorway_pos[2]
            ),
            (
                doorway_pos[0] + half_width * sin_angle,
                doorway_pos[1] - half_width * cos_angle,
                doorway_pos[2]
            ),
            (
                doorway_pos[0] + half_width * sin_angle,
                doorway_pos[1] - half_width * cos_angle,
                doorway_pos[2] + doorway_height
            ),
            (
                doorway_pos[0] - half_width * sin_angle,
                doorway_pos[1] + half_width * cos_angle,
                doorway_pos[2] + doorway_height
            ),
        ]

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


# ===========================================================================
# Connection System
# ===========================================================================

class ConnectionResolver(object):
    """
    Resolve room connections and auto-generate connecting corridors.
    """

    @staticmethod
    def connect_rooms(room1_def, room2_def):
        """
        Connect two rooms with auto-generated corridor.

        Args:
            room1_def: First room definition.
            room2_def: Second room definition.

        Returns:
            Connection definition with corridor geometry and doorway positions.
        """
        c1 = room1_def['center']
        c2 = room2_def['center']

        dx = c2[0] - c1[0]
        dy = c2[1] - c1[1]
        dz = c2[2] - c1[2]

        distance_2d = math.sqrt(dx ** 2 + dy ** 2)
        angle = math.atan2(dy, dx)

        corridor_width = 8.0
        corridor_height = 6.0

        r1_radius = ConnectionResolver._get_room_radius(room1_def)
        r2_radius = ConnectionResolver._get_room_radius(room2_def)

        corridor_length = max(1.0, distance_2d - r1_radius - r2_radius)

        corridor_start = (
            c1[0] + r1_radius * math.cos(angle),
            c1[1] + r1_radius * math.sin(angle),
            c1[2]
        )

        corridor_center = (
            corridor_start[0] + (corridor_length / 2.0) * math.cos(angle),
            corridor_start[1] + (corridor_length / 2.0) * math.sin(angle),
            corridor_start[2] + dz / 2.0
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
    def _get_room_radius(room_def):
        """Get effective radius of room (for connection calculations)."""
        room_type = room_def['type']

        if room_type == 'circular':
            return room_def['radius']
        elif room_type == 'box' or room_type == 'corridor':
            return (room_def['width'] + room_def['length']) / 4.0
        elif room_type == 'chamber':
            return room_def['radius']
        elif room_type == 'spiral':
            return room_def['radius']
        elif room_type == 'raw_mesh':
            bounds = room_def.get('bounds')
            if bounds:
                dx = bounds['max'][0] - bounds['min'][0]
                dy = bounds['max'][1] - bounds['min'][1]
                return (dx + dy) / 4.0
            return 10.0
        else:
            return 10.0


# ===========================================================================
# Lighting System
# ===========================================================================

class LightGenerator(object):
    """
    Generate lighting definitions for rooms.
    """

    @staticmethod
    def generate_room_lights(room_def):
        """
        Generate light definitions based on room type and size.

        Args:
            room_def: Room definition.

        Returns:
            List of light definitions.
        """
        lights = []
        room_type = room_def['type']
        center = room_def['center']

        light_config = room_def.get('lights', [])

        if not light_config:
            # Auto-generate default lighting
            if room_type == 'circular' or room_type == 'chamber':
                lights.append({
                    'type': 'point',
                    'position': (center[0], center[1],
                                 center[2] + room_def['height'] * 0.7),
                    'color': (1.0, 1.0, 1.0),
                    'intensity': 1.0,
                    'attenuation_start': room_def.get('radius', 15.0) * 0.5,
                    'attenuation_end': room_def.get('radius', 15.0) * 1.5,
                })
            elif room_type == 'box' or room_type == 'corridor':
                w = room_def['width'] / 3.0
                l = room_def['length'] / 3.0
                h = room_def['height'] * 0.7

                for x_offset in [-w, w]:
                    for y_offset in [-l, l]:
                        lights.append({
                            'type': 'point',
                            'position': (center[0] + x_offset,
                                         center[1] + y_offset,
                                         center[2] + h),
                            'color': (1.0, 1.0, 1.0),
                            'intensity': 0.7,
                            'attenuation_start': 10.0,
                            'attenuation_end': 25.0,
                        })
            elif room_type == 'spiral':
                lights.append({
                    'type': 'point',
                    'position': (center[0], center[1],
                                 center[2] + abs(room_def['height']) * 0.5),
                    'color': (1.0, 1.0, 1.0),
                    'intensity': 0.8,
                    'attenuation_start': 12.0,
                    'attenuation_end': 30.0,
                })
            elif room_type == 'raw_mesh':
                bounds = room_def.get('bounds')
                if bounds:
                    mid_z = (bounds['min'][2] + bounds['max'][2]) / 2.0
                    height_range = bounds['max'][2] - bounds['min'][2]
                else:
                    mid_z = center[2] + 5.0
                    height_range = 10.0
                lights.append({
                    'type': 'point',
                    'position': (center[0], center[1],
                                 mid_z + height_range * 0.3),
                    'color': (1.0, 1.0, 1.0),
                    'intensity': 1.0,
                    'attenuation_start': 15.0,
                    'attenuation_end': 30.0,
                })
        else:
            # Use custom light configuration
            for light_def in light_config:
                pos = light_def.get('position', (0, 0, 0))
                if light_def.get('relative', True):
                    pos = (center[0] + pos[0],
                           center[1] + pos[1],
                           center[2] + pos[2])

                lights.append({
                    'type': light_def.get('type', 'point'),
                    'position': pos,
                    'color': light_def.get('color', (1.0, 1.0, 1.0)),
                    'intensity': light_def.get('intensity', 1.0),
                    'attenuation_start': light_def.get('attenuation_start', 15.0),
                    'attenuation_end': light_def.get('attenuation_end', 30.0),
                })

        return lights


# ===========================================================================
# Doodad System
# ===========================================================================

class DoodadPlacer(object):
    """
    Place doodads (M2 models) within rooms.
    """

    @staticmethod
    def place_doodads(room_def):
        """
        Place doodads in room based on room definition.

        Args:
            room_def: Room definition with doodad placements.

        Returns:
            List of doodad placement definitions.
        """
        doodads = []
        center = room_def['center']

        doodad_config = room_def.get('doodads', [])

        for doodad_def in doodad_config:
            model_path = doodad_def['model']
            positions = doodad_def.get('positions', [])

            for pos in positions:
                world_pos = (center[0] + pos[0],
                             center[1] + pos[1],
                             center[2] + pos[2])

                doodads.append({
                    'model': model_path,
                    'position': world_pos,
                    'rotation': doodad_def.get('rotation', (0, 0, 0)),
                    'scale': doodad_def.get('scale', 1.0),
                    'doodad_set': doodad_def.get('doodad_set', 0),
                })

        return doodads


# ===========================================================================
# BSP Tree Generator
# ===========================================================================

class BSPTreeBuilder(object):
    """
    Build BSP tree for collision detection.

    Generates MOBN (BSP nodes) and MOBR (face indices) data for WMO groups.
    """

    @staticmethod
    def build_bsp_tree(vertices, triangles, max_depth=10):
        """
        Build BSP tree from triangle mesh.

        Args:
            vertices: List of (x, y, z) vertex positions.
            triangles: List of (v0, v1, v2) triangle indices.
            max_depth: Maximum tree depth.

        Returns:
            (bsp_nodes, face_indices):
                bsp_nodes: List of BSP node dicts.
                face_indices: List of triangle indices referenced by leaf nodes.
        """
        # Build polygon list with planes
        polygons = []
        for tri_idx, tri in enumerate(triangles):
            v0 = vertices[tri[0]]
            v1 = vertices[tri[1]]
            v2 = vertices[tri[2]]

            # Calculate polygon center
            cx = (v0[0] + v1[0] + v2[0]) / 3.0
            cy = (v0[1] + v1[1] + v2[1]) / 3.0
            cz = (v0[2] + v1[2] + v2[2]) / 3.0

            # Calculate face normal
            e1 = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
            e2 = (v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2])
            nx = e1[1] * e2[2] - e1[2] * e2[1]
            ny = e1[2] * e2[0] - e1[0] * e2[2]
            nz = e1[0] * e2[1] - e1[1] * e2[0]

            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            if length > 0.0:
                nx /= length
                ny /= length
                nz /= length

            plane_dist = -(nx * v0[0] + ny * v0[1] + nz * v0[2])

            polygons.append({
                'index': tri_idx,
                'center': (cx, cy, cz),
                'plane': {
                    'normal': (nx, ny, nz),
                    'distance': plane_dist,
                },
            })

        bsp_nodes = []
        face_indices = []
        BSPTreeBuilder._build_node(polygons, bsp_nodes, face_indices,
                                   max_depth, 0)

        return bsp_nodes, face_indices

    @staticmethod
    def _build_node(polygons, bsp_nodes, face_indices, max_depth, depth):
        """
        Recursively build BSP tree node.

        Args:
            polygons: List of polygon dicts for this node.
            bsp_nodes: Accumulator list for BSP nodes.
            face_indices: Accumulator list for face indices.
            max_depth: Maximum tree depth.
            depth: Current recursion depth.

        Returns:
            Index of this node in bsp_nodes list.
        """
        node_idx = len(bsp_nodes)

        if not polygons or depth >= max_depth or len(polygons) <= 4:
            # Leaf node
            face_start = len(face_indices)
            for poly in polygons:
                face_indices.append(poly['index'])

            bsp_nodes.append({
                'flags': 0x04,  # Leaf node flag
                'neg_child': -1,
                'pos_child': -1,
                'num_faces': len(polygons),
                'first_face': face_start,
                'plane_dist': 0.0,
            })
            return node_idx

        # Select splitting plane from first polygon
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
            else:
                # Spanning: add to both sides
                front_polygons.append(poly)
                back_polygons.append(poly)

        # Add placeholder node
        bsp_nodes.append({
            'flags': 0x00,
            'neg_child': -1,
            'pos_child': -1,
            'num_faces': 0,
            'first_face': 0,
            'plane_dist': split_plane['distance'],
        })

        # Build children
        if back_polygons:
            neg_idx = BSPTreeBuilder._build_node(back_polygons, bsp_nodes,
                                                  face_indices, max_depth,
                                                  depth + 1)
            bsp_nodes[node_idx]['neg_child'] = neg_idx

        if front_polygons:
            pos_idx = BSPTreeBuilder._build_node(front_polygons, bsp_nodes,
                                                  face_indices, max_depth,
                                                  depth + 1)
            bsp_nodes[node_idx]['pos_child'] = pos_idx

        return node_idx

    @staticmethod
    def _classify_polygon(poly, plane):
        """
        Classify polygon relative to plane.

        Returns:
            'front', 'back', or 'spanning'.
        """
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

    @staticmethod
    def pack_bsp_nodes(bsp_nodes):
        """
        Pack BSP nodes into binary MOBN data.

        Format per node (0x10 = 16 bytes):
            uint16 flags
            int16 negChild
            int16 posChild
            uint16 nFaces
            uint32 faceStart
            float planeDist

        Returns:
            bytes: MOBN chunk data.
        """
        buf = BytesIO()

        for node in bsp_nodes:
            flags = node['flags']
            neg = node['neg_child'] if node['neg_child'] >= 0 else -1
            pos = node['pos_child'] if node['pos_child'] >= 0 else -1
            num_faces = node['num_faces']
            first_face = node['first_face']
            plane_dist = node['plane_dist']

            buf.write(struct.pack('<hhhHIf',
                                  flags, neg, pos,
                                  num_faces, first_face, plane_dist))

        return buf.getvalue()

    @staticmethod
    def pack_face_indices(face_indices):
        """
        Pack face indices into binary MOBR data.

        Format: Array of uint16 (triangle indices).

        Returns:
            bytes: MOBR chunk data.
        """
        buf = BytesIO()
        for idx in face_indices:
            buf.write(struct.pack('<H', idx))
        return buf.getvalue()


# ===========================================================================
# WMO Root File Assembler
# ===========================================================================

class WMORootAssembler(object):
    """
    Assemble WMO root file from dungeon definition.
    """

    def __init__(self, dungeon_def):
        self.dungeon_def = dungeon_def
        self.materials = []      # Ordered list of material preset names
        self.groups = []         # List of room definitions
        self.portals = []        # List of portal definitions
        self.lights = []         # List of light definitions
        self.doodads = []        # List of doodad placements

    def assemble(self):
        """
        Assemble complete WMO root file.

        Returns:
            Binary WMO root file data (bytes).
        """
        output = BytesIO()

        # Write MVER chunk (version = 17)
        _write_chunk(output, b'MVER', struct.pack('<I', _WMO_VERSION))

        # Collect all materials, groups, portals, lights, doodads from rooms
        self._collect_components()

        # Write all root-level chunks
        self._write_mohd_chunk(output)
        self._write_motx_chunk(output)
        self._write_momt_chunk(output)
        self._write_mogn_chunk(output)
        self._write_mogi_chunk(output)
        self._write_mosb_chunk(output)
        self._write_mopv_chunk(output)
        self._write_mopt_chunk(output)
        self._write_mopr_chunk(output)
        self._write_molt_chunk(output)
        self._write_mods_chunk(output)
        self._write_modn_chunk(output)
        self._write_modd_chunk(output)

        return output.getvalue()

    def _collect_components(self):
        """Collect all materials, groups, portals, lights, doodads from rooms."""
        # Collect materials from all rooms (deterministic ordering)
        material_set = []
        seen_materials = set()
        for room in self.dungeon_def['rooms']:
            room_materials = room.get('materials', {})
            for face_type in ['floor', 'wall', 'ceiling']:
                mat = room_materials.get(face_type)
                if mat and mat not in seen_materials:
                    material_set.append(mat)
                    seen_materials.add(mat)

        self.materials = material_set

        # Each room becomes one WMO group
        self.groups = self.dungeon_def['rooms']

        # Collect portals from connections
        self.portals = self.dungeon_def.get('portals', [])

        # Collect lights from all rooms
        self.lights = []
        for room in self.dungeon_def['rooms']:
            room_lights = LightGenerator.generate_room_lights(room)
            self.lights.extend(room_lights)

        # Collect doodads from all rooms
        self.doodads = []
        for room in self.dungeon_def['rooms']:
            room_doodads = DoodadPlacer.place_doodads(room)
            self.doodads.extend(room_doodads)

    def _get_bounding_box(self):
        """Calculate bounding box from all rooms."""
        if not self.groups:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

        all_centers = [room['center'] for room in self.groups]
        min_x = min(c[0] for c in all_centers) - 50.0
        min_y = min(c[1] for c in all_centers) - 50.0
        min_z = min(c[2] for c in all_centers) - 10.0
        max_x = max(c[0] for c in all_centers) + 50.0
        max_y = max(c[1] for c in all_centers) + 50.0
        max_z = max(c[2] for c in all_centers) + 30.0

        return (min_x, min_y, min_z), (max_x, max_y, max_z)

    def _write_mohd_chunk(self, output):
        """
        Write MOHD chunk (WMO header).

        Format (64 bytes):
            uint32 nMaterials
            uint32 nGroups
            uint32 nPortals
            uint32 nLights
            uint32 nModels (unused, always 0)
            uint32 nDoodads
            uint32 nSets
            uint32 ambientColor (BGRA)
            uint32 wmoID
            float[3] bounding_box_min
            float[3] bounding_box_max
            uint16 flags
            uint16 numLod (unused)
        """
        bbox_min, bbox_max = self._get_bounding_box()

        data = BytesIO()
        # nMaterials, nGroups, nPortals, nLights
        data.write(struct.pack('<IIII',
                               len(self.materials),
                               len(self.groups),
                               len(self.portals),
                               len(self.lights)))
        # nModels (unused)
        data.write(struct.pack('<I', 0))
        # nDoodads
        data.write(struct.pack('<I', len(self.doodads)))
        # nSets (always at least 1)
        data.write(struct.pack('<I', 1))
        # ambientColor (BGRA)
        data.write(struct.pack('<I', 0x00000000))
        # wmoID
        data.write(struct.pack('<I', self.dungeon_def.get('map_id', 0)))
        # bounding box min
        data.write(struct.pack('<fff', bbox_min[0], bbox_min[1], bbox_min[2]))
        # bounding box max
        data.write(struct.pack('<fff', bbox_max[0], bbox_max[1], bbox_max[2]))
        # flags (0x0001 = do not attenuate vertices based on distance)
        # numLod (unused)
        data.write(struct.pack('<HH', 0x0001, 0))

        _write_chunk(output, b'MOHD', data.getvalue())

    def _write_motx_chunk(self, output):
        """
        Write MOTX chunk (texture file paths).
        Null-terminated strings concatenated.
        """
        buf = BytesIO()

        for material_name in self.materials:
            material = MaterialPreset.get_material(material_name)
            texture_path = material['texture']
            buf.write(texture_path.encode('utf-8') + b'\x00')

        _write_chunk(output, b'MOTX', buf.getvalue())

    def _write_momt_chunk(self, output):
        """
        Write MOMT chunk (material definitions).

        Format per material (64 bytes):
            uint32 flags
            uint32 shader
            uint32 blendMode
            uint32 texture1_offset (into MOTX)
            uint32 color1 (BGRA)
            uint32 flags1
            uint32 texture2_offset
            uint32 color2 (BGRA)
            uint32 flags2
            uint32 color3 (BGRA)
            28 bytes padding (to reach 64 bytes total: 10*4 = 40 + 24 = 64)
        """
        data = BytesIO()

        texture_offset = 0
        for material_name in self.materials:
            material = MaterialPreset.get_material(material_name)
            texture_path = material['texture']

            flags = 0x00

            data.write(struct.pack('<IIIIIIIIII',
                                   flags,
                                   material['shader'],
                                   material['blend_mode'],
                                   texture_offset,
                                   0xFFFFFFFF,  # color1 (white)
                                   0,            # flags1
                                   0,            # texture2_offset (none)
                                   0xFFFFFFFF,  # color2
                                   0,            # flags2
                                   0xFFFFFFFF   # color3
                                   ))

            # Padding to 64 bytes (10 uint32 = 40 bytes, need 24 more)
            data.write(b'\x00' * 24)

            texture_offset += len(texture_path.encode('utf-8')) + 1

        _write_chunk(output, b'MOMT', data.getvalue())

    def _write_mogn_chunk(self, output):
        """
        Write MOGN chunk (group names).
        Null-terminated strings concatenated.
        """
        buf = BytesIO()

        for i, room in enumerate(self.groups):
            group_name = room.get('name', "Group_{:03d}".format(i))
            buf.write(group_name.encode('utf-8') + b'\x00')

        _write_chunk(output, b'MOGN', buf.getvalue())

    def _write_mogi_chunk(self, output):
        """
        Write MOGI chunk (group info).

        Format per group (32 bytes):
            uint32 flags
            float[3] bounding_box_min
            float[3] bounding_box_max
            int32 nameOffset (into MOGN)
        """
        data = BytesIO()
        name_offset = 0

        for i, room in enumerate(self.groups):
            center = room['center']
            room_type = room['type']

            if room_type == 'circular' or room_type == 'chamber':
                r = room.get('radius', 15.0)
                h = room.get('height', 10.0)
                bbox_min = (center[0] - r, center[1] - r, center[2])
                bbox_max = (center[0] + r, center[1] + r, center[2] + h)
            elif room_type == 'box' or room_type == 'corridor':
                w = room.get('width', 10.0) / 2.0
                l = room.get('length', 10.0) / 2.0
                h = room.get('height', 10.0)
                bbox_min = (center[0] - w, center[1] - l, center[2])
                bbox_max = (center[0] + w, center[1] + l, center[2] + h)
            elif room_type == 'spiral':
                r = room.get('radius', 15.0) + 2.0
                h_val = room.get('height', 10.0)
                min_z = center[2] + min(0.0, h_val)
                max_z = center[2] + max(0.0, h_val)
                bbox_min = (center[0] - r, center[1] - r, min_z)
                bbox_max = (center[0] + r, center[1] + r, max_z)
            elif room_type == 'raw_mesh':
                bounds = room.get('bounds')
                if bounds:
                    bbox_min = tuple(bounds['min'])
                    bbox_max = tuple(bounds['max'])
                else:
                    bbox_min = (center[0] - 20.0, center[1] - 20.0,
                                center[2] - 20.0)
                    bbox_max = (center[0] + 20.0, center[1] + 20.0,
                                center[2] + 20.0)
            else:
                bbox_min = (center[0] - 20.0, center[1] - 20.0, center[2])
                bbox_max = (center[0] + 20.0, center[1] + 20.0, center[2] + 10.0)

            # Group flags: 0x01=has_bsp, 0x08=indoor
            flags = 0x01 | 0x08

            data.write(struct.pack('<Iffffffi',
                                   flags,
                                   bbox_min[0], bbox_min[1], bbox_min[2],
                                   bbox_max[0], bbox_max[1], bbox_max[2],
                                   name_offset))

            group_name = room.get('name', "Group_{:03d}".format(i))
            name_offset += len(group_name.encode('utf-8')) + 1

        _write_chunk(output, b'MOGI', data.getvalue())

    def _write_mosb_chunk(self, output):
        """
        Write MOSB chunk (skybox name).
        Null-terminated string. Empty for indoor dungeon.
        """
        _write_chunk(output, b'MOSB', b'\x00')

    def _write_mopv_chunk(self, output):
        """
        Write MOPV chunk (portal vertices).
        Array of float[3] vertices.
        """
        if not self.portals:
            _write_chunk(output, b'MOPV', b'')
            return

        data = BytesIO()
        for portal in self.portals:
            for vertex in portal['vertices']:
                data.write(struct.pack('<fff',
                                       vertex[0], vertex[1], vertex[2]))

        _write_chunk(output, b'MOPV', data.getvalue())

    def _write_mopt_chunk(self, output):
        """
        Write MOPT chunk (portal info).

        Format per portal (20 bytes):
            uint16 startVertex
            uint16 count
            float[4] plane (nx, ny, nz, distance)
        """
        if not self.portals:
            _write_chunk(output, b'MOPT', b'')
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
                                   plane['distance']))

            vertex_offset += vertex_count

        _write_chunk(output, b'MOPT', data.getvalue())

    def _write_mopr_chunk(self, output):
        """
        Write MOPR chunk (portal references).

        Format per reference (8 bytes):
            uint16 portalIndex
            uint16 groupIndex
            int16 side (1=front, -1=back)
            uint16 padding
        """
        if not self.portals:
            _write_chunk(output, b'MOPR', b'')
            return

        data = BytesIO()

        for i, portal in enumerate(self.portals):
            room1_id = portal['room1']
            room2_id = portal['room2']

            group1_idx = 0
            group2_idx = 0
            for j, r in enumerate(self.groups):
                if r['id'] == room1_id:
                    group1_idx = j
                if r['id'] == room2_id:
                    group2_idx = j

            # Portal reference for room1 (front side)
            data.write(struct.pack('<HHhH', i, group1_idx, 1, 0))
            # Portal reference for room2 (back side)
            data.write(struct.pack('<HHhH', i, group2_idx, -1, 0))

        _write_chunk(output, b'MOPR', data.getvalue())

    def _write_molt_chunk(self, output):
        """
        Write MOLT chunk (lights).

        Format per light (48 bytes):
            uint8 type (0=omni, 1=spot, 2=directional, 3=ambient)
            uint8 useAttenuation
            uint8[2] padding
            uint32 color (BGRA)
            float[3] position
            float intensity
            float[3] unknown
            float attenuationStart
            float attenuationEnd
        """
        if not self.lights:
            _write_chunk(output, b'MOLT', b'')
            return

        data = BytesIO()

        for light in self.lights:
            light_type = 0   # Omni/point light
            use_attenuation = 1

            r, g, b = light['color']
            color = ((int(b * 255) & 0xFF) << 16 |
                     (int(g * 255) & 0xFF) << 8 |
                     (int(r * 255) & 0xFF) |
                     0xFF000000)

            pos = light['position']
            intensity = light['intensity']
            atten_start = light['attenuation_start']
            atten_end = light['attenuation_end']

            data.write(struct.pack('<BBBBI',
                                   light_type,
                                   use_attenuation,
                                   0, 0,
                                   color))
            data.write(struct.pack('<fff', pos[0], pos[1], pos[2]))
            data.write(struct.pack('<f', intensity))
            data.write(struct.pack('<fff', 0.0, 0.0, 0.0))  # unknown
            data.write(struct.pack('<ff', atten_start, atten_end))
            # Padding to reach 48 bytes per light entry
            data.write(b'\x00' * 4)

        _write_chunk(output, b'MOLT', data.getvalue())

    def _write_mods_chunk(self, output):
        """
        Write MODS chunk (doodad sets).

        Format per set (32 bytes):
            char[20] name
            uint32 startIndex
            uint32 count
            uint32 padding
        """
        name_bytes = b'Set_Default\x00'
        # Pad name to 20 bytes
        name_bytes = name_bytes + b'\x00' * (20 - len(name_bytes))

        data = struct.pack('<20sIII',
                           name_bytes,
                           0,                     # startIndex
                           len(self.doodads),     # count
                           0)                     # padding

        _write_chunk(output, b'MODS', data)

    def _write_modn_chunk(self, output):
        """
        Write MODN chunk (doodad model names).
        Null-terminated strings concatenated.
        """
        if not self.doodads:
            _write_chunk(output, b'MODN', b'\x00')
            return

        buf = BytesIO()
        seen_models = set()

        for doodad in self.doodads:
            model_path = doodad['model']
            if model_path not in seen_models:
                buf.write(model_path.encode('utf-8') + b'\x00')
                seen_models.add(model_path)

        _write_chunk(output, b'MODN', buf.getvalue())

    def _write_modd_chunk(self, output):
        """
        Write MODD chunk (doodad definitions).

        Format per doodad (40 bytes):
            uint32 nameOffset (into MODN, bits 0-23) | flags (bits 24-31)
            float[3] position
            float[4] rotation (quaternion: x, y, z, w)
            float scale
            uint32 color (BGRA)
        """
        if not self.doodads:
            _write_chunk(output, b'MODD', b'')
            return

        # Build name offset map
        name_offset_map = {}
        offset = 0
        for doodad in self.doodads:
            model_path = doodad['model']
            if model_path not in name_offset_map:
                name_offset_map[model_path] = offset
                offset += len(model_path.encode('utf-8')) + 1

        data = BytesIO()

        for doodad in self.doodads:
            name_offset = name_offset_map[doodad['model']]
            pos = doodad['position']
            scale = doodad.get('scale', 1.0)

            # Quaternion (identity rotation)
            qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0

            data.write(struct.pack('<I', name_offset & 0x00FFFFFF))
            data.write(struct.pack('<fff', pos[0], pos[1], pos[2]))
            data.write(struct.pack('<ffff', qx, qy, qz, qw))
            data.write(struct.pack('<f', scale))
            data.write(struct.pack('<I', 0xFFFFFFFF))  # color (white)

        _write_chunk(output, b'MODD', data.getvalue())


# ===========================================================================
# WMO Group File Assembler
# ===========================================================================

class WMOGroupAssembler(object):
    """
    Assemble WMO group file (one per room).
    """

    def __init__(self, room_def, material_map):
        """
        Args:
            room_def: Room definition dict.
            material_map: Dict mapping material preset name to global index.
        """
        self.room_def = room_def
        self.material_map = material_map

        # Generate room geometry
        self.room_geometry = self._generate_room_geometry()

    def assemble(self):
        """
        Assemble complete WMO group file.

        Returns:
            Binary WMO group file data (bytes).
        """
        output = BytesIO()

        # Write MVER chunk
        _write_chunk(output, b'MVER', struct.pack('<I', _WMO_VERSION))

        # Write MOGP chunk (group header + all sub-chunks)
        self._write_mogp_chunk(output)

        return output.getvalue()

    def _generate_room_geometry(self):
        """
        Generate geometry for this room based on room type.

        Returns:
            dict with vertices, normals, uvs, triangles, face_materials.
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
        elif room_type == 'raw_mesh':
            # Raw mesh from imported WMO data -- use stored geometry directly
            return {
                'vertices': list(self.room_def['vertices']),
                'normals': list(self.room_def['normals']),
                'uvs': list(self.room_def['uvs']),
                'triangles': list(self.room_def['triangles']),
                'face_materials': list(self.room_def.get(
                    'face_materials', ['floor'] * len(self.room_def['triangles'])
                )),
            }
        else:
            raise ValueError("Unknown room type: {}".format(room_type))

        # Translate vertices to room center (world space)
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

    def _write_mogp_chunk(self, output):
        """
        Write MOGP chunk (group header + all geometry sub-chunks).
        MOGP contains all group geometry as sub-chunks.
        """
        mogp_data = BytesIO()

        # Write group header (68 bytes)
        self._write_mogp_header(mogp_data)

        # Write geometry sub-chunks
        self._write_mopy_subchunk(mogp_data)
        self._write_movi_subchunk(mogp_data)
        self._write_movt_subchunk(mogp_data)
        self._write_monr_subchunk(mogp_data)
        self._write_motv_subchunk(mogp_data)
        self._write_moba_subchunk(mogp_data)

        # Write BSP sub-chunks
        self._write_bsp_subchunks(mogp_data)

        _write_chunk(output, b'MOGP', mogp_data.getvalue())

    def _write_mogp_header(self, output):
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
        vertices = self.room_geometry['vertices']

        if vertices:
            bbox_min = (min(v[0] for v in vertices),
                        min(v[1] for v in vertices),
                        min(v[2] for v in vertices))
            bbox_max = (max(v[0] for v in vertices),
                        max(v[1] for v in vertices),
                        max(v[2] for v in vertices))
        else:
            bbox_min = (0.0, 0.0, 0.0)
            bbox_max = (0.0, 0.0, 0.0)

        # Group flags: 0x01=has_bsp, 0x08=indoor, 0x200=has_vertex_colors (MOCV)
        flags = 0x01 | 0x08

        output.write(struct.pack('<III',
                                 0,      # nameOffset
                                 0,      # descOffset
                                 flags))
        output.write(struct.pack('<fff', bbox_min[0], bbox_min[1], bbox_min[2]))
        output.write(struct.pack('<fff', bbox_max[0], bbox_max[1], bbox_max[2]))
        output.write(struct.pack('<HHHHHH',
                                 0,   # portalStart
                                 0,   # portalCount
                                 0,   # transBatchCount
                                 1,   # intBatchCount (one opaque batch)
                                 0,   # extBatchCount
                                 0))  # padding
        output.write(struct.pack('<BBBB', 0, 0, 0, 0))  # fogIndices
        output.write(struct.pack('<III',
                                 0,   # liquidType
                                 0,   # groupID
                                 0))  # unknown1
        output.write(struct.pack('<I', 0))  # unknown2

    def _write_mopy_subchunk(self, output):
        """
        Write MOPY sub-chunk (material info per triangle).

        Format per triangle (2 bytes):
            uint8 flags
            uint8 materialID
        """
        face_materials = self.room_geometry['face_materials']

        data = BytesIO()

        # raw_mesh face_materials are dicts with flags/material_id;
        # generated rooms use string labels ('floor', 'wall', 'ceiling').
        if face_materials and isinstance(face_materials[0], dict):
            # Imported raw mesh -- use stored flags and material_id directly
            for face_mat in face_materials:
                flags = face_mat.get('flags', 0x05)
                material_idx = face_mat.get('material_id', 0)
                data.write(struct.pack('<BB', flags, material_idx))
        else:
            room_materials = self.room_def.get('materials', {
                'floor': 'floor_tile',
                'wall': 'stone_dark',
                'ceiling': 'stone_dark',
            })

            for face_mat in face_materials:
                material_preset = room_materials.get(face_mat, 'stone_dark')
                material_idx = self.material_map.get(material_preset, 0)

                # flags: 0x04 = collision, 0x01 = unknown/render
                flags = 0x04 | 0x01
                data.write(struct.pack('<BB', flags, material_idx))

        _write_chunk(output, b'MOPY', data.getvalue())

    def _write_movi_subchunk(self, output):
        """
        Write MOVI sub-chunk (triangle vertex indices).
        Array of uint16[3] (triangle indices).
        """
        triangles = self.room_geometry['triangles']

        data = BytesIO()
        for tri in triangles:
            data.write(struct.pack('<HHH', tri[0], tri[1], tri[2]))

        _write_chunk(output, b'MOVI', data.getvalue())

    def _write_movt_subchunk(self, output):
        """
        Write MOVT sub-chunk (vertices).
        Array of float[3] (vertex positions).
        """
        vertices = self.room_geometry['vertices']

        data = BytesIO()
        for v in vertices:
            data.write(struct.pack('<fff', v[0], v[1], v[2]))

        _write_chunk(output, b'MOVT', data.getvalue())

    def _write_monr_subchunk(self, output):
        """
        Write MONR sub-chunk (normals).
        Array of float[3] (normal vectors).
        """
        normals = self.room_geometry['normals']

        data = BytesIO()
        for n in normals:
            data.write(struct.pack('<fff', n[0], n[1], n[2]))

        _write_chunk(output, b'MONR', data.getvalue())

    def _write_motv_subchunk(self, output):
        """
        Write MOTV sub-chunk (texture coordinates).
        Array of float[2] (UV coords).
        """
        uvs = self.room_geometry['uvs']

        data = BytesIO()
        for uv in uvs:
            data.write(struct.pack('<ff', uv[0], uv[1]))

        _write_chunk(output, b'MOTV', data.getvalue())

    def _write_moba_subchunk(self, output):
        """
        Write MOBA sub-chunk (render batches).

        Format per batch (24 bytes):
            int16[3] bounding_box_min (short)
            int16[3] bounding_box_max (short)
            uint32 startIndex
            uint16 count (number of indices)
            uint16 minIndex
            uint16 maxIndex
            uint8 unused
            uint8 materialID
        """
        triangles = self.room_geometry['triangles']
        vertices = self.room_geometry['vertices']

        n_indices = len(triangles) * 3
        max_vertex_idx = len(vertices) - 1 if vertices else 0

        # Compute integer bounding box for batch
        if vertices:
            bb_min_x = int(min(v[0] for v in vertices))
            bb_min_y = int(min(v[1] for v in vertices))
            bb_min_z = int(min(v[2] for v in vertices))
            bb_max_x = int(max(v[0] for v in vertices))
            bb_max_y = int(max(v[1] for v in vertices))
            bb_max_z = int(max(v[2] for v in vertices))
        else:
            bb_min_x = bb_min_y = bb_min_z = 0
            bb_max_x = bb_max_y = bb_max_z = 0

        # Clamp to int16 range
        def _clamp_i16(v):
            return max(-32768, min(32767, v))

        data = struct.pack('<hhhhhh',
                           _clamp_i16(bb_min_x),
                           _clamp_i16(bb_min_y),
                           _clamp_i16(bb_min_z),
                           _clamp_i16(bb_max_x),
                           _clamp_i16(bb_max_y),
                           _clamp_i16(bb_max_z))
        data += struct.pack('<IHHHBB',
                            0,              # startIndex
                            n_indices,      # count
                            0,              # minIndex
                            max_vertex_idx, # maxIndex
                            0,              # unused
                            0)              # materialID

        _write_chunk(output, b'MOBA', data)

    def _write_bsp_subchunks(self, output):
        """Write MOBN (BSP nodes) and MOBR (face indices) sub-chunks."""
        vertices = self.room_geometry['vertices']
        triangles = self.room_geometry['triangles']

        if not triangles:
            _write_chunk(output, b'MOBN', b'')
            _write_chunk(output, b'MOBR', b'')
            return

        bsp_nodes, face_indices = BSPTreeBuilder.build_bsp_tree(
            vertices, triangles)

        mobn_data = BSPTreeBuilder.pack_bsp_nodes(bsp_nodes)
        mobr_data = BSPTreeBuilder.pack_face_indices(face_indices)

        _write_chunk(output, b'MOBN', mobn_data)
        _write_chunk(output, b'MOBR', mobr_data)


# ===========================================================================
# Connection and Portal Resolution
# ===========================================================================

def resolve_connections(dungeon_def):
    """
    Resolve room connections and generate portal definitions.

    Walks the 'connects_to' list in each room and generates portal data
    for the MOPV/MOPT/MOPR chunks.

    Args:
        dungeon_def: Dungeon definition dict (modified in-place).
    """
    rooms_by_id = {room['id']: room for room in dungeon_def['rooms']}
    portals = []
    seen_connections = set()

    for room in dungeon_def['rooms']:
        room_id = room['id']
        connects_to = room.get('connects_to', [])

        for target_id in connects_to:
            # Avoid duplicate connections
            conn_key = tuple(sorted([room_id, target_id]))
            if conn_key in seen_connections:
                continue
            seen_connections.add(conn_key)

            if target_id not in rooms_by_id:
                continue

            target_room = rooms_by_id[target_id]

            # Calculate doorway position (midpoint between room centers)
            c1 = room['center']
            c2 = target_room['center']
            doorway_pos = (
                (c1[0] + c2[0]) / 2.0,
                (c1[1] + c2[1]) / 2.0,
                (c1[2] + c2[2]) / 2.0,
            )

            # Calculate orientation (angle from room1 to room2)
            dx = c2[0] - c1[0]
            dy = c2[1] - c1[1]
            orientation = math.atan2(dy, dx)

            connection = {
                'position': doorway_pos,
                'width': 4.0,
                'height': min(room.get('height', 6.0),
                              target_room.get('height', 6.0)) * 0.8,
                'orientation': orientation,
            }

            portal = PortalGenerator.generate_doorway_portal(
                room, target_room, connection)
            portals.append(portal)

    dungeon_def['portals'] = portals


def collect_materials(dungeon_def):
    """
    Collect all unique materials from rooms and build material index map.

    Returns:
        dict mapping material preset name to index.
    """
    material_list = []
    seen = set()

    for room in dungeon_def['rooms']:
        room_materials = room.get('materials', {})
        for face_type in ['floor', 'wall', 'ceiling']:
            mat = room_materials.get(face_type)
            if mat and mat not in seen:
                material_list.append(mat)
                seen.add(mat)

    return {mat: idx for idx, mat in enumerate(material_list)}


# ===========================================================================
# Coordinate Export
# ===========================================================================

def export_spawn_coordinates(dungeon_def):
    """
    Export spawn coordinates for bosses, trash, doors.

    Returns:
        Coordinate metadata dict for SQL generator.
    """
    coordinate_metadata = {
        'map_id': dungeon_def.get('map_id', 0),
        'dungeon_name': dungeon_def.get('name', 'Unknown'),
        'rooms': {},
    }

    for room in dungeon_def['rooms']:
        room_id = room['id']
        center = room['center']

        boss_spawn = None
        if room.get('boss', {}).get('enabled'):
            boss_offset = room['boss'].get('spawn_offset', (0, 0, 0))
            boss_spawn = {
                'entry_id': room['boss']['entry_id'],
                'position': (center[0] + boss_offset[0],
                             center[1] + boss_offset[1],
                             center[2] + boss_offset[2]),
                'orientation': 0.0,
            }

        coordinate_metadata['rooms'][room_id] = {
            'center': center,
            'boss_spawn': boss_spawn,
            'trash_spawns': [],
            'doors': [],
        }

    return coordinate_metadata


# ===========================================================================
# High-Level API
# ===========================================================================

def build_dungeon(dungeon_def, output_dir, dbc_dir=None):
    """
    Build complete dungeon with full WMO generation.

    Args:
        dungeon_def: Dungeon definition dictionary containing room layouts,
            materials, lights, doodads, and connection info.
        output_dir: Output directory for WMO files.
        dbc_dir: Path to DBFilesClient directory for Map.dbc registration.
            If None, DBC registration is skipped.

    Returns:
        dict with:
            wmo_files: List of generated WMO file paths.
            coordinate_metadata: Spawn coordinates for SQL generator.
            map_id: Map.dbc ID.
    """
    dungeon_name = dungeon_def.get('name', 'UnknownDungeon')

    # Create output directory
    wmo_dir = os.path.join(output_dir, "World", "wmo", "Dungeons", dungeon_name)
    os.makedirs(wmo_dir, exist_ok=True)

    # Resolve room connections and generate portals
    resolve_connections(dungeon_def)

    # Collect all unique materials
    material_map = collect_materials(dungeon_def)

    # Generate WMO root file
    root_assembler = WMORootAssembler(dungeon_def)
    root_data = root_assembler.assemble()

    root_path = os.path.join(wmo_dir, "{}.wmo".format(dungeon_name))
    with open(root_path, 'wb') as f:
        f.write(root_data)

    # Generate WMO group files (one per room)
    group_files = []
    for i, room in enumerate(dungeon_def['rooms']):
        group_assembler = WMOGroupAssembler(room, material_map)
        group_data = group_assembler.assemble()

        group_path = os.path.join(wmo_dir,
                                  "{}_{:03d}.wmo".format(dungeon_name, i))
        with open(group_path, 'wb') as f:
            f.write(group_data)
        group_files.append(group_path)

    # Export spawn coordinates
    coordinate_metadata = export_spawn_coordinates(dungeon_def)

    coord_path = os.path.join(output_dir, "coordinate_metadata.json")
    with open(coord_path, 'w') as f:
        json.dump(coordinate_metadata, f, indent=2)

    # Register in Map.dbc (optional)
    if dbc_dir:
        _register_dungeon_map(dungeon_def, dbc_dir)

    return {
        'wmo_files': [root_path] + group_files,
        'coordinate_metadata': coordinate_metadata,
        'map_id': dungeon_def.get('map_id', 0),
    }


def _register_dungeon_map(dungeon_def, dbc_dir):
    """
    Register dungeon in Map.dbc using dbc_injector.

    Args:
        dungeon_def: Dungeon definition dict.
        dbc_dir: Path to directory containing Map.dbc.
    """
    from world_builder.dbc_injector import register_map

    register_map(
        dbc_dir=dbc_dir,
        map_name=dungeon_def.get('name', 'UnknownDungeon'),
        map_id=dungeon_def.get('map_id', None),
        instance_type=dungeon_def.get('instance_type', 1),
    )


# ===========================================================================
# WMO Reader -- Import dungeon from existing WMO files
# ===========================================================================

def read_dungeon(wmo_filepath, version=17):
    """
    Read an existing WMO dungeon file and return a dungeon definition dict.

    Parses the WMO root file and all associated group files using the parent
    library WMOFile reader. Extracts geometry, materials, portals, lights,
    and doodads into a dict that can be modified and re-exported via
    build_dungeon().

    Rooms use ``'type': 'raw_mesh'`` since primitive shapes cannot be
    reverse-engineered from arbitrary geometry.

    Args:
        wmo_filepath: Path to the WMO root file.
        version: WMO version number (default 17 for WotLK 3.3.5a).

    Returns:
        dict: Dungeon definition with keys:
            - name (str): Dungeon display name derived from filename.
            - rooms (list[dict]): One dict per WMO group. Each has
              ``'type': 'raw_mesh'``, vertices, triangles, normals, uvs,
              face_materials, bounds, and center.
            - portals (list[dict]): Portal definitions with vertices,
              plane, and room references.
            - materials (list[dict]): Material definitions with texture
              paths and shader info.
            - lights (list[dict]): Light definitions.
            - doodads (list[dict]): Doodad placement definitions.

    Raises:
        FileNotFoundError: If the WMO root file does not exist.
        ImportError: If the parent WMO library is not available.
    """
    if not os.path.isfile(wmo_filepath):
        raise FileNotFoundError(
            "WMO file not found: {}".format(wmo_filepath)
        )

    try:
        from ..wmo_file import WMOFile
    except (ImportError, SystemError):
        try:
            from wmo_file import WMOFile
        except ImportError:
            raise ImportError(
                "Parent library wmo_file is required for read_dungeon(). "
                "Ensure wmo_file.py is importable."
            )

    log.info("Reading WMO dungeon from: %s", wmo_filepath)

    wmo = WMOFile(version, wmo_filepath)
    wmo.read()

    dungeon_name = os.path.basename(os.path.splitext(wmo_filepath)[0])

    # --- Extract materials from MOMT + texture paths from MOTX ---
    materials = _extract_materials(wmo)

    # --- Extract rooms (one per WMO group) ---
    rooms = _extract_rooms(wmo)

    # --- Extract portals ---
    portals = _extract_portals(wmo)

    # --- Extract lights from MOLT ---
    lights = _extract_lights(wmo)

    # --- Extract doodads from MODD + model paths from MODN ---
    doodads = _extract_doodads(wmo)

    dungeon_def = {
        'name': dungeon_name,
        'rooms': rooms,
        'portals': portals,
        'materials': materials,
        'lights': lights,
        'doodads': doodads,
    }

    log.info(
        "Read dungeon '%s': %d rooms, %d portals, %d materials, "
        "%d lights, %d doodads",
        dungeon_name, len(rooms), len(portals), len(materials),
        len(lights), len(doodads),
    )

    return dungeon_def


def _extract_materials(wmo):
    """
    Extract material definitions from WMO root chunks.

    Args:
        wmo: WMOFile instance (already read).

    Returns:
        list[dict]: Material definitions with texture paths and shader info.
    """
    materials = []

    for mat in wmo.momt.materials:
        tex1 = wmo.motx.get_string(mat.texture1_ofs)
        tex2 = wmo.motx.get_string(mat.texture2_ofs) if mat.texture2_ofs else ''

        materials.append({
            'texture1': tex1,
            'texture2': tex2,
            'shader': mat.shader,
            'blend_mode': mat.blend_mode,
            'terrain_type': mat.terrain_type,
            'flags': mat.flags,
            'emissive_color': tuple(mat.emissive_color),
            'diff_color': tuple(mat.diff_color),
        })

    return materials


def _extract_rooms(wmo):
    """
    Extract room geometry from WMO group files.

    Each WMO group becomes one room with ``'type': 'raw_mesh'``.

    Args:
        wmo: WMOFile instance (already read).

    Returns:
        list[dict]: Room definitions with raw mesh geometry.
    """
    rooms = []

    for group_idx, group in enumerate(wmo.groups):
        # Extract group name from MOGN via MOGI name offset
        group_name = "Group_{:03d}".format(group_idx)
        if group_idx < len(wmo.mogi.infos):
            gi = wmo.mogi.infos[group_idx]
            name_from_table = wmo.mogn.get_string(gi.name_ofs)
            if name_from_table:
                group_name = name_from_table

        # Extract vertices from MOVT
        vertices = []
        for v in group.movt.vertices:
            vertices.append(tuple(v))

        # Extract triangle indices from MOVI (flat list -> triplets)
        triangles = []
        indices = group.movi.indices
        for i in range(0, len(indices), 3):
            if i + 2 < len(indices):
                triangles.append((indices[i], indices[i + 1], indices[i + 2]))

        # Extract normals from MONR
        normals = []
        for n in group.monr.normals:
            normals.append(tuple(n))

        # Extract UVs from MOTV
        uvs = []
        for tc in group.motv.tex_coords:
            # MOTV item is (float32, float32), read returns tuple of values
            if isinstance(tc, tuple):
                uvs.append(tc)
            else:
                uvs.append((float(tc), 0.0))

        # Extract face materials from MOPY
        face_materials = []
        for tri_mat in group.mopy.triangle_materials:
            face_materials.append({
                'flags': tri_mat.flags,
                'material_id': tri_mat.material_id,
            })

        # Compute bounding box from MOGP header
        bbox_min = tuple(group.mogp.bounding_box_corner1)
        bbox_max = tuple(group.mogp.bounding_box_corner2)

        # Compute center from bounding box
        center = (
            (bbox_min[0] + bbox_max[0]) / 2.0,
            (bbox_min[1] + bbox_max[1]) / 2.0,
            (bbox_min[2] + bbox_max[2]) / 2.0,
        )

        room = {
            'id': "group_{:03d}".format(group_idx),
            'name': group_name,
            'type': 'raw_mesh',
            'center': center,
            'vertices': vertices,
            'triangles': triangles,
            'normals': normals,
            'uvs': uvs,
            'face_materials': face_materials,
            'bounds': {
                'min': list(bbox_min),
                'max': list(bbox_max),
            },
            'mogp_flags': group.mogp.flags,
            'connects_to': [],
            'boss': {'enabled': False},
            'materials': {},
            'lights': [],
            'doodads': [],
        }

        rooms.append(room)

    return rooms


def _extract_portals(wmo):
    """
    Extract portal definitions from WMO root chunks.

    Args:
        wmo: WMOFile instance (already read).

    Returns:
        list[dict]: Portal definitions with vertices, plane, and room refs.
    """
    portals = []
    portal_infos = wmo.mopt.infos
    portal_vertices = wmo.mopv.portal_vertices
    portal_relations = wmo.mopr.relations

    # Build a mapping from portal index to its relations
    relation_map = {}
    for rel in portal_relations:
        pidx = rel.portal_index
        if pidx not in relation_map:
            relation_map[pidx] = []
        relation_map[pidx].append(rel)

    for i, pinfo in enumerate(portal_infos):
        start = pinfo.start_vertex
        count = pinfo.n_vertices
        verts = []
        for vi in range(start, start + count):
            if vi < len(portal_vertices):
                verts.append(tuple(portal_vertices[vi]))

        plane_normal = tuple(pinfo.normal)
        plane_distance = pinfo.unknown  # stored as the float after normal

        # Determine connected rooms from relations
        room1 = "group_{:03d}".format(0)
        room2 = "group_{:03d}".format(0)
        relations_for_portal = relation_map.get(i, [])
        if len(relations_for_portal) >= 1:
            room1 = "group_{:03d}".format(relations_for_portal[0].group_index)
        if len(relations_for_portal) >= 2:
            room2 = "group_{:03d}".format(relations_for_portal[1].group_index)

        portals.append({
            'vertices': verts,
            'plane': {
                'normal': plane_normal,
                'distance': plane_distance,
            },
            'room1': room1,
            'room2': room2,
        })

    return portals


def _extract_lights(wmo):
    """
    Extract light definitions from WMO root MOLT chunk.

    Args:
        wmo: WMOFile instance (already read).

    Returns:
        list[dict]: Light definitions.
    """
    lights = []

    for light in wmo.molt.lights:
        lights.append({
            'light_type': light.light_type,
            'type': 'point' if light.light_type == 0 else 'spot',
            'use_attenuation': bool(light.use_attenuation),
            'color': tuple(light.color),
            'position': tuple(light.position),
            'intensity': light.intensity,
            'attenuation_start': light.attenuation_start,
            'attenuation_end': light.attenuation_end,
        })

    return lights


def _extract_doodads(wmo):
    """
    Extract doodad placements from WMO root MODD + MODN chunks.

    Args:
        wmo: WMOFile instance (already read).

    Returns:
        list[dict]: Doodad placement definitions.
    """
    doodads = []

    # Extract doodad sets from MODS
    doodad_sets = []
    for ds in wmo.mods.sets:
        doodad_sets.append({
            'name': ds.name.rstrip('\x00'),
            'start_doodad': ds.start_doodad,
            'n_doodads': ds.n_doodads,
        })

    for doodad_def in wmo.modd.definitions:
        model_path = wmo.modn.get_string(doodad_def.name_ofs)

        doodads.append({
            'model': model_path,
            'position': tuple(doodad_def.position),
            'rotation': tuple(doodad_def.rotation)
                if hasattr(doodad_def.rotation, '__iter__')
                else (0.0, 0.0, 0.0, 1.0),
            'scale': doodad_def.scale,
            'color': tuple(doodad_def.color)
                if hasattr(doodad_def.color, '__iter__')
                else (255, 255, 255, 255),
            'flags': doodad_def.flags,
        })

    return doodads


# ===========================================================================
# Vault of Storms - Example Dungeon Definition
# ===========================================================================

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
                {
                    'type': 'point',
                    'position': (0, 0, 10),
                    'color': (0.3, 0.5, 1.0),
                    'intensity': 1.0,
                    'attenuation_start': 15,
                    'attenuation_end': 40,
                },
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Pillar_01.m2',
                    'positions': [(15, 0, 0), (-15, 0, 0),
                                  (0, 15, 0), (0, -15, 0)],
                },
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
                {
                    'type': 'point',
                    'position': (0, -15, 4),
                    'color': (0.8, 0.8, 1.0),
                    'intensity': 0.7,
                    'attenuation_start': 10,
                    'attenuation_end': 25,
                },
                {
                    'type': 'point',
                    'position': (0, 15, 4),
                    'color': (0.8, 0.8, 1.0),
                    'intensity': 0.7,
                    'attenuation_start': 10,
                    'attenuation_end': 25,
                },
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Conduit_Broken.m2',
                    'positions': [(3, -10, 0), (-3, 10, 0)],
                },
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
                {
                    'type': 'point',
                    'position': (0, 0, 15),
                    'color': (0.5, 0.2, 0.8),
                    'intensity': 1.2,
                    'attenuation_start': 20,
                    'attenuation_end': 50,
                },
            ],
            'doodads': [],
            'boss': {
                'enabled': True,
                'entry_id': 90100,
                'spawn_offset': (0, 0, 0),
            },
            'connects_to': ['winding_core'],
        },
        {
            'id': 'winding_core',
            'name': 'The Winding Core',
            'type': 'spiral',
            'radius': 15,
            'height': -30,
            'turns': 3.0,
            'center': (0, 150, 20),
            'materials': {
                'floor': 'titan_metal',
                'wall': 'titan_metal',
                'ceiling': 'titan_metal',
            },
            'lights': [
                {
                    'type': 'point',
                    'position': (0, 0, 15),
                    'color': (0.4, 0.7, 1.0),
                    'intensity': 0.8,
                    'attenuation_start': 12,
                    'attenuation_end': 30,
                },
                {
                    'type': 'point',
                    'position': (0, 0, 0),
                    'color': (0.4, 0.7, 1.0),
                    'intensity': 0.8,
                    'attenuation_start': 12,
                    'attenuation_end': 30,
                },
                {
                    'type': 'point',
                    'position': (0, 0, -15),
                    'color': (0.4, 0.7, 1.0),
                    'intensity': 0.8,
                    'attenuation_start': 12,
                    'attenuation_end': 30,
                },
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Coolant_Vent.m2',
                    'positions': [(10, 0, 10), (10, 0, -10), (10, 0, -20)],
                },
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
                {
                    'type': 'point',
                    'position': (-10, -10, 8),
                    'color': (1.0, 0.5, 0.2),
                    'intensity': 1.1,
                    'attenuation_start': 15,
                    'attenuation_end': 35,
                },
                {
                    'type': 'point',
                    'position': (10, -10, 8),
                    'color': (1.0, 0.5, 0.2),
                    'intensity': 1.1,
                    'attenuation_start': 15,
                    'attenuation_end': 35,
                },
                {
                    'type': 'point',
                    'position': (-10, 10, 8),
                    'color': (1.0, 0.5, 0.2),
                    'intensity': 1.1,
                    'attenuation_start': 15,
                    'attenuation_end': 35,
                },
                {
                    'type': 'point',
                    'position': (10, 10, 8),
                    'color': (1.0, 0.5, 0.2),
                    'intensity': 1.1,
                    'attenuation_start': 15,
                    'attenuation_end': 35,
                },
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Forge_Anvil.m2',
                    'positions': [(10, 10, 0)],
                },
            ],
            'boss': {
                'enabled': True,
                'entry_id': 90101,
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
                {
                    'type': 'point',
                    'position': (0, 0, 20),
                    'color': (0.7, 0.8, 1.0),
                    'intensity': 1.3,
                    'attenuation_start': 25,
                    'attenuation_end': 60,
                },
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Pillar_Tall.m2',
                    'positions': [(20, 15, 0), (-20, 15, 0),
                                  (20, -15, 0), (-20, -15, 0)],
                },
            ],
            'boss': {
                'enabled': True,
                'entry_id': 90102,
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
                {
                    'type': 'point',
                    'position': (0, 0, 10),
                    'color': (0.6, 0.6, 0.6),
                    'intensity': 0.9,
                    'attenuation_start': 15,
                    'attenuation_end': 35,
                },
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Debris_Pile.m2',
                    'positions': [(10, 0, 0)],
                },
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
                {
                    'type': 'point',
                    'position': (0, 0, 3),
                    'color': (0.3, 0.8, 1.0),
                    'intensity': 1.0,
                    'attenuation_start': 8,
                    'attenuation_end': 20,
                },
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Ward_Effect.m2',
                    'positions': [(0, 0, 2)],
                },
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
                {
                    'type': 'point',
                    'position': (0, 0, 20),
                    'color': (0.5, 0.3, 1.0),
                    'intensity': 1.5,
                    'attenuation_start': 30,
                    'attenuation_end': 70,
                },
            ],
            'doodads': [
                {
                    'model': 'World\\Expansion02\\Doodads\\Ulduar\\Ulduar_Containment_Orb.m2',
                    'positions': [(0, 0, 12)],
                },
            ],
            'boss': {
                'enabled': True,
                'entry_id': 90103,
                'spawn_offset': (0, 0, 0),
            },
            'connects_to': [],
        },
    ],
}
