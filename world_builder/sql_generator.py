"""
SQL generator for AzerothCore 3.3.5a world database (acore_world).

Provides structured Python APIs for generating all server-side database entries
needed for a playable custom WoW WotLK zone: items, NPCs, creatures, quests,
SmartAI scripts, spawns, gameobjects, dungeon configuration, world events,
loot tables, spawn pools, and translations.

Target database: AzerothCore ``acore_world`` (build 12340, WotLK 3.3.5a).

Usage::

    from world_builder.sql_generator import SQLGenerator

    gen = SQLGenerator(start_entry=90000, map_id=1, zone_id=9001)
    gen.add_items([{'name': 'Test Sword', 'class': 2, 'subclass': 7}])
    gen.add_creatures([{'name': 'Test Beast', 'minlevel': 10, 'maxlevel': 12}])
    gen.write_sql('output.sql')

Philosophy: self-contained, dependency-free, pure Python SQL generation with
comprehensive validation and cross-referencing.
"""

import datetime
import os
import logging

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Table output ordering (FK dependency order)
# ---------------------------------------------------------------------------
_TABLE_ORDER = [
    # Base entity definitions
    'item_template', 'item_template_locale',
    'creature_template', 'creature_template_locale',
    'gameobject_template', 'gameobject_template_locale',

    # NPC data
    'npc_text', 'gossip_menu', 'gossip_menu_option',
    'npc_vendor',

    # Quests
    'quest_template', 'quest_template_addon',
    'quest_template_locale', 'quest_offer_reward_locale',
    'quest_request_items_locale',
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


# ---------------------------------------------------------------------------
# SmartAI event type constants
# ---------------------------------------------------------------------------
SMART_EVENT_UPDATE_IC = 0        # In Combat (repeat timer)
SMART_EVENT_UPDATE_OOC = 1       # Out of Combat (repeat timer)
SMART_EVENT_HEALTH_PCT = 2       # Health percentage
SMART_EVENT_MANA_PCT = 3         # Mana percentage
SMART_EVENT_AGGRO = 4            # On aggro
SMART_EVENT_KILL = 5             # On kill
SMART_EVENT_DEATH = 6            # On death
SMART_EVENT_EVADE = 7            # On evade
SMART_EVENT_SPELLHIT = 8        # On spell hit
SMART_EVENT_RANGE = 9            # Range check
SMART_EVENT_OOC_LOS = 10        # Out of combat LoS
SMART_EVENT_RESPAWN = 11         # On respawn
SMART_EVENT_IC_LOS = 23          # In combat LoS
SMART_EVENT_JUST_SUMMONED = 37   # Just summoned
SMART_EVENT_WAYPOINT_REACHED = 40  # Waypoint reached

SMART_ACTION_CAST = 11           # Cast spell
SMART_ACTION_THREAT_ALL_PCT = 32  # Modify threat
SMART_ACTION_FLEE = 47           # Flee for assist
SMART_ACTION_SET_EMOTE = 5       # Set emote state
SMART_ACTION_TALK = 1            # Say text

SMART_TARGET_SELF = 1            # Self
SMART_TARGET_VICTIM = 2          # Current victim
SMART_TARGET_HOSTILE_SECOND = 6  # Second on threat list
SMART_TARGET_RANDOM = 24         # Random player
SMART_TARGET_RANDOM_NOT_TOP = 25  # Random player not top threat

# Source type constants
SMART_SOURCE_CREATURE = 0
SMART_SOURCE_GAMEOBJECT = 1


# ===================================================================
# BaseBuilder
# ===================================================================

class BaseBuilder:
    """Base class for all table builders."""

    def __init__(self, generator):
        """
        Args:
            generator: Parent SQLGenerator instance.
        """
        self.gen = generator

    # ------------------------------------------------------------------
    # SQL helpers
    # ------------------------------------------------------------------

    @staticmethod
    def escape_sql_string(s):
        """
        Escape a string value for safe insertion into a SQL statement.

        Returns the string wrapped in single quotes with internal single
        quotes doubled and backslashes escaped. ``None`` returns ``'NULL'``
        (unquoted).
        """
        if s is None:
            return 'NULL'
        return "'" + str(s).replace("\\", "\\\\").replace("'", "''") + "'"

    def format_insert(self, table, columns, values, comment=None):
        """
        Format an INSERT statement with explicit column names.

        Args:
            table: Table name.
            columns: List of column name strings.
            values: List of value tuples (one tuple per row).
            comment: Optional SQL comment placed before the INSERT.

        Returns:
            str: Formatted INSERT statement.
        """
        lines = []
        if comment:
            lines.append(comment)

        col_list = ', '.join('`{}`'.format(c) for c in columns)
        lines.append('INSERT INTO `{}` ({}) VALUES'.format(table, col_list))

        value_rows = []
        for row in values:
            formatted = []
            for v in row:
                if v is None:
                    formatted.append('NULL')
                elif isinstance(v, str):
                    formatted.append(self.escape_sql_string(v))
                elif isinstance(v, float):
                    formatted.append(str(v))
                elif isinstance(v, int):
                    formatted.append(str(v))
                else:
                    formatted.append(self.escape_sql_string(str(v)))
            value_rows.append('(' + ', '.join(formatted) + ')')

        lines.append(',\n'.join(value_rows) + ';')
        lines.append('')  # blank line separator
        return '\n'.join(lines)

    def add_sql(self, table, sql):
        """Append a SQL statement string to the generator buffer for *table*."""
        if table not in self.gen.sql_buffers:
            self.gen.sql_buffers[table] = []
        self.gen.sql_buffers[table].append(sql)


# ===================================================================
# ItemBuilder
# ===================================================================

class ItemBuilder(BaseBuilder):
    """Generates ``item_template`` and ``item_template_locale`` SQL."""

    def add_item(self, item_def):
        """
        Add an item from a structured definition dict.

        Args:
            item_def: dict with keys matching the AzerothCore
                ``item_template`` schema.  Required: ``name``, ``class``.
                Optional: ``entry`` (auto-allocated if omitted),
                ``subclass``, ``inventory_type``, ``quality``,
                ``item_level``, ``required_level``, ``displayid``,
                ``buy_price``, ``sell_price``, ``stackable``, ``stats``
                (list of ``{type, value}``), ``spells`` (list of spell
                dicts), ``description``, ``bonding``, ``max_durability``,
                ``armor``, ``delay``, ``dmg_min1``, ``dmg_max1``,
                ``dmg_type1``, ``flags``, ``flags_extra``, ``material``,
                ``sheath``, ``max_count``, ``bag_family``,
                ``socket_color_1``, ``socket_content_1``, ``socket_bonus``,
                ``food_type``, ``start_quest``, ``lock_id``,
                ``random_property``, ``random_suffix``, ``block``,
                ``itemset``, ``area``, ``container_slots``, ``totem_category``,
                ``required_skill``, ``required_skill_rank``, ``ammo_type``,
                ``script_name``, ``disenchant_id``, ``required_disenchant_skill``,
                ``duration``, ``min_money_loot``, ``max_money_loot``.

        Returns:
            int: Allocated or explicit entry ID.
        """
        entry = item_def.get('entry')
        if entry is None:
            entry = self.gen.allocate_entry()

        # Register for cross-referencing
        self.gen.register_entity('items', entry, item_def)

        columns = ['entry', 'class', 'subclass', 'SoundOverrideSubclass',
                    'name', 'displayid', 'Quality', 'Flags', 'FlagsExtra',
                    'BuyCount', 'BuyPrice', 'SellPrice', 'InventoryType',
                    'AllowableClass', 'AllowableRace',
                    'ItemLevel', 'RequiredLevel',
                    'RequiredSkill', 'RequiredSkillRank',
                    'maxcount', 'stackable', 'ContainerSlots', 'StatsCount']

        stats = item_def.get('stats', [])
        stats_count = len(stats)

        # Add stat columns (up to 10 stats)
        for i in range(1, 11):
            columns.append('stat_type{}'.format(i))
            columns.append('stat_value{}'.format(i))

        columns.extend([
            'dmg_min1', 'dmg_max1', 'dmg_type1',
            'armor', 'delay', 'ammo_type',
            'spellid_1', 'spelltrigger_1', 'spellcharges_1',
            'spellppmRate_1', 'spellcooldown_1',
            'spellcategory_1', 'spellcategorycooldown_1',
            'spellid_2', 'spelltrigger_2', 'spellcharges_2',
            'spellppmRate_2', 'spellcooldown_2',
            'spellcategory_2', 'spellcategorycooldown_2',
            'spellid_3', 'spelltrigger_3', 'spellcharges_3',
            'spellppmRate_3', 'spellcooldown_3',
            'spellcategory_3', 'spellcategorycooldown_3',
            'spellid_4', 'spelltrigger_4', 'spellcharges_4',
            'spellppmRate_4', 'spellcooldown_4',
            'spellcategory_4', 'spellcategorycooldown_4',
            'spellid_5', 'spelltrigger_5', 'spellcharges_5',
            'spellppmRate_5', 'spellcooldown_5',
            'spellcategory_5', 'spellcategorycooldown_5',
            'bonding', 'description',
            'Material', 'sheath', 'block',
            'MaxDurability', 'area',
            'BagFamily', 'socketColor_1', 'socketContent_1',
            'socketColor_2', 'socketContent_2',
            'socketColor_3', 'socketContent_3',
            'socketBonus', 'startquest', 'lockid',
            'RandomProperty', 'RandomSuffix',
            'itemset', 'ContainerSlots',
            'RequiredDisenchantSkill', 'DisenchantID',
            'FoodType', 'duration',
            'minMoneyLoot', 'maxMoneyLoot',
            'ScriptName',
        ])

        # Build value row
        spells = item_def.get('spells', [])

        row = [
            entry,
            item_def.get('class', 0),
            item_def.get('subclass', 0),
            item_def.get('sound_override_subclass', -1),
            item_def.get('name', ''),
            item_def.get('displayid', 0),
            item_def.get('quality', 0),
            item_def.get('flags', 0),
            item_def.get('flags_extra', 0),
            item_def.get('buy_count', 1),
            item_def.get('buy_price', 0),
            item_def.get('sell_price', 0),
            item_def.get('inventory_type', 0),
            item_def.get('allowable_class', -1),
            item_def.get('allowable_race', -1),
            item_def.get('item_level', 0),
            item_def.get('required_level', 0),
            item_def.get('required_skill', 0),
            item_def.get('required_skill_rank', 0),
            item_def.get('max_count', 0),
            item_def.get('stackable', 1),
            item_def.get('container_slots', 0),
            stats_count,
        ]

        # Stats (10 slots)
        for i in range(10):
            if i < len(stats):
                row.append(stats[i].get('type', 0))
                row.append(stats[i].get('value', 0))
            else:
                row.append(0)
                row.append(0)

        # Damage
        row.append(item_def.get('dmg_min1', 0))
        row.append(item_def.get('dmg_max1', 0))
        row.append(item_def.get('dmg_type1', 0))

        # Armor, delay, ammo_type
        row.append(item_def.get('armor', 0))
        row.append(item_def.get('delay', 0))
        row.append(item_def.get('ammo_type', 0))

        # Spells (5 slots)
        for i in range(5):
            if i < len(spells):
                sp = spells[i]
                row.append(sp.get('id', 0))
                row.append(sp.get('trigger', 0))
                row.append(sp.get('charges', 0))
                row.append(sp.get('ppm_rate', 0))
                row.append(sp.get('cooldown', -1))
                row.append(sp.get('category', 0))
                row.append(sp.get('category_cooldown', -1))
            else:
                row.extend([0, 0, 0, 0, -1, 0, -1])

        # Bonding, description
        row.append(item_def.get('bonding', 0))
        row.append(item_def.get('description', ''))

        # Material, sheath, block
        row.append(item_def.get('material', 0))
        row.append(item_def.get('sheath', 0))
        row.append(item_def.get('block', 0))

        # MaxDurability, area
        row.append(item_def.get('max_durability', 0))
        row.append(item_def.get('area', 0))

        # BagFamily, sockets
        row.append(item_def.get('bag_family', 0))
        row.append(item_def.get('socket_color_1', 0))
        row.append(item_def.get('socket_content_1', 0))
        row.append(item_def.get('socket_color_2', 0))
        row.append(item_def.get('socket_content_2', 0))
        row.append(item_def.get('socket_color_3', 0))
        row.append(item_def.get('socket_content_3', 0))
        row.append(item_def.get('socket_bonus', 0))

        # startquest, lockid
        row.append(item_def.get('start_quest', 0))
        row.append(item_def.get('lock_id', 0))

        # RandomProperty, RandomSuffix
        row.append(item_def.get('random_property', 0))
        row.append(item_def.get('random_suffix', 0))

        # itemset, ContainerSlots (duplicate in schema but we keep it)
        row.append(item_def.get('itemset', 0))
        row.append(item_def.get('container_slots', 0))

        # RequiredDisenchantSkill, DisenchantID
        row.append(item_def.get('required_disenchant_skill', -1))
        row.append(item_def.get('disenchant_id', 0))

        # FoodType, duration
        row.append(item_def.get('food_type', 0))
        row.append(item_def.get('duration', 0))

        # minMoneyLoot, maxMoneyLoot
        row.append(item_def.get('min_money_loot', 0))
        row.append(item_def.get('max_money_loot', 0))

        # ScriptName
        row.append(item_def.get('script_name', ''))

        comment = '-- Item: {} ({})'.format(item_def.get('name', ''), entry)
        sql = self.format_insert('item_template', columns, [row], comment=comment)
        self.add_sql('item_template', sql)

        return entry


# ===================================================================
# CreatureBuilder
# ===================================================================

class CreatureBuilder(BaseBuilder):
    """Generates ``creature_template`` SQL."""

    def add_creature(self, creature_def):
        """
        Add a creature from a structured definition dict.

        Args:
            creature_def: dict with keys matching the AzerothCore
                ``creature_template`` schema.  Required: ``name``.
                Optional: ``entry`` (auto-allocated if omitted),
                ``modelid1``-``modelid4``, ``subname``, ``minlevel``,
                ``maxlevel``, ``faction``, ``npcflag``, ``type``,
                ``family``, ``rank``, ``health_modifier``,
                ``mana_modifier``, ``armor_modifier``,
                ``damage_modifier``, ``experience_modifier``,
                ``speed_walk``, ``speed_run``, ``scale``, ``unit_class``,
                ``unit_flags``, ``unit_flags2``, ``dynamicflags``,
                ``type_flags``, ``lootid``, ``pickpocketloot``,
                ``skinloot``, ``gossip_menu_id``, ``ai_name``,
                ``movement_type``, ``inhabit_type``, ``hover_height``,
                ``regen_health``, ``mechanic_immune_mask``,
                ``flags_extra``, ``script_name``,
                ``mingold``, ``maxgold``,
                ``resistance1``-``resistance6``,
                ``spell1``-``spell8``,
                ``trainer_type``, ``trainer_spell``, ``trainer_class``,
                ``trainer_race``, ``base_attack_time``,
                ``range_attack_time``.

        Returns:
            int: Allocated or explicit entry ID.
        """
        entry = creature_def.get('entry')
        if entry is None:
            entry = self.gen.allocate_entry()

        # Register for cross-referencing
        self.gen.register_entity('creatures', entry, creature_def)

        columns = [
            'entry', 'difficulty_entry_1', 'difficulty_entry_2',
            'difficulty_entry_3',
            'KillCredit1', 'KillCredit2',
            'modelid1', 'modelid2', 'modelid3', 'modelid4',
            'name', 'subname', 'IconName',
            'gossip_menu_id', 'minlevel', 'maxlevel',
            'exp', 'faction', 'npcflag',
            'speed_walk', 'speed_run', 'scale',
            'rank', 'dmgschool',
            'BaseAttackTime', 'RangeAttackTime',
            'BaseVariance', 'RangeVariance',
            'unit_class', 'unit_flags', 'unit_flags2', 'dynamicflags',
            'family',
            'trainer_type', 'trainer_spell', 'trainer_class', 'trainer_race',
            'type', 'type_flags',
            'lootid', 'pickpocketloot', 'skinloot',
            'resistance1', 'resistance2', 'resistance3',
            'resistance4', 'resistance5', 'resistance6',
            'spell1', 'spell2', 'spell3', 'spell4',
            'spell5', 'spell6', 'spell7', 'spell8',
            'PetSpellDataId', 'VehicleId',
            'mingold', 'maxgold',
            'AIName', 'MovementType',
            'InhabitType', 'HoverHeight',
            'HealthModifier', 'ManaModifier',
            'ArmorModifier', 'DamageModifier', 'ExperienceModifier',
            'RacialLeader', 'movementId',
            'RegenHealth', 'mechanic_immune_mask',
            'flags_extra', 'ScriptName',
        ]

        row = [
            entry,
            creature_def.get('difficulty_entry_1', 0),
            creature_def.get('difficulty_entry_2', 0),
            creature_def.get('difficulty_entry_3', 0),
            creature_def.get('kill_credit_1', 0),
            creature_def.get('kill_credit_2', 0),
            creature_def.get('modelid1', 0),
            creature_def.get('modelid2', 0),
            creature_def.get('modelid3', 0),
            creature_def.get('modelid4', 0),
            creature_def.get('name', ''),
            creature_def.get('subname', ''),
            creature_def.get('icon_name', ''),
            creature_def.get('gossip_menu_id', 0),
            creature_def.get('minlevel', 1),
            creature_def.get('maxlevel', 1),
            creature_def.get('exp', 0),
            creature_def.get('faction', 0),
            creature_def.get('npcflag', 0),
            creature_def.get('speed_walk', 1.0),
            creature_def.get('speed_run', 1.14286),
            creature_def.get('scale', 1.0),
            creature_def.get('rank', 0),
            creature_def.get('dmgschool', 0),
            creature_def.get('base_attack_time', 2000),
            creature_def.get('range_attack_time', 0),
            creature_def.get('base_variance', 1.0),
            creature_def.get('range_variance', 1.0),
            creature_def.get('unit_class', 0),
            creature_def.get('unit_flags', 0),
            creature_def.get('unit_flags2', 0),
            creature_def.get('dynamicflags', 0),
            creature_def.get('family', 0),
            creature_def.get('trainer_type', 0),
            creature_def.get('trainer_spell', 0),
            creature_def.get('trainer_class', 0),
            creature_def.get('trainer_race', 0),
            creature_def.get('type', 0),
            creature_def.get('type_flags', 0),
            creature_def.get('lootid', 0),
            creature_def.get('pickpocketloot', 0),
            creature_def.get('skinloot', 0),
            creature_def.get('resistance1', 0),
            creature_def.get('resistance2', 0),
            creature_def.get('resistance3', 0),
            creature_def.get('resistance4', 0),
            creature_def.get('resistance5', 0),
            creature_def.get('resistance6', 0),
            creature_def.get('spell1', 0),
            creature_def.get('spell2', 0),
            creature_def.get('spell3', 0),
            creature_def.get('spell4', 0),
            creature_def.get('spell5', 0),
            creature_def.get('spell6', 0),
            creature_def.get('spell7', 0),
            creature_def.get('spell8', 0),
            creature_def.get('pet_spell_data_id', 0),
            creature_def.get('vehicle_id', 0),
            creature_def.get('mingold', 0),
            creature_def.get('maxgold', 0),
            creature_def.get('ai_name', ''),
            creature_def.get('movement_type', 0),
            creature_def.get('inhabit_type', 3),
            creature_def.get('hover_height', 1.0),
            creature_def.get('health_modifier', 1.0),
            creature_def.get('mana_modifier', 1.0),
            creature_def.get('armor_modifier', 1.0),
            creature_def.get('damage_modifier', 1.0),
            creature_def.get('experience_modifier', 1.0),
            creature_def.get('racial_leader', 0),
            creature_def.get('movement_id', 0),
            creature_def.get('regen_health', 1),
            creature_def.get('mechanic_immune_mask', 0),
            creature_def.get('flags_extra', 0),
            creature_def.get('script_name', ''),
        ]

        comment = '-- Creature: {} ({})'.format(
            creature_def.get('name', ''), entry)
        sql = self.format_insert('creature_template', columns, [row],
                                 comment=comment)
        self.add_sql('creature_template', sql)

        return entry


# ===================================================================
# NPCBuilder
# ===================================================================

class NPCBuilder(BaseBuilder):
    """
    Generates NPC-related SQL: ``creature_template`` (via CreatureBuilder),
    plus ``npc_text``, ``gossip_menu``, ``gossip_menu_option``, and
    ``npc_vendor`` entries.
    """

    def add_npc(self, npc_def):
        """
        Add an NPC from a structured definition dict.

        This creates the ``creature_template`` row (delegating to
        CreatureBuilder) and optionally adds gossip/vendor data.

        Args:
            npc_def: dict -- same keys as CreatureBuilder plus:
                ``gossip_text`` (str), ``gossip_menu_id`` (int, auto if
                omitted), ``vendor_items`` (list of item entry ints or
                dicts with ``item``, ``maxcount``, ``incrtime``,
                ``extended_cost``).

        Returns:
            int: Allocated or explicit entry ID.
        """
        entry = npc_def.get('entry')
        if entry is None:
            entry = self.gen.allocate_entry()
            npc_def = dict(npc_def, entry=entry)
        else:
            npc_def = dict(npc_def)

        # Ensure npcflag includes quest-giver if not already set
        # (quest giver flag is 2). The caller can override this.

        # Register as NPC (for quest giver/ender validation)
        self.gen.register_entity('npcs', entry, npc_def)

        # Also register as creature
        self.gen.register_entity('creatures', entry, npc_def)

        # Build creature_template row via CreatureBuilder
        # We construct the row directly here to avoid double-registration
        creature_sql = self.gen.creature_builder._build_creature_sql(npc_def, entry)
        self.add_sql('creature_template', creature_sql)

        # Gossip text
        gossip_text = npc_def.get('gossip_text')
        gossip_menu_id = npc_def.get('gossip_menu_id', 0)

        if gossip_text and gossip_menu_id:
            text_id = gossip_menu_id  # use same ID for simplicity

            # npc_text entry
            npc_text_cols = ['ID', 'text0_0', 'BroadcastTextID0',
                             'lang0', 'Probability0']
            npc_text_row = [text_id, gossip_text, 0, 0, 1.0]
            sql = self.format_insert(
                'npc_text', npc_text_cols, [npc_text_row],
                comment='-- NPC Text: {} ({})'.format(
                    npc_def.get('name', ''), text_id))
            self.add_sql('npc_text', sql)

            # gossip_menu link
            gossip_cols = ['MenuID', 'TextID']
            gossip_row = [gossip_menu_id, text_id]
            sql = self.format_insert(
                'gossip_menu', gossip_cols, [gossip_row],
                comment='-- Gossip Menu: {} ({})'.format(
                    npc_def.get('name', ''), gossip_menu_id))
            self.add_sql('gossip_menu', sql)

        # Gossip menu options
        gossip_options = npc_def.get('gossip_options', [])
        if gossip_options and gossip_menu_id:
            opt_cols = ['MenuID', 'OptionID', 'OptionIcon', 'OptionText',
                        'OptionBroadcastTextID', 'OptionType', 'OptionNpcFlag',
                        'ActionMenuID', 'ActionPoiID', 'BoxCoded', 'BoxMoney',
                        'BoxText', 'BoxBroadcastTextID']
            opt_rows = []
            for idx, opt in enumerate(gossip_options):
                opt_rows.append([
                    gossip_menu_id,
                    opt.get('option_id', idx),
                    opt.get('icon', 0),
                    opt.get('text', ''),
                    opt.get('broadcast_text_id', 0),
                    opt.get('type', 0),
                    opt.get('npc_flag', 0),
                    opt.get('action_menu_id', 0),
                    opt.get('action_poi_id', 0),
                    opt.get('box_coded', 0),
                    opt.get('box_money', 0),
                    opt.get('box_text', ''),
                    opt.get('box_broadcast_text_id', 0),
                ])
            sql = self.format_insert(
                'gossip_menu_option', opt_cols, opt_rows,
                comment='-- Gossip Options: {} ({})'.format(
                    npc_def.get('name', ''), gossip_menu_id))
            self.add_sql('gossip_menu_option', sql)

        # Vendor items
        vendor_items = npc_def.get('vendor_items', [])
        if vendor_items:
            vendor_cols = ['entry', 'slot', 'item', 'maxcount', 'incrtime',
                           'ExtendedCost']
            vendor_rows = []
            for slot, vi in enumerate(vendor_items):
                if isinstance(vi, int):
                    vi = {'item': vi}
                vendor_rows.append([
                    entry,
                    slot,
                    vi.get('item', 0),
                    vi.get('maxcount', 0),
                    vi.get('incrtime', 0),
                    vi.get('extended_cost', 0),
                ])
            sql = self.format_insert(
                'npc_vendor', vendor_cols, vendor_rows,
                comment='-- Vendor: {} ({})'.format(
                    npc_def.get('name', ''), entry))
            self.add_sql('npc_vendor', sql)

        return entry


# ===================================================================
# QuestBuilder
# ===================================================================

class QuestBuilder(BaseBuilder):
    """
    Generates ``quest_template``, ``quest_template_addon``,
    ``creature_queststarter``, and ``creature_questender`` SQL.
    """

    def add_quest(self, quest_def):
        """
        Add a quest from a structured definition dict.

        Args:
            quest_def: dict with keys:
                ``entry`` (optional, auto), ``title``,
                ``log_description``, ``quest_description``,
                ``offer_reward_text``, ``request_items_text``,
                ``quest_completion_log``, ``area_description``,
                ``min_level``, ``quest_level``, ``quest_sort``,
                ``quest_type``, ``quest_info``, ``suggested_group``,
                ``flags``, ``reward_xp``, ``reward_money``,
                ``reward_bonus_money``, ``reward_honor``,
                ``reward_kill_honor``, ``start_item``,
                ``reward_item`` (list of ``(entry, count)``),
                ``reward_choice_item`` (list of ``(entry, count)``),
                ``required_item`` (list of ``(entry, count)``),
                ``required_npc_or_go`` (list of ``(entry, count)``),
                ``objective_text`` (list of up to 4 strings),
                ``quest_giver_entry``, ``quest_ender_entry``,
                ``prev_quest_id``, ``next_quest_id``,
                ``exclusive_group``, ``time_allowed``,
                ``allowable_races``, ``special_flags``,
                ``reward_title``, ``reward_talents``,
                ``reward_arena_points``,
                ``reward_faction`` (list of ``{id, value, override}``),
                ``poi_continent``, ``poi_x``, ``poi_y``, ``poi_priority``.

        Returns:
            int: Allocated or explicit entry ID.
        """
        entry = quest_def.get('entry')
        if entry is None:
            entry = self.gen.allocate_entry()

        # Register for cross-referencing
        self.gen.register_entity('quests', entry, quest_def)

        # --- quest_template ---
        reward_items = quest_def.get('reward_item', [])
        required_items = quest_def.get('required_item', [])
        required_npcs = quest_def.get('required_npc_or_go', [])
        reward_choice = quest_def.get('reward_choice_item', [])
        objectives = quest_def.get('objective_text', [])
        reward_factions = quest_def.get('reward_faction', [])

        columns = [
            'ID', 'QuestType', 'QuestLevel', 'MinLevel',
            'QuestSortID', 'QuestInfoID', 'SuggestedGroupNum',
            'RequiredFactionId1', 'RequiredFactionId2',
            'RequiredFactionValue1', 'RequiredFactionValue2',
            'RewardNextQuest', 'RewardXPDifficulty',
            'RewardMoney', 'RewardBonusMoney',
            'RewardDisplaySpell', 'RewardSpell',
            'RewardHonor', 'RewardKillHonor',
            'StartItem', 'Flags', 'RequiredPlayerKills',
        ]

        row = [
            entry,
            quest_def.get('quest_type', 2),
            quest_def.get('quest_level', 1),
            quest_def.get('min_level', 0),
            quest_def.get('quest_sort', 0),
            quest_def.get('quest_info', 0),
            quest_def.get('suggested_group', 0),
            quest_def.get('required_faction_id_1', 0),
            quest_def.get('required_faction_id_2', 0),
            quest_def.get('required_faction_value_1', 0),
            quest_def.get('required_faction_value_2', 0),
            quest_def.get('reward_next_quest', 0),
            quest_def.get('reward_xp_difficulty', 0),
            quest_def.get('reward_money', 0),
            quest_def.get('reward_bonus_money', 0),
            quest_def.get('reward_display_spell', 0),
            quest_def.get('reward_spell', 0),
            quest_def.get('reward_honor', 0),
            quest_def.get('reward_kill_honor', 0),
            quest_def.get('start_item', 0),
            quest_def.get('flags', 0),
            quest_def.get('required_player_kills', 0),
        ]

        # Reward items (up to 4)
        for i in range(1, 5):
            columns.append('RewardItem{}'.format(i))
            columns.append('RewardAmount{}'.format(i))
            if i - 1 < len(reward_items):
                item_entry, count = reward_items[i - 1]
                row.append(item_entry)
                row.append(count)
            else:
                row.append(0)
                row.append(0)

        # Item drops (up to 4)
        item_drops = quest_def.get('item_drop', [])
        for i in range(1, 5):
            columns.append('ItemDrop{}'.format(i))
            columns.append('ItemDropQuantity{}'.format(i))
            if i - 1 < len(item_drops):
                drop_entry, count = item_drops[i - 1]
                row.append(drop_entry)
                row.append(count)
            else:
                row.append(0)
                row.append(0)

        # Reward choice items (up to 6)
        for i in range(1, 7):
            columns.append('RewardChoiceItemID{}'.format(i))
            columns.append('RewardChoiceItemQuantity{}'.format(i))
            if i - 1 < len(reward_choice):
                choice_entry, count = reward_choice[i - 1]
                row.append(choice_entry)
                row.append(count)
            else:
                row.append(0)
                row.append(0)

        # POI
        columns.extend(['POIContinent', 'POIx', 'POIy', 'POIPriority'])
        row.extend([
            quest_def.get('poi_continent', 0),
            quest_def.get('poi_x', 0),
            quest_def.get('poi_y', 0),
            quest_def.get('poi_priority', 0),
        ])

        # RewardTitle, RewardTalents, RewardArenaPoints
        columns.extend(['RewardTitle', 'RewardTalents', 'RewardArenaPoints'])
        row.extend([
            quest_def.get('reward_title', 0),
            quest_def.get('reward_talents', 0),
            quest_def.get('reward_arena_points', 0),
        ])

        # Reward factions (up to 5)
        for i in range(1, 6):
            columns.append('RewardFactionID{}'.format(i))
            columns.append('RewardFactionValue{}'.format(i))
            columns.append('RewardFactionOverride{}'.format(i))
            if i - 1 < len(reward_factions):
                rf = reward_factions[i - 1]
                row.append(rf.get('id', 0))
                row.append(rf.get('value', 0))
                row.append(rf.get('override', 0))
            else:
                row.append(0)
                row.append(0)
                row.append(0)

        # TimeAllowed, AllowableRaces
        columns.extend(['TimeAllowed', 'AllowableRaces'])
        row.extend([
            quest_def.get('time_allowed', 0),
            quest_def.get('allowable_races', 0),
        ])

        # Text fields
        columns.extend([
            'LogTitle', 'LogDescription', 'QuestDescription',
            'AreaDescription', 'QuestCompletionLog',
        ])
        row.extend([
            quest_def.get('title', ''),
            quest_def.get('log_description', ''),
            quest_def.get('quest_description', ''),
            quest_def.get('area_description', ''),
            quest_def.get('quest_completion_log', ''),
        ])

        # Required NPCs/GOs (up to 4)
        for i in range(1, 5):
            columns.append('RequiredNpcOrGo{}'.format(i))
            columns.append('RequiredNpcOrGoCount{}'.format(i))
            if i - 1 < len(required_npcs):
                npc_entry, count = required_npcs[i - 1]
                row.append(npc_entry)
                row.append(count)
            else:
                row.append(0)
                row.append(0)

        # Required items (up to 6)
        for i in range(1, 7):
            columns.append('RequiredItemId{}'.format(i))
            columns.append('RequiredItemCount{}'.format(i))
            if i - 1 < len(required_items):
                item_entry, count = required_items[i - 1]
                row.append(item_entry)
                row.append(count)
            else:
                row.append(0)
                row.append(0)

        # Unknown0
        columns.append('Unknown0')
        row.append(0)

        # Objective texts (up to 4)
        for i in range(1, 5):
            columns.append('ObjectiveText{}'.format(i))
            if i - 1 < len(objectives):
                row.append(objectives[i - 1])
            else:
                row.append('')

        comment = '-- Quest: {} ({})'.format(
            quest_def.get('title', ''), entry)
        sql = self.format_insert('quest_template', columns, [row],
                                 comment=comment)
        self.add_sql('quest_template', sql)

        # --- quest_template_addon ---
        addon_cols = [
            'ID', 'MaxLevel', 'AllowableClasses',
            'SourceSpellID', 'PrevQuestID', 'NextQuestID',
            'ExclusiveGroup',
            'RewardMailTemplateID', 'RewardMailDelay',
            'RequiredSkillID', 'RequiredSkillPoints',
            'RequiredMinRepFaction', 'RequiredMaxRepFaction',
            'RequiredMinRepValue', 'RequiredMaxRepValue',
            'ProvidedItemCount', 'SpecialFlags',
        ]
        addon_row = [
            entry,
            quest_def.get('max_level', 0),
            quest_def.get('allowable_classes', 0),
            quest_def.get('source_spell_id', 0),
            quest_def.get('prev_quest_id', 0),
            quest_def.get('next_quest_id', 0),
            quest_def.get('exclusive_group', 0),
            quest_def.get('reward_mail_template_id', 0),
            quest_def.get('reward_mail_delay', 0),
            quest_def.get('required_skill_id', 0),
            quest_def.get('required_skill_points', 0),
            quest_def.get('required_min_rep_faction', 0),
            quest_def.get('required_max_rep_faction', 0),
            quest_def.get('required_min_rep_value', 0),
            quest_def.get('required_max_rep_value', 0),
            quest_def.get('provided_item_count', 0),
            quest_def.get('special_flags', 0),
        ]
        sql = self.format_insert('quest_template_addon', addon_cols,
                                 [addon_row])
        self.add_sql('quest_template_addon', sql)

        # --- creature_queststarter / creature_questender ---
        giver = quest_def.get('quest_giver_entry')
        if giver:
            sql = self.format_insert(
                'creature_queststarter',
                ['id', 'quest'], [[giver, entry]],
                comment='-- Quest starter: {} -> {}'.format(giver, entry))
            self.add_sql('creature_queststarter', sql)

        ender = quest_def.get('quest_ender_entry')
        if ender:
            sql = self.format_insert(
                'creature_questender',
                ['id', 'quest'], [[ender, entry]],
                comment='-- Quest ender: {} -> {}'.format(ender, entry))
            self.add_sql('creature_questender', sql)

        return entry


# ===================================================================
# SmartAIBuilder
# ===================================================================

class SmartAIBuilder(BaseBuilder):
    """
    Generates ``smart_scripts`` and ``conditions`` SQL for creature AI.

    Supports common event types (combat timer, health_pct, aggro, death,
    evade) and translates high-level ability definitions into the low-level
    SmartAI row format.
    """

    def __init__(self, generator):
        super().__init__(generator)
        self.ai_scripts = {}  # creature_entry -> list of ability dicts

    def add_creature_ai(self, creature_entry, ai_def):
        """
        Add SmartAI abilities for a creature.

        Args:
            creature_entry: Creature entry ID.
            ai_def: dict with keys:
                ``name`` (str): Creature name (for comments).
                ``abilities`` (list of dicts): Each ability dict has:
                    ``event``: 'combat'|'health_pct'|'mana_pct'|'aggro'|
                               'death'|'evade'|'kill'|'ooc'
                    ``spell_id``: Spell to cast (for ``action_type`` CAST).
                    ``min_repeat`` / ``max_repeat``: Timer in ms (for
                        'combat' / 'ooc').
                    ``health_pct`` / ``mana_pct``: Threshold percentage.
                    ``target``: 'self'|'victim'|'random'|'random_not_top'|
                                'hostile_second'
                    ``event_flags``: SmartAI event flags (default 0, set
                        to 1 for NOT_REPEATABLE where appropriate).
                    ``event_chance``: Chance 0-100 (default 100).
                    ``action_type``: Override action type (default CAST).
                    ``action_params``: Override action params as list.
                    ``comment``: Custom comment string.
        """
        self.ai_scripts[creature_entry] = ai_def

        name = ai_def.get('name', str(creature_entry))
        abilities = ai_def.get('abilities', [])

        rows = []
        for script_id, ability in enumerate(abilities):
            event = ability.get('event', 'combat')
            spell_id = ability.get('spell_id', 0)
            target = ability.get('target', 'victim')
            event_chance = ability.get('event_chance', 100)
            event_flags = ability.get('event_flags', 0)
            comment = ability.get('comment', '')

            # Resolve event type and params
            event_type, ep1, ep2, ep3, ep4 = self._resolve_event(
                event, ability)

            # Resolve action
            action_type = ability.get('action_type', SMART_ACTION_CAST)
            if ability.get('action_params'):
                ap = ability['action_params']
                ap1 = ap[0] if len(ap) > 0 else 0
                ap2 = ap[1] if len(ap) > 1 else 0
                ap3 = ap[2] if len(ap) > 2 else 0
                ap4 = ap[3] if len(ap) > 3 else 0
                ap5 = ap[4] if len(ap) > 4 else 0
                ap6 = ap[5] if len(ap) > 5 else 0
            else:
                # Default: cast spell
                ap1 = spell_id
                ap2 = 0
                ap3 = 0
                ap4 = 0
                ap5 = 0
                ap6 = 0

            # Resolve target type
            target_type = self._resolve_target(target)

            # Build comment
            if not comment:
                comment = '{} - {} - Cast {}'.format(
                    name, self._event_description(event, ability), spell_id)

            rows.append([
                creature_entry,   # entryorguid
                SMART_SOURCE_CREATURE,  # source_type
                script_id,        # id
                0,                # link
                event_type,       # event_type
                0,                # event_phase_mask
                event_chance,     # event_chance
                event_flags,      # event_flags
                ep1, ep2, ep3, ep4,  # event_param1-4
                0,                # event_param5
                action_type,      # action_type
                ap1, ap2, ap3, ap4, ap5, ap6,  # action_param1-6
                target_type,      # target_type
                0, 0, 0, 0,      # target_param1-4
                0.0, 0.0, 0.0, 0.0,  # target_x/y/z/o
                comment,          # comment
            ])

        if rows:
            columns = [
                'entryorguid', 'source_type', 'id', 'link',
                'event_type', 'event_phase_mask', 'event_chance',
                'event_flags',
                'event_param1', 'event_param2', 'event_param3',
                'event_param4', 'event_param5',
                'action_type',
                'action_param1', 'action_param2', 'action_param3',
                'action_param4', 'action_param5', 'action_param6',
                'target_type',
                'target_param1', 'target_param2', 'target_param3',
                'target_param4',
                'target_x', 'target_y', 'target_z', 'target_o',
                'comment',
            ]
            sql = self.format_insert(
                'smart_scripts', columns, rows,
                comment='-- {} ({}) - SmartAI'.format(name, creature_entry))
            self.add_sql('smart_scripts', sql)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_event(event, ability):
        """Map high-level event name to SmartAI event_type and params."""
        if event == 'combat':
            min_r = ability.get('min_repeat', 5000)
            max_r = ability.get('max_repeat', 10000)
            return (SMART_EVENT_UPDATE_IC, min_r, max_r, min_r, max_r)
        elif event == 'ooc':
            min_r = ability.get('min_repeat', 5000)
            max_r = ability.get('max_repeat', 10000)
            return (SMART_EVENT_UPDATE_OOC, min_r, max_r, min_r, max_r)
        elif event == 'health_pct':
            pct = ability.get('health_pct', 30)
            return (SMART_EVENT_HEALTH_PCT, 0, pct, 0, 0)
        elif event == 'mana_pct':
            pct = ability.get('mana_pct', 15)
            return (SMART_EVENT_MANA_PCT, 0, pct, 0, 0)
        elif event == 'aggro':
            return (SMART_EVENT_AGGRO, 0, 0, 0, 0)
        elif event == 'kill':
            return (SMART_EVENT_KILL, 0, 0, 0, 0)
        elif event == 'death':
            return (SMART_EVENT_DEATH, 0, 0, 0, 0)
        elif event == 'evade':
            return (SMART_EVENT_EVADE, 0, 0, 0, 0)
        else:
            # Unknown event -- default to in-combat timer
            log.warning("Unknown SmartAI event type: %s", event)
            return (SMART_EVENT_UPDATE_IC, 5000, 10000, 5000, 10000)

    @staticmethod
    def _resolve_target(target):
        """Map high-level target name to SmartAI target_type constant."""
        mapping = {
            'self': SMART_TARGET_SELF,
            'victim': SMART_TARGET_VICTIM,
            'hostile_second': SMART_TARGET_HOSTILE_SECOND,
            'random': SMART_TARGET_RANDOM,
            'random_not_top': SMART_TARGET_RANDOM_NOT_TOP,
        }
        return mapping.get(target, SMART_TARGET_VICTIM)

    @staticmethod
    def _event_description(event, ability):
        """Generate human-readable event description for comments."""
        if event == 'combat':
            return 'In Combat'
        elif event == 'ooc':
            return 'Out of Combat'
        elif event == 'health_pct':
            return 'Below {}% HP'.format(ability.get('health_pct', 30))
        elif event == 'mana_pct':
            return 'Below {}% Mana'.format(ability.get('mana_pct', 15))
        elif event == 'aggro':
            return 'On Aggro'
        elif event == 'kill':
            return 'On Kill'
        elif event == 'death':
            return 'On Death'
        elif event == 'evade':
            return 'On Evade'
        return event


# ===================================================================
# SpawnBuilder
# ===================================================================

class SpawnBuilder(BaseBuilder):
    """Generates ``creature`` (spawn) and ``creature_addon`` SQL."""

    def __init__(self, generator):
        super().__init__(generator)
        self._next_guid = 1  # auto-increment GUID counter

    def add_spawn(self, spawn_def):
        """
        Add a creature spawn from a structured definition dict.

        Args:
            spawn_def: dict with keys:
                ``entry``: Creature template entry ID (required).
                ``map``: Map ID (default: generator's map_id).
                ``zone``: Zone ID (default: generator's zone_id).
                ``area``: Area ID (default: zone).
                ``position``: Tuple of (x, y, z, orientation).
                ``spawntimesecs``: Respawn time in seconds (default 120).
                ``wander_distance``: Wander radius (default 0).
                ``movement_type``: 0=Idle, 1=Random, 2=Waypoint
                    (default 0).
                ``spawn_mask``: Spawn difficulty mask (default 1).
                ``phase_mask``: Phase mask (default 1).
                ``equipment_id``: Equipment template ID (default 0).
                ``model_id``: Override model (default 0 = use template).
                ``addon``: Optional dict for ``creature_addon`` with keys
                    ``path_id``, ``mount``, ``bytes1``, ``bytes2``,
                    ``emote``, ``is_large``, ``auras``.

        Returns:
            int: Assigned GUID for the spawn.
        """
        guid = self._next_guid
        self._next_guid += 1

        creature_entry = spawn_def.get('entry', 0)
        map_id = spawn_def.get('map', self.gen.map_id or 0)
        zone_id = spawn_def.get('zone', self.gen.zone_id or 0)
        area_id = spawn_def.get('area', zone_id)
        pos = spawn_def.get('position', (0, 0, 0, 0))

        # Register for cross-referencing
        self.gen.entities['spawns'][guid] = {
            'entry': creature_entry,
            'map': map_id,
            'guid': guid,
        }

        columns = [
            'guid', 'id', 'map', 'zoneId', 'areaId',
            'spawnMask', 'phaseMask', 'modelid', 'equipment_id',
            'position_x', 'position_y', 'position_z', 'orientation',
            'spawntimesecs', 'wander_distance', 'currentwaypoint',
            'curhealth', 'curmana',
            'MovementType', 'npcflag', 'unit_flags', 'dynamicflags',
            'ScriptName',
        ]

        row = [
            guid,
            creature_entry,
            map_id,
            zone_id,
            area_id,
            spawn_def.get('spawn_mask', 1),
            spawn_def.get('phase_mask', 1),
            spawn_def.get('model_id', 0),
            spawn_def.get('equipment_id', 0),
            pos[0], pos[1], pos[2],
            pos[3] if len(pos) > 3 else 0,
            spawn_def.get('spawntimesecs', 120),
            spawn_def.get('wander_distance', 0),
            0,   # currentwaypoint
            spawn_def.get('curhealth', 1),
            spawn_def.get('curmana', 0),
            spawn_def.get('movement_type', 0),
            spawn_def.get('npcflag', 0),
            spawn_def.get('unit_flags', 0),
            spawn_def.get('dynamicflags', 0),
            spawn_def.get('script_name', ''),
        ]

        comment = '-- Spawn: creature {} at ({}, {}, {})'.format(
            creature_entry, pos[0], pos[1], pos[2])
        sql = self.format_insert('creature', columns, [row], comment=comment)
        self.add_sql('creature', sql)

        # creature_addon (optional)
        addon = spawn_def.get('addon')
        if addon:
            addon_cols = ['guid', 'path_id', 'mount', 'bytes1', 'bytes2',
                          'emote', 'isLarge', 'auras']
            addon_row = [
                guid,
                addon.get('path_id', 0),
                addon.get('mount', 0),
                addon.get('bytes1', 0),
                addon.get('bytes2', 0),
                addon.get('emote', 0),
                addon.get('is_large', 0),
                addon.get('auras', ''),
            ]
            sql = self.format_insert('creature_addon', addon_cols,
                                     [addon_row])
            self.add_sql('creature_addon', sql)

        return guid


# ===================================================================
# GameObjectBuilder
# ===================================================================

class GameObjectBuilder(BaseBuilder):
    """
    Generates ``gameobject_template`` and ``gameobject`` (spawn) SQL.
    """

    def __init__(self, generator):
        super().__init__(generator)
        self._next_guid = 1  # auto-increment GUID counter

    def add_gameobject_template(self, go_def):
        """
        Add a gameobject template (``gameobject_template``).

        Args:
            go_def: dict with template fields including ``entry``,
                ``type``, ``displayId``, ``name``, ``size``, ``data0``
                through ``data23``, etc.

        Returns:
            int: Entry ID.
        """
        entry = go_def.get('entry')
        if entry is None:
            entry = self.gen.allocate_entry()

        self.gen.register_entity('gameobjects', entry, go_def)

        columns = ['entry', 'type', 'displayId', 'name', 'IconName',
                    'castBarCaption', 'unk1', 'size']

        row = [
            entry,
            go_def.get('type', 0),
            go_def.get('display_id', 0),
            go_def.get('name', ''),
            go_def.get('icon_name', ''),
            go_def.get('cast_bar_caption', ''),
            go_def.get('unk1', ''),
            go_def.get('size', 1.0),
        ]

        # Data fields (data0 - data23)
        for i in range(24):
            col_name = 'Data{}'.format(i)
            columns.append(col_name)
            row.append(go_def.get('data{}'.format(i), 0))

        columns.append('AIName')
        row.append(go_def.get('ai_name', ''))
        columns.append('ScriptName')
        row.append(go_def.get('script_name', ''))

        comment = '-- GameObject Template: {} ({})'.format(
            go_def.get('name', ''), entry)
        sql = self.format_insert('gameobject_template', columns, [row],
                                 comment=comment)
        self.add_sql('gameobject_template', sql)

        return entry

    def add_gameobject_spawn(self, spawn_def):
        """
        Add a gameobject spawn (``gameobject`` table).

        Args:
            spawn_def: dict with keys:
                ``entry``: Gameobject template entry (required).
                ``map``: Map ID.
                ``zone``: Zone ID.
                ``area``: Area ID.
                ``position``: Tuple of (x, y, z, orientation).
                ``rotation``: Tuple of (rot0, rot1, rot2, rot3).
                ``spawntimesecs``: Respawn time (default 120).
                ``animprogress``: Animation progress (default 0).
                ``state``: State (default 1).
                ``spawn_mask``: (default 1).
                ``phase_mask``: (default 1).

        Returns:
            int: Assigned GUID.
        """
        guid = self._next_guid
        self._next_guid += 1

        go_entry = spawn_def.get('entry', 0)
        map_id = spawn_def.get('map', self.gen.map_id or 0)
        zone_id = spawn_def.get('zone', self.gen.zone_id or 0)
        area_id = spawn_def.get('area', zone_id)
        pos = spawn_def.get('position', (0, 0, 0, 0))
        rot = spawn_def.get('rotation', (0, 0, 0, 1))

        self.gen.entities['go_spawns'][guid] = {
            'entry': go_entry,
            'map': map_id,
            'guid': guid,
        }

        columns = [
            'guid', 'id', 'map', 'zoneId', 'areaId',
            'spawnMask', 'phaseMask',
            'position_x', 'position_y', 'position_z', 'orientation',
            'rotation0', 'rotation1', 'rotation2', 'rotation3',
            'spawntimesecs', 'animprogress', 'state',
            'ScriptName',
        ]

        row = [
            guid,
            go_entry,
            map_id,
            zone_id,
            area_id,
            spawn_def.get('spawn_mask', 1),
            spawn_def.get('phase_mask', 1),
            pos[0], pos[1], pos[2],
            pos[3] if len(pos) > 3 else 0,
            rot[0] if len(rot) > 0 else 0,
            rot[1] if len(rot) > 1 else 0,
            rot[2] if len(rot) > 2 else 0,
            rot[3] if len(rot) > 3 else 1,
            spawn_def.get('spawntimesecs', 120),
            spawn_def.get('animprogress', 0),
            spawn_def.get('state', 1),
            spawn_def.get('script_name', ''),
        ]

        comment = '-- GO Spawn: {} at ({}, {}, {})'.format(
            go_entry, pos[0], pos[1], pos[2])
        sql = self.format_insert('gameobject', columns, [row], comment=comment)
        self.add_sql('gameobject', sql)

        return guid


# ===================================================================
# DungeonBuilder
# ===================================================================

class DungeonBuilder(BaseBuilder):
    """
    Generates dungeon/instance SQL: ``instance_template``,
    ``access_requirement``, ``areatrigger_teleport``,
    ``lfg_dungeon_template``.
    """

    def add_dungeon(self, dungeon_def):
        """
        Add a complete dungeon setup.

        Args:
            dungeon_def: dict with keys:
                ``map_id``: Instance map ID.
                ``parent_map``: Parent continent map (default 0).
                ``script``: Instance script name (default '').
                ``allow_mount``: Allow mounting (default 0).
                ``access_requirement``: Optional dict with
                    ``level_min``, ``level_max``, ``item``, ``item2``,
                    ``quest_done_A``, ``quest_done_H``,
                    ``completed_achievement``, ``quest_failed_text``,
                    ``comment``, ``difficulty`` (default 0).
                ``areatrigger``: Optional dict with ``id``, ``name``,
                    ``target_map``, ``target_position`` (x,y,z,o tuple).
                ``lfg_entry``: Optional dict with ``dungeon_id``,
                    ``name``, ``position`` (x,y,z,o tuple).
        """
        map_id = dungeon_def.get('map_id', 0)

        # instance_template
        inst_cols = ['map', 'parent', 'script', 'allowMount']
        inst_row = [
            map_id,
            dungeon_def.get('parent_map', 0),
            dungeon_def.get('script', ''),
            dungeon_def.get('allow_mount', 0),
        ]
        sql = self.format_insert(
            'instance_template', inst_cols, [inst_row],
            comment='-- Instance: map {}'.format(map_id))
        self.add_sql('instance_template', sql)

        # access_requirement
        access = dungeon_def.get('access_requirement')
        if access:
            acc_cols = ['mapId', 'difficulty', 'level_min', 'level_max',
                        'item', 'item2',
                        'quest_done_A', 'quest_done_H',
                        'completed_achievement',
                        'quest_failed_text', 'comment']
            acc_row = [
                map_id,
                access.get('difficulty', 0),
                access.get('level_min', 0),
                access.get('level_max', 0),
                access.get('item', 0),
                access.get('item2', 0),
                access.get('quest_done_A', 0),
                access.get('quest_done_H', 0),
                access.get('completed_achievement', 0),
                access.get('quest_failed_text', ''),
                access.get('comment', ''),
            ]
            sql = self.format_insert('access_requirement', acc_cols,
                                     [acc_row])
            self.add_sql('access_requirement', sql)

        # areatrigger_teleport
        at = dungeon_def.get('areatrigger')
        if at:
            pos = at.get('target_position', (0, 0, 0, 0))
            at_cols = ['ID', 'Name', 'target_map',
                       'target_position_x', 'target_position_y',
                       'target_position_z', 'target_orientation']
            at_row = [
                at.get('id', 0),
                at.get('name', ''),
                at.get('target_map', map_id),
                pos[0], pos[1], pos[2],
                pos[3] if len(pos) > 3 else 0,
            ]
            sql = self.format_insert('areatrigger_teleport', at_cols,
                                     [at_row])
            self.add_sql('areatrigger_teleport', sql)

        # lfg_dungeon_template
        lfg = dungeon_def.get('lfg_entry')
        if lfg:
            pos = lfg.get('position', (0, 0, 0, 0))
            lfg_cols = ['dungeonId', 'name',
                        'position_x', 'position_y',
                        'position_z', 'orientation']
            lfg_row = [
                lfg.get('dungeon_id', 0),
                lfg.get('name', ''),
                pos[0], pos[1], pos[2],
                pos[3] if len(pos) > 3 else 0,
            ]
            sql = self.format_insert('lfg_dungeon_template', lfg_cols,
                                     [lfg_row])
            self.add_sql('lfg_dungeon_template', sql)


# ===================================================================
# EventBuilder
# ===================================================================

class EventBuilder(BaseBuilder):
    """
    Generates ``game_event``, ``game_event_creature``, and
    ``game_event_gameobject`` SQL.
    """

    def add_event(self, event_def):
        """
        Add a world event.

        Args:
            event_def: dict with keys:
                ``entry``: Event entry ID.
                ``start_time``: Start timestamp string
                    (default '2000-01-01 00:00:00').
                ``end_time``: End timestamp string.
                ``occurence``: Repeat period in seconds.
                ``length``: Duration in seconds.
                ``holiday``: Holiday ID (default 0).
                ``description``: Event description.
                ``world_event``: World event flag (default 0).
                ``announce``: Announce flag (default 2).
                ``creatures``: List of creature spawn GUIDs to link.
                ``gameobjects``: List of GO spawn GUIDs to link.
        """
        entry = event_def.get('entry', 0)

        # game_event
        ev_cols = ['eventEntry', 'start_time', 'end_time', 'occurence',
                   'length', 'holiday', 'description', 'world_event',
                   'announce']
        ev_row = [
            entry,
            event_def.get('start_time', '2000-01-01 00:00:00'),
            event_def.get('end_time', '2000-01-01 00:00:00'),
            event_def.get('occurence', 5184000),
            event_def.get('length', 2592000),
            event_def.get('holiday', 0),
            event_def.get('description', ''),
            event_def.get('world_event', 0),
            event_def.get('announce', 2),
        ]
        sql = self.format_insert(
            'game_event', ev_cols, [ev_row],
            comment='-- Event: {} ({})'.format(
                event_def.get('description', ''), entry))
        self.add_sql('game_event', sql)

        # game_event_creature
        creature_guids = event_def.get('creatures', [])
        if creature_guids:
            rows = [[entry, g] for g in creature_guids]
            sql = self.format_insert(
                'game_event_creature',
                ['eventEntry', 'guid'], rows)
            self.add_sql('game_event_creature', sql)

        # game_event_gameobject
        go_guids = event_def.get('gameobjects', [])
        if go_guids:
            rows = [[entry, g] for g in go_guids]
            sql = self.format_insert(
                'game_event_gameobject',
                ['eventEntry', 'guid'], rows)
            self.add_sql('game_event_gameobject', sql)


# ===================================================================
# LocaleBuilder
# ===================================================================

class LocaleBuilder(BaseBuilder):
    """
    Generates locale/translation SQL for ``item_template_locale``,
    ``creature_template_locale``, ``quest_template_locale``,
    ``quest_offer_reward_locale``, ``quest_request_items_locale``,
    and ``gameobject_template_locale``.
    """

    def add_translations(self, locale_data, locale='deDE'):
        """
        Add translations for multiple entity types.

        Args:
            locale_data: dict with optional keys ``items``, ``creatures``,
                ``quests``, ``gameobjects``. Each maps entry ID to a dict
                of translated fields:
                - items: ``name``, ``description``
                - creatures: ``name``, ``subname``
                - quests: ``title``, ``description``, ``objectives``,
                    ``end_text``, ``completed_text``,
                    ``objective_text1``-``objective_text4``,
                    ``offer_reward``, ``request_items``
                - gameobjects: ``name``
            locale: Locale code (e.g. 'deDE', 'frFR', 'esES').
        """
        # Items
        for entry, data in locale_data.get('items', {}).items():
            cols = ['ID', 'locale', 'Name', 'Description']
            row = [
                entry,
                locale,
                data.get('name', ''),
                data.get('description', ''),
            ]
            sql = self.format_insert('item_template_locale', cols, [row])
            self.add_sql('item_template_locale', sql)

        # Creatures
        for entry, data in locale_data.get('creatures', {}).items():
            cols = ['entry', 'locale', 'Name', 'Title']
            row = [
                entry,
                locale,
                data.get('name', ''),
                data.get('subname', ''),
            ]
            sql = self.format_insert('creature_template_locale', cols, [row])
            self.add_sql('creature_template_locale', sql)

        # Quests
        for entry, data in locale_data.get('quests', {}).items():
            # quest_template_locale
            qt_cols = ['ID', 'locale', 'Title', 'Details', 'Objectives',
                       'EndText', 'CompletedText',
                       'ObjectiveText1', 'ObjectiveText2',
                       'ObjectiveText3', 'ObjectiveText4']
            qt_row = [
                entry,
                locale,
                data.get('title', ''),
                data.get('description', ''),
                data.get('objectives', ''),
                data.get('end_text', ''),
                data.get('completed_text', ''),
                data.get('objective_text1', ''),
                data.get('objective_text2', ''),
                data.get('objective_text3', ''),
                data.get('objective_text4', ''),
            ]
            sql = self.format_insert('quest_template_locale', qt_cols,
                                     [qt_row])
            self.add_sql('quest_template_locale', sql)

            # quest_offer_reward_locale (if present)
            offer_reward = data.get('offer_reward')
            if offer_reward:
                sql = self.format_insert(
                    'quest_offer_reward_locale',
                    ['ID', 'locale', 'RewardText'],
                    [[entry, locale, offer_reward]])
                self.add_sql('quest_offer_reward_locale', sql)

            # quest_request_items_locale (if present)
            request_items = data.get('request_items')
            if request_items:
                sql = self.format_insert(
                    'quest_request_items_locale',
                    ['ID', 'locale', 'CompletionText'],
                    [[entry, locale, request_items]])
                self.add_sql('quest_request_items_locale', sql)

        # Gameobjects
        for entry, data in locale_data.get('gameobjects', {}).items():
            cols = ['entry', 'locale', 'name']
            row = [entry, locale, data.get('name', '')]
            sql = self.format_insert('gameobject_template_locale', cols, [row])
            self.add_sql('gameobject_template_locale', sql)


# ===================================================================
# ZoneBuilder
# ===================================================================

class ZoneBuilder(BaseBuilder):
    """Generates ``areatable_dbc`` SQL for server-side zone registration."""

    def add_zone(self, zone_def):
        """
        Register a zone in the server-side ``areatable_dbc`` table.

        Args:
            zone_def: dict with keys:
                ``id``: Zone/area ID.
                ``map_id``: Map ID.
                ``parent_area_id``: Parent area (default 0).
                ``area_bit``: Area bit (default 0).
                ``flags``: Area flags (default 0).
                ``exploration_level``: Exploration level (default 0).
                ``name``: Zone name (enUS).
                ``faction_group_mask``: Faction mask (default 0).
                ``ambient_multiplier``: Ambient light (default 0).
                ``light_id``: Light ID (default 0).
        """
        zone_id = zone_def.get('id', 0)

        columns = [
            'ID', 'MapID', 'ParentAreaID', 'AreaBit', 'Flags',
            'SoundProviderPref', 'SoundProviderPrefUnderwater',
            'AmbienceID', 'ZoneMusic', 'IntroSound', 'ExplorationLevel',
            'AreaName_Lang_enUS',
            'AreaName_Lang_enGB', 'AreaName_Lang_koKR',
            'AreaName_Lang_frFR', 'AreaName_Lang_deDE',
            'AreaName_Lang_enCN', 'AreaName_Lang_zhCN',
            'AreaName_Lang_enTW', 'AreaName_Lang_zhTW',
            'AreaName_Lang_esES', 'AreaName_Lang_esMX',
            'AreaName_Lang_ruRU', 'AreaName_Lang_ptPT',
            'AreaName_Lang_ptBR', 'AreaName_Lang_itIT',
            'AreaName_Lang_Unk',
            'AreaName_Lang_Mask',
            'FactionGroupMask',
            'LiquidTypeID1', 'LiquidTypeID2',
            'LiquidTypeID3', 'LiquidTypeID4',
            'MinElevation', 'AmbientMultiplier', 'LightID',
        ]

        name = zone_def.get('name', '')

        row = [
            zone_id,
            zone_def.get('map_id', 0),
            zone_def.get('parent_area_id', 0),
            zone_def.get('area_bit', 0),
            zone_def.get('flags', 0),
            zone_def.get('sound_provider_pref', 0),
            zone_def.get('sound_provider_pref_underwater', 0),
            zone_def.get('ambience_id', 0),
            zone_def.get('zone_music', 0),
            zone_def.get('intro_sound', 0),
            zone_def.get('exploration_level', 0),
            name,   # enUS
            '',     # enGB
            '',     # koKR
            '',     # frFR
            '',     # deDE
            '',     # enCN
            '',     # zhCN
            '',     # enTW
            '',     # zhTW
            '',     # esES
            '',     # esMX
            '',     # ruRU
            '',     # ptPT
            '',     # ptBR
            '',     # itIT
            '',     # Unk
            0xFFFFFFFF if name else 0,  # Mask
            zone_def.get('faction_group_mask', 0),
            zone_def.get('liquid_type_id_1', 0),
            zone_def.get('liquid_type_id_2', 0),
            zone_def.get('liquid_type_id_3', 0),
            zone_def.get('liquid_type_id_4', 0),
            zone_def.get('min_elevation', 0.0),
            zone_def.get('ambient_multiplier', 0.0),
            zone_def.get('light_id', 0),
        ]

        comment = '-- Zone: {} ({})'.format(name, zone_id)
        sql = self.format_insert('areatable_dbc', columns, [row],
                                 comment=comment)
        self.add_sql('areatable_dbc', sql)


# ===================================================================
# Loot helpers (used by SQLGenerator convenience methods)
# ===================================================================

class _LootHelper(BaseBuilder):
    """Internal helper for generating loot table SQL."""

    def add_loot(self, table, loot_entry, loot_items):
        """
        Add loot entries for a specific loot table.

        Args:
            table: Table name ('creature_loot_template',
                'gameobject_loot_template', 'pickpocketing_loot_template',
                'skinning_loot_template').
            loot_entry: Entry ID for the loot table (usually creature
                entry).
            loot_items: List of dicts with keys: ``item``, ``chance``,
                ``quest_required`` (default 0), ``loot_mode`` (default 1),
                ``group_id`` (default 0), ``min`` (default 1),
                ``max`` (default 1), ``reference`` (default 0),
                ``comment``.
        """
        columns = ['Entry', 'Item', 'Reference', 'Chance', 'QuestRequired',
                   'LootMode', 'GroupId', 'MinCount', 'MaxCount', 'Comment']

        rows = []
        for item_def in loot_items:
            rows.append([
                loot_entry,
                item_def.get('item', 0),
                item_def.get('reference', 0),
                item_def.get('chance', 100.0),
                item_def.get('quest_required', 0),
                item_def.get('loot_mode', 1),
                item_def.get('group_id', 0),
                item_def.get('min', 1),
                item_def.get('max', 1),
                item_def.get('comment', ''),
            ])

        comment = '-- Loot: {} ({})'.format(table, loot_entry)
        sql = self.format_insert(table, columns, rows, comment=comment)
        self.add_sql(table, sql)


# ===================================================================
# Pool helpers (used by SQLGenerator convenience methods)
# ===================================================================

class _PoolHelper(BaseBuilder):
    """Internal helper for generating spawn pool SQL."""

    def add_pool(self, pool_def):
        """
        Add a spawn pool with its creature or gameobject members.

        Args:
            pool_def: dict with keys:
                ``entry``: Pool entry ID.
                ``max_limit``: Max simultaneous spawns from pool.
                ``description``: Pool description.
                ``creatures``: List of dicts with ``guid``, ``chance``,
                    ``description``.
                ``gameobjects``: List of dicts with ``guid``, ``chance``,
                    ``description``.
        """
        pool_entry = pool_def.get('entry', 0)

        # pool_template
        pt_cols = ['entry', 'max_limit', 'description']
        pt_row = [
            pool_entry,
            pool_def.get('max_limit', 0),
            pool_def.get('description', ''),
        ]
        sql = self.format_insert('pool_template', pt_cols, [pt_row],
                                 comment='-- Pool: {}'.format(pool_entry))
        self.add_sql('pool_template', sql)

        # pool_creature
        creatures = pool_def.get('creatures', [])
        if creatures:
            pc_cols = ['guid', 'pool_entry', 'chance', 'description']
            pc_rows = []
            for c in creatures:
                pc_rows.append([
                    c.get('guid', 0),
                    pool_entry,
                    c.get('chance', 0),
                    c.get('description', ''),
                ])
            sql = self.format_insert('pool_creature', pc_cols, pc_rows)
            self.add_sql('pool_creature', sql)

        # pool_gameobject
        gameobjects = pool_def.get('gameobjects', [])
        if gameobjects:
            pg_cols = ['guid', 'pool_entry', 'chance', 'description']
            pg_rows = []
            for g in gameobjects:
                pg_rows.append([
                    g.get('guid', 0),
                    pool_entry,
                    g.get('chance', 0),
                    g.get('description', ''),
                ])
            sql = self.format_insert('pool_gameobject', pg_cols, pg_rows)
            self.add_sql('pool_gameobject', sql)


# ===================================================================
# SQLGenerator (orchestrator)
# ===================================================================

class SQLGenerator:
    """
    Orchestrates all SQL generation for AzerothCore world database.

    Responsibilities:
    - Entry ID management (auto-increment from configurable base).
    - Foreign key tracking and validation.
    - SQL output formatting (single file or split by table).
    - Cross-reference validation (detect missing references).
    """

    def __init__(self, start_entry=90000, map_id=None, zone_id=None):
        """
        Args:
            start_entry: Base entry ID for auto-generated IDs.
            map_id: Map ID for this zone (for spawn coordinates).
            zone_id: Zone ID for quest_sort, area table references.
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

        # Internal helpers
        self._loot_helper = _LootHelper(self)
        self._pool_helper = _PoolHelper(self)

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

    # ------------------------------------------------------------------
    # Entry ID management
    # ------------------------------------------------------------------

    def allocate_entry(self):
        """Allocate and return the next available entry ID."""
        entry = self.current_entry
        self.current_entry += 1
        return entry

    def register_entity(self, entity_type, entry, data):
        """
        Register an entity for cross-reference validation.

        Args:
            entity_type: One of 'items', 'creatures', 'npcs', 'quests',
                'gameobjects'.
            entry: Entity entry ID.
            data: Entity definition dict.

        Raises:
            ValueError: If a duplicate entry ID is detected.
        """
        if entry in self.entities[entity_type]:
            raise ValueError(
                "Duplicate {} entry: {}".format(entity_type, entry))
        self.entities[entity_type][entry] = data

    # ------------------------------------------------------------------
    # High-level convenience API
    # ------------------------------------------------------------------

    def add_items(self, items_list):
        """
        Add multiple items.

        Args:
            items_list: List of item definition dicts.

        Returns:
            list[int]: Allocated entry IDs.
        """
        return [self.item_builder.add_item(item) for item in items_list]

    def add_creatures(self, creatures_list):
        """
        Add multiple creatures.

        Args:
            creatures_list: List of creature definition dicts.

        Returns:
            list[int]: Allocated entry IDs.
        """
        return [self.creature_builder.add_creature(c) for c in creatures_list]

    def add_npcs(self, npcs_list):
        """
        Add multiple NPCs (creatures with gossip/vendor support).

        Args:
            npcs_list: List of NPC definition dicts.

        Returns:
            list[int]: Allocated entry IDs.
        """
        return [self.npc_builder.add_npc(npc) for npc in npcs_list]

    def add_quests(self, quests_list):
        """
        Add multiple quests.

        Args:
            quests_list: List of quest definition dicts.

        Returns:
            list[int]: Allocated entry IDs.
        """
        return [self.quest_builder.add_quest(q) for q in quests_list]

    def add_smartai(self, ai_definitions):
        """
        Add SmartAI definitions for creatures.

        Args:
            ai_definitions: dict mapping creature entry -> AI definition
                dict (see SmartAIBuilder.add_creature_ai).
        """
        for creature_entry, ai_def in ai_definitions.items():
            self.smartai_builder.add_creature_ai(creature_entry, ai_def)

    def add_spawns(self, spawn_list):
        """
        Add multiple creature spawns.

        Args:
            spawn_list: List of spawn definition dicts.

        Returns:
            list[int]: Assigned GUIDs.
        """
        return [self.spawn_builder.add_spawn(s) for s in spawn_list]

    def add_gameobject_templates(self, go_list):
        """
        Add multiple gameobject templates.

        Args:
            go_list: List of gameobject template dicts.

        Returns:
            list[int]: Allocated entry IDs.
        """
        return [self.gameobject_builder.add_gameobject_template(g)
                for g in go_list]

    def add_gameobject_spawns(self, spawn_list):
        """
        Add multiple gameobject spawns.

        Args:
            spawn_list: List of GO spawn definition dicts.

        Returns:
            list[int]: Assigned GUIDs.
        """
        return [self.gameobject_builder.add_gameobject_spawn(s)
                for s in spawn_list]

    def add_loot(self, table, loot_entry, loot_items):
        """
        Add loot entries to a loot table.

        Args:
            table: Loot table name ('creature_loot_template',
                'gameobject_loot_template', etc.).
            loot_entry: Loot table entry ID.
            loot_items: List of loot item dicts.
        """
        self._loot_helper.add_loot(table, loot_entry, loot_items)

    def add_creature_loot(self, loot_map):
        """
        Add creature loot from a dict mapping creature entry to loot list.

        Args:
            loot_map: dict of ``{creature_entry: [loot_item_dicts]}``.
        """
        for entry, items in loot_map.items():
            self._loot_helper.add_loot('creature_loot_template', entry, items)

    def add_pools(self, pool_list):
        """
        Add spawn pools.

        Args:
            pool_list: List of pool definition dicts.
        """
        for pool in pool_list:
            self._pool_helper.add_pool(pool)

    def add_dungeon_setup(self, dungeon_config):
        """
        Add dungeon/instance configuration.

        Args:
            dungeon_config: Dungeon definition dict.
        """
        self.dungeon_builder.add_dungeon(dungeon_config)

    def add_world_events(self, events_list):
        """
        Add world events.

        Args:
            events_list: List of event definition dicts.
        """
        for event in events_list:
            self.event_builder.add_event(event)

    def add_translations(self, locale_data, locale='deDE'):
        """
        Add translations for multiple entity types.

        Args:
            locale_data: Translation data dict (see LocaleBuilder).
            locale: Locale code string.
        """
        self.locale_builder.add_translations(locale_data, locale)

    def add_zone(self, zone_def):
        """
        Register a zone in the server-side areatable_dbc.

        Args:
            zone_def: Zone definition dict (see ZoneBuilder).
        """
        self.zone_builder.add_zone(zone_def)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self):
        """
        Validate all cross-references and detect issues.

        Checks performed:
        1. Quest references valid items (required_item, reward_item).
        2. Quest references valid creatures (quest_giver, quest_ender,
           required_npc_or_go).
        3. Spawns reference valid creatures.
        4. SmartAI references valid creatures.
        5. Quest chains (prev_quest_id, next_quest_id exist).
        6. Unused entities (warnings).

        Returns:
            dict: ``{'valid': bool, 'errors': list[str],
            'warnings': list[str]}``.
        """
        errors = []
        warnings = []

        # Check quest item references
        for quest_entry, quest_data in self.entities['quests'].items():
            for item_entry, count in quest_data.get('required_item', []):
                if item_entry not in self.entities['items']:
                    errors.append(
                        "Quest {} requires non-existent item {}".format(
                            quest_entry, item_entry))

            for item_entry, count in quest_data.get('reward_item', []):
                if item_entry not in self.entities['items']:
                    errors.append(
                        "Quest {} rewards non-existent item {}".format(
                            quest_entry, item_entry))

        # Check quest creature references
        for quest_entry, quest_data in self.entities['quests'].items():
            giver = quest_data.get('quest_giver_entry')
            if giver and giver not in self.entities['npcs']:
                errors.append(
                    "Quest {} giver {} does not exist".format(
                        quest_entry, giver))

            ender = quest_data.get('quest_ender_entry')
            if ender and ender not in self.entities['npcs']:
                errors.append(
                    "Quest {} ender {} does not exist".format(
                        quest_entry, ender))

            for creature_entry, count in quest_data.get(
                    'required_npc_or_go', []):
                if creature_entry not in self.entities['creatures']:
                    errors.append(
                        "Quest {} requires non-existent creature {}".format(
                            quest_entry, creature_entry))

        # Check quest chains
        for quest_entry, quest_data in self.entities['quests'].items():
            prev_id = quest_data.get('prev_quest_id', 0)
            if prev_id and prev_id not in self.entities['quests']:
                warnings.append(
                    "Quest {} references prev_quest_id {} "
                    "which is not in this generation set".format(
                        quest_entry, prev_id))

            next_id = quest_data.get('next_quest_id', 0)
            if next_id and next_id not in self.entities['quests']:
                warnings.append(
                    "Quest {} references next_quest_id {} "
                    "which is not in this generation set".format(
                        quest_entry, next_id))

        # Check spawn references
        for spawn_guid, spawn_data in self.entities['spawns'].items():
            entry = spawn_data['entry']
            if entry not in self.entities['creatures']:
                errors.append(
                    "Spawn {} references non-existent creature {}".format(
                        spawn_guid, entry))

        # Check GO spawn references
        for go_guid, go_data in self.entities['go_spawns'].items():
            entry = go_data['entry']
            if entry not in self.entities['gameobjects']:
                # GO spawns may reference existing (vanilla) templates
                # that are not in our generation set; treat as warning.
                warnings.append(
                    "GO spawn {} references gameobject {} "
                    "not in this generation set".format(go_guid, entry))

        # Check SmartAI references
        for creature_entry in self.smartai_builder.ai_scripts.keys():
            if creature_entry not in self.entities['creatures']:
                errors.append(
                    "SmartAI script for non-existent creature {}".format(
                        creature_entry))

        # Check for unused creatures (warnings only)
        spawned_creatures = {
            sd['entry'] for sd in self.entities['spawns'].values()
        }
        for creature_entry in self.entities['creatures']:
            if creature_entry not in spawned_creatures:
                warnings.append(
                    "Creature {} is defined but never spawned".format(
                        creature_entry))

        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
        }

    # ------------------------------------------------------------------
    # SQL output
    # ------------------------------------------------------------------

    def write_sql(self, output_path):
        """
        Write all generated SQL to a single monolithic file.

        The file is structured with a header comment, followed by
        table-by-table sections in foreign key dependency order.
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(self._generate_header())
            f.write('\n\n')

            for table in _TABLE_ORDER:
                if table in self.sql_buffers and self.sql_buffers[table]:
                    f.write(
                        '-- ============================================\n')
                    f.write('-- {}\n'.format(table.upper()))
                    f.write(
                        '-- ============================================\n\n')
                    for sql in self.sql_buffers[table]:
                        f.write(sql)
                        f.write('\n\n')

            # Write any tables not in the predefined order
            for table, statements in self.sql_buffers.items():
                if table not in _TABLE_ORDER and statements:
                    f.write(
                        '-- ============================================\n')
                    f.write('-- {}\n'.format(table.upper()))
                    f.write(
                        '-- ============================================\n\n')
                    for sql in statements:
                        f.write(sql)
                        f.write('\n\n')

    def write_sql_split(self, output_dir):
        """
        Write SQL split by table name (one file per table).

        Useful for version control and selective application.
        """
        os.makedirs(output_dir, exist_ok=True)

        for table, statements in self.sql_buffers.items():
            if not statements:
                continue

            file_path = os.path.join(output_dir, '{}.sql'.format(table))
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self._generate_header())
                f.write('\n\n-- Table: {}\n\n'.format(table))
                for sql in statements:
                    f.write(sql)
                    f.write('\n\n')

    def get_sql(self):
        """
        Return all generated SQL as a single string (in-memory).

        Useful for testing and programmatic consumption.

        Returns:
            str: Complete SQL output.
        """
        parts = [self._generate_header(), '\n\n']

        for table in _TABLE_ORDER:
            if table in self.sql_buffers and self.sql_buffers[table]:
                parts.append(
                    '-- ============================================\n')
                parts.append('-- {}\n'.format(table.upper()))
                parts.append(
                    '-- ============================================\n\n')
                for sql in self.sql_buffers[table]:
                    parts.append(sql)
                    parts.append('\n\n')

        for table, statements in self.sql_buffers.items():
            if table not in _TABLE_ORDER and statements:
                parts.append(
                    '-- ============================================\n')
                parts.append('-- {}\n'.format(table.upper()))
                parts.append(
                    '-- ============================================\n\n')
                for sql in statements:
                    parts.append(sql)
                    parts.append('\n\n')

        return ''.join(parts)

    def _generate_header(self):
        """Generate the SQL file header comment."""
        last_entry = self.current_entry - 1
        if last_entry < self.start_entry:
            last_entry = self.start_entry
        return (
            '-- ============================================\n'
            '-- PyWoWLib SQL Generator\n'
            '-- Generated: {}\n'
            '-- Zone: {}\n'
            '-- Map: {}\n'
            '-- Entry Range: {} - {}\n'
            '-- ============================================'
        ).format(
            datetime.datetime.now().isoformat(),
            self.zone_id if self.zone_id is not None else 'Unknown',
            self.map_id if self.map_id is not None else 'Unknown',
            self.start_entry,
            last_entry,
        )


# ---------------------------------------------------------------------------
# CreatureBuilder internal helper for NPC reuse
# ---------------------------------------------------------------------------

def _creature_builder_build_sql(self, creature_def, entry):
    """
    Build creature_template SQL without registering entities.

    Used internally by NPCBuilder to avoid double-registration.
    """
    columns = [
        'entry', 'difficulty_entry_1', 'difficulty_entry_2',
        'difficulty_entry_3',
        'KillCredit1', 'KillCredit2',
        'modelid1', 'modelid2', 'modelid3', 'modelid4',
        'name', 'subname', 'IconName',
        'gossip_menu_id', 'minlevel', 'maxlevel',
        'exp', 'faction', 'npcflag',
        'speed_walk', 'speed_run', 'scale',
        'rank', 'dmgschool',
        'BaseAttackTime', 'RangeAttackTime',
        'BaseVariance', 'RangeVariance',
        'unit_class', 'unit_flags', 'unit_flags2', 'dynamicflags',
        'family',
        'trainer_type', 'trainer_spell', 'trainer_class', 'trainer_race',
        'type', 'type_flags',
        'lootid', 'pickpocketloot', 'skinloot',
        'resistance1', 'resistance2', 'resistance3',
        'resistance4', 'resistance5', 'resistance6',
        'spell1', 'spell2', 'spell3', 'spell4',
        'spell5', 'spell6', 'spell7', 'spell8',
        'PetSpellDataId', 'VehicleId',
        'mingold', 'maxgold',
        'AIName', 'MovementType',
        'InhabitType', 'HoverHeight',
        'HealthModifier', 'ManaModifier',
        'ArmorModifier', 'DamageModifier', 'ExperienceModifier',
        'RacialLeader', 'movementId',
        'RegenHealth', 'mechanic_immune_mask',
        'flags_extra', 'ScriptName',
    ]

    row = [
        entry,
        creature_def.get('difficulty_entry_1', 0),
        creature_def.get('difficulty_entry_2', 0),
        creature_def.get('difficulty_entry_3', 0),
        creature_def.get('kill_credit_1', 0),
        creature_def.get('kill_credit_2', 0),
        creature_def.get('modelid1', 0),
        creature_def.get('modelid2', 0),
        creature_def.get('modelid3', 0),
        creature_def.get('modelid4', 0),
        creature_def.get('name', ''),
        creature_def.get('subname', ''),
        creature_def.get('icon_name', ''),
        creature_def.get('gossip_menu_id', 0),
        creature_def.get('minlevel', 1),
        creature_def.get('maxlevel', 1),
        creature_def.get('exp', 0),
        creature_def.get('faction', 0),
        creature_def.get('npcflag', 0),
        creature_def.get('speed_walk', 1.0),
        creature_def.get('speed_run', 1.14286),
        creature_def.get('scale', 1.0),
        creature_def.get('rank', 0),
        creature_def.get('dmgschool', 0),
        creature_def.get('base_attack_time', 2000),
        creature_def.get('range_attack_time', 0),
        creature_def.get('base_variance', 1.0),
        creature_def.get('range_variance', 1.0),
        creature_def.get('unit_class', 0),
        creature_def.get('unit_flags', 0),
        creature_def.get('unit_flags2', 0),
        creature_def.get('dynamicflags', 0),
        creature_def.get('family', 0),
        creature_def.get('trainer_type', 0),
        creature_def.get('trainer_spell', 0),
        creature_def.get('trainer_class', 0),
        creature_def.get('trainer_race', 0),
        creature_def.get('type', 0),
        creature_def.get('type_flags', 0),
        creature_def.get('lootid', 0),
        creature_def.get('pickpocketloot', 0),
        creature_def.get('skinloot', 0),
        creature_def.get('resistance1', 0),
        creature_def.get('resistance2', 0),
        creature_def.get('resistance3', 0),
        creature_def.get('resistance4', 0),
        creature_def.get('resistance5', 0),
        creature_def.get('resistance6', 0),
        creature_def.get('spell1', 0),
        creature_def.get('spell2', 0),
        creature_def.get('spell3', 0),
        creature_def.get('spell4', 0),
        creature_def.get('spell5', 0),
        creature_def.get('spell6', 0),
        creature_def.get('spell7', 0),
        creature_def.get('spell8', 0),
        creature_def.get('pet_spell_data_id', 0),
        creature_def.get('vehicle_id', 0),
        creature_def.get('mingold', 0),
        creature_def.get('maxgold', 0),
        creature_def.get('ai_name', ''),
        creature_def.get('movement_type', 0),
        creature_def.get('inhabit_type', 3),
        creature_def.get('hover_height', 1.0),
        creature_def.get('health_modifier', 1.0),
        creature_def.get('mana_modifier', 1.0),
        creature_def.get('armor_modifier', 1.0),
        creature_def.get('damage_modifier', 1.0),
        creature_def.get('experience_modifier', 1.0),
        creature_def.get('racial_leader', 0),
        creature_def.get('movement_id', 0),
        creature_def.get('regen_health', 1),
        creature_def.get('mechanic_immune_mask', 0),
        creature_def.get('flags_extra', 0),
        creature_def.get('script_name', ''),
    ]

    comment = '-- Creature: {} ({})'.format(
        creature_def.get('name', ''), entry)
    return self.format_insert('creature_template', columns, [row],
                              comment=comment)


# Attach internal method to CreatureBuilder
CreatureBuilder._build_creature_sql = _creature_builder_build_sql


# ===================================================================
# _SQLParser (internal class for SQL import)
# ===================================================================

import re


class _SQLParser:
    """
    Internal parser for reading INSERT INTO statements from SQL files.

    Handles comment stripping, value parsing (strings, numbers, NULL),
    and SQL escape sequences. Designed for AzerothCore SQL dumps.
    """

    # Regex to match INSERT INTO `table` (columns) VALUES ...;
    _INSERT_RE = re.compile(
        r'INSERT\s+INTO\s+`?(\w+)`?\s*'
        r'\(([^)]+)\)\s*VALUES\s*'
        r'(.+?)\s*;',
        re.IGNORECASE | re.DOTALL,
    )

    @classmethod
    def parse_file(cls, filepath):
        """
        Read a SQL file and extract all INSERT INTO statements.

        Strips ``--`` line comments and ``/* */`` block comments before
        parsing. Returns a dict mapping table names to lists of row dicts.

        Args:
            filepath: Path to the ``.sql`` file.

        Returns:
            dict: ``{table_name: [{'col': value, ...}, ...]}``.
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            raw = f.read()

        # Strip comments
        cleaned = cls._strip_comments(raw)

        results = {}
        for match in cls._INSERT_RE.finditer(cleaned):
            table_name = match.group(1)
            columns_raw = match.group(2)
            values_raw = match.group(3)

            columns = cls._parse_column_list(columns_raw)
            value_tuples = cls._parse_values_block(values_raw)

            if table_name not in results:
                results[table_name] = []

            for vtuple in value_tuples:
                row_dict = {}
                for i, col in enumerate(columns):
                    if i < len(vtuple):
                        row_dict[col] = vtuple[i]
                    else:
                        row_dict[col] = None
                results[table_name].append(row_dict)

        return results

    @staticmethod
    def _strip_comments(sql_text):
        """
        Remove ``--`` line comments and ``/* */`` block comments.

        Args:
            sql_text: Raw SQL text.

        Returns:
            str: SQL text with comments removed.
        """
        # Remove block comments (non-greedy)
        sql_text = re.sub(r'/\*.*?\*/', '', sql_text, flags=re.DOTALL)
        # Remove line comments (-- to end of line)
        sql_text = re.sub(r'--[^\n]*', '', sql_text)
        return sql_text

    @staticmethod
    def _parse_column_list(columns_raw):
        """
        Parse a comma-separated column list, stripping backticks.

        Args:
            columns_raw: Raw column string from between parentheses.

        Returns:
            list[str]: Column names.
        """
        columns = []
        for col in columns_raw.split(','):
            col = col.strip().strip('`').strip()
            if col:
                columns.append(col)
        return columns

    @classmethod
    def _parse_values_block(cls, values_str):
        """
        Parse a VALUES block containing one or more row tuples.

        Handles: SQL string escaping (``''`` and ``\\'``), NULL keyword,
        numeric types (int/float), and quoted strings.

        Args:
            values_str: The text after VALUES, e.g.
                ``(1, 'foo', NULL), (2, 'bar', 3.14)``.

        Returns:
            list[tuple]: List of parsed value tuples.
        """
        rows = []
        i = 0
        length = len(values_str)

        while i < length:
            # Find opening paren
            if values_str[i] == '(':
                # Find matching closing paren, respecting quoted strings
                paren_content, end_pos = cls._extract_paren_content(
                    values_str, i)
                row_values = cls._parse_single_row(paren_content)
                rows.append(tuple(row_values))
                i = end_pos + 1
            else:
                i += 1

        return rows

    @classmethod
    def _extract_paren_content(cls, text, start):
        """
        Extract content between matched parentheses, respecting strings.

        Args:
            text: Full text.
            start: Index of opening parenthesis.

        Returns:
            tuple: (content_string, end_index) where end_index is the
                position of the closing parenthesis.
        """
        i = start + 1
        depth = 1
        in_string = False
        escape_next = False
        length = len(text)

        while i < length and depth > 0:
            ch = text[i]

            if escape_next:
                escape_next = False
                i += 1
                continue

            if ch == '\\':
                escape_next = True
                i += 1
                continue

            if ch == "'":
                if in_string:
                    # Check for escaped quote ('')
                    if i + 1 < length and text[i + 1] == "'":
                        i += 2
                        continue
                    in_string = False
                else:
                    in_string = True
                i += 1
                continue

            if not in_string:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        return text[start + 1:i], i

            i += 1

        # Fallback if unmatched
        return text[start + 1:], length - 1

    @classmethod
    def _parse_single_row(cls, row_content):
        """
        Parse the comma-separated values inside a single row tuple.

        Args:
            row_content: String content between parentheses for one row.

        Returns:
            list: Parsed values (int, float, str, or None).
        """
        values = []
        i = 0
        length = len(row_content)
        current_token = []
        in_string = False
        escape_next = False

        while i < length:
            ch = row_content[i]

            if escape_next:
                current_token.append(ch)
                escape_next = False
                i += 1
                continue

            if ch == '\\' and in_string:
                current_token.append(ch)
                escape_next = True
                i += 1
                continue

            if ch == "'":
                if in_string:
                    # Check for escaped quote ''
                    if i + 1 < length and row_content[i + 1] == "'":
                        current_token.append("'")
                        current_token.append("'")
                        i += 2
                        continue
                    in_string = False
                    current_token.append(ch)
                else:
                    in_string = True
                    current_token.append(ch)
                i += 1
                continue

            if ch == ',' and not in_string:
                token = ''.join(current_token).strip()
                values.append(cls._parse_value(token))
                current_token = []
                i += 1
                continue

            current_token.append(ch)
            i += 1

        # Last token
        token = ''.join(current_token).strip()
        if token:
            values.append(cls._parse_value(token))

        return values

    @staticmethod
    def _parse_value(value_str):
        """
        Parse a single SQL value token into a Python type.

        - ``NULL`` -> None
        - Quoted strings -> str (with escapes resolved)
        - Integers -> int
        - Floats -> float

        Args:
            value_str: Trimmed string of a single SQL value.

        Returns:
            Parsed value (int, float, str, or None).
        """
        if not value_str:
            return None

        upper = value_str.upper()
        if upper == 'NULL':
            return None

        # Quoted string
        if value_str.startswith("'") and value_str.endswith("'"):
            inner = value_str[1:-1]
            # Resolve SQL escapes
            inner = inner.replace("''", "'")
            inner = inner.replace("\\'", "'")
            inner = inner.replace("\\\\", "\\")
            inner = inner.replace("\\n", "\n")
            inner = inner.replace("\\r", "\r")
            inner = inner.replace("\\t", "\t")
            return inner

        # Try integer
        try:
            return int(value_str)
        except ValueError:
            pass

        # Try float
        try:
            return float(value_str)
        except ValueError:
            pass

        # Fallback: return as string
        return value_str


# ---------------------------------------------------------------------------
# Table name -> entity category mapping for import_sql()
# ---------------------------------------------------------------------------

_TABLE_CATEGORY_MAP = {
    'item_template': 'items',
    'creature_template': 'creatures',
    'quest_template': 'quests',
    'quest_template_addon': 'quests',
    'gameobject_template': 'gameobjects',
    'creature': 'spawns',
    'smart_scripts': 'smart_ai',
    'npc_text': 'npcs',
    'gossip_menu': 'npcs',
    'npc_vendor': 'npcs',
}


def import_sql(filepath):
    """
    Import entities from a SQL file containing INSERT INTO statements.

    Parses the SQL file, maps table names to entity categories, and
    returns structured data suitable for programmatic consumption or
    re-injection via the SQLGenerator builder methods.

    Supported tables and their categories:
        - ``item_template`` -> ``'items'``
        - ``creature_template`` -> ``'creatures'``
        - ``quest_template`` / ``quest_template_addon`` -> ``'quests'``
        - ``gameobject_template`` -> ``'gameobjects'``
        - ``creature`` (spawn table) -> ``'spawns'``
        - ``smart_scripts`` -> ``'smart_ai'``
        - ``npc_text`` / ``gossip_menu`` / ``npc_vendor`` -> ``'npcs'``

    Args:
        filepath: Path to the ``.sql`` file to import.

    Returns:
        dict: ``{'items': [dict,...], 'creatures': [dict,...],
        'quests': [dict,...], 'gameobjects': [dict,...],
        'spawns': [dict,...], 'smart_ai': [dict,...],
        'npcs': [dict,...]}``. Each dict has column names as keys
        and parsed values as values.
    """
    parsed = _SQLParser.parse_file(filepath)

    result = {
        'items': [],
        'creatures': [],
        'quests': [],
        'gameobjects': [],
        'spawns': [],
        'smart_ai': [],
        'npcs': [],
    }

    for table_name, rows in parsed.items():
        category = _TABLE_CATEGORY_MAP.get(table_name)
        if category is None:
            log.debug(
                "Skipping unmapped table during SQL import: %s", table_name)
            continue
        result[category].extend(rows)

    total = sum(len(v) for v in result.values())
    log.info(
        "Imported %d rows from %s across %d categories",
        total, filepath,
        sum(1 for v in result.values() if v),
    )

    return result
