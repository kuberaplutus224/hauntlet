"""Honest path badge (scorecard SP4, builder half; task 9.4).

**Validates: scorecard Requirements 2.3–2.5, SP4**
"""

from __future__ import annotations

import json
from dataclasses import replace

from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings

from hauntlet.exorcist.texts import DEMO_LABEL, REAL_CLIENT_LABEL
from hauntlet.scorecard import copy
from hauntlet.scorecard.build import badge_for, build


def test_each_path_maps_to_its_string() -> None:
    assert badge_for("demo-agent") == copy.C1
    assert badge_for("real-client") == copy.C2
    assert badge_for("reference:naive") == copy.C3.format(name="naive")
    assert badge_for("reference:hardened") == copy.C3.format(name="hardened")
    assert badge_for("not-recorded") == copy.C4
    assert badge_for("reference:") == copy.C4
    assert badge_for("something-else") == copy.C4


def _text(vm) -> str:
    return json.dumps(vm.to_dict(), ensure_ascii=False)


@settings(max_examples=120, deadline=None)
@given(case=scorecard_inputs())
def test_badge_and_forbidden_labels(case) -> None:
    vm = build(case.inp)
    assert vm.badge == badge_for(case.inp.path)
    text = _text(vm)
    if case.inp.path == "demo-agent":
        assert copy.C2 not in text and REAL_CLIENT_LABEL not in text
    if case.inp.path == "real-client":
        assert copy.C1 not in text and DEMO_LABEL not in text
    if case.kind in ("demo", "real", "pending"):
        assert vm.path_label == case.delta["path_label"]


@settings(max_examples=40, deadline=None)
@given(case=scorecard_inputs(kinds=("none",)))
def test_badge_follows_the_caller_not_the_score(case) -> None:
    for path in ("demo-agent", "real-client", "reference:naive", "not-recorded"):
        assert build(replace(case.inp, path=path)).badge == badge_for(path)
