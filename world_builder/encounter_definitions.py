"""
Encounter definitions for the Vault of Storms dungeon.

Contains the complete structured data for 4 boss encounters and the
instance-level configuration. These definitions are consumed by
ScriptGenerator to produce fully deployable Eluna Lua scripts.

All NPC entries use the 90xxx range. All custom spell IDs use the 90xxx
range (managed by SpellRegistry). Door/object entries use the 195xxx range.
"""


# ---------------------------------------------------------------------------
# Instance definition
# ---------------------------------------------------------------------------

VAULT_INSTANCE = {
    'name': 'VaultOfStorms',
    'display_name': 'Vault of Storms',
    'map_id': 801,
    'script_name': 'instance_vault_of_storms',

    'bosses': [
        {
            'name': 'ShadeOfZharkaan',
            'entry': 90100,
            'encounter_id': 0,
            'encounter_name': 'BOSS_SHADE',
        },
        {
            'name': 'OverseerV7',
            'entry': 90200,
            'encounter_id': 1,
            'encounter_name': 'BOSS_OVERSEER',
        },
        {
            'name': 'GorgashStormfather',
            'entry': 90300,
            'encounter_id': 2,
            'encounter_name': 'BOSS_GORGASH',
        },
        {
            'name': 'ZharkaanStormheart',
            'entry': 90400,
            'encounter_id': 3,
            'encounter_name': 'BOSS_ZHARKAAN',
        },
    ],

    'doors': [
        {
            'entry': 195000,
            'name': 'door_nexus_to_core',
            'const_name': 'DOOR_NEXUS_TO_CORE',
            'unlock_on_encounter': 0,
            'initial_state': 'closed',
        },
        {
            'entry': 195001,
            'name': 'door_core_to_forge',
            'const_name': 'DOOR_CORE_TO_FORGE',
            'unlock_on_encounter': 1,
            'initial_state': 'closed',
        },
        {
            'entry': 195002,
            'name': 'door_forge_to_sanctum',
            'const_name': 'DOOR_FORGE_TO_SANCTUM',
            'unlock_on_encounter': 2,
            'initial_state': 'closed',
        },
    ],

    'events': [
        {
            'type': 'coolant_vents',
            'name': 'activate_coolant_system',
            'objects': [
                {'entry': 195100, 'name': 'coolant_vent_1'},
                {'entry': 195101, 'name': 'coolant_vent_2'},
                {'entry': 195102, 'name': 'coolant_vent_3'},
            ],
            'reward': {
                'type': 'unlock_door',
                'door_entry': 195003,
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# Boss 1: Shade of Zhar'kaan (85k HP, 2 phases)
# ---------------------------------------------------------------------------

BOSS_SHADE_OF_ZHARKAAN = {
    'name': "Shade of Zhar'kaan",
    'script_name': 'ShadeOfZharkaan',
    'entry': 90100,
    'health': 85000,
    'mana': 50000,
    'encounter_id': 0,

    'npcs': [
        {'entry': 90101, 'name': 'NPC_DARKLING_WISP', 'label': 'Darkling Wisp'},
        {'entry': 90102, 'name': 'NPC_SHADOWY_STALKER', 'label': 'Shadowy Stalker'},
    ],

    'phases': [
        {
            'phase_id': 1,
            'name': 'Phase 1 - Shadow Phase',
            'const_name': 'PHASE_SHADOW',
            'hp_range': (100, 50),

            'on_enter': {
                'yell': 'The shadows consume you!',
                'sound_id': 15000,
            },

            'abilities': [
                {
                    'id': 'shadow_bolt_volley',
                    'func_name': 'CastShadowBoltVolley',
                    'spell': 'SPELL_SHADOW_BOLT_VOLLEY',
                    'spell_id': 27831,
                    'name': 'Shadow Bolt Volley',
                    'description': 'AoE shadow damage, interruptible',
                    'timer': {'initial': 5000, 'min': 8000, 'max': 12000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 2000,
                    'interruptible': True,
                },
                {
                    'id': 'summon_wisps',
                    'func_name': 'SummonWisps',
                    'spell': 'SPELL_SUMMON_WISPS',
                    'spell_id': 90001,
                    'name': 'Summon Darkling Wisps',
                    'description': 'Summons 2 Darkling Wisps to attack players',
                    'timer': {'initial': 10000, 'min': 20000, 'max': 20000},
                    'targeting': {'type': 'self'},
                    'summon': {
                        'entry': 90101,
                        'count': 2,
                        'position': 'random_around_boss',
                        'radius': 10.0,
                        'duration': 60000,
                    },
                },
                {
                    'id': 'shadow_pool',
                    'func_name': 'CastShadowPool',
                    'spell': 'SPELL_SHADOW_POOL',
                    'spell_id': 90002,
                    'name': 'Shadow Pool',
                    'description': 'Void zone at random player location',
                    'timer': {'initial': 8000, 'min': 15000, 'max': 20000},
                    'targeting': {'type': 'random_player'},
                    'void_zone': {
                        'visual_spell': 90002,
                        'damage_spell': 90003,
                        'duration': 30000,
                        'radius': 5.0,
                    },
                },
            ],
        },
        {
            'phase_id': 2,
            'name': 'Phase 2 - Storm Phase',
            'const_name': 'PHASE_STORM',
            'hp_range': (50, 0),

            'on_enter': {
                'yell': 'The storm awakens! You cannot contain what was never meant to be caged!',
                'sound_id': 15001,
                'action': {
                    'type': 'transform_adds',
                    'from_entry': 90101,
                    'to_entry': 90102,
                },
            },

            'abilities': [
                {
                    'id': 'lightning_lash',
                    'func_name': 'CastLightningLash',
                    'spell': 'SPELL_LIGHTNING_LASH',
                    'spell_id': 90004,
                    'name': 'Lightning Lash',
                    'description': 'Chain lightning, hits 3 targets',
                    'timer': {'initial': 3000, 'min': 6000, 'max': 10000},
                    'targeting': {'type': 'random_player'},
                    'chain': {'enabled': True, 'max_targets': 3, 'range': 10.0},
                },
                {
                    'id': 'shadow_bolt_volley_p2',
                    'func_name': 'CastShadowBoltVolleyP2',
                    'spell': 'SPELL_SHADOW_BOLT_VOLLEY',
                    'spell_id': 27831,
                    'name': 'Shadow Bolt Volley',
                    'description': 'Continues from Phase 1',
                    'timer': {'initial': 8000, 'min': 8000, 'max': 12000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 2000,
                    'interruptible': True,
                },
            ],
        },
    ],

    'on_death': {
        'yell': 'The darkness... recedes...',
        'sound_id': 15002,
        'unlock_door': 195000,
    },

    'loot_id': 90100,

    'achievements': [
        {
            'id': 90001,
            'name': 'Shadow Dance',
            'description': "Defeat Shade of Zhar'kaan without any player being hit by Shadow Pool",
            'criteria': 'no_player_hit_by_void_zone',
            'tracking': {
                'variable': 'shadow_pool_hits',
                'condition': 'equals',
                'value': 0,
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# Boss 2: Overseer Construct V-7 (110k HP, 2 phases)
# ---------------------------------------------------------------------------

BOSS_OVERSEER_V7 = {
    'name': 'Overseer Construct V-7',
    'script_name': 'OverseerV7',
    'entry': 90200,
    'health': 110000,
    'mana': 0,
    'encounter_id': 1,

    'npcs': [
        {'entry': 90201, 'name': 'NPC_WALL_TURRET', 'label': 'Wall Turret'},
    ],

    'phases': [
        {
            'phase_id': 1,
            'name': 'Phase 1 - Operational',
            'const_name': 'PHASE_OPERATIONAL',
            'hp_range': (100, 40),

            'on_enter': {
                'yell': 'INTRUDERS DETECTED. INITIATING DEFENSE PROTOCOL.',
                'sound_id': 15010,
            },

            'abilities': [
                {
                    'id': 'slam',
                    'func_name': 'CastSlam',
                    'spell': 'SPELL_SLAM',
                    'spell_id': 90010,
                    'name': 'Slam',
                    'description': 'Heavy slam on current tank',
                    'timer': {'initial': 6000, 'min': 10000, 'max': 14000},
                    'targeting': {'type': 'current'},
                    'cast_time': 0,
                    'interruptible': False,
                },
                {
                    'id': 'arcane_bolt',
                    'func_name': 'CastArcaneBolt',
                    'spell': 'SPELL_ARCANE_BOLT',
                    'spell_id': 90011,
                    'name': 'Arcane Bolt',
                    'description': 'Arcane bolt at random player',
                    'timer': {'initial': 4000, 'min': 7000, 'max': 10000},
                    'targeting': {'type': 'random_player'},
                    'cast_time': 1500,
                    'interruptible': True,
                },
                {
                    'id': 'activate_turret',
                    'func_name': 'ActivateTurret',
                    'spell': 'SPELL_ACTIVATE_TURRET',
                    'spell_id': 90012,
                    'name': 'Activate Turret',
                    'description': 'Activates 1 of 3 wall turrets to fire at players',
                    'timer': {'initial': 15000, 'min': 25000, 'max': 30000},
                    'targeting': {'type': 'self'},
                    'turret': {
                        'entries': [90201],
                        'count': 1,
                        'duration': 20000,
                    },
                },
            ],
        },
        {
            'phase_id': 2,
            'name': 'Phase 2 - Overcharged',
            'const_name': 'PHASE_OVERCHARGED',
            'hp_range': (40, 0),

            'on_enter': {
                'yell': 'POWER CORE UNSTABLE. ENGAGING OVERDRIVE.',
                'sound_id': 15011,
                'action': {
                    'type': 'apply_buff',
                    'buff_spell': 90013,
                },
            },

            'abilities': [
                {
                    'id': 'slam_p2',
                    'func_name': 'CastSlamP2',
                    'spell': 'SPELL_SLAM',
                    'spell_id': 90010,
                    'name': 'Slam',
                    'description': 'Continues from Phase 1, faster',
                    'timer': {'initial': 4000, 'min': 8000, 'max': 10000},
                    'targeting': {'type': 'current'},
                    'cast_time': 0,
                    'interruptible': False,
                },
                {
                    'id': 'arcane_pulse',
                    'func_name': 'CastArcanePulse',
                    'spell': 'SPELL_ARCANE_PULSE',
                    'spell_id': 90014,
                    'name': 'Arcane Pulse',
                    'description': 'AoE arcane pulse, unavoidable',
                    'timer': {'initial': 5000, 'min': 12000, 'max': 15000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 2500,
                    'interruptible': False,
                },
                {
                    'id': 'reactivate_turrets',
                    'func_name': 'ReactivateTurrets',
                    'spell': 'SPELL_REACTIVATE_TURRETS',
                    'spell_id': 90015,
                    'name': 'Reactivate All Turrets',
                    'description': 'All turrets reactivate and fire continuously',
                    'timer': {'initial': 8000, 'min': 30000, 'max': 30000},
                    'targeting': {'type': 'self'},
                    'turret': {
                        'entries': [90201],
                        'count': 3,
                        'duration': 15000,
                    },
                },
            ],
        },
    ],

    'on_death': {
        'yell': 'SYSTEM... FAILURE...',
        'sound_id': 15012,
        'unlock_door': 195001,
    },

    'loot_id': 90200,

    'achievements': [
        {
            'id': 90002,
            'name': 'Short Circuit',
            'description': 'Defeat Overseer Construct V-7 without destroying any turrets',
            'criteria': 'no_turrets_destroyed',
            'tracking': {
                'variable': 'turrets_destroyed',
                'condition': 'equals',
                'value': 0,
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# Boss 3: Gorgash, Stormfather (100k HP, 3 phases)
# ---------------------------------------------------------------------------

BOSS_GORGASH_STORMFATHER = {
    'name': 'Gorgash, Stormfather',
    'script_name': 'GorgashStormfather',
    'entry': 90300,
    'health': 100000,
    'mana': 30000,
    'encounter_id': 2,

    'npcs': [
        {'entry': 90301, 'name': 'NPC_STORM_ZEALOT', 'label': 'Storm Zealot'},
    ],

    'phases': [
        {
            'phase_id': 1,
            'name': 'Phase 1 - Thunder',
            'const_name': 'PHASE_THUNDER',
            'hp_range': (100, 60),

            'on_enter': {
                'yell': 'The storm obeys my command! Kneel before the Stormfather!',
                'sound_id': 15020,
            },

            'abilities': [
                {
                    'id': 'thunderous_slam',
                    'func_name': 'CastThunderousSlam',
                    'spell': 'SPELL_THUNDEROUS_SLAM',
                    'spell_id': 90020,
                    'name': 'Thunderous Slam',
                    'description': 'Frontal cone slam, heavy damage',
                    'timer': {'initial': 7000, 'min': 10000, 'max': 14000},
                    'targeting': {'type': 'current'},
                    'cast_time': 1500,
                    'interruptible': False,
                },
                {
                    'id': 'call_zealots',
                    'func_name': 'CallZealots',
                    'spell': 'SPELL_CALL_ZEALOTS',
                    'spell_id': 90021,
                    'name': 'Call Storm Zealots',
                    'description': 'Summons 2 Storm Zealots',
                    'timer': {'initial': 12000, 'min': 25000, 'max': 25000},
                    'targeting': {'type': 'self'},
                    'summon': {
                        'entry': 90301,
                        'count': 2,
                        'position': 'random_around_boss',
                        'radius': 12.0,
                        'duration': 0,
                    },
                },
                {
                    'id': 'primal_roar',
                    'func_name': 'CastPrimalRoar',
                    'spell': 'SPELL_PRIMAL_ROAR',
                    'spell_id': 90022,
                    'name': 'Primal Roar',
                    'description': 'AoE fear for 3 seconds',
                    'timer': {'initial': 20000, 'min': 25000, 'max': 30000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 0,
                    'interruptible': False,
                },
            ],
        },
        {
            'phase_id': 2,
            'name': 'Phase 2 - Lightning',
            'const_name': 'PHASE_LIGHTNING',
            'hp_range': (60, 30),

            'on_enter': {
                'yell': 'The sky splits! Lightning answers my call!',
                'sound_id': 15021,
            },

            'abilities': [
                {
                    'id': 'static_field',
                    'func_name': 'CastStaticField',
                    'spell': 'SPELL_STATIC_FIELD',
                    'spell_id': 90023,
                    'name': 'Static Field',
                    'description': 'Periodic AoE damage around boss',
                    'timer': {'initial': 5000, 'min': 10000, 'max': 15000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 0,
                    'interruptible': False,
                },
                {
                    'id': 'lightning_charge',
                    'func_name': 'CastLightningCharge',
                    'spell': 'SPELL_LIGHTNING_CHARGE',
                    'spell_id': 90025,
                    'name': 'Lightning Charge',
                    'description': 'Dash to random player, damages all in path',
                    'timer': {'initial': 8000, 'min': 15000, 'max': 20000},
                    'targeting': {'type': 'random_player'},
                    'cast_time': 1000,
                    'interruptible': False,
                },
                {
                    'id': 'call_zealots_p2',
                    'func_name': 'CallZealotsP2',
                    'spell': 'SPELL_CALL_ZEALOTS',
                    'spell_id': 90021,
                    'name': 'Call Storm Zealots',
                    'description': 'Continues from Phase 1',
                    'timer': {'initial': 15000, 'min': 25000, 'max': 25000},
                    'targeting': {'type': 'self'},
                    'summon': {
                        'entry': 90301,
                        'count': 2,
                        'position': 'random_around_boss',
                        'radius': 12.0,
                        'duration': 0,
                    },
                },
            ],
        },
        {
            'phase_id': 3,
            'name': 'Phase 3 - Fury',
            'const_name': 'PHASE_FURY',
            'hp_range': (30, 0),

            'on_enter': {
                'yell': 'ENOUGH! The full fury of the storm is MINE!',
                'sound_id': 15022,
                'action': {
                    'type': 'apply_buff',
                    'buff_spell': 90026,
                },
            },

            'abilities': [
                {
                    'id': 'static_field_double',
                    'func_name': 'CastStaticFieldDouble',
                    'spell': 'SPELL_STATIC_FIELD_DOUBLE',
                    'spell_id': 90024,
                    'name': 'Static Field Enhanced',
                    'description': 'Double damage periodic AoE',
                    'timer': {'initial': 3000, 'min': 8000, 'max': 10000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 0,
                    'interruptible': False,
                },
                {
                    'id': 'thunderous_slam_p3',
                    'func_name': 'CastThunderousSlamP3',
                    'spell': 'SPELL_THUNDEROUS_SLAM',
                    'spell_id': 90020,
                    'name': 'Thunderous Slam',
                    'description': 'Continues, faster in P3',
                    'timer': {'initial': 5000, 'min': 8000, 'max': 10000},
                    'targeting': {'type': 'current'},
                    'cast_time': 1500,
                    'interruptible': False,
                },
            ],
        },
    ],

    'on_death': {
        'yell': 'The storm... fades...',
        'sound_id': 15023,
        'unlock_door': 195002,
    },

    'loot_id': 90300,

    'achievements': [
        {
            'id': 90003,
            'name': 'Zealot Zapper',
            'description': 'Defeat Gorgash without letting any Storm Zealot live longer than 10 seconds',
            'criteria': 'no_zealot_survived_long',
            'tracking': {
                'variable': 'zealot_survived_long',
                'condition': 'equals',
                'value': 0,
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# Boss 4: Zhar'kaan the Stormheart (150k HP, 3 phases)
# ---------------------------------------------------------------------------

BOSS_ZHARKAAN_STORMHEART = {
    'name': "Zhar'kaan the Stormheart",
    'script_name': 'ZharkaanStormheart',
    'entry': 90400,
    'health': 150000,
    'mana': 80000,
    'encounter_id': 3,

    'npcs': [
        {'entry': 90401, 'name': 'NPC_STORM_WISP', 'label': 'Storm Wisp'},
    ],

    'phases': [
        {
            'phase_id': 1,
            'name': 'Phase 1 - Gathering Storm',
            'const_name': 'PHASE_GATHERING',
            'hp_range': (100, 65),

            'on_enter': {
                'yell': 'You dare enter MY sanctum? The storm itself shall be your executioner!',
                'sound_id': 15030,
            },

            'abilities': [
                {
                    'id': 'lightning_bolt',
                    'func_name': 'CastLightningBolt',
                    'spell': 'SPELL_LIGHTNING_BOLT',
                    'spell_id': 9532,
                    'name': 'Lightning Bolt',
                    'description': 'Single target lightning at tank',
                    'timer': {'initial': 3000, 'min': 4000, 'max': 6000},
                    'targeting': {'type': 'current'},
                    'cast_time': 2000,
                    'interruptible': True,
                },
                {
                    'id': 'arc_lightning',
                    'func_name': 'CastArcLightning',
                    'spell': 'SPELL_ARC_LIGHTNING',
                    'spell_id': 90030,
                    'name': 'Arc Lightning',
                    'description': 'Chain lightning hitting 4 targets',
                    'timer': {'initial': 8000, 'min': 12000, 'max': 15000},
                    'targeting': {'type': 'random_player'},
                    'chain': {'enabled': True, 'max_targets': 4, 'range': 10.0},
                },
                {
                    'id': 'summon_storm_wisps',
                    'func_name': 'SummonStormWisps',
                    'spell': 'SPELL_SUMMON_STORM_WISPS',
                    'spell_id': 90031,
                    'name': 'Summon Storm Wisps',
                    'description': 'Summons 3 Storm Wisps every 25 seconds',
                    'timer': {'initial': 10000, 'min': 25000, 'max': 25000},
                    'targeting': {'type': 'self'},
                    'summon': {
                        'entry': 90401,
                        'count': 3,
                        'position': 'random_around_boss',
                        'radius': 15.0,
                        'duration': 0,
                    },
                },
            ],
        },
        {
            'phase_id': 2,
            'name': 'Phase 2 - Stormwall',
            'const_name': 'PHASE_STORMWALL',
            'hp_range': (65, 30),

            'on_enter': {
                'yell': 'The walls close in! There is no escape from the eye of the storm!',
                'sound_id': 15031,
            },

            'abilities': [
                {
                    'id': 'stormwall',
                    'func_name': 'CastStormwall',
                    'spell': 'SPELL_STORMWALL',
                    'spell_id': 90032,
                    'name': 'Stormwall',
                    'description': 'Shrinks the arena by 20 percent, damages players outside',
                    'timer': {'initial': 5000, 'min': 30000, 'max': 30000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 3000,
                    'interruptible': False,
                },
                {
                    'id': 'eye_of_storm',
                    'func_name': 'CastEyeOfStorm',
                    'spell': 'SPELL_EYE_OF_STORM',
                    'spell_id': 90033,
                    'name': 'Eye of the Storm',
                    'description': 'Targeted circle on player, must move out',
                    'timer': {'initial': 7000, 'min': 12000, 'max': 18000},
                    'targeting': {'type': 'random_player'},
                    'void_zone': {
                        'visual_spell': 90033,
                        'damage_spell': 90033,
                        'duration': 10000,
                        'radius': 6.0,
                    },
                },
                {
                    'id': 'summon_storm_wisps_p2',
                    'func_name': 'SummonStormWispsP2',
                    'spell': 'SPELL_SUMMON_STORM_WISPS',
                    'spell_id': 90031,
                    'name': 'Summon Storm Wisps',
                    'description': 'Wisps continue spawning',
                    'timer': {'initial': 12000, 'min': 25000, 'max': 25000},
                    'targeting': {'type': 'self'},
                    'summon': {
                        'entry': 90401,
                        'count': 3,
                        'position': 'random_around_boss',
                        'radius': 15.0,
                        'duration': 0,
                    },
                },
                {
                    'id': 'arc_lightning_p2',
                    'func_name': 'CastArcLightningP2',
                    'spell': 'SPELL_ARC_LIGHTNING',
                    'spell_id': 90030,
                    'name': 'Arc Lightning',
                    'description': 'Continues from Phase 1',
                    'timer': {'initial': 10000, 'min': 10000, 'max': 14000},
                    'targeting': {'type': 'random_player'},
                    'chain': {'enabled': True, 'max_targets': 4, 'range': 10.0},
                },
            ],
        },
        {
            'phase_id': 3,
            'name': 'Phase 3 - Tempest',
            'const_name': 'PHASE_TEMPEST',
            'hp_range': (30, 0),

            'on_enter': {
                'yell': 'BEHOLD THE TEMPEST UNLEASHED! ALL SHALL BE CONSUMED!',
                'sound_id': 15032,
            },

            'abilities': [
                {
                    'id': 'tempest',
                    'func_name': 'CastTempest',
                    'spell': 'SPELL_TEMPEST',
                    'spell_id': 90034,
                    'name': 'Tempest',
                    'description': 'Ramping AoE damage, increases every tick',
                    'timer': {'initial': 2000, 'min': 2000, 'max': 2000},
                    'targeting': {'type': 'aoe'},
                    'cast_time': 0,
                    'interruptible': False,
                    'ramping': {
                        'base_damage': 200,
                        'max_damage': 600,
                        'increment': 50,
                    },
                },
                {
                    'id': 'chain_lightning_ultimate',
                    'func_name': 'CastChainLightningUltimate',
                    'spell': 'SPELL_CHAIN_LIGHTNING_ULTIMATE',
                    'spell_id': 90035,
                    'name': 'Chain Lightning',
                    'description': 'Uninterruptible chain lightning, 6 targets',
                    'timer': {'initial': 6000, 'min': 8000, 'max': 12000},
                    'targeting': {'type': 'random_player'},
                    'chain': {'enabled': True, 'max_targets': 6, 'range': 12.0},
                    'cast_time': 0,
                    'interruptible': False,
                },
                {
                    'id': 'summon_storm_wisps_p3',
                    'func_name': 'SummonStormWispsP3',
                    'spell': 'SPELL_SUMMON_STORM_WISPS',
                    'spell_id': 90031,
                    'name': 'Summon Storm Wisps',
                    'description': 'Wisps spawn faster in final phase',
                    'timer': {'initial': 5000, 'min': 15000, 'max': 15000},
                    'targeting': {'type': 'self'},
                    'summon': {
                        'entry': 90401,
                        'count': 3,
                        'position': 'random_around_boss',
                        'radius': 15.0,
                        'duration': 0,
                    },
                },
            ],
        },
    ],

    'on_death': {
        'yell': "The storm... is... eternal... You have won... nothing...",
        'sound_id': 15033,
        'unlock_door': None,  # Final boss, no door to unlock
    },

    'loot_id': 90400,

    'achievements': [
        {
            'id': 90004,
            'name': 'Eye of the Storm Dancer',
            'description': "Defeat Zhar'kaan without any player being hit by Eye of the Storm",
            'criteria': 'no_player_hit_by_eye',
            'tracking': {
                'variable': 'eye_of_storm_hits',
                'condition': 'equals',
                'value': 0,
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# Aggregated list for convenience
# ---------------------------------------------------------------------------

VAULT_BOSSES = [
    BOSS_SHADE_OF_ZHARKAAN,
    BOSS_OVERSEER_V7,
    BOSS_GORGASH_STORMFATHER,
    BOSS_ZHARKAAN_STORMHEART,
]
