"""Put API positions on Oxford's map image.

Oxford publishes a top-down map image (https://docs.oxfd.re/#res-map) whose top-left corner is
``x = -6700, z = -2500`` and bottom-right corner is ``x = 1450, z = 3800``. Positions from the
API are ``[x, y, z]``; only ``x`` and ``z`` matter on the map (``y`` is height).

The full-size image is 8151 x 6301 pixels, so 1 stud is about 1 pixel. If you resize the image,
pass your size to :func:`to_pixels`.

Example::

    from oxrpy.map import to_pixels

    for player in api.get_players() or []:
        if player.get("Position"):
            px, py = to_pixels(player["Position"], width=1630, height=1260)   # a 20% size copy
"""

from __future__ import annotations

import math
from typing import Optional, Sequence, Tuple

#: Oxford's map image (it may change when the map does; check the docs for the latest).
MAP_IMAGE_URL = "https://docs.oxfd.re/map-march.png"

#: ``(x, z)`` of the image's top-left and bottom-right corners, in studs.
MAP_TOP_LEFT = (-6700.0, -2500.0)
MAP_BOTTOM_RIGHT = (1450.0, 3800.0)

#: The full-size image's size in pixels.
MAP_IMAGE_SIZE = (8151, 6301)


def _xz(position: Sequence[float]) -> Tuple[float, float]:
    """``[x, y, z]`` -> ``(x, z)``. Also accepts ``(x, z)``."""
    if position is None:
        raise ValueError("position is None (the player hasn't spawned, or the server is offline)")
    if len(position) == 3:
        return float(position[0]), float(position[2])
    if len(position) == 2:
        return float(position[0]), float(position[1])
    raise ValueError(f"position must be [x, y, z] or (x, z), got {position!r}")


def to_pixels(
    position: Sequence[float],
    width: Optional[float] = None,
    height: Optional[float] = None,
    *,
    clamp: bool = False,
) -> Tuple[float, float]:
    """Where a position falls on the map image, in pixels from its top-left corner.

    Args:
        position: ``[x, y, z]`` from the API (or ``(x, z)``).
        width, height: Your image's size. Defaults to the full-size image.
        clamp: Keep the point inside the image (otherwise points off the map come back
            negative or larger than the image).
    """
    full_w, full_h = MAP_IMAGE_SIZE
    width = full_w if width is None else width
    height = full_h if height is None else height
    x, z = _xz(position)
    (left, top), (right, bottom) = MAP_TOP_LEFT, MAP_BOTTOM_RIGHT
    px = (x - left) / (right - left) * width
    py = (z - top) / (bottom - top) * height
    if clamp:
        px = min(max(px, 0.0), float(width))
        py = min(max(py, 0.0), float(height))
    return px, py


def from_pixels(
    px: float,
    py: float,
    width: Optional[float] = None,
    height: Optional[float] = None,
) -> Tuple[float, float]:
    """The other way: a pixel on the map image -> ``(x, z)`` in studs. Handy for
    ``api.create_incident(team, priority, x, z, text)`` from a click on a map."""
    full_w, full_h = MAP_IMAGE_SIZE
    width = full_w if width is None else width
    height = full_h if height is None else height
    (left, top), (right, bottom) = MAP_TOP_LEFT, MAP_BOTTOM_RIGHT
    return left + px / width * (right - left), top + py / height * (bottom - top)


def on_map(position: Sequence[float]) -> bool:
    """Whether a position is inside the area the map image covers."""
    x, z = _xz(position)
    (left, top), (right, bottom) = MAP_TOP_LEFT, MAP_BOTTOM_RIGHT
    return left <= x <= right and top <= z <= bottom


def distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Distance in studs between two positions, across the ground (ignoring height)."""
    ax, az = _xz(a)
    bx, bz = _xz(b)
    return math.hypot(ax - bx, az - bz)


def nearest(position: Sequence[float], places: Sequence[dict]) -> Optional[dict]:
    """The entry in ``places`` (anything with a ``Position``, e.g. the Catalogue's
    ``Map.Places``, ``PointsOfInterest``, players or vehicles) closest to ``position``."""
    best, best_distance = None, math.inf
    for place in places:
        where = place.get("Position")
        if not where:
            continue
        d = distance(position, where)
        if d < best_distance:
            best, best_distance = place, d
    return best
