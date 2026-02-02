# SQL Generator Module - Complete Server-Side Database Generation

**Status**: DESIGN PHASE
**Target**: AzerothCore 3.3.5a `acore_world` database
**Location**: `world_builder/sql_generator.py`
**Purpose**: Enable AI agents to generate ALL server-side database entries for WoW 3.3.5a custom zones

## Executive Summary

This module transforms pywowlib from a client-only world compiler into a complete headless world compiler (client + server). It provides structured Python APIs for generating all AzerothCore database entries needed for a playable custom zone: items, NPCs, creatures, quests, SmartAI scripts, spawns, gameobjects, dungeon configuration, world events, and translations.

**Enabled TODOs**: 1.5 (Items), 1.6 (NPCs), 1.7 (Creatures), 2.1 (Zone Registration), 2.2 (SmartAI), 2.3 (Quests), 2.4 (Quest Events), 2.5 (Dungeon DB setup), 3.1 (Spawns), 3.2 (Game Objects), 3.4 (Breadcrumbs), 4.1 (World Events), 4.2 (Translation)

**Philosophy**: Self-contained, dependency-free, pure Python SQL generation with comprehensive validation and cross-referencing.

---

## 1. Module Architecture

### 1.1 Core Class Structure

```python
# world_builder/sql_generator.py

class SQLGenerator:
    """
    Orchestrates all SQL generation for AzerothCore world database.

    Responsibilities:
    - Entry ID management (auto-increment from configurable base)
    - Foreign key tracking and validation
    - SQL output formatting (single file or split by table)
    - Cross-reference validation (detect missing references)
    """

    def __init__(self, start_entry=90000, map_id=None, zone_id=None):
        """
        Args:
            start_entry: Base entry ID for auto-generated IDs
            map_id: Map ID for this zone (for spawn coordinates)
            zone_id: Zone ID for quest_sort, area table references
        """
        self.start_entry = start_entry
        self.current_entry = start_entry
        self.map_id = map_id
        self.zone_id = zone_id

        # Builder instances
        self.item_builder = ItemBuilder(self)
        self.creature_builder = CreatureBuilder(self)
        self.npc_builder = NPCBuilder(self)
        self.quest_builder = QuestBuilder(self)
        self.smartai_builder = SmartAIBuilder(self)
        self.spawn_builder = SpawnBuilder(self)
        self.gameobject_builder = GameObjectBuilder(self)
        self.dungeon_builder = DungeonBuilder(self)
        self.event_builder = EventBuilder(self)
        self.locale_builder = LocaleBuilder(self)
        self.zone_builder = ZoneBuilder(self)

        # Cross-reference tracking
        self.entities = {
            'items': {},         # entry -> item_data
            'creatures': {},     # entry -> creature_data
            'npcs': {},          # entry -> npc_data (subset of creatures)
            'quests': {},        # entry -> quest_data
            'gameobjects': {},   # entry -> go_data
            'spawns': {},        # guid -> spawn_data
            'go_spawns': {},     # guid -> go_spawn_data
        }

        # SQL output buffers (table_name -> list of SQL statements)
        self.sql_buffers = {}

    def allocate_entry(self):
        """Allocate next available entry ID."""
        entry = self.current_entry
        self.current_entry += 1
        return entry

    def validate(self):
        """
        Validate all cross-references and detect issues.

        Returns:
            dict: {
                'valid': bool,
                'errors': list[str],
                'warnings': list[str],
            }
        """
        pass

    def write_sql(self, output_path):
        """Write all SQL to a single monolithic file."""
        pass

    def write_sql_split(self, output_dir):
        """Write SQL split by table name (one file per table)."""
        pass
```

### 1.2 Per-Table Builder Pattern

Each builder is responsible for a specific domain (items, quests, creatures, etc.) and knows the schema of its tables.

```python
class BaseBuilder:
    """Base class for all table builders."""

    def __init__(self, generator):
        self.gen = generator  # Reference to parent SQLGenerator

    def escape_sql_string(self, s):
        """Escape string for SQL insertion."""
        if s is None:
            return 'NULL'
        return "'" + str(s).replace("'", "''").replace("\\", "\\\\") + "'"

    def format_insert(self, table, columns, values):
        """
        Format INSERT statement with explicit column names.

        Args:
            table: Table name
            columns: List of column names
            values: List of value tuples (one tuple per row)

        Returns:
            str: Formatted INSERT statement
        """
        lines = []
        lines.append(f"INSERT INTO `{table}` ({', '.join(f'`{c}`' for c in columns)}) VALUES")

        value_rows = []
        for row in values:
            formatted = []
            for v in row:
                if v is None:
                    formatted.append('NULL')
                elif isinstance(v, str):
                    formatted.append(self.escape_sql_string(v))
                elif isinstance(v, (int, float)):
                    formatted.append(str(v))
                else:
                    formatted.append(self.escape_sql_string(str(v)))
            value_rows.append('(' + ', '.join(formatted) + ')')

        lines.append(',\n'.join(value_rows) + ';')
        return '\n'.join(lines)

    def add_sql(self, table, sql):
        """Add SQL statement to buffer for a specific table."""
        if table not in self.gen.sql_buffers:
            self.gen.sql_buffers[table] = []
        self.gen.sql_buffers[table].append(sql)


class ItemBuilder(BaseBuilder):
    """Generates item_template and related tables."""

    def add_item(self, item_def):
        """
        Add item from structured definition.

        Args:
            item_def: dict with keys: entry (optional), name, class, subclass,
                      inventory_type, quality, item_level, required_level, stats, etc.

        Returns:
            int: Allocated entry ID
        """
        pass


class CreatureBuilder(BaseBuilder):
    """Generates creature_template and related tables."""

    def add_creature(self, creature_def):
        """Add creature from structured definition."""
        pass


# ... similar for QuestBuilder, SmartAIBuilder, etc.
```

---

## 2. Entry ID Management

### 2.1 Auto-Increment Strategy

```python
class SQLGenerator:
    def allocate_entry(self):
        """
        Allocate next available entry ID.

        Thread-safe increment. Used when entry is not explicitly provided
        in entity definition.
        """
        entry = self.current_entry
        self.current_entry += 1
        return entry

    def register_entity(self, entity_type, entry, data):
        """
        Register entity for cross-reference validation.

        Args:
            entity_type: 'items', 'creatures', 'quests', etc.
            entry: Entity entry ID
            data: Entity definition dict
        """
        if entry in self.entities[entity_type]:
            raise ValueError(f"Duplicate {entity_type} entry: {entry}")
        self.entities[entity_type][entry] = data
```

### 2.2 Explicit vs Auto Entry IDs

```python
# Example usage:

# Explicit entry ID
gen.add_items([{'entry': 90001, 'name': 'Gladiator Coin', ...}])

# Auto-allocated entry ID
item_entry = gen.add_items([{'name': 'Mystery Potion', ...}])
# Returns: 90000 (first auto-allocated ID)

# Subsequent auto-allocation
gen.add_creatures([{'name': 'Tel\'Abim Gorilla', ...}])
# Uses entry: 90001
```

---

## 3. Foreign Key Cross-Referencing

### 3.1 Reference Types

```python
# Quest references item (required_item, reward_item)
quests = [{
    'entry': 90010,
    'required_item': [(90001, 5)],  # Collect 5 of item 90001
    'reward_item': [(90002, 1)],    # Reward item 90002
}]

# Quest references creature (quest_giver, quest_ender, required_npc_or_go)
quests = [{
    'entry': 90010,
    'quest_giver_entry': 90050,      # NPC 90050 gives quest
    'quest_ender_entry': 90050,      # NPC 90050 ends quest
    'required_npc_or_go': [(90060, 10)],  # Kill 10 of creature 90060
}]

# Spawn references creature
spawns = [{
    'type': 'creature',
    'entry': 90050,  # Must exist in creature_template
    'map': 1,
    'position': (x, y, z, o),
}]

# SmartAI references creature
creature_ai = {
    90060: {  # creature entry, must exist in creature_template
        'abilities': [...],
    },
}
```

### 3.2 Validation Logic

```python
class SQLGenerator:
    def validate(self):
        """
        Validate all cross-references and detect issues.

        Checks:
        1. Quest references valid items (required_item, reward_item)
        2. Quest references valid creatures (quest_giver, quest_ender, required_npc_or_go)
        3. Spawns reference valid creatures/gameobjects
        4. SmartAI references valid creatures
        5. Quest chains are valid (prev_quest_id, next_quest_id exist)
        6. Duplicate entry IDs
        7. Missing required fields

        Returns:
            dict: {
                'valid': bool,
                'errors': list[str],     # Critical issues (missing FK, duplicate ID)
                'warnings': list[str],   # Non-critical (unused entities)
            }
        """
        errors = []
        warnings = []

        # Check quest item references
        for quest_entry, quest_data in self.entities['quests'].items():
            for item_entry, count in quest_data.get('required_item', []):
                if item_entry not in self.entities['items']:
                    errors.append(f"Quest {quest_entry} requires non-existent item {item_entry}")

            for item_entry, count in quest_data.get('reward_item', []):
                if item_entry not in self.entities['items']:
                    errors.append(f"Quest {quest_entry} rewards non-existent item {item_entry}")

        # Check quest creature references
        for quest_entry, quest_data in self.entities['quests'].items():
            giver = quest_data.get('quest_giver_entry')
            if giver and giver not in self.entities['npcs']:
                errors.append(f"Quest {quest_entry} giver {giver} does not exist")

            ender = quest_data.get('quest_ender_entry')
            if ender and ender not in self.entities['npcs']:
                errors.append(f"Quest {quest_entry} ender {ender} does not exist")

            for creature_entry, count in quest_data.get('required_npc_or_go', []):
                if creature_entry not in self.entities['creatures']:
                    errors.append(f"Quest {quest_entry} requires non-existent creature {creature_entry}")

        # Check spawn references
        for spawn_guid, spawn_data in self.entities['spawns'].items():
            entry = spawn_data['entry']
            if entry not in self.entities['creatures']:
                errors.append(f"Spawn {spawn_guid} references non-existent creature {entry}")

        # Check SmartAI references
        for creature_entry in self.smartai_builder.ai_scripts.keys():
            if creature_entry not in self.entities['creatures']:
                errors.append(f"SmartAI script for non-existent creature {creature_entry}")

        # Check for unused entities (warnings only)
        spawned_creatures = {spawn['entry'] for spawn in self.entities['spawns'].values()}
        for creature_entry in self.entities['creatures']:
            if creature_entry not in spawned_creatures:
                warnings.append(f"Creature {creature_entry} is defined but never spawned")

        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
        }
```

---

## 4. SQL Output Format

### 4.1 Statement Formatting

```python
class BaseBuilder:
    def format_insert(self, table, columns, values):
        """
        Generate INSERT with explicit column names and proper escaping.

        Example output:
        -- Item: Gladiator's Coin (90001)
        INSERT INTO `item_template` (`entry`, `name`, `class`, `subclass`, `Quality`,
                                      `ItemLevel`, `RequiredLevel`, `stat_type1`, `stat_value1`)
        VALUES
        (90001, 'Gladiator\'s Coin', 4, 0, 3, 50, 45, 4, 15);
        """
        # Add comment header
        comment = self._generate_comment(table, values)

        # Format INSERT
        lines = [comment]
        lines.append(f"INSERT INTO `{table}` ({', '.join(f'`{c}`' for c in columns)}) VALUES")

        # Format value rows
        value_rows = []
        for row in values:
            formatted = []
            for v in row:
                if v is None:
                    formatted.append('NULL')
                elif isinstance(v, str):
                    formatted.append(self.escape_sql_string(v))
                elif isinstance(v, (int, float)):
                    formatted.append(str(v))
                else:
                    formatted.append(self.escape_sql_string(str(v)))
            value_rows.append('(' + ', '.join(formatted) + ')')

        lines.append(',\n'.join(value_rows) + ';')
        lines.append('')  # Blank line separator
        return '\n'.join(lines)

    def _generate_comment(self, table, values):
        """Generate descriptive comment for SQL statement."""
        # Override in subclasses for table-specific comments
        return f"-- {table}"
```

### 4.2 Output Modes

```python
class SQLGenerator:
    def write_sql(self, output_path):
        """
        Write all SQL to a single monolithic file.

        File structure:
        1. Header comment (zone name, entry range, generation timestamp)
        2. Table-by-table sections with headers
        3. Foreign key dependency order (items -> creatures -> quests -> spawns)
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            # Header
            f.write(self._generate_header())
            f.write('\n\n')

            # Write tables in dependency order
            table_order = [
                # Base entity definitions
                'item_template', 'item_template_locale',
                'creature_template', 'creature_template_locale',
                'gameobject_template', 'gameobject_template_locale',

                # NPC data
                'npc_text', 'gossip_menu', 'gossip_menu_option',
                'npc_vendor',

                # Quests
                'quest_template', 'quest_template_addon',
                'quest_template_locale', 'quest_offer_reward_locale', 'quest_request_items_locale',
                'creature_queststarter', 'creature_questender',

                # AI
                'smart_scripts', 'conditions',

                # Spawns
                'creature', 'creature_addon',
                'gameobject',

                # Loot
                'creature_loot_template', 'gameobject_loot_template',
                'pickpocketing_loot_template', 'skinning_loot_template',

                # Pools
                'pool_template', 'pool_creature', 'pool_gameobject',

                # Instance/Dungeon
                'instance_template', 'access_requirement',
                'areatrigger_teleport', 'lfg_dungeon_template',

                # Events
                'game_event', 'game_event_creature', 'game_event_gameobject',

                # Zone registration
                'areatable_dbc',
            ]

            for table in table_order:
                if table in self.sql_buffers and self.sql_buffers[table]:
                    f.write(f"-- ============================================\n")
                    f.write(f"-- {table.upper()}\n")
                    f.write(f"-- ============================================\n\n")
                    for sql in self.sql_buffers[table]:
                        f.write(sql)
                        f.write('\n\n')

    def write_sql_split(self, output_dir):
        """
        Write SQL split by table name (one file per table).

        Useful for version control and selective application.
        """
        import os
        os.makedirs(output_dir, exist_ok=True)

        for table, statements in self.sql_buffers.items():
            if not statements:
                continue

            file_path = os.path.join(output_dir, f"{table}.sql")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self._generate_header())
                f.write(f"\n\n-- Table: {table}\n\n")
                for sql in statements:
                    f.write(sql)
                    f.write('\n\n')

    def _generate_header(self):
        """Generate SQL file header comment."""
        import datetime
        return f"""-- ============================================
-- PyWoWLib SQL Generator
-- Generated: {datetime.datetime.now().isoformat()}
-- Zone: {self.zone_id or 'Unknown'}
-- Map: {self.map_id or 'Unknown'}
-- Entry Range: {self.start_entry} - {self.current_entry - 1}
-- ============================================"""
```

---

## 5. AzerothCore Table Schemas

### 5.1 Item Tables

#### item_template
```sql
CREATE TABLE `item_template` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `class` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `subclass` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `SoundOverrideSubclass` tinyint(4) NOT NULL DEFAULT -1,
  `name` varchar(255) NOT NULL DEFAULT '',
  `displayid` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `Quality` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `Flags` int(10) unsigned NOT NULL DEFAULT 0,
  `FlagsExtra` int(10) unsigned NOT NULL DEFAULT 0,
  `BuyCount` tinyint(3) unsigned NOT NULL DEFAULT 1,
  `BuyPrice` bigint(20) NOT NULL DEFAULT 0,
  `SellPrice` int(10) unsigned NOT NULL DEFAULT 0,
  `InventoryType` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `AllowableClass` int(11) NOT NULL DEFAULT -1,
  `AllowableRace` int(11) NOT NULL DEFAULT -1,
  `ItemLevel` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RequiredLevel` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `RequiredSkill` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RequiredSkillRank` smallint(5) unsigned NOT NULL DEFAULT 0,
  `requiredspell` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `requiredhonorrank` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RequiredCityRank` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RequiredReputationFaction` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RequiredReputationRank` smallint(5) unsigned NOT NULL DEFAULT 0,
  `maxcount` int(11) NOT NULL DEFAULT 0,
  `stackable` int(11) DEFAULT 1,
  `ContainerSlots` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `StatsCount` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `stat_type1` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `stat_value1` smallint(6) NOT NULL DEFAULT 0,
  -- ... stat_type2-10, stat_value2-10
  `ScalingStatDistribution` smallint(6) NOT NULL DEFAULT 0,
  `ScalingStatValue` int(11) NOT NULL DEFAULT 0,
  `dmg_min1` float NOT NULL DEFAULT 0,
  `dmg_max1` float NOT NULL DEFAULT 0,
  `dmg_type1` tinyint(3) unsigned NOT NULL DEFAULT 0,
  -- ... dmg_min2-5, dmg_max2-5, dmg_type2-5
  `armor` smallint(5) unsigned NOT NULL DEFAULT 0,
  `holy_res` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `fire_res` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `nature_res` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `frost_res` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `shadow_res` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `arcane_res` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `delay` smallint(5) unsigned NOT NULL DEFAULT 0,
  `ammo_type` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `RangedModRange` float NOT NULL DEFAULT 0,
  `spellid_1` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `spelltrigger_1` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `spellcharges_1` smallint(6) NOT NULL DEFAULT 0,
  `spellppmRate_1` float NOT NULL DEFAULT 0,
  `spellcooldown_1` int(11) NOT NULL DEFAULT -1,
  `spellcategory_1` smallint(5) unsigned NOT NULL DEFAULT 0,
  `spellcategorycooldown_1` int(11) NOT NULL DEFAULT -1,
  -- ... spellid_2-5, spelltrigger_2-5, etc.
  `bonding` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `description` varchar(255) NOT NULL DEFAULT '',
  `PageText` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `LanguageID` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `PageMaterial` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `startquest` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `lockid` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `Material` tinyint(4) NOT NULL DEFAULT 0,
  `sheath` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `RandomProperty` mediumint(8) NOT NULL DEFAULT 0,
  `RandomSuffix` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `block` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `itemset` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `MaxDurability` smallint(5) unsigned NOT NULL DEFAULT 0,
  `area` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `Map` smallint(6) NOT NULL DEFAULT 0,
  `BagFamily` mediumint(8) NOT NULL DEFAULT 0,
  `TotemCategory` mediumint(8) NOT NULL DEFAULT 0,
  `socketColor_1` tinyint(4) NOT NULL DEFAULT 0,
  `socketContent_1` mediumint(8) NOT NULL DEFAULT 0,
  -- ... socketColor_2-3, socketContent_2-3
  `socketBonus` mediumint(8) NOT NULL DEFAULT 0,
  `GemProperties` mediumint(8) NOT NULL DEFAULT 0,
  `RequiredDisenchantSkill` smallint(6) NOT NULL DEFAULT -1,
  `ArmorDamageModifier` float NOT NULL DEFAULT 0,
  `duration` int(11) NOT NULL DEFAULT 0,
  `ItemLimitCategory` smallint(6) NOT NULL DEFAULT 0,
  `HolidayId` int(11) unsigned NOT NULL DEFAULT 0,
  `ScriptName` varchar(64) NOT NULL DEFAULT '',
  `DisenchantID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `FoodType` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `minMoneyLoot` int(10) unsigned NOT NULL DEFAULT 0,
  `maxMoneyLoot` int(10) unsigned NOT NULL DEFAULT 0,
  `flagsCustom` int(10) unsigned NOT NULL DEFAULT 0,
  `VerifiedBuild` smallint(6) DEFAULT 0,
  PRIMARY KEY (`entry`)
);
```

#### item_template_locale
```sql
CREATE TABLE `item_template_locale` (
  `ID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `locale` varchar(4) NOT NULL,
  `Name` text,
  `Description` text,
  PRIMARY KEY (`ID`, `locale`)
);
```

### 5.2 Creature Tables

#### creature_template
```sql
CREATE TABLE `creature_template` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `difficulty_entry_1` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `difficulty_entry_2` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `difficulty_entry_3` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `KillCredit1` int(10) unsigned NOT NULL DEFAULT 0,
  `KillCredit2` int(10) unsigned NOT NULL DEFAULT 0,
  `modelid1` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `modelid2` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `modelid3` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `modelid4` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `name` char(100) NOT NULL DEFAULT '',
  `subname` char(100) DEFAULT NULL,
  `IconName` char(100) DEFAULT NULL,
  `gossip_menu_id` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `minlevel` tinyint(3) unsigned NOT NULL DEFAULT 1,
  `maxlevel` tinyint(3) unsigned NOT NULL DEFAULT 1,
  `exp` smallint(6) NOT NULL DEFAULT 0,
  `faction` smallint(5) unsigned NOT NULL DEFAULT 0,
  `npcflag` int(10) unsigned NOT NULL DEFAULT 0,
  `speed_walk` float NOT NULL DEFAULT 1,
  `speed_run` float NOT NULL DEFAULT 1.14286,
  `scale` float NOT NULL DEFAULT 1,
  `rank` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `dmgschool` tinyint(4) NOT NULL DEFAULT 0,
  `BaseAttackTime` int(10) unsigned NOT NULL DEFAULT 2000,
  `RangeAttackTime` int(10) unsigned NOT NULL DEFAULT 0,
  `BaseVariance` float NOT NULL DEFAULT 1,
  `RangeVariance` float NOT NULL DEFAULT 1,
  `unit_class` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `unit_flags` int(10) unsigned NOT NULL DEFAULT 0,
  `unit_flags2` int(10) unsigned NOT NULL DEFAULT 0,
  `dynamicflags` int(10) unsigned NOT NULL DEFAULT 0,
  `family` tinyint(4) NOT NULL DEFAULT 0,
  `trainer_type` tinyint(4) NOT NULL DEFAULT 0,
  `trainer_spell` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `trainer_class` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `trainer_race` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `type` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `type_flags` int(10) unsigned NOT NULL DEFAULT 0,
  `lootid` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `pickpocketloot` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `skinloot` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `resistance1` smallint(6) NOT NULL DEFAULT 0,
  `resistance2` smallint(6) NOT NULL DEFAULT 0,
  `resistance3` smallint(6) NOT NULL DEFAULT 0,
  `resistance4` smallint(6) NOT NULL DEFAULT 0,
  `resistance5` smallint(6) NOT NULL DEFAULT 0,
  `resistance6` smallint(6) NOT NULL DEFAULT 0,
  `spell1` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `spell2` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `spell3` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `spell4` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `spell5` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `spell6` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `spell7` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `spell8` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `PetSpellDataId` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `VehicleId` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `mingold` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `maxgold` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `AIName` char(64) NOT NULL DEFAULT '',
  `MovementType` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `InhabitType` tinyint(3) unsigned NOT NULL DEFAULT 3,
  `HoverHeight` float NOT NULL DEFAULT 1,
  `HealthModifier` float NOT NULL DEFAULT 1,
  `ManaModifier` float NOT NULL DEFAULT 1,
  `ArmorModifier` float NOT NULL DEFAULT 1,
  `DamageModifier` float NOT NULL DEFAULT 1,
  `ExperienceModifier` float NOT NULL DEFAULT 1,
  `RacialLeader` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `movementId` int(10) unsigned NOT NULL DEFAULT 0,
  `RegenHealth` tinyint(3) unsigned NOT NULL DEFAULT 1,
  `mechanic_immune_mask` int(10) unsigned NOT NULL DEFAULT 0,
  `flags_extra` int(10) unsigned NOT NULL DEFAULT 0,
  `ScriptName` char(64) NOT NULL DEFAULT '',
  `VerifiedBuild` smallint(6) DEFAULT 0,
  PRIMARY KEY (`entry`)
);
```

#### creature_template_locale
```sql
CREATE TABLE `creature_template_locale` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `locale` varchar(4) NOT NULL,
  `Name` text,
  `Title` text,
  PRIMARY KEY (`entry`, `locale`)
);
```

#### npc_text
```sql
CREATE TABLE `npc_text` (
  `ID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `text0_0` longtext,
  `text0_1` longtext,
  -- ... text1_0 through text7_1
  `BroadcastTextID0` mediumint(6) NOT NULL DEFAULT 0,
  `BroadcastTextID1` mediumint(6) NOT NULL DEFAULT 0,
  -- ... BroadcastTextID2-7
  `lang0` tinyint(3) unsigned NOT NULL DEFAULT 0,
  -- ... lang1-7
  `Probability0` float NOT NULL DEFAULT 0,
  -- ... Probability1-7
  `EmoteDelay0_0` smallint(5) unsigned NOT NULL DEFAULT 0,
  `Emote0_0` smallint(5) unsigned NOT NULL DEFAULT 0,
  -- ... EmoteDelay and Emote for 0_1-0_2, 1_0-1_2, etc.
  PRIMARY KEY (`ID`)
);
```

#### gossip_menu
```sql
CREATE TABLE `gossip_menu` (
  `MenuID` smallint(6) unsigned NOT NULL DEFAULT 0,
  `TextID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`MenuID`, `TextID`)
);
```

#### gossip_menu_option
```sql
CREATE TABLE `gossip_menu_option` (
  `MenuID` smallint(6) unsigned NOT NULL DEFAULT 0,
  `OptionID` smallint(6) unsigned NOT NULL DEFAULT 0,
  `OptionIcon` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `OptionText` text,
  `OptionBroadcastTextID` mediumint(6) NOT NULL DEFAULT 0,
  `OptionType` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `OptionNpcFlag` int(10) unsigned NOT NULL DEFAULT 0,
  `ActionMenuID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `ActionPoiID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `BoxCoded` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `BoxMoney` int(10) unsigned NOT NULL DEFAULT 0,
  `BoxText` text,
  `BoxBroadcastTextID` mediumint(6) NOT NULL DEFAULT 0,
  PRIMARY KEY (`MenuID`, `OptionID`)
);
```

#### npc_vendor
```sql
CREATE TABLE `npc_vendor` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `slot` smallint(6) NOT NULL DEFAULT 0,
  `item` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `maxcount` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `incrtime` int(10) unsigned NOT NULL DEFAULT 0,
  `ExtendedCost` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `VerifiedBuild` smallint(6) DEFAULT 0,
  PRIMARY KEY (`entry`, `item`)
);
```

### 5.3 Quest Tables

#### quest_template
```sql
CREATE TABLE `quest_template` (
  `ID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `QuestType` tinyint(3) unsigned NOT NULL DEFAULT 2,
  `QuestLevel` smallint(6) NOT NULL DEFAULT 1,
  `MinLevel` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `QuestSortID` smallint(6) NOT NULL DEFAULT 0,
  `QuestInfoID` smallint(5) unsigned NOT NULL DEFAULT 0,
  `SuggestedGroupNum` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `RequiredFactionId1` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RequiredFactionId2` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RequiredFactionValue1` mediumint(9) NOT NULL DEFAULT 0,
  `RequiredFactionValue2` mediumint(9) NOT NULL DEFAULT 0,
  `RewardNextQuest` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RewardXPDifficulty` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `RewardMoney` int(11) NOT NULL DEFAULT 0,
  `RewardBonusMoney` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RewardDisplaySpell` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RewardSpell` int(11) NOT NULL DEFAULT 0,
  `RewardHonor` int(11) NOT NULL DEFAULT 0,
  `RewardKillHonor` float NOT NULL DEFAULT 0,
  `StartItem` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `Flags` int(10) unsigned NOT NULL DEFAULT 0,
  `RequiredPlayerKills` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `RewardItem1` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RewardAmount1` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RewardItem2` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RewardAmount2` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RewardItem3` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RewardAmount3` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RewardItem4` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RewardAmount4` smallint(5) unsigned NOT NULL DEFAULT 0,
  `ItemDrop1` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `ItemDropQuantity1` smallint(5) unsigned NOT NULL DEFAULT 0,
  `ItemDrop2` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `ItemDropQuantity2` smallint(5) unsigned NOT NULL DEFAULT 0,
  `ItemDrop3` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `ItemDropQuantity3` smallint(5) unsigned NOT NULL DEFAULT 0,
  `ItemDrop4` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `ItemDropQuantity4` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RewardChoiceItemID1` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RewardChoiceItemQuantity1` smallint(5) unsigned NOT NULL DEFAULT 0,
  -- ... RewardChoiceItemID2-6, RewardChoiceItemQuantity2-6
  `POIContinent` smallint(5) unsigned NOT NULL DEFAULT 0,
  `POIx` float NOT NULL DEFAULT 0,
  `POIy` float NOT NULL DEFAULT 0,
  `POIPriority` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RewardTitle` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `RewardTalents` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `RewardArenaPoints` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RewardFactionID1` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RewardFactionValue1` mediumint(9) NOT NULL DEFAULT 0,
  `RewardFactionOverride1` mediumint(9) NOT NULL DEFAULT 0,
  -- ... RewardFactionID2-5, RewardFactionValue2-5, RewardFactionOverride2-5
  `TimeAllowed` int(10) unsigned NOT NULL DEFAULT 0,
  `AllowableRaces` smallint(5) unsigned NOT NULL DEFAULT 0,
  `LogTitle` text,
  `LogDescription` text,
  `QuestDescription` text,
  `AreaDescription` text,
  `QuestCompletionLog` text,
  `RequiredNpcOrGo1` mediumint(9) NOT NULL DEFAULT 0,
  `RequiredNpcOrGoCount1` smallint(5) unsigned NOT NULL DEFAULT 0,
  -- ... RequiredNpcOrGo2-4, RequiredNpcOrGoCount2-4
  `RequiredItemId1` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RequiredItemCount1` smallint(5) unsigned NOT NULL DEFAULT 0,
  -- ... RequiredItemId2-6, RequiredItemCount2-6
  `Unknown0` int(11) NOT NULL DEFAULT 0,
  `ObjectiveText1` text,
  `ObjectiveText2` text,
  `ObjectiveText3` text,
  `ObjectiveText4` text,
  `VerifiedBuild` smallint(6) DEFAULT 0,
  PRIMARY KEY (`ID`)
);
```

#### quest_template_addon
```sql
CREATE TABLE `quest_template_addon` (
  `ID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `MaxLevel` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `AllowableClasses` int(10) unsigned NOT NULL DEFAULT 0,
  `SourceSpellID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `PrevQuestID` mediumint(9) NOT NULL DEFAULT 0,
  `NextQuestID` mediumint(9) NOT NULL DEFAULT 0,
  `ExclusiveGroup` mediumint(9) NOT NULL DEFAULT 0,
  `RewardMailTemplateID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `RewardMailDelay` int(10) unsigned NOT NULL DEFAULT 0,
  `RequiredSkillID` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RequiredSkillPoints` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RequiredMinRepFaction` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RequiredMaxRepFaction` smallint(5) unsigned NOT NULL DEFAULT 0,
  `RequiredMinRepValue` mediumint(9) NOT NULL DEFAULT 0,
  `RequiredMaxRepValue` mediumint(9) NOT NULL DEFAULT 0,
  `ProvidedItemCount` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `SpecialFlags` tinyint(3) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`ID`)
);
```

#### quest_template_locale
```sql
CREATE TABLE `quest_template_locale` (
  `ID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `locale` varchar(4) NOT NULL,
  `Title` text,
  `Details` text,
  `Objectives` text,
  `EndText` text,
  `CompletedText` text,
  `ObjectiveText1` text,
  `ObjectiveText2` text,
  `ObjectiveText3` text,
  `ObjectiveText4` text,
  PRIMARY KEY (`ID`, `locale`)
);
```

#### quest_offer_reward_locale
```sql
CREATE TABLE `quest_offer_reward_locale` (
  `ID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `locale` varchar(4) NOT NULL,
  `RewardText` text,
  PRIMARY KEY (`ID`, `locale`)
);
```

#### quest_request_items_locale
```sql
CREATE TABLE `quest_request_items_locale` (
  `ID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `locale` varchar(4) NOT NULL,
  `CompletionText` text,
  PRIMARY KEY (`ID`, `locale`)
);
```

#### creature_queststarter
```sql
CREATE TABLE `creature_queststarter` (
  `id` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `quest` mediumint(8) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`, `quest`)
);
```

#### creature_questender
```sql
CREATE TABLE `creature_questender` (
  `id` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `quest` mediumint(8) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`, `quest`)
);
```

### 5.4 SmartAI Tables

#### smart_scripts
```sql
CREATE TABLE `smart_scripts` (
  `entryorguid` bigint(20) NOT NULL,
  `source_type` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `id` smallint(5) unsigned NOT NULL DEFAULT 0,
  `link` smallint(5) unsigned NOT NULL DEFAULT 0,
  `event_type` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `event_phase_mask` smallint(5) unsigned NOT NULL DEFAULT 0,
  `event_chance` tinyint(3) unsigned NOT NULL DEFAULT 100,
  `event_flags` smallint(5) unsigned NOT NULL DEFAULT 0,
  `event_param1` int(10) unsigned NOT NULL DEFAULT 0,
  `event_param2` int(10) unsigned NOT NULL DEFAULT 0,
  `event_param3` int(10) unsigned NOT NULL DEFAULT 0,
  `event_param4` int(10) unsigned NOT NULL DEFAULT 0,
  `event_param5` int(10) unsigned NOT NULL DEFAULT 0,
  `action_type` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `action_param1` int(10) unsigned NOT NULL DEFAULT 0,
  `action_param2` int(10) unsigned NOT NULL DEFAULT 0,
  `action_param3` int(10) unsigned NOT NULL DEFAULT 0,
  `action_param4` int(10) unsigned NOT NULL DEFAULT 0,
  `action_param5` int(10) unsigned NOT NULL DEFAULT 0,
  `action_param6` int(10) unsigned NOT NULL DEFAULT 0,
  `target_type` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `target_param1` int(10) unsigned NOT NULL DEFAULT 0,
  `target_param2` int(10) unsigned NOT NULL DEFAULT 0,
  `target_param3` int(10) unsigned NOT NULL DEFAULT 0,
  `target_param4` int(10) unsigned NOT NULL DEFAULT 0,
  `target_x` float NOT NULL DEFAULT 0,
  `target_y` float NOT NULL DEFAULT 0,
  `target_z` float NOT NULL DEFAULT 0,
  `target_o` float NOT NULL DEFAULT 0,
  `comment` text NOT NULL,
  PRIMARY KEY (`entryorguid`, `source_type`, `id`, `link`)
);
```

#### conditions
```sql
CREATE TABLE `conditions` (
  `SourceTypeOrReferenceId` mediumint(8) NOT NULL DEFAULT 0,
  `SourceGroup` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `SourceEntry` mediumint(8) NOT NULL DEFAULT 0,
  `SourceId` int(11) NOT NULL DEFAULT 0,
  `ElseGroup` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `ConditionTypeOrReference` mediumint(8) NOT NULL DEFAULT 0,
  `ConditionTarget` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `ConditionValue1` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `ConditionValue2` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `ConditionValue3` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `NegativeCondition` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `ErrorType` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `ErrorTextId` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `ScriptName` char(64) NOT NULL DEFAULT '',
  `Comment` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`SourceTypeOrReferenceId`, `SourceGroup`, `SourceEntry`, `SourceId`, `ElseGroup`, `ConditionTypeOrReference`, `ConditionTarget`, `ConditionValue1`, `ConditionValue2`, `ConditionValue3`)
);
```

### 5.5 Spawn Tables

#### creature
```sql
CREATE TABLE `creature` (
  `guid` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `id` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `map` smallint(5) unsigned NOT NULL DEFAULT 0,
  `zoneId` smallint(5) unsigned NOT NULL DEFAULT 0,
  `areaId` smallint(5) unsigned NOT NULL DEFAULT 0,
  `spawnMask` tinyint(3) unsigned NOT NULL DEFAULT 1,
  `phaseMask` int(10) unsigned NOT NULL DEFAULT 1,
  `modelid` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `equipment_id` tinyint(4) NOT NULL DEFAULT 0,
  `position_x` float NOT NULL DEFAULT 0,
  `position_y` float NOT NULL DEFAULT 0,
  `position_z` float NOT NULL DEFAULT 0,
  `orientation` float NOT NULL DEFAULT 0,
  `spawntimesecs` int(10) unsigned NOT NULL DEFAULT 120,
  `wander_distance` float NOT NULL DEFAULT 0,
  `currentwaypoint` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `curhealth` int(10) unsigned NOT NULL DEFAULT 1,
  `curmana` int(10) unsigned NOT NULL DEFAULT 0,
  `MovementType` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `npcflag` int(10) unsigned NOT NULL DEFAULT 0,
  `unit_flags` int(10) unsigned NOT NULL DEFAULT 0,
  `dynamicflags` int(10) unsigned NOT NULL DEFAULT 0,
  `ScriptName` char(64) NOT NULL DEFAULT '',
  `VerifiedBuild` smallint(6) DEFAULT 0,
  PRIMARY KEY (`guid`)
);
```

#### creature_addon
```sql
CREATE TABLE `creature_addon` (
  `guid` int(10) unsigned NOT NULL DEFAULT 0,
  `path_id` int(10) unsigned NOT NULL DEFAULT 0,
  `mount` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `bytes1` int(10) unsigned NOT NULL DEFAULT 0,
  `bytes2` int(10) unsigned NOT NULL DEFAULT 0,
  `emote` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `isLarge` tinyint(1) unsigned NOT NULL DEFAULT 0,
  `auras` text,
  PRIMARY KEY (`guid`)
);
```

#### gameobject
```sql
CREATE TABLE `gameobject` (
  `guid` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `id` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `map` smallint(5) unsigned NOT NULL DEFAULT 0,
  `zoneId` smallint(5) unsigned NOT NULL DEFAULT 0,
  `areaId` smallint(5) unsigned NOT NULL DEFAULT 0,
  `spawnMask` tinyint(3) unsigned NOT NULL DEFAULT 1,
  `phaseMask` int(10) unsigned NOT NULL DEFAULT 1,
  `position_x` float NOT NULL DEFAULT 0,
  `position_y` float NOT NULL DEFAULT 0,
  `position_z` float NOT NULL DEFAULT 0,
  `orientation` float NOT NULL DEFAULT 0,
  `rotation0` float NOT NULL DEFAULT 0,
  `rotation1` float NOT NULL DEFAULT 0,
  `rotation2` float NOT NULL DEFAULT 0,
  `rotation3` float NOT NULL DEFAULT 0,
  `spawntimesecs` int(11) NOT NULL DEFAULT 0,
  `animprogress` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `state` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `ScriptName` char(64) NOT NULL DEFAULT '',
  `VerifiedBuild` smallint(6) DEFAULT 0,
  PRIMARY KEY (`guid`)
);
```

### 5.6 Loot Tables

#### creature_loot_template
```sql
CREATE TABLE `creature_loot_template` (
  `Entry` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `Item` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `Reference` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `Chance` float NOT NULL DEFAULT 100,
  `QuestRequired` tinyint(1) NOT NULL DEFAULT 0,
  `LootMode` smallint(5) unsigned NOT NULL DEFAULT 1,
  `GroupId` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `MinCount` tinyint(3) unsigned NOT NULL DEFAULT 1,
  `MaxCount` tinyint(3) unsigned NOT NULL DEFAULT 1,
  `Comment` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`Entry`, `Item`)
);
```

### 5.7 Pool Tables

#### pool_template
```sql
CREATE TABLE `pool_template` (
  `entry` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `max_limit` int(10) unsigned NOT NULL DEFAULT 0,
  `description` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`entry`)
);
```

#### pool_creature
```sql
CREATE TABLE `pool_creature` (
  `guid` int(10) unsigned NOT NULL DEFAULT 0,
  `pool_entry` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `chance` float unsigned NOT NULL DEFAULT 0,
  `description` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`guid`)
);
```

#### pool_gameobject
```sql
CREATE TABLE `pool_gameobject` (
  `guid` int(10) unsigned NOT NULL DEFAULT 0,
  `pool_entry` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `chance` float unsigned NOT NULL DEFAULT 0,
  `description` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`guid`)
);
```

### 5.8 Instance/Dungeon Tables

#### instance_template
```sql
CREATE TABLE `instance_template` (
  `map` smallint(5) unsigned NOT NULL,
  `parent` smallint(5) unsigned NOT NULL,
  `script` varchar(128) NOT NULL DEFAULT '',
  `allowMount` tinyint(3) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`map`)
);
```

#### access_requirement
```sql
CREATE TABLE `access_requirement` (
  `mapId` mediumint(8) unsigned NOT NULL,
  `difficulty` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `level_min` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `level_max` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `item` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `item2` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `quest_done_A` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `quest_done_H` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `completed_achievement` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `quest_failed_text` text,
  `comment` text,
  PRIMARY KEY (`mapId`, `difficulty`)
);
```

#### areatrigger_teleport
```sql
CREATE TABLE `areatrigger_teleport` (
  `ID` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `Name` text,
  `target_map` smallint(5) unsigned NOT NULL DEFAULT 0,
  `target_position_x` float NOT NULL DEFAULT 0,
  `target_position_y` float NOT NULL DEFAULT 0,
  `target_position_z` float NOT NULL DEFAULT 0,
  `target_orientation` float NOT NULL DEFAULT 0,
  PRIMARY KEY (`ID`)
);
```

#### lfg_dungeon_template
```sql
CREATE TABLE `lfg_dungeon_template` (
  `dungeonId` int(10) unsigned NOT NULL DEFAULT 0,
  `name` varchar(255) DEFAULT NULL,
  `position_x` float NOT NULL DEFAULT 0,
  `position_y` float NOT NULL DEFAULT 0,
  `position_z` float NOT NULL DEFAULT 0,
  `orientation` float NOT NULL DEFAULT 0,
  `VerifiedBuild` smallint(6) DEFAULT 0,
  PRIMARY KEY (`dungeonId`)
);
```

### 5.9 Event Tables

#### game_event
```sql
CREATE TABLE `game_event` (
  `eventEntry` tinyint(3) unsigned NOT NULL,
  `start_time` timestamp NOT NULL DEFAULT '2000-01-01 00:00:00',
  `end_time` timestamp NOT NULL DEFAULT '2000-01-01 00:00:00',
  `occurence` bigint(20) unsigned NOT NULL DEFAULT 5184000,
  `length` bigint(20) unsigned NOT NULL DEFAULT 2592000,
  `holiday` mediumint(8) unsigned NOT NULL DEFAULT 0,
  `description` varchar(255) DEFAULT NULL,
  `world_event` tinyint(3) unsigned NOT NULL DEFAULT 0,
  `announce` tinyint(3) unsigned DEFAULT 2,
  PRIMARY KEY (`eventEntry`)
);
```

#### game_event_creature
```sql
CREATE TABLE `game_event_creature` (
  `eventEntry` tinyint(4) NOT NULL,
  `guid` int(10) unsigned NOT NULL,
  PRIMARY KEY (`guid`, `eventEntry`)
);
```

#### game_event_gameobject
```sql
CREATE TABLE `game_event_gameobject` (
  `eventEntry` tinyint(4) NOT NULL,
  `guid` int(10) unsigned NOT NULL,
  PRIMARY KEY (`guid`, `eventEntry`)
);
```

### 5.10 Zone Registration Table

#### areatable_dbc
```sql
CREATE TABLE `areatable_dbc` (
  `ID` int(10) unsigned NOT NULL,
  `MapID` int(10) unsigned NOT NULL DEFAULT 0,
  `ParentAreaID` int(10) unsigned NOT NULL DEFAULT 0,
  `AreaBit` int(10) unsigned NOT NULL DEFAULT 0,
  `Flags` int(10) unsigned NOT NULL DEFAULT 0,
  `SoundProviderPref` int(10) unsigned NOT NULL DEFAULT 0,
  `SoundProviderPrefUnderwater` int(10) unsigned NOT NULL DEFAULT 0,
  `AmbienceID` int(10) unsigned NOT NULL DEFAULT 0,
  `ZoneMusic` int(10) unsigned NOT NULL DEFAULT 0,
  `IntroSound` int(10) unsigned NOT NULL DEFAULT 0,
  `ExplorationLevel` int(10) unsigned NOT NULL DEFAULT 0,
  `AreaName_Lang_enUS` varchar(100) DEFAULT NULL,
  `AreaName_Lang_enGB` varchar(100) DEFAULT NULL,
  `AreaName_Lang_koKR` varchar(100) DEFAULT NULL,
  `AreaName_Lang_frFR` varchar(100) DEFAULT NULL,
  `AreaName_Lang_deDE` varchar(100) DEFAULT NULL,
  `AreaName_Lang_enCN` varchar(100) DEFAULT NULL,
  `AreaName_Lang_zhCN` varchar(100) DEFAULT NULL,
  `AreaName_Lang_enTW` varchar(100) DEFAULT NULL,
  `AreaName_Lang_zhTW` varchar(100) DEFAULT NULL,
  `AreaName_Lang_esES` varchar(100) DEFAULT NULL,
  `AreaName_Lang_esMX` varchar(100) DEFAULT NULL,
  `AreaName_Lang_ruRU` varchar(100) DEFAULT NULL,
  `AreaName_Lang_ptPT` varchar(100) DEFAULT NULL,
  `AreaName_Lang_ptBR` varchar(100) DEFAULT NULL,
  `AreaName_Lang_itIT` varchar(100) DEFAULT NULL,
  `AreaName_Lang_Unk` varchar(100) DEFAULT NULL,
  `AreaName_Lang_Mask` int(10) unsigned NOT NULL DEFAULT 0,
  `FactionGroupMask` int(10) unsigned NOT NULL DEFAULT 0,
  `LiquidTypeID1` int(10) unsigned NOT NULL DEFAULT 0,
  `LiquidTypeID2` int(10) unsigned NOT NULL DEFAULT 0,
  `LiquidTypeID3` int(10) unsigned NOT NULL DEFAULT 0,
  `LiquidTypeID4` int(10) unsigned NOT NULL DEFAULT 0,
  `MinElevation` float NOT NULL DEFAULT 0,
  `AmbientMultiplier` float NOT NULL DEFAULT 0,
  `LightID` int(10) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`ID`)
);
```

---

## 6. Tel'Abim Example Snippets

### 6.1 Item Example

```python
# Tel'Abim Gladiator's Coin (trinket)
item = {
    'entry': 90001,
    'name': "Gladiator's Coin",
    'class': 4,          # Armor
    'subclass': 0,       # Misc
    'inventory_type': 12, # Trinket
    'quality': 3,        # Rare (blue)
    'item_level': 50,
    'required_level': 45,
    'displayid': 37300,  # Coin model
    'buy_price': 0,
    'sell_price': 2500,
    'stackable': 1,
    'stats': [
        {'type': 4, 'value': 15},   # +15 Strength
        {'type': 45, 'value': 20},  # +20 Spell Power
    ],
    'spells': [
        {
            'id': 23723,           # Spell: Battle Trance (placeholder)
            'trigger': 0,          # Use
            'charges': 0,          # Unlimited
            'cooldown': 120000,    # 2 min cooldown
            'category_cooldown': 120000,
        },
    ],
    'description': 'Use: Increases attack power by 50 for 15 sec. (2 Min Cooldown)',
    'bonding': 1,  # Binds on pickup
}

# Expected SQL:
# INSERT INTO `item_template` (`entry`, `name`, `class`, `subclass`, `InventoryType`,
#                               `Quality`, `ItemLevel`, `RequiredLevel`, `displayid`,
#                               `BuyPrice`, `SellPrice`, `stackable`, `stat_type1`,
#                               `stat_value1`, `stat_type2`, `stat_value2`, `spellid_1`,
#                               `spelltrigger_1`, `spellcooldown_1`, `description`, `bonding`)
# VALUES
# (90001, 'Gladiator\'s Coin', 4, 0, 12, 3, 50, 45, 37300, 0, 2500, 1, 4, 15, 45, 20,
#  23723, 0, 120000, 'Use: Increases attack power by 50 for 15 sec. (2 Min Cooldown)', 1);
```

### 6.2 NPC Example

```python
# Captain Smoltz (quest giver at Mortuga docks)
npc = {
    'entry': 90050,
    'name': 'Captain Smoltz',
    'subname': 'Harbor Master',
    'modelid1': 4532,      # Human male model
    'minlevel': 55,
    'maxlevel': 55,
    'faction': 35,         # Friendly to all
    'npcflag': 2,          # Quest giver
    'type': 7,             # Humanoid
    'gossip_menu_id': 90001,
    'gossip_text': "Welcome to Mortuga, $N. The island is full of opportunity for a seasoned adventurer.",
    'health_modifier': 1.5,
    'ai_name': 'SmartAI',
}

# Expected SQL (creature_template):
# INSERT INTO `creature_template` (`entry`, `name`, `subname`, `modelid1`, `minlevel`,
#                                   `maxlevel`, `faction`, `npcflag`, `type`,
#                                   `gossip_menu_id`, `HealthModifier`, `AIName`)
# VALUES
# (90050, 'Captain Smoltz', 'Harbor Master', 4532, 55, 55, 35, 2, 7, 90001, 1.5, 'SmartAI');

# Expected SQL (npc_text):
# INSERT INTO `npc_text` (`ID`, `text0_0`, `BroadcastTextID0`, `lang0`, `Probability0`)
# VALUES
# (90001, 'Welcome to Mortuga, $N. The island is full of opportunity for a seasoned adventurer.', 0, 0, 1.0);

# Expected SQL (gossip_menu):
# INSERT INTO `gossip_menu` (`MenuID`, `TextID`)
# VALUES
# (90001, 90001);
```

### 6.3 Creature Example

```python
# Tel'Abim Gorilla (hostile beast, level 47-48)
creature = {
    'entry': 90060,
    'name': "Tel'Abim Gorilla",
    'modelid1': 3725,      # Gorilla model
    'minlevel': 47,
    'maxlevel': 48,
    'faction': 14,         # Monster (hostile)
    'type': 1,             # Beast
    'family': 9,           # Gorilla (hunter pet family)
    'rank': 0,             # Normal
    'damage_modifier': 1.1,
    'health_modifier': 1.0,
    'lootid': 90060,
    'skinloot': 0,
    'ai_name': 'SmartAI',
}

# Expected SQL:
# INSERT INTO `creature_template` (`entry`, `name`, `modelid1`, `minlevel`, `maxlevel`,
#                                   `faction`, `type`, `family`, `rank`, `DamageModifier`,
#                                   `HealthModifier`, `lootid`, `AIName`)
# VALUES
# (90060, 'Tel\'Abim Gorilla', 3725, 47, 48, 14, 1, 9, 0, 1.1, 1.0, 90060, 'SmartAI');
```

### 6.4 Quest Example

```python
# "Welcome to Mortuga" - intro quest
quest = {
    'entry': 90100,
    'title': 'Welcome to Mortuga',
    'log_description': "Speak with Captain Smoltz at the Mortuga docks.",
    'quest_description': "The island of Tel'Abim is a wild place, full of adventure and danger. "
                         "Captain Smoltz can point you in the right direction.",
    'offer_reward_text': "Ah, another adventurer! We can always use capable hands around here.",
    'request_items_text': "",
    'min_level': 45,
    'quest_level': 46,
    'quest_sort': 9001,      # Tel'Abim zone ID
    'quest_type': 2,         # Normal quest
    'quest_info': 0,         # No specific type
    'reward_xp': 5500,
    'reward_money': 15000,   # 1g 50s
    'reward_item': [
        (90001, 1),          # Gladiator's Coin x1
    ],
    'quest_giver_entry': 90050,  # Captain Smoltz
    'quest_ender_entry': 90050,
}

# Expected SQL (quest_template):
# INSERT INTO `quest_template` (`ID`, `LogTitle`, `LogDescription`, `QuestDescription`,
#                                `AreaDescription`, `MinLevel`, `QuestLevel`, `QuestSortID`,
#                                `QuestType`, `QuestInfoID`, `RewardXPDifficulty`, `RewardMoney`,
#                                `RewardItem1`, `RewardAmount1`)
# VALUES
# (90100, 'Welcome to Mortuga', 'Speak with Captain Smoltz at the Mortuga docks.',
#  'The island of Tel\'Abim is a wild place, full of adventure and danger. Captain Smoltz can point you in the right direction.',
#  'Ah, another adventurer! We can always use capable hands around here.',
#  45, 46, 9001, 2, 0, 0, 15000, 90001, 1);

# Expected SQL (creature_queststarter):
# INSERT INTO `creature_queststarter` (`id`, `quest`) VALUES (90050, 90100);

# Expected SQL (creature_questender):
# INSERT INTO `creature_questender` (`id`, `quest`) VALUES (90050, 90100);
```

### 6.5 SmartAI Example

```python
# Tel'Abim Gorilla abilities
creature_ai = {
    90060: {  # creature entry
        'name': "Tel'Abim Gorilla",
        'abilities': [
            {
                'event': 'combat',
                'spell_id': 11428,      # Thunderous Slam
                'min_repeat': 8000,     # 8 sec
                'max_repeat': 12000,    # 12 sec
                'target': 'victim',
                'comment': 'Cast Thunderous Slam on victim',
            },
            {
                'event': 'health_pct',
                'health_pct': 30,
                'spell_id': 19134,      # Frightening Shout
                'target': 'self',       # AoE centered on self
                'comment': 'Cast Frightening Shout at 30% health',
            },
        ],
    },
}

# Expected SQL (smart_scripts):
# -- Tel'Abim Gorilla (90060) - Combat abilities
# INSERT INTO `smart_scripts` (`entryorguid`, `source_type`, `id`, `link`, `event_type`,
#                               `event_phase_mask`, `event_chance`, `event_flags`,
#                               `event_param1`, `event_param2`, `event_param3`, `event_param4`,
#                               `action_type`, `action_param1`, `action_param2`, `action_param3`,
#                               `target_type`, `target_param1`, `comment`)
# VALUES
# -- Thunderous Slam on repeat
# (90060, 0, 0, 0, 0, 0, 100, 0, 8000, 12000, 8000, 12000, 11, 11428, 0, 0, 2, 0, 'Tel\'Abim Gorilla - In Combat - Cast Thunderous Slam'),
# -- Frightening Shout at 30% health
# (90060, 0, 1, 0, 2, 0, 100, 1, 0, 30, 0, 0, 11, 19134, 0, 0, 1, 0, 'Tel\'Abim Gorilla - Below 30% HP - Cast Frightening Shout');
```

### 6.6 Spawn Example

```python
# Creature spawns in Mortuga
spawns = [
    {
        'type': 'creature',
        'entry': 90050,          # Captain Smoltz
        'map': 1,                # Kalimdor (example, use actual Tel'Abim map ID)
        'zone': 9001,
        'area': 9001,
        'position': (-2500.5, 3200.3, 5.2, 1.57),  # x, y, z, o
        'spawntimesecs': 300,    # 5 min respawn
        'movement_type': 0,      # Idle
        'wander_distance': 0,
    },
    {
        'type': 'creature',
        'entry': 90060,          # Tel'Abim Gorilla
        'map': 1,
        'zone': 9001,
        'area': 9001,
        'position': (-2600.0, 3250.0, 10.5, 2.1),
        'spawntimesecs': 300,
        'movement_type': 1,      # Random
        'wander_distance': 10,
    },
]

# Expected SQL (creature):
# INSERT INTO `creature` (`guid`, `id`, `map`, `zoneId`, `areaId`, `position_x`,
#                         `position_y`, `position_z`, `orientation`, `spawntimesecs`,
#                         `wander_distance`, `MovementType`)
# VALUES
# (NULL, 90050, 1, 9001, 9001, -2500.5, 3200.3, 5.2, 1.57, 300, 0, 0),
# (NULL, 90060, 1, 9001, 9001, -2600.0, 3250.0, 10.5, 2.1, 300, 10, 1);
```

### 6.7 GameObject Spawn Example

```python
# Herb node spawns (reuse existing herb template)
go_spawns = [
    {
        'entry': 180165,         # Sungrass (existing template)
        'map': 1,
        'zone': 9001,
        'area': 9001,
        'position': (-2550.0, 3220.0, 8.0, 0),
        'rotation': (0, 0, 0, 1),
        'spawntimesecs': 300,
        'state': 1,              # Ready
        'pool_entry': None,
    },
]

# Expected SQL (gameobject):
# INSERT INTO `gameobject` (`guid`, `id`, `map`, `zoneId`, `areaId`, `position_x`,
#                           `position_y`, `position_z`, `orientation`, `rotation0`,
#                           `rotation1`, `rotation2`, `rotation3`, `spawntimesecs`, `state`)
# VALUES
# (NULL, 180165, 1, 9001, 9001, -2550.0, 3220.0, 8.0, 0, 0, 0, 0, 1, 300, 1);
```

### 6.8 Loot Example

```python
# Tel'Abim Gorilla loot
loot = {
    90060: [  # creature entry
        {'item': 4306, 'chance': 35.0, 'min': 1, 'max': 3, 'comment': 'Silk Cloth'},
        {'item': 90001, 'chance': 5.0, 'min': 1, 'max': 1, 'comment': "Gladiator's Coin (rare)"},
        {'item': 2589, 'chance': 15.0, 'min': 1, 'max': 2, 'comment': 'Linen Cloth'},
    ],
}

# Expected SQL (creature_loot_template):
# -- Tel'Abim Gorilla (90060) loot
# INSERT INTO `creature_loot_template` (`Entry`, `Item`, `Chance`, `QuestRequired`,
#                                        `MinCount`, `MaxCount`, `Comment`)
# VALUES
# (90060, 4306, 35.0, 0, 1, 3, 'Silk Cloth'),
# (90060, 90001, 5.0, 0, 1, 1, 'Gladiator\'s Coin (rare)'),
# (90060, 2589, 15.0, 0, 1, 2, 'Linen Cloth');
```

### 6.9 Dungeon DB Example

```python
# Tel'Abim Ruins (5-man dungeon)
dungeon = {
    'map_id': 1001,              # Custom map ID for dungeon
    'parent_map': 1,             # Kalimdor
    'script': 'instance_telabim_ruins',
    'allow_mount': 0,
    'access_requirement': {
        'level_min': 45,
        'level_max': 70,
        'item': 0,
        'quest_done_A': 90110,   # Alliance attunement quest
        'quest_done_H': 90111,   # Horde attunement quest
        'comment': 'Tel\'Abim Ruins attunement',
    },
    'areatrigger': {
        'id': 9001,
        'name': 'Tel\'Abim Ruins Entrance',
        'target_map': 1001,
        'target_position': (100.0, 200.0, 50.0, 0),
    },
    'lfg_entry': {
        'dungeon_id': 9001,
        'name': 'Tel\'Abim Ruins',
        'position': (100.0, 200.0, 50.0, 0),
    },
}

# Expected SQL (instance_template):
# INSERT INTO `instance_template` (`map`, `parent`, `script`, `allowMount`)
# VALUES
# (1001, 1, 'instance_telabim_ruins', 0);

# Expected SQL (access_requirement):
# INSERT INTO `access_requirement` (`mapId`, `difficulty`, `level_min`, `level_max`,
#                                    `quest_done_A`, `quest_done_H`, `comment`)
# VALUES
# (1001, 0, 45, 70, 90110, 90111, 'Tel\'Abim Ruins attunement');

# Expected SQL (areatrigger_teleport):
# INSERT INTO `areatrigger_teleport` (`ID`, `Name`, `target_map`, `target_position_x`,
#                                     `target_position_y`, `target_position_z`, `target_orientation`)
# VALUES
# (9001, 'Tel\'Abim Ruins Entrance', 1001, 100.0, 200.0, 50.0, 0);

# Expected SQL (lfg_dungeon_template):
# INSERT INTO `lfg_dungeon_template` (`dungeonId`, `name`, `position_x`, `position_y`,
#                                     `position_z`, `orientation`)
# VALUES
# (9001, 'Tel\'Abim Ruins', 100.0, 200.0, 50.0, 0);
```

### 6.10 World Event Example

```python
# "Mortuga Pirate Festival" - annual event
event = {
    'entry': 90,
    'start_time': '2024-09-01 00:00:00',
    'end_time': '2024-09-07 23:59:59',
    'occurence': 31536000,       # 365 days (annual)
    'length': 604800,            # 7 days
    'description': 'Mortuga Pirate Festival',
    'world_event': 1,
    'announce': 2,
    'creatures': [
        90070,  # Festival Vendor (spawns only during event)
        90071,  # Pirate Performer
    ],
    'gameobjects': [
        90500,  # Festival Decoration
    ],
}

# Expected SQL (game_event):
# INSERT INTO `game_event` (`eventEntry`, `start_time`, `end_time`, `occurence`, `length`,
#                            `description`, `world_event`, `announce`)
# VALUES
# (90, '2024-09-01 00:00:00', '2024-09-07 23:59:59', 31536000, 604800,
#  'Mortuga Pirate Festival', 1, 2);

# Expected SQL (game_event_creature):
# INSERT INTO `game_event_creature` (`eventEntry`, `guid`)
# VALUES
# (90, <guid_for_90070>),
# (90, <guid_for_90071>);

# Expected SQL (game_event_gameobject):
# INSERT INTO `game_event_gameobject` (`eventEntry`, `guid`)
# VALUES
# (90, <guid_for_90500>);
```

### 6.11 Translation Example

```python
# German translation for quest 90100
locale_data = {
    'quests': {
        90100: {
            'title': 'Willkommen in Mortuga',
            'description': 'Die Insel Tel\'Abim ist ein wilder Ort voller Abenteuer und Gefahren. '
                           'Kapitän Smoltz kann dich in die richtige Richtung weisen.',
            'objectives': 'Sprich mit Kapitän Smoltz an den Docks von Mortuga.',
            'offer_reward': 'Ah, ein weiterer Abenteurer! Wir können immer fähige Hände hier gebrauchen.',
        },
    },
    'items': {
        90001: {
            'name': 'Gladiatorenmünze',
            'description': 'Benutzen: Erhöht Angriffskraft um 50 für 15 Sek. (2 Min Abklingzeit)',
        },
    },
    'creatures': {
        90050: {
            'name': 'Kapitän Smoltz',
            'subname': 'Hafenmeister',
        },
    },
}

# Expected SQL (quest_template_locale):
# INSERT INTO `quest_template_locale` (`ID`, `locale`, `Title`, `Details`, `Objectives`)
# VALUES
# (90100, 'deDE', 'Willkommen in Mortuga',
#  'Die Insel Tel\'Abim ist ein wilder Ort voller Abenteuer und Gefahren. Kapitän Smoltz kann dich in die richtige Richtung weisen.',
#  'Sprich mit Kapitän Smoltz an den Docks von Mortuga.');

# Expected SQL (quest_offer_reward_locale):
# INSERT INTO `quest_offer_reward_locale` (`ID`, `locale`, `RewardText`)
# VALUES
# (90100, 'deDE', 'Ah, ein weiterer Abenteurer! Wir können immer fähige Hände hier gebrauchen.');

# Expected SQL (item_template_locale):
# INSERT INTO `item_template_locale` (`ID`, `locale`, `Name`, `Description`)
# VALUES
# (90001, 'deDE', 'Gladiatorenmünze',
#  'Benutzen: Erhöht Angriffskraft um 50 für 15 Sek. (2 Min Abklingzeit)');

# Expected SQL (creature_template_locale):
# INSERT INTO `creature_template_locale` (`entry`, `locale`, `Name`, `Title`)
# VALUES
# (90050, 'deDE', 'Kapitän Smoltz', 'Hafenmeister');
```

---

## 7. Testing Approach

### 7.1 SQL Syntax Validation

```python
# world_builder/tests/test_sql_generator.py

import sqlite3
import pytest
from world_builder.sql_generator import SQLGenerator


def test_sql_syntax_valid():
    """Test that generated SQL has valid syntax."""
    gen = SQLGenerator(start_entry=90000, map_id=1, zone_id=9001)

    # Add test data
    gen.add_items([{
        'name': 'Test Item',
        'class': 4,
        'subclass': 0,
        'inventory_type': 12,
        'quality': 3,
    }])

    # Write SQL to memory buffer
    import io
    output = io.StringIO()
    gen.write_sql(output.getvalue())
    sql = output.getvalue()

    # Parse with sqlite3 (basic syntax check)
    try:
        conn = sqlite3.connect(':memory:')
        # Create tables (simplified schema)
        conn.execute('CREATE TABLE item_template (entry INT, name TEXT, class INT, subclass INT)')
        # Execute generated SQL (adjusted for sqlite)
        conn.execute(sql.replace('`', '"'))
        conn.commit()
    except sqlite3.Error as e:
        pytest.fail(f"SQL syntax error: {e}")
```

### 7.2 Foreign Key Consistency Checks

```python
def test_quest_item_references():
    """Test that quests reference valid items."""
    gen = SQLGenerator(start_entry=90000)

    # Add item
    gen.add_items([{'entry': 90001, 'name': 'Test Item', 'class': 0}])

    # Add quest that references item
    gen.add_quests([{
        'entry': 90100,
        'title': 'Test Quest',
        'required_item': [(90001, 5)],  # Valid reference
        'reward_item': [(90002, 1)],     # INVALID reference (item 90002 doesn't exist)
    }])

    # Validate
    result = gen.validate()

    assert not result['valid']
    assert any('90002' in err for err in result['errors'])


def test_spawn_creature_references():
    """Test that spawns reference valid creatures."""
    gen = SQLGenerator(start_entry=90000, map_id=1)

    # Add creature
    gen.add_creatures([{'entry': 90050, 'name': 'Test NPC'}])

    # Add spawn referencing creature
    gen.add_spawns([{
        'entry': 90050,  # Valid
        'map': 1,
        'position': (0, 0, 0, 0),
    }])

    # Add spawn referencing non-existent creature
    gen.add_spawns([{
        'entry': 90999,  # INVALID
        'map': 1,
        'position': (0, 0, 0, 0),
    }])

    result = gen.validate()

    assert not result['valid']
    assert any('90999' in err for err in result['errors'])
```

### 7.3 Entry ID Uniqueness

```python
def test_duplicate_entry_ids():
    """Test that duplicate entry IDs are detected."""
    gen = SQLGenerator(start_entry=90000)

    # Add item with explicit entry
    gen.add_items([{'entry': 90001, 'name': 'Item A', 'class': 0}])

    # Add item with duplicate entry (should raise error)
    with pytest.raises(ValueError, match='Duplicate.*90001'):
        gen.add_items([{'entry': 90001, 'name': 'Item B', 'class': 0}])
```

### 7.4 Escaping and Injection Prevention

```python
def test_sql_string_escaping():
    """Test that strings with quotes/backslashes are escaped correctly."""
    gen = SQLGenerator(start_entry=90000)

    # Add item with single quotes and backslashes in name
    gen.add_items([{
        'entry': 90001,
        'name': "Captain's \"Special\" Coin\\Token",
        'description': "It's a \"special\" coin\\token",
        'class': 0,
    }])

    import io
    output = io.StringIO()
    gen.write_sql(output.getvalue())
    sql = output.getvalue()

    # Check that quotes are escaped
    assert "Captain''s" in sql or "Captain\\'s" in sql
    assert '\\"Special\\"' in sql or '""Special""' in sql
    assert '\\\\' in sql  # Backslash escaped
```

### 7.5 Complete Integration Test

```python
def test_complete_tel_abim_zone():
    """Integration test: Generate complete Tel'Abim zone SQL."""
    gen = SQLGenerator(start_entry=90000, map_id=1, zone_id=9001)

    # Add items
    gen.add_items([
        {'entry': 90001, 'name': "Gladiator's Coin", 'class': 4, 'subclass': 0},
    ])

    # Add NPCs
    gen.add_npcs([
        {'entry': 90050, 'name': 'Captain Smoltz', 'subname': 'Harbor Master',
         'minlevel': 55, 'maxlevel': 55},
    ])

    # Add creatures
    gen.add_creatures([
        {'entry': 90060, 'name': "Tel'Abim Gorilla", 'minlevel': 47, 'maxlevel': 48},
    ])

    # Add quests
    gen.add_quests([
        {'entry': 90100, 'title': 'Welcome to Mortuga',
         'quest_giver_entry': 90050, 'quest_ender_entry': 90050,
         'reward_item': [(90001, 1)]},
    ])

    # Add SmartAI
    gen.add_smartai({
        90060: {
            'abilities': [
                {'event': 'combat', 'spell_id': 11428, 'min_repeat': 8000,
                 'max_repeat': 12000, 'target': 'victim'},
            ],
        },
    })

    # Add spawns
    gen.add_spawns([
        {'entry': 90050, 'map': 1, 'position': (0, 0, 0, 0)},
        {'entry': 90060, 'map': 1, 'position': (10, 10, 0, 0)},
    ])

    # Validate
    result = gen.validate()
    assert result['valid'], f"Validation failed: {result['errors']}"

    # Write SQL
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False) as f:
        gen.write_sql(f.name)

        # Check file exists and has content
        import os
        assert os.path.exists(f.name)
        assert os.path.getsize(f.name) > 0

        # Basic content checks
        with open(f.name, 'r') as rf:
            content = rf.read()
            assert 'item_template' in content
            assert 'creature_template' in content
            assert 'quest_template' in content
            assert 'smart_scripts' in content
            assert 'creature' in content
            assert "Gladiator's Coin" in content
            assert 'Captain Smoltz' in content
```

---

## 8. Implementation Checklist

### Phase 1: Foundation (Priority 1)
- [ ] **1.1** Create `world_builder/sql_generator.py` module structure
- [ ] **1.2** Implement `SQLGenerator` core class with entry ID management
- [ ] **1.3** Implement `BaseBuilder` with SQL escaping and INSERT formatting
- [ ] **1.4** Add cross-reference tracking infrastructure (`entities` dict)
- [ ] **1.5** Implement `validate()` method for FK consistency checks
- [ ] **1.6** Implement `write_sql()` and `write_sql_split()` output methods
- [ ] **1.7** Add unit tests for SQL escaping and entry allocation

### Phase 2: Core Entity Builders (Priority 1)
- [ ] **2.1** Implement `ItemBuilder` with `item_template` schema
- [ ] **2.2** Implement `CreatureBuilder` with `creature_template` schema
- [ ] **2.3** Implement `NPCBuilder` (extends `CreatureBuilder` + gossip/vendor)
- [ ] **2.4** Implement `QuestBuilder` with `quest_template` + addon + relations
- [ ] **2.5** Add tests for item, creature, and quest generation
- [ ] **2.6** Validate FK references: quests → items, quests → creatures

### Phase 3: AI and Spawns (Priority 2)
- [ ] **3.1** Implement `SmartAIBuilder` with `smart_scripts` schema
- [ ] **3.2** Implement `SpawnBuilder` with `creature` + `creature_addon` schemas
- [ ] **3.3** Implement `GameObjectBuilder` with `gameobject` schema
- [ ] **3.4** Add SmartAI event/action type helpers (combat, health_pct, etc.)
- [ ] **3.5** Add tests for SmartAI generation
- [ ] **3.6** Validate FK references: spawns → creatures, AI → creatures

### Phase 4: Advanced Features (Priority 3)
- [ ] **4.1** Implement `DungeonBuilder` (instance_template, access_requirement, etc.)
- [ ] **4.2** Implement `EventBuilder` (game_event, game_event_creature, etc.)
- [ ] **4.3** Implement loot tables (creature_loot_template, GroupId support)
- [ ] **4.4** Implement pool system (pool_template, pool_creature, pool_gameobject)
- [ ] **4.5** Add tests for dungeon and event generation

### Phase 5: Localization (Priority 3)
- [ ] **5.1** Implement `LocaleBuilder` for all `*_locale` tables
- [ ] **5.2** Add helper methods for common locales (deDE, frFR, esES, etc.)
- [ ] **5.3** Validate locale consistency (all localized entries exist in base tables)
- [ ] **5.4** Add tests for German/French translations

### Phase 6: Zone Registration (Priority 2)
- [ ] **6.1** Implement `ZoneBuilder` for `areatable_dbc` server-side mirror
- [ ] **6.2** Add zone registration to `build_zone()` high-level API
- [ ] **6.3** Validate zone references in quests (quest_sort matches zone_id)

### Phase 7: Integration and Examples (Priority 1)
- [ ] **7.1** Create Tel'Abim complete example script (`examples/tel_abim_sql.py`)
- [ ] **7.2** Add integration test for complete zone generation
- [ ] **7.3** Add SQL syntax validation tests
- [ ] **7.4** Document high-level API in `world_builder/__init__.py`
- [ ] **7.5** Update README with SQL generation examples

### Phase 8: Documentation (Priority 4)
- [ ] **8.1** Document all table schemas in docstrings
- [ ] **8.2** Add AI agent usage examples for each builder
- [ ] **8.3** Create troubleshooting guide for FK validation errors
- [ ] **8.4** Add migration guide for existing tel-abim entity scripts

---

## 9. API Design Summary

### 9.1 High-Level API

```python
from world_builder.sql_generator import SQLGenerator

# Initialize generator
gen = SQLGenerator(start_entry=90000, map_id=1, zone_id=9001)

# Add entities (auto-allocate entry IDs if not provided)
gen.add_items(items_list)
gen.add_npcs(npcs_list)
gen.add_creatures(creatures_list)
gen.add_quests(quests_list)
gen.add_smartai(ai_definitions)
gen.add_spawns(spawn_list)
gen.add_gameobjects(go_list)
gen.add_dungeon_setup(dungeon_config)
gen.add_world_events(events_list)
gen.add_translations(locale_data, locale='deDE')

# Validate cross-references
result = gen.validate()
if not result['valid']:
    print("Errors:", result['errors'])
    print("Warnings:", result['warnings'])

# Write SQL
gen.write_sql('output/tel_abim.sql')           # Single file
gen.write_sql_split('output/sql/')             # Split by table
```

### 9.2 Builder-Specific APIs

```python
# Items
gen.item_builder.add_item({
    'entry': 90001,  # Optional, auto-allocated if omitted
    'name': 'Item Name',
    'class': 4,
    'subclass': 0,
    # ... see section 6.1 for full schema
})

# Quests
gen.quest_builder.add_quest({
    'entry': 90100,
    'title': 'Quest Title',
    'quest_giver_entry': 90050,
    'reward_item': [(90001, 1)],
    # ... see section 6.4 for full schema
})

# SmartAI
gen.smartai_builder.add_creature_ai(90060, {
    'name': 'Creature Name',
    'abilities': [
        {
            'event': 'combat',
            'spell_id': 11428,
            'min_repeat': 8000,
            'max_repeat': 12000,
            'target': 'victim',
        },
    ],
})

# Spawns
gen.spawn_builder.add_spawn({
    'entry': 90050,
    'map': 1,
    'position': (x, y, z, o),
    'spawntimesecs': 300,
    'movement_type': 1,
    'wander_distance': 10,
})
```

---

## 10. Design Notes

### 10.1 Why Self-Contained in pywowlib?

- **Headless compiler**: pywowlib becomes complete client + server solution
- **No external dependencies**: Pure Python, no SQLAlchemy/ORM overhead
- **Agent-friendly**: Single module, structured API, comprehensive validation
- **Version control**: Generated SQL can be committed alongside client files

### 10.2 Why Not Use tel-abim entity scripts?

tel-abim's `entities/` scripts are project-specific and Django-dependent. pywowlib should be framework-agnostic and reusable across projects.

However, tel-abim's entity definitions can serve as **input data** for this module:
```python
# tel-abim/scripts/generate_sql.py
from pywowlib.world_builder.sql_generator import SQLGenerator
from entities.item import ITEMS
from entities.npc import NPCS
from entities.quest import QUESTS

gen = SQLGenerator(start_entry=90000, map_id=1, zone_id=9001)
gen.add_items(ITEMS)
gen.add_npcs(NPCS)
gen.add_quests(QUESTS)
gen.write_sql('tel_abim.sql')
```

### 10.3 Entry ID Collision Prevention

```python
# Recommended entry ID allocation strategy:
# 90000-90999: Items
# 91000-91999: Creatures/NPCs
# 92000-92999: Quests
# 93000-93999: GameObjects
# 94000-94999: Spawns (GUIDs)
# 95000-95999: Events

gen = SQLGenerator(start_entry=90000)
gen.item_builder.start_entry = 90000
gen.creature_builder.start_entry = 91000
gen.quest_builder.start_entry = 92000
gen.gameobject_builder.start_entry = 93000
gen.spawn_builder.start_entry = 94000
gen.event_builder.start_entry = 95000
```

### 10.4 Extensibility

Future extensions can add:
- **spell_dbc generation** (custom spells for items/abilities)
- **creature_template_movement** (patrol paths, waypoints)
- **conditions** (complex quest/event conditions)
- **achievement** support
- **mail rewards** (delayed quest rewards)

---

## 11. Success Criteria

This plan is successful when:

1. **AI agents can generate complete zones** - All TODOs 1.5-4.2 are fully automatable
2. **Zero manual SQL editing** - Generated SQL is production-ready
3. **Validation catches all FK errors** - No broken references slip through
4. **Tel'Abim example works end-to-end** - Complete zone from Python → SQL → AzerothCore
5. **Tests pass 100%** - SQL syntax, FK consistency, escaping, integration
6. **Documentation is complete** - API docs, examples, troubleshooting guide

**Estimated effort**: 40-60 hours (spread across 8 phases)

**Dependencies**: None (pure Python, no external libraries)

**Risks**:
- AzerothCore schema changes (mitigation: version checks, schema validation)
- Complex SmartAI event types (mitigation: incremental support, helper methods)
- Performance with large datasets (mitigation: streaming SQL output, batch inserts)

---

## 12. Next Steps

1. **Review this plan** with project stakeholders
2. **Prioritize phases** based on immediate needs (e.g., Phase 1-2 for basic items/quests)
3. **Start Phase 1**: Foundation and core infrastructure
4. **Iterate**: Add builders incrementally, test with Tel'Abim data
5. **Deploy**: Integrate with tel-abim project, generate production SQL

---

**END OF PLAN**
