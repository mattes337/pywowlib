"""
ID Remapper - Transforms layer-local IDs to real IDs during merge.

Local ID Syntax:
- @entity_type:N  - Local ID N for specified entity type (e.g., @item:50)
- @:N             - Local ID N for same entity type as current record
- Plain number    - Vanilla/real ID (unchanged)

Entity Type Aliases:
- quest       → quest_template
- item        → item_template
- creature    → creature_template
- go / gameobject → gameobject_template
- spell       → spell_dbc (server) or Spell (client DBC)
- npc         → creature_template
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class IDRange:
    """Represents an ID range for a layer/entity type."""
    layer: str
    entity_type: str
    base: int
    end: int

    @property
    def count(self) -> int:
        """Number of IDs in this range."""
        return self.end - self.base + 1

    def contains(self, local_id: int) -> bool:
        """Check if local_id fits in this range (1-indexed)."""
        return 1 <= local_id <= self.count

    def to_real(self, local_id: int) -> int:
        """Convert local ID to real ID."""
        if not self.contains(local_id):
            raise ValueError(
                f"Local ID {local_id} exceeds range {self.base}-{self.end} "
                f"(max local: {self.count})"
            )
        return self.base + local_id - 1


# Entity type aliases - short names to canonical names
ENTITY_ALIASES = {
    "quest": "quest_template",
    "item": "item_template",
    "i": "item_template",  # Short alias
    "creature": "creature_template",
    "c": "creature_template",  # Short alias
    "npc": "creature_template",
    "go": "gameobject_template",
    "gameobject": "gameobject_template",
    "g": "gameobject_template",  # Short alias
    "spell": "spell_dbc",  # Server-side default
    "loot": "creature_loot_template",
    "goloot": "gameobject_loot_template",
    "area": "AreaTable",
    "map": "Map",
    # Client DBC aliases (capitalized)
    "Spell": "Spell",
    "Item": "Item",
    "Map": "Map",
    "AreaTable": "AreaTable",
}

# Regex to match @entity_type:N or @:N syntax
LOCAL_ID_PATTERN = re.compile(r'^@([a-zA-Z_]*):(\d+)$')


class IDRemapper:
    """
    Transforms layer-local IDs to real IDs during merge.

    Loads ID range configuration from id-registry.yaml and provides
    methods to remap @entity_type:N syntax to real IDs.
    """

    def __init__(self, registry_path: Optional[str] = None):
        """
        Initialize the remapper.

        Args:
            registry_path: Path to id-registry.yaml. If None, searches default locations.
        """
        self.registry_path = self._find_registry(registry_path)
        self.config: dict = self._load_config()
        self.ranges: dict[str, dict[str, list[IDRange]]] = self._parse_ranges()

    def _find_registry(self, registry_path: Optional[str]) -> Path:
        """Find the id-registry.yaml file."""
        if registry_path:
            path = Path(registry_path)
            if path.exists():
                return path

        # Search in common locations
        search_paths = [
            Path(".patch/id-registry.yaml"),
            Path("../.patch/id-registry.yaml"),
            Path("G:/WoW Projects/.patch/id-registry.yaml"),
        ]

        for path in search_paths:
            if path.exists():
                return path

        raise FileNotFoundError(
            "Could not find id-registry.yaml. "
            "Please specify the path explicitly."
        )

    def _load_config(self) -> dict:
        """Load the id-registry.yaml configuration."""
        with open(self.registry_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _parse_ranges(self) -> dict[str, dict[str, list[IDRange]]]:
        """
        Parse ID ranges from config into structured format.

        Returns:
            {entity_type: {layer_id: [IDRange, ...]}}
        """
        ranges: dict[str, dict[str, list[IDRange]]] = {}
        id_ranges = self.config.get("id_ranges", {})

        for entity_type, layer_entries in id_ranges.items():
            if entity_type not in ranges:
                ranges[entity_type] = {}

            for entry in layer_entries:
                layer_id = entry.get("layer", "")
                range_str = entry.get("range", "")

                if not layer_id or not range_str:
                    continue

                # Parse range "90001-90099"
                try:
                    if "-" in range_str:
                        base, end = map(int, range_str.split("-"))
                    else:
                        # Single ID
                        base = end = int(range_str)
                except ValueError:
                    continue

                id_range = IDRange(
                    layer=layer_id,
                    entity_type=entity_type,
                    base=base,
                    end=end
                )

                if layer_id not in ranges[entity_type]:
                    ranges[entity_type][layer_id] = []
                ranges[entity_type][layer_id].append(id_range)

        return ranges

    def resolve_entity_type(self, entity_type: str) -> str:
        """
        Resolve an entity type alias to its canonical name.

        Args:
            entity_type: Short name (e.g., "item") or canonical name

        Returns:
            Canonical entity type name
        """
        return ENTITY_ALIASES.get(entity_type, entity_type)

    def get_range(self, layer_id: str, entity_type: str) -> Optional[IDRange]:
        """
        Get the first available ID range for a layer/entity type.

        Args:
            layer_id: Layer identifier (e.g., "sensible-loot")
            entity_type: Entity type (e.g., "item_template")

        Returns:
            IDRange if found, None otherwise
        """
        canonical_type = self.resolve_entity_type(entity_type)

        layer_ranges = self.ranges.get(canonical_type, {}).get(layer_id, [])
        if layer_ranges:
            return layer_ranges[0]

        return None

    def get_real_id(self, layer_id: str, entity_type: str, local_id: int) -> int:
        """
        Convert a local ID to a real ID.

        Args:
            layer_id: Layer identifier
            entity_type: Entity type (canonical or alias)
            local_id: Local ID (1-indexed)

        Returns:
            Real ID

        Raises:
            ValueError: If no range found or local_id exceeds range
        """
        id_range = self.get_range(layer_id, entity_type)

        if not id_range:
            raise ValueError(
                f"No ID range found for layer '{layer_id}', "
                f"entity type '{entity_type}'"
            )

        return id_range.to_real(local_id)

    def parse_local_id(self, value: str) -> Optional[tuple[str, int]]:
        """
        Parse a local ID string like "@item:50" or "@:1".

        Args:
            value: String value to parse

        Returns:
            Tuple of (entity_type, local_id) if local ID, None otherwise
        """
        match = LOCAL_ID_PATTERN.match(value)
        if not match:
            return None

        entity_type = match.group(1)  # Empty for @:N syntax
        local_id = int(match.group(2))

        return (entity_type, local_id)

    def remap_value(
        self,
        layer_id: str,
        value: Any,
        default_entity_type: Optional[str] = None
    ) -> Any:
        """
        Remap a value if it contains a local ID reference.

        Args:
            layer_id: Layer identifier
            value: Value to potentially remap
            default_entity_type: Entity type to use for @:N syntax

        Returns:
            Remapped value (int) or original value if not a local ID
        """
        if not isinstance(value, str):
            return value

        # Handle negative prefix (for RequiredNpcOrGo gameobject references)
        negative = False
        work_value = value
        if value.startswith('-'):
            negative = True
            work_value = value[1:]

        parsed = self.parse_local_id(work_value)
        if not parsed:
            return value

        entity_type, local_id = parsed

        # @:N syntax uses default entity type
        if not entity_type:
            if not default_entity_type:
                raise ValueError(
                    f"@:N syntax requires default_entity_type, got: {value}"
                )
            entity_type = default_entity_type

        real_id = self.get_real_id(layer_id, entity_type, local_id)
        return -real_id if negative else real_id

    def remap_pk(
        self,
        layer_id: str,
        pk_value: Any,
        default_entity_type: Optional[str] = None
    ) -> Any:
        """
        Remap a primary key value.

        Handles both single IDs and composite PKs with pipe-delimited format.

        Args:
            layer_id: Layer identifier
            pk_value: PK value (can be string, int, or pipe-delimited)
            default_entity_type: Entity type for @:N syntax

        Returns:
            Remapped PK value
        """
        if isinstance(pk_value, int):
            return pk_value

        if not isinstance(pk_value, str):
            return pk_value

        # Check for pipe-delimited composite PK
        if "|" in pk_value:
            return self.remap_composite_pk(layer_id, pk_value, default_entity_type)

        # Single value
        return self.remap_value(layer_id, pk_value, default_entity_type)

    def remap_composite_pk(
        self,
        layer_id: str,
        pk_str: str,
        default_entity_type: Optional[str] = None
    ) -> str:
        """
        Remap a composite PK with pipe-delimited format.

        Each component is remapped independently if it's a local ID.

        Args:
            layer_id: Layer identifier
            pk_str: Pipe-delimited PK string (e.g., "38|@item:500")
            default_entity_type: Entity type for @:N syntax

        Returns:
            Remapped pipe-delimited PK string
        """
        components = pk_str.split("|")
        remapped = []

        for component in components:
            component = component.strip()
            parsed = self.parse_local_id(component)

            if parsed:
                entity_type, local_id = parsed
                if not entity_type:
                    entity_type = default_entity_type or ""
                real_id = self.get_real_id(layer_id, entity_type, local_id)
                remapped.append(str(real_id))
            else:
                remapped.append(component)

        return "|".join(remapped)

    def remap_record(
        self,
        layer_id: str,
        table_name: str,
        record: dict,
        pk_value: Any
    ) -> tuple[dict, Any]:
        """
        Remap all IDs in a record including PK and all field values.

        Args:
            layer_id: Layer identifier
            table_name: Table name (used as default entity type for @:N)
            record: Record dictionary with field values
            pk_value: Primary key value

        Returns:
            Tuple of (remapped_record, remapped_pk)
        """
        default_entity = table_name

        # Remap PK
        remapped_pk = self.remap_pk(layer_id, pk_value, default_entity)

        # Remap all field values
        remapped_record = {}
        for field_name, field_value in record.items():
            if isinstance(field_value, str):
                remapped_record[field_name] = self.remap_value(
                    layer_id, field_value, default_entity
                )
            elif isinstance(field_value, (int, float, bool)):
                remapped_record[field_name] = field_value
            elif isinstance(field_value, dict):
                # Handle nested dicts (e.g., localized strings)
                remapped_record[field_name] = self._remap_dict(
                    layer_id, field_value, default_entity
                )
            elif isinstance(field_value, list):
                # Handle arrays (e.g., DBC fields like Effect: [27, 0, 0])
                remapped_record[field_name] = self._remap_list(
                    layer_id, field_value, default_entity
                )
            else:
                remapped_record[field_name] = field_value

        return remapped_record, remapped_pk

    def _remap_dict(
        self,
        layer_id: str,
        value: dict,
        default_entity_type: Optional[str]
    ) -> dict:
        """Remap values in a nested dictionary."""
        result = {}
        for k, v in value.items():
            if isinstance(v, str):
                result[k] = self.remap_value(layer_id, v, default_entity_type)
            elif isinstance(v, dict):
                result[k] = self._remap_dict(layer_id, v, default_entity_type)
            elif isinstance(v, list):
                result[k] = self._remap_list(layer_id, v, default_entity_type)
            else:
                result[k] = v
        return result

    def _remap_list(
        self,
        layer_id: str,
        value: list,
        default_entity_type: Optional[str]
    ) -> list:
        """Remap values in a list."""
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(self.remap_value(layer_id, item, default_entity_type))
            elif isinstance(item, dict):
                result.append(self._remap_dict(layer_id, item, default_entity_type))
            elif isinstance(item, list):
                result.append(self._remap_list(layer_id, item, default_entity_type))
            else:
                result.append(item)
        return result

    def validate_local_id(
        self,
        layer_id: str,
        entity_type: str,
        local_id: int
    ) -> tuple[bool, str]:
        """
        Validate that a local ID is within the allocated range.

        Args:
            layer_id: Layer identifier
            entity_type: Entity type
            local_id: Local ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        id_range = self.get_range(layer_id, entity_type)

        if not id_range:
            return False, f"No ID range found for layer '{layer_id}', type '{entity_type}'"

        if local_id < 1:
            return False, f"Local ID must be >= 1, got {local_id}"

        if local_id > id_range.count:
            return False, (
                f"Local ID {local_id} exceeds range {id_range.base}-{id_range.end} "
                f"(max local: {id_range.count})"
            )

        return True, ""

    def get_layer_ranges(self, layer_id: str) -> dict[str, list[IDRange]]:
        """
        Get all ID ranges for a specific layer.

        Args:
            layer_id: Layer identifier

        Returns:
            Dict of {entity_type: [IDRange, ...]}
        """
        result = {}
        for entity_type, layer_ranges in self.ranges.items():
            if layer_id in layer_ranges:
                result[entity_type] = layer_ranges[layer_id]
        return result

    def list_layers(self) -> list[str]:
        """Get list of all layer IDs that have registered ranges."""
        layers = set()
        for entity_type, layer_ranges in self.ranges.items():
            layers.update(layer_ranges.keys())
        return sorted(layers)

    def list_entity_types(self) -> list[str]:
        """Get list of all entity types with registered ranges."""
        return sorted(self.ranges.keys())
