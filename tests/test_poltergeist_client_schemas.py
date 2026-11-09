"""Tests for ``PoltergeistClient.input_schemas()`` (approved change D20, Exorcist task 1.2).

The accessor returns the ``inputSchema`` of every tool from the latest
``tools/list``: equal to the server's ``INPUT_SCHEMAS`` after ``approve()`` and
after the post-mutation ``relist()``, on ``poltergeist`` (2026-07-28) and on
``poltergeist-legacy`` under both 2025-11-25 and 2025-06-18. It is a copy, and
it is empty before ``approve()``. The naive and hardened goldens are covered,
unchanged, by ``tests/test_poltergeist_e2e.py``.

_Requirements (exorcist): 14.1 (g), D20_
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import mcp.client.session as sdk_session
import pytest

from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.core.toolbox import ToolBox
from hauntlet.rooms.poltergeist import factlog
from hauntlet.rooms.poltergeist.client import connect
from hauntlet.rooms.poltergeist.config import POLTERGEIST, POLTERGEIST_LEGACY, RoomConfig
from hauntlet.rooms.poltergeist.room import PoltergeistRoom
from hauntlet.rooms.poltergeist.server import INPUT_SCHEMAS

BASE_URL = "http://range.test"

CASES = [
    (POLTERGEIST, "2026-07-28", False),
    (POLTERGEIST_LEGACY, "2025-11-25", False),
    (POLTERGEIST_LEGACY, "2025-06-18", True),
]


@pytest.fixture
def rig(tmp_path: Path) -> Iterator:
    rooms = {c.name: PoltergeistRoom(c) for c in (POLTERGEIST, POLTERGEIST_LEGACY)}
    service = RangeService(Store(":memory:"), rooms, base_url=BASE_URL)
    made = []

    def make(cfg: RoomConfig):
        room = rooms[cfg.name]
        run_id = service.start_run([cfg.name]).run.run_id
        ctx = service.context(run_id, cfg.name, tmp_path)
        materials = room.setup(ctx)
        made.append((room, ctx))
        tools = ToolBox(materials.workspace, materials.env, service.fetch_local, BASE_URL)
        return ctx, materials, tools

    yield make
    for room, ctx in made:
        room.teardown(ctx)


def _negotiated(ctx, materials) -> str | None:
    facts = factlog.read(factlog.facts_path(materials.workspace), ctx.run.run_id)
    return next((f.revision for f in facts if isinstance(f, factlog.NegotiatedFact)), None)


@pytest.mark.parametrize(
    ("cfg", "revision", "patch"), CASES, ids=[f"{c.name}@{r}" for c, r, _ in CASES]
)
def test_input_schemas_match_server_before_and_after_mutation(
    cfg: RoomConfig, revision: str, patch: bool, rig, monkeypatch
) -> None:
    if patch:
        monkeypatch.setattr(sdk_session, "LATEST_HANDSHAKE_VERSION", revision)
    ctx, materials, tools = rig(cfg)
    with connect(materials, tools) as client:
        assert client.input_schemas() == {}, "empty before approve()"

        approved = client.approve()
        assert client.input_schemas() == INPUT_SCHEMAS

        client.call("list_topics")  # the first call triggers the rug pull
        client.on_change()
        relisted = client.relist()
        assert relisted["get_note"] != approved["get_note"], "the relist saw the rug pull"
        assert client.input_schemas() == INPUT_SCHEMAS, "schemas unchanged across mutation"

    assert _negotiated(ctx, materials) == revision


def test_input_schemas_returns_a_copy(rig) -> None:
    _ctx, materials, tools = rig(POLTERGEIST)
    with connect(materials, tools) as client:
        client.approve()
        first = client.input_schemas()
        first["get_note"]["properties"]["topic"]["type"] = "integer"
        first.pop("save_note")
        assert client.input_schemas() == INPUT_SCHEMAS
