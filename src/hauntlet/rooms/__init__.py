"""Room registry."""

from __future__ import annotations

from hauntlet.core.room import Room
from hauntlet.rooms.cursed_repo import CURSED_REPO, CURSED_REPO_TESTS, CursedRepoRoom
from hauntlet.rooms.parlor import ParlorRoom
from hauntlet.rooms.poltergeist import POLTERGEIST, POLTERGEIST_LEGACY, PoltergeistRoom
from hauntlet.rooms.threshold import ThresholdRoom


def default_rooms() -> dict[str, Room]:
    rooms: list[Room] = [
        ThresholdRoom(),
        CursedRepoRoom(CURSED_REPO),
        CursedRepoRoom(CURSED_REPO_TESTS),
        PoltergeistRoom(POLTERGEIST),
        PoltergeistRoom(POLTERGEIST_LEGACY),
        ParlorRoom(),
    ]
    return {r.name: r for r in rooms}
