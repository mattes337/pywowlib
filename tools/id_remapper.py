#!/usr/bin/env python3
"""ID Remapper CLI - Transform layer-local IDs to real IDs.

Usage:
    python id_remapper.py analyze --layer sensible-loot   # Find conversion candidates
    python id_remapper.py preview --layer sensible-loot   # Preview remapping
    python id_remapper.py migrate --layer sensible-loot   # Convert to local format
    python id_remapper.py validate                        # Validate local IDs
    python id_remapper.py ranges                          # Show configured ranges
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from wdbx.id_remapper import IDRemapper, ENTITY_ALIASES, LOCAL_ID_PATTERN

PROJECT_ROOT = Path(__file__).parent.parent.parent
REGISTRY_PATH = PROJECT_ROOT / ".patch" / "id-registry.yaml"
PATCH_DIR = PROJECT_ROOT / ".patch"


def detect_layer_from_path(yaml_path: str) -> Optional[str]:
    """Extract layer ID from yaml path."""
    parts = Path(yaml_path).parts
    for i, part in enumerate(parts):
        if part == ".patch" and i + 1 < len(parts):
            layer_dir = parts[i + 1]
            if layer_dir.startswith("dev-"):
                return layer_dir[4:]
            elif layer_dir[0].isdigit() and "-" in layer_dir:
                return layer_dir.split("-", 1)[1] if "-" in layer_dir else layer_dir
            return layer_dir
    return None


def scan_yaml_files(layer_id: str) -> list[tuple[str, str, dict]]:
    """Scan all YAML files in a layer.

    Returns: [(yaml_path, table_name, data), ...]
    """
    results = []

    # Find layer directory
    layer_dir = None
    for d in PATCH_DIR.iterdir():
        if not d.is_dir():
            continue
        name = d.name
        if name == f"dev-{layer_id}" or name == layer_id:
            layer_dir = d
            break
        if name.split("-", 1)[-1] == layer_id:
            layer_dir = d
            break

    if not layer_dir:
        print(f"Error: Layer '{layer_id}' not found in {PATCH_DIR}")
        return results

    # Scan database YAMLs
    db_dir = layer_dir / "database"
    if db_dir.exists():
        for yml in db_dir.rglob("*.yaml"):
            try:
                with open(yml, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if data and "records" in data:
                    table = (data.get("_meta") or {}).get("table_name", yml.stem)
                    results.append((str(yml), table, data))
            except Exception as e:
                print(f"  Warn: Could not load {yml}: {e}")

    # Scan client DBC YAMLs
    dbc_dir = layer_dir / "client" / "dbc"
    if dbc_dir.exists():
        for yml in dbc_dir.rglob("*.yaml"):
            try:
                with open(yml, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if data and "records" in data:
                    table = (data.get("_meta") or {}).get("dbc_name", yml.stem)
                    results.append((str(yml), table, data))
            except Exception as e:
                print(f"  Warn: Could not load {yml}: {e}")

    return results


def extract_ids_from_record(record: dict) -> set[int]:
    """Extract all numeric IDs from a record (PK and field values)."""
    ids = set()

    for key, value in record.items():
        # Skip non-ID fields
        if key in ("_meta",):
            continue

        # Extract from key if numeric
        if isinstance(key, int):
            ids.add(key)
        elif isinstance(key, str):
            # Handle pipe-delimited PKs
            for part in key.split("|"):
                try:
                    ids.add(int(part))
                except ValueError:
                    pass

        # Extract from value if numeric
        if isinstance(value, int):
            ids.add(value)
        elif isinstance(value, str):
            try:
                ids.add(int(value))
            except ValueError:
                pass
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, int):
                    ids.add(item)
                elif isinstance(item, str):
                    try:
                        ids.add(int(item))
                    except ValueError:
                        pass

    return ids


def cmd_analyze(args):
    """Analyze a layer for local ID conversion candidates."""
    layer_id = args.layer

    try:
        remapper = IDRemapper()
    except FileNotFoundError:
        print("Error: id-registry.yaml not found")
        return 1

    print(f"Analyzing layer: {layer_id}")
    print("=" * 60)

    # Get ranges for this layer
    layer_ranges = remapper.get_layer_ranges(layer_id)
    if not layer_ranges:
        print(f"Warning: No ID ranges registered for layer '{layer_id}'")

    yaml_files = scan_yaml_files(layer_id)
    if not yaml_files:
        print(f"No YAML files found for layer '{layer_id}'")
        return 1

    print(f"Found {len(yaml_files)} YAML files\n")

    conversion_candidates = []

    for yaml_path, table_name, data in yaml_files:
        uses_local_ids = (data.get("_meta") or {}).get("local_ids", False)

        if uses_local_ids:
            print(f"[LOCAL] {table_name} ({yaml_path})")
            print(f"        Already using local IDs")
            continue

        # Check if this table has a range
        canonical_table = remapper.resolve_entity_type(table_name)
        id_range = remapper.get_range(layer_id, canonical_table)

        if not id_range:
            print(f"[SKIP]  {table_name} ({yaml_path})")
            print(f"        No ID range registered")
            continue

        # Extract IDs from records
        records = data.get("records", {})
        all_ids = set()
        for pk_key, fields in records.items():
            record = {"pk": pk_key}
            if isinstance(fields, dict):
                record.update(fields)
            all_ids.update(extract_ids_from_record(record))

        # Filter to IDs within the range
        in_range_ids = [i for i in all_ids if id_range.base <= i <= id_range.end]

        if in_range_ids:
            print(f"[CAND]  {table_name} ({yaml_path})")
            print(f"        Range: {id_range.base}-{id_range.end}")
            print(f"        IDs in range: {sorted(in_range_ids)}")
            conversion_candidates.append((yaml_path, table_name, in_range_ids))
        else:
            print(f"[OK]    {table_name} ({yaml_path})")
            print(f"        No IDs in registered range")

    print("\n" + "=" * 60)
    print(f"Summary: {len(conversion_candidates)} files can be converted to local IDs")

    if conversion_candidates:
        print("\nTo convert:")
        for yaml_path, table_name, ids in conversion_candidates:
            print(f"  python pywowlib/tools/id_remapper.py migrate --layer {layer_id} --file {yaml_path}")

    return 0


def cmd_preview(args):
    """Preview remapping for a layer."""
    layer_id = args.layer

    try:
        remapper = IDRemapper()
    except FileNotFoundError:
        print("Error: id-registry.yaml not found")
        return 1

    print(f"Previewing remap for layer: {layer_id}")
    print("=" * 60)

    yaml_files = scan_yaml_files(layer_id)
    if not yaml_files:
        print(f"No YAML files found for layer '{layer_id}'")
        return 1

    for yaml_path, table_name, data in yaml_files:
        uses_local_ids = (data.get("_meta") or {}).get("local_ids", False)

        if not uses_local_ids:
            continue

        print(f"\n{table_name} ({yaml_path})")
        print("-" * 40)

        records = data.get("records", {})
        for pk_key, fields in records.items():
            if not isinstance(fields, dict):
                continue

            print(f"  Original PK: {pk_key}")
            try:
                remapped_record, remapped_pk = remapper.remap_record(
                    layer_id, table_name, fields, pk_key
                )
                print(f"  Remapped PK: {remapped_pk}")

                # Show changed fields
                for field_name, original_value in fields.items():
                    remapped_value = remapped_record.get(field_name)
                    if str(original_value) != str(remapped_value):
                        print(f"    {field_name}: {original_value} -> {remapped_value}")
            except ValueError as e:
                print(f"  ERROR: {e}")

    return 0


def cmd_migrate(args):
    """Migrate a layer or file to local ID format."""
    layer_id = args.layer
    dry_run = args.dry_run

    try:
        remapper = IDRemapper()
    except FileNotFoundError:
        print("Error: id-registry.yaml not found")
        return 1

    if dry_run:
        print(f"DRY RUN: Would migrate layer '{layer_id}'")

    yaml_files = scan_yaml_files(layer_id)
    if not yaml_files:
        print(f"No YAML files found for layer '{layer_id}'")
        return 1

    # Filter to specific file if provided
    if args.file:
        yaml_files = [(p, t, d) for p, t, d in yaml_files if p == args.file]
        if not yaml_files:
            print(f"File not found: {args.file}")
            return 1

    migrated_count = 0

    for yaml_path, table_name, data in yaml_files:
        uses_local_ids = (data.get("_meta") or {}).get("local_ids", False)

        if uses_local_ids:
            print(f"SKIP: {yaml_path} (already using local IDs)")
            continue

        # Get range for this table
        canonical_table = remapper.resolve_entity_type(table_name)
        id_range = remapper.get_range(layer_id, canonical_table)

        if not id_range:
            print(f"SKIP: {yaml_path} (no range for {table_name})")
            continue

        # Find IDs to convert
        records = data.get("records", {})
        new_records = {}
        conversions = []

        for pk_key, fields in records.items():
            if not isinstance(fields, dict):
                new_records[pk_key] = fields
                continue

            new_fields = {}
            new_pk = pk_key

            # Convert PK
            if isinstance(pk_key, int) and id_range.base <= pk_key <= id_range.end:
                local_id = pk_key - id_range.base + 1
                new_pk = f"@:{local_id}"
                conversions.append(f"PK: {pk_key} -> @:{local_id}")

            # Convert fields
            for field_name, value in fields.items():
                if isinstance(value, int) and id_range.base <= value <= id_range.end:
                    local_id = value - id_range.base + 1
                    new_fields[field_name] = f"@:{local_id}"
                    conversions.append(f"{field_name}: {value} -> @:{local_id}")
                else:
                    new_fields[field_name] = value

            new_records[new_pk] = new_fields

        if not conversions:
            continue

        print(f"\n{yaml_path}")
        print(f"  {len(conversions)} conversions:")
        for c in conversions[:10]:
            print(f"    {c}")
        if len(conversions) > 10:
            print(f"    ... and {len(conversions) - 10} more")

        if dry_run:
            continue

        # Update data
        data["records"] = new_records
        if "_meta" not in data:
            data["_meta"] = {}
        data["_meta"]["local_ids"] = True

        # Write back
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False, width=120)

        print(f"  MIGRATED: {yaml_path}")
        migrated_count += 1

    print(f"\nMigrated {migrated_count} files")
    return 0


def cmd_validate(args):
    """Validate local IDs in all layers."""
    try:
        remapper = IDRemapper()
    except FileNotFoundError:
        print("Error: id-registry.yaml not found")
        return 1

    print("Validating local IDs across all layers")
    print("=" * 60)

    errors = []

    for layer_id in remapper.list_layers():
        yaml_files = scan_yaml_files(layer_id)

        for yaml_path, table_name, data in yaml_files:
            uses_local_ids = (data.get("_meta") or {}).get("local_ids", False)

            if not uses_local_ids:
                continue

            records = data.get("records", {})
            for pk_key, fields in records.items():
                if not isinstance(fields, dict):
                    continue

                # Check PK
                if isinstance(pk_key, str) and pk_key.startswith("@:"):
                    match = LOCAL_ID_PATTERN.match(pk_key)
                    if match:
                        local_id = int(match.group(2))
                        is_valid, err = remapper.validate_local_id(
                            layer_id, table_name, local_id
                        )
                        if not is_valid:
                            errors.append(f"{yaml_path}: PK {pk_key} - {err}")

                # Check fields
                for field_name, value in fields.items():
                    if isinstance(value, str) and value.startswith("@"):
                        match = LOCAL_ID_PATTERN.match(value)
                        if match:
                            entity_type = match.group(1) or table_name
                            local_id = int(match.group(2))
                            is_valid, err = remapper.validate_local_id(
                                layer_id, entity_type, local_id
                            )
                            if not is_valid:
                                errors.append(
                                    f"{yaml_path}: {field_name}={value} - {err}"
                                )

    if errors:
        print(f"Found {len(errors)} validation errors:\n")
        for err in errors:
            print(f"  ERROR: {err}")
        return 1
    else:
        print("All local IDs are valid!")
        return 0


def cmd_ranges(args):
    """Show configured ID ranges."""
    try:
        remapper = IDRemapper()
    except FileNotFoundError:
        print("Error: id-registry.yaml not found")
        return 1

    layer_filter = args.layer

    print("ID Ranges")
    print("=" * 60)

    for layer_id in sorted(remapper.list_layers()):
        if layer_filter and layer_id != layer_filter:
            continue

        layer_ranges = remapper.get_layer_ranges(layer_id)
        if not layer_ranges:
            continue

        print(f"\n[{layer_id}]")
        for entity_type, ranges in sorted(layer_ranges.items()):
            for r in ranges:
                print(f"  {entity_type}: {r.base}-{r.end} ({r.count} IDs)")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="ID Remapper - Transform layer-local IDs to real IDs"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Find local ID conversion candidates")
    p_analyze.add_argument("--layer", required=True, help="Layer ID to analyze")
    p_analyze.set_defaults(func=cmd_analyze)

    # preview
    p_preview = subparsers.add_parser("preview", help="Preview remapping")
    p_preview.add_argument("--layer", required=True, help="Layer ID to preview")
    p_preview.set_defaults(func=cmd_preview)

    # migrate
    p_migrate = subparsers.add_parser("migrate", help="Convert to local ID format")
    p_migrate.add_argument("--layer", required=True, help="Layer ID to migrate")
    p_migrate.add_argument("--file", help="Specific file to migrate")
    p_migrate.add_argument("--dry-run", action="store_true", help="Preview without changes")
    p_migrate.set_defaults(func=cmd_migrate)

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate local IDs")
    p_validate.set_defaults(func=cmd_validate)

    # ranges
    p_ranges = subparsers.add_parser("ranges", help="Show configured ranges")
    p_ranges.add_argument("--layer", help="Filter to specific layer")
    p_ranges.set_defaults(func=cmd_ranges)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
