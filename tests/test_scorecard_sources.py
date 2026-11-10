"""Scorecard inputs from the store and the filesystem (scorecard task 11.2).

- the live fact-log path is the one ``hauntlet mcp serve`` / ``parlor open`` use;
- hostile run IDs and symlinked logs give a 404 or "fact log not available", and
  nothing outside the scratch root is opened;
- with two attached after runs, the one created later is shown;
- a corrupt ``bundle.json`` or delta gives the C27 state, never an exception.

**Validates: scorecard Requirements 8.9, design "Fact-log path"**
"""

from __future__ import annotations

import builtins
import io
import json
from pathlib import Path

import pytest

from hauntlet.agents import get_agent
from hauntlet.cli import mcp_workspace
from hauntlet.core.runner import run_once
from hauntlet.core.service import RangeService, UnknownRun
from hauntlet.core.store import Store
from hauntlet.exorcist.mcpfacts import demo_facts_path
from hauntlet.exorcist.service import ExorcistService
from hauntlet.paths import scratch_root_beside
from hauntlet.rooms import default_rooms
from hauntlet.rooms.parlor import factlog as pfl
from hauntlet.rooms.poltergeist import factlog as mfl
from hauntlet.scorecard import copy, render_exorcism
from hauntlet.scorecard.sources import live_fact_log, load_run


class Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def db(tmp_path) -> Path:
    return tmp_path / "range" / "range.db"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def svc(db, clock) -> RangeService:
    return RangeService(Store(db), default_rooms(), clock=clock)


def _write_mcp_log(path: Path, run_id: str, room: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mfl.append(path, mfl.CallFact(1_700_000_001.0, run_id, room, tool="list_topics", args={}, live={"get_note": "pre", "check_health": "pre"}))


@pytest.mark.parametrize("room", ["poltergeist", "poltergeist-legacy"])
def test_live_path_matches_the_mcp_workspace(svc, db, room) -> None:
    run_id = svc.start_run([room]).run.run_id
    expected = demo_facts_path(scratch_root_beside(db), room, run_id)
    assert expected == mfl.facts_path(mcp_workspace(scratch_root_beside(db), room, run_id))
    assert live_fact_log(db, run_id, room) is None  # nothing there yet
    _write_mcp_log(expected, run_id, room)
    assert live_fact_log(db, run_id, room) == expected
    ri = load_run(svc, run_id, db_path=db)
    assert ri.fact_logs == {room: True}
    assert any(f.source == "mcp" and f.kind == "call" for f in ri.facts)


def test_live_path_for_parlor(svc, db) -> None:
    run_id = svc.start_run(["parlor"]).run.run_id
    path = pfl.facts_path(mcp_workspace(scratch_root_beside(db), "parlor", run_id))
    path.parent.mkdir(parents=True)
    pfl.append(path, pfl.PageFact(1_700_000_002.0, run_id, "parlor", page_id="start"))
    assert live_fact_log(db, run_id, "parlor") == path
    assert load_run(svc, run_id, db_path=db).fact_logs == {"parlor": True}


def test_rooms_without_a_log_are_not_listed(svc, db) -> None:
    run_id = svc.start_run(["threshold", "poltergeist"]).run.run_id
    assert load_run(svc, run_id, db_path=db).fact_logs == {"poltergeist": False}
    assert live_fact_log(db, run_id, "threshold") is None


@pytest.mark.parametrize(
    "bad", ["..", "../../etc", "%2F..%2Fx", "/etc/passwd", "a" * 65, "short", "x/../../y", "", "wellFormedButUnknown"]
)
def test_hostile_or_unknown_ids_are_404(svc, db, bad) -> None:
    with pytest.raises(UnknownRun):
        load_run(svc, bad, db_path=db)


def test_symlinked_log_is_not_read_and_nothing_outside_scratch_is_opened(svc, db, tmp_path, monkeypatch) -> None:
    run_id = svc.start_run(["poltergeist"]).run.run_id
    outside = tmp_path / "outside" / "secret.jsonl"
    _write_mcp_log(outside, run_id, "poltergeist")
    target = demo_facts_path(scratch_root_beside(db), "poltergeist", run_id)
    target.parent.mkdir(parents=True)
    target.symlink_to(outside)

    opened: list[str] = []
    real_open, real_io_open = builtins.open, io.open

    def spy(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    def spy_io(file, *a, **k):
        opened.append(str(file))
        return real_io_open(file, *a, **k)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy_io)
    ri = load_run(svc, run_id, db_path=db)
    monkeypatch.undo()
    assert ri.fact_logs == {"poltergeist": False}
    assert not any("outside" in p for p in opened), opened

    # A workspace directory that is itself a symlink out of the scratch root.
    run2 = svc.start_run(["poltergeist"]).run.run_id
    ws = mcp_workspace(scratch_root_beside(db), "poltergeist", run2)
    _write_mcp_log(mfl.facts_path(tmp_path / "elsewhere"), run2, "poltergeist")
    ws.symlink_to(tmp_path / "elsewhere")
    assert live_fact_log(db, run2, "poltergeist") is None


def _finalize(svc: RangeService, run_id: str) -> None:
    svc.finalize(run_id, [], transcript_provided=False)


def test_latest_after_run_is_shown(svc, db, clock, tmp_path) -> None:
    before = svc.start_run(["poltergeist"], grace_window_secs=0).run.run_id
    _finalize(svc, before)
    clock.now += 10
    ex = ExorcistService(svc, tmp_path / "ex", clock=clock)
    _bid, bundle_dir = ex.generate_bundle(before)
    after_ids = []
    for _ in range(2):
        clock.now += 10
        a = svc.start_run(["poltergeist"], grace_window_secs=0).run.run_id
        _finalize(svc, a)
        clock.now += 1
        ex.attach_to_bundle(bundle_dir, a)
        after_ids.append(a)
    html = render_exorcism(ex, bundle_dir)
    assert after_ids[1] in html
    assert after_ids[0] not in html
    # Asking for one after run explicitly shows that one.
    assert after_ids[0] in render_exorcism(ex, bundle_dir, after_run_id=after_ids[0])


def test_corrupt_bundle_or_delta_gives_c27(svc, db, clock, tmp_path) -> None:
    ex = ExorcistService(svc, tmp_path / "ex", clock=clock)
    r = run_once(svc, "threshold", get_agent("naive"), tmp_path / "s")
    clock.now += 60
    _bid, bundle_dir = ex.generate_bundle(r.score.run_id)

    clock.now += 10
    a = svc.start_run(["threshold"], grace_window_secs=0).run.run_id
    _finalize(svc, a)
    clock.now += 1
    ex.attach_to_bundle(bundle_dir, a)
    (bundle_dir / "deltas" / f"{a}.json").write_text("{not json", encoding="utf-8")
    html = render_exorcism(ex, bundle_dir)
    assert copy.C27 in html and r.score.run_id in html

    (bundle_dir / "bundle.json").write_text("[]", encoding="utf-8")
    html = render_exorcism(ex, bundle_dir)
    assert copy.C27 in html and r.score.run_id in html
    json.loads((bundle_dir / "bundle.json").read_text())  # still the corrupt file; nothing rewritten
