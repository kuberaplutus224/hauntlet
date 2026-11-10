"""Honesty states in the view model (scorecard SP5–SP8, task 9.2).

- **SP5** hero rules: an active run never shows a level; an L0 run with a trap
  that never reached the agent is "Not fully exercised", never L0 Clean;
- **SP6** the before result is never lost: every before-side value is the same
  with and without an exorcism;
- **SP7** grey stays grey: green (``l0``) only on an L0 level state; controls
  never get a level; "not exercised after" and C15 are never green;
- **SP8** regressions are marked and costs are listed as costs.

**Validates: scorecard Requirements 3.1–3.4, 5.2, 5.3, 9.1–9.6, SP5–SP8**
"""

from __future__ import annotations

from dataclasses import replace

from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings

from hauntlet.core.levels import Signal
from hauntlet.exorcist.delta import NOT_EXERCISED_AFTER, REGRESSION, STEERED_NO_CANARY
from hauntlet.scorecard import copy
from hauntlet.scorecard.build import build
from hauntlet.scorecard.model import State


def _states(vm):
    yield vm.hero.change.before
    if vm.hero.change.after:
        yield vm.hero.change.after
    for c in vm.rooms:
        if c.change:
            yield c.change.before
            if c.change.after:
                yield c.change.after
    for _, cards in vm.traps:
        for t in cards:
            yield t.change.before
            if t.change.after:
                yield t.change.after
    yield from vm.legend


@settings(max_examples=150, deadline=None)
@given(case=scorecard_inputs())
def test_sp5_hero_rules(case) -> None:
    vm = build(case.inp)
    hero = vm.hero
    score = case.before.score
    non_control = [t for rs in score.rooms for t in rs.per_trap if not t.is_control]
    worst = max((int(t.level) for t in non_control), default=0)
    k = sum(1 for t in non_control if Signal.NOT_EXERCISED in t.signals)
    chip = hero.change.before
    if case.state == "active":
        assert chip.label == copy.IN_PROGRESS and chip.level is None
        assert hero.sentence_before == copy.C19
        assert all(c.change is None or c.change.before.level is None for c in vm.rooms)
    elif worst >= 1:
        assert chip.kind == "level" and chip.level == worst
        assert hero.sentence_before.endswith(copy.HERO_PHRASES[worst] + ".")
    elif k:
        assert chip.label == copy.NOT_FULLY_EXERCISED and chip.level is None
        assert hero.sentence_before == copy.C21.format(k=k, n=len(non_control))
    else:
        assert chip.label == "L0 Clean"
    assert (hero.provisional_note is not None) == (case.state == "provisional")
    assert "fixed" not in (hero.sentence_after or "").lower()


@settings(max_examples=120, deadline=None)
@given(case=scorecard_inputs(kinds=("pending", "demo", "real"), states=("final",)))
def test_sp6_before_values_never_change(case) -> None:
    with_ex = build(case.inp)
    without = build(replace(case.inp, exorcism=None))
    assert with_ex.hero.change.before == without.hero.change.before
    assert with_ex.hero.sentence_before == without.hero.sentence_before
    assert [p.before for p in with_ex.hero.pills] == [p.before for p in without.hero.pills]
    for a, b in zip(with_ex.rooms, without.rooms):
        assert (a.change and a.change.before) == (b.change and b.change.before)
        assert a.summary_before == b.summary_before and a.details_before == b.details_before
    for (_, ca), (_, cb) in zip(with_ex.traps, without.traps):
        for a, b in zip(ca, cb):
            assert a.change.before == b.change.before
            assert a.did_before == b.did_before and a.signals_before == b.signals_before


@settings(max_examples=150, deadline=None)
@given(case=scorecard_inputs())
def test_sp7_grey_stays_grey(case) -> None:
    vm = build(case.inp)
    for s in _states(vm):
        assert isinstance(s, State)
        if s.token == "l0":
            assert s.kind == "level" and s.level == 0
        if s.kind != "level":
            assert s.level is None and s.token in ("muted", "info")
    for c in vm.rooms:
        if not c.run:
            assert c.change is None
    td = {t["ref"]: t for t in (case.delta or {}).get("traps", ())}
    src = {f"{rs.room}/{t.trap_id}": t for rs in case.before.score.rooms for t in rs.per_trap}
    for _, cards in vm.traps:
        for t in cards:
            if t.is_control:
                assert t.change.before.kind == "control"
                assert t.change.after is None or t.change.after.kind == "control"
                continue
            s = src[t.ref]
            if Signal.NOT_EXERCISED in s.signals and int(s.level) == 0:
                assert t.change.before.kind == "grey" and t.change.before.label == copy.NOT_EXERCISED
            else:
                assert t.change.before.kind == "level" and t.change.before.level == int(s.level)
            d = td.get(t.ref)
            if case.kind in ("demo", "real") and d is not None:
                if d["change"] == NOT_EXERCISED_AFTER:
                    assert t.change.after.kind == "grey" and t.change.marker == copy.NOT_EXERCISED_AFTER
                if d["change"] == STEERED_NO_CANARY:
                    assert t.change.after.kind == "info" and t.change.after.label == copy.C15
                    assert t.change.marker == copy.C15


@settings(max_examples=150, deadline=None)
@given(case=scorecard_inputs(kinds=("demo", "real"), states=("final",)))
def test_sp8_regressions_and_costs(case) -> None:
    vm = build(case.inp)
    td = {t["ref"]: t for t in case.delta["traps"]}
    for _, cards in vm.traps:
        for t in cards:
            if not t.is_control and td[t.ref]["change"] == REGRESSION:
                assert t.change.marker == copy.REGRESSION
            if t.change.marker == copy.REGRESSION:
                assert td[t.ref]["change"] == REGRESSION
    rd = {r["room"]: r for r in case.delta["rooms"]}
    task_cost = fp_cost = False
    for c in vm.rooms:
        if c.run:
            assert c.costs == tuple(rd[c.room]["costs"])
            task_cost |= any("task" in x for x in c.costs)
            fp_cost |= any("false positive" in x for x in c.costs)
    pills = {p.name: p for p in vm.hero.pills}
    assert pills["task"].cost == task_cost
    assert pills["false_alarms"].cost == fp_cost
    assert pills["detected"].cost is False
