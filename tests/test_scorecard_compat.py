"""Compatibility goldens (scorecard SP17, task 1 and task 17.3).

Captured before any scorecard change, so they record today's behaviour:

- ``render_json`` and ``render_text`` for three fixed deltas (demo path with an
  after run, real-client path, pending);
- the JSON bodies of ``GET /runs/{id}``, ``GET /runs/{id}/score``,
  ``GET /health`` and ``POST /runs/{id}/finalize`` for one fixed run.

The cases are built deterministically (fixed seeds, fixed clock, fixed IDs), so
the files compare byte for byte. To re-capture deliberately, run with
``HAUNTLET_UPDATE_COMPAT=1``; never do that to make a failing test pass.

**Validates: scorecard Requirements 13.1, 13.2, SP17**
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hauntlet.core.levels import Level, Signal
from hauntlet.core.models import RoomScore, RunManifest, RunScore, TrapScore
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.exorcist import report
from hauntlet.exorcist.delta import DEMO, PENDING, REAL, build_delta
from hauntlet.exorcist.generate import generate
from hauntlet.exorcist.mcpfacts import STEERED_CALL_NO_CANARY
from hauntlet.exorcist.texts import DEMO_ENV_NOTE, DEMO_LABEL, PENDING_LABEL, REAL_CLIENT_LABEL
from hauntlet.rooms import default_rooms
from hauntlet.server import create_app

GOLDEN = Path(__file__).parent / "fixtures" / "scorecard_compat"
UPDATE = os.environ.get("HAUNTLET_UPDATE_COMPAT") == "1"

ROOMS = default_rooms()
TRAP_SIGNALS = ("reached", "echoed", "acted", "exposed", "flagged", "not_exercised")


# --------------------------------------------------------------------------- #
# deterministic synthetic runs
# --------------------------------------------------------------------------- #


def _run(seed: int, run_id: str, rooms: tuple[str, ...]) -> tuple[RunScore, RunManifest]:
    rnd = random.Random(seed)
    manifest = RunManifest(run_id=run_id, rooms=tuple(ROOMS[n].manifest() for n in rooms))
    room_scores = []
    for rm in manifest.rooms:
        per_trap = []
        for t in rm.traps:
            level = Level(rnd.randint(0, 4))
            signals = tuple(sorted(rnd.sample(TRAP_SIGNALS, rnd.randint(0, 3))))
            per_trap.append(TrapScore(t.trap_id, t.is_control, level, Signal.FLAGGED in signals, signals))
        controls = [t.trap_id for t in rm.traps if t.is_control]
        fps = tuple(c for c in controls if rnd.random() < 0.5)
        worst = max((t.level for t in per_trap if not t.is_control), default=Level.L0)
        room_scores.append(
            RoomScore(rm.room, worst, rnd.random() < 0.5, fps, tuple(per_trap), rnd.random() < 0.7, rnd.random() < 0.6)
        )
    overall = max((r.worst_level for r in room_scores), default=Level.L0)
    return RunScore(run_id, tuple(room_scores), overall), manifest


def _after(before: RunScore, seed: int, run_id: str) -> RunScore:
    rnd = random.Random(seed)
    rooms = []
    for rs in before.rooms:
        per_trap = []
        for t in rs.per_trap:
            level = Level(rnd.randint(0, 4))
            signals = tuple(sorted(rnd.sample(TRAP_SIGNALS, rnd.randint(0, 2))))
            per_trap.append(replace(t, level=level, signals=signals, detected=Signal.FLAGGED in signals))
        worst = max((t.level for t in per_trap if not t.is_control), default=Level.L0)
        rooms.append(replace(rs, per_trap=tuple(per_trap), worst_level=worst, task_completed=rnd.random() < 0.5))
    overall = max((r.worst_level for r in rooms), default=Level.L0)
    return replace(before, run_id=run_id, rooms=tuple(rooms), overall_worst=overall)


def _trace(manifest: RunManifest, spec, seed: int) -> list:
    """A demo-agent trace: one denied action per trap surface, denied by the items citing it."""
    rnd = random.Random(seed)
    out = []
    for rm in manifest.rooms:
        for t in rm.traps:
            ref = f"{rm.room}/{t.trap_id}"
            deniers = tuple(i.item_id for i in spec.items if ref in i.cites)
            proceeded = not deniers or rnd.random() < 0.3
            out.append(("web_fetch", t.surface, "repo_file", proceeded, () if proceeded else deniers[:2]))
    return out


def _deltas() -> dict[str, object]:
    cases = {}

    b, m = _run(11, "compatDemoBefore", ("cursed-repo", "poltergeist"))
    spec = generate(b, m)
    a = _after(b, 12, "compatDemoAfter1")
    cases["demo"] = build_delta(
        b, m, spec, path=DEMO, path_label=DEMO_LABEL, after=a, after_run_id=a.run_id,
        extras={("poltergeist", "rug-desc"): {STEERED_CALL_NO_CANARY}},
        fact_logs={"poltergeist": True}, denials=tuple(i.item_id for i in spec.items[:3]),
        not_interpreted=("steering/extra.md: sentence not in the grammar",),
        demo_env_note=DEMO_ENV_NOTE, trace=_trace(m, spec, 13),
    )

    b, m = _run(21, "compatRealBefore", ("poltergeist", "parlor"))
    spec = generate(b, m)
    a = _after(b, 22, "compatRealAfter01")
    cases["real"] = build_delta(
        b, m, spec, path=REAL, path_label=REAL_CLIENT_LABEL, after=a, after_run_id=a.run_id,
        fact_logs={"poltergeist": False},
    )

    b, m = _run(31, "compatPendBefore", ("threshold", "cursed-repo-tests"))
    spec = generate(b, m)
    cases["pending"] = build_delta(b, m, spec, path=PENDING, path_label=PENDING_LABEL)
    return cases


# --------------------------------------------------------------------------- #
# deterministic JSON routes
# --------------------------------------------------------------------------- #

CLOCK = 1_700_000_000.0


def _route_bodies() -> dict[str, bytes]:
    service = RangeService(
        Store(":memory:"), default_rooms(), base_url="http://127.0.0.1:8666",
        clock=lambda: CLOCK, run_id_factory=lambda: "compatRoute01", seed_factory=lambda: 0,
    )
    service.start_run(["threshold"], ttl=600)
    c = TestClient(create_app(service))
    out = {}
    out["get_run"] = c.get("/runs/compatRoute01").content
    fin = c.post(
        "/runs/compatRoute01/finalize",
        json={
            "observations": [
                {"room": "threshold", "trap_id": "notes-instruction", "channel": "filesystem",
                 "signal": "acted", "detail": "created SETUP_DONE.txt"},
                {"room": "threshold", "trap_id": "__task__", "channel": "filesystem", "signal": "task_done"},
            ],
            "transcript_provided": False,
        },
    )
    assert fin.status_code == 200
    out["finalize"] = fin.content
    out["score"] = c.get("/runs/compatRoute01/score").content
    health = c.get("/health").json()
    out["health"] = json.dumps(health, sort_keys=True).encode()
    return out


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #


def _check(name: str, data: bytes) -> None:
    path = GOLDEN / name
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    assert path.is_file(), f"missing golden {path} (capture with HAUNTLET_UPDATE_COMPAT=1)"
    assert data == path.read_bytes(), f"{name} differs from the captured golden"


@pytest.mark.parametrize("case", ["demo", "real", "pending"])
def test_delta_json_and_text_unchanged(case: str) -> None:
    delta = _deltas()[case]
    _check(f"delta-{case}.json", report.render_json(delta).encode("utf-8"))
    _check(f"delta-{case}.txt", report.render_text(delta).encode("utf-8"))


def test_json_route_bodies_unchanged() -> None:
    for name, body in _route_bodies().items():
        _check(f"route-{name}.json", body)


def test_cases_are_deterministic() -> None:
    first = {k: report.render_json(v) for k, v in _deltas().items()}
    second = {k: report.render_json(v) for k, v in _deltas().items()}
    assert first == second
    assert _route_bodies() == _route_bodies()


# --------------------------------------------------------------------------- #
# second half (task 17.3): after the D23 switch
# --------------------------------------------------------------------------- #


def test_sample_report_is_a_deterministic_scorecard(tmp_path) -> None:
    from hauntlet.cli import SAMPLE_RUN_ID, main
    from hauntlet.scorecard import copy

    a, b = tmp_path / "a.html", tmp_path / "b.html"
    assert main(["sample-report", "--out", str(a)]) == 0
    assert main(["sample-report", "--out", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()
    html = a.read_text(encoding="utf-8")
    assert f"<code>{SAMPLE_RUN_ID}</code>" in html
    assert copy.C3.format(name="naive") in html and 'class="badge"' in html
