Here is the extensive **Modding Operations Manual**. This table breaks down exactly what needs to be touched for every major "Classic+" feature you might want to crowdsource.

I have categorized them by **World**, **Combat**, **Items**, **Creatures**, and **System** to help you organize your forum sections.

### **Category 1: World Building & Environment**

| Use Case | Client-Side Files (The Patch) | Server-Side Files (The DB/Core) | Complexity | Notes |
| --- | --- | --- | --- | --- |
| **Add New Zone (Exterior)** | `.adt`, `.wdt` (Terrain)<br>

<br>`Map.dbc` (Map ID)<br>

<br>`AreaTable.dbc` (Zone Name) | `map.vmap`/`mmap` (Collision/Pathing)<br>

<br>SQL: `access_requirement` (Level req) | **Extreme** | Requires Noggit. Server pathing files must be generated or NPCs will walk through walls. |
| **Add New Dungeon (Instance)** | `.wmo` (The building)<br>

<br>`Map.dbc`, `AreaTable.dbc`<br>

<br>`DungeonEncounter.dbc` (Boss tracking) | SQL: `instance_template`<br>

<br>Script: `InstanceScript.cpp` (Gates, binding) | **High** | Dungeons are easier than zones (smaller), but require C++ scripting for things like "Door opens when Boss dies." |
| **Update Zone Scenery** | `.adt` (Modified)<br>

<br>Add `.m2`/`.wmo` (New trees/buildings) | None (if only visual) | **Medium** | "Make Elwynn Forest darker and scarier." Purely Noggit work. |
| **Add Custom Music** | `SoundEntries.dbc`<br>

<br>`ZoneIntroMusicTable.dbc`<br>

<br>`.mp3` files in MPQ | None | **Low** | Great for "Atmosphere" updates. Easy for audio engineers. |
| **Change Loading Screen** | `LoadingScreens.dbc`<br>

<br>`.blp` texture files | None | **Low** | Visual only. Good for branding your server. |

---

### **Category 2: Combat, Classes, & Spells**

| Use Case | Client-Side Files (The Patch) | Server-Side Files (The DB/Core) | Complexity | Notes |
| --- | --- | --- | --- | --- |
| **Add New Spell** | `Spell.dbc`<br>

<br>`SpellIcon.dbc`<br>

<br>`SpellVisual.dbc` (Animation) | SQL: `spell_linked_spell` (Triggering)<br>

<br>Lua/C++: If custom mechanic needed | **High** | Conflicts are common. Requires a strict ID registry (e.g., "Mages use IDs 80000-81000"). |
| **Change Spell Data** | `Spell.dbc` (Dmg, Mana, Cast Time) | SQL: `spell_bonus_data` (Scaling)<br>

<br>SQL: `spell_custom_attr` | **Medium** | "Buff Fireball by 10%." Simple, but client/server must match or tooltips will lie. |
| **Modify Talent Tree** | `Talent.dbc` (Position)<br>

<br>`TalentTab.dbc` (Background)<br>

<br>`Spell.dbc` (The talent effect) | None (Server trusts the spell ID learned) | **Very High** | The UI breaks easily if arrows/dependencies are wrong. Hard to crowdsource. |
| **Change Racial Traits** | `Spell.dbc` (The new passive)<br>

<br>`SkillLineAbility.dbc` (Auto-learn) | SQL: `player_levelstats` (Base stats) | **High** | "Give Orcs +1% Hit." Requires editing core spell files. |
| **Add New Class** | `ChrClasses.dbc`, `CharBaseInfo.dbc`<br>

<br>`Spell.dbc` (Entire kit)<br>

<br>UI Textures | **Core Rewrite** (C++) | **Impossible** | *Avoid this.* 3.3.5a has hardcoded limits on class count. Replace an existing class instead. |

---

### **Category 3: The Armory (Items & Loot)**

| Use Case | Client-Side Files (The Patch) | Server-Side Files (The DB/Core) | Complexity | Notes |
| --- | --- | --- | --- | --- |
| **Add New Item** | `Item.dbc` (Visual/Sound link)<br>

<br>`ItemDisplayInfo.dbc`<br>

<br>`.m2` + `.blp` (Model) | SQL: `item_template` (Stats)<br>

<br>SQL: `item_enchantment_template` | **Medium** | The most common mod. "Add Ashbringer." Easy to pipeline. |
| **Create Item Set** | `ItemSet.dbc` (Bonuses) | SQL: `item_template` (Link to Set ID) | **Low** | "New Tier 11 Set." Defines "2 pieces = +50 Crit." |
| **Modify Loot Tables** | None | SQL: `creature_loot_template`<br>

<br>SQL: `gameobject_loot_template` | **Low** | Pure SQL. "Make Ragnaros drop 2x Gold." |
| **Custom Crafting Recipe** | `Spell.dbc` (The "Craft" action)<br>

<br>`SkillLineAbility.dbc` | SQL: `item_template` (Reagents req) | **Medium** | Requires making a "Spell" that creates an "Item." |

---

### **Category 4: Creatures & Encounters**

| Use Case | Client-Side Files (The Patch) | Server-Side Files (The DB/Core) | Complexity | Notes |
| --- | --- | --- | --- | --- |
| **Add New Creature** | `.m2` + `.blp` (Model)<br>

<br>`CreatureDisplayInfo.dbc`<br>

<br>`CreatureModelData.dbc` | SQL: `creature_template` (Stats/Faction) | **Medium** | "Add a Fel-Orc." If using existing models, Client side is skipped (Low difficulty). |
| **Update Boss Mechanics** | `Spell.dbc` (If boss uses new spell) | **Lua (Eluna)** or C++ Script<br>

<br>SQL: `creature_text` (Yelling) | **High** | "Boss enrages at 30%." Logic is all server-side. |
| **Add Vendor/Trainer** | None | SQL: `npc_vendor`<br>

<br>SQL: `npc_trainer` | **Very Low** | "Add an Apple vendor." Easiest task for beginners. |
| **Change NPC Pathing** | None | SQL: `creature_addon` (Waypoints)<br>

<br>SQL: `waypoint_data` | **Medium** | "Guard patrols the city." Done via GM commands or DB. |

---

### **Category 5: Narrative & Quests**

| Use Case | Client-Side Files (The Patch) | Server-Side Files (The DB/Core) | Complexity | Notes |
| --- | --- | --- | --- | --- |
| **Add New Quest** | None | SQL: `quest_template`<br>

<br>SQL: `quest_offer_reward` | **Low** | "Kill 10 Rats." Text-heavy, great for writers. |
| **Create Quest Chain** | None | SQL: `quest_template` (NextQuestId)<br>

<br>SQL: `conditions` (Reqs) | **Medium** | Requires logic: "Must finish Quest A to see Quest B." |
| **Add Object Interaction** | `GameObjectDisplayInfo.dbc` | SQL: `gameobject_template` | **Low** | "Click the Ancient Stone." |
| **Custom Teleporter** | None | SQL: `smart_scripts` or Lua | **Low** | "NPC teleports you to Mall." |

---

### **Category 6: System & UI**

| Use Case | Client-Side Files (The Patch) | Server-Side Files (The DB/Core) | Complexity | Notes |
| --- | --- | --- | --- | --- |
| **Add Playable Race** | `ChrRaces.dbc`<br>

<br>`CharStartOutfit.dbc`<br>

<br>Hundreds of `.m2` (Helm fixes) | C++ Core (Race flags/Start location)<br>

<br>SQL: `player_levelstats` | **Extreme** | "Play as Goblins." Requires refitting every helmet in the game to the new head. |
| **Custom UI Frame** | `Interface/AddOns/`<br>

<br>`.xml`, `.lua` | None | **Medium** | "New LFG Tool." Can be done entirely via AddOn API. |
| **Modify Flight Paths** | `TaxiNodes.dbc`<br>

<br>`TaxiPath.dbc` | SQL: `creature_template` (Flight Master) | **High** | Adding a new Flight Path requires drawing the line coordinates in the DBC. |

### **Summary of "Crowd-Sourceable" Tasks**

* **Green Light (Open to everyone):** Items, Quests, Loot, Vendors, simple Zone updates (Scenery).
* **Yellow Light (Vetted modders only):** New Spells, Dungeon Scripting, Item Sets, Texture/Model imports.
* **Red Light (Core Team only):** Map Geometry (ADTs), Core Talents, Playable Races, complex Pathing/Collision.