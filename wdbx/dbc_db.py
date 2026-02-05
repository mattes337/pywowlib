"""SQLite-backed DBC database with FTS5 search, patch writing, and YAML merge.

Imports extracted YAML files (from extract-dbc.py) into a fast SQLite cache.
Supports query, search, patch overlay writes, and YAML merge for the build pipeline.

Schema per DBC table:
  - Column per YAML field (INTEGER / REAL / TEXT)
  - Array fields stored as JSON text
  - Locstring fields stored as TEXT (enUS string)
  - First column = PRIMARY KEY (record ID)
  - FTS5 virtual table on TEXT columns for search
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_WDBX_DIR = os.path.dirname(os.path.abspath(__file__))
_PYWOWLIB_ROOT = os.path.dirname(_WDBX_DIR)
_PROJECT_ROOT = os.path.dirname(_PYWOWLIB_ROOT)

DB_PATH = os.environ.get(
    "DBC_DB_PATH",
    os.path.join(_PYWOWLIB_ROOT, "dbc.db"),
)

ORIGINAL_DBC_DIR = os.path.join(_PROJECT_ROOT, ".original", "client", "dbc")
PATCH_DBC_DIR = os.path.join(_PROJECT_ROOT, ".patch", "client", "dbc")
MERGED_DBC_DIR = os.path.join(_PROJECT_ROOT, ".merged", "client", "dbc")

# ---------------------------------------------------------------------------
# DBC category mapping (mirrors extract-dbc.py)
# ---------------------------------------------------------------------------
_DBC_CATEGORIES = {
    "spells": [
        "Spell", "SpellAuraOptions", "SpellAuraRestrictions",
        "SpellCastTimes", "SpellCastingRequirements", "SpellCategories",
        "SpellCategory", "SpellClassOptions", "SpellCooldowns",
        "SpellDescriptionVariables", "SpellDifficulty", "SpellDispelType",
        "SpellDuration", "SpellEffectCameraShakes", "SpellEquippedItems",
        "SpellFocusObject", "SpellIcon", "SpellInterrupts", "SpellItemEnchantment",
        "SpellItemEnchantmentCondition", "SpellLevels", "SpellMechanic",
        "SpellMissile", "SpellMissileMotion", "SpellPower", "SpellRadius",
        "SpellRange", "SpellReagents", "SpellRuneCost", "SpellScaling",
        "SpellShapeshift", "SpellShapeshiftForm", "SpellTargetRestrictions",
        "SpellTotems", "SpellVisual", "SpellVisualEffectName",
        "SpellVisualKit", "SpellVisualKitAreaModel",
        "SpellVisualKitModelAttach", "SpellVisualPrecastTransitions",
        "Totem", "TotemCategory",
    ],
    "items": [
        "Item", "ItemBagFamily", "ItemClass", "ItemCondExtCosts",
        "ItemDisplayInfo", "ItemExtendedCost", "ItemGroupSounds",
        "ItemLimitCategory", "ItemPetFood", "ItemPurchaseGroup",
        "ItemRandomProperties", "ItemRandomSuffix", "ItemSet",
        "ItemSubClass", "ItemSubClassMask", "ItemVisualEffects",
        "ItemVisuals", "GemProperties",
    ],
    "creatures": [
        "CreatureDisplayInfo", "CreatureDisplayInfoExtra", "CreatureFamily",
        "CreatureModelData", "CreatureMovementInfo", "CreatureSoundData",
        "CreatureSpellData", "CreatureType",
    ],
    "maps": [
        "Map", "AreaTable", "AreaGroup", "AreaAssignment", "AreaPOI",
        "AreaTrigger", "WorldMapArea", "WorldMapContinent",
        "WorldMapOverlay", "WorldMapTransforms", "WorldSafeLocs",
        "DungeonMap", "DungeonMapChunk", "WMOAreaTable",
    ],
    "characters": [
        "ChrClasses", "ChrRaces", "CharBaseInfo", "CharHairGeosets",
        "CharHairTextures", "CharSections", "CharStartOutfit",
        "CharTitles", "CharVariations",
    ],
    "quests": [
        "QuestFactionReward", "QuestInfo", "QuestSort", "QuestXP",
    ],
    "achievements": [
        "Achievement", "Achievement_Category", "Achievement_Criteria",
        "GtOCTHpPerStamina", "GtRegenHPPerSpt", "GtRegenMPPerSpt",
    ],
    "skills": [
        "Talent", "TalentTab", "SkillLine", "SkillLineAbility",
        "SkillLineCategory", "SkillRaceClassInfo", "SkillTiers",
        "GlyphProperties", "GlyphSlot",
    ],
    "audio": [
        "SoundEntries", "SoundAmbience", "SoundEmitters", "SoundFilter",
        "SoundFilterElem", "SoundProviderPreferences", "SoundWaterType",
        "ZoneMusic", "ZoneIntroMusicTable",
    ],
    "vehicles": [
        "Vehicle", "VehicleSeat", "VehicleUIIndicator", "VehicleUIIndSeat",
    ],
    "factions": [
        "Faction", "FactionGroup", "FactionTemplate",
    ],
    "transport": [
        "TaxiNodes", "TaxiPath", "TaxiPathNode",
        "TransportAnimation", "TransportPhysics", "TransportRotation",
    ],
    "ui": [
        "GameTips", "LoadingScreens", "LoadingScreenTaxiSplines",
        "WorldStateUI", "WorldStateZoneSounds",
        "ScreenEffect", "ScreenLocation",
    ],
    "visuals": [
        "Light", "LightFloatBand", "LightIntBand", "LightParams",
        "LightSkybox", "CameraShakes", "AnimationData",
        "AttackAnimKits", "AttackAnimTypes", "CinematicCamera",
        "CinematicSequences", "GroundEffectDoodad", "GroundEffectTexture",
        "OverrideSpellData", "ParticleColor",
        "Weather", "DestructibleModelData",
    ],
}

_DBC_TO_CATEGORY: dict[str, str] = {}
for _cat, _names in _DBC_CATEGORIES.items():
    for _name in _names:
        _DBC_TO_CATEGORY[_name] = _cat


def _get_category(dbc_name: str) -> str:
    return _DBC_TO_CATEGORY.get(dbc_name, "misc")


# ---------------------------------------------------------------------------
# Schema resolution helpers
# ---------------------------------------------------------------------------
def _try_resolve_schema(dbc_name: str, build: str = "3.3.5.12340"):
    """Try to resolve DBD schema, return None on failure."""
    try:
        sys.path.insert(0, _PYWOWLIB_ROOT)
        from tools.dbc_converter import _resolve_schema
        return _resolve_schema(dbc_name, build)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Type inference from YAML values
# ---------------------------------------------------------------------------
def _infer_field_types(records: dict) -> dict[str, str]:
    """Infer SQLite column types from sample record values.

    Returns {field_name: 'INTEGER' | 'REAL' | 'TEXT'}.
    """
    types: dict[str, str] = {}
    for rec in records.values():
        if not isinstance(rec, dict):
            continue
        for key, val in rec.items():
            if key in types:
                continue
            if isinstance(val, bool):
                types[key] = "INTEGER"
            elif isinstance(val, int):
                types[key] = "INTEGER"
            elif isinstance(val, float):
                types[key] = "REAL"
            elif isinstance(val, list):
                types[key] = "TEXT"  # JSON array
            elif isinstance(val, dict):
                types[key] = "TEXT"  # locstring dict
            else:
                types[key] = "TEXT"
        if types:
            break  # first record is enough for type inference
    return types


def _infer_types_from_schema(dbc_name: str, build: str = "3.3.5.12340") -> dict[str, str] | None:
    """Infer SQLite column types from DBD schema definitions."""
    schema = _try_resolve_schema(dbc_name, build)
    if schema is None:
        return None
    types = {}
    for field in schema:
        ftype = field["type"]
        if ftype in ("float",):
            types[field["name"]] = "REAL"
        elif ftype in ("string", "locstring"):
            types[field["name"]] = "TEXT"
        elif field["count"] > 1:
            types[field["name"]] = "TEXT"  # array → JSON
        else:
            types[field["name"]] = "INTEGER"
    return types


# ---------------------------------------------------------------------------
# SQLite identifier quoting
# ---------------------------------------------------------------------------
_SAFE_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _quote(name: str) -> str:
    """Quote a SQLite identifier."""
    return '"{}"'.format(name.replace('"', '""'))


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------
class DBCDB:
    """SQLite-backed DBC database with FTS5 search."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")  # 64MB
            self._init_meta_table()
        return self._conn

    def _init_meta_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS _dbc_meta (
                table_name TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                schema_json TEXT,
                field_types_json TEXT
            )
        """)
        self.conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Build — import YAML files into SQLite
    # ------------------------------------------------------------------
    def import_yaml(self, yaml_path: str) -> int:
        """Parse one YAML file and import into a SQLite table.

        Returns the number of records imported.
        """
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "_meta" not in data:
            return 0

        meta = data["_meta"]
        dbc_name = meta["dbc_name"]
        records = data.get("records", {})
        if not records:
            return 0

        category = _get_category(dbc_name)
        table_name = dbc_name

        # Determine field types — prefer DBD schema, fall back to value inspection
        field_types = _infer_types_from_schema(dbc_name, meta.get("build", "3.3.5.12340"))
        if field_types is None:
            field_types = _infer_field_types(records)

        # Ensure we have types for all fields that appear in records
        sample_rec = next(iter(records.values()))
        if isinstance(sample_rec, dict):
            for key in sample_rec:
                if key not in field_types:
                    val = sample_rec[key]
                    if isinstance(val, int):
                        field_types[key] = "INTEGER"
                    elif isinstance(val, float):
                        field_types[key] = "REAL"
                    else:
                        field_types[key] = "TEXT"

        if not field_types:
            return 0

        # Determine PK — first field in field_types (usually "ID")
        field_names = list(field_types.keys())
        pk_field = field_names[0]

        # Drop existing table + FTS
        self.conn.execute("DROP TABLE IF EXISTS {}".format(_quote(table_name + "_fts")))
        self.conn.execute("DROP TABLE IF EXISTS {}".format(_quote(table_name)))

        # Create main table
        col_defs = []
        for fname in field_names:
            ftype = field_types[fname]
            if fname == pk_field:
                col_defs.append("{} {} PRIMARY KEY".format(_quote(fname), ftype))
            else:
                col_defs.append("{} {}".format(_quote(fname), ftype))

        create_sql = "CREATE TABLE {} ({})".format(
            _quote(table_name), ", ".join(col_defs))
        self.conn.execute(create_sql)

        # Identify TEXT columns for FTS (exclude JSON arrays)
        text_cols = [fn for fn in field_names if field_types[fn] == "TEXT"]

        # Create FTS5 if we have text columns
        if text_cols:
            fts_cols = ", ".join(_quote(c) for c in text_cols)
            fts_name = table_name + "_fts"
            self.conn.execute(
                "CREATE VIRTUAL TABLE {} USING fts5({}, content={}, content_rowid={})".format(
                    _quote(fts_name), fts_cols,
                    _quote(table_name), _quote(pk_field)))

            # Sync triggers — keep FTS in sync with main table
            main_tbl = _quote(table_name)
            fts_tbl = _quote(fts_name)
            pk_col = _quote(pk_field)
            new_vals = ", ".join("new." + _quote(c) for c in text_cols)
            old_vals = ", ".join("old." + _quote(c) for c in text_cols)

            self.conn.execute(
                "CREATE TRIGGER {} AFTER INSERT ON {} BEGIN"
                " INSERT INTO {}(rowid, {}) VALUES (new.{}, {});"
                " END".format(
                    _quote(table_name + "_ai"), main_tbl,
                    fts_tbl, fts_cols, pk_col, new_vals))

            self.conn.execute(
                "CREATE TRIGGER {} AFTER DELETE ON {} BEGIN"
                " INSERT INTO {}({}, rowid, {}) VALUES ('delete', old.{}, {});"
                " END".format(
                    _quote(table_name + "_ad"), main_tbl,
                    fts_tbl, fts_tbl, fts_cols, pk_col, old_vals))

            self.conn.execute(
                "CREATE TRIGGER {} AFTER UPDATE ON {} BEGIN"
                " INSERT INTO {}({}, rowid, {}) VALUES ('delete', old.{}, {});"
                " INSERT INTO {}(rowid, {}) VALUES (new.{}, {});"
                " END".format(
                    _quote(table_name + "_au"), main_tbl,
                    fts_tbl, fts_tbl, fts_cols, pk_col, old_vals,
                    fts_tbl, fts_cols, pk_col, new_vals))

        # Insert records
        placeholders = ", ".join("?" for _ in field_names)
        insert_sql = "INSERT OR REPLACE INTO {} ({}) VALUES ({})".format(
            _quote(table_name),
            ", ".join(_quote(fn) for fn in field_names),
            placeholders)

        batch = []
        for rec_id, rec in records.items():
            if not isinstance(rec, dict):
                continue
            row = []
            for fname in field_names:
                val = rec.get(fname)
                if val is None:
                    # For PK field, use the record key from YAML
                    if fname == pk_field:
                        val = rec_id
                    row.append(val)
                elif isinstance(val, (list, dict)):
                    row.append(json.dumps(val, ensure_ascii=False))
                else:
                    row.append(val)
            batch.append(tuple(row))

            if len(batch) >= 5000:
                self.conn.executemany(insert_sql, batch)
                batch.clear()

        if batch:
            self.conn.executemany(insert_sql, batch)

        # Store metadata
        self.conn.execute("""
            INSERT OR REPLACE INTO _dbc_meta (table_name, category, schema_json, field_types_json)
            VALUES (?, ?, ?, ?)
        """, (table_name, category,
              json.dumps(meta, ensure_ascii=False),
              json.dumps(field_types, ensure_ascii=False)))

        self.conn.commit()
        return len(records)

    def import_directory(self, yaml_dir: str) -> dict:
        """Batch import all YAML files from a categorised directory.

        Returns {table_name: record_count, ...}.
        """
        results = {}
        yaml_dir = os.path.normpath(yaml_dir)

        for root, _dirs, files in os.walk(yaml_dir):
            for fname in sorted(files):
                if not fname.endswith(".yaml"):
                    continue
                yaml_path = os.path.join(root, fname)
                try:
                    count = self.import_yaml(yaml_path)
                    table_name = os.path.splitext(fname)[0]
                    results[table_name] = count
                    print("  {:40s} {:>6} records".format(table_name, count))
                except Exception as e:
                    print("  FAIL {:40s} -- {}".format(fname, e))
        return results

    def apply_patches(self, patch_dir: str) -> dict:
        """Overlay .patch/ YAML changes onto the SQLite database.

        Patch YAML format:
          records:
            123: {field: value, ...}   # modify existing or add new
          _deleted:
            - 456                       # remove record

        Returns {table_name: {modified, added, deleted}, ...}.
        """
        results = {}
        patch_dir = os.path.normpath(patch_dir)

        for root, _dirs, files in os.walk(patch_dir):
            for fname in sorted(files):
                if not fname.endswith(".yaml"):
                    continue
                yaml_path = os.path.join(root, fname)
                try:
                    with open(yaml_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)

                    if not data:
                        continue

                    meta = data.get("_meta", {})
                    dbc_name = meta.get("dbc_name", os.path.splitext(fname)[0])
                    table_name = dbc_name

                    # Check table exists
                    row = self.conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table_name,)).fetchone()
                    if not row:
                        print("  SKIP {:40s} -- table not found".format(fname))
                        continue

                    # Get field info
                    meta_row = self.conn.execute(
                        "SELECT field_types_json FROM _dbc_meta WHERE table_name=?",
                        (table_name,)).fetchone()
                    if not meta_row:
                        continue
                    field_types = json.loads(meta_row["field_types_json"])
                    field_names = list(field_types.keys())
                    pk_field = field_names[0]

                    stats = {"modified": 0, "added": 0, "deleted": 0}

                    # Apply record modifications/additions
                    patch_records = data.get("records", {})
                    for rec_id, fields in patch_records.items():
                        if not isinstance(fields, dict):
                            continue
                        rec_id_val = int(rec_id) if isinstance(rec_id, str) and rec_id.isdigit() else rec_id

                        # Check if record exists
                        existing = self.conn.execute(
                            "SELECT * FROM {} WHERE {} = ?".format(
                                _quote(table_name), _quote(pk_field)),
                            (rec_id_val,)).fetchone()

                        if existing:
                            # Update only specified fields
                            set_clauses = []
                            values = []
                            for fk, fv in fields.items():
                                if fk == pk_field:
                                    continue
                                if fk not in field_types:
                                    continue
                                if isinstance(fv, (list, dict)):
                                    fv = json.dumps(fv, ensure_ascii=False)
                                set_clauses.append("{} = ?".format(_quote(fk)))
                                values.append(fv)
                            if set_clauses:
                                values.append(rec_id_val)
                                self.conn.execute(
                                    "UPDATE {} SET {} WHERE {} = ?".format(
                                        _quote(table_name),
                                        ", ".join(set_clauses),
                                        _quote(pk_field)),
                                    values)
                                stats["modified"] += 1
                        else:
                            # Insert new record
                            fields[pk_field] = rec_id_val
                            cols = []
                            vals = []
                            for fk, fv in fields.items():
                                if fk not in field_types:
                                    continue
                                if isinstance(fv, (list, dict)):
                                    fv = json.dumps(fv, ensure_ascii=False)
                                cols.append(_quote(fk))
                                vals.append(fv)
                            if cols:
                                self.conn.execute(
                                    "INSERT OR REPLACE INTO {} ({}) VALUES ({})".format(
                                        _quote(table_name),
                                        ", ".join(cols),
                                        ", ".join("?" for _ in cols)),
                                    vals)
                                stats["added"] += 1

                    # Apply deletions
                    deleted_ids = data.get("_deleted", [])
                    for del_id in deleted_ids:
                        self.conn.execute(
                            "DELETE FROM {} WHERE {} = ?".format(
                                _quote(table_name), _quote(pk_field)),
                            (del_id,))
                        stats["deleted"] += 1

                    self.conn.commit()
                    results[table_name] = stats
                    total = stats["modified"] + stats["added"] + stats["deleted"]
                    if total > 0:
                        print("  {:40s} +{} ~{} -{} records".format(
                            table_name, stats["added"], stats["modified"], stats["deleted"]))

                except Exception as e:
                    print("  FAIL {:40s} -- {}".format(fname, e))

        return results

    # ------------------------------------------------------------------
    # Query (read)
    # ------------------------------------------------------------------
    def tables(self) -> list[dict]:
        """List all DBC tables with record counts and categories."""
        rows = self.conn.execute("""
            SELECT m.table_name, m.category,
                   (SELECT COUNT(*) FROM sqlite_master sm
                    WHERE sm.type='table' AND sm.name=m.table_name) as exists_flag
            FROM _dbc_meta m
            ORDER BY m.category, m.table_name
        """).fetchall()

        result = []
        for row in rows:
            table_name = row["table_name"]
            # Get actual record count
            try:
                count_row = self.conn.execute(
                    "SELECT COUNT(*) as cnt FROM {}".format(_quote(table_name))).fetchone()
                count = count_row["cnt"] if count_row else 0
            except sqlite3.OperationalError:
                count = 0
            result.append({
                "name": table_name,
                "category": row["category"],
                "records": count,
            })
        return result

    def schema(self, table: str) -> list[dict]:
        """Show columns and types for a table."""
        rows = self.conn.execute(
            "PRAGMA table_info({})".format(_quote(table))).fetchall()
        return [{"name": r["name"], "type": r["type"],
                 "pk": bool(r["pk"])} for r in rows]

    def lookup(self, table: str, record_id: int) -> dict | None:
        """Single record by primary key."""
        schema_info = self.schema(table)
        if not schema_info:
            return None
        pk_field = next((s["name"] for s in schema_info if s["pk"]), schema_info[0]["name"])
        row = self.conn.execute(
            "SELECT * FROM {} WHERE {} = ?".format(
                _quote(table), _quote(pk_field)),
            (record_id,)).fetchone()
        return dict(row) if row else None

    def search(self, table: str, term: str, limit: int = 20) -> list[dict]:
        """FTS5 search on string columns, falls back to prefix then LIKE."""
        term = term.strip()
        if not term:
            return []

        fts_table = table + "_fts"
        # Check FTS table exists
        exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (fts_table,)).fetchone()

        if exists:
            # Try exact FTS match
            sql = """
                SELECT t.* FROM {fts} fts
                JOIN {tbl} t ON t.rowid = fts.rowid
                WHERE {fts} MATCH ?
                ORDER BY fts.rank
                LIMIT ?
            """.format(fts=_quote(fts_table), tbl=_quote(table))

            try:
                rows = self.conn.execute(sql, (term, limit)).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass

            # Try prefix search
            prefix_q = " ".join('"{}"*'.format(t) for t in term.split() if t)
            try:
                rows = self.conn.execute(sql, (prefix_q, limit)).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass

        # Fall back to LIKE on all TEXT columns
        meta_row = self.conn.execute(
            "SELECT field_types_json FROM _dbc_meta WHERE table_name=?",
            (table,)).fetchone()
        if not meta_row:
            return []

        field_types = json.loads(meta_row["field_types_json"])
        text_cols = [fn for fn, ft in field_types.items() if ft == "TEXT"]
        if not text_cols:
            return []

        like_pat = "%{}%".format(term)
        where = " OR ".join("{} LIKE ?".format(_quote(c)) for c in text_cols)
        params = [like_pat] * len(text_cols) + [limit]
        rows = self.conn.execute(
            "SELECT * FROM {} WHERE ({}) LIMIT ?".format(
                _quote(table), where),
            params).fetchall()
        return [dict(r) for r in rows]

    def list_records(self, table: str, limit: int = 50,
                     where: dict[str, Any] | None = None) -> list[dict]:
        """List records with optional field filters."""
        sql = "SELECT * FROM {}".format(_quote(table))
        params: list = []

        if where:
            clauses = []
            for field, value in where.items():
                clauses.append("{} = ?".format(_quote(field)))
                params.append(value)
            sql += " WHERE " + " AND ".join(clauses)

        sql += " LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Modify — write to .patch/ YAML
    # ------------------------------------------------------------------
    def write_patch(self, patch_dir: str, table: str, action: str,
                    record_id: int, fields: dict | None = None):
        """Write a modification to the patch YAML file.

        Args:
            patch_dir: Base patch directory (e.g. .patch/client/dbc)
            table: DBC table name (e.g. "Spell")
            action: "modify", "add", or "remove"
            record_id: Record ID
            fields: Field values (required for modify/add)
        """
        category = _get_category(table)
        patch_file = os.path.join(patch_dir, category, table + ".yaml")

        # Load existing patch file or create new
        if os.path.isfile(patch_file):
            with open(patch_file, "r", encoding="utf-8") as f:
                patch_data = yaml.safe_load(f) or {}
        else:
            patch_data = {}

        if "_meta" not in patch_data:
            patch_data["_meta"] = {"dbc_name": table}
        if "records" not in patch_data:
            patch_data["records"] = {}
        if "_deleted" not in patch_data:
            patch_data["_deleted"] = []

        if action == "modify" or action == "add":
            if fields is None:
                raise ValueError("fields required for {} action".format(action))
            existing = patch_data["records"].get(record_id, {})
            existing.update(fields)
            if action == "add":
                existing.setdefault("ID", record_id)
            patch_data["records"][record_id] = existing

        elif action == "remove":
            if record_id not in patch_data["_deleted"]:
                patch_data["_deleted"].append(record_id)
            # Remove from records if it was added/modified in this patch
            patch_data["records"].pop(record_id, None)

        # Clean up empty sections
        if not patch_data["_deleted"]:
            del patch_data["_deleted"]

        # Write patch file
        os.makedirs(os.path.dirname(patch_file), exist_ok=True)
        with open(patch_file, "w", encoding="utf-8") as f:
            yaml.dump(patch_data, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False, width=120)

    # ------------------------------------------------------------------
    # Merge — combine original + patch YAML files
    # ------------------------------------------------------------------
    def merge_yaml(self, original_path: str, patch_path: str,
                   output_path: str):
        """Merge an original YAML file with a patch YAML file.

        1. Load original (full records dict)
        2. Load patch (partial records + _deleted)
        3. For each record in patch: original[id].update(patch_fields)
        4. For each ID in _deleted: del original[id]
        5. Write merged YAML
        """
        with open(original_path, "r", encoding="utf-8") as f:
            original = yaml.safe_load(f)

        with open(patch_path, "r", encoding="utf-8") as f:
            patch = yaml.safe_load(f)

        if not original or not patch:
            # Nothing to merge — just copy original
            if original:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as f:
                    yaml.dump(original, f, default_flow_style=False,
                              allow_unicode=True, sort_keys=False, width=120)
            return

        records = original.get("records", {})

        # Apply modifications and additions
        for rec_id, patch_fields in patch.get("records", {}).items():
            if not isinstance(patch_fields, dict):
                continue
            if rec_id in records:
                records[rec_id].update(patch_fields)
            else:
                records[rec_id] = patch_fields

        # Apply deletions
        for del_id in patch.get("_deleted", []):
            records.pop(del_id, None)

        original["records"] = records
        # Update record count in meta
        if "_meta" in original:
            original["_meta"]["record_count"] = len(records)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(original, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False, width=120)

    def merge_directory(self, original_dir: str, patch_dir: str,
                        output_dir: str) -> dict:
        """Merge all YAML files from original + patch directories.

        For YAML files that exist in both original and patch: merge them.
        For YAML files only in original: copy to output.
        For YAML files only in patch (new tables): copy to output.

        Returns {table_name: action, ...}.
        """
        original_dir = os.path.normpath(original_dir)
        patch_dir = os.path.normpath(patch_dir)
        output_dir = os.path.normpath(output_dir)

        # Collect all original YAML files
        orig_files: dict[str, str] = {}  # dbc_name -> full path
        for root, _dirs, files in os.walk(original_dir):
            for fname in files:
                if fname.endswith(".yaml"):
                    dbc_name = os.path.splitext(fname)[0]
                    orig_files[dbc_name] = os.path.join(root, fname)

        # Collect all patch YAML files
        patch_files: dict[str, str] = {}  # dbc_name -> full path
        for root, _dirs, files in os.walk(patch_dir):
            for fname in files:
                if fname.endswith(".yaml"):
                    dbc_name = os.path.splitext(fname)[0]
                    patch_files[dbc_name] = os.path.join(root, fname)

        results = {}

        # Process all original files
        for dbc_name, orig_path in sorted(orig_files.items()):
            category = _get_category(dbc_name)
            out_path = os.path.join(output_dir, category, dbc_name + ".yaml")

            if dbc_name in patch_files:
                # Merge original + patch
                self.merge_yaml(orig_path, patch_files[dbc_name], out_path)
                results[dbc_name] = "merged"
                print("  MERGE {:40s}".format(dbc_name))
            else:
                # Copy original as-is
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                import shutil
                shutil.copy2(orig_path, out_path)
                results[dbc_name] = "copied"

        # Process patch-only files (new tables)
        for dbc_name, patch_path in sorted(patch_files.items()):
            if dbc_name in orig_files:
                continue  # already handled above
            category = _get_category(dbc_name)
            out_path = os.path.join(output_dir, category, dbc_name + ".yaml")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            import shutil
            shutil.copy2(patch_path, out_path)
            results[dbc_name] = "new"
            print("  NEW   {:40s}".format(dbc_name))

        return results

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_yaml(self, table: str, output_path: str):
        """Export a SQLite table back to YAML format."""
        # Get metadata
        meta_row = self.conn.execute(
            "SELECT * FROM _dbc_meta WHERE table_name=?",
            (table,)).fetchone()
        if not meta_row:
            raise ValueError("Table '{}' not found in metadata".format(table))

        meta = json.loads(meta_row["schema_json"])
        field_types = json.loads(meta_row["field_types_json"])

        # Fetch all records
        rows = self.conn.execute(
            "SELECT * FROM {} ORDER BY rowid".format(_quote(table))).fetchall()

        # Convert to YAML format
        field_names = list(field_types.keys())
        pk_field = field_names[0]
        records = {}
        for row in rows:
            rec = {}
            for fname in field_names:
                val = row[fname]
                if val is not None and field_types[fname] == "TEXT":
                    # Try to decode JSON arrays/dicts
                    if isinstance(val, str) and val.startswith(("[", "{")):
                        try:
                            val = json.loads(val)
                        except (json.JSONDecodeError, ValueError):
                            pass
                rec[fname] = val
            rec_id = row[pk_field]
            records[rec_id] = rec

        yaml_data = {
            "_meta": meta,
            "records": records,
        }
        yaml_data["_meta"]["record_count"] = len(records)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False, width=120)

        return len(records)
