"""
DBC file injector for WoW WotLK 3.3.5a (build 12340).

Provides low-level binary read/write of DBC files and convenience functions
for injecting custom Map and AreaTable entries. Works directly with raw bytes
so it does not depend on the DBD definition infrastructure.

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


def register_area(dbc_dir, area_name, map_id, area_id=None, parent_area_id=0):
    """
    Register a new area in AreaTable.dbc.

    Args:
        dbc_dir: Path to directory containing AreaTable.dbc.
        area_name: Display name for the area.
        map_id: Map ID this area belongs to (ContinentID).
        area_id: Specific area ID or None for auto (max_id + 1).
        parent_area_id: Parent area (0 for top-level zone).

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
    )

    dbc.records.append(record)
    dbc.write(filepath)

    return area_id
