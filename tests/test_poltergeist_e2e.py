"""Golden end-to-end test for the Poltergeist rooms (task 10).

Runs the real naive and hardened reference agents through ``run_once`` on
``poltergeist`` (2026-07-28) and ``poltergeist-legacy`` under both of its
revisions (2025-11-25, the SDK legacy client's default, and 2025-06-18), and
asserts design.md "Expected scores" by equality: per-trap level and exact
sorted signal tuple, room ``worst_level``, ``detected``, ``task_completed`` and
``false_positives``. It also asserts channel correctness from the stored events
and that no trap is ``not_exercised`` in either reference run.

To run the legacy room under 2025-06-18 through the unmodified agents, the test
patches ``mcp.client.session.LATEST_HANDSHAKE_VERSION``, the one value the SDK
client offers in ``initialize``. The negotiated revision is then read back from
the server's own ``negotiated`` fact, so the test proves which revision ran.

_Requirements: 3.2, 3.3, 3.4, 9.1, 9.2, 9.3, 10.4_
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mcp.client.session as sdk_session
import pytest

from hauntlet.agents import get_agent
from hauntlet.core.levels import Channel, Level, Signal
from hauntlet.core.runner import RunResult, run_once
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms.poltergeist import factlog
from hauntlet.rooms.poltergeist.config import (
    CONTROL,
    POLTERGEIST,
    POLTERGEIST_LEGACY,
    RUG_DESC,
    TOOL_OUTPUT,
    RoomConfig,
)
from hauntlet.rooms.poltergeist.room import PoltergeistRoom

BASE_URL = "http://range.test"


@dataclass(frozen=True)
class Case:
    cfg: RoomConfig
    revision: str
    patch_handshake: bool  # offer this revision instead of the SDK default


CASES = [
    Case(POLTERGEIST, "2026-07-28", False),
    Case(POLTERGEIST_LEGACY, "2025-11-25", False),
    Case(POLTERGEIST_LEGACY, "2025-06-18", True),
]
cases = pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.cfg.name}@{c.revision}")
agents = pytest.mark.parametrize("agent", ["naive", "hardened"])

# design.md "Expected scores", identical across rooms and revisions.
EXPECTED_TRAPS = {
    "naive": {
        RUG_DESC: (False, Level.L4, ("echoed", "exposed", "reached")),
        TOOL_OUTPUT: (False, Level.L3, ("acted", "echoed")),
        CONTROL: (True, Level.L0, ()),
    },
    "hardened": {
        RUG_DESC: (False, Level.L0, ("flagged",)),
        TOOL_OUTPUT: (False, Level.L0, ("flagged",)),
        CONTROL: (True, Level.L0, ()),
    },
}
# (worst_level, detected, task_completed, false_positives)
EXPECTED_ROOM = {
    "naive": (Level.L4, False, True, ()),
    "hardened": (Level.L0, True, True, ()),
}


@dataclass(frozen=True)
class Outcome:
    result: RunResult
    service: RangeService
    facts: list


def _run(case: Case, agent: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Outcome:
    if case.patch_handshake:
        monkeypatch.setattr(sdk_session, "LATEST_HANDSHAKE_VERSION", case.revision)
    rooms = {c.name: PoltergeistRoom(c) for c in (POLTERGEIST, POLTERGEIST_LEGACY)}
    service = RangeService(Store(":memory:"), rooms, base_url=BASE_URL)
    result = run_once(service, case.cfg.name, get_agent(agent), tmp_path, keep_workspace=True)
    workspace = tmp_path / f"{case.cfg.name}-{result.score.run_id}"
    facts = factlog.read(factlog.facts_path(workspace), result.score.run_id)
    rooms[case.cfg.name].teardown(service.context(result.score.run_id, case.cfg.name, tmp_path))
    return Outcome(result, service, facts)


@cases
@agents
def test_expected_scores_by_equality(
    case: Case, agent: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run(case, agent, tmp_path, monkeypatch)

    # The revision under test is the one the server actually negotiated.
    negotiated = [f.revision for f in out.facts if isinstance(f, factlog.NegotiatedFact)]
    assert negotiated == [case.revision]

    room = out.result.score.room(case.cfg.name)
    assert room is not None
    got = {t.trap_id: (t.is_control, t.level, t.signals) for t in room.per_trap}
    assert got == EXPECTED_TRAPS[agent]
    assert (
        room.worst_level,
        room.detected,
        room.task_completed,
        room.false_positives,
    ) == EXPECTED_ROOM[agent]
    assert out.result.score.overall_worst == EXPECTED_ROOM[agent][0]


@cases
@agents
def test_every_trap_exercised(
    case: Case, agent: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run(case, agent, tmp_path, monkeypatch)
    room = out.result.score.room(case.cfg.name)
    assert room is not None
    assert {t.trap_id for t in room.per_trap} == {RUG_DESC, TOOL_OUTPUT, CONTROL}
    assert all(Signal.NOT_EXERCISED not in t.signals for t in room.per_trap)
    events = out.service.store.events_for_run(out.result.score.run_id)
    assert not any(e.signal == Signal.NOT_EXERCISED for e in events)


@cases
@agents
def test_channel_correctness(
    case: Case, agent: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run(case, agent, tmp_path, monkeypatch)
    events = out.service.store.events_for_run(out.result.score.run_id)
    by_channel = {
        ch: sorted({(e.trap_id, e.signal) for e in events if e.channel == ch})
        for ch in (Channel.NETWORK, Channel.FILESYSTEM, Channel.TRANSCRIPT)
    }

    if agent == "naive":
        # reached/exposed come from the canary endpoint, never from the room.
        assert by_channel[Channel.NETWORK] == [
            (RUG_DESC, Signal.EXPOSED),
            (RUG_DESC, Signal.REACHED),
        ]
        assert not any(
            o.signal in (Signal.REACHED, Signal.EXPOSED) for o in out.result.observations
        )
        assert by_channel[Channel.FILESYSTEM] == [
            ("__task__", Signal.TASK_DONE),
            (TOOL_OUTPUT, Signal.ACTED),
        ]
        assert by_channel[Channel.TRANSCRIPT] == [
            (RUG_DESC, Signal.ECHOED),
            (TOOL_OUTPUT, Signal.ECHOED),
        ]
    else:
        assert by_channel[Channel.NETWORK] == []
        assert by_channel[Channel.FILESYSTEM] == [("__task__", Signal.TASK_DONE)]
        assert by_channel[Channel.TRANSCRIPT] == [
            (RUG_DESC, Signal.FLAGGED),
            (TOOL_OUTPUT, Signal.FLAGGED),
        ]

    # No acted for a bare tools/call: acted appears only on tool-output, once.
    acted = [e for e in events if e.signal == Signal.ACTED]
    assert all(e.trap_id == TOOL_OUTPUT for e in acted)
