#!/usr/bin/env python
"""
World database query tool — SQLite-backed search, lookup, and patch management
for the AzerothCore acore_world database.

Imports SQL dump files into a fast SQLite cache, provides query/search,
and supports writing patch YAML files that convert to SQL for the overlay pipeline.

Usage:
  python world_query.py build [--from-sql | --from-mysql]
  python world_query.py tables [--category CAT]
  python world_query.py schema <table>
  python world_query.py lookup <table> <pk> [<pk2> ...]
  python world_query.py search <table> <term> [--limit N]
  python world_query.py list <table> [--limit N] [--where field=value ...]
  python world_query.py modify <table> <pk> [<pk2> ...] [--] field=value [...]
  python world_query.py add <table> field=value [...]
  python world_query.py remove <table> <pk> [<pk2> ...]
  python world_query.py generate-sql [--patches DIR] [--output DIR]
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from wdbx.world_db import WorldDB, DB_PATH, SQL_DIR, PATCH_DB_DIR, MERGED_DB_DIR


def _parse_field_value(s: str):
    """Parse a 'field=value' string into (field, typed_value)."""
    if "=" not in s:
        raise ValueError("Expected field=value, got: {}".format(s))
    field, raw = s.split("=", 1)
    try:
        return field, int(raw)
    except ValueError:
        pass
    try:
        return field, float(raw)
    except ValueError:
        pass
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

def cmd_build(args, db: WorldDB):
    if args.from_mysql:
        print("Building SQLite from live MySQL...")
        print("Database: {}".format(db.db_path))
        print()
        results = db.build_from_mysql(
            host=args.mysql_host, port=args.mysql_port,
            user=args.mysql_user, password=args.mysql_password)
    else:
        sql_dir = args.sql_dir or SQL_DIR
        print("Building SQLite from SQL dumps: {}".format(sql_dir))
        print("Database: {}".format(db.db_path))
        print()
        results = db.build_from_sql(sql_dir)

    total = sum(results.values())
    print()
    print("{} tables, {} total records".format(len(results), total))


def cmd_tables(args, db: WorldDB):
    tables = db.tables(category=args.category)
    if not tables:
        print("No tables. Run 'build' first.")
        return

    by_cat: dict[str, list] = {}
    for t in tables:
        by_cat.setdefault(t["category"], []).append(t)

    for cat in sorted(by_cat):
        for t in sorted(by_cat[cat], key=lambda x: x["name"]):
            print(_compact_json(t))


def cmd_schema(args, db: WorldDB):
    schema = db.schema(args.table)
    if not schema:
        print("Table '{}' not found".format(args.table))
        return
    for col in schema:
        print(_compact_json(col))


def cmd_lookup(args, db: WorldDB):
    # Parse PK values with type inference
    pk_values = _parse_pk_args(args.pk_values)

    record = db.lookup(args.table, *pk_values)
    if record is None:
        print("Record not found in {}".format(args.table))
        return
    print(_compact_json(record))


def cmd_search(args, db: WorldDB):
    results = db.search(args.table, args.term, limit=args.limit)
    if not results:
        print("No results for '{}' in {}".format(args.term, args.table))
        return
    for r in results:
        print(_compact_json(r))


def cmd_list(args, db: WorldDB):
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


def cmd_modify(args, db: WorldDB):
    patch_dir = args.patches or PATCH_DB_DIR

    # Split args into PK values and field=value pairs
    # Use -- as separator, or infer from schema
    pk_values, fields = _split_modify_args(args, db)

    db.write_patch(args.table, "modify", pk_values, fields,
                   patch_dir=patch_dir)
    pk_str = "|".join(str(v) for v in pk_values)
    print("Wrote patch: {} record {} -> {}".format(
        args.table, pk_str,
        os.path.join(patch_dir, "*", args.table + ".yaml")))


def cmd_add(args, db: WorldDB):
    patch_dir = args.patches or PATCH_DB_DIR
    fields = {}
    for fv in args.fields:
        field, value = _parse_field_value(fv)
        fields[field] = value

    # Get PK columns to extract PK values from fields
    meta = db._get_meta(args.table)
    if meta:
        pk_cols = json.loads(meta["pk_columns"])
    else:
        pk_cols = ["entry"]

    pk_values = []
    for pc in pk_cols:
        if pc in fields:
            pk_values.append(fields[pc])
        else:
            print("ERROR: New record must include PK field '{}'".format(pc))
            sys.exit(1)

    db.write_patch(args.table, "add", pk_values, fields,
                   patch_dir=patch_dir)
    pk_str = "|".join(str(v) for v in pk_values)
    print("Wrote patch: {} new record {} -> {}".format(
        args.table, pk_str,
        os.path.join(patch_dir, "*", args.table + ".yaml")))


def cmd_remove(args, db: WorldDB):
    patch_dir = args.patches or PATCH_DB_DIR
    pk_values = _parse_pk_args(args.pk_values)

    db.write_patch(args.table, "remove", pk_values,
                   patch_dir=patch_dir)
    pk_str = "|".join(str(v) for v in pk_values)
    print("Wrote patch: {} delete record {} -> {}".format(
        args.table, pk_str,
        os.path.join(patch_dir, "*", args.table + ".yaml")))


def cmd_generate_sql(args, db: WorldDB):
    output_dir = args.output or MERGED_DB_DIR

    # Support multi-layer: --patch-dirs dir1 dir2 dir3
    # Falls back to single --patches for backward compat
    patch_dirs = args.patch_dirs if args.patch_dirs else \
        [args.patches or PATCH_DB_DIR]

    # Filter to existing directories
    patch_dirs = [d for d in patch_dirs if os.path.isdir(d)]
    if not patch_dirs:
        print("No patch directories found")
        return

    print("Generating SQL from YAML patches:")
    for i, d in enumerate(patch_dirs):
        print("  Patches{}: {}".format(
            " [{}]".format(i + 1) if len(patch_dirs) > 1 else "", d))
    print("  Output:  {}".format(output_dir))
    print()

    generated = db.patches_to_sql(patch_dirs=patch_dirs, output_dir=output_dir)
    print()
    print("{} SQL file(s) generated".format(len(generated)))


# ===================================================================
# Arg parsing helpers
# ===================================================================

def _parse_pk_args(pk_strs: list[str]) -> list:
    """Parse PK value strings into typed values."""
    result = []
    for s in pk_strs:
        try:
            result.append(int(s))
        except ValueError:
            try:
                result.append(float(s))
            except ValueError:
                result.append(s)
    return result


def _split_modify_args(args, db: WorldDB) -> tuple[list, dict]:
    """Split modify command args into PK values and field=value pairs.

    Uses -- separator if present, otherwise infers PK count from schema.
    """
    all_args = args.args_and_fields

    # Check for -- separator
    if "--" in all_args:
        sep_idx = all_args.index("--")
        pk_strs = all_args[:sep_idx]
        field_strs = all_args[sep_idx + 1:]
    else:
        # Infer PK count from schema
        meta = db._get_meta(args.table)
        if meta:
            pk_cols = json.loads(meta["pk_columns"])
            pk_count = len(pk_cols)
        else:
            pk_count = 1

        pk_strs = all_args[:pk_count]
        field_strs = all_args[pk_count:]

    pk_values = _parse_pk_args(pk_strs)
    fields = {}
    for fv in field_strs:
        field, value = _parse_field_value(fv)
        fields[field] = value

    if not pk_values:
        print("ERROR: No PK values provided")
        sys.exit(1)
    if not fields:
        print("ERROR: No field=value pairs provided")
        sys.exit(1)

    return pk_values, fields


# ===================================================================
# CLI
# ===================================================================

def main():
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument("--db", default=None,
                               help="SQLite database path")
    global_parser.add_argument("--patches", default=None,
                               help="Patch YAML directory")

    parser = argparse.ArgumentParser(
        description="World database query tool — SQLite-backed search and patch management",
        parents=[global_parser])
    subparsers = parser.add_subparsers(dest="command")

    # -- build --
    p_build = subparsers.add_parser("build", parents=[global_parser],
        help="Build SQLite from SQL dumps or live MySQL")
    p_build.add_argument("--from-sql", action="store_true", default=True,
                         help="Build from SQL dump files (default)")
    p_build.add_argument("--from-mysql", action="store_true",
                         help="Build from live MySQL connection")
    p_build.add_argument("--sql-dir", default=None,
                         help="SQL dump directory")
    p_build.add_argument("--mysql-host", default="127.0.0.1")
    p_build.add_argument("--mysql-port", type=int, default=3306)
    p_build.add_argument("--mysql-user", default="acore")
    p_build.add_argument("--mysql-password", default="acore")

    # -- tables --
    p_tables = subparsers.add_parser("tables", parents=[global_parser],
        help="List tables with record counts")
    p_tables.add_argument("--category", default=None,
                          help="Filter by category")

    # -- schema --
    p_schema = subparsers.add_parser("schema", parents=[global_parser],
        help="Show columns and types for a table")
    p_schema.add_argument("table", help="Table name")

    # -- lookup --
    p_lookup = subparsers.add_parser("lookup", parents=[global_parser],
        help="Look up a single record by primary key")
    p_lookup.add_argument("table", help="Table name")
    p_lookup.add_argument("pk_values", nargs="+", help="Primary key value(s)")

    # -- search --
    p_search = subparsers.add_parser("search", parents=[global_parser],
        help="FTS search on text columns")
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
    p_modify.add_argument("args_and_fields", nargs="+",
                          help="<pk> [<pk2> ...] [--] field=value [...]")

    # -- add --
    p_add = subparsers.add_parser("add", parents=[global_parser],
        help="Add new record to patch YAML")
    p_add.add_argument("table", help="Table name")
    p_add.add_argument("fields", nargs="+",
                       help="field=value pairs (must include PK fields)")

    # -- remove --
    p_remove = subparsers.add_parser("remove", parents=[global_parser],
        help="Mark record for deletion in patch YAML")
    p_remove.add_argument("table", help="Table name")
    p_remove.add_argument("pk_values", nargs="+", help="Primary key value(s)")

    # -- generate-sql --
    p_gensql = subparsers.add_parser("generate-sql", parents=[global_parser],
        help="Convert YAML patches to MySQL SQL files")
    p_gensql.add_argument("--patch-dirs", nargs="+", default=None,
                          help="Patch directories in layer order (for layered merge)")
    p_gensql.add_argument("--output", default=None,
                          help="Output directory")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    db_path = args.db or DB_PATH
    db = WorldDB(db_path)

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
            "generate-sql": cmd_generate_sql,
        }
        commands[args.command](args, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
