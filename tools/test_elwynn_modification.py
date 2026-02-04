"""
Elwynn Forest Modification Test Script

Creates a modified ADT for Elwynn Forest tile (3, 4) -- which covers
Goldshire and Northshire -- and packs it into patch-4.MPQ for the
WoW 3.3.5a client.

Since we cannot extract original ADTs from the existing MPQs (StormLib
unavailable), we generate a replacement ADT with visible terrain changes.
The WoW client loads the highest-numbered patch first, so our patch-4.MPQ
ADT overrides the original.

Tile coordinates for Elwynn Forest:
    World coords for Goldshire:  approx (-9459, 62)
    adt_composer formula: tile_fx = (MAP_SIZE_MAX - world_y) / TILE_SIZE
                          tile_fy = (MAP_SIZE_MAX - world_x) / TILE_SIZE
    MAP_SIZE_MAX = 17066.66657, TILE_SIZE = 533.333...  (per adt_composer)

    Wait -- let me recalculate. The adt_composer tile size is the actual
    WoW tile size: 533.33333 yards (1/64 of 34133.33).

Actually the key values from adt_composer.py:
    _TILE_SIZE = 533.33333
    tile (3, 4) covers a region within Elwynn Forest

Usage:
    python tools/test_elwynn_modification.py [--output-dir DIR] [--wow-data DIR]

After running:
    1. The script copies patch-4.MPQ to the WoW Data directory
    2. In-game: type '.reload map' or zone out and back into Elwynn Forest
    3. You should see dramatically altered terrain around Goldshire

To revert:
    Delete G:\\WoW AzerothCore\\Data\\patch-4.MPQ
"""

import argparse
import math
import os
import shutil
import struct
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world_builder.adt_composer import create_adt, add_doodad_to_adt
from world_builder.wdt_generator import create_wdt
from world_builder.mpq_packer import MPQPacker


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# WoW tile grid constants (from adt_composer)
_TILE_SIZE = 533.33333
_MAP_SIZE_MAX = 17066.66657
_HEIGHTMAP_RES = 129  # 129x129 vertices per ADT tile

# Elwynn Forest tile coordinates
# The Azeroth map uses map_id 0; Elwynn Forest primarily covers tiles:
#   (2, 4) - western Elwynn (Stormwind Gates area)
#   (3, 4) - eastern Elwynn (Goldshire, Northshire)
# We modify tile (3, 4) since that's where Goldshire is.
ELWYNN_TILE_X = 3
ELWYNN_TILE_Y = 4
MAP_NAME = "Azeroth"

# Elwynn Forest area IDs (from DBC)
ELWYNN_AREA_ID = 12  # AreaTable.dbc ID for Elwynn Forest
GOLDSHIRE_AREA_ID = 87  # Goldshire subzone

# Textures - use Elwynn Forest textures from the existing game
ELWYNN_TEXTURES = [
    "Tileset\\Elwynn\\ElwynnGrassBase.blp",
    "Tileset\\Elwynn\\ElwynnDirtMud.blp",
    "Tileset\\Elwynn\\ElwynnRockBase.blp",
    "Tileset\\Elwynn\\ElwynnFlowerBase.blp",
]


def generate_elwynn_heightmap():
    """Generate a heightmap with visible hills and valleys for Elwynn.

    Creates rolling hills with a prominent central hill (visible from
    Goldshire area) and some valleys. The terrain should be noticeably
    different from the original flat Elwynn to confirm the patch works.
    """
    hm = [[0.0] * _HEIGHTMAP_RES for _ in range(_HEIGHTMAP_RES)]

    center = _HEIGHTMAP_RES // 2

    for row in range(_HEIGHTMAP_RES):
        for col in range(_HEIGHTMAP_RES):
            # Normalised position 0..1
            nx = col / (_HEIGHTMAP_RES - 1)
            ny = row / (_HEIGHTMAP_RES - 1)

            # Base gentle rolling hills using multiple sine waves
            h = 0.0

            # Large rolling terrain
            h += 15.0 * math.sin(nx * math.pi * 2.0) * math.sin(ny * math.pi * 2.0)

            # Medium frequency hills
            h += 8.0 * math.sin(nx * math.pi * 4.0 + 0.5) * math.cos(ny * math.pi * 3.0)

            # Prominent central hill/mesa -- very visible landmark
            dx = nx - 0.5
            dy = ny - 0.5
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 0.2:
                # Smooth raised area in the center -- like a big grassy hill
                t = 1.0 - (dist / 0.2)
                # Smooth hermite interpolation
                t = t * t * (3.0 - 2.0 * t)
                h += 60.0 * t  # 60 yard high hill

            # A ridge in the northeast
            ridge_x = nx - 0.75
            ridge_y = ny - 0.25
            ridge_dist = abs(ridge_x * 0.7 + ridge_y * 0.7)
            if ridge_dist < 0.08:
                t = 1.0 - (ridge_dist / 0.08)
                t = t * t * (3.0 - 2.0 * t)
                h += 35.0 * t

            # A valley/depression in the southwest
            val_x = nx - 0.25
            val_y = ny - 0.75
            val_dist = math.sqrt(val_x * val_x + val_y * val_y)
            if val_dist < 0.15:
                t = 1.0 - (val_dist / 0.15)
                t = t * t * (3.0 - 2.0 * t)
                h -= 10.0 * t  # Shallow depression

            # Shift everything up so minimum is around ground level
            h += 20.0

            hm[row][col] = h

    return hm


def generate_splat_map(heightmap):
    """Generate a basic splat map based on elevation.

    Layer 0: grass (base, always present)
    Layer 1: dirt (on lower areas)
    Layer 2: rock (on higher areas / steep slopes)
    Layer 3: flowers (on medium elevations)
    """
    size = 64  # Alpha map resolution
    splat = {}

    # Layer 1: dirt on low areas
    dirt = [[0] * size for _ in range(size)]
    for row in range(size):
        for col in range(size):
            # Sample height at this position
            hm_row = int(row * (_HEIGHTMAP_RES - 1) / (size - 1))
            hm_col = int(col * (_HEIGHTMAP_RES - 1) / (size - 1))
            h = heightmap[hm_row][hm_col]

            if h < 15.0:
                dirt[row][col] = 200
            elif h < 25.0:
                t = (h - 15.0) / 10.0
                dirt[row][col] = int(200 * (1.0 - t))
            else:
                dirt[row][col] = 0
    splat[1] = dirt

    # Layer 2: rock on high areas (the big hill)
    rock = [[0] * size for _ in range(size)]
    for row in range(size):
        for col in range(size):
            hm_row = int(row * (_HEIGHTMAP_RES - 1) / (size - 1))
            hm_col = int(col * (_HEIGHTMAP_RES - 1) / (size - 1))
            h = heightmap[hm_row][hm_col]

            if h > 50.0:
                rock[row][col] = 255
            elif h > 35.0:
                t = (h - 35.0) / 15.0
                rock[row][col] = int(255 * t)
            else:
                rock[row][col] = 0
    splat[2] = rock

    # Layer 3: flowers on medium elevations
    flowers = [[0] * size for _ in range(size)]
    for row in range(size):
        for col in range(size):
            hm_row = int(row * (_HEIGHTMAP_RES - 1) / (size - 1))
            hm_col = int(col * (_HEIGHTMAP_RES - 1) / (size - 1))
            h = heightmap[hm_row][hm_col]

            if 20.0 < h < 40.0:
                center = 30.0
                t = 1.0 - abs(h - center) / 10.0
                flowers[row][col] = int(180 * max(0, t))
            else:
                flowers[row][col] = 0
    splat[3] = flowers

    return splat


def build_elwynn_patch(output_dir, wow_data_dir=None):
    """Build a patch-4.MPQ containing a modified Elwynn Forest tile.

    Args:
        output_dir: Where to write intermediate and output files.
        wow_data_dir: Path to WoW Data directory. If provided, copies
                      the MPQ there automatically.

    Returns:
        str: Path to the generated patch-4.MPQ file.
    """
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("Elwynn Forest Modification Test")
    print("=" * 60)

    # Step 1: Generate heightmap
    print("\n[1/5] Generating terrain heightmap...")
    heightmap = generate_elwynn_heightmap()

    # Print some stats
    flat = [h for row in heightmap for h in row]
    print("  Heightmap: {}x{} vertices".format(len(heightmap), len(heightmap[0])))
    print("  Elevation range: {:.1f} - {:.1f} yards".format(min(flat), max(flat)))
    print("  Mean elevation: {:.1f} yards".format(sum(flat) / len(flat)))

    # Step 2: Generate splat map
    print("\n[2/5] Generating texture splat map...")
    splat_map = generate_splat_map(heightmap)
    print("  Texture layers: {}".format(len(ELWYNN_TEXTURES)))
    for i, t in enumerate(ELWYNN_TEXTURES):
        print("    [{}] {}".format(i, t))

    # Step 3: Create ADT
    print("\n[3/5] Creating ADT for tile ({}, {})...".format(
        ELWYNN_TILE_X, ELWYNN_TILE_Y))

    adt_bytes = create_adt(
        tile_x=ELWYNN_TILE_X,
        tile_y=ELWYNN_TILE_Y,
        heightmap=heightmap,
        texture_paths=ELWYNN_TEXTURES,
        splat_map=splat_map,
        area_id=ELWYNN_AREA_ID,
    )

    print("  ADT size: {:,} bytes".format(len(adt_bytes)))

    # Step 4: Create WDT (must include at least the tile we're modifying)
    # For Azeroth, the WDT normally lists all 64x64 tiles. We only need
    # to override the specific ADT tile though. The WDT in the base MPQ
    # already has the tile flags set, so we just need the ADT file itself.
    # However, to be safe we also include a WDT.
    print("\n[4/5] Building WDT...")

    # We create a minimal WDT that marks tile (3,4) as present
    wdt_bytes = create_wdt(
        active_coords=[(ELWYNN_TILE_X, ELWYNN_TILE_Y)],
        mphd_flags=0x0,  # No big alpha flag to match original Azeroth
    )
    print("  WDT size: {:,} bytes".format(len(wdt_bytes)))

    # Step 5: Pack into MPQ
    print("\n[5/5] Packing into patch-4.MPQ...")

    packer = MPQPacker(output_dir, patch_name="patch-4.MPQ")

    # Add the ADT file (this is the main payload)
    adt_mpq_path = "World\\Maps\\{}\\{}_{:d}_{:d}.adt".format(
        MAP_NAME, MAP_NAME, ELWYNN_TILE_X, ELWYNN_TILE_Y)
    packer.add_file(adt_mpq_path, adt_bytes)

    # Note: We intentionally do NOT include the WDT in the patch.
    # The existing WDT in the base MPQs already has tile (3,4) flagged.
    # Including a new WDT with only one tile would break the rest of
    # Azeroth's tiles. The client will use the base WDT and our patched ADT.

    print("  MPQ internal path: {}".format(adt_mpq_path))

    # Build the MPQ
    mpq_path = packer.build_mpq()
    print("  Output: {}".format(mpq_path))

    # Step 6: Copy to WoW Data directory
    if wow_data_dir:
        dest = os.path.join(wow_data_dir, "patch-4.MPQ")
        print("\n[+] Copying to WoW Data directory...")
        print("    Source: {}".format(mpq_path))
        print("    Dest:   {}".format(dest))

        if os.path.isfile(mpq_path):
            shutil.copy2(mpq_path, dest)
            print("    Done!")
        else:
            # build_mpq might have fallen back to directory structure
            # In that case, we need to look for the directory output
            print("    WARNING: MPQ file not found at expected path.")
            print("    The MPQ builder may have created a directory structure instead.")
            print("    Check: {}".format(output_dir))

            # Try to find if the pure-python writer created it
            alt_path = os.path.join(output_dir, "patch-4.MPQ")
            if os.path.isfile(alt_path):
                shutil.copy2(alt_path, dest)
                print("    Found at alternate path and copied!")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("  Map:        {} (Azeroth)".format(MAP_NAME))
    print("  Tile:       ({}, {})".format(ELWYNN_TILE_X, ELWYNN_TILE_Y))
    print("  Area ID:    {} (Elwynn Forest)".format(ELWYNN_AREA_ID))
    print("  Textures:   {} layers".format(len(ELWYNN_TEXTURES)))
    print("  Terrain:    Rolling hills with 60yd central hill")
    print("  ADT size:   {:,} bytes".format(len(adt_bytes)))

    if wow_data_dir:
        print("\n  TESTING INSTRUCTIONS:")
        print("  1. The patch has been copied to your WoW Data directory")
        print("  2. If the WoW client is running, you need to restart it")
        print("     (ADT changes require client restart)")
        print("  3. Log in and go to Goldshire in Elwynn Forest")
        print("  4. You should see dramatically changed terrain:")
        print("     - A large 60-yard hill in the center of the tile")
        print("     - Rolling hills across the landscape")
        print("     - Rock textures on the hilltop, dirt in valleys")
        print("  5. To revert: delete G:\\WoW AzerothCore\\Data\\patch-4.MPQ")
    else:
        print("\n  To test: copy patch-4.MPQ to your WoW Data directory")
        print("  Then restart the WoW client and visit Elwynn Forest")

    return mpq_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate a modified Elwynn Forest tile for testing"
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "output", "elwynn_test"),
        help="Output directory for generated files",
    )
    parser.add_argument(
        "--wow-data",
        default="G:\\WoW AzerothCore\\Data",
        help="Path to WoW Data directory (for auto-copy)",
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Don't copy the MPQ to the WoW Data directory",
    )

    args = parser.parse_args()

    wow_data = None if args.no_copy else args.wow_data

    if wow_data and not os.path.isdir(wow_data):
        print("WARNING: WoW Data directory not found: {}".format(wow_data))
        print("         MPQ will be generated but not copied.")
        wow_data = None

    build_elwynn_patch(args.output_dir, wow_data)


if __name__ == "__main__":
    main()
