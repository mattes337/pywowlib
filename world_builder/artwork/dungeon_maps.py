"""
Dungeon map overlay generator for WoW WotLK 3.3.5a.

Procedurally generates top-down floor-plan views for dungeon instances.
Rooms are rendered as coloured rectangles connected by corridor lines,
with boss markers (red circles) and an entrance arrow.
"""

import logging

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise ImportError(
        "Pillow is required for dungeon map generation.  "
        "Install with: pip install Pillow"
    )

from .text_rendering import load_font, draw_text_outlined


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class Room:
    """
    A single dungeon room.

    Attributes:
        id:     Unique integer identifier.
        name:   Human-readable room name.
        type:   One of 'corridor', 'chamber', 'boss_room'.
        bounds: (x_min, x_max, y_min, y_max) in world units.
    """

    __slots__ = ('id', 'name', 'type', 'bounds')

    def __init__(self, id, name, type, bounds):
        self.id = id
        self.name = name
        self.type = type
        self.bounds = tuple(bounds)


class Connection:
    """
    A corridor between two rooms.

    Attributes:
        room_a_id: ID of the first room.
        room_b_id: ID of the second room.
    """

    __slots__ = ('room_a_id', 'room_b_id')

    def __init__(self, room_a_id, room_b_id):
        self.room_a_id = room_a_id
        self.room_b_id = room_b_id


class DungeonLayout:
    """
    Complete dungeon floor plan.

    Attributes:
        rooms:       List of :class:`Room` instances.
        connections: List of :class:`Connection` instances.
    """

    __slots__ = ('rooms', 'connections')

    def __init__(self, rooms, connections):
        self.rooms = list(rooms)
        self.connections = list(connections)


# ---------------------------------------------------------------------------
# Room colours
# ---------------------------------------------------------------------------

_ROOM_COLORS = {
    'corridor': (40, 40, 40),
    'chamber': (80, 80, 80),
    'boss_room': (100, 40, 40),
}

_ROOM_OUTLINE = (120, 120, 120)
_CONNECTION_COLOR = (80, 80, 80)


# ---------------------------------------------------------------------------
# Scale helpers
# ---------------------------------------------------------------------------

def _compute_layout_transform(layout, image_size, margin=0.05):
    """
    Compute the scale and offset needed to fit *layout* into *image_size*.

    Returns:
        (scale, offset_x, offset_y) where offset is the minimum world
        coordinate in each axis.
    """
    all_x = []
    all_y = []
    for room in layout.rooms:
        all_x.extend([room.bounds[0], room.bounds[1]])
        all_y.extend([room.bounds[2], room.bounds[3]])

    if not all_x or not all_y:
        return (1.0, 0.0, 0.0)

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    world_w = max_x - min_x
    world_h = max_y - min_y

    if world_w == 0:
        world_w = 1.0
    if world_h == 0:
        world_h = 1.0

    usable_w = image_size[0] * (1 - 2 * margin)
    usable_h = image_size[1] * (1 - 2 * margin)

    scale = min(usable_w / world_w, usable_h / world_h)
    offset_x = min_x - (image_size[0] / scale - world_w) / 2
    offset_y = min_y - (image_size[1] / scale - world_h) / 2

    return (scale, offset_x, offset_y)


def _world_to_px(wx, wy, scale, offset_x, offset_y):
    """Convert world coordinates to pixel coordinates."""
    return (int((wx - offset_x) * scale), int((wy - offset_y) * scale))


# ---------------------------------------------------------------------------
# Room layout rendering
# ---------------------------------------------------------------------------

def _render_rooms(draw, layout, scale, offset_x, offset_y, label_font):
    """Draw all rooms as coloured rectangles with optional labels."""
    for room in layout.rooms:
        x1, y1 = _world_to_px(room.bounds[0], room.bounds[2], scale, offset_x, offset_y)
        x2, y2 = _world_to_px(room.bounds[1], room.bounds[3], scale, offset_x, offset_y)

        color = _ROOM_COLORS.get(room.type, (60, 60, 60))
        draw.rectangle([x1, y1, x2, y2], fill=color, outline=_ROOM_OUTLINE, width=2)

        # Label important rooms
        if room.type in ('chamber', 'boss_room') and room.name:
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            draw_text_outlined(
                draw, (cx, cy), room.name, font=label_font,
                fill=(200, 200, 200), outline=(0, 0, 0), outline_width=1,
            )


# ---------------------------------------------------------------------------
# Connection rendering
# ---------------------------------------------------------------------------

def _render_connections(draw, layout, scale, offset_x, offset_y):
    """Draw corridor lines between connected rooms."""
    room_by_id = {r.id: r for r in layout.rooms}

    for conn in layout.connections:
        room_a = room_by_id.get(conn.room_a_id)
        room_b = room_by_id.get(conn.room_b_id)
        if room_a is None or room_b is None:
            continue

        # Centre of each room
        cx_a = (room_a.bounds[0] + room_a.bounds[1]) / 2
        cy_a = (room_a.bounds[2] + room_a.bounds[3]) / 2
        cx_b = (room_b.bounds[0] + room_b.bounds[1]) / 2
        cy_b = (room_b.bounds[2] + room_b.bounds[3]) / 2

        pa = _world_to_px(cx_a, cy_a, scale, offset_x, offset_y)
        pb = _world_to_px(cx_b, cy_b, scale, offset_x, offset_y)

        draw.line([pa, pb], fill=_CONNECTION_COLOR, width=4)


# ---------------------------------------------------------------------------
# Boss markers
# ---------------------------------------------------------------------------

def _render_boss_markers(draw, boss_positions, scale, offset_x, offset_y):
    """Draw red circles with 'B' at each boss location."""
    marker_font = load_font(size=14, bold=True)
    label_font = load_font(size=10)

    for boss_name, (bx, by) in boss_positions:
        px, py = _world_to_px(bx, by, scale, offset_x, offset_y)
        radius = 12

        # Red circle
        draw.ellipse(
            [px - radius, py - radius, px + radius, py + radius],
            fill=(180, 0, 0), outline=(255, 255, 255), width=2,
        )

        # 'B' marker
        draw.text((px - 4, py - 7), 'B', font=marker_font, fill=(255, 255, 255))

        # Boss name label
        draw_text_outlined(
            draw, (px + radius + 5, py - 5), boss_name, font=label_font,
            fill=(220, 220, 220), outline=(0, 0, 0), outline_width=1,
        )


# ---------------------------------------------------------------------------
# Entrance marker
# ---------------------------------------------------------------------------

def _render_entrance(draw, entrance, scale, offset_x, offset_y):
    """Draw a green downward-pointing arrow at the entrance."""
    ex, ey = entrance
    px, py = _world_to_px(ex, ey, scale, offset_x, offset_y)

    arrow = [
        (px, py + 15),       # Tip
        (px - 10, py - 5),   # Left wing
        (px + 10, py - 5),   # Right wing
    ]
    draw.polygon(arrow, fill=(0, 200, 0), outline=(255, 255, 255))


# ---------------------------------------------------------------------------
# High-level generator
# ---------------------------------------------------------------------------

def generate_dungeon_map(layout, boss_positions, entrance_position,
                         size=(512, 512), dungeon_name="Dungeon"):
    """
    Procedurally generate a dungeon map overlay.

    Pipeline:
        1. Compute scale/offset to fit layout into image
        2. Render corridor connections (grey lines)
        3. Render rooms (coloured rectangles with labels)
        4. Render boss markers (red circles)
        5. Render entrance marker (green arrow)

    Args:
        layout:            :class:`DungeonLayout` with rooms and connections.
        boss_positions:    List of (boss_name, (world_x, world_y)) tuples.
        entrance_position: (world_x, world_y) entrance location.
        size:              (width, height) output dimensions.
        dungeon_name:      Dungeon name (metadata).

    Returns:
        Pillow RGB Image.
    """
    log.info("Generating dungeon map '%s' at %s", dungeon_name, size)

    img = Image.new('RGB', size, (0, 0, 0))
    draw = ImageDraw.Draw(img)

    scale, off_x, off_y = _compute_layout_transform(layout, size)
    label_font = load_font(size=12)

    # Order matters: connections behind rooms
    _render_connections(draw, layout, scale, off_x, off_y)
    _render_rooms(draw, layout, scale, off_x, off_y, label_font)
    _render_boss_markers(draw, boss_positions, scale, off_x, off_y)
    _render_entrance(draw, entrance_position, scale, off_x, off_y)

    log.info("Dungeon map complete for '%s'", dungeon_name)
    return img
