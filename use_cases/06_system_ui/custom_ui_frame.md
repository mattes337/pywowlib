# Custom UI Frame (WoW 3.3.5a AddOn Development)

## Complexity Rating: Moderate

Creating custom UI frames in World of Warcraft 3.3.5a involves writing AddOns using
Blizzard's XML layout system and Lua scripting API. Unlike most pywowlib use cases
that modify DBC files or server databases, AddOn development is a purely client-side
activity. The AddOn files live in the `Interface/AddOns/` directory and are loaded by
the WoW client at startup. No server-side changes are needed for UI-only
modifications.

This guide covers the full AddOn development pipeline: directory structure, TOC file
format, XML layout elements, Lua scripting APIs, event handling, and how to package
AddOns into MPQ patches for distribution. The walkthrough example builds a custom
LFG (Looking For Group) tool addon from scratch.

---

## Table of Contents

1. [Overview and Architecture](#1-overview-and-architecture)
2. [Prerequisites](#2-prerequisites)
3. [AddOn Directory Structure](#3-addon-directory-structure)
4. [TOC File Format](#4-toc-file-format)
5. [XML Layout Reference](#5-xml-layout-reference)
6. [Lua API Reference](#6-lua-api-reference)
7. [Event System](#7-event-system)
8. [Step-by-Step: Building a Custom LFG Tool](#8-step-by-step-building-a-custom-lfg-tool)
9. [Advanced XML Elements](#9-advanced-xml-elements)
10. [Slash Commands](#10-slash-commands)
11. [Saved Variables (Persistent Data)](#11-saved-variables-persistent-data)
12. [Packaging AddOns in MPQ Archives](#12-packaging-addons-in-mpq-archives)
13. [Debugging Techniques](#13-debugging-techniques)
14. [Common Pitfalls and Troubleshooting](#14-common-pitfalls-and-troubleshooting)
15. [Cross-References](#15-cross-references)

---

## 1. Overview and Architecture

The WoW 3.3.5a UI framework is a layered system:

```
+-------------------------------------------------------+
|  WoW Client Window                                     |
|  +---------------------------------------------------+|
|  |  Blizzard Default UI (FrameXML/)                   ||
|  |  +-----------------------------------------------+||
|  |  |  Your Custom AddOns (Interface/AddOns/)        |||
|  |  |  +-------------------------------------------+|||
|  |  |  |  XML Layout  -->  Lua Scripts              ||||
|  |  |  |  (structure)      (behavior)               ||||
|  |  |  +-------------------------------------------+|||
|  |  +-----------------------------------------------+||
|  +---------------------------------------------------+|
+-------------------------------------------------------+
```

**Key principles:**

- **XML** defines the visual structure: frames, buttons, textures, fonts, positions.
- **Lua** defines the behavior: event handlers, click responses, data processing.
- **Events** are the communication channel between the game engine and your code.
  The engine fires events (e.g., `PLAYER_LOGIN`, `CHAT_MSG_CHANNEL`) and your Lua
  code responds to them.
- **Frames** are the fundamental UI building block. Everything visible on screen is
  a frame or a child of a frame.

### API Version

WoW 3.3.5a (build 12340) uses Interface version `30300`. This determines which API
functions and widget types are available. Retail WoW APIs are significantly different
and incompatible -- always reference 3.3.5-specific documentation.

---

## 2. Prerequisites

### Required Knowledge

- Basic **Lua** syntax (variables, functions, tables, string manipulation).
- Basic understanding of **XML** structure (tags, attributes, nesting).
- Familiarity with the **WoW game client** and its UI elements.

### Required Tools

| Tool | Purpose |
|------|---------|
| Text editor (VS Code, Notepad++, etc.) | Editing XML and Lua files |
| WoW 3.3.5a client | Testing the addon in-game |
| WoW AddOn Studio (optional) | Visual frame editor for 3.3.5a |
| BugSack / BugGrabber addons (optional) | Captures Lua errors in-game |
| `/console scriptErrors 1` | Enable in-game error display |

### File Encoding

All XML and Lua files must be saved as **UTF-8 without BOM**. The WoW client will
reject files with incorrect encoding or byte order marks.

---

## 3. AddOn Directory Structure

Each AddOn lives in its own subdirectory under `Interface/AddOns/`:

```
World of Warcraft/
  Interface/
    AddOns/
      MyCustomAddon/              <-- AddOn root directory
        MyCustomAddon.toc         <-- Table of Contents (REQUIRED)
        MyCustomAddon.xml         <-- XML layout file(s)
        MyCustomAddon.lua         <-- Lua script file(s)
        Locales/                  <-- Optional: localization strings
          enUS.lua
          deDE.lua
        Textures/                 <-- Optional: custom textures
          background.tga
          icon.tga
        Libs/                     <-- Optional: embedded libraries
          LibStub/
            LibStub.lua
```

### Naming Conventions

- The directory name, TOC file name, and "Title" field should all match.
- Use PascalCase or camelCase for the addon name (e.g., `MyCustomAddon`).
- Avoid spaces and special characters in directory names.
- File names are case-sensitive on some operating systems.

---

## 4. TOC File Format

The `.toc` (Table of Contents) file tells the WoW client what files to load and in
what order. It is a plain text file with a specific format.

### Structure

```
## Interface: 30300
## Title: My Custom Addon
## Notes: A detailed description of what this addon does.
## Author: YourName
## Version: 1.0.0
## SavedVariables: MyCustomAddonDB
## SavedVariablesPerCharacter: MyCustomAddonCharDB
## Dependencies: SomeOtherAddon
## OptionalDeps: LibStub, CallbackHandler-1.0

# Load order matters! Libraries first, then core, then UI.
Libs\LibStub\LibStub.lua
Locales\enUS.lua
MyCustomAddon.lua
MyCustomAddon.xml
```

### TOC Metadata Fields

| Field | Required | Description |
|-------|----------|-------------|
| `## Interface` | **Yes** | Client interface version. Must be `30300` for WoW 3.3.5a. If this does not match, the addon will be marked "out of date" and disabled by default. |
| `## Title` | **Yes** | Display name shown in the AddOns list on the character selection screen. Supports color codes: `|cFF00FF00Green Title|r`. |
| `## Notes` | No | Description shown when hovering over the addon name in the list. |
| `## Author` | No | Author name displayed in the addon list. |
| `## Version` | No | Version string for your reference. Not enforced by the client. |
| `## SavedVariables` | No | Comma-separated list of global Lua variable names that persist between sessions. These are saved to `WTF/Account/<name>/SavedVariables/<AddonName>.lua`. |
| `## SavedVariablesPerCharacter` | No | Same as above but saved per-character in `WTF/Account/<name>/<server>/<character>/SavedVariables/`. |
| `## Dependencies` | No | Comma-separated list of addons that MUST be loaded before this one. If a dependency is missing, this addon will not load. |
| `## OptionalDeps` | No | Comma-separated list of addons that SHOULD be loaded before this one if present, but are not required. |
| `## DefaultState` | No | `enabled` (default) or `disabled`. Controls whether the addon is enabled by default for new characters. |
| `## LoadOnDemand` | No | `1` to make this addon load only when explicitly requested via `LoadAddOn("name")`. |

### File Loading Order

Files are loaded in the exact order they appear in the TOC. This is critical:

1. **Libraries first** -- External libraries like LibStub must be loaded before any
   code that depends on them.
2. **Localization** -- Locale strings should be available before the main code runs.
3. **Core Lua** -- Main addon logic that creates data structures and functions.
4. **XML layouts** -- XML files that reference Lua functions defined in the core.

If a Lua file references a function that has not been defined yet (because its file
has not been loaded), you will get a nil reference error.

---

## 5. XML Layout Reference

The WoW UI uses a custom XML schema to define frame hierarchies. All UI elements
are represented as XML tags with attributes and child elements.

### Root Element

Every XML layout file must begin with the `<Ui>` root element:

```xml
<Ui xmlns="http://www.blizzard.com/wow/ui/"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.blizzard.com/wow/ui/ ..\FrameXML\UI.xsd">

    <!-- All frames go here -->

</Ui>
```

### Core XML Element Types

#### Frame

The fundamental container element. All other UI elements are either Frames or
children of Frames.

```xml
<Frame name="MyAddonMainFrame" parent="UIParent"
       toplevel="true" movable="true" enableMouse="true"
       hidden="false" frameStrata="MEDIUM">
    <Size x="400" y="300"/>
    <Anchors>
        <Anchor point="CENTER" relativeTo="UIParent" relativePoint="CENTER">
            <Offset x="0" y="0"/>
        </Anchor>
    </Anchors>
    <Backdrop bgFile="Interface\DialogFrame\UI-DialogBox-Background"
              edgeFile="Interface\DialogFrame\UI-DialogBox-Border" tile="true">
        <BackgroundInsets left="11" right="12" top="12" bottom="11"/>
        <TileSize val="32"/>
        <EdgeSize val="32"/>
    </Backdrop>
    <Layers>
        <Layer level="ARTWORK">
            <FontString name="$parentTitle" inherits="GameFontNormalLarge"
                        text="My Custom Frame">
                <Anchors>
                    <Anchor point="TOP" relativePoint="TOP">
                        <Offset x="0" y="-15"/>
                    </Anchor>
                </Anchors>
            </FontString>
        </Layer>
    </Layers>
    <Scripts>
        <OnLoad>MyAddon_OnLoad(self)</OnLoad>
        <OnShow>MyAddon_OnShow(self)</OnShow>
        <OnHide>MyAddon_OnHide(self)</OnHide>
        <OnDragStart>self:StartMoving()</OnDragStart>
        <OnDragStop>self:StopMovingOrSizing()</OnDragStop>
    </Scripts>
</Frame>
```

**Key Frame attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | string | Global Lua name for this frame. Use `$parent` prefix to create hierarchical names (e.g., `$parentTitle` becomes `MyAddonMainFrameTitle`). |
| `parent` | string | Parent frame name. `UIParent` is the root of the visible UI. |
| `toplevel` | boolean | If true, clicking this frame brings it to the front. |
| `movable` | boolean | If true, the frame can be dragged with `StartMoving()`. |
| `enableMouse` | boolean | If true, the frame receives mouse events. |
| `hidden` | boolean | If true, the frame starts hidden (`frame:Show()` to reveal). |
| `frameStrata` | string | Draw order layer: `BACKGROUND`, `LOW`, `MEDIUM`, `HIGH`, `DIALOG`, `FULLSCREEN`, `FULLSCREEN_DIALOG`, `TOOLTIP`. |
| `inherits` | string | Template to inherit from (e.g., `BasicFrameTemplate`). |

#### Button

Clickable UI element with normal, pushed, highlighted, and disabled states:

```xml
<Button name="$parentCloseButton" inherits="UIPanelCloseButton">
    <Anchors>
        <Anchor point="TOPRIGHT" relativePoint="TOPRIGHT">
            <Offset x="-5" y="-5"/>
        </Anchor>
    </Anchors>
    <Scripts>
        <OnClick>MyAddon_OnCloseClick(self)</OnClick>
    </Scripts>
</Button>

<!-- Custom styled button -->
<Button name="$parentSearchButton" text="Search">
    <Size x="120" y="25"/>
    <Anchors>
        <Anchor point="BOTTOM" relativePoint="BOTTOM">
            <Offset x="0" y="20"/>
        </Anchor>
    </Anchors>
    <NormalTexture file="Interface\Buttons\UI-Panel-Button-Up"/>
    <PushedTexture file="Interface\Buttons\UI-Panel-Button-Down"/>
    <HighlightTexture file="Interface\Buttons\UI-Panel-Button-Highlight"
                      alphaMode="ADD"/>
    <NormalFont style="GameFontNormal"/>
    <HighlightFont style="GameFontHighlight"/>
    <Scripts>
        <OnClick>MyAddon_OnSearchClick(self)</OnClick>
    </Scripts>
</Button>
```

#### FontString

Text display element. Must be placed inside a `<Layer>` within `<Layers>`:

```xml
<Layers>
    <Layer level="OVERLAY">
        <FontString name="$parentStatusText" inherits="GameFontNormal"
                    justifyH="LEFT" text="Status: Ready">
            <Size x="200" y="20"/>
            <Anchors>
                <Anchor point="BOTTOMLEFT" relativePoint="BOTTOMLEFT">
                    <Offset x="15" y="10"/>
                </Anchor>
            </Anchors>
            <Color r="0.8" g="1.0" b="0.8"/>
        </FontString>
    </Layer>
</Layers>
```

**Layer levels (draw order within a frame):**

| Level | Order | Typical Use |
|-------|-------|-------------|
| `BACKGROUND` | 1 (back) | Background textures, tiling patterns |
| `BORDER` | 2 | Border artwork |
| `ARTWORK` | 3 | Main content artwork |
| `OVERLAY` | 4 | Text, icons on top of artwork |
| `HIGHLIGHT` | 5 (front) | Hover/selection highlights |

#### Texture

Image display element. Also placed inside `<Layers>`:

```xml
<Layers>
    <Layer level="ARTWORK">
        <Texture name="$parentIcon"
                 file="Interface\Icons\INV_Misc_GroupLooking">
            <Size x="32" y="32"/>
            <Anchors>
                <Anchor point="TOPLEFT" relativePoint="TOPLEFT">
                    <Offset x="15" y="-15"/>
                </Anchor>
            </Anchors>
        </Texture>
    </Layer>
</Layers>
```

#### EditBox

Text input field:

```xml
<EditBox name="$parentSearchBox" autoFocus="false" letters="100">
    <Size x="200" y="20"/>
    <Anchors>
        <Anchor point="TOP" relativePoint="TOP">
            <Offset x="0" y="-50"/>
        </Anchor>
    </Anchors>
    <Layers>
        <Layer level="BACKGROUND">
            <Texture name="$parentSearchBoxBg"
                     file="Interface\Common\Common-Input-Border">
                <Size x="210" y="28"/>
                <Anchors>
                    <Anchor point="CENTER"/>
                </Anchors>
            </Texture>
        </Layer>
    </Layers>
    <FontString inherits="ChatFontNormal"/>
    <Scripts>
        <OnEnterPressed>MyAddon_OnSearchEnter(self)</OnEnterPressed>
        <OnEscapePressed>self:ClearFocus()</OnEscapePressed>
    </Scripts>
</EditBox>
```

#### ScrollFrame

Scrollable content area:

```xml
<ScrollFrame name="$parentScrollFrame" inherits="FauxScrollFrameTemplate">
    <Size x="360" y="200"/>
    <Anchors>
        <Anchor point="TOP" relativePoint="TOP">
            <Offset x="0" y="-80"/>
        </Anchor>
    </Anchors>
    <Scripts>
        <OnVerticalScroll>
            FauxScrollFrame_OnVerticalScroll(self, offset, 20,
                MyAddon_UpdateScrollFrame)
        </OnVerticalScroll>
    </Scripts>
</ScrollFrame>
```

#### CheckButton

Toggle checkbox:

```xml
<CheckButton name="$parentFilterCheck" inherits="UICheckButtonTemplate">
    <Anchors>
        <Anchor point="TOPLEFT" relativePoint="TOPLEFT">
            <Offset x="15" y="-100"/>
        </Anchor>
    </Anchors>
    <Scripts>
        <OnClick>MyAddon_OnFilterToggle(self)</OnClick>
    </Scripts>
</CheckButton>
```

### Anchor Points Reference

Anchors control positioning. Each frame can have multiple anchors that define how it
is positioned relative to another frame.

```
TOPLEFT      TOP       TOPRIGHT
   +----------+----------+
   |                      |
LEFT       CENTER       RIGHT
   |                      |
   +----------+----------+
BOTTOMLEFT  BOTTOM  BOTTOMRIGHT
```

**Anchor syntax:**

```xml
<Anchor point="TOPLEFT"             -- This frame's anchor point
        relativeTo="ParentFrame"    -- Reference frame (default: parent)
        relativePoint="TOPLEFT">    -- Point on the reference frame
    <Offset x="10" y="-10"/>        -- Pixel offset from anchor
</Anchor>
```

**Common positioning patterns:**

```xml
<!-- Center in parent -->
<Anchor point="CENTER" relativeTo="UIParent" relativePoint="CENTER"/>

<!-- Below another element with 5px gap -->
<Anchor point="TOP" relativeTo="$parentTitle" relativePoint="BOTTOM">
    <Offset x="0" y="-5"/>
</Anchor>

<!-- Fill parent width with margins -->
<Anchor point="LEFT" relativePoint="LEFT"><Offset x="10" y="0"/></Anchor>
<Anchor point="RIGHT" relativePoint="RIGHT"><Offset x="-10" y="0"/></Anchor>
```

---

## 6. Lua API Reference

### Frame Creation and Manipulation

```lua
-- Create a frame programmatically (alternative to XML)
local frame = CreateFrame("Frame", "MyFrameName", UIParent)
frame:SetSize(400, 300)
frame:SetPoint("CENTER", UIParent, "CENTER", 0, 0)

-- Create a button
local btn = CreateFrame("Button", "MyButton", frame, "UIPanelButtonTemplate")
btn:SetSize(120, 25)
btn:SetPoint("BOTTOM", frame, "BOTTOM", 0, 20)
btn:SetText("Click Me")

-- Create a font string (text label)
local text = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
text:SetPoint("TOP", frame, "TOP", 0, -20)
text:SetText("Hello World")

-- Create a texture
local tex = frame:CreateTexture(nil, "BACKGROUND")
tex:SetAllPoints(frame)
tex:SetTexture("Interface\\DialogFrame\\UI-DialogBox-Background")
```

### Positioning API (SetPoint)

```lua
-- SetPoint(point, relativeTo, relativePoint, offsetX, offsetY)
frame:SetPoint("CENTER", UIParent, "CENTER", 0, 0)

-- Clear all points and reposition
frame:ClearAllPoints()
frame:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 100, -100)

-- Multiple anchors (stretches frame between two points)
frame:SetPoint("TOPLEFT", parent, "TOPLEFT", 10, -10)
frame:SetPoint("BOTTOMRIGHT", parent, "BOTTOMRIGHT", -10, 10)
```

### Script Handlers (SetScript)

```lua
-- Mouse click handler
btn:SetScript("OnClick", function(self, button)
    if button == "LeftButton" then
        print("Left clicked!")
    elseif button == "RightButton" then
        print("Right clicked!")
    end
end)

-- Mouse enter/leave (hover effects)
frame:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText("Hover text here")
    GameTooltip:Show()
end)

frame:SetScript("OnLeave", function(self)
    GameTooltip:Hide()
end)

-- Frame shown/hidden
frame:SetScript("OnShow", function(self)
    print("Frame is now visible")
end)

frame:SetScript("OnHide", function(self)
    print("Frame is now hidden")
end)

-- Update handler (called every frame render)
frame:SetScript("OnUpdate", function(self, elapsed)
    -- elapsed = seconds since last OnUpdate call
    self.timer = (self.timer or 0) + elapsed
    if self.timer >= 1.0 then
        self.timer = 0
        -- Do something every second
    end
end)
```

### Event Registration (RegisterEvent)

```lua
-- Register for specific game events
frame:RegisterEvent("PLAYER_LOGIN")
frame:RegisterEvent("CHAT_MSG_CHANNEL")
frame:RegisterEvent("GROUP_ROSTER_UPDATE")

-- Event handler
frame:SetScript("OnEvent", function(self, event, ...)
    if event == "PLAYER_LOGIN" then
        print("Player logged in!")
    elseif event == "CHAT_MSG_CHANNEL" then
        local message, sender, _, _, _, _, _, channelNum, channelName = ...
        print(sender .. ": " .. message)
    elseif event == "GROUP_ROSTER_UPDATE" then
        -- Party/raid composition changed
        MyAddon_UpdateGroupDisplay()
    end
end)

-- Unregister when no longer needed
frame:UnregisterEvent("CHAT_MSG_CHANNEL")

-- Unregister all events
frame:UnregisterAllEvents()
```

### Common WoW API Functions (3.3.5a)

```lua
-- Player information
local name = UnitName("player")              -- Character name
local level = UnitLevel("player")            -- Character level
local class = UnitClass("player")            -- Localized class name
local _, classFile = UnitClass("player")     -- Non-localized: "WARRIOR", etc.
local health = UnitHealth("player")          -- Current HP
local maxHealth = UnitHealthMax("player")    -- Maximum HP
local power = UnitMana("player")             -- Current mana/rage/energy
local zone = GetZoneText()                   -- Current zone name
local subzone = GetSubZoneText()             -- Current subzone name
local mapID = GetCurrentMapAreaID()          -- Numeric map area ID

-- Group information
local numParty = GetNumPartyMembers()        -- 0-4
local numRaid = GetNumRaidMembers()          -- 0-40
local inInstance, instanceType = IsInInstance()

-- Chat
SendChatMessage("Hello!", "SAY")
SendChatMessage("LFG tank!", "CHANNEL", nil, 4)  -- Channel 4 = LFG

-- Frame manipulation
frame:Show()
frame:Hide()
frame:SetAlpha(0.8)                          -- Transparency (0-1)
frame:EnableMouse(true)
frame:SetMovable(true)
frame:RegisterForDrag("LeftButton")

-- Sound
PlaySound("igMainMenuOpen")
PlaySoundFile("Sound\\Interface\\iQuestUpdate.ogg")

-- Timer (C_Timer not available in 3.3.5a, use OnUpdate or this pattern)
-- For delayed execution, use OnUpdate timers
```

---

## 7. Event System

Events are the backbone of AddOn development. The WoW client fires events when
game state changes, and your Lua code responds to them.

### Critical Events for AddOn Initialization

| Event | When Fired | Typical Use |
|-------|------------|-------------|
| `ADDON_LOADED` | When a specific addon finishes loading. `arg1` = addon name. | Initialize addon state, load saved variables. |
| `PLAYER_LOGIN` | After the player has fully logged in and all data is available. | Safe to access player data, set up UI. |
| `PLAYER_ENTERING_WORLD` | After loading screen finishes (login, reload, zone change). | Update zone-dependent displays. |
| `VARIABLES_LOADED` | After all saved variables have been loaded from disk. | Access SavedVariables data. |

### Common Game Events

| Event | Arguments | Description |
|-------|-----------|-------------|
| `CHAT_MSG_SAY` | message, sender, language, ... | Player /say message |
| `CHAT_MSG_PARTY` | message, sender, ... | Party chat message |
| `CHAT_MSG_RAID` | message, sender, ... | Raid chat message |
| `CHAT_MSG_CHANNEL` | message, sender, language, channelName, ... , channelNum, ... | Channel message |
| `CHAT_MSG_WHISPER` | message, sender, ... | Incoming whisper |
| `GROUP_ROSTER_UPDATE` | (none) | Party or raid membership changed |
| `PLAYER_TARGET_CHANGED` | (none) | Player selected a new target |
| `ZONE_CHANGED` | (none) | Player moved to a different subzone |
| `ZONE_CHANGED_NEW_AREA` | (none) | Player moved to a different zone |
| `UNIT_HEALTH` | unitId | A unit's health changed |
| `PLAYER_REGEN_ENABLED` | (none) | Player left combat |
| `PLAYER_REGEN_DISABLED` | (none) | Player entered combat |
| `BAG_UPDATE` | bagSlot | Inventory changed |

### Event Handler Pattern

```lua
local frame = CreateFrame("Frame")

-- Register events
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")

-- Central event dispatcher
frame:SetScript("OnEvent", function(self, event, ...)
    if self[event] then
        self[event](self, ...)
    end
end)

-- Event handlers as methods
function frame:ADDON_LOADED(addonName)
    if addonName ~= "MyCustomAddon" then return end
    -- Initialize saved variables, set defaults
    if not MyCustomAddonDB then
        MyCustomAddonDB = { enabled = true, scale = 1.0 }
    end
    print("MyCustomAddon loaded!")
end

function frame:PLAYER_LOGIN()
    -- Player data is now available
    local name = UnitName("player")
    print("Welcome, " .. name .. "!")
end
```

---

## 8. Step-by-Step: Building a Custom LFG Tool

This section walks through building a complete LFG (Looking For Group) tool addon
that allows players to list their group needs and browse other groups.

### Step 1: Create the Directory Structure

```
Interface/AddOns/CustomLFGTool/
    CustomLFGTool.toc
    CustomLFGTool.lua
    CustomLFGTool.xml
```

### Step 2: Write the TOC File

```
## Interface: 30300
## Title: Custom LFG Tool
## Notes: A custom Looking For Group tool for finding and listing dungeon groups.
## Author: YourName
## Version: 1.0.0
## SavedVariables: CustomLFGToolDB

CustomLFGTool.lua
CustomLFGTool.xml
```

### Step 3: Write the Core Lua Logic

Create `CustomLFGTool.lua`:

```lua
-- ============================================================
-- CustomLFGTool - Core Logic
-- ============================================================

-- Namespace table to avoid global pollution
CustomLFGTool = CustomLFGTool or {}

-- Internal state
local LFG = CustomLFGTool
LFG.listings = {}        -- Current group listings
LFG.myListing = nil      -- Player's own listing
LFG.LFG_CHANNEL = "CustomLFG"  -- Addon communication channel

-- Dungeon database (subset of WotLK dungeons)
LFG.DUNGEONS = {
    { id = 1,  name = "Utgarde Keep",          minLevel = 69, maxLevel = 72 },
    { id = 2,  name = "The Nexus",             minLevel = 71, maxLevel = 73 },
    { id = 3,  name = "Azjol-Nerub",           minLevel = 72, maxLevel = 74 },
    { id = 4,  name = "Ahn'kahet",             minLevel = 73, maxLevel = 75 },
    { id = 5,  name = "Drak'Tharon Keep",      minLevel = 74, maxLevel = 76 },
    { id = 6,  name = "Violet Hold",           minLevel = 75, maxLevel = 77 },
    { id = 7,  name = "Gundrak",               minLevel = 76, maxLevel = 78 },
    { id = 8,  name = "Halls of Stone",        minLevel = 77, maxLevel = 79 },
    { id = 9,  name = "Halls of Lightning",    minLevel = 78, maxLevel = 80 },
    { id = 10, name = "The Oculus",            minLevel = 79, maxLevel = 80 },
    { id = 11, name = "Culling of Stratholme", minLevel = 79, maxLevel = 80 },
    { id = 12, name = "Utgarde Pinnacle",      minLevel = 79, maxLevel = 80 },
    { id = 13, name = "Trial of the Champion", minLevel = 80, maxLevel = 80 },
    { id = 14, name = "Forge of Souls",        minLevel = 80, maxLevel = 80 },
    { id = 15, name = "Pit of Saron",          minLevel = 80, maxLevel = 80 },
    { id = 16, name = "Halls of Reflection",   minLevel = 80, maxLevel = 80 },
}

-- Role definitions
LFG.ROLES = {
    TANK   = { name = "Tank",   icon = "Interface\\LFGFrame\\UI-LFG-ICON-PORTRAITROLES",
               coords = {0, 0.25, 0, 0.25} },
    HEALER = { name = "Healer", icon = "Interface\\LFGFrame\\UI-LFG-ICON-PORTRAITROLES",
               coords = {0.25, 0.5, 0, 0.25} },
    DPS    = { name = "DPS",    icon = "Interface\\LFGFrame\\UI-LFG-ICON-PORTRAITROLES",
               coords = {0.5, 0.75, 0, 0.25} },
}


-- ============================================================
-- Initialization
-- ============================================================

function LFG:Initialize()
    -- Load saved settings
    if not CustomLFGToolDB then
        CustomLFGToolDB = {
            minimapButton = true,
            autoJoinChannel = true,
            filterMinLevel = true,
        }
    end
    self.db = CustomLFGToolDB

    -- Register addon communication prefix
    RegisterAddonMessagePrefix("CLFG")

    self:Print("Custom LFG Tool loaded. Type /lfgt to open.")
end


-- ============================================================
-- Listing Management
-- ============================================================

function LFG:CreateListing(dungeonId, rolesNeeded, comment)
    local playerName = UnitName("player")
    local _, classFile = UnitClass("player")
    local level = UnitLevel("player")

    self.myListing = {
        leader = playerName,
        class = classFile,
        level = level,
        dungeonId = dungeonId,
        rolesNeeded = rolesNeeded,  -- e.g., { "TANK", "HEALER", "DPS" }
        comment = comment or "",
        timestamp = time(),
    }

    -- Broadcast to other addon users
    self:BroadcastListing()
    self:Print("Listed for: " .. self:GetDungeonName(dungeonId))
end


function LFG:RemoveListing()
    if self.myListing then
        self:BroadcastRemoval()
        self.myListing = nil
        self:Print("Listing removed.")
    end
end


function LFG:GetDungeonName(dungeonId)
    for _, d in ipairs(self.DUNGEONS) do
        if d.id == dungeonId then
            return d.name
        end
    end
    return "Unknown Dungeon"
end


-- ============================================================
-- Communication (Addon Messages)
-- ============================================================

function LFG:BroadcastListing()
    if not self.myListing then return end
    local data = string.format("LIST:%d:%s:%s:%d:%s",
        self.myListing.dungeonId,
        self.myListing.leader,
        self.myListing.class,
        self.myListing.level,
        table.concat(self.myListing.rolesNeeded, ",")
    )
    SendAddonMessage("CLFG", data, "CHANNEL",
        GetChannelName(self.LFG_CHANNEL))
end


function LFG:BroadcastRemoval()
    local data = "DELIST:" .. UnitName("player")
    SendAddonMessage("CLFG", data, "CHANNEL",
        GetChannelName(self.LFG_CHANNEL))
end


function LFG:OnAddonMessage(prefix, message, channel, sender)
    if prefix ~= "CLFG" then return end
    if sender == UnitName("player") then return end  -- Ignore own messages

    local command = message:match("^(%w+):")
    if command == "LIST" then
        local _, dungeonId, leader, class, level, roles =
            strsplit(":", message)
        dungeonId = tonumber(dungeonId)
        level = tonumber(level)

        self.listings[leader] = {
            leader = leader,
            class = class,
            level = level,
            dungeonId = dungeonId,
            rolesNeeded = { strsplit(",", roles or "") },
            timestamp = time(),
        }

        self:UpdateScrollFrame()

    elseif command == "DELIST" then
        local _, leader = strsplit(":", message)
        self.listings[leader] = nil
        self:UpdateScrollFrame()
    end
end


-- ============================================================
-- Scroll Frame Update
-- ============================================================

function LFG:UpdateScrollFrame()
    if not CustomLFGToolScrollFrame then return end

    -- Build sorted listing array
    local sorted = {}
    for _, listing in pairs(self.listings) do
        table.insert(sorted, listing)
    end
    table.sort(sorted, function(a, b)
        return a.timestamp > b.timestamp
    end)

    local numEntries = #sorted
    local ENTRY_HEIGHT = 20
    local VISIBLE_ENTRIES = 10

    FauxScrollFrame_Update(CustomLFGToolScrollFrame,
        numEntries, VISIBLE_ENTRIES, ENTRY_HEIGHT)

    local offset = FauxScrollFrame_GetOffset(CustomLFGToolScrollFrame)

    for i = 1, VISIBLE_ENTRIES do
        local index = offset + i
        local row = _G["CustomLFGToolEntry" .. i]
        if row then
            if index <= numEntries then
                local listing = sorted[index]
                local dungeonName = self:GetDungeonName(listing.dungeonId)
                local rolesStr = table.concat(listing.rolesNeeded, "/")

                _G[row:GetName() .. "DungeonText"]:SetText(dungeonName)
                _G[row:GetName() .. "LeaderText"]:SetText(listing.leader)
                _G[row:GetName() .. "RolesText"]:SetText("Need: " .. rolesStr)
                _G[row:GetName() .. "LevelText"]:SetText(
                    tostring(listing.level))

                row:Show()
            else
                row:Hide()
            end
        end
    end
end


-- ============================================================
-- Utility
-- ============================================================

function LFG:Print(msg)
    DEFAULT_CHAT_FRAME:AddMessage("|cFF00CCFF[LFG Tool]|r " .. msg)
end


-- ============================================================
-- Slash Command
-- ============================================================

SLASH_CUSTOMLFGTOOL1 = "/lfgt"
SLASH_CUSTOMLFGTOOL2 = "/lfgtool"

SlashCmdList["CUSTOMLFGTOOL"] = function(msg)
    msg = msg:lower():trim()

    if msg == "list" then
        -- Show current listings count
        local count = 0
        for _ in pairs(CustomLFGTool.listings) do
            count = count + 1
        end
        CustomLFGTool:Print(count .. " active listings.")
    elseif msg == "clear" then
        CustomLFGTool:RemoveListing()
    else
        -- Toggle main frame visibility
        if CustomLFGToolMainFrame then
            if CustomLFGToolMainFrame:IsShown() then
                CustomLFGToolMainFrame:Hide()
            else
                CustomLFGToolMainFrame:Show()
            end
        end
    end
end
```

### Step 4: Write the XML Layout

Create `CustomLFGTool.xml`:

```xml
<Ui xmlns="http://www.blizzard.com/wow/ui/"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.blizzard.com/wow/ui/ ..\FrameXML\UI.xsd">

    <!-- ======================================================
         Entry Row Template (used for each listing in scroll list)
         ====================================================== -->
    <Button name="CustomLFGToolEntryTemplate" virtual="true">
        <Size x="340" y="20"/>
        <Layers>
            <Layer level="ARTWORK">
                <FontString name="$parentDungeonText" inherits="GameFontNormal"
                            justifyH="LEFT">
                    <Size x="140" y="20"/>
                    <Anchors>
                        <Anchor point="LEFT" relativePoint="LEFT">
                            <Offset x="5" y="0"/>
                        </Anchor>
                    </Anchors>
                </FontString>
                <FontString name="$parentLeaderText"
                            inherits="GameFontHighlightSmall" justifyH="LEFT">
                    <Size x="80" y="20"/>
                    <Anchors>
                        <Anchor point="LEFT" relativePoint="LEFT">
                            <Offset x="150" y="0"/>
                        </Anchor>
                    </Anchors>
                </FontString>
                <FontString name="$parentRolesText"
                            inherits="GameFontHighlightSmall" justifyH="LEFT">
                    <Size x="80" y="20"/>
                    <Anchors>
                        <Anchor point="LEFT" relativePoint="LEFT">
                            <Offset x="235" y="0"/>
                        </Anchor>
                    </Anchors>
                </FontString>
                <FontString name="$parentLevelText"
                            inherits="GameFontHighlightSmall" justifyH="RIGHT">
                    <Size x="30" y="20"/>
                    <Anchors>
                        <Anchor point="RIGHT" relativePoint="RIGHT">
                            <Offset x="-5" y="0"/>
                        </Anchor>
                    </Anchors>
                </FontString>
            </Layer>
        </Layers>
        <HighlightTexture file="Interface\QuestFrame\UI-QuestTitleHighlight"
                          alphaMode="ADD"/>
        <Scripts>
            <OnClick>CustomLFGTool:OnEntryClick(self)</OnClick>
            <OnEnter>
                GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
                local leader = _G[self:GetName().."LeaderText"]:GetText()
                GameTooltip:SetText("Click to whisper " .. (leader or ""))
                GameTooltip:Show()
            </OnEnter>
            <OnLeave>GameTooltip:Hide()</OnLeave>
        </Scripts>
    </Button>

    <!-- ======================================================
         Main Frame
         ====================================================== -->
    <Frame name="CustomLFGToolMainFrame" parent="UIParent" toplevel="true"
           movable="true" enableMouse="true" hidden="true"
           frameStrata="MEDIUM">
        <Size x="400" y="380"/>
        <Anchors>
            <Anchor point="CENTER" relativeTo="UIParent" relativePoint="CENTER">
                <Offset x="0" y="50"/>
            </Anchor>
        </Anchors>
        <Backdrop bgFile="Interface\DialogFrame\UI-DialogBox-Background"
                  edgeFile="Interface\DialogFrame\UI-DialogBox-Border"
                  tile="true">
            <BackgroundInsets left="11" right="12" top="12" bottom="11"/>
            <TileSize val="32"/>
            <EdgeSize val="32"/>
        </Backdrop>

        <Layers>
            <!-- Title -->
            <Layer level="ARTWORK">
                <FontString name="$parentTitleText"
                            inherits="GameFontNormalLarge"
                            text="Custom LFG Tool">
                    <Anchors>
                        <Anchor point="TOP" relativePoint="TOP">
                            <Offset x="0" y="-18"/>
                        </Anchor>
                    </Anchors>
                </FontString>

                <!-- Column headers -->
                <FontString inherits="GameFontNormalSmall" text="Dungeon"
                            justifyH="LEFT">
                    <Size x="140" y="15"/>
                    <Anchors>
                        <Anchor point="TOPLEFT" relativePoint="TOPLEFT">
                            <Offset x="25" y="-55"/>
                        </Anchor>
                    </Anchors>
                    <Color r="1.0" g="0.82" b="0.0"/>
                </FontString>
                <FontString inherits="GameFontNormalSmall" text="Leader"
                            justifyH="LEFT">
                    <Size x="80" y="15"/>
                    <Anchors>
                        <Anchor point="TOPLEFT" relativePoint="TOPLEFT">
                            <Offset x="170" y="-55"/>
                        </Anchor>
                    </Anchors>
                    <Color r="1.0" g="0.82" b="0.0"/>
                </FontString>
                <FontString inherits="GameFontNormalSmall" text="Need"
                            justifyH="LEFT">
                    <Size x="80" y="15"/>
                    <Anchors>
                        <Anchor point="TOPLEFT" relativePoint="TOPLEFT">
                            <Offset x="255" y="-55"/>
                        </Anchor>
                    </Anchors>
                    <Color r="1.0" g="0.82" b="0.0"/>
                </FontString>
                <FontString inherits="GameFontNormalSmall" text="Lv"
                            justifyH="RIGHT">
                    <Size x="30" y="15"/>
                    <Anchors>
                        <Anchor point="TOPRIGHT" relativePoint="TOPRIGHT">
                            <Offset x="-25" y="-55"/>
                        </Anchor>
                    </Anchors>
                    <Color r="1.0" g="0.82" b="0.0"/>
                </FontString>

                <!-- Status bar -->
                <FontString name="$parentStatusText"
                            inherits="GameFontHighlightSmall"
                            justifyH="LEFT" text="0 groups listed">
                    <Anchors>
                        <Anchor point="BOTTOMLEFT" relativePoint="BOTTOMLEFT">
                            <Offset x="20" y="15"/>
                        </Anchor>
                    </Anchors>
                    <Color r="0.7" g="0.7" b="0.7"/>
                </FontString>
            </Layer>
        </Layers>

        <Frames>
            <!-- Close button -->
            <Button name="$parentCloseButton"
                    inherits="UIPanelCloseButton">
                <Anchors>
                    <Anchor point="TOPRIGHT" relativePoint="TOPRIGHT">
                        <Offset x="-5" y="-5"/>
                    </Anchor>
                </Anchors>
            </Button>

            <!-- Scroll frame for listings -->
            <ScrollFrame name="CustomLFGToolScrollFrame"
                         inherits="FauxScrollFrameTemplate">
                <Size x="340" y="200"/>
                <Anchors>
                    <Anchor point="TOPLEFT" relativePoint="TOPLEFT">
                        <Offset x="20" y="-72"/>
                    </Anchor>
                </Anchors>
                <Scripts>
                    <OnVerticalScroll>
                        FauxScrollFrame_OnVerticalScroll(self, offset, 20,
                            function() CustomLFGTool:UpdateScrollFrame() end)
                    </OnVerticalScroll>
                </Scripts>
            </ScrollFrame>

            <!-- Listing entry rows (10 visible) -->
            <Button name="CustomLFGToolEntry1"
                    inherits="CustomLFGToolEntryTemplate">
                <Anchors>
                    <Anchor point="TOPLEFT"
                            relativeTo="CustomLFGToolScrollFrame"
                            relativePoint="TOPLEFT"/>
                </Anchors>
            </Button>
            <Button name="CustomLFGToolEntry2"
                    inherits="CustomLFGToolEntryTemplate">
                <Anchors>
                    <Anchor point="TOPLEFT"
                            relativeTo="CustomLFGToolEntry1"
                            relativePoint="BOTTOMLEFT"/>
                </Anchors>
            </Button>
            <Button name="CustomLFGToolEntry3"
                    inherits="CustomLFGToolEntryTemplate">
                <Anchors>
                    <Anchor point="TOPLEFT"
                            relativeTo="CustomLFGToolEntry2"
                            relativePoint="BOTTOMLEFT"/>
                </Anchors>
            </Button>
            <Button name="CustomLFGToolEntry4"
                    inherits="CustomLFGToolEntryTemplate">
                <Anchors>
                    <Anchor point="TOPLEFT"
                            relativeTo="CustomLFGToolEntry3"
                            relativePoint="BOTTOMLEFT"/>
                </Anchors>
            </Button>
            <Button name="CustomLFGToolEntry5"
                    inherits="CustomLFGToolEntryTemplate">
                <Anchors>
                    <Anchor point="TOPLEFT"
                            relativeTo="CustomLFGToolEntry4"
                            relativePoint="BOTTOMLEFT"/>
                </Anchors>
            </Button>
            <Button name="CustomLFGToolEntry6"
                    inherits="CustomLFGToolEntryTemplate">
                <Anchors>
                    <Anchor point="TOPLEFT"
                            relativeTo="CustomLFGToolEntry5"
                            relativePoint="BOTTOMLEFT"/>
                </Anchors>
            </Button>
            <Button name="CustomLFGToolEntry7"
                    inherits="CustomLFGToolEntryTemplate">
                <Anchors>
                    <Anchor point="TOPLEFT"
                            relativeTo="CustomLFGToolEntry6"
                            relativePoint="BOTTOMLEFT"/>
                </Anchors>
            </Button>
            <Button name="CustomLFGToolEntry8"
                    inherits="CustomLFGToolEntryTemplate">
                <Anchors>
                    <Anchor point="TOPLEFT"
                            relativeTo="CustomLFGToolEntry7"
                            relativePoint="BOTTOMLEFT"/>
                </Anchors>
            </Button>
            <Button name="CustomLFGToolEntry9"
                    inherits="CustomLFGToolEntryTemplate">
                <Anchors>
                    <Anchor point="TOPLEFT"
                            relativeTo="CustomLFGToolEntry8"
                            relativePoint="BOTTOMLEFT"/>
                </Anchors>
            </Button>
            <Button name="CustomLFGToolEntry10"
                    inherits="CustomLFGToolEntryTemplate">
                <Anchors>
                    <Anchor point="TOPLEFT"
                            relativeTo="CustomLFGToolEntry9"
                            relativePoint="BOTTOMLEFT"/>
                </Anchors>
            </Button>

            <!-- Refresh button -->
            <Button name="$parentRefreshButton" text="Refresh"
                    inherits="UIPanelButtonTemplate">
                <Size x="80" y="22"/>
                <Anchors>
                    <Anchor point="BOTTOMRIGHT" relativePoint="BOTTOMRIGHT">
                        <Offset x="-20" y="12"/>
                    </Anchor>
                </Anchors>
                <Scripts>
                    <OnClick>
                        CustomLFGTool:BroadcastListing()
                        CustomLFGTool:Print("Refreshing listings...")
                    </OnClick>
                </Scripts>
            </Button>
        </Frames>

        <Scripts>
            <OnLoad>
                -- Make frame draggable
                self:RegisterForDrag("LeftButton")
                -- Register game events
                self:RegisterEvent("ADDON_LOADED")
                self:RegisterEvent("CHAT_MSG_ADDON")
                self:RegisterEvent("PLAYER_LOGIN")
                -- Set up table for the toc close integration
                tinsert(UISpecialFrames, self:GetName())
            </OnLoad>
            <OnEvent>
                local event, arg1, arg2, arg3, arg4 = event, ...
                if event == "ADDON_LOADED" and arg1 == "CustomLFGTool" then
                    CustomLFGTool:Initialize()
                elseif event == "PLAYER_LOGIN" then
                    -- Join the addon communication channel
                    JoinChannelByName(CustomLFGTool.LFG_CHANNEL)
                elseif event == "CHAT_MSG_ADDON" then
                    CustomLFGTool:OnAddonMessage(arg1, arg2, arg3, arg4)
                end
            </OnEvent>
            <OnDragStart>self:StartMoving()</OnDragStart>
            <OnDragStop>self:StopMovingOrSizing()</OnDragStop>
        </Scripts>
    </Frame>

</Ui>
```

### Step 5: Add Entry Click Handler

Add this to the bottom of `CustomLFGTool.lua`:

```lua
-- ============================================================
-- Entry click handler - whisper the group leader
-- ============================================================

function LFG:OnEntryClick(button)
    local leaderText = _G[button:GetName() .. "LeaderText"]
    if leaderText then
        local leader = leaderText:GetText()
        if leader and leader ~= "" then
            -- Open whisper to the leader
            ChatFrame_OpenChat("/w " .. leader .. " ")
        end
    end
end
```

### Step 6: Test In-Game

1. Copy the `CustomLFGTool` directory to `<WoW>/Interface/AddOns/`.
2. Launch the WoW client (or type `/reload` if already logged in).
3. Verify the addon appears in the AddOns list on the character select screen.
4. Log in and type `/lfgt` to open the custom LFG frame.

---

## 9. Advanced XML Elements

### Dropdown Menus

WoW 3.3.5a uses `UIDropDownMenu` for dropdown selections. These are created in Lua
rather than XML:

```lua
-- Create a dropdown for dungeon selection
local dropdown = CreateFrame("Frame", "CustomLFGDungeonDropdown",
    CustomLFGToolMainFrame, "UIDropDownMenuTemplate")
dropdown:SetPoint("TOPLEFT", CustomLFGToolMainFrame, "TOPLEFT", 10, -40)

local function OnDungeonSelected(self, dungeonId)
    UIDropDownMenu_SetSelectedID(dropdown, self:GetID())
    CustomLFGTool.selectedDungeon = dungeonId
end

local function InitDungeonDropdown(self, level)
    for i, dungeon in ipairs(CustomLFGTool.DUNGEONS) do
        local info = UIDropDownMenu_CreateInfo()
        info.text = dungeon.name
        info.value = dungeon.id
        info.func = OnDungeonSelected
        info.arg1 = dungeon.id
        UIDropDownMenu_AddButton(info, level)
    end
end

UIDropDownMenu_Initialize(dropdown, InitDungeonDropdown)
UIDropDownMenu_SetWidth(dropdown, 180)
UIDropDownMenu_SetText(dropdown, "Select Dungeon")
```

### Tab Frames

Create tabbed interfaces for multiple panels:

```lua
-- Create tab buttons
local function CreateTab(parent, id, text)
    local tab = CreateFrame("Button", parent:GetName() .. "Tab" .. id,
        parent, "CharacterFrameTabButtonTemplate")
    tab:SetID(id)
    tab:SetText(text)
    tab:SetScript("OnClick", function(self)
        PanelTemplates_SetTab(parent, self:GetID())
        -- Show/hide panels based on selected tab
        CustomLFGTool:ShowPanel(self:GetID())
    end)
    return tab
end

local tab1 = CreateTab(CustomLFGToolMainFrame, 1, "Browse")
tab1:SetPoint("BOTTOMLEFT", CustomLFGToolMainFrame, "BOTTOMLEFT", 15, -30)

local tab2 = CreateTab(CustomLFGToolMainFrame, 2, "Create")
tab2:SetPoint("LEFT", tab1, "RIGHT", -14, 0)

PanelTemplates_SetNumTabs(CustomLFGToolMainFrame, 2)
PanelTemplates_SetTab(CustomLFGToolMainFrame, 1)
```

### Tooltip Integration

Show rich tooltips with multiple lines:

```lua
function LFG:ShowListingTooltip(frame, listing)
    GameTooltip:SetOwner(frame, "ANCHOR_RIGHT")
    GameTooltip:ClearLines()

    -- Title line (colored by class)
    local classColor = RAID_CLASS_COLORS[listing.class] or
        { r = 1, g = 1, b = 1 }
    GameTooltip:AddLine(listing.leader, classColor.r, classColor.g,
        classColor.b)

    -- Dungeon info
    GameTooltip:AddDoubleLine("Dungeon:",
        self:GetDungeonName(listing.dungeonId), 1, 0.82, 0, 1, 1, 1)
    GameTooltip:AddDoubleLine("Level:", tostring(listing.level),
        1, 0.82, 0, 1, 1, 1)

    -- Roles needed
    local rolesStr = table.concat(listing.rolesNeeded, ", ")
    GameTooltip:AddDoubleLine("Need:", rolesStr, 1, 0.82, 0, 0.5, 1, 0.5)

    -- Comment
    if listing.comment and listing.comment ~= "" then
        GameTooltip:AddLine(" ")
        GameTooltip:AddLine(listing.comment, 1, 1, 1, true)
    end

    -- Age
    local age = time() - listing.timestamp
    local ageStr
    if age < 60 then
        ageStr = age .. "s ago"
    else
        ageStr = math.floor(age / 60) .. "m ago"
    end
    GameTooltip:AddLine(" ")
    GameTooltip:AddLine("Listed " .. ageStr, 0.5, 0.5, 0.5)

    GameTooltip:Show()
end
```

---

## 10. Slash Commands

Register slash commands for user interaction:

```lua
-- Single command with subcommands
SLASH_CUSTOMLFGTOOL1 = "/lfgt"
SLASH_CUSTOMLFGTOOL2 = "/lfgtool"
SLASH_CUSTOMLFGTOOL3 = "/clfg"

SlashCmdList["CUSTOMLFGTOOL"] = function(msg)
    local args = {}
    for word in msg:gmatch("%S+") do
        table.insert(args, word:lower())
    end

    local cmd = args[1] or ""

    if cmd == "show" or cmd == "" then
        CustomLFGToolMainFrame:Show()

    elseif cmd == "hide" then
        CustomLFGToolMainFrame:Hide()

    elseif cmd == "list" then
        -- Show current listing count
        local count = 0
        for _ in pairs(CustomLFGTool.listings) do count = count + 1 end
        CustomLFGTool:Print(count .. " active group listings.")

    elseif cmd == "clear" then
        CustomLFGTool:RemoveListing()

    elseif cmd == "help" then
        CustomLFGTool:Print("Commands:")
        CustomLFGTool:Print("  /lfgt         - Toggle LFG window")
        CustomLFGTool:Print("  /lfgt show    - Show LFG window")
        CustomLFGTool:Print("  /lfgt hide    - Hide LFG window")
        CustomLFGTool:Print("  /lfgt list    - Show listing count")
        CustomLFGTool:Print("  /lfgt clear   - Remove your listing")
        CustomLFGTool:Print("  /lfgt help    - Show this help text")

    else
        CustomLFGTool:Print("Unknown command: " .. cmd ..
            ". Type /lfgt help for usage.")
    end
end
```

---

## 11. Saved Variables (Persistent Data)

Saved Variables allow your addon to persist data between game sessions. They are
declared in the TOC file and stored as Lua tables in the WTF directory.

### Declaration in TOC

```
## SavedVariables: CustomLFGToolDB
## SavedVariablesPerCharacter: CustomLFGToolCharDB
```

### Initialization Pattern

```lua
-- Initialize saved variables with defaults
function LFG:InitDB()
    -- Account-wide settings
    if not CustomLFGToolDB then
        CustomLFGToolDB = {}
    end

    -- Per-character settings
    if not CustomLFGToolCharDB then
        CustomLFGToolCharDB = {}
    end

    -- Apply defaults (do not overwrite existing values)
    local defaults = {
        minimapButton = true,
        frameScale = 1.0,
        frameAlpha = 1.0,
        autoRefresh = true,
        refreshInterval = 30,
        filterByLevel = true,
    }

    for key, value in pairs(defaults) do
        if CustomLFGToolDB[key] == nil then
            CustomLFGToolDB[key] = value
        end
    end

    self.db = CustomLFGToolDB
    self.charDB = CustomLFGToolCharDB
end
```

### File Storage Location

The WoW client saves these variables to:

```
WTF/
  Account/
    <ACCOUNT_NAME>/
      SavedVariables/
        CustomLFGTool.lua           <-- SavedVariables (account-wide)
      <SERVER_NAME>/
        <CHARACTER_NAME>/
          SavedVariables/
            CustomLFGTool.lua       <-- SavedVariablesPerCharacter
```

### Important Timing

Saved variables are loaded **before** `ADDON_LOADED` fires but **after** the addon's
Lua files have been executed. This means:

1. Your global variable declarations run first (setting them to `{}` or `nil`).
2. The WoW client then **overwrites** those globals with the saved data from disk.
3. `ADDON_LOADED` fires, and you can now safely read the saved data.

**Critical mistake to avoid:**

```lua
-- WRONG: This overwrites saved data every time!
CustomLFGToolDB = { setting1 = true }

-- CORRECT: Only set defaults if no saved data exists
-- (do this in ADDON_LOADED handler, not at file scope)
if not CustomLFGToolDB then
    CustomLFGToolDB = { setting1 = true }
end
```

---

## 12. Packaging AddOns in MPQ Archives

For server-wide distribution, AddOns can be packaged inside an MPQ patch file. This
ensures all players on the server automatically load the addon without manual
installation.

### MPQ Internal Path

AddOns go in the `Interface\AddOns\` path inside the MPQ:

```
patch-4.MPQ
  |
  +-- Interface\
        +-- AddOns\
              +-- CustomLFGTool\
                    +-- CustomLFGTool.toc
                    +-- CustomLFGTool.lua
                    +-- CustomLFGTool.xml
```

### Using pywowlib's MPQPacker

```python
from world_builder.mpq_packer import MPQPacker
import os

packer = MPQPacker(output_dir=r'D:\modding\output', patch_name='patch-4.MPQ')

addon_dir = r'D:\modding\addons\CustomLFGTool'
mpq_base = r'Interface\AddOns\CustomLFGTool'

for filename in os.listdir(addon_dir):
    filepath = os.path.join(addon_dir, filename)
    mpq_path = os.path.join(mpq_base, filename)
    packer.add_file(filepath, mpq_path)

packer.build()
```

### Manual MPQ Packing

1. Create the directory structure on disk mirroring the MPQ layout.
2. Use Ladik's MPQ Editor:
   - File > New MPQ Archive > Save as `patch-4.MPQ`
   - Drag the `Interface` directory into the archive
   - Ensure all files appear at the correct internal paths

### Important Notes on MPQ-Packed AddOns

- AddOns packed in MPQ are **read-only** -- SavedVariables still go to the WTF
  directory on disk, not inside the MPQ.
- MPQ-packed addons cannot be disabled by the user through the normal AddOns
  interface (they are always loaded).
- The MPQ patch number must be higher than the client's existing patches to ensure
  files are loaded in the correct priority order.

---

## 13. Debugging Techniques

### Enable Script Errors

Type this in the chat window to see Lua errors on screen:

```
/console scriptErrors 1
```

Or in your addon code:

```lua
SetCVar("scriptErrors", "1")
```

### Print Debugging

```lua
-- Basic print to chat
print("Debug: variable =", tostring(myVar))

-- Colored output
DEFAULT_CHAT_FRAME:AddMessage("|cFFFF0000ERROR:|r Something went wrong")

-- Dump a table's contents
local function DumpTable(t, indent)
    indent = indent or ""
    for k, v in pairs(t) do
        if type(v) == "table" then
            print(indent .. tostring(k) .. ":")
            DumpTable(v, indent .. "  ")
        else
            print(indent .. tostring(k) .. " = " .. tostring(v))
        end
    end
end
```

### Frame Stack Inspector

Type `/framestack` in-game to see the frame hierarchy under your mouse cursor.
This shows the name, type, and strata of every frame at the cursor position.

### BugSack / BugGrabber

Install these debugging addons to capture and browse Lua errors in a structured
window rather than the default error popup:

1. Download BugGrabber and BugSack for 3.3.5a.
2. Place them in `Interface/AddOns/`.
3. Errors are collected silently and can be browsed via `/bugsack`.

### Checking Frame Existence

```lua
-- Verify a frame was created before using it
if CustomLFGToolMainFrame then
    print("Frame exists, visible:", CustomLFGToolMainFrame:IsShown())
else
    print("ERROR: Frame was not created!")
end

-- Check if a global exists
if _G["CustomLFGToolEntry1"] then
    print("Entry row 1 exists")
end
```

---

## 14. Common Pitfalls and Troubleshooting

### "AddOn is not compatible" / "Out of date"

**Cause:** The `## Interface` value in the TOC file does not match `30300`.

**Fix:** Ensure the TOC contains exactly:
```
## Interface: 30300
```

### AddOn does not appear in the addon list

**Cause 1:** The TOC file name does not match the directory name.

**Fix:** If the directory is `MyAddon/`, the TOC file must be `MyAddon/MyAddon.toc`.

**Cause 2:** The TOC file has a BOM (byte order mark) or wrong encoding.

**Fix:** Save as UTF-8 without BOM.

### "attempt to call global 'xxx' (a nil value)"

**Cause:** A Lua file references a function defined in another file that has not been
loaded yet.

**Fix:** Check the file loading order in the TOC. The file defining the function must
be listed before the file calling it.

### Frame does not appear when Show() is called

**Cause 1:** Frame has zero size.

**Fix:** Add `<Size x="400" y="300"/>` or call `frame:SetSize(400, 300)`.

**Cause 2:** Frame has no anchor points.

**Fix:** Add at least one `<Anchor>` element or call `frame:SetPoint(...)`.

**Cause 3:** Frame strata is too low and is hidden behind other frames.

**Fix:** Use `frameStrata="HIGH"` or `frameStrata="DIALOG"`.

### XML parsing errors on load

**Cause:** Malformed XML (unclosed tags, missing quotes, invalid characters).

**Fix:** Validate your XML with an external tool. Common issues:
- `&` must be written as `&amp;`
- `<` inside attribute values must be `&lt;`
- All tags must be properly closed
- Attribute values must be quoted

### Saved variables are always nil

**Cause:** The variable name in the TOC does not match the Lua global variable name.

**Fix:** Ensure exact name match:
```
## SavedVariables: MyAddonDB     <-- TOC declaration
```
```lua
-- Lua code must use the exact same global name
if not MyAddonDB then MyAddonDB = {} end
```

### Performance: OnUpdate causing lag

**Cause:** Heavy processing in an OnUpdate handler runs every frame (60+ times per
second).

**Fix:** Use a throttle timer:

```lua
local updateInterval = 0.5  -- seconds
frame:SetScript("OnUpdate", function(self, elapsed)
    self.timeSinceLastUpdate = (self.timeSinceLastUpdate or 0) + elapsed
    if self.timeSinceLastUpdate < updateInterval then return end
    self.timeSinceLastUpdate = 0
    -- Do your work here (runs twice per second instead of 60+ times)
end)
```

---

## 15. Cross-References

| Topic | Guide | Relevance |
|-------|-------|-----------|
| LFG dungeon DBC registration | `01_world_building_environment/` | Register custom dungeons in LFGDungeons.dbc that your LFG tool can reference. |
| Custom flight path display | `06_system_ui/modify_flight_paths.md` | Custom taxi nodes that could be displayed in a custom flight map addon. |
| DBC injector core API | `world_builder/dbc_injector.py` | Low-level DBC manipulation for any client-side data modifications. |
| MPQ packing | `world_builder/mpq_packer.py` | Package addons and DBC files into client patches for distribution. |
| SQL generator | `world_builder/sql_generator.py` | Generate server-side SQL for NPCs, items, and quests that your addon interacts with. |
| Adding a playable race | `06_system_ui/add_playable_race.md` | Race selection UI changes required when adding new races. |
