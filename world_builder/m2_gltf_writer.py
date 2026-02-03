"""
M2 model to glTF 2.0 converter for WoW WotLK 3.3.5a.

Converts M2 models (creatures, NPCs, items, doodads) to glTF 2.0 binary
(.glb) format for 3D web preview. Follows the same binary data writing
pattern as WMOGltfWriter in intermediate_format.py.

Dependencies: pygltflib (already used by WMOGltfWriter)
"""

import os
import struct as _struct
import logging

log = logging.getLogger(__name__)

try:
    import pygltflib
    _HAS_GLTFLIB = True
except ImportError:
    pygltflib = None
    _HAS_GLTFLIB = False


class M2GltfWriter(object):
    """
    Writes M2 model geometry as a glTF 2.0 binary (.glb) file.

    Each submesh becomes a primitive in the glTF mesh. Material
    references are stored in material extras with WoW texture paths.
    Bone weights and indices are written as _WEIGHTS_0 and _JOINTS_0
    vertex attributes for skeletal animation support.
    """

    def __init__(self, output_path):
        """
        Args:
            output_path: Path to write the .glb file to.
        """
        if not _HAS_GLTFLIB:
            raise ImportError("pygltflib is required for glTF M2 format")
        self.output_path = output_path

    def write_from_m2(self, m2_file, skin_index=0):
        """
        Write an M2File to glTF.

        Extracts geometry from the M2 root vertices and the specified skin
        profile (LoD level), groups triangles by submesh, resolves texture
        paths through the texture lookup chain, and writes a .glb file.

        Args:
            m2_file: M2File instance (already read with skins loaded).
            skin_index: Which skin/LoD to use (default 0 = highest detail).
        """
        if skin_index >= len(m2_file.skins):
            raise ValueError(
                "skin_index {} out of range, model has {} skins".format(
                    skin_index, len(m2_file.skins)))

        skin = m2_file.skins[skin_index]
        root = m2_file.root

        # Build material list from texture units
        materials = self._extract_materials(root, skin)

        # Build submesh geometry
        submeshes = self._extract_submeshes(root, skin, materials)

        # Write glTF
        self.write(submeshes, materials)

    def write(self, submeshes, materials):
        """
        Write geometry directly to a .glb file.

        Args:
            submeshes: list of dicts, each with:
                - 'name': submesh display name
                - 'vertices': list of (x,y,z) position tuples
                - 'normals': list of (x,y,z) normal tuples
                - 'uvs': list of (u,v) tuples
                - 'indices': flat list of triangle vertex indices
                - 'material_index': index into materials list
                - 'bone_weights': list of (w0,w1,w2,w3) float tuples, or None
                - 'bone_indices': list of (j0,j1,j2,j3) int tuples, or None
            materials: list of dicts with 'name', 'texture1', and optional
                extras like 'blend_mode', 'flags'.
        """
        gltf = pygltflib.GLTF2(
            asset=pygltflib.Asset(version="2.0", generator="wow-pywowlib-m2"),
            scene=0,
            scenes=[pygltflib.Scene(nodes=[])],
        )

        blob = bytearray()

        # Build glTF materials
        gltf.materials = self._build_materials(materials)

        # Single mesh node for the entire M2 model
        node_idx = len(gltf.nodes)
        gltf.scenes[0].nodes.append(node_idx)

        mesh_idx = len(gltf.meshes)
        model_name = materials[0].get('name', 'M2Model') if materials else 'M2Model'
        gltf.nodes.append(pygltflib.Node(name=model_name, mesh=mesh_idx))

        # Build primitives from submeshes
        primitives = []
        for submesh in submeshes:
            verts = submesh['vertices']
            norms = submesh['normals']
            uvs = submesh['uvs']
            indices = submesh['indices']
            mat_idx = submesh.get('material_index', 0)
            bone_w = submesh.get('bone_weights')
            bone_j = submesh.get('bone_indices')

            if not verts or not indices:
                continue

            prim = self._write_primitive_data(
                gltf, blob, verts, norms, uvs, indices,
                mat_idx, bone_w, bone_j)
            prim.extras = {
                "submesh_name": submesh.get('name', ''),
                "skin_section_id": submesh.get('skin_section_id', 0),
            }
            primitives.append(prim)

        gltf.meshes.append(pygltflib.Mesh(
            name=model_name, primitives=primitives))

        # Set the binary blob
        gltf.buffers = [pygltflib.Buffer(byteLength=len(blob))]
        gltf.set_binary_blob(bytes(blob))

        # Write .glb
        parent = os.path.dirname(self.output_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        gltf.save_binary(self.output_path)

        log.info("Wrote M2 glTF binary: %s (%d bytes, %d submeshes)",
                 self.output_path, len(blob), len(primitives))

    def _extract_materials(self, root, skin):
        """
        Extract material definitions from M2 texture units.

        Walks the skin texture_units -> texture_combo_index ->
        root.texture_lookup_table -> root.textures chain to resolve
        texture filenames.

        Returns a list of material dicts.
        """
        materials = []
        seen = {}

        for tu in skin.texture_units:
            combo_idx = tu.texture_combo_index

            # Resolve texture path through the lookup chain
            tex_path = ''
            if combo_idx < len(root.texture_lookup_table):
                tex_idx = root.texture_lookup_table[combo_idx]
                if tex_idx < len(root.textures):
                    tex_path = root.textures[tex_idx].filename.value

            # Resolve M2Material properties
            mat_flags = 0
            blend_mode = 0
            if tu.material_index < len(root.materials):
                m2_mat = root.materials[tu.material_index]
                mat_flags = m2_mat.flags
                blend_mode = m2_mat.blending_mode

            # Deduplicate materials by texture + blend combo
            mat_key = (tex_path, mat_flags, blend_mode)
            if mat_key in seen:
                continue

            seen[mat_key] = len(materials)
            materials.append({
                'name': tex_path or 'material_{}'.format(len(materials)),
                'texture1': tex_path,
                'flags': mat_flags,
                'blend_mode': blend_mode,
            })

        # Ensure at least one default material
        if not materials:
            materials.append({
                'name': 'default',
                'texture1': '',
                'flags': 0,
                'blend_mode': 0,
            })

        return materials

    def _extract_submeshes(self, root, skin, materials):
        """
        Extract submesh geometry from M2 skin profile.

        For each submesh in the skin, extracts the vertex positions,
        normals, UVs, bone weights/indices, and triangle indices using
        the M2 double-indirection scheme:
            skin.triangle_indices -> skin.vertex_indices -> root.vertices

        Returns a list of submesh dicts ready for write().
        """
        result = []

        # Build a mapping from texture unit -> material index
        # (texture units reference submeshes via skin_section_index)
        submesh_to_mat = {}
        mat_key_to_idx = {}
        for i, mat in enumerate(materials):
            key = (mat['texture1'], mat['flags'], mat['blend_mode'])
            mat_key_to_idx[key] = i

        for tu in skin.texture_units:
            combo_idx = tu.texture_combo_index
            tex_path = ''
            if combo_idx < len(root.texture_lookup_table):
                tex_idx = root.texture_lookup_table[combo_idx]
                if tex_idx < len(root.textures):
                    tex_path = root.textures[tex_idx].filename.value

            mat_flags = 0
            blend_mode = 0
            if tu.material_index < len(root.materials):
                m2_mat = root.materials[tu.material_index]
                mat_flags = m2_mat.flags
                blend_mode = m2_mat.blending_mode

            mat_key = (tex_path, mat_flags, blend_mode)
            mat_idx = mat_key_to_idx.get(mat_key, 0)
            submesh_to_mat[tu.skin_section_index] = mat_idx

        for sub_idx, submesh in enumerate(skin.submeshes):
            verts = []
            norms = []
            uvs = []
            bone_weights = []
            bone_indices = []
            indices = []

            # Map from root vertex index to local vertex index for this
            # submesh, so triangle indices reference local positions.
            root_to_local = {}

            # Extract triangle indices for this submesh.
            # skin.triangle_indices values point into skin.vertex_indices,
            # which in turn point into root.vertices.
            for i in range(submesh.index_start,
                           submesh.index_start + submesh.index_count):
                if i >= len(skin.triangle_indices):
                    break

                skin_vi = skin.triangle_indices[i]

                if skin_vi >= len(skin.vertex_indices):
                    continue

                root_vi = skin.vertex_indices[skin_vi]

                if root_vi not in root_to_local:
                    local_idx = len(verts)
                    root_to_local[root_vi] = local_idx

                    if root_vi < len(root.vertices):
                        v = root.vertices[root_vi]
                        verts.append(v.pos)
                        norms.append(v.normal)
                        uvs.append(v.tex_coords)

                        # Normalize bone weights to [0.0, 1.0] range
                        bw = v.bone_weights
                        w_sum = sum(bw)
                        if w_sum > 0:
                            bone_weights.append(tuple(
                                w / 255.0 for w in bw))
                        else:
                            bone_weights.append((1.0, 0.0, 0.0, 0.0))
                        bone_indices.append(v.bone_indices)
                    else:
                        verts.append((0.0, 0.0, 0.0))
                        norms.append((0.0, 0.0, 1.0))
                        uvs.append((0.0, 0.0))
                        bone_weights.append((1.0, 0.0, 0.0, 0.0))
                        bone_indices.append((0, 0, 0, 0))

                indices.append(root_to_local[root_vi])

            mat_idx = submesh_to_mat.get(sub_idx, 0)

            result.append({
                'name': 'Submesh_{:03d}'.format(sub_idx),
                'skin_section_id': submesh.skin_section_id,
                'vertices': verts,
                'normals': norms,
                'uvs': uvs,
                'indices': indices,
                'material_index': mat_idx,
                'bone_weights': bone_weights,
                'bone_indices': bone_indices,
            })

        return result

    def _build_materials(self, materials):
        """Build glTF Material list from M2 material dicts."""
        result = []
        for mat in materials:
            tex1 = mat.get('texture1', '')
            gltf_mat = pygltflib.Material(
                name=tex1 or mat.get('name', 'material'),
                extras={
                    'blend_mode': mat.get('blend_mode', 0),
                    'flags': mat.get('flags', 0),
                    'texture1': tex1,
                },
            )
            result.append(gltf_mat)
        return result

    def _write_primitive_data(self, gltf, blob, verts, normals, uvs,
                              indices, material_idx, bone_weights=None,
                              bone_indices=None):
        """
        Write vertex/index data to the binary blob and create accessors.

        Follows the same pattern as WMOGltfWriter._write_primitive_data:
        binary blob accumulation, BufferView per data type, Accessor with
        min/max for positions, 4-byte alignment padding.
        """
        attributes = pygltflib.Attributes()

        # --- Indices ---
        max_idx = max(indices) if indices else 0
        if max_idx <= 65535:
            idx_fmt = '<H'
            idx_component = pygltflib.UNSIGNED_SHORT
        else:
            idx_fmt = '<I'
            idx_component = pygltflib.UNSIGNED_INT

        idx_offset = len(blob)
        for i in indices:
            blob.extend(_struct.pack(idx_fmt, i))
        idx_length = len(blob) - idx_offset
        # Pad to 4-byte alignment
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

        # --- Positions ---
        pos_offset = len(blob)
        mins = [float('inf')] * 3
        maxs = [float('-inf')] * 3
        for v in verts:
            for c in range(3):
                val = float(v[c]) if c < len(v) else 0.0
                if val < mins[c]:
                    mins[c] = val
                if val > maxs[c]:
                    maxs[c] = val
                blob.extend(_struct.pack('<f', val))
        pos_length = len(blob) - pos_offset

        if not verts:
            mins = [0.0, 0.0, 0.0]
            maxs = [0.0, 0.0, 0.0]

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
            count=len(verts),
            type=pygltflib.VEC3,
            max=maxs,
            min=mins,
        ))
        attributes.POSITION = pos_acc

        # --- Normals ---
        if normals:
            norm_offset = len(blob)
            for n in normals:
                for c in range(3):
                    val = float(n[c]) if c < len(n) else 0.0
                    blob.extend(_struct.pack('<f', val))
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

        # --- UVs ---
        if uvs:
            uv_offset = len(blob)
            for u in uvs:
                for c in range(2):
                    val = float(u[c]) if c < len(u) else 0.0
                    blob.extend(_struct.pack('<f', val))
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

        # --- Bone Joints (_JOINTS_0) ---
        if bone_indices:
            joints_offset = len(blob)
            for j in bone_indices:
                for c in range(4):
                    val = int(j[c]) if c < len(j) else 0
                    blob.extend(_struct.pack('<B', val & 0xFF))
            joints_length = len(blob) - joints_offset
            # Pad to 4-byte alignment
            while len(blob) % 4 != 0:
                blob.append(0)

            joints_bv = len(gltf.bufferViews)
            gltf.bufferViews.append(pygltflib.BufferView(
                buffer=0,
                byteOffset=joints_offset,
                byteLength=joints_length,
                target=pygltflib.ARRAY_BUFFER,
            ))
            joints_acc = len(gltf.accessors)
            gltf.accessors.append(pygltflib.Accessor(
                bufferView=joints_bv,
                componentType=pygltflib.UNSIGNED_BYTE,
                count=len(bone_indices),
                type=pygltflib.VEC4,
            ))
            attributes.JOINTS_0 = joints_acc

        # --- Bone Weights (_WEIGHTS_0) ---
        if bone_weights:
            weights_offset = len(blob)
            for w in bone_weights:
                for c in range(4):
                    val = float(w[c]) if c < len(w) else 0.0
                    blob.extend(_struct.pack('<f', val))
            weights_length = len(blob) - weights_offset

            weights_bv = len(gltf.bufferViews)
            gltf.bufferViews.append(pygltflib.BufferView(
                buffer=0,
                byteOffset=weights_offset,
                byteLength=weights_length,
                target=pygltflib.ARRAY_BUFFER,
            ))
            weights_acc = len(gltf.accessors)
            gltf.accessors.append(pygltflib.Accessor(
                bufferView=weights_bv,
                componentType=pygltflib.FLOAT,
                count=len(bone_weights),
                type=pygltflib.VEC4,
            ))
            attributes.WEIGHTS_0 = weights_acc

        prim = pygltflib.Primitive(
            attributes=attributes,
            indices=idx_acc,
            material=material_idx,
            mode=pygltflib.TRIANGLES,
        )

        return prim


class M2GltfReader(object):
    """
    Reads M2 model geometry from a glTF 2.0 binary (.glb) file.

    Reconstructs submesh geometry and material definitions from the glTF
    scene structure written by M2GltfWriter. Each primitive becomes a
    submesh with positions, normals, UVs, bone indices, and bone weights.
    """

    def __init__(self, glb_path):
        """
        Args:
            glb_path: Path to the .glb file.
        """
        if not _HAS_GLTFLIB:
            raise ImportError("pygltflib is required for glTF M2 format")
        self.glb_path = glb_path

    def read(self):
        """
        Read geometry and material extras from the .glb file.

        Returns:
            tuple: (materials, submeshes)
                materials: list of dicts with 'name', 'texture1',
                    'blend_mode', 'flags' from glTF material extras.
                submeshes: list of dicts, each with:
                    - 'name': submesh display name
                    - 'vertices': list of (x,y,z) position tuples
                    - 'normals': list of (x,y,z) normal tuples
                    - 'uvs': list of (u,v) tuples
                    - 'indices': list of (i0,i1,i2) triangle tuples
                    - 'material_index': index into materials list
                    - 'bone_weights': list of (w0,w1,w2,w3) float tuples
                    - 'bone_indices': list of (j0,j1,j2,j3) int tuples
                    - 'skin_section_id': int
        """
        gltf = pygltflib.GLTF2.load_binary(self.glb_path)
        blob = gltf.binary_blob()

        # Extract materials from glTF material extras
        materials = []
        for mat in gltf.materials:
            extras = mat.extras if mat.extras else {}
            materials.append({
                'name': mat.name or '',
                'texture1': extras.get('texture1', ''),
                'blend_mode': extras.get('blend_mode', 0),
                'flags': extras.get('flags', 0),
            })

        # Ensure at least one default material
        if not materials:
            materials.append({
                'name': 'default',
                'texture1': '',
                'blend_mode': 0,
                'flags': 0,
            })

        # Extract submeshes from mesh primitives
        submeshes = []
        scene = gltf.scenes[gltf.scene]
        for node_idx in scene.nodes:
            node = gltf.nodes[node_idx]
            if node.mesh is None:
                continue

            mesh = gltf.meshes[node.mesh]
            for prim in mesh.primitives:
                submesh = self._read_primitive(gltf, blob, prim)
                submeshes.append(submesh)

        return materials, submeshes

    def _read_primitive(self, gltf, blob, prim):
        """Read a single primitive into a submesh dict."""
        # Read positions
        verts = self._read_accessor_vec(
            gltf, blob, prim.attributes.POSITION, 3)

        # Read normals
        normals = []
        if prim.attributes.NORMAL is not None:
            normals = self._read_accessor_vec(
                gltf, blob, prim.attributes.NORMAL, 3)

        # Read UVs
        uvs = []
        if prim.attributes.TEXCOORD_0 is not None:
            uvs = self._read_accessor_vec(
                gltf, blob, prim.attributes.TEXCOORD_0, 2)

        # Read bone joints (VEC4 unsigned byte)
        bone_indices = []
        if prim.attributes.JOINTS_0 is not None:
            bone_indices = self._read_accessor_vec4_ubyte(
                gltf, blob, prim.attributes.JOINTS_0)

        # Read bone weights (VEC4 float)
        bone_weights = []
        if prim.attributes.WEIGHTS_0 is not None:
            bone_weights = self._read_accessor_vec(
                gltf, blob, prim.attributes.WEIGHTS_0, 4)

        # Read triangle indices
        flat_indices = self._read_accessor_scalar(gltf, blob, prim.indices)

        # Convert flat index list to triangle tuples
        triangles = []
        for i in range(0, len(flat_indices), 3):
            if i + 2 < len(flat_indices):
                triangles.append(
                    (flat_indices[i], flat_indices[i + 1], flat_indices[i + 2]))

        # Material index
        mat_idx = prim.material if prim.material is not None else 0

        # Read skin_section_id from primitive extras
        extras = prim.extras if prim.extras else {}
        skin_section_id = extras.get('skin_section_id', 0)
        submesh_name = extras.get('submesh_name', '')

        return {
            'name': submesh_name,
            'vertices': verts,
            'normals': normals,
            'uvs': uvs,
            'indices': triangles,
            'material_index': mat_idx,
            'bone_weights': bone_weights,
            'bone_indices': bone_indices,
            'skin_section_id': skin_section_id,
        }

    def _read_accessor_vec(self, gltf, blob, acc_idx, components):
        """Read a VEC2/VEC3/VEC4 float accessor into a list of tuples."""
        if acc_idx is None:
            return []
        acc = gltf.accessors[acc_idx]
        bv = gltf.bufferViews[acc.bufferView]
        offset = bv.byteOffset + (acc.byteOffset or 0)
        result = []
        for i in range(acc.count):
            vals = _struct.unpack_from(
                '<' + 'f' * components, blob, offset + i * 4 * components)
            result.append(tuple(vals))
        return result

    def _read_accessor_vec4_ubyte(self, gltf, blob, acc_idx):
        """Read a VEC4 unsigned byte accessor (JOINTS_0) into a list of tuples."""
        if acc_idx is None:
            return []
        acc = gltf.accessors[acc_idx]
        bv = gltf.bufferViews[acc.bufferView]
        offset = bv.byteOffset + (acc.byteOffset or 0)
        result = []
        for i in range(acc.count):
            vals = _struct.unpack_from('<BBBB', blob, offset + i * 4)
            result.append(tuple(vals))
        return result

    def _read_accessor_scalar(self, gltf, blob, acc_idx):
        """Read a SCALAR accessor (indices) into a list of ints."""
        if acc_idx is None:
            return []
        acc = gltf.accessors[acc_idx]
        bv = gltf.bufferViews[acc.bufferView]
        offset = bv.byteOffset + (acc.byteOffset or 0)
        result = []
        if acc.componentType == pygltflib.UNSIGNED_SHORT:
            for i in range(acc.count):
                val = _struct.unpack_from('<H', blob, offset + i * 2)[0]
                result.append(val)
        elif acc.componentType == pygltflib.UNSIGNED_INT:
            for i in range(acc.count):
                val = _struct.unpack_from('<I', blob, offset + i * 4)[0]
                result.append(val)
        elif acc.componentType == pygltflib.UNSIGNED_BYTE:
            for i in range(acc.count):
                val = _struct.unpack_from('<B', blob, offset + i)[0]
                result.append(val)
        return result
