#!/usr/bin/env python
"""
M2 model converter for WoW 3.3.5a (WotLK).

Bidirectional converter between M2 binary model files and glTF 2.0 (.glb)
or JSON. Handles skin file discovery and loading automatically.

Usage:
  python m2_converter.py m2togltf <input.m2> [-o output.glb]
  python m2_converter.py m2togltf --dir <m2_dir> [-o output_dir]
  python m2_converter.py m2tojson <input.m2> [-o output.json]
  python m2_converter.py gltftom2 <input.glb> [-o output.m2]
  python m2_converter.py jsontom2 <input.json> [-o output.m2]
"""

import json
import os
import sys
import argparse
import math
import importlib.util


# ---------------------------------------------------------------------------
# Package bootstrap: The wow-pywowlib library uses relative imports throughout,
# so it must be imported as a proper Python package. The directory name contains
# hyphens which prevents normal import. We register it as 'pywowlib' using
# importlib so all internal relative imports resolve correctly.
# ---------------------------------------------------------------------------

def _bootstrap_pywowlib():
    """Register the parent wow-pywowlib directory as an importable package."""
    pkg_name = 'pywowlib'
    if pkg_name in sys.modules:
        return  # already bootstrapped

    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    init_path = os.path.join(pkg_dir, '__init__.py')

    spec = importlib.util.spec_from_file_location(
        pkg_name, init_path,
        submodule_search_locations=[pkg_dir])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = mod
    spec.loader.exec_module(mod)

_bootstrap_pywowlib()

from pywowlib.file_formats.wow_common_types import M2VersionsManager, M2Versions
from pywowlib.m2_file import M2File


def _safe_float(val):
    """Sanitise a float for JSON (NaN / Inf are not valid JSON)."""
    if math.isnan(val) or math.isinf(val):
        return 0.0
    return round(val, 6)


def _find_skin_paths(m2_path):
    """
    Discover .skin file paths for a given .m2 file.

    WotLK skin files follow the naming convention:
        {model_base}00.skin, {model_base}01.skin, ...

    Returns a list of existing skin file paths.
    """
    base = os.path.splitext(m2_path)[0]
    skin_paths = []
    for i in range(4):  # WotLK supports up to 4 skin profiles
        skin_path = "{}{}.skin".format(base, str(i).zfill(2))
        if os.path.exists(skin_path):
            skin_paths.append(skin_path)
    return skin_paths


def _load_m2(m2_path, version=2):
    """
    Load an M2 file with its skin profiles.

    Args:
        m2_path: Path to the .m2 file.
        version: Expansion version number (2 = WotLK).

    Returns:
        M2File instance with skins loaded.
    """
    # Set the global version manager before creating the M2File
    M2VersionsManager().set_m2_version(M2Versions.from_expansion_number(version))

    m2 = M2File(version=version, filepath=m2_path)

    # The M2File constructor reads the file but we need to load skins
    # separately for WotLK+ where skins are external files.
    if not m2.skins or len(m2.skins) == 0:
        skin_paths = _find_skin_paths(m2_path)
        if not skin_paths:
            print("Warning: No .skin files found for {}".format(m2_path))
            return m2

        # Load skins manually
        from pywowlib.file_formats.skin_format import M2SkinProfile
        m2.skins = []
        for sp in skin_paths:
            with open(sp, 'rb') as f:
                skin = M2SkinProfile().read(f)
                m2.skins.append(skin)

    return m2


# ---------------------------------------------------------------------------
# M2 -> glTF
# ---------------------------------------------------------------------------

def m2_to_gltf(m2_path, output_path=None, version=2):
    """
    Convert an M2 model to glTF 2.0 binary (.glb).

    Args:
        m2_path: Path to the .m2 file.
        output_path: Output .glb path (default: same name with .glb extension).
        version: Expansion version number (2 = WotLK).
    """
    from pywowlib.world_builder.m2_gltf_writer import M2GltfWriter

    if output_path is None:
        output_path = os.path.splitext(m2_path)[0] + '.glb'

    m2 = _load_m2(m2_path, version)

    if not m2.skins:
        raise RuntimeError(
            "No skin profiles loaded for {}. "
            "Ensure .skin files are in the same directory.".format(m2_path))

    writer = M2GltfWriter(output_path)
    writer.write_from_m2(m2, skin_index=0)

    # Print summary
    skin = m2.skins[0]
    n_verts = len(m2.root.vertices)
    n_tris = len(skin.triangle_indices) // 3
    n_submeshes = len(skin.submeshes)
    print("{} -> {} ({} vertices, {} triangles, {} submeshes)".format(
        os.path.basename(m2_path), os.path.basename(output_path),
        n_verts, n_tris, n_submeshes))


def m2_to_gltf_directory(m2_dir, output_dir=None, version=2):
    """
    Batch-convert every .m2 file in a directory to glTF.

    Args:
        m2_dir: Directory containing .m2 files.
        output_dir: Output directory for .glb files.
        version: Expansion version number (2 = WotLK).
    """
    if output_dir is None:
        output_dir = os.path.join(m2_dir, 'glb')
    os.makedirs(output_dir, exist_ok=True)

    converted = 0
    failed = 0

    for filename in sorted(os.listdir(m2_dir)):
        if not filename.lower().endswith('.m2'):
            continue

        m2_path = os.path.join(m2_dir, filename)
        glb_name = os.path.splitext(filename)[0] + '.glb'
        glb_path = os.path.join(output_dir, glb_name)

        try:
            m2_to_gltf(m2_path, glb_path, version)
            converted += 1
        except Exception as e:
            print("  FAIL  {:50s} -- {}".format(filename, e))
            failed += 1

    print("\n{} converted, {} failed".format(converted, failed))


# ---------------------------------------------------------------------------
# M2 -> JSON (metadata dump)
# ---------------------------------------------------------------------------

def m2_to_json(m2_path, version=2):
    """
    Extract M2 metadata as a JSON-serialisable dict.

    Includes vertex/triangle counts, submesh info, texture paths,
    bone count, bounding box, and animation sequence info.

    Args:
        m2_path: Path to the .m2 file.
        version: Expansion version number (2 = WotLK).

    Returns:
        Dict with M2 metadata.
    """
    m2 = _load_m2(m2_path, version)
    root = m2.root

    # Bounding box
    bbox_min = root.bounding_box.min
    bbox_max = root.bounding_box.max
    bounding_box = {
        'min': [_safe_float(bbox_min[0]),
                _safe_float(bbox_min[1]),
                _safe_float(bbox_min[2])],
        'max': [_safe_float(bbox_max[0]),
                _safe_float(bbox_max[1]),
                _safe_float(bbox_max[2])],
    }

    # Textures
    textures = []
    for i, tex in enumerate(root.textures):
        textures.append({
            'index': i,
            'type': tex.type,
            'flags': tex.flags,
            'filename': tex.filename.value,
        })

    # Materials
    materials = []
    for i, mat in enumerate(root.materials):
        materials.append({
            'index': i,
            'flags': mat.flags,
            'blending_mode': mat.blending_mode,
        })

    # Texture lookup table
    tex_lookup = list(root.texture_lookup_table)

    # Bones
    bones = []
    for i, bone in enumerate(root.bones):
        bones.append({
            'index': i,
            'key_bone_id': bone.key_bone_id,
            'flags': bone.flags,
            'parent_bone': bone.parent_bone,
            'pivot': [_safe_float(bone.pivot[0]),
                      _safe_float(bone.pivot[1]),
                      _safe_float(bone.pivot[2])],
        })

    # Animations
    animations = []
    for i, seq in enumerate(root.sequences):
        anim_info = {
            'index': i,
            'id': seq.id,
            'variation_index': seq.variation_index,
            'movespeed': _safe_float(seq.movespeed),
            'flags': seq.flags,
            'frequency': seq.frequency,
            'variation_next': seq.variation_next,
            'alias_next': seq.alias_next,
        }
        if hasattr(seq, 'duration'):
            anim_info['duration'] = seq.duration
        if hasattr(seq, 'start_timestamp'):
            anim_info['start_timestamp'] = seq.start_timestamp
            anim_info['end_timestamp'] = seq.end_timestamp
        animations.append(anim_info)

    # Skin profile info
    skin_profiles = []
    for si, skin in enumerate(m2.skins):
        submeshes_info = []
        for subi, sub in enumerate(skin.submeshes):
            submeshes_info.append({
                'index': subi,
                'skin_section_id': sub.skin_section_id,
                'vertex_start': sub.vertex_start,
                'vertex_count': sub.vertex_count,
                'index_start': sub.index_start,
                'index_count': sub.index_count,
                'bone_count': sub.bone_count,
                'bone_combo_index': sub.bone_combo_index,
                'bone_influences': sub.bone_influences,
                'center_position': [
                    _safe_float(sub.center_position[0]),
                    _safe_float(sub.center_position[1]),
                    _safe_float(sub.center_position[2])],
            })

        tex_units_info = []
        for tui, tu in enumerate(skin.texture_units):
            tex_units_info.append({
                'index': tui,
                'skin_section_index': tu.skin_section_index,
                'material_index': tu.material_index,
                'texture_combo_index': tu.texture_combo_index,
                'shader_id': tu.shader_id,
                'flags': tu.flags,
                'texture_count': tu.texture_count,
            })

        skin_profiles.append({
            'skin_index': si,
            'vertex_indices_count': len(skin.vertex_indices),
            'triangle_indices_count': len(skin.triangle_indices),
            'submesh_count': len(skin.submeshes),
            'texture_unit_count': len(skin.texture_units),
            'submeshes': submeshes_info,
            'texture_units': tex_units_info,
        })

    result = {
        '_meta': {
            'filename': os.path.basename(m2_path),
            'version': root.version,
            'name': root.name.value,
            'global_flags': root.global_flags,
        },
        'summary': {
            'vertex_count': len(root.vertices),
            'bone_count': len(root.bones),
            'texture_count': len(root.textures),
            'material_count': len(root.materials),
            'animation_count': len(root.sequences),
            'skin_profile_count': len(m2.skins),
            'triangle_count': (len(m2.skins[0].triangle_indices) // 3
                               if m2.skins else 0),
        },
        'bounding_box': bounding_box,
        'bounding_sphere_radius': _safe_float(root.bounding_sphere_radius),
        'textures': textures,
        'materials': materials,
        'texture_lookup_table': tex_lookup,
        'bones': bones,
        'animations': animations,
        'skin_profiles': skin_profiles,
    }

    return result


# ---------------------------------------------------------------------------
# glTF -> M2
# ---------------------------------------------------------------------------

def _compute_submesh_bounds(vertices):
    """
    Compute the centroid and bounding sphere radius for a list of vertices.

    Args:
        vertices: list of (x, y, z) tuples.

    Returns:
        tuple: (origin, radius) where origin is (cx, cy, cz).
    """
    if not vertices:
        return (0.0, 0.0, 0.0), 0.0

    n = len(vertices)
    cx = sum(v[0] for v in vertices) / n
    cy = sum(v[1] for v in vertices) / n
    cz = sum(v[2] for v in vertices) / n

    max_dist_sq = 0.0
    for v in vertices:
        dx = v[0] - cx
        dy = v[1] - cy
        dz = v[2] - cz
        dist_sq = dx * dx + dy * dy + dz * dz
        if dist_sq > max_dist_sq:
            max_dist_sq = dist_sq

    radius = math.sqrt(max_dist_sq)
    return (cx, cy, cz), radius


def _float_weights_to_uint8(weights):
    """
    Convert float bone weights [0.0-1.0] to uint8 [0-255].

    Ensures the four weights sum to exactly 255 by assigning any
    rounding remainder to the largest component.

    Args:
        weights: tuple of 4 floats in [0.0, 1.0] range.

    Returns:
        tuple of 4 ints in [0, 255] range.
    """
    raw = [int(round(w * 255.0)) for w in weights]
    total = sum(raw)
    if total != 255 and total > 0:
        # Adjust the largest weight to fix rounding
        max_i = raw.index(max(raw))
        raw[max_i] += 255 - total
    elif total == 0:
        raw[0] = 255
    return tuple(raw)


def gltf_to_m2(glb_path, output_path=None, version=2):
    """
    Convert a glTF 2.0 binary (.glb) back to M2 model format.

    Reads geometry and material data from a .glb file (typically one
    previously exported by m2_to_gltf) and writes an M2 binary with
    its associated .skin file.

    Args:
        glb_path: Path to the input .glb file.
        output_path: Output .m2 path (default: same name with .m2 extension).
        version: Expansion version number (2 = WotLK).
    """
    from pywowlib.world_builder.m2_gltf_writer import M2GltfReader

    if output_path is None:
        output_path = os.path.splitext(glb_path)[0] + '.m2'

    reader = M2GltfReader(glb_path)
    materials, submeshes = reader.read()

    M2VersionsManager().set_m2_version(M2Versions.from_expansion_number(version))
    m2 = M2File(version=version)

    # Add at least one root bone
    m2.add_bone(pivot=(0, 0, 0), key_bone_id=-1, flags=0, parent_bone=-1)

    # Add textures and build a mapping from glTF material index to
    # texture lookup index
    tex_indices = []
    for mat in materials:
        tex_path = mat.get('texture1', '')
        tex_flags = mat.get('flags', 0)
        tex_idx = m2.add_texture(path=tex_path, flags=tex_flags, tex_type=0)
        tex_indices.append(tex_idx)

    # Add geosets (submeshes)
    total_verts = 0
    total_tris = 0
    for submesh in submeshes:
        verts = submesh['vertices']
        norms = submesh['normals']
        uvs = submesh['uvs']
        tris = submesh['indices']  # list of (i0, i1, i2) tuples
        bone_w_float = submesh.get('bone_weights', [])
        bone_j = submesh.get('bone_indices', [])
        skin_section_id = submesh.get('skin_section_id', 0)

        if not verts or not tris:
            continue

        # Ensure normals and UVs have the same length as vertices
        n_verts = len(verts)
        if len(norms) < n_verts:
            norms = list(norms) + [(0.0, 0.0, 1.0)] * (n_verts - len(norms))
        if len(uvs) < n_verts:
            uvs = list(uvs) + [(0.0, 0.0)] * (n_verts - len(uvs))

        # Default bone data if not present
        if not bone_j:
            bone_j = [(0, 0, 0, 0)] * n_verts
        if not bone_w_float:
            bone_w_float = [(1.0, 0.0, 0.0, 0.0)] * n_verts

        # Convert float weights to uint8
        b_weights = [_float_weights_to_uint8(w) for w in bone_w_float]

        # Convert bone indices to tuples of ints
        b_indices = [tuple(int(j) for j in bi) for bi in bone_j]

        # Compute submesh bounds
        origin, radius = _compute_submesh_bounds(verts)

        m2.add_geoset(
            vertices=verts,
            normals=norms,
            uv=uvs,
            uv2=uvs,
            tris=tris,
            b_indices=b_indices,
            b_weights=b_weights,
            origin=origin,
            sort_pos=origin,
            sort_radius=radius,
            mesh_part_id=skin_section_id,
        )

        total_verts += n_verts
        total_tris += len(tris)

    m2.write(output_path)

    print("{} -> {} ({} vertices, {} triangles, {} submeshes, {} textures)".format(
        os.path.basename(glb_path), os.path.basename(output_path),
        total_verts, total_tris, len(submeshes), len(materials)))


# ---------------------------------------------------------------------------
# JSON -> M2
# ---------------------------------------------------------------------------

def json_to_m2(json_path, output_path=None, version=2):
    """
    Reconstruct an M2 binary from JSON metadata (produced by m2_to_json).

    This recreates the M2 file structure from the JSON dump, including
    textures, bones, and submesh geometry placeholders. Note that the
    JSON format from m2_to_json contains metadata and structure info
    but not raw vertex data, so this is primarily useful for
    round-tripping structure and metadata.

    Args:
        json_path: Path to the input .json file.
        output_path: Output .m2 path (default: same name with .m2 extension).
        version: Expansion version number (2 = WotLK).
    """
    if output_path is None:
        output_path = os.path.splitext(json_path)[0] + '.m2'

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    M2VersionsManager().set_m2_version(M2Versions.from_expansion_number(version))
    m2 = M2File(version=version)

    # Set model name from metadata
    meta = data.get('_meta', {})
    model_name = meta.get('name', '')
    if model_name:
        m2.root.name.value = model_name

    # Add textures
    for tex_info in data.get('textures', []):
        m2.add_texture(
            path=tex_info.get('filename', ''),
            flags=tex_info.get('flags', 0),
            tex_type=tex_info.get('type', 0),
        )

    # Add bones
    for bone_info in data.get('bones', []):
        pivot = tuple(bone_info.get('pivot', [0, 0, 0]))
        m2.add_bone(
            pivot=pivot,
            key_bone_id=bone_info.get('key_bone_id', -1),
            flags=bone_info.get('flags', 0),
            parent_bone=bone_info.get('parent_bone', -1),
        )

    # If no bones were added, add a default root bone
    if not data.get('bones'):
        m2.add_bone(pivot=(0, 0, 0), key_bone_id=-1, flags=0, parent_bone=-1)

    m2.write(output_path)

    n_textures = len(data.get('textures', []))
    n_bones = len(data.get('bones', []))
    print("{} -> {} ({} textures, {} bones)".format(
        os.path.basename(json_path), os.path.basename(output_path),
        n_textures, n_bones))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='M2 model converter for WoW 3.3.5a (WotLK)')
    subparsers = parser.add_subparsers(dest='command')

    # -- m2togltf -------------------------------------------------------
    p_gltf = subparsers.add_parser('m2togltf',
                                    help='Convert M2 model to glTF 2.0 (.glb)')
    p_gltf.add_argument('input', nargs='?', help='Input .m2 file')
    p_gltf.add_argument('-o', '--output',
                        help='Output .glb file (or directory with --dir)')
    p_gltf.add_argument('--dir',
                        help='Batch-convert all .m2 files in a directory')
    p_gltf.add_argument('--version', type=int, default=2,
                        help='Expansion version number (default: 2 = WotLK)')

    # -- m2tojson -------------------------------------------------------
    p_json = subparsers.add_parser('m2tojson',
                                    help='Dump M2 metadata as JSON')
    p_json.add_argument('input', help='Input .m2 file')
    p_json.add_argument('-o', '--output', help='Output .json file')
    p_json.add_argument('--version', type=int, default=2,
                        help='Expansion version number (default: 2 = WotLK)')

    # -- gltftom2 -------------------------------------------------------
    p_gltf2m2 = subparsers.add_parser('gltftom2',
                                       help='Convert glTF 2.0 (.glb) to M2 model')
    p_gltf2m2.add_argument('input', help='Input .glb file')
    p_gltf2m2.add_argument('-o', '--output', help='Output .m2 file')
    p_gltf2m2.add_argument('--version', type=int, default=2,
                           help='Expansion version number (default: 2 = WotLK)')

    # -- jsontom2 -------------------------------------------------------
    p_json2m2 = subparsers.add_parser('jsontom2',
                                       help='Convert JSON metadata to M2 model')
    p_json2m2.add_argument('input', help='Input .json file (from m2tojson)')
    p_json2m2.add_argument('-o', '--output', help='Output .m2 file')
    p_json2m2.add_argument('--version', type=int, default=2,
                           help='Expansion version number (default: 2 = WotLK)')

    args = parser.parse_args()

    if args.command == 'm2togltf':
        if args.dir:
            output_dir = args.output or None
            print("Converting all .m2 files in: {}".format(args.dir))
            if output_dir:
                print("Output directory: {}".format(output_dir))
            m2_to_gltf_directory(args.dir, output_dir, args.version)
        elif args.input:
            m2_to_gltf(args.input, args.output, args.version)
        else:
            p_gltf.print_help()

    elif args.command == 'm2tojson':
        output = args.output or os.path.splitext(args.input)[0] + '.json'
        data = m2_to_json(args.input, args.version)
        with open(output, 'w', encoding='utf-8') as jf:
            json.dump(data, jf, indent=2, ensure_ascii=False)
        summary = data['summary']
        print("{} -> {} ({} verts, {} tris, {} bones, {} textures, {} anims)".format(
            args.input, output,
            summary['vertex_count'],
            summary['triangle_count'],
            summary['bone_count'],
            summary['texture_count'],
            summary['animation_count']))

    elif args.command == 'gltftom2':
        try:
            gltf_to_m2(args.input, args.output, args.version)
        except Exception as e:
            print("Error converting glTF to M2: {}".format(e))
            sys.exit(1)

    elif args.command == 'jsontom2':
        try:
            json_to_m2(args.input, args.output, args.version)
        except Exception as e:
            print("Error converting JSON to M2: {}".format(e))
            sys.exit(1)

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
