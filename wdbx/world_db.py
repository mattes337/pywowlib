"""SQLite-backed AzerothCore world database with FTS5 search and YAML patch support.

Mirrors the DBC pattern (dbc_db.py) for the acore_world MySQL database.
Provides local querying without a running MySQL instance, and YAML patches
that convert to SQL for the production pipeline.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml

from .id_remapper import IDRemapper
from .sql_parser import parse_create_table, parse_insert_rows, TableSchema

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_WDBX_DIR = os.path.dirname(os.path.abspath(__file__))
_PYWOWLIB_ROOT = os.path.dirname(_WDBX_DIR)
_PROJECT_ROOT = os.path.dirname(_PYWOWLIB_ROOT)

DB_PATH = os.environ.get(
    "WORLD_DB_PATH",
    os.path.join(_PROJECT_ROOT, ".original", "database", "world.db"),
)

SQL_DIR = os.path.join(
    _PROJECT_ROOT, ".original", "server", "data", "sql", "base", "db_world",
)

PATCH_DB_DIR = os.path.join(_PROJECT_ROOT, ".patch", "dev", "database")
MERGED_DB_DIR = os.path.join(_PROJECT_ROOT, ".merged", "database")

# ---------------------------------------------------------------------------
# Category mapping for world tables
# ---------------------------------------------------------------------------
_WORLD_CATEGORIES: dict[str, list[str]] = {
    "creatures": [
        "creature", "creature_addon", "creature_classlevelstats",
        "creature_default_trainer", "creature_equip_template",
        "creature_formations", "creature_loot_template",
        "creature_model_info", "creature_movement_override",
        "creature_onkill_reputation", "creature_questender",
        "creature_questitem", "creature_queststarter", "creature_sparring",
        "creature_summon_groups", "creature_template",
        "creature_template_addon", "creature_template_locale",
        "creature_template_model", "creature_template_movement",
        "creature_template_resistance", "creature_template_spell",
        "creature_text", "creature_text_locale",
    ],
    "quests": [
        "quest_details", "quest_greeting", "quest_greeting_locale",
        "quest_mail_sender", "quest_money_reward", "quest_offer_reward",
        "quest_offer_reward_locale", "quest_poi", "quest_poi_points",
        "quest_request_items", "quest_request_items_locale",
        "quest_template", "quest_template_addon", "quest_template_locale",
    ],
    "items": [
        "item_enchantment_template", "item_loot_template",
        "item_set_names", "item_set_names_locale",
        "item_template", "item_template_locale",
    ],
    "gameobjects": [
        "gameobject", "gameobject_addon", "gameobject_loot_template",
        "gameobject_questender", "gameobject_questitem",
        "gameobject_queststarter", "gameobject_template",
        "gameobject_template_addon", "gameobject_template_locale",
    ],
    "npcs": [
        "gossip_menu", "gossip_menu_option", "gossip_menu_option_locale",
        "npc_spellclick_spells", "npc_text", "npc_text_locale",
        "npc_trainer", "npc_vendor", "trainer", "trainer_locale",
        "trainer_spell",
    ],
    "spells": [
        "spell_area", "spell_bonus_data", "spell_cooldown_overrides",
        "spell_custom_attr", "spell_enchant_proc_data", "spell_group",
        "spell_group_stack_rules", "spell_linked_spell",
        "spell_loot_template", "spell_mixology", "spell_pet_auras",
        "spell_proc", "spell_proc_event", "spell_ranks", "spell_required",
        "spell_script_names", "spell_scripts", "spell_target_position",
        "spell_threat",
    ],
    "loot": [
        "disenchant_loot_template", "fishing_loot_template",
        "mail_loot_template", "milling_loot_template",
        "pickpocketing_loot_template", "player_loot_template",
        "prospecting_loot_template", "reference_loot_template",
        "skinning_loot_template",
    ],
    "scripts": [
        "smart_scripts", "areatrigger_scripts", "conditions",
        "event_scripts", "script_waypoint", "spell_scripts",
        "waypoint_data", "waypoint_scripts", "waypoints",
    ],
    "world": [
        "areatrigger", "areatrigger_involvedrelation",
        "areatrigger_tavern", "areatrigger_teleport",
        "battleground_template", "battlemaster_entry",
        "exploration_basexp", "game_graveyard", "game_tele",
        "game_weather", "graveyard_zone", "instance_encounters",
        "instance_template", "linked_respawn", "outdoorpvp_template",
        "points_of_interest", "points_of_interest_locale", "transports",
    ],
    "events": [
        "game_event", "game_event_arena_seasons",
        "game_event_battleground_holiday", "game_event_condition",
        "game_event_creature", "game_event_creature_quest",
        "game_event_gameobject", "game_event_gameobject_quest",
        "game_event_model_equip", "game_event_npc_vendor",
        "game_event_npcflag", "game_event_pool",
        "game_event_prerequisite", "game_event_quest_condition",
        "game_event_seasonal_questrelation",
    ],
    "pools": [
        "pool_creature", "pool_gameobject", "pool_pool",
        "pool_quest", "pool_template",
    ],
    "broadcast": [
        "broadcast_text", "broadcast_text_locale",
        "page_text", "page_text_locale",
    ],
    "players": [
        "pet_levelstats", "pet_name_generation", "pet_name_generation_locale",
        "player_class_stats", "player_factionchange_achievement",
        "player_factionchange_items", "player_factionchange_quests",
        "player_factionchange_reputations", "player_factionchange_spells",
        "player_factionchange_titles", "player_loot_template",
        "player_race_stats", "player_shapeshift_model",
        "player_totem_model", "player_xp_for_level",
        "playercreateinfo", "playercreateinfo_action",
        "playercreateinfo_cast_spell", "playercreateinfo_item",
        "playercreateinfo_skills", "playercreateinfo_spell_custom",
    ],
    "system": [
        "acore_string", "antidos_opcode_policies", "command",
        "disables", "dungeon_access_requirements",
        "dungeon_access_template", "lfg_dungeon_rewards",
        "lfg_dungeon_template", "mail_level_reward",
        "module_string", "module_string_locale",
        "reputation_reward_rate", "reputation_spillover_template",
        "skill_discovery_template", "skill_extra_item_template",
        "skill_fishing_base_level", "skill_perfect_item_template",
        "updates", "updates_include", "version",
        "vehicle_accessory", "vehicle_seat_addon",
        "vehicle_template_accessory", "warden_checks",
        "arena_season_reward", "arena_season_reward_group",
        "holiday_dates",
    ],
}

# Tables with searchable text worth indexing via FTS5
_FTS_TABLES = frozenset([
    "creature_template", "item_template", "quest_template",
    "gameobject_template", "broadcast_text", "broadcast_text_locale",
    "acore_string", "npc_text", "creature_template_locale",
    "item_template_locale", "quest_template_locale",
    "gameobject_template_locale", "gossip_menu_option",
    "page_text", "smart_scripts",
])

# Build reverse mapping
_TABLE_TO_CATEGORY: dict[str, str] = {}
for _cat, _names in _WORLD_CATEGORIES.items():
    for _name in _names:
        _TABLE_TO_CATEGORY[_name] = _cat


def _get_category(table_name: str) -> str:
    """Determine category for a table name."""
    if table_name in _TABLE_TO_CATEGORY:
        return _TABLE_TO_CATEGORY[table_name]
    if table_name.endswith("_dbc"):
        return "dbc_overrides"
    return "misc"


# ---------------------------------------------------------------------------
# SQLite identifier quoting
# ---------------------------------------------------------------------------
# Known WoW locale codes
_LOCALE_CODES = frozenset([
    "enUS", "koKR", "frFR", "deDE", "enCN", "enTW", "esES", "esMX",
    "ruRU", "jaJP", "ptPT", "itIT", "zhCN", "zhTW",
])

_LOCALE_SUFFIX_RE = re.compile(
    r'^(.+)_(' + '|'.join(_LOCALE_CODES) + r')$'
)


def _quote(name: str) -> str:
    """Quote a SQLite identifier."""
    return '"{}"'.format(name.replace('"', '""'))


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------
class WorldDB:
    """SQLite-backed AzerothCore world database."""

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
            CREATE TABLE IF NOT EXISTS _world_meta (
                table_name TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                pk_columns TEXT NOT NULL,
                column_defs TEXT NOT NULL,
                field_types TEXT NOT NULL,
                record_count INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Build — import from SQL dump files
    # ------------------------------------------------------------------
    def build_from_sql(self, sql_dir: str = SQL_DIR) -> dict[str, int]:
        """Parse .original/server/data/sql/base/db_world/*.sql → SQLite.

        Returns {table_name: record_count, ...}.
        """
        sql_dir = os.path.normpath(sql_dir)
        results: dict[str, int] = {}

        sql_files = sorted(
            f for f in os.listdir(sql_dir) if f.endswith(".sql")
        )

        for fname in sql_files:
            path = os.path.join(sql_dir, fname)
            try:
                count = self._import_sql_file(path)
                table_name = os.path.splitext(fname)[0]
                results[table_name] = count
                print("  {:45s} {:>8} records".format(table_name, count))
            except Exception as e:
                print("  FAIL {:45s} -- {}".format(fname, e))

        return results

    def _import_sql_file(self, path: str) -> int:
        """Parse one SQL file and import into SQLite. Returns record count."""
        schema = parse_create_table(path)
        if schema is None or not schema.columns:
            return 0

        table_name = schema.table_name
        category = _get_category(table_name)
        pk_columns = schema.pk_columns
        col_names = schema.column_names

        # Build field_types dict
        field_types = {c.name: c.sqlite_type for c in schema.columns}

        # Drop existing table + FTS
        self.conn.execute("DROP TABLE IF EXISTS {}".format(
            _quote(table_name + "_fts")))
        self.conn.execute("DROP TABLE IF EXISTS {}".format(
            _quote(table_name)))

        # Create main table
        col_defs = []
        for col in schema.columns:
            col_defs.append("{} {}".format(_quote(col.name), col.sqlite_type))

        # Add PK constraint
        pk_expr = ", ".join(_quote(c) for c in pk_columns)
        create_sql = "CREATE TABLE {} ({}, PRIMARY KEY ({}))".format(
            _quote(table_name), ", ".join(col_defs), pk_expr)
        self.conn.execute(create_sql)

        # Create FTS5 for eligible tables
        text_cols = [c.name for c in schema.columns if c.sqlite_type == "TEXT"]
        if table_name in _FTS_TABLES and text_cols:
            self._create_fts(table_name, text_cols, pk_columns[0])

        # Insert records in batches
        placeholders = ", ".join("?" for _ in col_names)
        insert_sql = "INSERT OR REPLACE INTO {} ({}) VALUES ({})".format(
            _quote(table_name),
            ", ".join(_quote(c) for c in col_names),
            placeholders)

        batch: list[tuple] = []
        count = 0

        for row in parse_insert_rows(path, schema):
            batch.append(row)
            count += 1
            if len(batch) >= 5000:
                self.conn.executemany(insert_sql, batch)
                batch.clear()

        if batch:
            self.conn.executemany(insert_sql, batch)

        # Store column definitions for SQL generation
        column_defs = [
            {"name": c.name, "mysql_type": c.mysql_type,
             "sqlite_type": c.sqlite_type, "nullable": c.nullable}
            for c in schema.columns
        ]

        # Store metadata
        self.conn.execute("""
            INSERT OR REPLACE INTO _world_meta
            (table_name, category, pk_columns, column_defs, field_types, record_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (table_name, category,
              json.dumps(pk_columns),
              json.dumps(column_defs, ensure_ascii=False),
              json.dumps(field_types, ensure_ascii=False),
              count))

        self.conn.commit()
        return count

    def _create_fts(self, table_name: str, text_cols: list[str],
                    rowid_col: str):
        """Create FTS5 virtual table with sync triggers."""
        fts_name = table_name + "_fts"
        fts_cols = ", ".join(_quote(c) for c in text_cols)

        self.conn.execute(
            "CREATE VIRTUAL TABLE {} USING fts5({}, content={}, content_rowid={})".format(
                _quote(fts_name), fts_cols,
                _quote(table_name), _quote(rowid_col)))

        main_tbl = _quote(table_name)
        fts_tbl = _quote(fts_name)
        pk_col = _quote(rowid_col)
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

    # ------------------------------------------------------------------
    # Build — import from live MySQL
    # ------------------------------------------------------------------
    def build_from_mysql(self, host: str = "127.0.0.1", port: int = 3306,
                         user: str = "acore", password: str = "acore",
                         database: str = "acore_world") -> dict[str, int]:
        """Connect to live MySQL and dump acore_world tables → SQLite.

        Requires pymysql: pip install pymysql
        """
        try:
            import pymysql
        except ImportError:
            print("ERROR: pymysql required. Install with: pip install pymysql")
            sys.exit(1)

        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=database, charset="utf8mb4",
        )
        results: dict[str, int] = {}

        try:
            cur = conn.cursor()
            cur.execute("SHOW TABLES")
            tables = [row[0] for row in cur.fetchall()]

            for table_name in sorted(tables):
                try:
                    count = self._import_mysql_table(conn, table_name)
                    results[table_name] = count
                    print("  {:45s} {:>8} records".format(table_name, count))
                except Exception as e:
                    print("  FAIL {:45s} -- {}".format(table_name, e))
        finally:
            conn.close()

        return results

    def _import_mysql_table(self, mysql_conn, table_name: str) -> int:
        """Import a single MySQL table into SQLite."""
        import pymysql

        cur = mysql_conn.cursor()

        # Get column info
        cur.execute("SHOW COLUMNS FROM `{}`".format(table_name))
        columns = cur.fetchall()
        # columns: (Field, Type, Null, Key, Default, Extra)

        # Get PK columns
        pk_columns = [c[0] for c in columns if c[3] == "PRI"]
        if not pk_columns:
            pk_columns = [columns[0][0]]

        # Map MySQL types to SQLite
        col_defs_list = []
        field_types = {}
        column_defs = []
        for c in columns:
            col_name = c[0]
            mysql_type_raw = c[1].lower()
            # Extract base type
            base_type = re.match(r'(\w+)', mysql_type_raw).group(1)
            from .sql_parser import _TYPE_MAP
            sqlite_type = _TYPE_MAP.get(base_type, "TEXT")
            nullable = c[2] == "YES"

            col_defs_list.append("{} {}".format(_quote(col_name), sqlite_type))
            field_types[col_name] = sqlite_type
            column_defs.append({
                "name": col_name, "mysql_type": base_type,
                "sqlite_type": sqlite_type, "nullable": nullable,
            })

        col_names = [c[0] for c in columns]
        category = _get_category(table_name)

        # Drop and recreate
        self.conn.execute("DROP TABLE IF EXISTS {}".format(
            _quote(table_name + "_fts")))
        self.conn.execute("DROP TABLE IF EXISTS {}".format(
            _quote(table_name)))

        pk_expr = ", ".join(_quote(c) for c in pk_columns)
        create_sql = "CREATE TABLE {} ({}, PRIMARY KEY ({}))".format(
            _quote(table_name), ", ".join(col_defs_list), pk_expr)
        self.conn.execute(create_sql)

        # Create FTS5 for eligible tables
        text_cols = [cn for cn in col_names if field_types[cn] == "TEXT"]
        if table_name in _FTS_TABLES and text_cols:
            self._create_fts(table_name, text_cols, pk_columns[0])

        # Fetch and insert data
        cur.execute("SELECT * FROM `{}`".format(table_name))
        placeholders = ", ".join("?" for _ in col_names)
        insert_sql = "INSERT OR REPLACE INTO {} ({}) VALUES ({})".format(
            _quote(table_name),
            ", ".join(_quote(c) for c in col_names),
            placeholders)

        batch: list[tuple] = []
        count = 0

        while True:
            rows = cur.fetchmany(5000)
            if not rows:
                break
            self.conn.executemany(insert_sql, rows)
            count += len(rows)

        # Store metadata
        self.conn.execute("""
            INSERT OR REPLACE INTO _world_meta
            (table_name, category, pk_columns, column_defs, field_types, record_count)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (table_name, category,
              json.dumps(pk_columns),
              json.dumps(column_defs, ensure_ascii=False),
              json.dumps(field_types, ensure_ascii=False),
              count))

        self.conn.commit()
        return count

    # ------------------------------------------------------------------
    # Query (read)
    # ------------------------------------------------------------------
    def tables(self, category: str | None = None) -> list[dict]:
        """List all tables with record counts and categories."""
        if category:
            rows = self.conn.execute(
                "SELECT * FROM _world_meta WHERE category=? ORDER BY table_name",
                (category,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM _world_meta ORDER BY category, table_name"
            ).fetchall()

        result = []
        for row in rows:
            result.append({
                "name": row["table_name"],
                "category": row["category"],
                "records": row["record_count"],
                "pk": json.loads(row["pk_columns"]),
            })
        return result

    def schema(self, table: str) -> list[dict]:
        """Show columns and types for a table."""
        meta = self._get_meta(table)
        if not meta:
            return []
        col_defs = json.loads(meta["column_defs"])
        pk_cols = set(json.loads(meta["pk_columns"]))
        return [{"name": c["name"], "type": c["sqlite_type"],
                 "mysql_type": c["mysql_type"],
                 "pk": c["name"] in pk_cols} for c in col_defs]

    def lookup(self, table: str, *pk_values) -> dict | None:
        """Single record by primary key.

        Single PK:    lookup("creature_template", 1234)
        Composite PK: lookup("smart_scripts", 1234, 0, 5, 0)
        """
        meta = self._get_meta(table)
        if not meta:
            return None
        pk_cols = json.loads(meta["pk_columns"])

        if len(pk_values) != len(pk_cols):
            raise ValueError(
                "Expected {} PK values ({}), got {}".format(
                    len(pk_cols), ", ".join(pk_cols), len(pk_values)))

        where = " AND ".join("{} = ?".format(_quote(c)) for c in pk_cols)
        row = self.conn.execute(
            "SELECT * FROM {} WHERE {}".format(_quote(table), where),
            pk_values).fetchone()
        return dict(row) if row else None

    def search(self, table: str, term: str, limit: int = 20) -> list[dict]:
        """FTS5 search on text columns, falls back to LIKE."""
        term = term.strip()
        if not term:
            return []

        fts_table = table + "_fts"
        exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (fts_table,)).fetchone()

        if exists:
            meta = self._get_meta(table)
            pk_col = json.loads(meta["pk_columns"])[0]
            sql = """
                SELECT t.* FROM {fts} fts
                JOIN {tbl} t ON t.{pk} = fts.rowid
                WHERE {fts} MATCH ?
                ORDER BY fts.rank
                LIMIT ?
            """.format(fts=_quote(fts_table), tbl=_quote(table),
                       pk=_quote(pk_col))

            # Try exact match
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
        meta = self._get_meta(table)
        if not meta:
            return []
        field_types = json.loads(meta["field_types"])
        text_cols = [fn for fn, ft in field_types.items() if ft == "TEXT"]
        if not text_cols:
            return []

        like_pat = "%{}%".format(term)
        where = " OR ".join("{} LIKE ?".format(_quote(c)) for c in text_cols)
        params: list = [like_pat] * len(text_cols) + [limit]
        rows = self.conn.execute(
            "SELECT * FROM {} WHERE ({}) LIMIT ?".format(
                _quote(table), where),
            params).fetchall()
        return [dict(r) for r in rows]

    def list_records(self, table: str, limit: int = 50,
                     where: dict[str, Any] | None = None) -> list[dict]:
        """List records with optional field=value filters."""
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
    # Modify — write to .patch/database/ YAML
    # ------------------------------------------------------------------
    def write_patch(self, table: str, action: str,
                    pk_values: list, fields: dict | None = None,
                    patch_dir: str = PATCH_DB_DIR,
                    locale: str | None = None):
        """Write a modification to the patch YAML file.

        Args:
            table: Table name (e.g. "creature_template")
            action: "modify", "add", or "remove"
            pk_values: Primary key values (list, even for single PK)
            fields: Field values (required for modify/add)
            patch_dir: Base patch directory
            locale: If set, append _{locale} to field names
        """
        # Rewrite field names when locale is specified
        if locale and fields:
            fields = {"{}_{}".format(k, locale): v for k, v in fields.items()}
        category = _get_category(table)
        patch_file = os.path.join(patch_dir, category, table + ".yaml")

        # Load existing patch file or create new
        if os.path.isfile(patch_file):
            with open(patch_file, "r", encoding="utf-8") as f:
                patch_data = yaml.safe_load(f) or {}
        else:
            patch_data = {}

        if "_meta" not in patch_data:
            patch_data["_meta"] = {"table_name": table}
        if "records" not in patch_data:
            patch_data["records"] = {}
        if "_deleted" not in patch_data:
            patch_data["_deleted"] = []

        # Build key string (pipe-delimited for composite PKs)
        pk_key = self._make_pk_key(pk_values)

        if action in ("modify", "add"):
            if fields is None:
                raise ValueError("fields required for {} action".format(action))
            existing = patch_data["records"].get(pk_key, {})
            existing.update(fields)
            patch_data["records"][pk_key] = existing

        elif action == "remove":
            if pk_key not in patch_data["_deleted"]:
                patch_data["_deleted"].append(pk_key)
            patch_data["records"].pop(pk_key, None)

        # Clean up empty sections
        if not patch_data["_deleted"]:
            del patch_data["_deleted"]

        os.makedirs(os.path.dirname(patch_file), exist_ok=True)
        with open(patch_file, "w", encoding="utf-8") as f:
            yaml.dump(patch_data, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False, width=120)

    # ------------------------------------------------------------------
    # Generate SQL — convert YAML patches to MySQL SQL
    # ------------------------------------------------------------------
    def patches_to_sql(self, patch_dirs: str | list[str] = PATCH_DB_DIR,
                       output_dir: str = MERGED_DB_DIR,
                       remapper: Optional[IDRemapper] = None) -> list[str]:
        """Convert .patch/database/**/*.yaml → .merged/database/*.sql.

        patch_dirs can be a single path (str) or list of paths applied
        in order (for layered patches). When multiple layers modify the
        same table, records are merged in layer order (later wins).

        If remapper is provided, @entity_type:N syntax in YAML files with
        _meta.local_ids: true will be remapped to real IDs.

        Returns list of generated SQL file paths.
        """
        # Normalize to list
        if isinstance(patch_dirs, str):
            patch_dirs = [patch_dirs]

        output_dir = os.path.normpath(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # Create remapper if not provided
        if remapper is None:
            try:
                remapper = IDRemapper()
            except FileNotFoundError:
                remapper = None  # No registry file, skip remapping

        # Collect YAML files from all layers, grouped by table name.
        # _meta.table_name in the YAML overrides the filename-derived name.
        # table_name -> [yaml_path1, yaml_path2, ...] in layer order
        table_yamls: dict[str, list[str]] = {}
        for pdir in patch_dirs:
            pdir = os.path.normpath(pdir)
            for root, _dirs, files in os.walk(pdir):
                for fname in sorted(files):
                    if not fname.endswith(".yaml"):
                        continue
                    fpath = os.path.join(root, fname)
                    # Resolve table name: prefer _meta.table_name over filename
                    table_name = os.path.splitext(fname)[0]
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            header = yaml.safe_load(f)
                        if isinstance(header, dict):
                            meta_tn = (header.get("_meta") or {}).get("table_name")
                            if meta_tn:
                                table_name = meta_tn
                    except Exception:
                        pass
                    table_yamls.setdefault(table_name, []).append(fpath)

        generated: list[str] = []
        file_index = 1

        for table_name in sorted(table_yamls.keys()):
            yaml_paths = table_yamls[table_name]
            try:
                # Merge YAML data from all layers for this table
                merged_data = self._merge_yaml_layers(
                    yaml_paths, remapper=remapper, patch_dirs=patch_dirs
                )
                if not merged_data:
                    continue

                sql_lines = self._merged_data_to_sql(merged_data, table_name)
                if sql_lines:
                    out_name = "{:02d}_{}.sql".format(file_index, table_name)
                    out_path = os.path.join(output_dir, out_name)
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write("USE `acore_world`;\n\n")
                        f.write("\n".join(sql_lines))
                        f.write("\n")
                    generated.append(out_path)
                    print("  Generated: {}".format(out_name))
                    file_index += 1
            except Exception as e:
                print("  FAIL {:40s} -- {}".format(table_name, e))

        return generated

    @staticmethod
    def _detect_layer_from_path(yaml_path: str, patch_dirs: list[str]) -> Optional[str]:
        """Detect layer ID from yaml_path by matching against patch_dirs.

        Args:
            yaml_path: Full path to YAML file
            patch_dirs: List of patch directory roots

        Returns:
            Layer ID (directory name under .patch/) or None
        """
        yaml_path = os.path.normpath(yaml_path)

        for pdir in patch_dirs:
            pdir = os.path.normpath(pdir)
            if yaml_path.startswith(pdir):
                # Extract the layer name from path
                # e.g., .patch/dev-sensible-loot/database/... -> sensible-loot
                rel_path = os.path.relpath(yaml_path, pdir)
                parts = rel_path.split(os.sep)
                if parts:
                    # First part might be a category dir, check if it's the layer
                    # Patch dirs are like .patch/dev-sensible-loot/database/
                    # So we need to extract from the patch_dir path itself
                    pass

        # Fallback: extract from .patch/<layer>/ pattern
        # yaml_path might be like G:/WoW Projects/.patch/dev-sensible-loot/database/...
        parts = yaml_path.split(os.sep)
        for i, part in enumerate(parts):
            if part == ".patch" and i + 1 < len(parts):
                layer_dir = parts[i + 1]
                # Strip common prefixes like "dev-", "01-", etc.
                if layer_dir.startswith("dev-"):
                    return layer_dir[4:]  # Remove "dev-" prefix
                elif layer_dir[0].isdigit() and "-" in layer_dir:
                    # Handle numbered layers like "01-example-data"
                    return layer_dir.split("-", 1)[1] if "-" in layer_dir else layer_dir
                return layer_dir
        return None

    @staticmethod
    def _merge_yaml_layers(
        yaml_paths: list[str],
        remapper: Optional[IDRemapper] = None,
        patch_dirs: Optional[list[str]] = None
    ) -> dict:
        """Merge YAML patch data from multiple layers.

        Records are merged in order — later layers override earlier ones
        on a per-field basis. _deleted lists are accumulated.

        If remapper is provided and YAML has _meta.local_ids: true,
        @entity_type:N syntax is remapped to real IDs.
        """
        merged_records: dict = {}
        deleted_set: set = set()

        for yaml_path in yaml_paths:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data:
                continue

            # Check if this file uses local IDs
            meta = data.get("_meta") or {}
            uses_local_ids = meta.get("local_ids", False)
            table_name = meta.get("table_name", "")

            # Detect layer for remapping
            layer_id = None
            if uses_local_ids and remapper and patch_dirs:
                layer_id = WorldDB._detect_layer_from_path(yaml_path, patch_dirs)

            for pk_key, fields in data.get("records", {}).items():
                if not isinstance(fields, dict):
                    continue

                # Remap IDs if local mode is active
                if uses_local_ids and remapper and layer_id:
                    try:
                        fields, pk_key = remapper.remap_record(
                            layer_id, table_name, fields, pk_key
                        )
                    except ValueError as e:
                        print(f"  WARN: ID remap failed in {yaml_path}: {e}")
                        continue

                # Un-delete if a later layer re-adds a record
                deleted_set.discard(pk_key)
                if pk_key in merged_records:
                    merged_records[pk_key].update(fields)
                else:
                    merged_records[pk_key] = dict(fields)

            for del_key in data.get("_deleted", []):
                # Remap deletion keys too
                if uses_local_ids and remapper and layer_id:
                    try:
                        del_key = remapper.remap_pk(layer_id, del_key, table_name)
                    except ValueError as e:
                        print(f"  WARN: Delete key remap failed in {yaml_path}: {e}")
                        continue

                deleted_set.add(del_key)
                merged_records.pop(del_key, None)

        if not merged_records and not deleted_set:
            return {}

        result: dict = {}
        if merged_records:
            result["records"] = merged_records
        if deleted_set:
            result["_deleted"] = sorted(deleted_set,
                                        key=lambda x: str(x))
        return result

    def _merged_data_to_sql(self, data: dict,
                            table_name: str) -> list[str]:
        """Convert pre-merged YAML data dict to SQL statements."""
        meta = self._get_meta(table_name)
        pk_cols = json.loads(meta["pk_columns"]) if meta else [table_name]
        sql_lines: list[str] = []

        # Check if a locale table exists for this base table
        locale_table = table_name + "_locale"
        locale_meta = self._get_meta(locale_table)
        locale_col_set: set[str] = set()
        if locale_meta:
            locale_col_defs = json.loads(locale_meta["column_defs"])
            locale_col_set = {c["name"] for c in locale_col_defs
                              if c["name"] != "locale"
                              and c["name"] not in json.loads(locale_meta["pk_columns"])}

        for pk_key, fields in data.get("records", {}).items():
            if not isinstance(fields, dict):
                continue
            pk_values = self._parse_pk_key(str(pk_key))

            # Extract locale-suffixed fields before processing the base record
            # {locale_code: {column: value}} grouped by locale
            locale_data: dict[str, dict[str, str]] = {}
            base_fields: dict[str, Any] = {}

            for fk, fv in fields.items():
                m = _LOCALE_SUFFIX_RE.match(fk)
                if m and locale_meta:
                    col_name, locale_code = m.group(1), m.group(2)
                    if col_name in locale_col_set:
                        locale_data.setdefault(locale_code, {})[col_name] = fv
                        continue
                base_fields[fk] = fv

            existing = None
            if meta and len(pk_values) == len(pk_cols):
                typed_pks = self._type_pk_values(pk_values, pk_cols, meta)
                try:
                    existing = self.lookup(table_name, *typed_pks)
                except Exception:
                    pass

            if existing:
                set_parts = []
                for fk, fv in base_fields.items():
                    if fk in pk_cols:
                        continue
                    set_parts.append("`{}` = {}".format(
                        fk, self._sql_value(fv)))
                if set_parts:
                    where_parts = []
                    for i, pc in enumerate(pk_cols):
                        where_parts.append("`{}` = {}".format(
                            pc, self._sql_value(pk_values[i])))
                    sql_lines.append("UPDATE `{}` SET {} WHERE {};".format(
                        table_name, ", ".join(set_parts),
                        " AND ".join(where_parts)))
            else:
                row_data = dict(base_fields)
                for i, pc in enumerate(pk_cols):
                    if pc not in row_data:
                        row_data[pc] = pk_values[i]
                ins_cols = list(row_data.keys())
                ins_vals = [self._sql_value(row_data[c]) for c in ins_cols]
                sql_lines.append(
                    "REPLACE INTO `{}` ({}) VALUES ({});".format(
                        table_name,
                        ", ".join("`{}`".format(c) for c in ins_cols),
                        ", ".join(ins_vals)))

            # Generate locale table SQL
            if locale_data and locale_meta:
                locale_pk_cols = json.loads(locale_meta["pk_columns"])
                for locale_code, loc_fields in sorted(locale_data.items()):
                    loc_cols = list(loc_fields.keys())
                    # Build full row: PK columns + locale + data columns
                    all_cols = []
                    all_vals = []
                    for i, pc in enumerate(locale_pk_cols):
                        if pc == "locale":
                            all_cols.append("locale")
                            all_vals.append(self._sql_value(locale_code))
                        elif i < len(pk_values):
                            all_cols.append(pc)
                            all_vals.append(self._sql_value(pk_values[i]))
                    for col in loc_cols:
                        all_cols.append(col)
                        all_vals.append(self._sql_value(loc_fields[col]))
                    sql_lines.append(
                        "REPLACE INTO `{}` ({}) VALUES ({});".format(
                            locale_table,
                            ", ".join("`{}`".format(c) for c in all_cols),
                            ", ".join(all_vals)))

        for pk_key in data.get("_deleted", []):
            pk_values = self._parse_pk_key(str(pk_key))
            where_parts = []
            for i, pc in enumerate(pk_cols):
                if i < len(pk_values):
                    where_parts.append("`{}` = {}".format(
                        pc, self._sql_value(pk_values[i])))
            if where_parts:
                sql_lines.append("DELETE FROM `{}` WHERE {};".format(
                    table_name, " AND ".join(where_parts)))

        return sql_lines

    def _yaml_to_sql(self, yaml_path: str, table_name: str) -> list[str]:
        """Convert one YAML patch file to SQL statements."""
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            return []

        meta = self._get_meta(table_name)
        pk_cols = json.loads(meta["pk_columns"]) if meta else [table_name]
        col_defs = json.loads(meta["column_defs"]) if meta else []
        col_names = [c["name"] for c in col_defs]

        sql_lines: list[str] = []

        # Process records (modifications and additions)
        for pk_key, fields in data.get("records", {}).items():
            if not isinstance(fields, dict):
                continue
            pk_values = self._parse_pk_key(str(pk_key))

            # Check if record exists in SQLite to decide UPDATE vs INSERT
            existing = None
            if meta and len(pk_values) == len(pk_cols):
                typed_pks = self._type_pk_values(pk_values, pk_cols, meta)
                try:
                    existing = self.lookup(table_name, *typed_pks)
                except Exception:
                    pass

            if existing:
                # UPDATE
                set_parts = []
                for fk, fv in fields.items():
                    if fk in [c for c in pk_cols]:
                        continue
                    set_parts.append("`{}` = {}".format(fk, self._sql_value(fv)))
                if set_parts:
                    where_parts = []
                    for i, pc in enumerate(pk_cols):
                        where_parts.append("`{}` = {}".format(
                            pc, self._sql_value(pk_values[i])))
                    sql_lines.append("UPDATE `{}` SET {} WHERE {};".format(
                        table_name, ", ".join(set_parts),
                        " AND ".join(where_parts)))
            else:
                # INSERT — build full row from existing + patch fields
                if existing:
                    row_data = dict(existing)
                    row_data.update(fields)
                else:
                    row_data = dict(fields)
                    # Add PK values
                    for i, pc in enumerate(pk_cols):
                        if pc not in row_data:
                            row_data[pc] = pk_values[i]

                ins_cols = [c for c in row_data.keys()]
                ins_vals = [self._sql_value(row_data[c]) for c in ins_cols]
                sql_lines.append(
                    "REPLACE INTO `{}` ({}) VALUES ({});".format(
                        table_name,
                        ", ".join("`{}`".format(c) for c in ins_cols),
                        ", ".join(ins_vals)))

        # Process deletions
        for pk_key in data.get("_deleted", []):
            pk_values = self._parse_pk_key(str(pk_key))
            where_parts = []
            for i, pc in enumerate(pk_cols):
                if i < len(pk_values):
                    where_parts.append("`{}` = {}".format(
                        pc, self._sql_value(pk_values[i])))
            if where_parts:
                sql_lines.append("DELETE FROM `{}` WHERE {};".format(
                    table_name, " AND ".join(where_parts)))

        return sql_lines

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_meta(self, table: str) -> sqlite3.Row | None:
        """Get metadata row for a table."""
        return self.conn.execute(
            "SELECT * FROM _world_meta WHERE table_name=?",
            (table,)).fetchone()

    @staticmethod
    def _make_pk_key(pk_values: list) -> str | int:
        """Create YAML key from PK values.

        Single PK: returns the value directly (int or str).
        Composite PK: returns pipe-delimited string.
        """
        if len(pk_values) == 1:
            v = pk_values[0]
            if isinstance(v, str):
                try:
                    return int(v)
                except ValueError:
                    return v
            return v
        return "|".join(str(v) for v in pk_values)

    @staticmethod
    def _parse_pk_key(key: str) -> list:
        """Parse a PK key back into individual values."""
        if "|" in key:
            parts = key.split("|")
        else:
            parts = [key]
        result = []
        for p in parts:
            try:
                result.append(int(p))
            except ValueError:
                try:
                    result.append(float(p))
                except ValueError:
                    result.append(p)
        return result

    def _type_pk_values(self, pk_values: list, pk_cols: list[str],
                        meta: sqlite3.Row) -> list:
        """Cast PK values to appropriate types based on schema."""
        field_types = json.loads(meta["field_types"])
        result = []
        for i, v in enumerate(pk_values):
            col = pk_cols[i] if i < len(pk_cols) else None
            ftype = field_types.get(col, "TEXT") if col else "TEXT"
            if ftype == "INTEGER":
                try:
                    result.append(int(v))
                except (ValueError, TypeError):
                    result.append(v)
            elif ftype == "REAL":
                try:
                    result.append(float(v))
                except (ValueError, TypeError):
                    result.append(v)
            else:
                result.append(v)
        return result

    @staticmethod
    def _sql_value(val) -> str:
        """Convert a Python value to MySQL SQL literal."""
        if val is None:
            return "NULL"
        if isinstance(val, bool):
            return "1" if val else "0"
        if isinstance(val, int):
            return str(val)
        if isinstance(val, float):
            return str(val)
        # String — escape for MySQL
        s = str(val)
        s = s.replace("\\", "\\\\")
        s = s.replace("'", "\\'")
        s = s.replace("\n", "\\n")
        s = s.replace("\r", "\\r")
        return "'{}'".format(s)
