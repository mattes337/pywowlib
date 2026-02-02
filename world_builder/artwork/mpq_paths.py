"""
MPQ path generation for artwork assets.

Produces the correct internal MPQ paths that the WoW 3.3.5a client expects
for world-map textures, subzone overlays, loading screens and dungeon maps.
All paths use backslash separators per WoW/MPQ convention.
"""

import re


def _sanitise_name(name):
    """Remove non-alphanumeric characters (except underscores) from *name*."""
    return re.sub(r"[^A-Za-z0-9_]", "", name.replace("'", "").replace(" ", ""))


# ---------------------------------------------------------------------------
# World map paths
# ---------------------------------------------------------------------------

def world_map_base_path(zone_name):
    """
    Return the MPQ directory for world-map artwork.

    Example: Interface\\WorldMap\\TelAbim
    """
    safe = _sanitise_name(zone_name)
    return "Interface\\WorldMap\\{}".format(safe)


def world_map_blp_path(zone_name):
    """
    Return the full BLP path for the zone overview world-map image.

    Example: Interface\\WorldMap\\TelAbim\\TelAbim.blp
    """
    safe = _sanitise_name(zone_name)
    return "Interface\\WorldMap\\{}\\{}.blp".format(safe, safe)


# ---------------------------------------------------------------------------
# Subzone overlay paths
# ---------------------------------------------------------------------------

def subzone_overlay_blp_path(zone_name, subzone_name):
    """
    Return the BLP path for a subzone discovery overlay.

    Example: Interface\\WorldMap\\TelAbim\\PalmbreakShore_overlay.blp
    """
    safe_zone = _sanitise_name(zone_name)
    safe_sub = _sanitise_name(subzone_name)
    return "Interface\\WorldMap\\{}\\{}_overlay.blp".format(safe_zone, safe_sub)


# ---------------------------------------------------------------------------
# Loading screen paths
# ---------------------------------------------------------------------------

def loading_screen_blp_path(zone_name, widescreen=False):
    """
    Return the BLP path for a loading screen.

    Args:
        zone_name:  Zone or dungeon name.
        widescreen: If True, append '_wide' suffix.

    Example: Interface\\Glues\\LoadingScreens\\TelAbim.blp
             Interface\\Glues\\LoadingScreens\\TelAbim_wide.blp
    """
    safe = _sanitise_name(zone_name)
    suffix = "_wide" if widescreen else ""
    return "Interface\\Glues\\LoadingScreens\\{}{}.blp".format(safe, suffix)


# ---------------------------------------------------------------------------
# Dungeon map paths
# ---------------------------------------------------------------------------

def dungeon_map_blp_path(dungeon_name):
    """
    Return the BLP path for a dungeon map overlay.

    Example: Interface\\WorldMap\\VaultOfStorms\\VaultOfStorms.blp
    """
    safe = _sanitise_name(dungeon_name)
    return "Interface\\WorldMap\\{}\\{}.blp".format(safe, safe)
