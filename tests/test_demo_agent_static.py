"""The demo agent and interpreter are blind to our rooms (exorcist Requirement 9.1, task 11.3).

A static scan of the demo agent, the interpreter, the hook runner, the steering
grammar and the shipped guard script. It fails on:

- any registered room name or any trap ID from ``default_rooms()``;
- the marker prefix ``hauntlet-mark-`` or the dummy-secret prefix ``HAUNTLET-DUMMY-``;
- ``getenv`` or ``.env`` in ``demo.py`` (it must not read the environment itself);
- an import of ``hauntlet.rooms.*`` (the demo agent may import
  ``hauntlet.agents._task`` only).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hauntlet.rooms import default_rooms

SRC = Path(__file__).resolve().parent.parent / "src/hauntlet"
SCANNED = [
    SRC / "agents/demo.py",
    SRC / "exorcist/interpreter.py",
    SRC / "exorcist/hookrun.py",
    SRC / "exorcist/grammar.py",
    SRC / "exorcist/guards/credential_egress.py",
]

ROOMS = default_rooms()
ROOM_NAMES = sorted(ROOMS)
TRAP_IDS = sorted({t.trap_id for r in ROOMS.values() for t in r.manifest().traps})


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_no_room_name_or_trap_id(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for name in ROOM_NAMES:
        assert name not in text, f"{path.name} names room {name!r}"
    for trap_id in TRAP_IDS:
        # Trap IDs are hyphenated tokens; match as whole words to avoid false hits
        # on ordinary words, but every real trap ID still trips it.
        assert not re.search(rf"\b{re.escape(trap_id)}\b", text), f"{path.name} names trap {trap_id!r}"


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_no_marker_or_secret_prefix(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "hauntlet-mark-" not in text
    assert "HAUNTLET-DUMMY-" not in text


def test_demo_agent_does_not_read_the_environment() -> None:
    text = (SRC / "agents/demo.py").read_text(encoding="utf-8")
    assert "getenv" not in text
    assert ".env" not in text  # no materials.env / tools.env access


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_no_room_imports(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "hauntlet.rooms" not in stripped, f"{path.name}: {stripped!r}"
