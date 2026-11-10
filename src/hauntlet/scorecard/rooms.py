"""Room cards (approved change D28): room name -> (display name, what it stands for)."""

from __future__ import annotations

from hauntlet.rooms.cursed_repo.card import ROOM_CARDS as _CURSED
from hauntlet.rooms.parlor.card import ROOM_CARDS as _PARLOR
from hauntlet.rooms.poltergeist.card import ROOM_CARDS as _POLTERGEIST
from hauntlet.rooms.threshold.card import ROOM_CARDS as _THRESHOLD

ROOM_CARDS: dict[str, tuple[str, str]] = {**_THRESHOLD, **_CURSED, **_POLTERGEIST, **_PARLOR}


def card_for(room: str) -> tuple[str, str]:
    """(display name, stands for). An unregistered room shows its own name and nothing else."""
    return ROOM_CARDS.get(room, (room, ""))
