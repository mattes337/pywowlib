#!/usr/bin/env python
"""
DBC query tool — SQLite-backed search, lookup, and patch management for WoW DBC data.

Imports extracted YAML files into a fast SQLite cache, provides query/search,
and supports writing patch YAML files for the overlay build system.

Usage:
  python dbc_query.py build [--patches <dir>]
  python dbc_query.py tables
  python dbc_query.py schema <table>
  python dbc_query.py lookup <table> <id>
  python dbc_query.py search <table> <term> [--limit N]
  python dbc_query.py list <table> [--limit N] [--where "field=value"]
  python dbc_query.py modify <table> <id> field=value [...]
  python dbc_query.py add <table> field=value [...]
  python dbc_query.py remove <table> <id>
  python dbc_query.py merge [--output <dir>]
  python dbc_query.py export <table> [--format yaml|dbc] [-o path]
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from wdbx.dbc_db import DBCDB, ORIGINAL_DBC_DIR, PATCH_DBC_DIR, MERGED_DBC_DIR, DB_PATH


def _parse_field_value(s: str):
    """Parse a 'field=value' string into (field, typed_value)."""
    if "=" not in s:
        raise ValueError("Expected field=value, got: {}".format(s))
    field, raw = s.split("=", 1)
    # Try to parse as number
    try:
        return field, int(raw)
    except ValueError:
        pass
    try:
        return field, float(raw)
    except ValueError:
        pass
    # Try JSON (for arrays)
    if raw.startswith("[") or raw.startswith("{"):
        try:
            return field, json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return field, raw


def _compact_json(record: dict) -> str:
    """Format a record as compact single-line JSON."""
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


# ===================================================================
# Subcommand handlers
# ===================================================================

def cmd_build(args, db: DBCDB):
    original_dir = args.original or ORIGINAL_DBC_DIR
    print("Building SQLite from: {}".format(original_dir))
    print("Database: {}".format(db.db_path))
    print()

    results = db.import_directory(original_dir)

    if args.patches:
        patch_dir = args.patches
        print()
        print("Applying patches from: {}".format(patch_dir))
        db.apply_patches(patch_dir)

    total_records = sum(results.values())
    print()
    print("{} tables, {} total records".format(len(results), total_records))


def cmd_tables(args, db: DBCDB):
    tables = db.tables()
    if not tables:
        print("No tables. Run 'build' first.")
        return

    # Group by category
    by_cat: dict[str, list] = {}
    for t in tables:
        by_cat.setdefault(t["category"], []).append(t)

    for cat in sorted(by_cat):
        for t in sorted(by_cat[cat], key=lambda x: x["name"]):
            print(_compact_json(t))


def cmd_schema(args, db: DBCDB):
    schema = db.schema(args.table)
    if not schema:
        print("Table '{}' not found".format(args.table))
        return
    for col in schema:
        print(_compact_json(col))


def cmd_lookup(args, db: DBCDB):
    record = db.lookup(args.table, args.id)
    if record is None:
        print("Record {} not found in {}".format(args.id, args.table))
        return
    print(_compact_json(record))


def cmd_search(args, db: DBCDB):
    results = db.search(args.table, args.term, limit=args.limit)
    if not results:
        print("No results for '{}' in {}".format(args.term, args.table))
        return
    for r in results:
        print(_compact_json(r))


def cmd_list(args, db: DBCDB):
    where = None
    if args.where:
        where = {}
        for w in args.where:
            field, value = _parse_field_value(w)
            where[field] = value

    results = db.list_records(args.table, limit=args.limit, where=where)
    if not results:
        print("No records in {}".format(args.table))
        return
    for r in results:
        print(_compact_json(r))


def cmd_modify(args, db: DBCDB):
    patch_dir = args.patches or PATCH_DBC_DIR
    fields = {}
    for fv in args.fields:
        field, value = _parse_field_value(fv)
        fields[field] = value

    locale = getattr(args, "locale", None)
    db.write_patch(patch_dir, args.table, "modify", args.id, fields,
                   locale=locale)
    print("Wrote patch: {} record {} -> {}".format(
        args.table, args.id,
        os.path.join(patch_dir, "*", args.table + ".yaml")))


def cmd_add(args, db: DBCDB):
    patch_dir = args.patches or PATCH_DBC_DIR
    fields = {}
    record_id = None
    for fv in args.fields:
        field, value = _parse_field_value(fv)
        fields[field] = value
        if field == "ID" or field == fields.get("_pk_field", "ID"):
            record_id = int(value)

    if record_id is None:
        # Try to find the ID field
        if "ID" in fields:
            record_id = int(fields["ID"])
        else:
            print("ERROR: New record must include an ID field")
            sys.exit(1)

    locale = getattr(args, "locale", None)
    db.write_patch(patch_dir, args.table, "add", record_id, fields,
                   locale=locale)
    print("Wrote patch: {} new record {} -> {}".format(
        args.table, record_id,
        os.path.join(patch_dir, "*", args.table + ".yaml")))


def cmd_remove(args, db: DBCDB):
    patch_dir = args.patches or PATCH_DBC_DIR
    db.write_patch(patch_dir, args.table, "remove", args.id)
    print("Wrote patch: {} delete record {} -> {}".format(
        args.table, args.id,
        os.path.join(patch_dir, "*", args.table + ".yaml")))


def cmd_merge(args, db: DBCDB):
    original_dir = args.original or ORIGINAL_DBC_DIR
    output_dir = args.output or MERGED_DBC_DIR

    # Support multi-layer: --patch-dirs dir1 dir2 dir3
    # Falls back to single --patches for backward compat
    patch_dirs = args.patch_dirs if args.patch_dirs else \
        [args.patches or PATCH_DBC_DIR]

    # Filter to existing directories
    patch_dirs = [d for d in patch_dirs if os.path.isdir(d)]
    if not patch_dirs:
        print("No patch directories found")
        return

    print("Merging DBC YAML:")
    print("  Original: {}".format(original_dir))
    for i, d in enumerate(patch_dirs):
        print("  Patches{}: {}".format(
            " [{}]".format(i + 1) if len(patch_dirs) > 1 else "", d))
    print("  Output:   {}".format(output_dir))
    print()

    patched_only = getattr(args, 'patched_only', False)
    results = db.merge_directory(original_dir, patch_dirs, output_dir,
                                 patched_only=patched_only)

    merged = sum(1 for v in results.values() if v == "merged")
    copied = sum(1 for v in results.values() if v == "copied")
    new = sum(1 for v in results.values() if v == "new")
    print()
    print("{} merged, {} copied, {} new".format(merged, copied, new))


def cmd_merge_to_dbc(args, db: DBCDB):
    """Merge DBC YAML patches and convert directly to binary DBC files.

    Single-pass: parse original + patch → merge in memory → DBC binary.
    No intermediate YAML written, avoiding the double-parse bottleneck.
    """
    original_dir = args.original or ORIGINAL_DBC_DIR
    output_dir = args.output

    if not output_dir:
        print("Error: --output is required for merge-to-dbc")
        sys.exit(1)

    patch_dirs = args.patch_dirs if args.patch_dirs else \
        [args.patches or PATCH_DBC_DIR]
    patch_dirs = [d for d in patch_dirs if os.path.isdir(d)]
    if not patch_dirs:
        print("No patch directories found")
        return

    # Import yaml_to_dbc (accepts dict or path)
    scripts_dir = os.path.join(
        os.path.dirname(PROJECT_ROOT), "scripts", "pack")
    sys.path.insert(0, scripts_dir)
    from yaml_to_dbc import yaml_to_dbc

    # Collect original and patch files
    orig_files = {}
    for root, _dirs, files in os.walk(os.path.normpath(original_dir)):
        for fname in files:
            if fname.endswith(".yaml"):
                dbc_name = os.path.splitext(fname)[0]
                orig_files[dbc_name] = os.path.join(root, fname)

    patch_files = {}
    for pdir in patch_dirs:
        pdir = os.path.normpath(pdir)
        for root, _dirs, files in os.walk(pdir):
            for fname in files:
                if fname.endswith(".yaml"):
                    dbc_name = os.path.splitext(fname)[0]
                    patch_files.setdefault(dbc_name, []).append(
                        os.path.join(root, fname))

    # Collect pre-built .dbc files from sibling dbc_binary/ directories
    # (produced by pack-mpq.py). These avoid loading huge originals like
    # Spell.yaml (163 MB, 70K records) into memory.
    prebuilt_dbc = {}
    for pdir in patch_dirs:
        binary_dir = os.path.join(os.path.dirname(pdir), "dbc_binary")
        if os.path.isdir(binary_dir):
            for fname in os.listdir(binary_dir):
                if fname.endswith(".dbc"):
                    dbc_name = os.path.splitext(fname)[0]
                    prebuilt_dbc[dbc_name] = os.path.join(binary_dir, fname)

    os.makedirs(output_dir, exist_ok=True)
    count = 0

    for dbc_name in sorted(set(patch_files.keys())):
        patches = patch_files[dbc_name]

        # Check for pre-built binary DBC that's newer than all YAML sources.
        if dbc_name in prebuilt_dbc:
            prebuilt_path = prebuilt_dbc[dbc_name]
            prebuilt_mtime = os.path.getmtime(prebuilt_path)
            sources = list(patches)
            if dbc_name in orig_files:
                sources.append(orig_files[dbc_name])
            if all(os.path.getmtime(s) <= prebuilt_mtime for s in sources):
                import shutil
                out_path = os.path.join(output_dir, dbc_name + ".dbc")
                shutil.copy2(prebuilt_path, out_path)
                sz = os.path.getsize(out_path)
                count += 1
                print("  {} -> {} ({} bytes, pre-built)".format(
                    dbc_name, out_path, sz))
                continue

        if dbc_name in orig_files:
            # Merge original + patches in memory
            merged = db.merge_yaml_data(orig_files[dbc_name], patches[0])
            for extra in patches[1:]:
                # Apply additional patches directly in memory (no temp file)
                import yaml as _yaml
                _loader = getattr(_yaml, "CSafeLoader", _yaml.SafeLoader)
                with open(extra, "r", encoding="utf-8") as f:
                    patch = _yaml.load(f, Loader=_loader)
                if patch:
                    records = merged.get("records", {})
                    for rec_id, fields in patch.get("records", {}).items():
                        if isinstance(fields, dict):
                            if rec_id in records:
                                records[rec_id].update(fields)
                            else:
                                records[rec_id] = fields
                    for del_id in patch.get("_deleted", []):
                        records.pop(del_id, None)
                    merged["records"] = records
        else:
            # Patch-only (new table) — load directly
            import yaml as _yaml
            _loader = getattr(_yaml, "CSafeLoader", _yaml.SafeLoader)
            with open(patches[0], "r", encoding="utf-8") as f:
                merged = _yaml.load(f, Loader=_loader)

        # Convert merged dict directly to DBC binary
        dbc_bytes = yaml_to_dbc(merged)
        out_path = os.path.join(output_dir, dbc_name + ".dbc")
        with open(out_path, "wb") as f:
            f.write(dbc_bytes)
        count += 1
        print("  {} -> {} ({} bytes)".format(dbc_name, out_path, len(dbc_bytes)))

    print("\n{} DBC file(s) built".format(count))


def cmd_export(args, db: DBCDB):
    fmt = args.format or "yaml"

    if fmt == "yaml":
        output = args.output or "{}.yaml".format(args.table)
        count = db.export_yaml(args.table, output)
        print("Exported {} records to {}".format(count, output))

    elif fmt == "dbc":
        # Export via YAML -> yaml_to_dbc pipeline
        import tempfile
        tmp_yaml = tempfile.mktemp(suffix=".yaml")
        try:
            db.export_yaml(args.table, tmp_yaml)

            # Import yaml_to_dbc from scripts/pack
            scripts_dir = os.path.join(
                os.path.dirname(PROJECT_ROOT), "scripts", "pack")
            sys.path.insert(0, scripts_dir)
            from yaml_to_dbc import yaml_to_dbc

            dbc_bytes = yaml_to_dbc(tmp_yaml)
            output = args.output or "{}.dbc".format(args.table)
            with open(output, "wb") as f:
                f.write(dbc_bytes)
            print("Exported {} to binary DBC: {}".format(args.table, output))
        finally:
            if os.path.exists(tmp_yaml):
                os.unlink(tmp_yaml)

    else:
        print("Unknown format: {}".format(fmt))
        sys.exit(1)


# ===================================================================
# CLI
# ===================================================================

def main():
    # Global flags shared by all subcommands
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument("--db", default=None,
                               help="SQLite database path (default: pywowlib/dbc.db)")
    global_parser.add_argument("--original", default=None,
                               help="Original DBC YAML directory")
    global_parser.add_argument("--patches", default=None,
                               help="Patch DBC YAML directory")

    parser = argparse.ArgumentParser(
        description="DBC query tool — SQLite-backed search and patch management",
        parents=[global_parser])
    subparsers = parser.add_subparsers(dest="command")

    # -- build --
    p_build = subparsers.add_parser("build", parents=[global_parser],
        help="Build SQLite from YAML files")

    # -- tables --
    p_tables = subparsers.add_parser("tables", parents=[global_parser],
        help="List tables with record counts")

    # -- schema --
    p_schema = subparsers.add_parser("schema", parents=[global_parser],
        help="Show columns and types for a table")
    p_schema.add_argument("table", help="Table name")

    # -- lookup --
    p_lookup = subparsers.add_parser("lookup", parents=[global_parser],
        help="Look up a single record by ID")
    p_lookup.add_argument("table", help="Table name")
    p_lookup.add_argument("id", type=int, help="Record ID")

    # -- search --
    p_search = subparsers.add_parser("search", parents=[global_parser],
        help="FTS search on string columns")
    p_search.add_argument("table", help="Table name")
    p_search.add_argument("term", help="Search term")
    p_search.add_argument("--limit", type=int, default=20,
                          help="Max results (default: 20)")

    # -- list --
    p_list = subparsers.add_parser("list", parents=[global_parser],
        help="List records with optional filters")
    p_list.add_argument("table", help="Table name")
    p_list.add_argument("--limit", type=int, default=50,
                        help="Max records (default: 50)")
    p_list.add_argument("--where", nargs="*",
                        help="Field filters: field=value [...]")

    # -- modify --
    p_modify = subparsers.add_parser("modify", parents=[global_parser],
        help="Write field changes to patch YAML")
    p_modify.add_argument("table", help="Table name")
    p_modify.add_argument("id", type=int, help="Record ID")
    p_modify.add_argument("--locale", default=None,
                          help="Locale code (e.g. deDE) — appends _{locale} to _lang fields")
    p_modify.add_argument("fields", nargs="+",
                          help="field=value pairs")

    # -- add --
    p_add = subparsers.add_parser("add", parents=[global_parser],
        help="Add new record to patch YAML")
    p_add.add_argument("table", help="Table name")
    p_add.add_argument("--locale", default=None,
                       help="Locale code (e.g. deDE) — appends _{locale} to _lang fields")
    p_add.add_argument("fields", nargs="+",
                       help="field=value pairs (must include ID=N)")

    # -- remove --
    p_remove = subparsers.add_parser("remove", parents=[global_parser],
        help="Mark record for deletion in patch YAML")
    p_remove.add_argument("table", help="Table name")
    p_remove.add_argument("id", type=int, help="Record ID")

    # -- merge --
    p_merge = subparsers.add_parser("merge", parents=[global_parser],
        help="Merge .original/ + .patch/ YAML files")
    p_merge.add_argument("--patch-dirs", nargs="+", default=None,
                         help="Patch directories in layer order (for layered merge)")
    p_merge.add_argument("--output", default=None,
                         help="Output directory (default: .merged/client/dbc)")
    p_merge.add_argument("--patched-only", action="store_true", default=False,
                         help="Only output files that have patches (skip copying unmodified originals)")

    # -- merge-to-dbc --
    p_m2d = subparsers.add_parser("merge-to-dbc", parents=[global_parser],
        help="Merge patches and convert directly to binary DBC (single pass)")
    p_m2d.add_argument("--patch-dirs", nargs="+", default=None,
                        help="Patch directories in layer order")
    p_m2d.add_argument("--output", required=True,
                        help="Output directory for .dbc files")

    # -- export --
    p_export = subparsers.add_parser("export", parents=[global_parser],
        help="Export table to YAML or binary DBC")
    p_export.add_argument("table", help="Table name")
    p_export.add_argument("--format", choices=["yaml", "dbc"],
                          default="yaml", help="Output format (default: yaml)")
    p_export.add_argument("-o", "--output", default=None,
                          help="Output file path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    db_path = args.db or DB_PATH
    db = DBCDB(db_path)

    try:
        commands = {
            "build": cmd_build,
            "tables": cmd_tables,
            "schema": cmd_schema,
            "lookup": cmd_lookup,
            "search": cmd_search,
            "list": cmd_list,
            "modify": cmd_modify,
            "add": cmd_add,
            "remove": cmd_remove,
            "merge": cmd_merge,
            "merge-to-dbc": cmd_merge_to_dbc,
            "export": cmd_export,
        }
        commands[args.command](args, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
