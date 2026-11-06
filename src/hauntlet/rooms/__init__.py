"""Room registry."""

from __future__ import annotations

from hauntlet.core.room import Room
from hauntlet.rooms.threshold import ThresholdRoom


def default_rooms() -> dict[str, Room]:
    rooms: list[Room] = [ThresholdRoom()]
    return {r.name: r for r in rooms}
