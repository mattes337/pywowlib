#!/usr/bin/env python3
"""ID Remapper CLI - Transform layer-local IDs to real IDs.

Usage:
    python id_remapper.py analyze --layer sensible-loot   # Find conversion candidates
    python id_remapper.py preview --layer sensible-loot   # Preview remapping
    python id_remapper.py migrate --layer sensible-loot   # Convert to local format
    python id_remapper.py manifest --layer sensible-loot  # Manifest slug-only IDs
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

from wdbx.id_remapper import IDRemapper, ENTITY_ALIASES, LOCAL_ID_PATTERN, TEXT_ID_PATTERN, Manifestation

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
                if isinstance(pk_key, str) and pk_key.startswith("@"):
                    parsed = remapper.parse_local_id(pk_key)
                    if parsed:
                        entity_type, numeric_id, slug = parsed
                        if numeric_id is not None:
                            entity_type = entity_type or table_name
                            is_valid, err = remapper.validate_local_id(
                                layer_id, entity_type, numeric_id
                            )
                            if not is_valid:
                                errors.append(f"{yaml_path}: PK {pk_key} - {err}")

                # Check fields
                for field_name, value in fields.items():
                    if isinstance(value, str) and value.startswith("@"):
                        parsed = remapper.parse_local_id(value)
                        if parsed:
                            entity_type, numeric_id, slug = parsed
                            if numeric_id is not None:
                                entity_type = entity_type or table_name
                                is_valid, err = remapper.validate_local_id(
                                    layer_id, entity_type, numeric_id
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


def cmd_manifest(args):
    """Manifest slug-only IDs in a layer."""
    layer_id = args.layer
    dry_run = args.dry_run

    try:
        remapper = IDRemapper()
    except FileNotFoundError:
        print("Error: id-registry.yaml not found")
        return 1

    yaml_files = scan_yaml_files(layer_id)
    if not yaml_files:
        print(f"No YAML files found for layer '{layer_id}'")
        return 1

    # Augment with layer_id for manifestation scanning
    yaml_files_with_layer = [(p, t, d, layer_id) for p, t, d in yaml_files]

    print(f"Scanning layer: {layer_id}")
    print("=" * 60)

    # Phase 1: Scan for already-manifested IDs
    remapper.scan_manifested_ids(yaml_files_with_layer)

    # Count manifested IDs found
    manifested_count = sum(len(ids) for ids in remapper._manifested_ids.values())
    print(f"Found {manifested_count} already-manifested IDs")

    # Phase 2: Process files to find slug-only references
    slug_refs = []  # [(yaml_path, field_path, original_str, entity_type, slug), ...]

    for yaml_path, table_name, data, _ in yaml_files_with_layer:
        uses_local_ids = (data.get("_meta") or {}).get("local_ids", False)
        if not uses_local_ids:
            continue

        records = data.get("records", {})
        for pk_key, fields in records.items():
            if not isinstance(fields, dict):
                continue

            # Check PK
            if isinstance(pk_key, str) and pk_key.startswith("@"):
                parsed = remapper.parse_local_id(pk_key)
                if parsed:
                    entity_type, numeric_id, slug = parsed
                    if numeric_id is None and slug is not None:
                        entity_type = entity_type or table_name
                        slug_refs.append((yaml_path, f"PK[{pk_key}]", pk_key, entity_type, slug))

            # Check fields
            for field_name, value in fields.items():
                def collect_slugs(val, path):
                    if isinstance(val, str) and val.startswith("@"):
                        parsed = remapper.parse_local_id(val)
                        if parsed:
                            entity_type, numeric_id, slug = parsed
                            if numeric_id is None and slug is not None:
                                entity_type = entity_type or table_name
                                slug_refs.append((yaml_path, path, val, entity_type, slug))
                    elif isinstance(val, dict):
                        for k, v in val.items():
                            collect_slugs(v, f"{path}.{k}")
                    elif isinstance(val, list):
                        for i, item in enumerate(val):
                            collect_slugs(item, f"{path}[{i}]")

                collect_slugs(value, field_name)

    if not slug_refs:
        print("No slug-only IDs found to manifest")
        return 0

    print(f"\nFound {len(slug_refs)} slug-only references to manifest:")
    for yaml_path, field_path, original, entity_type, slug in slug_refs:
        print(f"  {original} in {Path(yaml_path).name} ({field_path})")

    if dry_run:
        print("\nDRY RUN: Would manifest the above IDs")
        return 0

    # Phase 3: Assign IDs to slugs (sorted for deterministic assignment)
    print("\nAssigning IDs...")

    # Group slugs by entity type and sort
    slugs_by_entity: dict[str, set[str]] = {}
    for yaml_path, field_path, original, entity_type, slug in slug_refs:
        key = remapper._get_key(layer_id, entity_type)
        if key not in slugs_by_entity:
            slugs_by_entity[key] = set()
        slugs_by_entity[key].add(slug)

    # Assign IDs in sorted order
    slug_to_id: dict[str, dict[str, int]] = {}  # {layer_entity: {slug: real_id}}

    for key, slugs in sorted(slugs_by_entity.items()):
        slug_to_id[key] = {}
        for slug in sorted(slugs):
            # Check if already assigned
            if key in remapper._slug_to_id and slug in remapper._slug_to_id[key]:
                slug_to_id[key][slug] = remapper._slug_to_id[key][slug]
                print(f"  @{slug} -> {remapper._slug_to_id[key][slug]} (existing)")
            else:
                # Assign new ID
                entity_type = key.split("_", 1)[1] if "_" in key else key
                real_id = remapper._assign_next_id(layer_id, entity_type, slug)
                slug_to_id[key][slug] = real_id
                print(f"  @{slug} -> {real_id} (new)")

    # Phase 4: Create manifestations
    for yaml_path, field_path, original, entity_type, slug in slug_refs:
        key = remapper._get_key(layer_id, entity_type)
        real_id = slug_to_id[key][slug]
        # Build manifested string: @entity:id:slug or @:id:slug
        # Preserve the original entity prefix style
        if original.startswith("@:"):
            manifested = f"@:{real_id}:{slug}"
        else:
            manifested = f"@{entity_type}:{real_id}:{slug}"
        remapper._manifestations.append(Manifestation(
            yaml_path=yaml_path,
            field_path=field_path,
            original=original,
            manifested=manifested
        ))

    # Phase 5: Write manifestations to source files
    files_changed = remapper.write_manifestations()

    print(f"\nManifested IDs in {files_changed} file(s)")
    return 0


def cmd_list_manifestations(args):
    """List all manifested IDs for a layer."""
    layer_id = args.layer

    try:
        remapper = IDRemapper()
    except FileNotFoundError:
        print("Error: id-registry.yaml not found")
        return 1

    yaml_files = scan_yaml_files(layer_id)
    if not yaml_files:
        print(f"No YAML files found for layer '{layer_id}'")
        return 1

    # Augment with layer_id for manifestation scanning
    yaml_files_with_layer = [(p, t, d, layer_id) for p, t, d in yaml_files]

    # Scan for already-manifested IDs
    remapper.scan_manifested_ids(yaml_files_with_layer)

    print(f"Manifested IDs for layer: {layer_id}")
    print("=" * 60)

    if not remapper._manifested_ids:
        print("No manifested IDs found")
        return 0

    for key, ids in sorted(remapper._manifested_ids.items()):
        print(f"\n{key}:")
        for real_id, slug in sorted(ids.items()):
            if slug:
                print(f"  {real_id}: {slug}")
            else:
                print(f"  {real_id}: (no slug)")

    return 0


def cmd_remap_text(args):
    """Remap @entity:N patterns in text files (Lua, conf, etc.)."""
    layer_id = args.layer
    quiet = args.quiet

    try:
        remapper = IDRemapper()
    except FileNotFoundError:
        print("Error: id-registry.yaml not found", file=sys.stderr)
        return 1

    if args.src_dir and args.dst_dir:
        # Batch mode: process all files in directory
        src = Path(args.src_dir)
        dst = Path(args.dst_dir)

        if not src.exists():
            print(f"Error: source directory not found: {src}", file=sys.stderr)
            return 1

        count = 0
        remapped_count = 0
        for f in sorted(src.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(src)
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)

            try:
                text = f.read_text(encoding="utf-8")
                result = remapper.remap_text(layer_id, text)
                out.write_text(result, encoding="utf-8")
                if result != text:
                    remapped_count += 1
                count += 1
            except UnicodeDecodeError:
                # Binary file — copy as-is
                import shutil
                shutil.copy2(f, out)
                count += 1

        if not quiet:
            print(
                f"Processed {count} file(s) ({remapped_count} remapped) "
                f"from {src} → {dst}",
                file=sys.stderr,
            )

    elif args.file:
        # Single file mode
        text = Path(args.file).read_text(encoding="utf-8")
        result = remapper.remap_text(layer_id, text)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(result, encoding="utf-8")
        else:
            sys.stdout.write(result)
        if not quiet and result != text:
            print(f"Remapped IDs in {args.file}", file=sys.stderr)

    else:
        # stdin/stdout mode
        text = sys.stdin.read()
        result = remapper.remap_text(layer_id, text)
        # Force UTF-8 for stdout on Windows (cp1252 default can't handle all chars)
        sys.stdout.buffer.write(result.encode("utf-8"))

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

    # manifest
    p_manifest = subparsers.add_parser("manifest", help="Manifest slug-only IDs to explicit IDs")
    p_manifest.add_argument("--layer", required=True, help="Layer ID to manifest")
    p_manifest.add_argument("--dry-run", action="store_true", help="Preview without changes")
    p_manifest.set_defaults(func=cmd_manifest)

    # list
    p_list = subparsers.add_parser("list", help="List manifested IDs for a layer")
    p_list.add_argument("--layer", required=True, help="Layer ID to list")
    p_list.set_defaults(func=cmd_list_manifestations)

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate local IDs")
    p_validate.set_defaults(func=cmd_validate)

    # remap-text
    p_remap = subparsers.add_parser(
        "remap-text",
        help="Remap @entity:N patterns in text files (Lua, conf, etc.)"
    )
    p_remap.add_argument("--layer", required=True, help="Layer ID for ID resolution")
    p_remap.add_argument("--file", help="Single input file")
    p_remap.add_argument("--output", help="Output file (default: stdout)")
    p_remap.add_argument("--src-dir", help="Source directory for batch mode")
    p_remap.add_argument("--dst-dir", help="Destination directory for batch mode")
    p_remap.add_argument("--quiet", action="store_true", help="Suppress progress output")
    p_remap.set_defaults(func=cmd_remap_text)

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
