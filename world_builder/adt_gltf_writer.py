"""
ADT terrain to glTF 2.0 and heightmap image converter for WoW WotLK 3.3.5a.

Converts ADT terrain tile data (as produced by tools/adt_converter.py
adt_to_json()) to:
- Grayscale heightmap PNG (129x129 outer-vertex grid for the full tile)
- 3D glTF terrain mesh (.glb) with per-vertex colors and UV mapping

Also supports reverse conversion:
- Grayscale heightmap PNG (129x129) -> ADT JSON data
- glTF terrain mesh (.glb) -> ADT JSON data

Dependencies: Pillow (for heightmap), pygltflib (for glTF)
"""

import os
import struct as _struct
import logging

log = logging.getLogger(__name__)

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    Image = None
    _HAS_PIL = False

try:
    import pygltflib
    _HAS_GLTFLIB = True
except ImportError:
    pygltflib = None
    _HAS_GLTFLIB = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Each MCNK has 145 height values arranged as 17 rows:
#   outer row (9 values), inner row (8 values), outer row, inner row, ...
# That gives 9 outer rows and 8 inner rows.
_OUTER_COLS = 9
_INNER_COLS = 8
_OUTER_ROWS = 9
_INNER_ROWS = 8
_VERTS_PER_CHUNK = 145

# ADT tile is 16x16 MCNK chunks.
_CHUNKS_PER_SIDE = 16

# Full tile outer-vertex grid: 16 chunks * 8 cells + 1 shared edge = 129
_TILE_VERTS_PER_SIDE = _CHUNKS_PER_SIDE * (_OUTER_COLS - 1) + 1  # 129

# WoW chunk unit size (yards). Each MCNK covers CHUNK_SIZE x CHUNK_SIZE.
_CHUNK_SIZE = 33.3333
_CELL_SIZE = _CHUNK_SIZE / 8.0  # Distance between outer vertices


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_outer_row(heightmap, outer_row_index):
    """Extract the 9 outer-vertex values from a given outer row index (0-8).

    In the 145-value layout, outer row r starts at index r * 17.
    """
    start = outer_row_index * 17
    return heightmap[start:start + _OUTER_COLS]


def _absolute_height(chunk, vert_index):
    """Compute the absolute world height for a vertex in a chunk.

    WoW ADT coordinate convention in the JSON:
      position[0] = X (north-south, decreasing southward)
      position[1] = Y (east-west, decreasing eastward)
      position[2] = Z (height/up, base elevation)

    Heightmap values are offsets relative to position[2].
    Absolute height = chunk.position[2] + heightmap[vert_index]
    """
    return chunk['position'][2] + chunk['heightmap'][vert_index]


# ---------------------------------------------------------------------------
# Heightmap PNG export
# ---------------------------------------------------------------------------

def adt_to_heightmap(adt_json, output_path):
    """Generate a grayscale PNG heightmap from ADT JSON data.

    Uses the 9x9 outer vertex grid from each MCNK chunk, producing a
    129x129 pixel image for the full tile. Heights are normalized to
    0-255 grayscale across the global min/max range.

    Args:
        adt_json: Dict as returned by adt_converter.adt_to_json().
        output_path: Path for the output PNG file.

    Raises:
        ImportError: If Pillow is not installed.
    """
    if not _HAS_PIL:
        raise ImportError("Pillow is required for heightmap export: "
                          "pip install Pillow")

    chunks = adt_json.get('terrain_chunks', [])
    if not chunks:
        log.warning("No terrain chunks found, writing blank heightmap")
        img = Image.new('L', (_TILE_VERTS_PER_SIDE, _TILE_VERTS_PER_SIDE), 0)
        _save_image(img, output_path)
        return

    # Build a lookup from (index_x, index_y) -> chunk for O(1) access.
    chunk_map = {}
    for chunk in chunks:
        key = (chunk['index_x'], chunk['index_y'])
        chunk_map[key] = chunk

    # Collect all absolute heights for the outer grid to find min/max.
    grid = [[0.0] * _TILE_VERTS_PER_SIDE for _ in range(_TILE_VERTS_PER_SIDE)]

    for cy in range(_CHUNKS_PER_SIDE):
        for cx in range(_CHUNKS_PER_SIDE):
            chunk = chunk_map.get((cx, cy))
            if chunk is None:
                continue
            base_z = chunk['position'][2]
            heightmap = chunk.get('heightmap', [0.0] * _VERTS_PER_CHUNK)

            for row in range(_OUTER_COLS):
                for col in range(_OUTER_COLS):
                    vert_idx = row * 17 + col
                    h = base_z + heightmap[vert_idx]

                    # Grid pixel position: chunks are laid out so that
                    # index_y maps to image rows (top to bottom) and
                    # index_x maps to image columns (left to right).
                    px = cx * (_OUTER_COLS - 1) + col
                    py = cy * (_OUTER_COLS - 1) + row
                    grid[py][px] = h

    # Find global min/max for normalization.
    h_min = float('inf')
    h_max = float('-inf')
    for row in grid:
        for h in row:
            if h < h_min:
                h_min = h
            if h > h_max:
                h_max = h

    # Normalize to 0-255 grayscale.
    h_range = h_max - h_min
    if h_range < 0.001:
        h_range = 1.0  # Flat terrain, avoid division by zero.

    img = Image.new('L', (_TILE_VERTS_PER_SIDE, _TILE_VERTS_PER_SIDE), 0)
    for py in range(_TILE_VERTS_PER_SIDE):
        for px in range(_TILE_VERTS_PER_SIDE):
            normalized = (grid[py][px] - h_min) / h_range
            pixel = int(round(normalized * 255.0))
            if pixel < 0:
                pixel = 0
            elif pixel > 255:
                pixel = 255
            img.putpixel((px, py), pixel)

    _save_image(img, output_path)
    log.info("Wrote heightmap: %s (%dx%d, height range %.1f - %.1f)",
             output_path, _TILE_VERTS_PER_SIDE, _TILE_VERTS_PER_SIDE,
             h_min, h_max)


def _save_image(img, output_path):
    """Save a PIL Image, creating parent directories if needed."""
    parent = os.path.dirname(output_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    img.save(output_path)


# ---------------------------------------------------------------------------
# glTF terrain mesh export
# ---------------------------------------------------------------------------

def adt_to_gltf(adt_json, output_path):
    """Generate a 3D terrain mesh as a glTF .glb from ADT JSON data.

    Creates a single mesh containing all 256 MCNK chunks triangulated
    with the full 145-vertex grid (outer + inner vertices). Includes
    per-vertex normals, UV coordinates, and vertex colors (if MCCV
    data is present).

    The WoW coordinate system is converted to glTF right-handed Y-up:
      WoW X (north-south) -> glTF X
      WoW Y (east-west)   -> glTF Z
      WoW Z (height/up)   -> glTF Y (up)

    Args:
        adt_json: Dict as returned by adt_converter.adt_to_json().
        output_path: Path for the output .glb file.

    Raises:
        ImportError: If pygltflib is not installed.
    """
    if not _HAS_GLTFLIB:
        raise ImportError("pygltflib is required for glTF export: "
                          "pip install pygltflib")

    chunks = adt_json.get('terrain_chunks', [])
    if not chunks:
        log.warning("No terrain chunks, writing empty glTF")
        _write_empty_gltf(output_path)
        return

    # Collect all vertices, normals, uvs, vertex colors, and triangle
    # indices across all chunks into flat lists for a single mesh.
    all_positions = []
    all_normals = []
    all_uvs = []
    all_colors = []
    all_indices = []
    has_colors = False

    for chunk in chunks:
        _triangulate_chunk(
            chunk, all_positions, all_normals, all_uvs, all_colors,
            all_indices)
        if chunk.get('vertex_colors') is not None:
            has_colors = True

    if not has_colors:
        all_colors = []

    _build_gltf(output_path, all_positions, all_normals, all_uvs,
                all_colors, all_indices)

    log.info("Wrote terrain glTF: %s (%d vertices, %d triangles)",
             output_path, len(all_positions), len(all_indices) // 3)


def _triangulate_chunk(chunk, positions, normals, uvs, colors, indices):
    """Triangulate a single MCNK chunk and append to the output lists.

    Each MCNK has 145 vertices in 17 rows:
      Row  0: 9 outer  (indices 0-8)
      Row  1: 8 inner  (indices 9-16)
      Row  2: 9 outer  (indices 17-25)
      ...
      Row 16: 9 outer  (indices 136-144)

    For each cell (r=0..7, c=0..7), there are 4 triangles formed by the
    surrounding outer vertices and the inner center vertex:

      TL---TR       TL = outer_row[r][c]
      |   /|        TR = outer_row[r][c+1]
      | C  |        BL = outer_row[r+1][c]
      |/   |        BR = outer_row[r+1][c+1]
      BL---BR       C  = inner_row[r][c]

      Triangle 1 (top):    TL, C, TR
      Triangle 2 (right):  TR, C, BR
      Triangle 3 (bottom): BR, C, BL
      Triangle 4 (left):   BL, C, TL
    """
    heightmap = chunk.get('heightmap', [0.0] * _VERTS_PER_CHUNK)
    chunk_normals = chunk.get('normals', [[0, 0, 127]] * _VERTS_PER_CHUNK)
    vertex_colors = chunk.get('vertex_colors')
    chunk_pos = chunk.get('position', [0.0, 0.0, 0.0])
    cx = chunk.get('index_x', 0)
    cy = chunk.get('index_y', 0)

    # Base index offset for this chunk in the global vertex list.
    base = len(positions)

    # Emit all 145 vertices for this chunk.
    for v_idx in range(_VERTS_PER_CHUNK):
        # Determine row/col in the interleaved grid.
        row_in_chunk = v_idx // 17  # Which pair of rows (0-based)
        col_in_row = v_idx % 17

        if col_in_row < 9:
            # Outer vertex.
            outer_row = row_in_chunk
            outer_col = col_in_row
            # Position within the chunk grid.
            local_x = outer_col * _CELL_SIZE
            local_z = outer_row * _CELL_SIZE
        else:
            # Inner vertex (offset by half a cell).
            inner_col = col_in_row - 9
            inner_row = row_in_chunk
            local_x = (inner_col + 0.5) * _CELL_SIZE
            local_z = (inner_row + 0.5) * _CELL_SIZE

        # Absolute world position.
        # WoW ADT coordinate convention:
        #   position[0] = X (north-south, decreasing southward)
        #   position[1] = Y (east-west, decreasing eastward)
        #   position[2] = Z (height/up, base elevation)
        # Within a chunk, rows traverse south (decreasing X),
        # columns traverse east (decreasing Y).
        # Heightmap offsets add to position[2].
        wow_x = chunk_pos[0] - local_z  # rows go south = decreasing X
        wow_y = chunk_pos[1] - local_x  # cols go east = decreasing Y
        wow_z = chunk_pos[2] + heightmap[v_idx]

        # glTF Y-up right-handed coordinate system.
        # Map WoW -> glTF: X->X, Z(up)->Y(up), Y->Z
        gltf_x = wow_x
        gltf_y = wow_z  # height
        gltf_z = wow_y
        positions.append((gltf_x, gltf_y, gltf_z))

        # Normal: int8 [x, y, z] normalized from [-127..127] to [-1..1].
        # WoW MCNR normals: [x, z, y] where y is up in WoW terms,
        # stored as (horizontal_x, horizontal_z, vertical_y).
        # Actually, WoW normals in MCNR are (x, z, y) with y being
        # the up component. Apply same axis mapping as positions.
        n = chunk_normals[v_idx] if v_idx < len(chunk_normals) else [0, 0, 127]
        n_wow_x = n[0] / 127.0
        n_wow_z = n[1] / 127.0  # horizontal component
        n_wow_y = n[2] / 127.0  # up component
        # Same mapping: WoW(x,y,z) -> glTF(x, z, y)
        normals.append((n_wow_x, n_wow_y, n_wow_z))

        # UV: map position within the full tile to [0..1].
        u = (cx * (_OUTER_COLS - 1) * _CELL_SIZE + local_x) / (
            _CHUNKS_PER_SIDE * (_OUTER_COLS - 1) * _CELL_SIZE)
        v = (cy * (_OUTER_COLS - 1) * _CELL_SIZE + local_z) / (
            _CHUNKS_PER_SIDE * (_OUTER_COLS - 1) * _CELL_SIZE)
        uvs.append((u, v))

        # Vertex color (RGBA, 0-255 -> 0.0-1.0).
        if vertex_colors is not None and v_idx < len(vertex_colors):
            vc = vertex_colors[v_idx]
            colors.append((
                vc[0] / 255.0,
                vc[1] / 255.0,
                vc[2] / 255.0,
                vc[3] / 255.0,
            ))
        else:
            colors.append((1.0, 1.0, 1.0, 1.0))

    # Generate triangle indices for the 8x8 cell grid.
    for r in range(8):
        for c in range(8):
            # Local vertex indices within the 145-vertex chunk.
            tl = r * 17 + c          # outer top-left
            tr = r * 17 + c + 1      # outer top-right
            center = r * 17 + 9 + c  # inner center
            bl = (r + 1) * 17 + c    # outer bottom-left
            br = (r + 1) * 17 + c + 1  # outer bottom-right

            # Offset by base to get global indices.
            tl += base
            tr += base
            center += base
            bl += base
            br += base

            # 4 triangles per cell (CCW winding for glTF).
            indices.extend([tl, center, tr])      # top
            indices.extend([tr, center, br])      # right
            indices.extend([br, center, bl])      # bottom
            indices.extend([bl, center, tl])      # left


def _build_gltf(output_path, positions, normals, uvs, colors, indices):
    """Construct and write a .glb file from flat vertex/index lists.

    Follows the same binary blob pattern as WMOGltfWriter.
    """
    gltf = pygltflib.GLTF2(
        asset=pygltflib.Asset(version="2.0", generator="wow-pywowlib"),
        scene=0,
        scenes=[pygltflib.Scene(nodes=[0])],
    )

    blob = bytearray()
    attributes = pygltflib.Attributes()

    # --- Index buffer ---
    max_idx = max(indices) if indices else 0
    if max_idx <= 65535:
        idx_fmt = '<H'
        idx_component = pygltflib.UNSIGNED_SHORT
        idx_byte_size = 2
    else:
        idx_fmt = '<I'
        idx_component = pygltflib.UNSIGNED_INT
        idx_byte_size = 4

    idx_offset = len(blob)
    for i in indices:
        blob.extend(_struct.pack(idx_fmt, i))
    idx_length = len(blob) - idx_offset
    # Pad to 4-byte alignment.
    while len(blob) % 4 != 0:
        blob.append(0)

    idx_bv = len(gltf.bufferViews)
    gltf.bufferViews.append(pygltflib.BufferView(
        buffer=0,
        byteOffset=idx_offset,
        byteLength=idx_length,
        target=pygltflib.ELEMENT_ARRAY_BUFFER,
    ))
    idx_acc = len(gltf.accessors)
    gltf.accessors.append(pygltflib.Accessor(
        bufferView=idx_bv,
        componentType=idx_component,
        count=len(indices),
        type=pygltflib.SCALAR,
        max=[max_idx],
        min=[min(indices)] if indices else [0],
    ))

    # --- Position buffer ---
    pos_offset = len(blob)
    pos_min = [float('inf')] * 3
    pos_max = [float('-inf')] * 3
    for p in positions:
        for c in range(3):
            val = float(p[c])
            if val < pos_min[c]:
                pos_min[c] = val
            if val > pos_max[c]:
                pos_max[c] = val
            blob.extend(_struct.pack('<f', val))
    pos_length = len(blob) - pos_offset

    if not positions:
        pos_min = [0.0, 0.0, 0.0]
        pos_max = [0.0, 0.0, 0.0]

    pos_bv = len(gltf.bufferViews)
    gltf.bufferViews.append(pygltflib.BufferView(
        buffer=0,
        byteOffset=pos_offset,
        byteLength=pos_length,
        target=pygltflib.ARRAY_BUFFER,
    ))
    pos_acc = len(gltf.accessors)
    gltf.accessors.append(pygltflib.Accessor(
        bufferView=pos_bv,
        componentType=pygltflib.FLOAT,
        count=len(positions),
        type=pygltflib.VEC3,
        max=pos_max,
        min=pos_min,
    ))
    attributes.POSITION = pos_acc

    # --- Normal buffer ---
    if normals:
        norm_offset = len(blob)
        for n in normals:
            for c in range(3):
                blob.extend(_struct.pack('<f', float(n[c])))
        norm_length = len(blob) - norm_offset

        norm_bv = len(gltf.bufferViews)
        gltf.bufferViews.append(pygltflib.BufferView(
            buffer=0,
            byteOffset=norm_offset,
            byteLength=norm_length,
            target=pygltflib.ARRAY_BUFFER,
        ))
        norm_acc = len(gltf.accessors)
        gltf.accessors.append(pygltflib.Accessor(
            bufferView=norm_bv,
            componentType=pygltflib.FLOAT,
            count=len(normals),
            type=pygltflib.VEC3,
        ))
        attributes.NORMAL = norm_acc

    # --- UV buffer ---
    if uvs:
        uv_offset = len(blob)
        for u in uvs:
            for c in range(2):
                blob.extend(_struct.pack('<f', float(u[c])))
        uv_length = len(blob) - uv_offset

        uv_bv = len(gltf.bufferViews)
        gltf.bufferViews.append(pygltflib.BufferView(
            buffer=0,
            byteOffset=uv_offset,
            byteLength=uv_length,
            target=pygltflib.ARRAY_BUFFER,
        ))
        uv_acc = len(gltf.accessors)
        gltf.accessors.append(pygltflib.Accessor(
            bufferView=uv_bv,
            componentType=pygltflib.FLOAT,
            count=len(uvs),
            type=pygltflib.VEC2,
        ))
        attributes.TEXCOORD_0 = uv_acc

    # --- Vertex color buffer (VEC4 float) ---
    if colors:
        col_offset = len(blob)
        for vc in colors:
            for c in range(4):
                blob.extend(_struct.pack('<f', float(vc[c])))
        col_length = len(blob) - col_offset

        col_bv = len(gltf.bufferViews)
        gltf.bufferViews.append(pygltflib.BufferView(
            buffer=0,
            byteOffset=col_offset,
            byteLength=col_length,
            target=pygltflib.ARRAY_BUFFER,
        ))
        col_acc = len(gltf.accessors)
        gltf.accessors.append(pygltflib.Accessor(
            bufferView=col_bv,
            componentType=pygltflib.FLOAT,
            count=len(colors),
            type=pygltflib.VEC4,
        ))
        attributes.COLOR_0 = col_acc

    # --- Material (simple default) ---
    gltf.materials = [pygltflib.Material(
        name="terrain",
        pbrMetallicRoughness=pygltflib.PbrMetallicRoughness(
            baseColorFactor=[0.6, 0.55, 0.45, 1.0],
            metallicFactor=0.0,
            roughnessFactor=0.9,
        ),
        doubleSided=True,
    )]

    # --- Mesh and node ---
    prim = pygltflib.Primitive(
        attributes=attributes,
        indices=idx_acc,
        material=0,
        mode=pygltflib.TRIANGLES,
    )
    gltf.meshes = [pygltflib.Mesh(name="terrain", primitives=[prim])]
    gltf.nodes = [pygltflib.Node(name="terrain", mesh=0)]

    # --- Finalize ---
    gltf.buffers = [pygltflib.Buffer(byteLength=len(blob))]
    gltf.set_binary_blob(bytes(blob))

    parent = os.path.dirname(output_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    gltf.save_binary(output_path)


def _write_empty_gltf(output_path):
    """Write a minimal empty glTF file."""
    gltf = pygltflib.GLTF2(
        asset=pygltflib.Asset(version="2.0", generator="wow-pywowlib"),
        scene=0,
        scenes=[pygltflib.Scene(nodes=[])],
    )
    gltf.buffers = []
    parent = os.path.dirname(output_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    gltf.save_binary(output_path)


# ---------------------------------------------------------------------------
# Heightmap PNG -> ADT JSON import
# ---------------------------------------------------------------------------

# Default tile center for tile (32, 32) in WoW world coordinates.
_TILE_BASE_X = 17066.666
_TILE_BASE_Y = 17066.666


def _build_default_chunk(index_x, index_y, heightmap_145, area_id):
    """Build a single terrain chunk dict in the ADT JSON format.

    Args:
        index_x: Chunk column index (0-15).
        index_y: Chunk row index (0-15).
        heightmap_145: List of 145 float height values (9x9 outer + 8x8 inner).
        area_id: Area ID for this chunk.

    Returns:
        dict: Terrain chunk compatible with json_to_adt().
    """
    # Chunk position follows WoW convention:
    #   position[0] = tile_base_X - index_y * chunk_size  (north to south)
    #   position[1] = tile_base_Y - index_x * chunk_size  (west to east)
    #   position[2] = base elevation (0.0, heights are absolute)
    pos_x = _TILE_BASE_X - index_y * _CHUNK_SIZE
    pos_y = _TILE_BASE_Y - index_x * _CHUNK_SIZE
    pos_z = 0.0

    return {
        'index_x': index_x,
        'index_y': index_y,
        'flags': 0,
        'area_id': area_id,
        'holes_low_res': 0,
        'position': [round(pos_x, 6), round(pos_y, 6), pos_z],
        'n_layers': 1,
        'n_doodad_refs': 0,
        'n_map_obj_refs': 0,
        'unknown_but_used': 0,
        'low_quality_texture_map': [[0] * 8 for _ in range(8)],
        'no_effect_doodad': [[0] * 8 for _ in range(8)],
        'size_mcal': 0,
        'size_mcsh': 0,
        'size_liquid': 0,
        'unused': 0,
        'heightmap': heightmap_145,
        'normals': [[0, 0, 127]] * _VERTS_PER_CHUNK,
        'texture_layers': [{
            'texture_id': 0,
            'flags': 0,
            'offset_in_mcal': 0,
            'effect_id': 0,
        }],
        'doodad_refs': [],
        'object_refs': [],
        'alpha_maps': [],
        'shadow_map': None,
        'vertex_colors': None,
        'sound_emitters': [],
    }


def heightmap_to_adt(heightmap_path, height_min=0.0, height_max=100.0,
                     area_id=0):
    """Import a grayscale heightmap PNG as ADT JSON data.

    Reads a 129x129 grayscale PNG and maps pixel values [0-255] to height
    values [height_min, height_max]. Produces a full ADT JSON dict compatible
    with json_to_adt() in tools/adt_converter.py.

    Args:
        heightmap_path: Path to 129x129 grayscale PNG.
        height_min: Real-world height for pixel value 0 (black).
        height_max: Real-world height for pixel value 255 (white).
        area_id: Area ID for terrain chunks.

    Returns:
        dict: ADT JSON data compatible with json_to_adt().

    Raises:
        ImportError: If Pillow is not installed.
        ValueError: If the image is not 129x129.
    """
    if not _HAS_PIL:
        raise ImportError("Pillow is required for heightmap import: "
                          "pip install Pillow")

    img = Image.open(heightmap_path).convert('L')
    if img.size != (_TILE_VERTS_PER_SIDE, _TILE_VERTS_PER_SIDE):
        raise ValueError(
            "Heightmap must be {}x{} pixels, got {}x{}".format(
                _TILE_VERTS_PER_SIDE, _TILE_VERTS_PER_SIDE,
                img.size[0], img.size[1]))

    # Build a full 129x129 height grid from pixel values.
    h_range = height_max - height_min
    grid = [[0.0] * _TILE_VERTS_PER_SIDE for _ in range(_TILE_VERTS_PER_SIDE)]
    for py in range(_TILE_VERTS_PER_SIDE):
        for px in range(_TILE_VERTS_PER_SIDE):
            pixel = img.getpixel((px, py))
            grid[py][px] = height_min + (pixel / 255.0) * h_range

    # Build 256 terrain chunks (16x16 grid).
    terrain_chunks = []
    for cy in range(_CHUNKS_PER_SIDE):
        for cx in range(_CHUNKS_PER_SIDE):
            # Extract the 9x9 outer vertices for this chunk from the grid.
            # Grid layout: index_y -> image rows (top to bottom),
            #              index_x -> image columns (left to right).
            outer = [[0.0] * _OUTER_COLS for _ in range(_OUTER_ROWS)]
            for row in range(_OUTER_ROWS):
                for col in range(_OUTER_COLS):
                    gx = cx * (_OUTER_COLS - 1) + col
                    gy = cy * (_OUTER_COLS - 1) + row
                    outer[row][col] = grid[gy][gx]

            # Build the 145-value heightmap array.
            # Layout: alternating outer row (9 values) and inner row (8 values).
            # Since chunk position[2] = 0, heightmap values ARE the absolute
            # heights (offsets from base elevation 0).
            heightmap_145 = []
            for row in range(_OUTER_ROWS):
                # Outer row: 9 values.
                for col in range(_OUTER_COLS):
                    heightmap_145.append(round(outer[row][col], 6))

                # Inner row: 8 values (average of surrounding 4 outer verts).
                # No inner row after the last outer row.
                if row < _INNER_ROWS:
                    for col in range(_INNER_COLS):
                        tl = outer[row][col]
                        tr = outer[row][col + 1]
                        bl = outer[row + 1][col]
                        br = outer[row + 1][col + 1]
                        inner_h = (tl + tr + bl + br) / 4.0
                        heightmap_145.append(round(inner_h, 6))

            chunk = _build_default_chunk(cx, cy, heightmap_145, area_id)
            terrain_chunks.append(chunk)

    result = {
        '_meta': {
            'filename': 'imported_heightmap.adt',
            'version': 18,
            'mhdr_flags': 0,
            'mamp_value': 0,
            'chunk_summary': {
                'textures': 1,
                'models': 0,
                'wmo_names': 0,
                'doodad_placements': 0,
                'wmo_placements': 0,
                'terrain_chunks': len(terrain_chunks),
            },
        },
        'textures': ['Tileset\\Generic\\Black.blp'],
        'models': [],
        'wmo_names': [],
        'mmid_offsets': [],
        'mwid_offsets': [],
        'doodad_placements': [],
        'wmo_placements': [],
        'terrain_chunks': terrain_chunks,
    }

    log.info("Imported heightmap: %s (%dx%d, height range %.1f - %.1f, "
             "%d chunks)",
             heightmap_path, _TILE_VERTS_PER_SIDE, _TILE_VERTS_PER_SIDE,
             height_min, height_max, len(terrain_chunks))

    return result


# ---------------------------------------------------------------------------
# glTF terrain mesh -> ADT JSON import
# ---------------------------------------------------------------------------

def _read_gltf_accessor_vec(gltf, blob, acc_idx, components):
    """Read a VEC2/VEC3/VEC4 accessor into a list of tuples.

    Args:
        gltf: The GLTF2 object.
        blob: Binary blob from gltf.binary_blob().
        acc_idx: Accessor index.
        components: Number of components per element (2, 3, or 4).

    Returns:
        list[tuple]: List of tuples with the specified number of components.
    """
    if acc_idx is None:
        return []
    acc = gltf.accessors[acc_idx]
    bv = gltf.bufferViews[acc.bufferView]
    offset = bv.byteOffset + (acc.byteOffset or 0)
    stride = components * 4  # float32
    result = []
    fmt = '<' + 'f' * components
    for i in range(acc.count):
        vals = _struct.unpack_from(fmt, blob, offset + i * stride)
        result.append(tuple(vals))
    return result


def gltf_to_adt(glb_path, area_id=0):
    """Import a glTF terrain mesh as ADT JSON data.

    Reads vertex positions from the glTF mesh and extracts height values
    by mapping glTF coordinates back to WoW ADT format.

    The coordinate mapping reversal:
      glTF(X, Y_up, Z) -> WoW(X=glTF_X, Y=glTF_Z, Z_height=glTF_Y)

    Args:
        glb_path: Path to .glb terrain mesh file.
        area_id: Area ID for terrain chunks.

    Returns:
        dict: ADT JSON data compatible with json_to_adt().

    Raises:
        ImportError: If pygltflib is not installed.
        ValueError: If the glTF file contains no mesh data.
    """
    if not _HAS_GLTFLIB:
        raise ImportError("pygltflib is required for glTF import: "
                          "pip install pygltflib")

    gltf = pygltflib.GLTF2.load_binary(glb_path)
    blob = gltf.binary_blob()

    if not blob:
        raise ValueError("glTF file contains no binary data")

    # Collect all vertex positions and optional normals/colors from all
    # mesh primitives.
    all_positions = []
    all_normals = []
    all_colors = []
    has_normals = False
    has_colors = False

    for mesh in gltf.meshes:
        for prim in mesh.primitives:
            if prim.attributes.POSITION is not None:
                positions = _read_gltf_accessor_vec(
                    gltf, blob, prim.attributes.POSITION, 3)
                all_positions.extend(positions)

            if prim.attributes.NORMAL is not None:
                normals = _read_gltf_accessor_vec(
                    gltf, blob, prim.attributes.NORMAL, 3)
                all_normals.extend(normals)
                has_normals = True

            if prim.attributes.COLOR_0 is not None:
                colors = _read_gltf_accessor_vec(
                    gltf, blob, prim.attributes.COLOR_0, 4)
                all_colors.extend(colors)
                has_colors = True

    if not all_positions:
        raise ValueError("glTF file contains no vertex positions")

    # Reverse coordinate mapping: glTF(X, Y_up, Z) -> WoW(X, Z, Y)
    # wow_x = gltf_x, wow_y = gltf_z, wow_z(height) = gltf_y
    wow_positions = []
    for gx, gy, gz in all_positions:
        wow_positions.append((gx, gz, gy))  # (wow_x, wow_y, wow_z)

    # Find bounding box of all WoW positions.
    min_x = min(p[0] for p in wow_positions)
    max_x = max(p[0] for p in wow_positions)
    min_y = min(p[1] for p in wow_positions)
    max_y = max(p[1] for p in wow_positions)

    # Determine tile dimensions and chunk layout.
    # WoW chunks: position[0] decreases south (index_y increases),
    #             position[1] decreases east (index_x increases).
    # The top-left corner (max_x, max_y) corresponds to chunk (0, 0).
    tile_span_x = max_x - min_x  # north-south span
    tile_span_y = max_y - min_y  # east-west span

    # Calculate number of chunks needed (minimum 16x16 for a full tile).
    n_chunks_y = max(1, int(round(tile_span_x / _CHUNK_SIZE)))
    n_chunks_x = max(1, int(round(tile_span_y / _CHUNK_SIZE)))
    # Clamp to standard ADT dimensions.
    n_chunks_x = min(n_chunks_x, _CHUNKS_PER_SIDE)
    n_chunks_y = min(n_chunks_y, _CHUNKS_PER_SIDE)

    # Build a height grid by snapping vertex positions to the nearest
    # chunk/vertex grid position. Use 129x129 outer vertex resolution.
    grid_w = n_chunks_x * (_OUTER_COLS - 1) + 1
    grid_h = n_chunks_y * (_OUTER_COLS - 1) + 1
    height_grid = [[0.0] * grid_w for _ in range(grid_h)]
    weight_grid = [[0] * grid_w for _ in range(grid_h)]

    # Map positions to grid cells.
    cell_spacing_x = tile_span_x / (grid_h - 1) if grid_h > 1 else 1.0
    cell_spacing_y = tile_span_y / (grid_w - 1) if grid_w > 1 else 1.0

    for wow_x, wow_y, wow_z in wow_positions:
        # Map position to grid index.
        # Row: max_x is row 0, min_x is last row (south).
        # Col: max_y is col 0, min_y is last col (east).
        if grid_h > 1:
            row_f = (max_x - wow_x) / cell_spacing_x
        else:
            row_f = 0.0
        if grid_w > 1:
            col_f = (max_y - wow_y) / cell_spacing_y
        else:
            col_f = 0.0

        row = int(round(row_f))
        col = int(round(col_f))

        # Clamp to grid bounds.
        row = max(0, min(row, grid_h - 1))
        col = max(0, min(col, grid_w - 1))

        height_grid[row][col] += wow_z
        weight_grid[row][col] += 1

    # Average accumulated heights.
    for r in range(grid_h):
        for c in range(grid_w):
            if weight_grid[r][c] > 0:
                height_grid[r][c] /= weight_grid[r][c]

    # Fill any unsampled grid cells by nearest-neighbor interpolation.
    _fill_empty_grid_cells(height_grid, weight_grid, grid_h, grid_w)

    # Reverse-map normals if available.
    normal_grid = None
    if has_normals and len(all_normals) == len(all_positions):
        normal_grid = [[[0.0, 0.0, 0.0] for _ in range(grid_w)]
                       for _ in range(grid_h)]
        normal_weight = [[0] * grid_w for _ in range(grid_h)]

        for idx, (wow_x, wow_y, _wow_z) in enumerate(wow_positions):
            if grid_h > 1:
                row_f = (max_x - wow_x) / cell_spacing_x
            else:
                row_f = 0.0
            if grid_w > 1:
                col_f = (max_y - wow_y) / cell_spacing_y
            else:
                col_f = 0.0
            row = max(0, min(int(round(row_f)), grid_h - 1))
            col = max(0, min(int(round(col_f)), grid_w - 1))

            # Reverse glTF normal -> WoW normal:
            # glTF(nx, ny_up, nz) -> WoW(nx, nz, ny)
            gn = all_normals[idx]
            normal_grid[row][col][0] += gn[0]  # wow_nx
            normal_grid[row][col][1] += gn[2]  # wow_ny (from gltf_z)
            normal_grid[row][col][2] += gn[1]  # wow_nz_up (from gltf_y)
            normal_weight[row][col] += 1

        for r in range(grid_h):
            for c in range(grid_w):
                w = normal_weight[r][c]
                if w > 0:
                    for comp in range(3):
                        normal_grid[r][c][comp] /= w

    # Reverse-map vertex colors if available.
    color_grid = None
    if has_colors and len(all_colors) == len(all_positions):
        color_grid = [[[1.0, 1.0, 1.0, 1.0] for _ in range(grid_w)]
                      for _ in range(grid_h)]
        color_weight = [[0] * grid_w for _ in range(grid_h)]

        for idx, (wow_x, wow_y, _wow_z) in enumerate(wow_positions):
            if grid_h > 1:
                row_f = (max_x - wow_x) / cell_spacing_x
            else:
                row_f = 0.0
            if grid_w > 1:
                col_f = (max_y - wow_y) / cell_spacing_y
            else:
                col_f = 0.0
            row = max(0, min(int(round(row_f)), grid_h - 1))
            col = max(0, min(int(round(col_f)), grid_w - 1))

            vc = all_colors[idx]
            for comp in range(4):
                color_grid[row][col][comp] += vc[comp]
            color_weight[row][col] += 1

        for r in range(grid_h):
            for c in range(grid_w):
                w = color_weight[r][c]
                if w > 0:
                    for comp in range(4):
                        color_grid[r][c][comp] /= w

    # Build terrain chunks from the grid.
    terrain_chunks = []
    for cy in range(n_chunks_y):
        for cx in range(n_chunks_x):
            # Extract outer vertices for this chunk.
            outer = [[0.0] * _OUTER_COLS for _ in range(_OUTER_ROWS)]
            for row in range(_OUTER_ROWS):
                for col in range(_OUTER_COLS):
                    gr = cy * (_OUTER_COLS - 1) + row
                    gc = cx * (_OUTER_COLS - 1) + col
                    if gr < grid_h and gc < grid_w:
                        outer[row][col] = height_grid[gr][gc]

            # Build 145-value heightmap.
            heightmap_145 = []
            for row in range(_OUTER_ROWS):
                for col in range(_OUTER_COLS):
                    heightmap_145.append(round(outer[row][col], 6))
                if row < _INNER_ROWS:
                    for col in range(_INNER_COLS):
                        tl = outer[row][col]
                        tr = outer[row][col + 1]
                        bl = outer[row + 1][col]
                        br = outer[row + 1][col + 1]
                        inner_h = (tl + tr + bl + br) / 4.0
                        heightmap_145.append(round(inner_h, 6))

            chunk = _build_default_chunk(cx, cy, heightmap_145, area_id)

            # Override normals if extracted from glTF.
            if normal_grid is not None:
                chunk_normals = []
                for v_idx in range(_VERTS_PER_CHUNK):
                    row_in_chunk = v_idx // 17
                    col_in_row = v_idx % 17

                    if col_in_row < 9:
                        gr = cy * (_OUTER_COLS - 1) + row_in_chunk
                        gc = cx * (_OUTER_COLS - 1) + col_in_row
                    else:
                        # Inner vertex: average surrounding outer normals.
                        inner_col = col_in_row - 9
                        inner_row = row_in_chunk
                        gr = cy * (_OUTER_COLS - 1) + inner_row
                        gc = cx * (_OUTER_COLS - 1) + inner_col
                        # Use the outer vertex at same position as approximation.

                    if gr < grid_h and gc < grid_w:
                        n = normal_grid[gr][gc]
                        # Convert to int8 [-127..127] WoW format.
                        nx = max(-127, min(127, int(round(n[0] * 127.0))))
                        ny = max(-127, min(127, int(round(n[1] * 127.0))))
                        nz = max(-127, min(127, int(round(n[2] * 127.0))))
                        chunk_normals.append([nx, ny, nz])
                    else:
                        chunk_normals.append([0, 0, 127])
                chunk['normals'] = chunk_normals

            # Override vertex colors if extracted from glTF.
            if color_grid is not None:
                chunk['flags'] |= 0x40  # HAS_MCCV flag
                vertex_colors = []
                for v_idx in range(_VERTS_PER_CHUNK):
                    row_in_chunk = v_idx // 17
                    col_in_row = v_idx % 17

                    if col_in_row < 9:
                        gr = cy * (_OUTER_COLS - 1) + row_in_chunk
                        gc = cx * (_OUTER_COLS - 1) + col_in_row
                    else:
                        inner_col = col_in_row - 9
                        inner_row = row_in_chunk
                        gr = cy * (_OUTER_COLS - 1) + inner_row
                        gc = cx * (_OUTER_COLS - 1) + inner_col

                    if gr < grid_h and gc < grid_w:
                        vc = color_grid[gr][gc]
                        r = max(0, min(255, int(round(vc[0] * 255.0))))
                        g = max(0, min(255, int(round(vc[1] * 255.0))))
                        b = max(0, min(255, int(round(vc[2] * 255.0))))
                        a = max(0, min(255, int(round(vc[3] * 255.0))))
                        vertex_colors.append([r, g, b, a])
                    else:
                        vertex_colors.append([255, 255, 255, 255])
                chunk['vertex_colors'] = vertex_colors

            terrain_chunks.append(chunk)

    result = {
        '_meta': {
            'filename': 'imported_gltf.adt',
            'version': 18,
            'mhdr_flags': 0,
            'mamp_value': 0,
            'chunk_summary': {
                'textures': 1,
                'models': 0,
                'wmo_names': 0,
                'doodad_placements': 0,
                'wmo_placements': 0,
                'terrain_chunks': len(terrain_chunks),
            },
        },
        'textures': ['Tileset\\Generic\\Black.blp'],
        'models': [],
        'wmo_names': [],
        'mmid_offsets': [],
        'mwid_offsets': [],
        'doodad_placements': [],
        'wmo_placements': [],
        'terrain_chunks': terrain_chunks,
    }

    log.info("Imported glTF terrain: %s (%d vertices, %d chunks)",
             glb_path, len(all_positions), len(terrain_chunks))

    return result


def _fill_empty_grid_cells(height_grid, weight_grid, grid_h, grid_w):
    """Fill grid cells with zero weight by averaging nearest valid neighbors.

    Modifies height_grid in place. Uses iterative expansion from known cells.
    """
    # Check if there are any empty cells at all.
    has_empty = False
    for r in range(grid_h):
        for c in range(grid_w):
            if weight_grid[r][c] == 0:
                has_empty = True
                break
        if has_empty:
            break

    if not has_empty:
        return

    # Iterative flood-fill: expand from cells with data.
    max_iters = grid_h + grid_w  # Worst case: fill from one corner.
    for _ in range(max_iters):
        filled_any = False
        for r in range(grid_h):
            for c in range(grid_w):
                if weight_grid[r][c] > 0:
                    continue
                # Average valid neighbors.
                total = 0.0
                count = 0
                for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nr, nc = r + dr, c + dc
                    if (0 <= nr < grid_h and 0 <= nc < grid_w
                            and weight_grid[nr][nc] > 0):
                        total += height_grid[nr][nc]
                        count += 1
                if count > 0:
                    height_grid[r][c] = total / count
                    weight_grid[r][c] = 1
                    filled_any = True
        if not filled_any:
            break
