"""Threat-profile registry (exorcist approved change D15).

The only Exorcist module that names rooms. It collects each room package's
``threats.THREATS`` and exposes the profile by room name. It also supplies the
demo agent's environment channel (Requirement 8.9). That channel is passed in
by the harness (``get_agent`` / ``ExorcistService``), so the demo agent itself
never looks a room up.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from hauntlet.core.room import RoomMaterials
from hauntlet.exorcist.model import RoomThreats
from hauntlet.rooms.cursed_repo.threats import THREATS as _CURSED_REPO
from hauntlet.rooms.parlor.threats import THREATS as _PARLOR
from hauntlet.rooms.poltergeist.threats import THREATS as _POLTERGEIST
from hauntlet.rooms.threshold.threats import THREATS as _THRESHOLD


def _merge(*parts: Mapping[str, RoomThreats]) -> Mapping[str, RoomThreats]:
    merged: dict[str, RoomThreats] = {}
    for part in parts:
        for name, threats in part.items():
            if name in merged:
                raise ValueError(f"room {name!r} has two threat profiles")
            merged[name] = threats
    return MappingProxyType(merged)


PROFILES: Mapping[str, RoomThreats] = _merge(_THRESHOLD, _CURSED_REPO, _POLTERGEIST, _PARLOR)


def profile_for(room_name: str) -> RoomThreats:
    """The room's threat profile. Raises ``KeyError`` naming the known rooms."""
    try:
        return PROFILES[room_name]
    except KeyError:
        raise KeyError(
            f"no threat profile for room {room_name!r}; known rooms: {sorted(PROFILES)}"
        ) from None


def real_client_env(materials: RoomMaterials) -> dict[str, str]:
    """The agent environment a real client of ``materials.room`` gets (Requirement 8.9).

    Exactly the room's declared ``real_client_env`` names that ``setup``
    planted. This is empty for rooms whose real clients get nothing from the
    environment, such as the Poltergeist rooms.
    """
    names = profile_for(materials.room).real_client_env
    return {k: v for k, v in materials.env.items() if k in names}
