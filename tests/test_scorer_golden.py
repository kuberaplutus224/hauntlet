"""Golden tests: recorded event lists → expected scores (Requirements 1.3, 1.4, 2, 3)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import load_golden, make_event
from hauntlet.core.levels import Level
from hauntlet.core.scorer import score_run

MANIFEST, CASES = load_golden()


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_golden(case: dict) -> None:
    events = [make_event(MANIFEST, e, ts=i) for i, e in enumerate(case["events"])]
    score = score_run(events, MANIFEST)
    exp = case["expected"]

    assert score.run_id == MANIFEST.run_id
    assert score.overall_worst == Level(exp["overall_worst"])
    assert score.ignored_events == exp["ignored_events"]
    for name, want in exp["rooms"].items():
        got = score.room(name)
        assert got is not None, name
        assert got.worst_level == Level(want["worst_level"]), name
        assert got.detected is want["detected"], name
        assert list(got.false_positives) == want["false_positives"], name
        assert got.task_completed is want["task_completed"], name
        assert got.l2_assessed is True


def test_l2_not_assessed_without_transcript() -> None:
    score = score_run([], replace(MANIFEST, transcript_provided=False))
    assert all(not r.l2_assessed for r in score.rooms)


def test_per_trap_breakdown_lists_every_trap_including_controls() -> None:
    score = score_run([], MANIFEST)
    repo = score.room("repo")
    assert repo is not None
    assert [t.trap_id for t in repo.per_trap] == ["readme", "agents", "ctrl"]
    assert [t.is_control for t in repo.per_trap] == [False, False, True]
