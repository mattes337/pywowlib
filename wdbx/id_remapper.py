"""
ID Remapper - Transforms layer-local IDs to real IDs during merge.

Local ID Syntax:
- @entity_type:N         - Local ID N for specified entity type (e.g., @item:50)
- @entity_type:slug      - Slug-based ID, auto-assigned and manifested (e.g., @item:iron-gauntlets)
- @entity_type:N:slug    - Explicit ID with slug for documentation (e.g., @item:90050:iron-gauntlets)
- @:N                    - Local ID N for same entity type as current record
- @:slug                 - Slug-based ID for same entity type
- @:N:slug               - Explicit ID with slug for same entity type
- Plain number           - Vanilla/real ID (unchanged)

Slug Syntax Rules:
- Lowercase letters, numbers, hyphens, underscores only
- Must start with a letter
- Maximum 64 characters

Manifestation Workflow:
1. User writes @item:iron-gauntlets (slug only)
2. Pipeline assigns next available ID (e.g., 90050)
3. Pipeline rewrites source to @item:90050:iron-gauntlets
4. Future runs use explicit ID (stable, no re-ordering)

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
class Manifestation:
    """Tracks an ID manifestation that needs to be written back to source."""
    yaml_path: str
    field_path: str  # e.g., "records.@:the-first-mail.RewardItem1"
    original: str    # "@item:iron-gauntlets"
    manifested: str  # "@item:90050:iron-gauntlets"


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

# Regex to match local ID patterns:
# Group 1-3: @entity:123 or @entity:123:slug (numeric ID, optional slug)
# Group 4-5: @entity:slug (slug only, no ID)
LOCAL_ID_PATTERN = re.compile(
    r'^@([a-zA-Z_]*):(\d+)(?::([a-z][a-z0-9_-]*))?$|'  # @e:123 or @e:123:slug
    r'^@([a-zA-Z_]*):([a-z][a-z0-9_-]*)$'              # @e:slug
)

# Slug validation pattern (same as embedded in LOCAL_ID_PATTERN)
SLUG_PATTERN = re.compile(r'^[a-z][a-z0-9_-]*$')

# Regex for finding @entity:N patterns in arbitrary text (e.g., Lua, conf files).
# Requires explicit entity type — @:N shorthand is NOT supported in text mode
# (no table context to infer entity type).
TEXT_ID_PATTERN = re.compile(r'@([a-zA-Z_]+):(\d+)(?::([a-z][a-z0-9_-]*))?')


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

        # Manifestation tracking
        self._manifestations: list[Manifestation] = []
        # {layer_entity_key: {real_id: slug}} - tracks already-manifested IDs
        self._manifested_ids: dict[str, dict[int, str]] = {}
        # {layer_entity_key: {slug: real_id}} - reverse lookup for cross-file consistency
        self._slug_to_id: dict[str, dict[str, int]] = {}

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

    def get_range(self, layer_id: str, entity_type: str, resolve_alias: bool = True) -> Optional[IDRange]:
        """
        Get the first available ID range for a layer/entity type.

        Args:
            layer_id: Layer identifier (e.g., "sensible-loot")
            entity_type: Entity type (e.g., "item_template")
            resolve_alias: Whether to resolve entity aliases (False for @:N same-table refs)

        Returns:
            IDRange if found, None otherwise
        """
        canonical_type = self.resolve_entity_type(entity_type) if resolve_alias else entity_type

        layer_ranges = self.ranges.get(canonical_type, {}).get(layer_id, [])
        if layer_ranges:
            return layer_ranges[0]

        return None

    def get_real_id(self, layer_id: str, entity_type: str, local_id: int, resolve_alias: bool = True) -> int:
        """
        Convert a local ID to a real ID.

        Args:
            layer_id: Layer identifier
            entity_type: Entity type (canonical or alias)
            local_id: Local ID (1-indexed)
            resolve_alias: Whether to resolve entity aliases (False for @:N same-table refs)

        Returns:
            Real ID

        Raises:
            ValueError: If no range found or local_id exceeds range
        """
        id_range = self.get_range(layer_id, entity_type, resolve_alias=resolve_alias)

        if not id_range:
            raise ValueError(
                f"No ID range found for layer '{layer_id}', "
                f"entity type '{entity_type}'"
            )

        return id_range.to_real(local_id)

    def parse_local_id(self, value: str) -> Optional[tuple[str, int | None, str | None]]:
        """
        Parse a local ID string.

        Supports formats:
        - @item:50              → ("item", 50, None)
        - @item:50:gauntlets    → ("item", 50, "gauntlets")
        - @item:gauntlets       → ("item", None, "gauntlets")
        - @:1                   → ("", 1, None)
        - @:1:gauntlets         → ("", 1, "gauntlets")
        - @:gauntlets           → ("", None, "gauntlets")

        Args:
            value: String value to parse

        Returns:
            Tuple of (entity_type, numeric_id or None, slug or None) if local ID, None otherwise
        """
        match = LOCAL_ID_PATTERN.match(value)
        if not match:
            return None

        # Check which group matched (numeric+optional slug vs slug-only)
        if match.group(1) is not None:
            # @entity:123 or @entity:123:slug format
            entity_type = match.group(1)
            numeric_id = int(match.group(2))
            slug = match.group(3)  # May be None
            return (entity_type, numeric_id, slug)
        else:
            # @entity:slug format
            entity_type = match.group(4)
            slug = match.group(5)
            return (entity_type, None, slug)

    def remap_value(
        self,
        layer_id: str,
        value: Any,
        default_entity_type: Optional[str] = None,
        yaml_path: Optional[str] = None,
        field_path: Optional[str] = None
    ) -> Any:
        """
        Remap a value if it contains a local ID reference.

        Args:
            layer_id: Layer identifier
            value: Value to potentially remap
            default_entity_type: Entity type to use for @:N syntax
            yaml_path: Path to source file (for manifestation tracking)
            field_path: Field path in record (for manifestation tracking)

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

        entity_type, numeric_id, slug = parsed

        # @:N or @:slug syntax uses default entity type (raw table name, no alias)
        # @entity:N uses explicit entity type (alias resolution applies)
        use_alias = True
        if not entity_type:
            if not default_entity_type:
                raise ValueError(
                    f"@:N syntax requires default_entity_type, got: {value}"
                )
            entity_type = default_entity_type
            use_alias = False  # @:N refs use raw table name for range lookup

        # Resolve entity type alias (only for explicit cross-table references)
        canonical_type = self.resolve_entity_type(entity_type) if use_alias else entity_type
        key = f"{layer_id}_{canonical_type}"

        if numeric_id is not None:
            # Explicit numeric ID - use it directly
            real_id = self.get_real_id(layer_id, entity_type, numeric_id, resolve_alias=use_alias)
        elif slug is not None:
            # Slug-only - look up or assign ID
            real_id = self._resolve_slug(layer_id, entity_type, slug, yaml_path, field_path, resolve_alias=use_alias)
        else:
            # Should not happen with valid regex
            return value

        return -real_id if negative else real_id

    def remap_pk(
        self,
        layer_id: str,
        pk_value: Any,
        default_entity_type: Optional[str] = None,
        yaml_path: Optional[str] = None,
        field_path: Optional[str] = None
    ) -> Any:
        """
        Remap a primary key value.

        Handles both single IDs and composite PKs with pipe-delimited format.

        Args:
            layer_id: Layer identifier
            pk_value: PK value (can be string, int, or pipe-delimited)
            default_entity_type: Entity type for @:N syntax
            yaml_path: Path to source file (for manifestation tracking)
            field_path: Field path in record (for manifestation tracking)

        Returns:
            Remapped PK value
        """
        if isinstance(pk_value, int):
            return pk_value

        if not isinstance(pk_value, str):
            return pk_value

        # Check for pipe-delimited composite PK
        if "|" in pk_value:
            return self.remap_composite_pk(layer_id, pk_value, default_entity_type, yaml_path, field_path)

        # Single value
        return self.remap_value(layer_id, pk_value, default_entity_type, yaml_path, field_path)

    def remap_composite_pk(
        self,
        layer_id: str,
        pk_str: str,
        default_entity_type: Optional[str] = None,
        yaml_path: Optional[str] = None,
        field_path: Optional[str] = None
    ) -> str:
        """
        Remap a composite PK with pipe-delimited format.

        Each component is remapped independently if it's a local ID.

        Args:
            layer_id: Layer identifier
            pk_str: Pipe-delimited PK string (e.g., "38|@item:500")
            default_entity_type: Entity type for @:N syntax
            yaml_path: Path to source file (for manifestation tracking)
            field_path: Field path in record (for manifestation tracking)

        Returns:
            Remapped pipe-delimited PK string
        """
        components = pk_str.split("|")
        remapped = []

        for i, component in enumerate(components):
            component = component.strip()
            parsed = self.parse_local_id(component)

            if parsed:
                entity_type, numeric_id, slug = parsed
                use_alias = True
                if not entity_type:
                    entity_type = default_entity_type or ""
                    use_alias = False  # @:N refs use raw table name

                canonical_type = self.resolve_entity_type(entity_type) if use_alias else entity_type
                key = f"{layer_id}_{canonical_type}"

                if numeric_id is not None:
                    real_id = self.get_real_id(layer_id, entity_type, numeric_id, resolve_alias=use_alias)
                elif slug is not None:
                    component_path = f"{field_path}[{i}]" if field_path else f"pk[{i}]"
                    real_id = self._resolve_slug(layer_id, entity_type, slug, yaml_path, component_path, resolve_alias=use_alias)
                else:
                    remapped.append(component)
                    continue

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

    def remap_text(self, layer_id: str, text: str) -> str:
        """
        Replace all @entity_type:N patterns in arbitrary text with real IDs.

        Unlike YAML remapping, this does NOT support @:N shorthand
        (no table context in text files). Entity type must be explicit.

        Patterns that can't be resolved (unknown layer/entity or out-of-range)
        are left unchanged.

        Args:
            layer_id: Layer identifier (e.g., "profession-quests")
            text: Input text containing @entity:N patterns

        Returns:
            Text with @entity:N patterns replaced by real ID numbers
        """
        def replacer(match):
            entity_type = match.group(1)
            local_id = int(match.group(2))
            try:
                real_id = self.get_real_id(layer_id, entity_type, local_id)
                return str(real_id)
            except ValueError:
                # No range found or out of range — leave unchanged
                return match.group(0)

        return TEXT_ID_PATTERN.sub(replacer, text)

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

    # =========================================================================
    # Manifestation System
    # =========================================================================

    def _get_key(self, layer_id: str, entity_type: str, resolve_alias: bool = True) -> str:
        """Get the storage key for a layer/entity combination."""
        canonical = self.resolve_entity_type(entity_type) if resolve_alias else entity_type
        return f"{layer_id}_{canonical}"

    def _resolve_slug(
        self,
        layer_id: str,
        entity_type: str,
        slug: str,
        yaml_path: Optional[str] = None,
        field_path: Optional[str] = None,
        resolve_alias: bool = True
    ) -> int:
        """
        Resolve a slug to a real ID.

        If the slug has already been manifested, returns the existing ID.
        Otherwise, assigns a new ID and tracks it for source rewriting.

        Args:
            layer_id: Layer identifier
            entity_type: Entity type
            slug: Slug string
            yaml_path: Path to source file (for manifestation tracking)
            field_path: Field path in record (for manifestation tracking)
            resolve_alias: Whether to resolve entity aliases (False for @:N same-table refs)

        Returns:
            Real ID for this slug
        """
        key = self._get_key(layer_id, entity_type, resolve_alias=resolve_alias)

        # Check if already resolved
        if key in self._slug_to_id and slug in self._slug_to_id[key]:
            return self._slug_to_id[key][slug]

        # Assign new ID
        real_id = self._assign_next_id(layer_id, entity_type, slug, resolve_alias=resolve_alias)

        # Track manifestation if we have source info
        if yaml_path and field_path:
            original = f"@{entity_type}:{slug}"
            manifested = f"@{entity_type}:{real_id}:{slug}"
            self._manifestations.append(Manifestation(
                yaml_path=yaml_path,
                field_path=field_path,
                original=original,
                manifested=manifested
            ))

        return real_id

    def _assign_next_id(self, layer_id: str, entity_type: str, slug: str, resolve_alias: bool = True) -> int:
        """
        Assign the next available ID to a slug.

        Args:
            layer_id: Layer identifier
            entity_type: Entity type
            slug: Slug string
            resolve_alias: Whether to resolve entity aliases (False for @:N same-table refs)

        Returns:
            Assigned real ID
        """
        key = self._get_key(layer_id, entity_type, resolve_alias=resolve_alias)
        id_range = self.get_range(layer_id, entity_type, resolve_alias=resolve_alias)

        if not id_range:
            raise ValueError(
                f"No ID range found for layer '{layer_id}', entity type '{entity_type}'"
            )

        # Initialize tracking if needed
        if key not in self._manifested_ids:
            self._manifested_ids[key] = {}
        if key not in self._slug_to_id:
            self._slug_to_id[key] = {}

        used_ids = set(self._manifested_ids[key].keys())

        # Find next available ID starting from 1
        local_id = 1
        while True:
            real_id = id_range.to_real(local_id)
            if real_id not in used_ids:
                break
            local_id += 1
            if local_id > id_range.count:
                raise ValueError(
                    f"ID range exhausted for layer '{layer_id}', entity type '{entity_type}'"
                )

        # Record the assignment
        self._manifested_ids[key][real_id] = slug
        self._slug_to_id[key][slug] = real_id

        return real_id

    def scan_manifested_ids(
        self,
        yaml_files: list[tuple[str, str, dict, str]]
    ) -> None:
        """
        Pre-scan files to collect already-manifested IDs.

        Call this before processing to ensure we don't reassign existing IDs.

        Args:
            yaml_files: List of (yaml_path, table_name, data, layer_id) tuples
        """
        for yaml_path, table_name, data, layer_id in yaml_files:
            self._scan_file_manifestations(yaml_path, table_name, data, layer_id)

    def _scan_file_manifestations(
        self,
        yaml_path: str,
        table_name: str,
        data: dict,
        layer_id: str
    ) -> None:
        """Scan a single file for already-manifested IDs."""
        records = data.get("records", {})

        for pk_key, fields in records.items():
            if not isinstance(fields, dict):
                continue

            # Scan PK
            if isinstance(pk_key, str) and pk_key.startswith("@"):
                self._collect_manifested_pk(layer_id, table_name, pk_key)

            # Scan fields
            for field_name, value in fields.items():
                self._collect_manifested_value(layer_id, table_name, value)

    def _collect_manifested_pk(self, layer_id: str, table_name: str, pk: str) -> None:
        """Collect manifested IDs from a primary key."""
        # Handle pipe-delimited PKs
        if "|" in pk:
            for component in pk.split("|"):
                self._collect_manifested_single(layer_id, table_name, component.strip())
        else:
            self._collect_manifested_single(layer_id, table_name, pk)

    def _collect_manifested_value(
        self,
        layer_id: str,
        default_entity: str,
        value: Any
    ) -> None:
        """Recursively collect manifested IDs from a value."""
        if isinstance(value, str) and value.startswith("@"):
            self._collect_manifested_single(layer_id, default_entity, value)
        elif isinstance(value, dict):
            for v in value.values():
                self._collect_manifested_value(layer_id, default_entity, v)
        elif isinstance(value, list):
            for item in value:
                self._collect_manifested_value(layer_id, default_entity, item)

    def _collect_manifested_single(
        self,
        layer_id: str,
        default_entity: str,
        value: str
    ) -> None:
        """Collect a single manifested ID if it has an explicit numeric ID.

        The numeric ID in @entity:N:slug format is a REAL ID (already manifested).
        """
        parsed = self.parse_local_id(value)
        if not parsed:
            return

        entity_type, numeric_id, slug = parsed

        # Only collect if we have an explicit numeric ID
        if numeric_id is None:
            return

        # Resolve entity type
        if not entity_type:
            entity_type = default_entity

        key = self._get_key(layer_id, entity_type)

        # Initialize tracking if needed
        if key not in self._manifested_ids:
            self._manifested_ids[key] = {}
        if key not in self._slug_to_id:
            self._slug_to_id[key] = {}

        # Record the manifested ID
        # Note: numeric_id is already a REAL ID (manifested), not a local ID
        id_range = self.get_range(layer_id, entity_type)
        if id_range and id_range.base <= numeric_id <= id_range.end:
            real_id = numeric_id
            self._manifested_ids[key][real_id] = slug or ""
            if slug:
                self._slug_to_id[key][slug] = real_id

    def write_manifestations(self) -> int:
        """
        Rewrite source YAML files with manifested IDs.

        Returns:
            Number of files modified
        """
        if not self._manifestations:
            return 0

        # Group by file
        by_file: dict[str, list[Manifestation]] = {}
        for m in self._manifestations:
            by_file.setdefault(m.yaml_path, []).append(m)

        files_changed = 0
        for yaml_path, manifests in by_file.items():
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    content = f.read()

                original_content = content

                # Apply all manifestations for this file
                for m in manifests:
                    content = content.replace(m.original, m.manifested)

                if content != original_content:
                    with open(yaml_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    files_changed += 1

            except Exception as e:
                print(f"Warning: Could not write manifestations to {yaml_path}: {e}")

        return files_changed

    def get_manifestations(self) -> list[Manifestation]:
        """Get list of pending manifestations."""
        return self._manifestations.copy()

    def clear_manifestations(self) -> None:
        """Clear all pending manifestations (useful for testing)."""
        self._manifestations.clear()
