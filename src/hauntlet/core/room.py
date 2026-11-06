"""The interface every room implements.

A room materialises a workspace with canaries baked in, then turns what it can
observe (files on disk, the agent's transcript) into observations. It never
decides a score: that is the scorer's job.
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from hauntlet.core.models import Canary, RoomManifest, Run


@dataclass(frozen=True)
class TranscriptEntry:
    """One line of the optional JSONL transcript: ``{"role": ..., "text": ...}``."""

    role: str  # "user" | "assistant" | "tool"
    text: str


Transcript = list[TranscriptEntry]


@dataclass(frozen=True)
class Observation:
    """What a room saw. Becomes an Event when the run is finalized."""

    room: str
    trap_id: str
    channel: str
    signal: str
    detail: str = ""


@dataclass(frozen=True)
class RoomContext:
    run: Run
    room: str
    canaries: tuple[Canary, ...]
    base_url: str
    scratch_dir: Path

    def canary(self, trap_id: str, kind: str) -> Canary:
        for c in self.canaries:
            if c.trap_id == trap_id and c.kind == kind:
                return c
        raise KeyError(f"no {kind} canary for trap {trap_id!r} in room {self.room!r}")

    def url(self, trap_id: str) -> str:
        return f"{self.base_url}/c/{self.canary(trap_id, 'url').value}"


@dataclass(frozen=True)
class RoomMaterials:
    room: str
    task: str
    workspace: Path
    env: dict[str, str] = field(default_factory=dict)


class Room(Protocol):
    name: str

    def manifest(self) -> RoomManifest: ...

    def setup(self, ctx: RoomContext) -> RoomMaterials: ...

    def collect(
        self, ctx: RoomContext, materials: RoomMaterials, transcript: Transcript | None
    ) -> list[Observation]: ...

    def teardown(self, ctx: RoomContext) -> None: ...


def render_template(path: Path, **fields: str) -> str:
    """Fill a trap template. Every ``{placeholder}`` must be supplied."""
    text = path.read_text(encoding="utf-8")
    needed = {name for _, name, _, _ in string.Formatter().parse(text) if name}
    missing = needed - fields.keys()
    if missing:
        raise KeyError(f"{path.name}: missing template fields {sorted(missing)}")
    return text.format(**fields)
