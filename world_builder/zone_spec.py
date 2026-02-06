"""
Zone Specification - AI agent output schema for zone generation.

Defines a strict-but-flexible dataclass schema for describing WoW zones
in JSON.  An AI agent (LLM) produces a ZoneSpec JSON, which the
generate_zone.py script consumes to build a playable MPQ patch.

The schema validates all fields and normalises positions (named strings
like "center" or [x, y] arrays) into float tuples.

Usage:
    from world_builder.zone_spec import ZoneSpec

    spec = ZoneSpec.from_json("my_zone.json")
    spec.validate()
    landmarks = spec.to_landmarks()
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from .zone_planner import (
    NAMED_POSITIONS,
    ZONE_ARCHETYPES,
    _LANDMARK_TRANSLATORS,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported types (kept in sync with zone_planner)
# ---------------------------------------------------------------------------

FEATURE_TYPES = sorted(set(_LANDMARK_TRANSLATORS.keys()))

BUILDING_TYPES = [
    'inn', 'blacksmith', 'farm', 'guard_tower', 'barracks',
    'church', 'stable', 'mine_entrance', 'lumber_mill',
    'townhall', 'house', 'shop', 'warehouse', 'dock',
]

BUILDING_STYLES = [
    'human_elwynn', 'human_duskwood', 'human_westfall',
    'night_elf', 'dwarf', 'orc', 'undead', 'tauren',
    'troll', 'blood_elf', 'draenei', 'goblin', 'northrend',
]

VEGETATION_DENSITIES = ['none', 'sparse', 'light', 'moderate', 'dense', 'thick']


# ---------------------------------------------------------------------------
# Position helpers
# ---------------------------------------------------------------------------

def _normalise_position(pos):
    """Resolve a position to (float, float) in [0, 1].

    Accepts:
        - Named string: 'center', 'northeast', etc.
        - List/tuple: [x, y] with values in [0, 1].

    Returns:
        (float, float)

    Raises:
        ValueError on unrecognised string or out-of-range coordinates.
    """
    if isinstance(pos, str):
        key = pos.lower().replace(' ', '_')
        resolved = NAMED_POSITIONS.get(key)
        if resolved is None:
            raise ValueError(
                "Unknown position name '{}'. Valid: {}".format(
                    pos, ', '.join(sorted(NAMED_POSITIONS.keys()))))
        return resolved
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        x, y = float(pos[0]), float(pos[1])
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError(
                "Position coordinates must be in [0, 1], got ({}, {})".format(x, y))
        return (x, y)
    raise ValueError(
        "Position must be a name string or [x, y], got: {!r}".format(pos))


# ---------------------------------------------------------------------------
# ZoneSpec dataclass
# ---------------------------------------------------------------------------

@dataclass
class ZoneSpec:
    """Validated zone specification from AI agent output."""

    name: str
    archetype: str
    features: list = field(default_factory=list)
    buildings: list = field(default_factory=list)
    roads: list = field(default_factory=list)
    water_regions: list = field(default_factory=list)
    style: dict = field(default_factory=dict)
    grid_size: tuple = (1, 1)
    base_coords: tuple = (32, 32)
    sea_level: float = 0.0
    seed: int = None
    description: str = ""

    # -- Constructors -------------------------------------------------------

    @classmethod
    def from_json(cls, path_or_str):
        """Load and validate from a JSON file path or JSON string.

        Args:
            path_or_str: Filesystem path to a .json file, or a raw JSON string.

        Returns:
            Validated ZoneSpec instance.
        """
        try:
            with open(path_or_str, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, IOError):
            data = json.loads(path_or_str)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, d):
        """Load and validate from a dict.

        Args:
            d: Dictionary matching the zone spec JSON schema.

        Returns:
            Validated ZoneSpec instance.
        """
        grid_size = d.get('grid_size', (1, 1))
        if isinstance(grid_size, list):
            grid_size = tuple(grid_size)
        base_coords = d.get('base_coords', (32, 32))
        if isinstance(base_coords, list):
            base_coords = tuple(base_coords)

        spec = cls(
            name=d.get('name', 'Unnamed Zone'),
            archetype=d.get('archetype', 'forested_highlands'),
            features=list(d.get('features', [])),
            buildings=list(d.get('buildings', [])),
            roads=list(d.get('roads', [])),
            water_regions=list(d.get('water_regions', [])),
            style=dict(d.get('style', {})),
            grid_size=grid_size,
            base_coords=base_coords,
            sea_level=float(d.get('sea_level', 0.0)),
            seed=d.get('seed', None),
            description=d.get('description', ''),
        )
        spec.validate()
        return spec

    # -- Validation ---------------------------------------------------------

    def validate(self):
        """Validate all fields.  Raises ValueError on problems."""
        errors = []

        # Name
        if not self.name or not self.name.strip():
            errors.append("'name' must be a non-empty string")

        # Archetype
        if self.archetype not in ZONE_ARCHETYPES:
            errors.append(
                "Unknown archetype '{}'. Valid: {}".format(
                    self.archetype, ', '.join(sorted(ZONE_ARCHETYPES.keys()))))

        # Grid size
        gw, gh = self.grid_size
        if not (1 <= gw <= 4 and 1 <= gh <= 4):
            errors.append(
                "grid_size must be [1-4, 1-4], got {}".format(self.grid_size))

        # Seed: auto-generate from name hash if missing
        if self.seed is None:
            self.seed = int(hashlib.md5(
                self.name.encode('utf-8')).hexdigest()[:8], 16)

        # Features
        for i, feat in enumerate(self.features):
            ftype = feat.get('type', '')
            if ftype not in FEATURE_TYPES:
                errors.append(
                    "features[{}].type '{}' unknown. Valid: {}".format(
                        i, ftype, ', '.join(FEATURE_TYPES)))
            try:
                _normalise_position(feat.get('position', 'center'))
            except ValueError as e:
                errors.append("features[{}].position: {}".format(i, e))

        # Buildings
        for i, bld in enumerate(self.buildings):
            btype = bld.get('type', '')
            if btype not in BUILDING_TYPES:
                errors.append(
                    "buildings[{}].type '{}' unknown. Valid: {}".format(
                        i, btype, ', '.join(BUILDING_TYPES)))
            pos = bld.get('position')
            if pos is None:
                errors.append("buildings[{}] missing 'position'".format(i))
            else:
                try:
                    _normalise_position(pos)
                except ValueError as e:
                    errors.append("buildings[{}].position: {}".format(i, e))
            rot = bld.get('rotation', 0)
            if not (0 <= rot <= 360):
                errors.append(
                    "buildings[{}].rotation must be 0-360, got {}".format(i, rot))

        # Roads
        for i, road in enumerate(self.roads):
            waypoints = road.get('waypoints', [])
            if len(waypoints) < 2:
                errors.append(
                    "roads[{}] must have 2+ waypoints, got {}".format(
                        i, len(waypoints)))
            for j, wp in enumerate(waypoints):
                try:
                    _normalise_position(wp)
                except ValueError as e:
                    errors.append(
                        "roads[{}].waypoints[{}]: {}".format(i, j, e))

        # Style validation
        bstyle = self.style.get('building_style')
        if bstyle and bstyle not in BUILDING_STYLES:
            errors.append(
                "style.building_style '{}' unknown. Valid: {}".format(
                    bstyle, ', '.join(BUILDING_STYLES)))

        veg = self.style.get('vegetation_density')
        if veg and veg not in VEGETATION_DENSITIES:
            errors.append(
                "style.vegetation_density '{}' unknown. Valid: {}".format(
                    veg, ', '.join(VEGETATION_DENSITIES)))

        if errors:
            raise ValueError(
                "ZoneSpec validation failed:\n  - " + "\n  - ".join(errors))

    # -- Conversion to zone_planner landmarks -------------------------------

    def to_landmarks(self):
        """Convert features list to zone_planner landmark format.

        Each feature dict is mapped to the landmark dict format expected
        by plan_zone(landmarks=[...]).  Position strings are preserved
        (zone_planner resolves them internally), and [x,y] arrays are
        passed through as tuples.

        Returns:
            list[dict]: Landmark dicts compatible with plan_zone().
        """
        landmarks = []
        for feat in self.features:
            lm = {
                'type': feat['type'],
                'position': feat.get('position', 'center'),
            }
            if 'name' in feat:
                lm['name'] = feat['name']
            # Pass through all params
            params = feat.get('params', {})
            for k, v in params.items():
                lm[k] = v
            # Also pass through top-level extra keys
            for k, v in feat.items():
                if k not in ('type', 'position', 'name', 'params'):
                    lm[k] = v
            landmarks.append(lm)
        return landmarks

    # -- Serialisation ------------------------------------------------------

    def to_dict(self):
        """Serialise back to a JSON-compatible dict.

        Returns:
            dict matching the zone spec JSON schema.
        """
        return {
            'name': self.name,
            'description': self.description,
            'archetype': self.archetype,
            'grid_size': list(self.grid_size),
            'base_coords': list(self.base_coords),
            'sea_level': self.sea_level,
            'seed': self.seed,
            'style': self.style,
            'features': self.features,
            'buildings': self.buildings,
            'roads': self.roads,
            'water_regions': self.water_regions,
        }

    def to_json(self, path=None, indent=2):
        """Serialise to JSON string, optionally writing to a file.

        Args:
            path: Optional file path to write to.
            indent: JSON indentation (default 2).

        Returns:
            str: JSON string.
        """
        text = json.dumps(self.to_dict(), indent=indent)
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
        return text
