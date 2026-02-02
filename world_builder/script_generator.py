"""
Eluna Lua script generator for WoW WotLK 3.3.5a AzerothCore.

Generates complete, deployable boss encounter scripts and instance
management scripts from structured data definitions. Uses Jinja2
templates to produce fully functional Eluna Lua code with no manual
completion required.

Output scripts follow AzerothCore Eluna conventions:
    - RegisterCreatureEvent for boss hooks
    - RegisterInstanceEvent for instance hooks
    - Creature:RegisterEvent for timed abilities
    - SetData/GetData for state management
    - SaveInstanceData for persistence
"""

import json
import os
import logging

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    raise ImportError(
        "Jinja2 is required for script generation. "
        "Install it with: pip install jinja2"
    )

from .spell_registry import SpellRegistry

log = logging.getLogger(__name__)


class ScriptGenerator:
    """
    Generates COMPLETE, DEPLOYABLE boss and instance scripts for
    WoW 3.3.5a AzerothCore with Eluna. Outputs fully functional
    Lua scripts with NO manual completion required.
    """

    def __init__(self, spell_registry=None):
        """
        Initialize the script generator.

        Args:
            spell_registry: Optional SpellRegistry instance. If None,
                            a fresh registry with default base ID is created.
        """
        self.spell_registry = spell_registry or SpellRegistry()

        # Initialize Jinja2 template engine
        template_dir = os.path.join(os.path.dirname(__file__), 'templates', 'eluna')
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Storage for generated scripts
        self.instance_script = None
        self.instance_data = None
        self.boss_scripts = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_instance_script(self, instance_def):
        """
        Generate a COMPLETE instance script with full functionality.

        The generated script includes:
            - Encounter state bitmask management (save/load persistence)
            - Door management (lock on create, unlock on boss kills)
            - OnCreatureCreate hooks for boss registration
            - Full save/load instance data persistence

        Args:
            instance_def: Dictionary defining the instance. Must follow
                          the schema documented in encounter_definitions.py.
        """
        template = self.env.get_template('instance_script.lua.jinja2')

        self.instance_data = instance_def
        self.instance_script = template.render(
            instance=instance_def,
            spell_registry=self.spell_registry,
        )

        log.info("Generated instance script: %s", instance_def.get('script_name', 'unknown'))

    def add_boss_encounter(self, boss_def):
        """
        Generate a COMPLETE boss encounter script with all mechanics.

        The generated script includes:
            - Multi-phase system with HP-percentage transitions
            - Timer-based spell casting (RegisterEvent pattern)
            - Target selection logic (tank, random, AoE)
            - Add spawning and management
            - Void zone / ground effect placement
            - Phase transition mechanics (transform, buff, despawn)
            - Boss yells on phase transitions and death
            - Achievement criteria tracking
            - Combat reset handling

        Args:
            boss_def: Dictionary defining the boss encounter. Must follow
                      the schema documented in encounter_definitions.py.
        """
        # Resolve all spell IDs from the registry
        for phase in boss_def.get('phases', []):
            for ability in phase.get('abilities', []):
                spell_name = ability.get('spell', '')
                resolved = self.spell_registry.resolve_spell_id(spell_name)
                if resolved:
                    ability['spell_id'] = resolved

        template = self.env.get_template('boss_script.lua.jinja2')

        script = template.render(
            boss=boss_def,
            spell_registry=self.spell_registry,
        )

        self.boss_scripts.append({
            'script': script,
            'name': boss_def['script_name'],
            'entry': boss_def['entry'],
        })

        log.info(
            "Generated boss script: %s (entry %d)",
            boss_def.get('name', 'unknown'),
            boss_def.get('entry', 0),
        )

    def write_scripts(self, output_dir):
        """
        Write all generated scripts to disk.

        Creates the output directory if needed. Writes the instance
        script, all boss scripts, the spell constants Lua file, and
        a JSON spell configuration file.

        Args:
            output_dir: Directory to write scripts into.

        Returns:
            list[str]: Paths to all written script files.
        """
        os.makedirs(output_dir, exist_ok=True)
        written_files = []

        # Write instance script
        if self.instance_script:
            instance_name = self.instance_data.get('script_name', 'instance')
            instance_path = os.path.join(output_dir, '{}.lua'.format(instance_name))
            with open(instance_path, 'w') as f:
                f.write(self.instance_script)
            written_files.append(instance_path)
            log.info("Wrote instance script: %s", instance_path)

        # Write boss scripts
        for boss_data in self.boss_scripts:
            filename = 'boss_{}.lua'.format(boss_data['name'].lower())
            boss_path = os.path.join(output_dir, filename)
            with open(boss_path, 'w') as f:
                f.write(boss_data['script'])
            written_files.append(boss_path)
            log.info("Wrote boss script: %s", boss_path)

        # Write spell constants
        spell_const_path = os.path.join(output_dir, 'spell_constants.lua')
        self.spell_registry.export_lua_constants(spell_const_path)
        written_files.append(spell_const_path)
        log.info("Wrote spell constants: %s", spell_const_path)

        # Write spell config JSON
        spell_json_path = os.path.join(output_dir, 'spell_config.json')
        self.spell_registry.export_json_config(spell_json_path)
        written_files.append(spell_json_path)
        log.info("Wrote spell config: %s", spell_json_path)

        return written_files

    def validate_scripts(self):
        """
        Validate generated scripts for syntax and logic errors.

        Checks for required function declarations and event registrations
        in both instance and boss scripts.

        Returns:
            dict: {
                'valid': bool,
                'errors': list[str],
                'warnings': list[str],
            }
        """
        results = {
            'valid': True,
            'errors': [],
            'warnings': [],
        }

        # Validate instance script
        if self.instance_script:
            self._validate_instance_script(results)
        else:
            results['warnings'].append("No instance script generated")

        # Validate boss scripts
        for boss_data in self.boss_scripts:
            self._validate_boss_script(boss_data, results)

        if not self.boss_scripts:
            results['warnings'].append("No boss scripts generated")

        return results

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_instance_script(self, results):
        """Validate the instance script for required elements."""
        script = self.instance_script

        required_functions = [
            'function INSTANCE.OnCreate',
            'function INSTANCE.SetDoorState',
            'function INSTANCE.UnlockDoor',
            'function INSTANCE.SetBossState',
            'function INSTANCE.IsBossKilled',
            'function INSTANCE.OnSave',
            'function INSTANCE.OnLoad',
            'function INSTANCE.OnCreatureCreate',
        ]

        for func in required_functions:
            if func not in script:
                results['errors'].append(
                    "Instance script: Missing {}".format(func)
                )
                results['valid'] = False

        if 'RegisterInstanceEvent' not in script:
            results['errors'].append(
                "Instance script: Missing event registration"
            )
            results['valid'] = False

        # Check for completeness indicators
        if 'TODO' in script or 'FIXME' in script:
            results['errors'].append(
                "Instance script: Contains TODO/FIXME markers"
            )
            results['valid'] = False

    def _validate_boss_script(self, boss_data, results):
        """Validate a single boss script for required elements."""
        script = boss_data['script']
        name = boss_data['name']

        required_functions = [
            'function Boss.OnEnterCombat',
            'function Boss.OnLeaveCombat',
            'function Boss.OnDied',
            'function Boss.GetRandomPlayer',
        ]

        for func in required_functions:
            if func not in script:
                results['errors'].append(
                    "Boss {}: Missing {}".format(name, func)
                )
                results['valid'] = False

        if 'RegisterCreatureEvent' not in script:
            results['errors'].append(
                "Boss {}: Missing event registration".format(name)
            )
            results['valid'] = False

        # Count ability functions (at least one per phase)
        func_count = script.count('function Boss.')
        if func_count < 5:
            results['warnings'].append(
                "Boss {}: Suspiciously few functions ({})".format(
                    name, func_count
                )
            )

        # Check for completeness indicators
        if 'TODO' in script or 'FIXME' in script:
            results['errors'].append(
                "Boss {}: Contains TODO/FIXME markers".format(name)
            )
            results['valid'] = False

        # Validate spell IDs are non-zero
        if ', 0, false)' in script:
            results['warnings'].append(
                "Boss {}: Possible unresolved spell ID (0)".format(name)
            )


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def register_vault_spells(registry):
    """
    Register all spell IDs for the Vault of Storms dungeon.

    Populates the provided SpellRegistry with the 30+ spells used
    across all 4 boss encounters. Spells that reuse existing WoW
    3.3.5a IDs are marked as 'existing'; all others receive custom
    IDs in the 90xxx range.

    Args:
        registry: SpellRegistry instance to populate.
    """
    # Boss 1: Shade of Zhar'kaan
    b1 = "BOSS 1: SHADE OF ZHAR'KAAN"
    registry.register_spell(
        'SPELL_SHADOW_BOLT_VOLLEY', existing_spell_id=27831,
        description='Shadow Bolt Volley (reused from Naxxramas)',
        boss_label=b1,
    )
    registry.register_spell(
        'SPELL_SUMMON_WISPS', custom_spell_id=90001,
        description='Summon Darkling Wisps',
        boss_label=b1,
    )
    registry.register_spell(
        'SPELL_SHADOW_POOL', custom_spell_id=90002,
        description='Shadow Pool visual',
        boss_label=b1,
    )
    registry.register_spell(
        'SPELL_SHADOW_POOL_DAMAGE', custom_spell_id=90003,
        description='Shadow Pool damage aura',
        boss_label=b1,
    )
    registry.register_spell(
        'SPELL_LIGHTNING_LASH', custom_spell_id=90004,
        description='Lightning Lash (chain lightning)',
        boss_label=b1,
    )

    # Boss 2: Overseer Construct V-7
    b2 = "BOSS 2: OVERSEER CONSTRUCT V-7"
    registry.register_spell(
        'SPELL_SLAM', custom_spell_id=90010,
        description='Slam (tank)',
        boss_label=b2,
    )
    registry.register_spell(
        'SPELL_ARCANE_BOLT', custom_spell_id=90011,
        description='Arcane Bolt (random player)',
        boss_label=b2,
    )
    registry.register_spell(
        'SPELL_ACTIVATE_TURRET', custom_spell_id=90012,
        description='Activate Turret (script trigger)',
        boss_label=b2,
    )
    registry.register_spell(
        'SPELL_OVERCHARGED', custom_spell_id=90013,
        description='Overcharged (+10% damage stacking)',
        boss_label=b2,
    )
    registry.register_spell(
        'SPELL_ARCANE_PULSE', custom_spell_id=90014,
        description='Arcane Pulse (AoE)',
        boss_label=b2,
    )
    registry.register_spell(
        'SPELL_REACTIVATE_TURRETS', custom_spell_id=90015,
        description='Reactivate All Turrets (script trigger)',
        boss_label=b2,
    )

    # Boss 3: Gorgash, Stormfather
    b3 = "BOSS 3: GORGASH, STORMFATHER"
    registry.register_spell(
        'SPELL_THUNDEROUS_SLAM', custom_spell_id=90020,
        description='Thunderous Slam (cone)',
        boss_label=b3,
    )
    registry.register_spell(
        'SPELL_CALL_ZEALOTS', custom_spell_id=90021,
        description='Call Storm Zealots (summon)',
        boss_label=b3,
    )
    registry.register_spell(
        'SPELL_PRIMAL_ROAR', custom_spell_id=90022,
        description='Primal Roar (fear)',
        boss_label=b3,
    )
    registry.register_spell(
        'SPELL_STATIC_FIELD', custom_spell_id=90023,
        description='Static Field (periodic AoE)',
        boss_label=b3,
    )
    registry.register_spell(
        'SPELL_STATIC_FIELD_DOUBLE', custom_spell_id=90024,
        description='Static Field Enhanced (double damage)',
        boss_label=b3,
    )
    registry.register_spell(
        'SPELL_LIGHTNING_CHARGE', custom_spell_id=90025,
        description='Lightning Charge (dash)',
        boss_label=b3,
    )
    registry.register_spell(
        'SPELL_STORMHEART_FURY', custom_spell_id=90026,
        description='Stormheart Fury (+50% attack speed)',
        boss_label=b3,
    )

    # Boss 4: Zhar'kaan the Stormheart
    b4 = "BOSS 4: ZHAR'KAAN THE STORMHEART"
    registry.register_spell(
        'SPELL_LIGHTNING_BOLT', existing_spell_id=9532,
        description='Lightning Bolt (existing)',
        boss_label=b4,
    )
    registry.register_spell(
        'SPELL_ARC_LIGHTNING', custom_spell_id=90030,
        description='Arc Lightning (chain 4)',
        boss_label=b4,
    )
    registry.register_spell(
        'SPELL_SUMMON_STORM_WISPS', custom_spell_id=90031,
        description='Summon Storm Wisps',
        boss_label=b4,
    )
    registry.register_spell(
        'SPELL_STORMWALL', custom_spell_id=90032,
        description='Stormwall (arena shrink)',
        boss_label=b4,
    )
    registry.register_spell(
        'SPELL_EYE_OF_STORM', custom_spell_id=90033,
        description='Eye of the Storm (targeted circle)',
        boss_label=b4,
    )
    registry.register_spell(
        'SPELL_TEMPEST', custom_spell_id=90034,
        description='Tempest (ramping AoE)',
        boss_label=b4,
    )
    registry.register_spell(
        'SPELL_CHAIN_LIGHTNING_ULTIMATE', custom_spell_id=90035,
        description='Chain Lightning (uninterruptible, chain 6)',
        boss_label=b4,
    )


def import_lua_script(filepath):
    """
    Import structured data from an Eluna Lua boss/instance script.

    Extracts spell constants, boss creature entries, event registrations,
    timer intervals, and instance-level metadata from Lua source files
    using regex pattern matching.

    Args:
        filepath: Path to the ``.lua`` file to import.

    Returns:
        dict: {
            'spell_constants': dict mapping name (str) to spell_id (int),
            'boss_entries': list of creature entry IDs (int),
            'events': list of dicts with keys 'creature_id' (int),
                'event_type' (int), 'handler' (str),
            'timers': list of dicts with keys 'name' (str),
                'interval_ms' (int),
            'instance_data': dict of any instance-level metadata found,
        }
    """
    import re as _re

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {
        'spell_constants': {},
        'boss_entries': [],
        'events': [],
        'timers': [],
        'instance_data': {},
    }

    # ---- Spell constants ----
    # Match: local SPELL_NAME = 12345
    local_pattern = _re.compile(
        r'local\s+(\w+)\s*=\s*(\d+)')
    for match in local_pattern.finditer(content):
        name = match.group(1)
        value = int(match.group(2))
        if name.startswith('SPELL_') or name.isupper():
            result['spell_constants'][name] = value

    # Match: SPELL_NAME = 12345 (global assignment, not local)
    global_pattern = _re.compile(
        r'^(\w+)\s*=\s*(\d+)', _re.MULTILINE)
    for match in global_pattern.finditer(content):
        name = match.group(1)
        value = int(match.group(2))
        if name.startswith('SPELL_') or name.isupper():
            if name not in result['spell_constants']:
                result['spell_constants'][name] = value

    # ---- Boss creature entries from RegisterCreatureEvent ----
    creature_event_pattern = _re.compile(
        r'RegisterCreatureEvent\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\w+)')
    seen_entries = set()
    for match in creature_event_pattern.finditer(content):
        creature_id = int(match.group(1))
        event_type = int(match.group(2))
        handler = match.group(3)

        result['events'].append({
            'creature_id': creature_id,
            'event_type': event_type,
            'handler': handler,
        })

        if creature_id not in seen_entries:
            result['boss_entries'].append(creature_id)
            seen_entries.add(creature_id)

    # ---- Timer intervals ----
    # Pattern: RegisterEvent(handler, delay, repeats)
    # or Creature:RegisterEvent(handler, delay, repeats)
    register_event_pattern = _re.compile(
        r':RegisterEvent\(\s*(\w+)\s*,\s*(\d+)')
    for match in register_event_pattern.finditer(content):
        handler_name = match.group(1)
        interval_ms = int(match.group(2))
        result['timers'].append({
            'name': handler_name,
            'interval_ms': interval_ms,
        })

    # Pattern: C_Timer.After(seconds, handler) -- convert to ms
    c_timer_pattern = _re.compile(
        r'C_Timer\.After\(\s*([\d.]+)\s*,\s*(\w+)')
    for match in c_timer_pattern.finditer(content):
        seconds = float(match.group(1))
        handler_name = match.group(2)
        result['timers'].append({
            'name': handler_name,
            'interval_ms': int(seconds * 1000),
        })

    # ---- Instance data (SetData / GetData patterns) ----
    set_data_pattern = _re.compile(
        r'SetData\(\s*(\w+)\s*,\s*(\w+)\s*\)')
    data_keys = set()
    for match in set_data_pattern.finditer(content):
        key = match.group(1)
        data_keys.add(key)

    get_data_pattern = _re.compile(
        r'GetData\(\s*(\w+)\s*\)')
    for match in get_data_pattern.finditer(content):
        key = match.group(1)
        data_keys.add(key)

    if data_keys:
        result['instance_data']['data_keys'] = sorted(data_keys)

    # Extract instance event registrations
    instance_event_pattern = _re.compile(
        r'RegisterInstanceEvent\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\w+)')
    instance_events = []
    for match in instance_event_pattern.finditer(content):
        instance_events.append({
            'instance_id': int(match.group(1)),
            'event_type': int(match.group(2)),
            'handler': match.group(3),
        })
    if instance_events:
        result['instance_data']['instance_events'] = instance_events

    log.info(
        "Imported Lua script %s: %d spells, %d bosses, %d events, %d timers",
        filepath,
        len(result['spell_constants']),
        len(result['boss_entries']),
        len(result['events']),
        len(result['timers']),
    )

    return result


def generate_vault_of_storms_scripts(output_dir='./output/scripts/'):
    """
    Generate COMPLETE, DEPLOYABLE scripts for the Vault of Storms dungeon.

    This is the primary entry point for generating all scripts. It creates
    the spell registry, registers all spells, generates the instance script
    and all 4 boss encounter scripts, writes them to disk, and validates.

    Args:
        output_dir: Directory to write generated scripts.

    Returns:
        dict: {
            'script_paths': list of written file paths,
            'spell_registry': populated SpellRegistry instance,
            'validation': validation result dict,
        }
    """
    from .encounter_definitions import VAULT_INSTANCE, VAULT_BOSSES

    # Initialize and populate spell registry
    spell_registry = SpellRegistry(base_spell_id=90000)
    register_vault_spells(spell_registry)

    # Initialize generator
    generator = ScriptGenerator(spell_registry)

    # Generate instance script
    generator.add_instance_script(VAULT_INSTANCE)

    # Generate all boss scripts
    for boss_def in VAULT_BOSSES:
        generator.add_boss_encounter(boss_def)

    # Write all scripts
    script_paths = generator.write_scripts(output_dir)

    # Validate
    validation = generator.validate_scripts()

    return {
        'script_paths': script_paths,
        'spell_registry': spell_registry,
        'validation': validation,
    }
