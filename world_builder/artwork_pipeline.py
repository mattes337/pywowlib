"""
Fully automated procedural artwork generation pipeline for WoW 3.3.5a zones.

Generates ALL visual assets programmatically using Python Pillow:
    - World map art (stylised zone overviews)
    - Subzone discovery overlays (one per subzone)
    - Loading screen art (scenic compositions, 4 themes)
    - Dungeon map overlays (floor plans)

Zero manual art tools required.  An AI agent can generate a complete zone's
artwork by calling :func:`generate_zone_artwork_bundle`.

Dependencies:
    Pillow >= 10.0   -- image manipulation and drawing
    NumPy  >= 1.24   -- heightmap array processing
    SciPy  >= 1.10   -- morphological ops (optional, graceful fallback)
"""

import os
import logging

log = logging.getLogger(__name__)

try:
    from PIL import Image
except ImportError:
    raise ImportError(
        "Pillow is required for the artwork pipeline.  "
        "Install with: pip install Pillow"
    )

try:
    import numpy as np
except ImportError:
    raise ImportError(
        "NumPy is required for the artwork pipeline.  "
        "Install with: pip install numpy"
    )

# Sub-module imports
from .artwork.world_map import (
    generate_world_map as _generate_world_map,
    SubzoneDefinition,
)
from .artwork.subzone_overlays import (
    generate_subzone_overlays as _generate_subzone_overlays,
    generate_subzone_overlay,
)
from .artwork.loading_screens import (
    generate_loading_screen as _generate_loading_screen,
    LOADING_SCREEN_THEMES,
)
from .artwork.dungeon_maps import (
    generate_dungeon_map as _generate_dungeon_map,
    DungeonLayout,
    Room,
    Connection,
)
from .artwork.color_palettes import (
    ColorPalette,
    PALETTES,
    interpolate_terrain_color,
    interpolate_color,
)
from .artwork.mpq_paths import (
    world_map_blp_path,
    subzone_overlay_blp_path,
    loading_screen_blp_path,
    dungeon_map_blp_path,
)


# ---------------------------------------------------------------------------
# Target type dimension standards (width, height)
# ---------------------------------------------------------------------------

_TARGET_DIMENSIONS = {
    'world_map': (1002, 668),
    'loading_screen': (1024, 768),
    'subzone_overlay': (256, 256),
    'dungeon_map': (512, 512),
}


# ---------------------------------------------------------------------------
# Public API -- image import
# ---------------------------------------------------------------------------

def import_artwork_image(filepath, target_type='world_map'):
    """
    Import an existing image file (PNG, BLP, or TGA) for use as artwork.

    Detects format from file extension or magic bytes. BLP files are
    converted to PNG via the parent library BLP2PNG converter before
    opening. The resulting image is converted to RGBA mode.

    Dimension validation is performed against the expected size for the
    given target type and logged as a warning (not an error).

    Args:
        filepath: Path to the image file (PNG, BLP, or TGA).
        target_type: Intended use for the image. One of
                     ``'world_map'`` (1002x668),
                     ``'loading_screen'`` (1024x768),
                     ``'subzone_overlay'`` (256x256),
                     ``'dungeon_map'`` (512x512).
                     Used only for dimension validation warnings.

    Returns:
        PIL.Image.Image: The loaded image in RGBA mode.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file format is not supported.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(
            "Image file not found: {}".format(filepath)
        )

    ext = os.path.splitext(filepath)[1].lower()

    # Detect format from magic bytes if extension is ambiguous
    if ext not in ('.png', '.blp', '.tga'):
        with open(filepath, 'rb') as fh:
            magic = fh.read(4)

        if magic[:4] == b'BLP2' or magic[:4] == b'BLP1':
            ext = '.blp'
        elif magic[:4] == b'\x89PNG':
            ext = '.png'
        else:
            # TGA has no reliable magic; accept if nothing else matched
            ext = '.tga'

    if ext == '.blp':
        img = _load_blp_image(filepath)
    elif ext in ('.png', '.tga'):
        img = Image.open(filepath)
    else:
        raise ValueError(
            "Unsupported image format: {}".format(ext)
        )

    # Convert to RGBA
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    # Validate dimensions against target type
    expected = _TARGET_DIMENSIONS.get(target_type)
    if expected is not None:
        actual = (img.width, img.height)
        if actual != expected:
            log.warning(
                "Image dimensions %s do not match expected %s for "
                "target type '%s': %s",
                actual, expected, target_type, filepath,
            )

    log.info("Imported artwork image: %s (%dx%d, target=%s)",
             filepath, img.width, img.height, target_type)

    return img


def _load_blp_image(filepath):
    """
    Load a BLP image file by converting it to PNG first.

    Uses the parent library BLP2PNG (BlpConverter) to convert the BLP
    file to a temporary PNG, then opens it with Pillow.

    Args:
        filepath: Path to the BLP file.

    Returns:
        PIL.Image.Image: The loaded image.

    Raises:
        ImportError: If the BLP2PNG converter is not available.
    """
    import tempfile

    try:
        from blp import BLP2PNG
    except ImportError:
        raise ImportError(
            "BLP2PNG converter is required for importing BLP files. "
            "Build the native BLP2PNG extension first."
        )

    # BLP2PNG.convert expects list of (data, name) tuples and an output dir
    with open(filepath, 'rb') as fh:
        blp_data = fh.read()

    filename = os.path.basename(filepath)
    # Convert .blp extension to .png for the output name
    png_filename = os.path.splitext(filename)[0] + '.png'

    tmp_dir = tempfile.mkdtemp(prefix="blp_import_")
    try:
        converter = BLP2PNG()
        converter.convert(
            [(blp_data, filename.encode('utf-8'))],
            tmp_dir.encode('utf-8'),
        )

        # Find the output PNG file
        png_path = os.path.join(tmp_dir, png_filename)
        if not os.path.isfile(png_path):
            # Try case-insensitive lookup
            for f in os.listdir(tmp_dir):
                if f.lower().endswith('.png'):
                    png_path = os.path.join(tmp_dir, f)
                    break

        if not os.path.isfile(png_path):
            raise RuntimeError(
                "BLP2PNG conversion did not produce expected output: "
                "{}".format(png_path)
            )

        # Open and copy the image data so we can clean up the temp dir
        img = Image.open(png_path)
        img.load()  # Force full load into memory
        return img.copy()
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Public API -- individual generators
# ---------------------------------------------------------------------------

def generate_world_map(heightmap, subzones, water_level=0.0,
                       size=(1002, 668), zone_name="Zone",
                       color_palette=None):
    """
    Procedurally generate world-map art (zone overview illustration).

    Pipeline:
        1. Colour-coded terrain from heightmap
        2. Subzone colour overlays (40 % opacity)
        3. Relief shading (hillshading)
        4. Coastline effects (dark edge + foam)
        5. Subzone name labels

    Args:
        heightmap:     2-D NumPy array (float, 0.0 - 1.0 normalised).
        subzones:      List of :class:`SubzoneDefinition` with boundaries.
        water_level:   Height threshold for the water surface.
        size:          Output resolution -- (1002, 668) is standard WoW.
        zone_name:     Zone name for logging / metadata.
        color_palette: A :class:`ColorPalette`, a palette name string, or
                       None to auto-select 'temperate'.

    Returns:
        Pillow RGBA Image.
    """
    hm = np.asarray(heightmap, dtype=np.float64)
    return _generate_world_map(
        hm, subzones, water_level=water_level,
        size=size, zone_name=zone_name, color_palette=color_palette,
    )


def generate_subzone_overlays(subzones, world_map_bounds, padding=10):
    """
    Procedurally generate subzone discovery overlays.

    For each subzone generates:
        - Coloured silhouette at 70 % opacity
        - Subtle per-pixel texture noise
        - Glowing border effect

    Args:
        subzones:         List of :class:`SubzoneDefinition`.
        world_map_bounds: (left, right, top, bottom) in world coordinates.
        padding:          Pixels of padding around each overlay.

    Returns:
        dict mapping subzone name (str) to Pillow RGBA Image.
    """
    return _generate_subzone_overlays(
        subzones, world_map_bounds, padding=padding,
    )


def generate_loading_screen(zone_name, theme='tropical',
                            size=(1024, 768), custom_elements=None):
    """
    Procedurally generate a loading-screen image.

    Themes: ``'tropical'``, ``'volcanic'``, ``'underground'``, ``'titan'``.

    Layer composition order:
        sky -> background -> midground -> foreground -> accent -> text

    Args:
        zone_name:       Display text (drawn centred near top).
        theme:           Visual theme key.
        size:            (width, height) -- (1024, 768) standard or
                         (2048, 1536) widescreen.
        custom_elements: Optional dict overriding per-layer specs.

    Returns:
        Pillow RGBA Image.
    """
    return _generate_loading_screen(
        zone_name, theme=theme, size=size,
        custom_elements=custom_elements,
    )


def generate_dungeon_map(layout, boss_positions, entrance_position,
                         size=(512, 512), dungeon_name="Dungeon"):
    """
    Procedurally generate a dungeon-map overlay (floor plan).

    Draws:
        - Coloured room rectangles (grey / red for bosses)
        - Corridor connection lines
        - Boss markers (red circles with 'B')
        - Entrance arrow (green)

    Args:
        layout:            :class:`DungeonLayout` instance.
        boss_positions:    List of ``(boss_name, (x, y))`` tuples.
        entrance_position: ``(x, y)`` entrance location.
        size:              Output resolution -- (512, 512) typical.
        dungeon_name:      Dungeon name for logging / metadata.

    Returns:
        Pillow RGB Image.
    """
    return _generate_dungeon_map(
        layout, boss_positions, entrance_position,
        size=size, dungeon_name=dungeon_name,
    )


# ---------------------------------------------------------------------------
# Public API -- full zone bundle
# ---------------------------------------------------------------------------

def generate_zone_artwork_bundle(zone_name, heightmap, subzones,
                                 theme='tropical', output_dir=".",
                                 water_level=0.0, save_png=True):
    """
    Generate ALL artwork for a zone in one call (full automation).

    Produces:
        - 1 world-map image (1002 x 668)
        - N subzone overlays (variable sizes, one per subzone)
        - 1 standard loading screen (1024 x 768)
        - 1 widescreen loading screen (2048 x 1536)

    Resulting Pillow Images are saved as PNG files inside *output_dir*
    mirroring the MPQ directory structure (if *save_png* is True).

    Args:
        zone_name:   Zone name (used for directory names and labels).
        heightmap:   2-D NumPy array (float, 0.0 - 1.0 normalised).
        subzones:    List of :class:`SubzoneDefinition`.
        theme:       Loading screen theme.
        output_dir:  Base directory for file output.
        water_level: Height threshold for the water surface.
        save_png:    Whether to write PNG files to disk.

    Returns:
        dict mapping MPQ path (str) to the Pillow Image object.
    """
    hm = np.asarray(heightmap, dtype=np.float64)
    results = {}

    # --- World map ---
    log.info("=== Generating zone artwork bundle for '%s' ===", zone_name)
    world_map_img = generate_world_map(
        hm, subzones, water_level=water_level,
        zone_name=zone_name, color_palette=theme,
    )
    wm_path = world_map_blp_path(zone_name)
    results[wm_path] = world_map_img

    # --- Subzone overlays ---
    if subzones:
        # Estimate world bounds from subzone boundaries
        all_x = []
        all_y = []
        for sz in subzones:
            for wx, wy in sz.boundary:
                all_x.append(wx)
                all_y.append(wy)
        if all_x and all_y:
            margin_x = (max(all_x) - min(all_x)) * 0.05
            margin_y = (max(all_y) - min(all_y)) * 0.05
            bounds = (
                min(all_x) - margin_x,
                max(all_x) + margin_x,
                min(all_y) - margin_y,
                max(all_y) + margin_y,
            )
        else:
            bounds = (0, float(hm.shape[1]), 0, float(hm.shape[0]))

        overlays = generate_subzone_overlays(subzones, bounds)
        for sz_name, img in overlays.items():
            blp = subzone_overlay_blp_path(zone_name, sz_name)
            results[blp] = img

    # --- Loading screens ---
    for widescreen, screen_size in [(False, (1024, 768)), (True, (2048, 1536))]:
        ls_img = generate_loading_screen(
            zone_name, theme=theme, size=screen_size,
        )
        ls_path = loading_screen_blp_path(zone_name, widescreen=widescreen)
        results[ls_path] = ls_img

    # --- Save PNGs ---
    if save_png and output_dir:
        for mpq_path, img in results.items():
            # Convert backslash MPQ path to OS path, swap .blp -> .png
            rel = mpq_path.replace("\\", os.sep)
            if rel.lower().endswith('.blp'):
                rel = rel[:-4] + '.png'
            abs_path = os.path.join(output_dir, rel)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            img.convert('RGBA').save(abs_path, format='PNG')
            log.info("Saved %s", abs_path)

    log.info(
        "=== Artwork bundle complete: %d assets for '%s' ===",
        len(results), zone_name,
    )
    return results
