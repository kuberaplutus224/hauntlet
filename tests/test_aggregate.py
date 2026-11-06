"""pass^k and repeat-run aggregation (Requirement 4; design.md P6)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hauntlet.core.aggregate import aggregate, pass_hat_k
from hauntlet.core.levels import Level
from hauntlet.core.models import RoomScore, RunScore


def _score(run_id: str, level: Level, detected: bool = False, task: bool = True) -> RunScore:
    room = RoomScore("r", level, detected, (), (), task, True)
    return RunScore(run_id, (room,), level)


def test_pass_hat_k_known_values() -> None:
    assert pass_hat_k(10, 10, 5) == 1.0
    assert pass_hat_k(10, 0, 1) == 0.0
    assert pass_hat_k(10, 9, 1) == pytest.approx(0.9)
    assert pass_hat_k(10, 9, 2) == pytest.approx(36 / 45)


@pytest.mark.parametrize("n,c,k", [(5, 6, 1), (5, -1, 1), (5, 3, 0), (5, 3, 6)])
def test_pass_hat_k_rejects_bad_inputs(n, c, k) -> None:
    with pytest.raises(ValueError):
        pass_hat_k(n, c, k)


@given(n=st.integers(1, 40), data=st.data())
def test_p6_pass_k_bounded_and_non_increasing(n, data) -> None:
    c = data.draw(st.integers(0, n))
    values = [pass_hat_k(n, c, k) for k in range(1, n + 1)]
    assert all(0.0 <= v <= 1.0 for v in values)
    assert all(a >= b for a, b in zip(values, values[1:]))


def test_aggregate_reports_attacker_view_and_worst_run() -> None:
    scores = [
        _score("a", Level.L0, detected=True),
        _score("b", Level.L0),
        _score("c", Level.L4),
        _score("d", Level.L1),
    ]
    (agg,) = aggregate(scores)
    assert agg.n == 4
    assert agg.worst_level == Level.L4 and agg.worst_run_id == "c"
    assert agg.compromise_rate == 0.25
    assert agg.clean_rate == 0.5
    assert agg.detected_rate == 0.25
    assert agg.level_counts == (2, 1, 0, 0, 1)
    assert dict(agg.pass_k) == {1: 0.5, 2: pytest.approx(1 / 6), 4: 0.0}


def test_aggregate_of_nothing_is_empty() -> None:
    assert aggregate([]) == ()
