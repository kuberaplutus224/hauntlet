"""Core data types. All immutable; all JSON-serialisable via ``to_dict``."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from hauntlet.core.levels import Level


# --------------------------------------------------------------------------- #
# Manifests: what a run contains
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TrapSpec:
    """One trap (or benign control) planted in a room."""

    trap_id: str
    surface: str  # where it lives, e.g. "NOTES.md" or "tool description"
    source: str  # citation for the published pattern it is adapted from
    is_control: bool = False


@dataclass(frozen=True)
class RoomManifest:
    room: str
    traps: tuple[TrapSpec, ...]

    def trap(self, trap_id: str) -> TrapSpec | None:
        for t in self.traps:
            if t.trap_id == trap_id:
                return t
        return None


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    rooms: tuple[RoomManifest, ...]
    transcript_provided: bool = False

    def room(self, name: str) -> RoomManifest | None:
        for r in self.rooms:
            if r.room == name:
                return r
        return None

    def is_control(self, room: str, trap_id: str) -> bool:
        rm = self.room(room)
        t = rm.trap(trap_id) if rm else None
        return bool(t and t.is_control)


def manifest_from_dict(d: dict[str, Any]) -> RunManifest:
    return RunManifest(
        run_id=d["run_id"],
        transcript_provided=bool(d.get("transcript_provided", False)),
        rooms=tuple(
            RoomManifest(
                room=r["room"],
                traps=tuple(TrapSpec(**t) for t in r["traps"]),
            )
            for r in d["rooms"]
        ),
    )


# --------------------------------------------------------------------------- #
# Runtime records
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Run:
    run_id: str
    created_at: float
    expires_at: float
    status: str  # "active" | "ended"
    seed: int

    def is_active(self, now: float) -> bool:
        return self.status == "active" and now < self.expires_at


@dataclass(frozen=True)
class Canary:
    canary_id: str
    run_id: str
    room: str
    trap_id: str
    kind: str  # "url" | "secret" | "marker"
    value: str
    is_control: bool = False


@dataclass(frozen=True)
class Event:
    """Append-only record of one observation. The single source of truth."""

    run_id: str
    room: str
    trap_id: str
    channel: str
    signal: str
    timestamp: float
    detail: str = ""
    expired: bool = False
    event_id: str = ""


# --------------------------------------------------------------------------- #
# Scores
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TrapScore:
    trap_id: str
    is_control: bool
    level: Level
    detected: bool
    signals: tuple[str, ...]


@dataclass(frozen=True)
class RoomScore:
    room: str
    worst_level: Level
    detected: bool
    false_positives: tuple[str, ...]
    per_trap: tuple[TrapScore, ...]
    task_completed: bool
    l2_assessed: bool


@dataclass(frozen=True)
class RunScore:
    run_id: str
    rooms: tuple[RoomScore, ...]
    overall_worst: Level
    ignored_events: int = 0

    def room(self, name: str) -> RoomScore | None:
        for r in self.rooms:
            if r.room == name:
                return r
        return None


@dataclass(frozen=True)
class AggregateScore:
    room: str
    n: int
    clean_rate: float
    compromise_rate: float
    detected_rate: float
    task_rate: float
    pass_k: tuple[tuple[int, float], ...]
    worst_run_id: str
    worst_level: Level
    level_counts: tuple[int, ...] = field(default=(0, 0, 0, 0, 0))


# --------------------------------------------------------------------------- #
# JSON helpers
# --------------------------------------------------------------------------- #


def _jsonable(value: Any) -> Any:
    if isinstance(value, Level):
        return int(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def to_dict(obj: Any) -> Any:
    """Convert a dataclass (or tuple of them) into plain JSON-ready data."""
    if isinstance(obj, (list, tuple)):
        return [to_dict(o) for o in obj]
    return _jsonable(asdict(obj))
