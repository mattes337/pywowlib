#!/usr/bin/env python3
"""ID Registry validation and collision detection for WoW custom content.

Usage:
    python id_registry.py validate                    # Check all layers for collisions
    python id_registry.py check <table> <id>          # Check if ID is available
    python id_registry.py ranges                      # Show registered ranges
    python id_registry.py scan                        # Scan layers for actual ID usage
"""

import argparse
import sys
import yaml
from pathlib import Path
from collections import defaultdict
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
REGISTRY_PATH = PROJECT_ROOT / ".patch" / "id-registry.yaml"


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {"id_ranges": {}, "reserved_ranges": {}}
    with open(REGISTRY_PATH) as f:
        return yaml.safe_load(f) or {"id_ranges": {}, "reserved_ranges": {}}


def parse_range(range_str: str) -> tuple[int, int]:
    if "-" in str(range_str):
        parts = str(range_str).split("-")
        return int(parts[0]), int(parts[1])
    return int(range_str), int(range_str)


def ranges_overlap(r1: tuple[int, int], r2: tuple[int, int]) -> bool:
    return not (r1[1] < r2[0] or r2[1] < r1[0])


def get_registered_ranges(registry: dict, table: str) -> list[tuple[str, int, int]]:
    ranges = []
    for entry in registry.get("id_ranges", {}).get(table, []):
        mn, mx = parse_range(entry["range"])
        ranges.append((entry["layer"], mn, mx))
    return ranges


def get_reserved_ranges(registry: dict, table: str) -> list[tuple[int, int]]:
    ranges = []
    for r in registry.get("reserved_ranges", {}).get(table, []):
        ranges.append(parse_range(r))
    return ranges


def scan_layer_ids() -> dict[str, dict[str, list[tuple[str, int, int]]]]:
    result = defaultdict(lambda: defaultdict(list))
    patch_dir = PROJECT_ROOT / ".patch"

    for layer_dir in patch_dir.iterdir():
        if not layer_dir.is_dir() or layer_dir.name.startswith("."):
            continue
        layer_name = layer_dir.name

        dbc_dir = layer_dir / "client" / "dbc"
        if dbc_dir.exists():
            for yml in dbc_dir.rglob("*.yaml"):
                try:
                    with open(yml) as f:
                        data = yaml.safe_load(f)
                    if data and "records" in data:
                        table = data.get("_meta", {}).get("dbc_name", yml.stem)
                        ids = [
                            int(r)
                            for r in data["records"].keys()
                            if str(r).isdigit() or (isinstance(r, int))
                        ]
                        if ids:
                            result[layer_name][table].append(
                                (min(ids), max(ids), len(ids))
                            )
                except:
                    pass

        db_dir = layer_dir / "database"
        if db_dir.exists():
            for yml in db_dir.rglob("*.yaml"):
                try:
                    with open(yml) as f:
                        data = yaml.safe_load(f)
                    if data and "records" in data:
                        table = data.get("_meta", {}).get("table_name", yml.stem)
                        ids = []
                        for r in data["records"].keys():
                            if isinstance(r, int):
                                ids.append(r)
                            elif isinstance(r, str) and r.split("|")[0].isdigit():
                                ids.append(int(r.split("|")[0]))
                        if ids:
                            result[layer_name][table].append(
                                (min(ids), max(ids), len(ids))
                            )
                except:
                    pass

    return result


def validate_registry(registry: dict) -> list[dict]:
    errors = []
    shared = set(registry.get("shared_tables", []))

    for table, entries in registry.get("id_ranges", {}).items():
        if table in shared:
            continue
        ranges = [(e["layer"], *parse_range(e["range"])) for e in entries]

        for i, (layer1, mn1, mx1) in enumerate(ranges):
            for layer2, mn2, mx2 in ranges[i + 1 :]:
                if ranges_overlap((mn1, mx1), (mn2, mx2)):
                    errors.append(
                        {
                            "type": "registry_collision",
                            "table": table,
                            "layer1": layer1,
                            "range1": f"{mn1}-{mx1}",
                            "layer2": layer2,
                            "range2": f"{mn2}-{mx2}",
                        }
                    )

    actual = scan_layer_ids()
    for layer, tables in actual.items():
        for table, usage_list in tables.items():
            for mn, mx, count in usage_list:
                registered = get_registered_ranges(registry, table)
                # Collect all registered ranges for this layer+table
                layer_ranges = []
                for reg_layer, reg_mn, reg_mx in registered:
                    layer_matches = (
                        layer == reg_layer
                        or layer == f"dev-{reg_layer}"
                        or layer.replace("dev-", "") == reg_layer
                    )
                    if layer_matches:
                        layer_ranges.append((reg_mn, reg_mx))
                # Check if scanned range fits in a single registered range
                in_registry = any(
                    mn >= r[0] and mx <= r[1] for r in layer_ranges
                )
                # If not, check if both endpoints fall within registered ranges
                # (gaps between ranges are expected — other layers own those IDs)
                if not in_registry and layer_ranges:
                    in_registry = all(
                        any(r[0] <= i <= r[1] for r in layer_ranges)
                        for i in (mn, mx)
                    )
                if not in_registry:
                    errors.append(
                        {
                            "type": "unregistered_usage",
                            "table": table,
                            "layer": layer,
                            "range": f"{mn}-{mx}",
                            "records": count,
                        }
                    )

    return errors


def check_id(registry: dict, table: str, id_val: int) -> dict:
    result = {"id": id_val, "table": table, "status": "available", "conflicts": []}

    for mn, mx in get_reserved_ranges(registry, table):
        if mn <= id_val <= mx:
            result["status"] = "reserved"
            result["conflicts"].append(f"reserved range {mn}-{mx}")

    for layer, mn, mx in get_registered_ranges(registry, table):
        if mn <= id_val <= mx:
            result["status"] = "registered"
            result["conflicts"].append(f"layer '{layer}' ({mn}-{mx})")

    return result


def cmd_validate(args):
    registry = load_registry()
    errors = validate_registry(registry)

    if not errors:
        print("[OK] No collisions or unregistered IDs found")
        return 0

    for err in errors:
        if err["type"] == "registry_collision":
            print(
                f"[X] COLLISION: {err['table']}: {err['layer1']} ({err['range1']}) overlaps {err['layer2']} ({err['range2']})"
            )
        else:
            print(
                f"[!] UNREGISTERED: {err['table']}: {err['layer']} uses {err['range']} ({err['records']} records) - not in registry"
            )

    return 1


def cmd_check(args):
    registry = load_registry()
    result = check_id(registry, args.table, args.id)

    if result["status"] == "available":
        print(f"[OK] ID {args.id} in {args.table} is available")
    else:
        print(f"[X] ID {args.id} in {args.table} is {result['status']}")
        for c in result["conflicts"]:
            print(f"  - {c}")

    return 0 if result["status"] == "available" else 1


def cmd_ranges(args):
    registry = load_registry()

    for table, entries in registry.get("id_ranges", {}).items():
        print(f"\n[{table}]")
        for e in sorted(entries, key=lambda x: parse_range(x["range"])[0]):
            print(f"  {e['layer']:25} {e['range']:15} {e.get('description', '')}")

    if registry.get("reserved_ranges"):
        print("\n[reserved]")
        for table, ranges in registry["reserved_ranges"].items():
            print(f"  {table}: {', '.join(str(r) for r in ranges)}")

    return 0


def cmd_scan(args):
    actual = scan_layer_ids()

    for layer in sorted(actual.keys()):
        print(f"\n[{layer}]")
        for table, usage_list in sorted(actual[layer].items()):
            for mn, mx, count in usage_list:
                print(f"  {table:30} {mn}-{mx} ({count} records)")

    return 0


def main():
    parser = argparse.ArgumentParser(description="ID Registry validation tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate", help="Check for collisions and unregistered IDs")

    check_p = sub.add_parser("check", help="Check if an ID is available")
    check_p.add_argument("table", help="Table name (e.g., Spell, creature_template)")
    check_p.add_argument("id", type=int, help="ID to check")

    sub.add_parser("ranges", help="Show registered ranges")
    sub.add_parser("scan", help="Scan layers for actual ID usage")

    args = parser.parse_args()

    cmds = {
        "validate": cmd_validate,
        "check": cmd_check,
        "ranges": cmd_ranges,
        "scan": cmd_scan,
    }
    sys.exit(cmds[args.cmd](args))


if __name__ == "__main__":
    main()
