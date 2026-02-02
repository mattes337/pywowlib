"""
DBC file injector for WoW WotLK 3.3.5a (build 12340).

Provides low-level binary read/write of DBC files and convenience functions
for injecting custom Map, AreaTable, WorldMapArea, WorldMapOverlay,
LoadingScreens, LFGDungeons, DungeonEncounter, AreaTrigger, TaxiNodes,
TaxiPath, TaxiPathNode, ZoneMusic, SoundAmbience, and Light entries.
Works directly with raw bytes so it does not depend on the DBD definition
infrastructure.

DBC binary layout:
  Header: 4-byte magic ('WDBC') + 4 uint32 (record_count, field_count,
          record_size, string_block_size) = 20 bytes total.
  Records: record_count * record_size bytes of fixed-size rows.
  String block: string_block_size bytes; offset 0 is always the null byte.
  Strings within records are stored as uint32 offsets into the string block.

Field layouts are derived from the authoritative .dbd definitions shipped
with this repository (wdbx/dbd/definitions/).
"""

import struct
import os


# ---------------------------------------------------------------------------
# Header size constant
# ---------------------------------------------------------------------------
_HEADER_SIZE = 20  # 4 (magic) + 4*4 (counts)

# ---------------------------------------------------------------------------
# WotLK 3.3.5 locstring: 8 locale slots + 8 unused slots + 1 mask = 17 uint32
# Only enUS (slot 0) is populated; mask is set to 0xFFFFFFFF.
# ---------------------------------------------------------------------------
_LOC_SLOTS = 17  # 8 locale string offsets + 8 unused + 1 flags/mask

# ---------------------------------------------------------------------------
# Map.dbc field layout (3.3.0.10958 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/Map.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     Directory                    string   (offset into string block)
#  2     InstanceType                 uint32
#  3     Flags                        uint32
#  4     PVP                          uint32
#  5-21  MapName_lang                 locstr   17 uint32
# 22     AreaTableID                  uint32
# 23-39  MapDescription0_lang         locstr   17 uint32
# 40-56  MapDescription1_lang         locstr   17 uint32
# 57     LoadingScreenID              uint32
# 58     MinimapIconScale             float
# 59     CorpseMapID                  uint32
# 60-61  Corpse[2]                    float[2]
# 62     TimeOfDayOverride            uint32
# 63     ExpansionID                  uint32
# 64     RaidOffset                   uint32
# 65     MaxPlayers                   uint32
# Total: 66 fields = 264 bytes
# ---------------------------------------------------------------------------
_MAP_FIELD_COUNT = 66
_MAP_RECORD_SIZE = _MAP_FIELD_COUNT * 4  # 264

# ---------------------------------------------------------------------------
# AreaTable.dbc field layout (3.0.1.8622 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/AreaTable.dbd
#
# Index  Field                         Type     Count
# -----  ----------------------------  -------  -----
#  0     ID                            uint32
#  1     ContinentID                   uint32
#  2     ParentAreaID                  uint32
#  3     AreaBit                       uint32
#  4     Flags                         uint32
#  5     SoundProviderPref             uint32
#  6     SoundProviderPrefUnderwater   uint32
#  7     AmbienceID                    uint32
#  8     ZoneMusic                     uint32
#  9     IntroSound                    uint32
# 10     ExplorationLevel              uint32
# 11-27  AreaName_lang                 locstr   17 uint32
# 28     FactionGroupMask              uint32
# 29-32  LiquidTypeID[4]              uint32[4]
# 33     MinElevation                  float
# 34     Ambient_multiplier            float
# 35     LightID                       uint32
# Total: 36 fields = 144 bytes
# ---------------------------------------------------------------------------
_AREA_FIELD_COUNT = 36
_AREA_RECORD_SIZE = _AREA_FIELD_COUNT * 4  # 144

# ---------------------------------------------------------------------------
# WorldMapArea.dbc field layout (3.2.0.10192 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/WorldMapArea.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     MapID                        uint32
#  2     AreaID                       uint32
#  3     AreaName                     string   (offset into string block)
#  4     LocLeft                      float
#  5     LocRight                     float
#  6     LocTop                       float
#  7     LocBottom                    float
#  8     DisplayMapID                 uint32
#  9     DefaultDungeonFloor          uint32
# 10     ParentWorldMapID             uint32
# Total: 11 fields = 44 bytes
# ---------------------------------------------------------------------------
_WORLDMAPAREA_FIELD_COUNT = 11
_WORLDMAPAREA_RECORD_SIZE = _WORLDMAPAREA_FIELD_COUNT * 4  # 44

# ---------------------------------------------------------------------------
# WorldMapOverlay.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/WorldMapOverlay.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     MapAreaID                    uint32
#  2-5   AreaID[4]                   uint32[4]
#  6     MapPointX                    uint32
#  7     MapPointY                    uint32
#  8     TextureName                  string   (offset into string block)
#  9     TextureWidth                 uint32
# 10     TextureHeight                uint32
# 11     OffsetX                      uint32
# 12     OffsetY                      uint32
# 13     HitRectTop                   uint32
# 14     HitRectLeft                  uint32
# 15     HitRectBottom                uint32
# 16     HitRectRight                 uint32
# Total: 17 fields = 68 bytes
# ---------------------------------------------------------------------------
_WORLDMAPOVERLAY_FIELD_COUNT = 17
_WORLDMAPOVERLAY_RECORD_SIZE = _WORLDMAPOVERLAY_FIELD_COUNT * 4  # 68

# ---------------------------------------------------------------------------
# LoadingScreens.dbc field layout (3.3.0.10958 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/LoadingScreens.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     Name                         string   (offset into string block)
#  2     FileName                     string   (offset into string block)
#  3     HasWideScreen                uint32
# Total: 4 fields = 16 bytes
# ---------------------------------------------------------------------------
_LOADINGSCREENS_FIELD_COUNT = 4
_LOADINGSCREENS_RECORD_SIZE = _LOADINGSCREENS_FIELD_COUNT * 4  # 16

# ---------------------------------------------------------------------------
# LFGDungeons.dbc field layout (3.3.3.11685 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/LFGDungeons.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1-17  Name_lang                    locstr   17 uint32
# 18     MinLevel                     uint32
# 19     MaxLevel                     uint32
# 20     Target_level                 uint32
# 21     Target_level_min             uint32
# 22     Target_level_max             uint32
# 23     MapID                        uint32   FK to Map.dbc
# 24     Difficulty                   uint32   0=normal, 1=heroic
# 25     Flags                        uint32
# 26     TypeID                       uint32   1=dungeon, 2=raid
# 27     Faction                      uint32   -1=both, 0=horde, 1=alliance
# 28     TextureFilename              string   offset into string block
# 29     ExpansionLevel               uint32   0=classic, 1=tbc, 2=wotlk
# 30     Order_index                  uint32   Sort order in LFG UI
# 31     Group_ID                     uint32   Dungeon group
# 32-48  Description_lang             locstr   17 uint32
# Total: 49 fields = 196 bytes
# ---------------------------------------------------------------------------
_LFGDUNGEONS_FIELD_COUNT = 49
_LFGDUNGEONS_RECORD_SIZE = _LFGDUNGEONS_FIELD_COUNT * 4  # 196

# ---------------------------------------------------------------------------
# DungeonEncounter.dbc field layout (3.3.0.10958 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/DungeonEncounter.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     MapID                        uint32   FK to Map.dbc
#  2     Difficulty                   uint32   0=normal, 1=heroic
#  3     OrderIndex                   uint32   Boss order (0-based)
#  4     Bit                          uint32   Bitmask position
#  5-21  Name_lang                    locstr   17 uint32
# 22     SpellIconID                  uint32   Icon reference
# Total: 23 fields = 92 bytes
# ---------------------------------------------------------------------------
_DUNGEONENCOUNTER_FIELD_COUNT = 23
_DUNGEONENCOUNTER_RECORD_SIZE = _DUNGEONENCOUNTER_FIELD_COUNT * 4  # 92

# ---------------------------------------------------------------------------
# AreaTrigger.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/AreaTrigger.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     ContinentID                  uint32   FK to Map.dbc
#  2     Pos_X                        float
#  3     Pos_Y                        float
#  4     Pos_Z                        float
#  5     Radius                       float    Spherical trigger radius
#  6     Box_length                   float
#  7     Box_width                    float
#  8     Box_height                   float
#  9     Box_yaw                      float    Rotation in radians
# Total: 10 fields = 40 bytes
# ---------------------------------------------------------------------------
_AREATRIGGER_FIELD_COUNT = 10
_AREATRIGGER_RECORD_SIZE = _AREATRIGGER_FIELD_COUNT * 4  # 40

# ---------------------------------------------------------------------------
# TaxiNodes.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/TaxiNodes.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     ContinentID                  uint32   FK to Map.dbc
#  2     Pos_X                        float
#  3     Pos_Y                        float
#  4     Pos_Z                        float
#  5-21  Name_lang                    locstr   17 uint32
# 22     MountCreatureID[0]           uint32   Alliance mount display ID
# 23     MountCreatureID[1]           uint32   Horde mount display ID
# Total: 24 fields = 96 bytes
# ---------------------------------------------------------------------------
_TAXINODES_FIELD_COUNT = 24
_TAXINODES_RECORD_SIZE = _TAXINODES_FIELD_COUNT * 4  # 96

# ---------------------------------------------------------------------------
# TaxiPath.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/TaxiPath.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     FromTaxiNode                 uint32   FK to TaxiNodes.dbc
#  2     ToTaxiNode                   uint32   FK to TaxiNodes.dbc
#  3     Cost                         uint32   Flight cost in copper
# Total: 4 fields = 16 bytes
# ---------------------------------------------------------------------------
_TAXIPATH_FIELD_COUNT = 4
_TAXIPATH_RECORD_SIZE = _TAXIPATH_FIELD_COUNT * 4  # 16

# ---------------------------------------------------------------------------
# TaxiPathNode.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/TaxiPathNode.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     PathID                       uint32   FK to TaxiPath.dbc
#  2     NodeIndex                    uint32   Sequence number (0-based)
#  3     ContinentID                  uint32   FK to Map.dbc
#  4     Loc_X                        float
#  5     Loc_Y                        float
#  6     Loc_Z                        float
#  7     Flags                        uint32
#  8     Delay                        uint32   Milliseconds to wait
#  9     ArrivalEventID               uint32
# 10     DepartureEventID             uint32
# Total: 11 fields (Loc is 3 floats counted individually) = 12 DBC fields = 48 bytes
# ---------------------------------------------------------------------------
_TAXIPATHNODE_FIELD_COUNT = 12
_TAXIPATHNODE_RECORD_SIZE = _TAXIPATHNODE_FIELD_COUNT * 4  # 48

# ---------------------------------------------------------------------------
# ZoneMusic.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/ZoneMusic.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     SetName                      string   (offset into string block)
#  2     SilenceIntervalMin[0]        uint32   Min silence day (ms)
#  3     SilenceIntervalMin[1]        uint32   Min silence night (ms)
#  4     SilenceIntervalMax[0]        uint32   Max silence day (ms)
#  5     SilenceIntervalMax[1]        uint32   Max silence night (ms)
#  6     Sounds[0]                    uint32   FK to SoundEntries.dbc (day)
#  7     Sounds[1]                    uint32   FK to SoundEntries.dbc (night)
# Total: 8 fields = 32 bytes
# ---------------------------------------------------------------------------
_ZONEMUSIC_FIELD_COUNT = 8
_ZONEMUSIC_RECORD_SIZE = _ZONEMUSIC_FIELD_COUNT * 4  # 32

# ---------------------------------------------------------------------------
# SoundAmbience.dbc field layout (3.0.1.8303 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/SoundAmbience.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     AmbienceID[0]                uint32   FK to SoundEntries.dbc (day)
#  2     AmbienceID[1]                uint32   FK to SoundEntries.dbc (night)
# Total: 3 fields = 12 bytes
# ---------------------------------------------------------------------------
_SOUNDAMBIENCE_FIELD_COUNT = 3
_SOUNDAMBIENCE_RECORD_SIZE = _SOUNDAMBIENCE_FIELD_COUNT * 4  # 12

# ---------------------------------------------------------------------------
# Light.dbc field layout (3.0.1.8622 - 3.3.5.12340)
# Source: wdbx/dbd/definitions/Light.dbd
#
# Index  Field                        Type     Count
# -----  ---------------------------  -------  -----
#  0     ID                           uint32
#  1     ContinentID                  uint32   FK to Map.dbc
#  2     GameCoords[0]                float    X position
#  3     GameCoords[1]                float    Y position
#  4     GameCoords[2]                float    Z position
#  5     GameFalloffStart             float    Inner radius (full strength)
#  6     GameFalloffEnd               float    Outer radius (fades to zero)
#  7     LightParamsID[0]             uint32   FK to LightParams.dbc (midnight)
#  8     LightParamsID[1]             uint32   FK to LightParams.dbc (dawn)
#  9     LightParamsID[2]             uint32   FK to LightParams.dbc (morning)
# 10     LightParamsID[3]             uint32   FK to LightParams.dbc (noon)
# 11     LightParamsID[4]             uint32   FK to LightParams.dbc (afternoon)
# 12     LightParamsID[5]             uint32   FK to LightParams.dbc (dusk)
# 13     LightParamsID[6]             uint32   FK to LightParams.dbc (evening)
# 14     LightParamsID[7]             uint32   FK to LightParams.dbc (night)
# Total: 15 fields = 60 bytes
# ---------------------------------------------------------------------------
_LIGHT_FIELD_COUNT = 15
_LIGHT_RECORD_SIZE = _LIGHT_FIELD_COUNT * 4  # 60


class DBCInjector:
    """
    Low-level DBC file reader/writer for injecting new records.
    Works directly with binary data without needing DBD definitions.
    """

    def __init__(self, filepath=None):
        self.magic = b'WDBC'
        self.record_count = 0
        self.field_count = 0
        self.record_size = 0
        self.string_block_size = 1
        self.records = []                       # list of bytes (raw record data)
        self.string_block = bytearray(b'\x00')  # offset 0 = empty string
        self._string_cache = {}                 # string -> offset

        if filepath is not None:
            self.read(filepath)

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def read(self, filepath):
        """Read an existing DBC file from *filepath*."""
        with open(filepath, 'rb') as f:
            data = f.read()

        if len(data) < _HEADER_SIZE:
            raise ValueError("File too small to be a valid DBC: {}".format(filepath))

        magic = data[0:4]
        if magic != b'WDBC':
            raise ValueError(
                "Bad magic in {}: expected b'WDBC', got {!r}".format(filepath, magic)
            )

        self.magic = magic
        self.record_count = struct.unpack_from('<I', data, 4)[0]
        self.field_count = struct.unpack_from('<I', data, 8)[0]
        self.record_size = struct.unpack_from('<I', data, 12)[0]
        self.string_block_size = struct.unpack_from('<I', data, 16)[0]

        records_start = _HEADER_SIZE
        records_end = records_start + self.record_count * self.record_size
        string_block_start = records_end

        self.records = []
        for i in range(self.record_count):
            offset = records_start + i * self.record_size
            self.records.append(data[offset:offset + self.record_size])

        self.string_block = bytearray(data[string_block_start:string_block_start + self.string_block_size])

        # Rebuild string cache for deduplication on future add_string calls
        self._string_cache = {}
        pos = 0
        while pos < len(self.string_block):
            end = self.string_block.find(b'\x00', pos)
            if end == -1:
                break
            s = self.string_block[pos:end].decode('utf-8', errors='replace')
            if s:  # skip empty string at offset 0
                self._string_cache[s] = pos
            pos = end + 1

    def write(self, filepath):
        """Write the DBC file back to disk at *filepath*."""
        self.record_count = len(self.records)
        self.string_block_size = len(self.string_block)

        with open(filepath, 'wb') as f:
            f.write(self.magic)
            f.write(struct.pack('<I', self.record_count))
            f.write(struct.pack('<I', self.field_count))
            f.write(struct.pack('<I', self.record_size))
            f.write(struct.pack('<I', self.string_block_size))

            for rec in self.records:
                f.write(rec)

            f.write(self.string_block)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_max_id(self):
        """Return the maximum ID (first uint32 of each record), or 0."""
        max_id = 0
        for rec in self.records:
            if len(rec) >= 4:
                rec_id = struct.unpack_from('<I', rec, 0)[0]
                if rec_id > max_id:
                    max_id = rec_id
        return max_id

    def add_string(self, s):
        """
        Add a string to the string block and return its offset.
        Empty or None strings return offset 0 (the null byte).
        Duplicate strings are deduplicated automatically.
        """
        if not s:
            return 0
        if s in self._string_cache:
            return self._string_cache[s]

        offset = len(self.string_block)
        encoded = s.encode('utf-8') + b'\x00'
        self.string_block.extend(encoded)
        self._string_cache[s] = offset
        return offset

    def get_string(self, offset):
        """Return the null-terminated string at *offset* in the string block."""
        if offset <= 0 or offset >= len(self.string_block):
            return ''
        end = self.string_block.find(b'\x00', offset)
        if end == -1:
            end = len(self.string_block)
        return self.string_block[offset:end].decode('utf-8', errors='replace')

    def get_record_field(self, record_index, field_index, fmt='<I'):
        """Read a single field from a record. Default format is uint32."""
        rec = self.records[record_index]
        offset = field_index * 4
        return struct.unpack_from(fmt, rec, offset)[0]

    def find_max_field(self, field_index):
        """Return the maximum uint32 value at *field_index* across all records."""
        max_val = 0
        for rec in self.records:
            offset = field_index * 4
            if offset + 4 <= len(rec):
                val = struct.unpack_from('<I', rec, offset)[0]
                if val > max_val:
                    max_val = val
        return max_val


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------

def _pack_locstring(string_offset):
    """
    Pack a WotLK locstring: 8 locale slots + 8 unused + 1 mask.
    Only enUS (slot 0) is set; the mask is 0xFFFFFFFF.
    Returns 17 uint32 values as bytes (68 bytes).
    """
    values = [0] * _LOC_SLOTS
    values[0] = string_offset   # enUS
    values[16] = 0xFFFFFFFF     # mask (last of 17)
    return struct.pack('<{}I'.format(_LOC_SLOTS), *values)


def _build_map_record(
    map_id,
    directory_offset,
    instance_type,
    map_name_offset,
    flags=0,
    pvp=0,
    area_table_id=0,
    loading_screen_id=0,
    minimap_icon_scale=0.0,
    corpse_map_id=0,
    corpse_x=0.0,
    corpse_y=0.0,
    time_of_day_override=-1,
    expansion_id=0,
    raid_offset=0,
    max_players=0,
):
    """
    Build a raw 264-byte Map.dbc record for WotLK 3.3.5.

    String arguments must already be offsets into the string block.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', map_id)
    # 1: Directory (string offset)
    buf += struct.pack('<I', directory_offset)
    # 2: InstanceType
    buf += struct.pack('<I', instance_type)
    # 3: Flags
    buf += struct.pack('<I', flags)
    # 4: PVP
    buf += struct.pack('<I', pvp)
    # 5-21: MapName_lang (locstring, 17 uint32)
    buf += _pack_locstring(map_name_offset)
    # 22: AreaTableID
    buf += struct.pack('<I', area_table_id)
    # 23-39: MapDescription0_lang (empty)
    buf += _pack_locstring(0)
    # 40-56: MapDescription1_lang (empty)
    buf += _pack_locstring(0)
    # 57: LoadingScreenID
    buf += struct.pack('<I', loading_screen_id)
    # 58: MinimapIconScale
    buf += struct.pack('<f', minimap_icon_scale)
    # 59: CorpseMapID
    buf += struct.pack('<I', corpse_map_id)
    # 60-61: Corpse[2] (float x, float y)
    buf += struct.pack('<ff', corpse_x, corpse_y)
    # 62: TimeOfDayOverride  (signed -1 stored as uint32 0xFFFFFFFF)
    buf += struct.pack('<i', time_of_day_override)
    # 63: ExpansionID
    buf += struct.pack('<I', expansion_id)
    # 64: RaidOffset
    buf += struct.pack('<I', raid_offset)
    # 65: MaxPlayers
    buf += struct.pack('<I', max_players)

    assert len(buf) == _MAP_RECORD_SIZE, (
        "Map record size mismatch: expected {}, got {}".format(_MAP_RECORD_SIZE, len(buf))
    )
    return bytes(buf)


def _build_area_record(
    area_id,
    continent_id,
    parent_area_id,
    area_bit,
    area_name_offset,
    flags=0,
    sound_provider_pref=0,
    sound_provider_pref_uw=0,
    ambience_id=0,
    zone_music=0,
    intro_sound=0,
    exploration_level=0,
    faction_group_mask=0,
    liquid_type_ids=None,
    min_elevation=0.0,
    ambient_multiplier=0.0,
    light_id=0,
):
    """
    Build a raw 144-byte AreaTable.dbc record for WotLK 3.3.5.

    String arguments must already be offsets into the string block.
    """
    if liquid_type_ids is None:
        liquid_type_ids = [0, 0, 0, 0]

    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', area_id)
    # 1: ContinentID
    buf += struct.pack('<I', continent_id)
    # 2: ParentAreaID
    buf += struct.pack('<I', parent_area_id)
    # 3: AreaBit
    buf += struct.pack('<I', area_bit)
    # 4: Flags
    buf += struct.pack('<I', flags)
    # 5: SoundProviderPref
    buf += struct.pack('<I', sound_provider_pref)
    # 6: SoundProviderPrefUnderwater
    buf += struct.pack('<I', sound_provider_pref_uw)
    # 7: AmbienceID
    buf += struct.pack('<I', ambience_id)
    # 8: ZoneMusic
    buf += struct.pack('<I', zone_music)
    # 9: IntroSound
    buf += struct.pack('<I', intro_sound)
    # 10: ExplorationLevel
    buf += struct.pack('<I', exploration_level)
    # 11-27: AreaName_lang (locstring, 17 uint32)
    buf += _pack_locstring(area_name_offset)
    # 28: FactionGroupMask
    buf += struct.pack('<I', faction_group_mask)
    # 29-32: LiquidTypeID[4]
    buf += struct.pack('<4I', *liquid_type_ids)
    # 33: MinElevation
    buf += struct.pack('<f', min_elevation)
    # 34: Ambient_multiplier
    buf += struct.pack('<f', ambient_multiplier)
    # 35: LightID
    buf += struct.pack('<I', light_id)

    assert len(buf) == _AREA_RECORD_SIZE, (
        "AreaTable record size mismatch: expected {}, got {}".format(
            _AREA_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_worldmaparea_record(
    worldmaparea_id,
    map_id,
    area_id,
    area_name_offset,
    loc_left=0.0,
    loc_right=0.0,
    loc_top=0.0,
    loc_bottom=0.0,
    display_map_id=-1,
    default_dungeon_floor=0,
    parent_worldmap_id=-1,
):
    """
    Build a raw 44-byte WorldMapArea.dbc record for WotLK 3.3.5.

    String arguments must already be offsets into the string block.

    Args:
        worldmaparea_id: Unique ID for this world map area entry.
        map_id: Map ID (FK to Map.dbc).
        area_id: Area ID (FK to AreaTable.dbc).
        area_name_offset: String offset for display name.
        loc_left: Left boundary X coordinate (float).
        loc_right: Right boundary X coordinate (float).
        loc_top: Top boundary Y coordinate (float).
        loc_bottom: Bottom boundary Y coordinate (float).
        display_map_id: Map to display on (-1 = use own map).
        default_dungeon_floor: Default floor level (0 for outdoor zones).
        parent_worldmap_id: Parent map area ID (-1 = top-level).
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', worldmaparea_id)
    # 1: MapID
    buf += struct.pack('<I', map_id)
    # 2: AreaID
    buf += struct.pack('<I', area_id)
    # 3: AreaName (string offset)
    buf += struct.pack('<I', area_name_offset)
    # 4: LocLeft
    buf += struct.pack('<f', loc_left)
    # 5: LocRight
    buf += struct.pack('<f', loc_right)
    # 6: LocTop
    buf += struct.pack('<f', loc_top)
    # 7: LocBottom
    buf += struct.pack('<f', loc_bottom)
    # 8: DisplayMapID (signed -1 stored as uint32 0xFFFFFFFF)
    buf += struct.pack('<i', display_map_id)
    # 9: DefaultDungeonFloor
    buf += struct.pack('<I', default_dungeon_floor)
    # 10: ParentWorldMapID (signed -1 stored as uint32 0xFFFFFFFF)
    buf += struct.pack('<i', parent_worldmap_id)

    assert len(buf) == _WORLDMAPAREA_RECORD_SIZE, (
        "WorldMapArea record size mismatch: expected {}, got {}".format(
            _WORLDMAPAREA_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_worldmapoverlay_record(
    worldmapoverlay_id,
    map_area_id,
    texture_name_offset,
    area_ids=None,
    map_point_x=0,
    map_point_y=0,
    texture_width=0,
    texture_height=0,
    offset_x=0,
    offset_y=0,
    hit_rect_top=0,
    hit_rect_left=0,
    hit_rect_bottom=0,
    hit_rect_right=0,
):
    """
    Build a raw 68-byte WorldMapOverlay.dbc record for WotLK 3.3.5.

    String arguments must already be offsets into the string block.

    Args:
        worldmapoverlay_id: Unique ID for this overlay entry.
        map_area_id: WorldMapArea ID this overlay belongs to.
        texture_name_offset: String offset for overlay texture path.
        area_ids: List of up to 4 area IDs this overlay covers (or None).
        map_point_x: X position on map.
        map_point_y: Y position on map.
        texture_width: Texture width in pixels.
        texture_height: Texture height in pixels.
        offset_x: X rendering offset.
        offset_y: Y rendering offset.
        hit_rect_top: Click detection - top edge.
        hit_rect_left: Click detection - left edge.
        hit_rect_bottom: Click detection - bottom edge.
        hit_rect_right: Click detection - right edge.
    """
    if area_ids is None:
        area_ids = [0, 0, 0, 0]
    elif len(area_ids) < 4:
        # Pad to 4 elements
        area_ids = list(area_ids) + [0] * (4 - len(area_ids))
    else:
        area_ids = area_ids[:4]

    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', worldmapoverlay_id)
    # 1: MapAreaID
    buf += struct.pack('<I', map_area_id)
    # 2-5: AreaID[4]
    buf += struct.pack('<4I', *area_ids)
    # 6: MapPointX
    buf += struct.pack('<I', map_point_x)
    # 7: MapPointY
    buf += struct.pack('<I', map_point_y)
    # 8: TextureName (string offset)
    buf += struct.pack('<I', texture_name_offset)
    # 9: TextureWidth
    buf += struct.pack('<I', texture_width)
    # 10: TextureHeight
    buf += struct.pack('<I', texture_height)
    # 11: OffsetX
    buf += struct.pack('<I', offset_x)
    # 12: OffsetY
    buf += struct.pack('<I', offset_y)
    # 13: HitRectTop
    buf += struct.pack('<I', hit_rect_top)
    # 14: HitRectLeft
    buf += struct.pack('<I', hit_rect_left)
    # 15: HitRectBottom
    buf += struct.pack('<I', hit_rect_bottom)
    # 16: HitRectRight
    buf += struct.pack('<I', hit_rect_right)

    assert len(buf) == _WORLDMAPOVERLAY_RECORD_SIZE, (
        "WorldMapOverlay record size mismatch: expected {}, got {}".format(
            _WORLDMAPOVERLAY_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_loadingscreen_record(
    loadingscreen_id,
    name_offset,
    filename_offset,
    has_widescreen=0,
):
    """
    Build a raw 16-byte LoadingScreens.dbc record for WotLK 3.3.5.

    String arguments must already be offsets into the string block.

    Args:
        loadingscreen_id: Unique ID for this loading screen.
        name_offset: String offset for internal name.
        filename_offset: String offset for BLP texture path.
        has_widescreen: 0=standard aspect ratio, 1=widescreen support.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', loadingscreen_id)
    # 1: Name (string offset)
    buf += struct.pack('<I', name_offset)
    # 2: FileName (string offset)
    buf += struct.pack('<I', filename_offset)
    # 3: HasWideScreen
    buf += struct.pack('<I', has_widescreen)

    assert len(buf) == _LOADINGSCREENS_RECORD_SIZE, (
        "LoadingScreens record size mismatch: expected {}, got {}".format(
            _LOADINGSCREENS_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_lfgdungeons_record(
    dungeon_id,
    name_offset,
    min_level,
    max_level,
    map_id,
    target_level=None,
    target_level_min=None,
    target_level_max=None,
    difficulty=0,
    flags=0,
    type_id=1,
    faction=0xFFFFFFFF,
    texture_filename_offset=0,
    expansion_level=2,
    order_index=0,
    group_id=0,
    description_offset=0,
):
    """
    Build a raw 196-byte LFGDungeons.dbc record for WotLK 3.3.5.

    Args:
        dungeon_id: Unique LFG dungeon ID.
        name_offset: String block offset for dungeon name.
        min_level: Minimum player level to queue.
        max_level: Maximum player level to queue.
        map_id: Map.dbc ID for the dungeon instance.
        target_level: Average/target level (defaults to min_level if None).
        target_level_min: Target range min (defaults to min_level if None).
        target_level_max: Target range max (defaults to max_level if None).
        difficulty: 0=normal, 1=heroic.
        flags: Dungeon flags (typically 0).
        type_id: 1=dungeon, 2=raid, 4=random, 6=random heroic.
        faction: 0xFFFFFFFF=both, 0=horde, 1=alliance.
        texture_filename_offset: String offset for icon texture (0=none).
        expansion_level: 0=classic, 1=TBC, 2=WotLK.
        order_index: Sort order in LFG UI.
        group_id: Dungeon group ID (0=none).
        description_offset: String offset for description (0=empty).

    Returns:
        bytes: 196-byte raw record.
    """
    # Default target levels to match min/max if not specified
    if target_level is None:
        target_level = min_level
    if target_level_min is None:
        target_level_min = min_level
    if target_level_max is None:
        target_level_max = max_level

    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', dungeon_id)
    # 1-17: Name_lang (locstring, 17 uint32)
    buf += _pack_locstring(name_offset)
    # 18: MinLevel
    buf += struct.pack('<I', min_level)
    # 19: MaxLevel
    buf += struct.pack('<I', max_level)
    # 20: Target_level
    buf += struct.pack('<I', target_level)
    # 21: Target_level_min
    buf += struct.pack('<I', target_level_min)
    # 22: Target_level_max
    buf += struct.pack('<I', target_level_max)
    # 23: MapID
    buf += struct.pack('<I', map_id)
    # 24: Difficulty
    buf += struct.pack('<I', difficulty)
    # 25: Flags
    buf += struct.pack('<I', flags)
    # 26: TypeID
    buf += struct.pack('<I', type_id)
    # 27: Faction (signed int, but stored as uint32)
    buf += struct.pack('<I', faction)
    # 28: TextureFilename (string offset)
    buf += struct.pack('<I', texture_filename_offset)
    # 29: ExpansionLevel
    buf += struct.pack('<I', expansion_level)
    # 30: Order_index
    buf += struct.pack('<I', order_index)
    # 31: Group_ID
    buf += struct.pack('<I', group_id)
    # 32-48: Description_lang (locstring, 17 uint32)
    buf += _pack_locstring(description_offset)

    assert len(buf) == _LFGDUNGEONS_RECORD_SIZE, (
        "LFGDungeons record size mismatch: expected {}, got {}".format(
            _LFGDUNGEONS_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_dungeonencounter_record(
    encounter_id,
    map_id,
    name_offset,
    order_index,
    bit,
    difficulty=0,
    spell_icon_id=0,
):
    """
    Build a raw 92-byte DungeonEncounter.dbc record for WotLK 3.3.5.

    Args:
        encounter_id: Unique encounter ID.
        map_id: Map.dbc ID for the dungeon instance.
        name_offset: String block offset for boss name.
        order_index: Boss order in dungeon (0-based).
        bit: Bitmask position for encounter state tracking.
        difficulty: 0=normal, 1=heroic.
        spell_icon_id: SpellIcon.dbc ID for boss icon (0=default).

    Returns:
        bytes: 92-byte raw record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', encounter_id)
    # 1: MapID
    buf += struct.pack('<I', map_id)
    # 2: Difficulty
    buf += struct.pack('<I', difficulty)
    # 3: OrderIndex
    buf += struct.pack('<I', order_index)
    # 4: Bit
    buf += struct.pack('<I', bit)
    # 5-21: Name_lang (locstring, 17 uint32)
    buf += _pack_locstring(name_offset)
    # 22: SpellIconID
    buf += struct.pack('<I', spell_icon_id)

    assert len(buf) == _DUNGEONENCOUNTER_RECORD_SIZE, (
        "DungeonEncounter record size mismatch: expected {}, got {}".format(
            _DUNGEONENCOUNTER_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_areatrigger_record(
    trigger_id,
    continent_id,
    pos_x,
    pos_y,
    pos_z,
    radius=0.0,
    box_length=0.0,
    box_width=0.0,
    box_height=0.0,
    box_yaw=0.0,
):
    """
    Build a raw 40-byte AreaTrigger.dbc record for WotLK 3.3.5.

    Args:
        trigger_id: Unique ID for this area trigger.
        continent_id: Map ID (FK to Map.dbc).
        pos_x, pos_y, pos_z: Center position of trigger.
        radius: Spherical trigger radius (set > 0 for sphere, 0 for box).
        box_length: Box trigger length (Y-axis aligned).
        box_width: Box trigger width (X-axis aligned).
        box_height: Box trigger height (Z-axis aligned).
        box_yaw: Box rotation in radians (rotation around Z-axis).

    Returns:
        bytes: 40-byte AreaTrigger.dbc record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', trigger_id)
    # 1: ContinentID
    buf += struct.pack('<I', continent_id)
    # 2-4: Pos (X, Y, Z)
    buf += struct.pack('<fff', pos_x, pos_y, pos_z)
    # 5: Radius
    buf += struct.pack('<f', radius)
    # 6-9: Box dimensions and rotation
    buf += struct.pack('<ffff', box_length, box_width, box_height, box_yaw)

    assert len(buf) == _AREATRIGGER_RECORD_SIZE, (
        "AreaTrigger record size mismatch: expected {}, got {}".format(
            _AREATRIGGER_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_taxinode_record(
    node_id,
    continent_id,
    pos_x,
    pos_y,
    pos_z,
    name_offset,
    mount_alliance=0,
    mount_horde=0,
):
    """
    Build a raw 96-byte TaxiNodes.dbc record for WotLK 3.3.5.

    Args:
        node_id: Unique ID for this taxi node.
        continent_id: Map ID (FK to Map.dbc).
        pos_x, pos_y, pos_z: Flight master position.
        name_offset: String block offset for node name (locstring enUS slot).
        mount_alliance: Alliance mount CreatureDisplayInfo ID.
        mount_horde: Horde mount CreatureDisplayInfo ID.

    Returns:
        bytes: 96-byte TaxiNodes.dbc record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', node_id)
    # 1: ContinentID
    buf += struct.pack('<I', continent_id)
    # 2-4: Pos (X, Y, Z)
    buf += struct.pack('<fff', pos_x, pos_y, pos_z)
    # 5-21: Name_lang (locstring, 17 uint32)
    buf += _pack_locstring(name_offset)
    # 22-23: MountCreatureID[2] (Alliance, Horde)
    buf += struct.pack('<II', mount_alliance, mount_horde)

    assert len(buf) == _TAXINODES_RECORD_SIZE, (
        "TaxiNodes record size mismatch: expected {}, got {}".format(
            _TAXINODES_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_taxipath_record(
    path_id,
    from_node,
    to_node,
    cost,
):
    """
    Build a raw 16-byte TaxiPath.dbc record for WotLK 3.3.5.

    Args:
        path_id: Unique ID for this taxi path.
        from_node: Starting TaxiNodes ID.
        to_node: Destination TaxiNodes ID.
        cost: Flight cost in copper.

    Returns:
        bytes: 16-byte TaxiPath.dbc record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', path_id)
    # 1: FromTaxiNode
    buf += struct.pack('<I', from_node)
    # 2: ToTaxiNode
    buf += struct.pack('<I', to_node)
    # 3: Cost
    buf += struct.pack('<I', cost)

    assert len(buf) == _TAXIPATH_RECORD_SIZE, (
        "TaxiPath record size mismatch: expected {}, got {}".format(
            _TAXIPATH_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_taxipathnode_record(
    node_id,
    path_id,
    node_index,
    continent_id,
    loc_x,
    loc_y,
    loc_z,
    flags=0,
    delay=0,
    arrival_event_id=0,
    departure_event_id=0,
):
    """
    Build a raw 48-byte TaxiPathNode.dbc record for WotLK 3.3.5.

    Args:
        node_id: Unique ID for this path node.
        path_id: TaxiPath ID this node belongs to.
        node_index: Sequence number in path (starts at 0).
        continent_id: Map ID (FK to Map.dbc).
        loc_x, loc_y, loc_z: Waypoint position.
        flags: Special behavior flags (0 = normal).
        delay: Milliseconds to wait at this node.
        arrival_event_id: Spell/event triggered on arrival.
        departure_event_id: Spell/event triggered on departure.

    Returns:
        bytes: 48-byte TaxiPathNode.dbc record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', node_id)
    # 1: PathID
    buf += struct.pack('<I', path_id)
    # 2: NodeIndex
    buf += struct.pack('<I', node_index)
    # 3: ContinentID
    buf += struct.pack('<I', continent_id)
    # 4-6: Loc (X, Y, Z)
    buf += struct.pack('<fff', loc_x, loc_y, loc_z)
    # 7: Flags
    buf += struct.pack('<I', flags)
    # 8: Delay
    buf += struct.pack('<I', delay)
    # 9: ArrivalEventID
    buf += struct.pack('<I', arrival_event_id)
    # 10: DepartureEventID
    buf += struct.pack('<I', departure_event_id)

    assert len(buf) == _TAXIPATHNODE_RECORD_SIZE, (
        "TaxiPathNode record size mismatch: expected {}, got {}".format(
            _TAXIPATHNODE_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_zone_music_record(
    zone_music_id,
    set_name_offset,
    silence_min,
    silence_max,
    sounds,
):
    """
    Build a raw 32-byte ZoneMusic.dbc record for WotLK 3.3.5.

    Args:
        zone_music_id: ZoneMusic ID (uint32).
        set_name_offset: String offset for SetName field.
        silence_min: [day, night] min silence intervals (uint32 x2).
        silence_max: [day, night] max silence intervals (uint32 x2).
        sounds: [day, night] SoundEntries IDs (uint32 x2).

    Returns:
        bytes: 32-byte binary record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', zone_music_id)
    # 1: SetName (string offset)
    buf += struct.pack('<I', set_name_offset)
    # 2-3: SilenceIntervalMin[2] (day, night)
    buf += struct.pack('<2I', silence_min[0], silence_min[1])
    # 4-5: SilenceIntervalMax[2] (day, night)
    buf += struct.pack('<2I', silence_max[0], silence_max[1])
    # 6-7: Sounds[2] (day, night)
    buf += struct.pack('<2I', sounds[0], sounds[1])

    assert len(buf) == _ZONEMUSIC_RECORD_SIZE, (
        "ZoneMusic record size mismatch: expected {}, got {}".format(
            _ZONEMUSIC_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_sound_ambience_record(
    ambience_id,
    day_ambience_id,
    night_ambience_id,
):
    """
    Build a raw 12-byte SoundAmbience.dbc record for WotLK 3.3.5.

    Args:
        ambience_id: SoundAmbience ID (uint32).
        day_ambience_id: SoundEntries ID for day ambience (uint32).
        night_ambience_id: SoundEntries ID for night ambience (uint32).

    Returns:
        bytes: 12-byte binary record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', ambience_id)
    # 1-2: AmbienceID[2] (day, night)
    buf += struct.pack('<2I', day_ambience_id, night_ambience_id)

    assert len(buf) == _SOUNDAMBIENCE_RECORD_SIZE, (
        "SoundAmbience record size mismatch: expected {}, got {}".format(
            _SOUNDAMBIENCE_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


def _build_light_record(
    light_id,
    continent_id,
    game_coords,
    falloff_start,
    falloff_end,
    light_params_ids,
):
    """
    Build a raw 60-byte Light.dbc record for WotLK 3.3.5.

    Args:
        light_id: Light ID (uint32).
        continent_id: Map ID (uint32).
        game_coords: (x, y, z) tuple of floats.
        falloff_start: Inner falloff radius (float).
        falloff_end: Outer falloff radius (float).
        light_params_ids: List of 8 LightParams IDs (uint32 x8).

    Returns:
        bytes: 60-byte binary record.
    """
    buf = bytearray()

    # 0: ID
    buf += struct.pack('<I', light_id)
    # 1: ContinentID
    buf += struct.pack('<I', continent_id)
    # 2-4: GameCoords[3] (x, y, z)
    buf += struct.pack('<3f', game_coords[0], game_coords[1], game_coords[2])
    # 5: GameFalloffStart
    buf += struct.pack('<f', falloff_start)
    # 6: GameFalloffEnd
    buf += struct.pack('<f', falloff_end)
    # 7-14: LightParamsID[8]
    buf += struct.pack('<8I', *light_params_ids)

    assert len(buf) == _LIGHT_RECORD_SIZE, (
        "Light record size mismatch: expected {}, got {}".format(
            _LIGHT_RECORD_SIZE, len(buf)
        )
    )
    return bytes(buf)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_map(dbc_dir, map_name, map_id=None, instance_type=0):
    """
    Register a new map in Map.dbc.

    Args:
        dbc_dir: Path to directory containing Map.dbc.
        map_name: Internal map directory name (e.g. "NewZone").
                  This is both the Directory field and the display name.
        map_id: Specific map ID to use, or None for auto (max_id + 1).
        instance_type: 0=open world, 1=party dungeon, 2=raid,
                       3=pvp, 4=arena.

    Returns:
        int: The assigned map ID.
    """
    filepath = os.path.join(dbc_dir, 'Map.dbc')
    dbc = DBCInjector(filepath)

    if map_id is None:
        map_id = dbc.get_max_id() + 1

    dir_offset = dbc.add_string(map_name)
    name_offset = dbc.add_string(map_name)

    record = _build_map_record(
        map_id=map_id,
        directory_offset=dir_offset,
        instance_type=instance_type,
        map_name_offset=name_offset,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return map_id


def register_area(
    dbc_dir,
    area_name,
    map_id,
    area_id=None,
    parent_area_id=0,
    ambience_id=0,
    zone_music=0,
    light_id=0,
):
    """
    Register a new area in AreaTable.dbc.

    Args:
        dbc_dir: Path to directory containing AreaTable.dbc.
        area_name: Display name for the area.
        map_id: Map ID this area belongs to (ContinentID).
        area_id: Specific area ID or None for auto (max_id + 1).
        parent_area_id: Parent area (0 for top-level zone).
        ambience_id: SoundAmbience ID (0 = no ambience).
        zone_music: ZoneMusic ID (0 = no music).
        light_id: Light ID (0 = default lighting).

    Returns:
        int: The assigned area ID.
    """
    filepath = os.path.join(dbc_dir, 'AreaTable.dbc')
    dbc = DBCInjector(filepath)

    if area_id is None:
        area_id = dbc.get_max_id() + 1

    # AreaBit must be unique across all areas; use max+1.
    area_bit = dbc.find_max_field(3) + 1

    name_offset = dbc.add_string(area_name)

    record = _build_area_record(
        area_id=area_id,
        continent_id=map_id,
        parent_area_id=parent_area_id,
        area_bit=area_bit,
        area_name_offset=name_offset,
        ambience_id=ambience_id,
        zone_music=zone_music,
        light_id=light_id,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return area_id


def register_world_map_area(
    dbc_dir,
    area_name,
    map_id,
    area_id,
    worldmaparea_id=None,
    loc_left=0.0,
    loc_right=0.0,
    loc_top=0.0,
    loc_bottom=0.0,
    display_map_id=-1,
    parent_worldmap_id=-1,
):
    """
    Register a new world map area in WorldMapArea.dbc.

    This defines how a zone appears on the world map interface, including
    its position, boundaries, and display settings.

    Args:
        dbc_dir: Path to directory containing WorldMapArea.dbc.
        area_name: Display name for the map area.
        map_id: Map ID (FK to Map.dbc).
        area_id: Area ID (FK to AreaTable.dbc).
        worldmaparea_id: Specific WorldMapArea ID or None for auto (max_id + 1).
        loc_left: Left boundary X coordinate (float).
        loc_right: Right boundary X coordinate (float).
        loc_top: Top boundary Y coordinate (float).
        loc_bottom: Bottom boundary Y coordinate (float).
        display_map_id: Map to display on (-1 = use own map).
        parent_worldmap_id: Parent map area ID (-1 = top-level).

    Returns:
        int: The assigned WorldMapArea ID.
    """
    filepath = os.path.join(dbc_dir, 'WorldMapArea.dbc')
    dbc = DBCInjector(filepath)

    if worldmaparea_id is None:
        worldmaparea_id = dbc.get_max_id() + 1

    area_name_offset = dbc.add_string(area_name)

    record = _build_worldmaparea_record(
        worldmaparea_id=worldmaparea_id,
        map_id=map_id,
        area_id=area_id,
        area_name_offset=area_name_offset,
        loc_left=loc_left,
        loc_right=loc_right,
        loc_top=loc_top,
        loc_bottom=loc_bottom,
        display_map_id=display_map_id,
        default_dungeon_floor=0,
        parent_worldmap_id=parent_worldmap_id,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return worldmaparea_id


def register_world_map_overlay(
    dbc_dir,
    map_area_id,
    texture_name,
    worldmapoverlay_id=None,
    area_ids=None,
    texture_width=512,
    texture_height=512,
    map_point_x=0,
    map_point_y=0,
    offset_x=0,
    offset_y=0,
    hit_rect_top=0,
    hit_rect_left=0,
    hit_rect_bottom=512,
    hit_rect_right=512,
):
    """
    Register a new world map overlay in WorldMapOverlay.dbc.

    Overlays add visual elements to the world map (POIs, zone boundaries,
    sub-region highlights, etc.).

    Args:
        dbc_dir: Path to directory containing WorldMapOverlay.dbc.
        map_area_id: WorldMapArea ID this overlay belongs to.
        texture_name: BLP texture path (e.g. "Interface\\WorldMap\\TelAbim\\TelAbim1").
        worldmapoverlay_id: Specific overlay ID or None for auto (max_id + 1).
        area_ids: List of up to 4 area IDs this overlay covers (or None).
        texture_width: Texture width in pixels (default 512).
        texture_height: Texture height in pixels (default 512).
        map_point_x: X position on map.
        map_point_y: Y position on map.
        offset_x: X rendering offset.
        offset_y: Y rendering offset.
        hit_rect_top: Click detection - top edge.
        hit_rect_left: Click detection - left edge.
        hit_rect_bottom: Click detection - bottom edge.
        hit_rect_right: Click detection - right edge.

    Returns:
        int: The assigned WorldMapOverlay ID.
    """
    filepath = os.path.join(dbc_dir, 'WorldMapOverlay.dbc')
    dbc = DBCInjector(filepath)

    if worldmapoverlay_id is None:
        worldmapoverlay_id = dbc.get_max_id() + 1

    texture_name_offset = dbc.add_string(texture_name)

    record = _build_worldmapoverlay_record(
        worldmapoverlay_id=worldmapoverlay_id,
        map_area_id=map_area_id,
        texture_name_offset=texture_name_offset,
        area_ids=area_ids,
        map_point_x=map_point_x,
        map_point_y=map_point_y,
        texture_width=texture_width,
        texture_height=texture_height,
        offset_x=offset_x,
        offset_y=offset_y,
        hit_rect_top=hit_rect_top,
        hit_rect_left=hit_rect_left,
        hit_rect_bottom=hit_rect_bottom,
        hit_rect_right=hit_rect_right,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return worldmapoverlay_id


def register_loading_screen(
    dbc_dir,
    name,
    filename,
    loadingscreen_id=None,
    has_widescreen=1,
):
    """
    Register a new loading screen in LoadingScreens.dbc.

    Loading screens are displayed when entering a zone or instance.

    Args:
        dbc_dir: Path to directory containing LoadingScreens.dbc.
        name: Internal name (e.g. "LoadScreenTelAbim").
        filename: BLP texture path (e.g. "Interface\\Glues\\LoadingScreens\\LoadScreenTelAbim.blp").
        loadingscreen_id: Specific ID or None for auto (max_id + 1).
        has_widescreen: 0=standard aspect ratio only, 1=widescreen support (default 1).

    Returns:
        int: The assigned LoadingScreen ID.
    """
    filepath = os.path.join(dbc_dir, 'LoadingScreens.dbc')
    dbc = DBCInjector(filepath)

    if loadingscreen_id is None:
        loadingscreen_id = dbc.get_max_id() + 1

    name_offset = dbc.add_string(name)
    filename_offset = dbc.add_string(filename)

    record = _build_loadingscreen_record(
        loadingscreen_id=loadingscreen_id,
        name_offset=name_offset,
        filename_offset=filename_offset,
        has_widescreen=has_widescreen,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return loadingscreen_id


def register_lfg_dungeon(
    dbc_dir,
    dungeon_name,
    min_level,
    max_level,
    map_id,
    dungeon_id=None,
    difficulty=0,
    type_id=1,
    faction=0xFFFFFFFF,
    expansion_level=2,
    description=None,
):
    """
    Register a new dungeon in LFGDungeons.dbc.

    Args:
        dbc_dir: Path to directory containing LFGDungeons.dbc.
        dungeon_name: Display name for the dungeon (e.g. "Vault of Storms").
        min_level: Minimum player level to queue.
        max_level: Maximum player level to queue.
        map_id: Map.dbc ID for the dungeon instance.
        dungeon_id: Specific dungeon ID or None for auto (max_id + 1).
        difficulty: 0=normal, 1=heroic. Default: 0 (normal).
        type_id: 1=dungeon, 2=raid. Default: 1 (dungeon).
        faction: 0xFFFFFFFF=both factions (-1 signed), 0=horde, 1=alliance.
                 Default: 0xFFFFFFFF (both).
        expansion_level: 0=classic, 1=TBC, 2=WotLK. Default: 2 (WotLK).
        description: Optional description text (displayed in LFG UI).

    Returns:
        int: The assigned dungeon ID.
    """
    filepath = os.path.join(dbc_dir, 'LFGDungeons.dbc')
    dbc = DBCInjector(filepath)

    if dungeon_id is None:
        dungeon_id = dbc.get_max_id() + 1

    name_offset = dbc.add_string(dungeon_name)
    desc_offset = dbc.add_string(description) if description else 0

    record = _build_lfgdungeons_record(
        dungeon_id=dungeon_id,
        name_offset=name_offset,
        min_level=min_level,
        max_level=max_level,
        map_id=map_id,
        difficulty=difficulty,
        type_id=type_id,
        faction=faction,
        expansion_level=expansion_level,
        description_offset=desc_offset,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return dungeon_id


def register_dungeon_encounter(
    dbc_dir,
    boss_name,
    map_id,
    order_index,
    bit,
    encounter_id=None,
    difficulty=0,
    spell_icon_id=0,
):
    """
    Register a single boss encounter in DungeonEncounter.dbc.

    Args:
        dbc_dir: Path to directory containing DungeonEncounter.dbc.
        boss_name: Display name for the boss (e.g. "Shade of Zhar'kaan").
        map_id: Map.dbc ID for the dungeon instance.
        order_index: Boss order in dungeon (0-based, e.g. 0=first boss).
        bit: Bitmask position for encounter state tracking (typically 0-based).
        encounter_id: Specific encounter ID or None for auto (max_id + 1).
        difficulty: 0=normal, 1=heroic. Default: 0 (normal).
        spell_icon_id: SpellIcon.dbc ID for boss icon. Default: 0 (generic).

    Returns:
        int: The assigned encounter ID.
    """
    filepath = os.path.join(dbc_dir, 'DungeonEncounter.dbc')
    dbc = DBCInjector(filepath)

    if encounter_id is None:
        encounter_id = dbc.get_max_id() + 1

    name_offset = dbc.add_string(boss_name)

    record = _build_dungeonencounter_record(
        encounter_id=encounter_id,
        map_id=map_id,
        name_offset=name_offset,
        order_index=order_index,
        bit=bit,
        difficulty=difficulty,
        spell_icon_id=spell_icon_id,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return encounter_id


def register_dungeon_encounters(
    dbc_dir,
    map_id,
    boss_names,
    difficulty=0,
    starting_encounter_id=None,
):
    """
    Register multiple boss encounters for a dungeon (convenience wrapper).

    Automatically assigns sequential order_index and bit values starting from 0.

    Args:
        dbc_dir: Path to directory containing DungeonEncounter.dbc.
        map_id: Map.dbc ID for the dungeon instance.
        boss_names: List of boss names in order (e.g. ["Boss 1", "Boss 2", ...]).
        difficulty: 0=normal, 1=heroic. Default: 0 (normal).
        starting_encounter_id: First encounter ID to use, or None for auto.

    Returns:
        list[int]: List of assigned encounter IDs in order.
    """
    filepath = os.path.join(dbc_dir, 'DungeonEncounter.dbc')
    dbc = DBCInjector(filepath)

    if starting_encounter_id is None:
        starting_encounter_id = dbc.get_max_id() + 1

    encounter_ids = []
    for i, boss_name in enumerate(boss_names):
        encounter_id = starting_encounter_id + i
        name_offset = dbc.add_string(boss_name)

        record = _build_dungeonencounter_record(
            encounter_id=encounter_id,
            map_id=map_id,
            name_offset=name_offset,
            order_index=i,  # Sequential: 0, 1, 2, 3
            bit=i,          # Sequential: 0, 1, 2, 3
            difficulty=difficulty,
            spell_icon_id=0,
        )

        dbc.records.append(record)
        encounter_ids.append(encounter_id)

    dbc.write(filepath)

    return encounter_ids


def register_area_trigger(
    dbc_dir,
    continent_id,
    pos_x,
    pos_y,
    pos_z,
    trigger_id=None,
    radius=5.0,
    box_length=0.0,
    box_width=0.0,
    box_height=0.0,
    box_yaw=0.0,
):
    """
    Register a new area trigger in AreaTrigger.dbc.

    Area triggers are invisible zones that can trigger dungeon entrances,
    quest events, or other gameplay mechanics.

    Args:
        dbc_dir: Path to directory containing AreaTrigger.dbc.
        continent_id: Map ID where trigger is located (FK to Map.dbc).
        pos_x, pos_y, pos_z: Center position of trigger.
        trigger_id: Specific trigger ID or None for auto (max_id + 1).
        radius: Spherical trigger radius in yards (default 5.0).
                Set to 0.0 to use box trigger instead.
        box_length: Box trigger length (Y-axis) in yards.
        box_width: Box trigger width (X-axis) in yards.
        box_height: Box trigger height (Z-axis) in yards.
        box_yaw: Box rotation in radians.

    Returns:
        int: The assigned area trigger ID.
    """
    filepath = os.path.join(dbc_dir, 'AreaTrigger.dbc')
    dbc = DBCInjector(filepath)

    if trigger_id is None:
        trigger_id = dbc.get_max_id() + 1

    record = _build_areatrigger_record(
        trigger_id=trigger_id,
        continent_id=continent_id,
        pos_x=pos_x,
        pos_y=pos_y,
        pos_z=pos_z,
        radius=radius,
        box_length=box_length,
        box_width=box_width,
        box_height=box_height,
        box_yaw=box_yaw,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return trigger_id


def register_taxi_node(
    dbc_dir,
    name,
    continent_id,
    pos_x,
    pos_y,
    pos_z,
    node_id=None,
    mount_alliance=0,
    mount_horde=0,
):
    """
    Register a new taxi node (flight master location) in TaxiNodes.dbc.

    Args:
        dbc_dir: Path to directory containing TaxiNodes.dbc.
        name: Display name for this flight point.
        continent_id: Map ID where node is located (FK to Map.dbc).
        pos_x, pos_y, pos_z: Flight master position.
        node_id: Specific node ID or None for auto (max_id + 1).
        mount_alliance: Alliance mount CreatureDisplayInfo ID (0 for default).
        mount_horde: Horde mount CreatureDisplayInfo ID (0 for default).

    Returns:
        int: The assigned taxi node ID.
    """
    filepath = os.path.join(dbc_dir, 'TaxiNodes.dbc')
    dbc = DBCInjector(filepath)

    if node_id is None:
        node_id = dbc.get_max_id() + 1

    name_offset = dbc.add_string(name)

    record = _build_taxinode_record(
        node_id=node_id,
        continent_id=continent_id,
        pos_x=pos_x,
        pos_y=pos_y,
        pos_z=pos_z,
        name_offset=name_offset,
        mount_alliance=mount_alliance,
        mount_horde=mount_horde,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return node_id


def register_taxi_path(
    dbc_dir,
    from_node,
    to_node,
    cost,
    path_id=None,
):
    """
    Register a new taxi path (flight route) in TaxiPath.dbc.

    Args:
        dbc_dir: Path to directory containing TaxiPath.dbc.
        from_node: Starting TaxiNodes ID.
        to_node: Destination TaxiNodes ID.
        cost: Flight cost in copper (e.g., 100 = 1 silver).
        path_id: Specific path ID or None for auto (max_id + 1).

    Returns:
        int: The assigned taxi path ID.
    """
    filepath = os.path.join(dbc_dir, 'TaxiPath.dbc')
    dbc = DBCInjector(filepath)

    if path_id is None:
        path_id = dbc.get_max_id() + 1

    record = _build_taxipath_record(
        path_id=path_id,
        from_node=from_node,
        to_node=to_node,
        cost=cost,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return path_id


def register_taxi_path_node(
    dbc_dir,
    path_id,
    node_index,
    continent_id,
    loc_x,
    loc_y,
    loc_z,
    node_id=None,
    flags=0,
    delay=0,
    arrival_event_id=0,
    departure_event_id=0,
):
    """
    Register a new taxi path waypoint in TaxiPathNode.dbc.

    Args:
        dbc_dir: Path to directory containing TaxiPathNode.dbc.
        path_id: TaxiPath ID this node belongs to.
        node_index: Sequence number in path (starts at 0).
        continent_id: Map ID for this waypoint.
        loc_x, loc_y, loc_z: Waypoint position.
        node_id: Specific node ID or None for auto (max_id + 1).
        flags: Special behavior flags (0 = normal).
        delay: Milliseconds to wait at this waypoint.
        arrival_event_id: Spell/event on arrival (0 = none).
        departure_event_id: Spell/event on departure (0 = none).

    Returns:
        int: The assigned taxi path node ID.
    """
    filepath = os.path.join(dbc_dir, 'TaxiPathNode.dbc')
    dbc = DBCInjector(filepath)

    if node_id is None:
        node_id = dbc.get_max_id() + 1

    record = _build_taxipathnode_record(
        node_id=node_id,
        path_id=path_id,
        node_index=node_index,
        continent_id=continent_id,
        loc_x=loc_x,
        loc_y=loc_y,
        loc_z=loc_z,
        flags=flags,
        delay=delay,
        arrival_event_id=arrival_event_id,
        departure_event_id=departure_event_id,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return node_id


def register_flight_path(
    dbc_dir,
    from_node,
    to_node,
    waypoints,
    cost,
    path_id=None,
):
    """
    Register a complete flight path with all waypoints in one call.

    This is a convenience function that creates both the TaxiPath entry
    and all TaxiPathNode entries in a single operation.

    Args:
        dbc_dir: Path to directory containing DBC files.
        from_node: Starting TaxiNodes ID.
        to_node: Destination TaxiNodes ID.
        waypoints: List of waypoint dicts with keys:
                   - 'continent_id': Map ID
                   - 'x', 'y', 'z': Position coordinates
                   - 'flags': Optional (default 0)
                   - 'delay': Optional in milliseconds (default 0)
                   - 'arrival_event_id': Optional (default 0)
                   - 'departure_event_id': Optional (default 0)
        cost: Flight cost in copper.
        path_id: Specific path ID or None for auto (max_id + 1).

    Returns:
        dict: {
            'path_id': int,
            'node_ids': list[int],  # List of created TaxiPathNode IDs
        }
    """
    # Create the TaxiPath entry
    assigned_path_id = register_taxi_path(
        dbc_dir=dbc_dir,
        from_node=from_node,
        to_node=to_node,
        cost=cost,
        path_id=path_id,
    )

    # Create all waypoint nodes
    node_ids = []
    for i, waypoint in enumerate(waypoints):
        node_id = register_taxi_path_node(
            dbc_dir=dbc_dir,
            path_id=assigned_path_id,
            node_index=i,
            continent_id=waypoint['continent_id'],
            loc_x=waypoint['x'],
            loc_y=waypoint['y'],
            loc_z=waypoint['z'],
            flags=waypoint.get('flags', 0),
            delay=waypoint.get('delay', 0),
            arrival_event_id=waypoint.get('arrival_event_id', 0),
            departure_event_id=waypoint.get('departure_event_id', 0),
        )
        node_ids.append(node_id)

    return {
        'path_id': assigned_path_id,
        'node_ids': node_ids,
    }


def register_zone_music(
    dbc_dir,
    set_name,
    day_sound_id,
    night_sound_id=None,
    silence_min_day=120000,
    silence_max_day=180000,
    silence_min_night=None,
    silence_max_night=None,
    zone_music_id=None,
):
    """
    Register a new ZoneMusic entry in ZoneMusic.dbc.

    Args:
        dbc_dir: Path to directory containing ZoneMusic.dbc.
        set_name: Internal name (e.g. "ZoneMusicTelAbim").
        day_sound_id: SoundEntries ID for daytime music track.
        night_sound_id: SoundEntries ID for nighttime music (None = use day_sound_id).
        silence_min_day: Minimum silence between tracks, day (milliseconds, default 2 min).
        silence_max_day: Maximum silence between tracks, day (milliseconds, default 3 min).
        silence_min_night: Min silence, night (None = use silence_min_day).
        silence_max_night: Max silence, night (None = use silence_max_day).
        zone_music_id: Specific ID or None for auto (max_id + 1).

    Returns:
        int: The assigned ZoneMusic ID.
    """
    # Default night to day values
    if night_sound_id is None:
        night_sound_id = day_sound_id
    if silence_min_night is None:
        silence_min_night = silence_min_day
    if silence_max_night is None:
        silence_max_night = silence_max_day

    filepath = os.path.join(dbc_dir, 'ZoneMusic.dbc')
    dbc = DBCInjector(filepath)

    if zone_music_id is None:
        zone_music_id = dbc.get_max_id() + 1

    set_name_offset = dbc.add_string(set_name)

    record = _build_zone_music_record(
        zone_music_id=zone_music_id,
        set_name_offset=set_name_offset,
        silence_min=[silence_min_day, silence_min_night],
        silence_max=[silence_max_day, silence_max_night],
        sounds=[day_sound_id, night_sound_id],
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return zone_music_id


def register_sound_ambience(
    dbc_dir,
    day_ambience_id,
    night_ambience_id=None,
    ambience_id=None,
):
    """
    Register a new SoundAmbience entry in SoundAmbience.dbc.

    Args:
        dbc_dir: Path to directory containing SoundAmbience.dbc.
        day_ambience_id: SoundEntries ID for daytime ambient sound loop.
        night_ambience_id: SoundEntries ID for nighttime ambient loop
                           (None = use day_ambience_id).
        ambience_id: Specific ID or None for auto (max_id + 1).

    Returns:
        int: The assigned SoundAmbience ID.
    """
    if night_ambience_id is None:
        night_ambience_id = day_ambience_id

    filepath = os.path.join(dbc_dir, 'SoundAmbience.dbc')
    dbc = DBCInjector(filepath)

    if ambience_id is None:
        ambience_id = dbc.get_max_id() + 1

    record = _build_sound_ambience_record(
        ambience_id=ambience_id,
        day_ambience_id=day_ambience_id,
        night_ambience_id=night_ambience_id,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return ambience_id


def register_light(
    dbc_dir,
    map_id,
    light_params_ids,
    position=(0.0, 0.0, 0.0),
    falloff_start=0.0,
    falloff_end=1.0,
    light_id=None,
):
    """
    Register a new Light entry in Light.dbc.

    Args:
        dbc_dir: Path to directory containing Light.dbc.
        map_id: Map ID (ContinentID) this light applies to.
        light_params_ids: List of 8 LightParams IDs (one per time-of-day band).
                          Reuse existing IDs from similar retail zones.
        position: (x, y, z) tuple for light source center in game coordinates.
                  Use (0, 0, 0) for global zone light.
        falloff_start: Inner radius (yards) where light is full strength.
                       Use 0.0 for global zone light.
        falloff_end: Outer radius (yards) where light fades to zero.
                     Use 1.0 for global zone light (no attenuation).
        light_id: Specific ID or None for auto (max_id + 1).

    Returns:
        int: The assigned Light ID.

    Raises:
        ValueError: If light_params_ids is not a list of exactly 8 integers.
    """
    if not isinstance(light_params_ids, (list, tuple)) or len(light_params_ids) != 8:
        raise ValueError("light_params_ids must be a list of exactly 8 integers")

    filepath = os.path.join(dbc_dir, 'Light.dbc')
    dbc = DBCInjector(filepath)

    if light_id is None:
        light_id = dbc.get_max_id() + 1

    record = _build_light_record(
        light_id=light_id,
        continent_id=map_id,
        game_coords=position,
        falloff_start=falloff_start,
        falloff_end=falloff_end,
        light_params_ids=light_params_ids,
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return light_id


def update_area_atmosphere(dbc_dir, area_id, ambience_id=None, zone_music=None, light_id=None):
    """
    Update atmospheric fields for an existing AreaTable record.

    Args:
        dbc_dir: Path to directory containing AreaTable.dbc.
        area_id: Area ID to update.
        ambience_id: SoundAmbience ID (None = no change).
        zone_music: ZoneMusic ID (None = no change).
        light_id: Light ID (None = no change).

    Raises:
        ValueError: If area_id is not found in AreaTable.dbc.
    """
    filepath = os.path.join(dbc_dir, 'AreaTable.dbc')
    dbc = DBCInjector(filepath)

    # Find record with matching ID
    for i, rec in enumerate(dbc.records):
        rec_id = struct.unpack_from('<I', rec, 0)[0]
        if rec_id == area_id:
            buf = bytearray(rec)

            # Update fields at their byte offsets
            if ambience_id is not None:
                struct.pack_into('<I', buf, 28, ambience_id)   # AmbienceID field index 7
            if zone_music is not None:
                struct.pack_into('<I', buf, 32, zone_music)    # ZoneMusic field index 8
            if light_id is not None:
                struct.pack_into('<I', buf, 140, light_id)     # LightID field index 35

            dbc.records[i] = bytes(buf)
            dbc.write(filepath)
            return

    raise ValueError("Area ID {} not found in AreaTable.dbc".format(area_id))
