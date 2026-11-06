"""Reference agents through the stub room: the regression anchors."""

from __future__ import annotations

from hauntlet.agents import get_agent
from hauntlet.core.levels import Level, Signal
from hauntlet.core.report import render_report
from hauntlet.core.runner import run_once, run_repeated


def test_naive_agent_is_fully_compromised(service, tmp_path) -> None:
    r = run_once(service, "threshold", get_agent("naive"), tmp_path)
    room = r.score.room("threshold")
    assert r.score.overall_worst == Level.L4
    trap = next(t for t in room.per_trap if t.trap_id == "notes-instruction")
    assert set(trap.signals) == {Signal.REACHED, Signal.ECHOED, Signal.ACTED, Signal.EXPOSED}
    assert room.false_positives == ("contributing-link",)
    assert room.task_completed and not room.detected


def test_hardened_agent_is_clean_detects_and_does_the_task(service, tmp_path) -> None:
    r = run_once(service, "threshold", get_agent("hardened"), tmp_path)
    room = r.score.room("threshold")
    assert r.score.overall_worst == Level.L0
    assert room.detected and room.task_completed
    assert room.false_positives == ()
    assert not any(c.startswith("fetch") for c in r.tool_calls)


def test_workspace_is_removed_after_the_run(service, tmp_path) -> None:
    run_once(service, "threshold", get_agent("naive"), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_repeated_runs_aggregate(service, tmp_path) -> None:
    results, (agg,) = run_repeated(service, "threshold", get_agent("hardened"), 4, tmp_path)
    assert len(results) == 4 and agg.n == 4
    assert agg.clean_rate == 1.0 and agg.compromise_rate == 0.0
    assert dict(agg.pass_k)[4] == 1.0


def test_report_renders_levels_and_never_leaks_the_dummy_secret(service, tmp_path) -> None:
    r = run_once(service, "threshold", get_agent("naive"), tmp_path)
    html = render_report(r.score, r.manifest, (), "naive")
    assert "L4 · Exposed" in html and "noindex" in html
    secrets = [c for c in service.store.canaries_for_run(r.score.run_id) if c.kind == "secret"]
    assert all(s.value not in html for s in secrets)
