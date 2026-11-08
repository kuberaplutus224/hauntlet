"""Tests for the in-process client helper ``rooms/poltergeist/client.py`` (task 9.1).

Each case sets up a real Poltergeist room on a real ``RangeService`` and drives
it through ``connect(materials, tools)`` with a real ``ToolBox`` whose fetcher
is ``RangeService.fetch_local``, exactly as the core runner hands it to an
agent. Both rooms are covered: ``poltergeist`` (2026-07-28, subscription) and
``poltergeist-legacy`` (2025-11-25 handshake, ``list_changed``).

_Requirements: 9.4, 10.2, 12 D4_
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from hauntlet.core.levels import Channel, Signal
from hauntlet.core.room import RoomContext, RoomMaterials
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.core.toolbox import ToolBox
from hauntlet.rooms.poltergeist import factlog
from hauntlet.rooms.poltergeist.client import PoltergeistClient, ToolCallError, connect
from hauntlet.rooms.poltergeist.config import (
    POLTERGEIST,
    POLTERGEIST_LEGACY,
    RUG_DESC,
    TOOL_OUTPUT,
    RoomConfig,
)
from hauntlet.rooms.poltergeist.room import ENV_RUN, PoltergeistRoom, server_for
from hauntlet.rooms.poltergeist.server import POST, PRE, PoltergeistServer

BASE_URL = "http://range.test"
NAMED_PATH = "sync-ack.txt"
CONFIGS = [POLTERGEIST, POLTERGEIST_LEGACY]
EXPECTED_VERSION = {POLTERGEIST.name: "2026-07-28", POLTERGEIST_LEGACY.name: "2025-11-25"}

params = pytest.mark.parametrize("cfg", CONFIGS, ids=lambda c: c.name)


@dataclass
class Rig:
    cfg: RoomConfig
    service: RangeService
    ctx: RoomContext
    materials: RoomMaterials
    tools: ToolBox

    @property
    def server(self) -> PoltergeistServer:
        return server_for(self.materials)

    def desc(self, tool: str, version: str) -> str:
        return self.server._descriptions[tool][version]

    def facts(self) -> list[factlog.Fact]:
        return factlog.read(factlog.facts_path(self.materials.workspace), self.ctx.run.run_id)

    def network(self, trap_id: str) -> set[str]:
        return {
            e.signal
            for e in self.service.store.events_for_run(self.ctx.run.run_id)
            if e.trap_id == trap_id and e.channel == Channel.NETWORK
        }


@pytest.fixture
def make_rig(tmp_path: Path) -> Iterator[Callable[..., Rig]]:
    rooms = {c.name: PoltergeistRoom(c) for c in CONFIGS}
    service = RangeService(Store(":memory:"), rooms, base_url=BASE_URL)
    made: list[tuple[PoltergeistRoom, RoomContext]] = []

    def make(cfg: RoomConfig, *, toolbox_base: str = BASE_URL) -> Rig:
        room = rooms[cfg.name]
        run_id = service.start_run([cfg.name]).run.run_id
        ctx = service.context(run_id, cfg.name, tmp_path)
        materials = room.setup(ctx)
        made.append((room, ctx))
        tools = ToolBox(materials.workspace, materials.env, service.fetch_local, toolbox_base)
        return Rig(cfg, service, ctx, materials, tools)

    yield make
    for room, ctx in made:
        room.teardown(ctx)


@pytest.fixture
def client_of() -> Iterator[Callable[[Rig], PoltergeistClient]]:
    opened: list[PoltergeistClient] = []

    def open_(rig: Rig) -> PoltergeistClient:
        c = connect(rig.materials, rig.tools)
        opened.append(c)
        return c

    yield open_
    for c in opened:
        c.close()


# --------------------------------------------------------------------------- #
# approve, the change signal, relist
# --------------------------------------------------------------------------- #


@params
def test_approve_lists_pre_mutation_descriptions(cfg: RoomConfig, make_rig, client_of) -> None:
    rig = make_rig(cfg)
    c = client_of(rig)
    assert c.protocol_version == EXPECTED_VERSION[cfg.name]
    assert c.descriptions() == {}

    listed = c.approve()
    assert list(listed) == [t.name for t in cfg.tools]
    assert listed["get_note"] == rig.desc("get_note", PRE)
    assert listed["check_health"] == rig.desc("check_health", PRE)
    assert c.descriptions() == listed
    assert c.subscribed is (cfg is POLTERGEIST)
    assert c.changes == 0

    negotiated = [f for f in rig.facts() if isinstance(f, factlog.NegotiatedFact)]
    assert {f.revision for f in negotiated} == {EXPECTED_VERSION[cfg.name]}
    assert any(f.subscribed for f in negotiated) is (cfg is POLTERGEIST)


@params
def test_first_call_signals_change_and_relist_returns_post_description(
    cfg: RoomConfig, make_rig, client_of
) -> None:
    rig = make_rig(cfg)
    c = client_of(rig)
    c.approve()

    topics = c.call("list_topics")
    assert "mascot" in topics
    c.on_change()
    assert c.changes == 1
    # Nothing re-listed yet: the remembered set is still the approved one.
    assert c.descriptions()["get_note"] == rig.desc("get_note", PRE)

    after = c.relist()
    assert after["get_note"] == rig.desc("get_note", POST)
    assert after["check_health"] == rig.desc("check_health", POST)
    assert after["get_note"] != rig.desc("get_note", PRE)
    assert c.descriptions() == after

    lists = [f for f in rig.facts() if isinstance(f, factlog.ListFact)]
    assert [f.after_mutation for f in lists] == [False, True]
    assert dict(lists[-1].desc_versions) == {"get_note": POST, "check_health": POST}

    # Only one rug pull, so no second signal.
    with pytest.raises(TimeoutError):
        c.on_change(timeout=0.2)


@params
def test_on_change_times_out_without_a_call(cfg: RoomConfig, make_rig, client_of) -> None:
    c = client_of(make_rig(cfg))
    c.approve()
    with pytest.raises(TimeoutError):
        c.on_change(timeout=0.2)


@params
def test_call_before_approve_is_refused(cfg: RoomConfig, make_rig, client_of) -> None:
    rig = make_rig(cfg)
    c = client_of(rig)
    with pytest.raises(RuntimeError, match="approve"):
        c.call("list_topics")
    assert not any(isinstance(f, factlog.CallFact) for f in rig.facts())


# --------------------------------------------------------------------------- #
# ToolBox I/O injection
# --------------------------------------------------------------------------- #


@params
def test_relay_and_scratch_write_go_through_the_toolbox(cfg: RoomConfig, make_rig, client_of) -> None:
    rig = make_rig(cfg)
    secret = rig.materials.env["POLTERGEIST_SESSION"]
    marker = rig.ctx.canary(TOOL_OUTPUT, "marker").value
    c = client_of(rig)
    c.approve()
    c.call("list_topics")
    c.on_change()
    c.relist()

    assert c.call("report_telemetry", payload=secret) == "Telemetry sent."
    assert c.call("save_note", name="../escape", text=f"ack-{marker}") == "Note saved."
    note = c.call("get_note", topic="mascot")
    assert f"session: {secret}" in note
    assert c.call("submit_answer", answer="Boo") == "Answer recorded."

    # Relay: through ToolBox.fetch to the run's own canary URL, into fetch_local.
    fetches = [x for x in rig.tools.calls if x.startswith("fetch ")]
    assert len(fetches) == 1
    assert fetches[0].startswith(f"fetch {rig.ctx.url(RUG_DESC)}?payload=")
    assert rig.network(RUG_DESC) == {Signal.REACHED, Signal.EXPOSED}

    # Scratch write: through ToolBox.write_file at the fixed path only.
    assert [x for x in rig.tools.calls if x.startswith("write_file")] == [f"write_file {NAMED_PATH}"]
    ws = rig.materials.workspace
    assert (ws / NAMED_PATH).read_text(encoding="utf-8") == f"ack-{marker}"
    assert not (ws.parent / "escape").exists()


@params
def test_toolbox_confinement_blocks_relay_off_the_canary_endpoint(
    cfg: RoomConfig, make_rig, client_of
) -> None:
    # A ToolBox whose canary prefix is another origin refuses the room's URL.
    rig = make_rig(cfg, toolbox_base="http://elsewhere.test")
    c = client_of(rig)
    c.approve()
    with pytest.raises(ToolCallError, match="Telemetry failed: PermissionError"):
        c.call("report_telemetry", payload="x")
    assert rig.network(RUG_DESC) == set()
    assert not any(isinstance(f, factlog.RelayFact) for f in rig.facts())


# --------------------------------------------------------------------------- #
# lookup and lifecycle
# --------------------------------------------------------------------------- #


@params
def test_connect_without_a_registered_server_raises(cfg: RoomConfig, make_rig) -> None:
    rig = make_rig(cfg)
    missing = RoomMaterials(
        room=cfg.name, task=cfg.task, workspace=rig.materials.workspace, env={ENV_RUN: "run-nope"}
    )
    with pytest.raises(KeyError):
        connect(missing, rig.tools)
    no_env = RoomMaterials(room=cfg.name, task=cfg.task, workspace=rig.materials.workspace, env={})
    with pytest.raises(KeyError):
        connect(no_env, rig.tools)


@params
def test_close_is_idempotent_and_stops_the_private_loop(cfg: RoomConfig, make_rig) -> None:
    rig = make_rig(cfg)
    before = threading.active_count()
    with connect(rig.materials, rig.tools) as c:
        c.approve()
        assert c.call("check_health") == "ok"
    c.close()
    assert c.protocol_version is None
    with pytest.raises(RuntimeError):
        c.call("check_health")
    assert threading.active_count() <= before
