"""Changed by is causal only (scorecard SP9, task 9.3).

**Validates: scorecard Requirements 6.7, SP9**
"""

from __future__ import annotations

from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings

from hauntlet.scorecard import copy
from hauntlet.scorecard.build import build

A4 = " (depends on A4)"


def _needs_a4(item_id: str) -> bool:
    return "credential-egress" in item_id or item_id.endswith("#SECRETS")


@settings(max_examples=150, deadline=None)
@given(case=scorecard_inputs(kinds=("demo",), states=("final",)))
def test_demo_chips_are_changed_by_display(case) -> None:
    vm = build(case.inp)
    td = {t["ref"]: t for t in case.delta["traps"]}
    for _, cards in vm.traps:
        for t in cards:
            d = td[t.ref]
            assert t.changed_by_note == copy.C17
            assert t.changed_by == tuple(d["changed_by_display"])
            bare = {c.removesuffix(A4) for c in t.changed_by}
            assert bare <= set(d["changed_by"]), "only items that denied an action appear"
            for c in t.changed_by:
                assert c.endswith(A4) == _needs_a4(c.removesuffix(A4))
            only_cited = set(d["cites"]) - set(d["changed_by"])
            assert not bare & only_cited


@settings(max_examples=60, deadline=None)
@given(case=scorecard_inputs(kinds=("real",), states=("final",)))
def test_real_client_shows_not_observable(case) -> None:
    vm = build(case.inp)
    for _, cards in vm.traps:
        for t in cards:
            assert t.changed_by is None and t.changed_by_note == copy.C18


@settings(max_examples=40, deadline=None)
@given(case=scorecard_inputs(kinds=("none", "pending")))
def test_no_changed_by_without_an_after_run(case) -> None:
    vm = build(case.inp)
    for _, cards in vm.traps:
        for t in cards:
            assert t.changed_by is None and t.changed_by_note is None
