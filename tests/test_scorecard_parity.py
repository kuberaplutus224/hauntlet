"""Parity with the outputs the scorecard replaces (scorecard SP2, task 12.4).

Every datum the core autopsy report shows, and every field value of the delta's
``render_json``, is on the scorecard. Controls are checked for their false-alarm
state, not a level or change word: a control never shows a level (9.3).

**Validates: scorecard Requirements 1.5, 13.6, SP2**
"""

from __future__ import annotations

from _scorecard_html import parse
from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings
from hypothesis import strategies as st

from hauntlet.core.levels import Level, Signal
from hauntlet.core.models import AggregateScore, LateEvent
from hauntlet.exorcist import CLASS_TEXT
from hauntlet.exorcist.model import TrapClass
from hauntlet.scorecard import copy
from hauntlet.scorecard.build import build
from hauntlet.scorecard.render import render

CHANGE_WORD = {
    "lower level observed": copy.LOWER,
    "regression": copy.REGRESSION,
    "unchanged": copy.UNCHANGED,
    "not exercised after": copy.NOT_EXERCISED_AFTER,
    "steered tool called, canary not reached": copy.C15,
}


def _article(doc, room: str, trap: str) -> str:
    return " ".join(
        n.text for n in doc.nodes if n.inside("section", data_room=room) and n.inside("article", data_trap=trap)
    )


def _panel(doc, room: str) -> str:
    return " ".join(n.text for n in doc.nodes if n.inside("section", data_room=room))


@settings(max_examples=60, deadline=None)
@given(case=scorecard_inputs(), agent=st.sampled_from(["", "naive", "real MCP client"]))
def test_sp2_core_report_data_is_present(case, agent) -> None:
    from dataclasses import replace

    inp = replace(case.inp, agent_name=agent)
    doc = parse(render(build(inp)))
    text = doc.text()
    score, manifest = case.before.score, case.before.manifest
    assert score.run_id in text
    if agent:
        assert agent in text
    for rs in score.rooms:
        rm = manifest.room(rs.room)
        panel = _panel(doc, rs.room)
        assert (copy.ROOM_TASK_DONE if rs.task_completed else copy.ROOM_TASK_NOT_DONE) in panel
        if rs.detected:
            assert copy.ROOM_DETECTED in panel
        elif not rs.l2_assessed:
            assert copy.ROOM_DETECTED_NA in panel
        else:
            assert copy.ROOM_NOT_DETECTED in panel
        if rs.false_positives:
            assert copy.ROOM_FALSE_ALARMS.format(ids=", ".join(rs.false_positives)) in panel
        if not rs.l2_assessed:
            assert copy.L2_NOT_ASSESSED in panel
        for t in rs.per_trap:
            spec = rm.trap(t.trap_id)
            art = _article(doc, rs.room, t.trap_id)
            assert t.trap_id in art and spec.surface in art and spec.source in art
            for sig in t.signals:
                assert sig in art
            if t.is_control:
                expected = copy.FALSE_ALARM if t.trap_id in rs.false_positives else copy.NO_FALSE_ALARM
                assert expected in art
            elif case.state != "active" and not (Signal.NOT_EXERCISED in t.signals and t.level == 0):
                assert f"{t.level.name} {t.level.label}" in art
    if case.state == "provisional":
        assert "Provisional" in text


def test_sp2_aggregates_late_and_ignored() -> None:
    from dataclasses import replace

    from _scorecard_strategies import CREATED, REGISTERED
    from _exorcist_strategies import runs
    from hypothesis import find

    run = find(runs(), lambda r: True)
    from hauntlet.core.models import Run
    from hauntlet.scorecard.inputs import RunInput, ScorecardInput

    score = replace(run.score, ignored_events=3, late_events=(LateEvent("t1", "reached", 4.25),))
    agg = AggregateScore("threshold", 4, None, 0.5, 0.25, 1.0, ((1, 0.5), (4, 0.0)), "w", Level.L4, (0, 0, 0, 0, 4), 2)
    inp = ScorecardInput(
        "reference:naive", RunInput(Run(run.score.run_id, CREATED, CREATED + 900, 0, finalized_at=CREATED + 10), score, run.manifest),
        REGISTERED, CREATED + 500, aggregates=(agg,),
    )
    text = parse(render(build(inp))).text()
    for s in ("threshold", "L4 Exposed", "50%", "25%", "100%", copy.AGG_CLEAN_NA, "pass^1 0.50", "pass^4 0.00",
              copy.AGG_NOTE, "threshold 2 of 4", "t1", "4.2 s after grace window closed", copy.IGNORED.format(n=3)):
        assert s in text, s


@settings(max_examples=60, deadline=None)
@given(case=scorecard_inputs(kinds=("pending", "demo", "real"), states=("final",)))
def test_sp2_every_delta_field_is_present(case) -> None:
    doc = parse(render(build(case.inp)))
    text = doc.text()
    d = case.delta
    assert d["path_label"] in text and d["before_run_id"] in text
    if d["after_run_id"]:
        assert d["after_run_id"] in text
    for rd in d["rooms"]:
        panel = _panel(doc, rd["room"])
        for cost in rd["costs"]:
            assert cost in panel
        if not rd["fact_log_available"]:
            assert copy.FACT_LOG_NA.format(room=rd["room"]) in text
        if rd["after"] is not None:
            a = rd["after"]
            assert (copy.ROOM_TASK_DONE if a["task_completed"] else copy.ROOM_TASK_NOT_DONE) in panel
            if a["false_positives"]:
                assert copy.ROOM_FALSE_ALARMS.format(ids=", ".join(a["false_positives"])) in panel
    controls = {f"{rm.room}/{t.trap_id}" for rm in case.before.manifest.rooms for t in rm.traps if t.is_control}
    for td in d["traps"]:
        room, trap = td["ref"].split("/", 1)
        art = _article(doc, room, trap)
        assert trap in art
        for sig in list(td["before_signals"]) + list(td["after_signals"]) + list(td["extra_signals"]):
            assert sig in art, sig
        assert CLASS_TEXT[TrapClass(td["cls"])] in art
        for item in td["cites"]:
            assert item in art
        for item in td["changed_by_display"] or ():
            assert item in art
        if td["after_level"] is not None and td["ref"] not in controls:
            assert CHANGE_WORD[td["change"]] in art
            if td["change"] not in ("not exercised after", "steered tool called, canary not reached"):
                lv = Level(td["after_level"])
                assert f"{lv.name} {lv.label}" in art
    for x in d["attributions"] + d["not_interpreted"] + d["demo_notes"]:
        assert x in text
    if d["demo_env_note"]:
        assert d["demo_env_note"] in text
    for c in d["cannot_fix"]:
        assert c["title"] in text and c["text"] in text
    for k, v in d["assumptions"].items():
        assert v in text
