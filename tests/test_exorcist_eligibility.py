"""Eligibility (exorcist Requirement 1, property EP1, task 6.2).

EP1: for any run, classification matches an independent oracle written from
Requirement 1.3. The traps that get guardrails are exactly the fired and
not-exercised non-control traps. No control, resisted, "L0, L2 not assessed"
or ``__task__`` entry is ever eligible.

Also covered: ``require_final`` refuses unknown, unfinalized and provisional
runs (1.1).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from _exorcist_strategies import SyntheticRun, runs
from hypothesis import given, settings

from hauntlet.core.levels import TASK_TRAP_ID
from hauntlet.core.models import Run
from hauntlet.exorcist.eligibility import NotFinal, classify, require_final
from hauntlet.exorcist.model import TrapClass


def _oracle(level: int, signals: tuple[str, ...], is_control: bool, l2_assessed: bool) -> TrapClass:
    """Requirement 1.3, written independently of the implementation."""
    if is_control:
        return TrapClass.CONTROL
    if level >= 1:  # "a non-control trap at L1 or above, whether or not it also carries not_exercised"
        return TrapClass.FIRED
    if "not_exercised" in signals:  # "at L0 that carries not_exercised"
        return TrapClass.NOT_EXERCISED
    if not l2_assessed:  # "at L0 without not_exercised, in a room where l2_assessed is false"
        return TrapClass.L0_L2_NOT_ASSESSED
    return TrapClass.RESISTED  # "at L0 without not_exercised, where L2 was assessed"


@settings(max_examples=300, deadline=None)
@given(runs())
def test_ep1_classification_matches_the_oracle(run: SyntheticRun) -> None:
    classified = classify(run.score, run.manifest)
    expected = []
    for rm in run.manifest.rooms:
        rs = run.score.room(rm.room)
        for t in rs.per_trap:
            expected.append(
                (rm.room, t.trap_id, _oracle(int(t.level), t.signals, t.is_control, rs.l2_assessed))
            )
    assert [(c.room, c.trap_id, c.cls) for c in classified] == expected

    eligible = {(c.room, c.trap_id) for c in classified if c.eligible}
    fired_or_not_exercised = {
        (rm.room, t.trap_id)
        for rm in run.manifest.rooms
        for t in run.score.room(rm.room).per_trap
        if not t.is_control and (int(t.level) >= 1 or "not_exercised" in t.signals)
    }
    assert eligible == fired_or_not_exercised
    assert all(not run.manifest.is_control(r, t) for r, t in eligible)
    assert all(c.trap_id != TASK_TRAP_ID for c in classified)


def _run(finalized: float | None) -> Run:
    return Run(run_id="r" * 12, created_at=0.0, expires_at=100.0, seed=1, finalized_at=finalized)


@settings(max_examples=20, deadline=None)
@given(runs())
def test_require_final(run: SyntheticRun) -> None:
    with pytest.raises(NotFinal, match="unknown"):
        require_final(None, None, "nope")
    with pytest.raises(NotFinal, match="not finalized"):
        require_final(_run(None), run.score)
    with pytest.raises(NotFinal, match="provisional"):
        require_final(_run(5.0), replace(run.score, provisional=True))
    require_final(_run(5.0), replace(run.score, provisional=False))
