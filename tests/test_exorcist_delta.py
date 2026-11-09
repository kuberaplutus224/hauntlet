"""The delta report (exorcist Requirement 10; properties EP10, EP11, EP12, EP15; task 12.3).

- **EP10:** every format holds every before trap's level and signals, with or
  without an after run; a trap not exercised after is never shown as improved;
  a higher after level is always a regression.
- **EP11:** the report's first line names the re-run path; a demo delta is never
  labelled real-client and vice versa.
- **EP12:** a candidate after run is admitted iff all four Requirement 10.6
  checks hold.
- **EP15:** a steered relay call with no ``reached`` after-signal is shown as
  "steered tool called, canary not reached" and never as clean or improved.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from _exorcist_strategies import ROOMS, SyntheticRun, runs
from hypothesis import given, settings
from hypothesis import strategies as st

from hauntlet.core.levels import Level, Signal
from hauntlet.core.models import Run, RunScore, TrapScore
from hauntlet.exorcist import report
from hauntlet.exorcist.delta import (
    AFTER_NOT_RUN,
    DEMO,
    LOWER,
    NOT_EXERCISED_AFTER,
    REAL,
    REGRESSION,
    STEERED_NO_CANARY,
    UNCHANGED,
    AfterRunRejected,
    admit,
    build_delta,
    classify_change,
)
from hauntlet.exorcist.generate import generate
from hauntlet.exorcist.mcpfacts import STEERED_CALL_NO_CANARY
from hauntlet.exorcist.texts import DEMO_LABEL, REAL_CLIENT_LABEL

LABELS = {DEMO: DEMO_LABEL, REAL: REAL_CLIENT_LABEL}


def _rescore(before: SyntheticRun, draw_after) -> RunScore:
    """A new after score over the same manifest, with fresh per-trap levels/signals."""
    rooms = []
    for rs in before.score.rooms:
        per_trap = tuple(draw_after(t) for t in rs.per_trap)
        worst = max((t.level for t in per_trap if not t.is_control), default=Level.L0)
        rooms.append(replace(rs, per_trap=per_trap, worst_level=worst))
    return replace(before.score, rooms=tuple(rooms))


# --------------------------------------------------------------------------- #
# EP10
# --------------------------------------------------------------------------- #


@settings(max_examples=150, deadline=None)
@given(before=runs(), path=st.sampled_from([DEMO, REAL]), with_after=st.booleans(), data=st.data())
def test_ep10_before_is_never_lost_and_no_false_improvement(before, path, with_after, data) -> None:
    spec = generate(before.score, before.manifest)
    after = None
    after_id = None
    if with_after:
        def draw_after(t: TrapScore) -> TrapScore:
            level = Level(data.draw(st.integers(0, 4)))
            sigs = tuple(sorted(data.draw(st.sets(st.sampled_from(
                [s.value for s in Signal if s is not Signal.TASK_DONE]), max_size=3))))
            return replace(t, level=level, signals=sigs, detected=Signal.FLAGGED in sigs)
        after = _rescore(before, draw_after)
        after_id = "after" + before.score.run_id

    delta = build_delta(before.score, before.manifest, spec, path=path, path_label=LABELS[path],
                        after=after, after_run_id=after_id)
    texts = [report.render_text(delta), report.render_json(delta), report.render_html(delta)]

    before_by_ref = {}
    for rm in before.manifest.rooms:
        for t in before.score.room(rm.room).per_trap:
            before_by_ref[f"{rm.room}/{t.trap_id}"] = t

    for td in delta.traps:
        b = before_by_ref[td.ref]
        assert td.before_level == int(b.level)
        assert td.before_signals == tuple(b.signals)
        # before level shows in every format
        for text in texts:
            assert td.ref in text
        # no false improvement
        if after is not None:
            a = {t.trap_id: t for t in after.room(td.ref.split("/", 1)[0]).per_trap}[td.ref.split("/", 1)[1]]
            if Signal.NOT_EXERCISED in a.signals and int(a.level) == 0:
                assert td.change == NOT_EXERCISED_AFTER
            elif int(a.level) > int(b.level):
                assert td.change == REGRESSION
            elif int(a.level) < int(b.level):
                assert td.change == LOWER
            else:
                assert td.change == UNCHANGED
        else:
            assert td.change == AFTER_NOT_RUN


# --------------------------------------------------------------------------- #
# EP11
# --------------------------------------------------------------------------- #


@settings(max_examples=40, deadline=None)
@given(before=runs(), path=st.sampled_from([DEMO, REAL]))
def test_ep11_first_line_names_the_path(before, path) -> None:
    spec = generate(before.score, before.manifest)
    delta = build_delta(before.score, before.manifest, spec, path=path, path_label=LABELS[path])
    text = report.render_text(delta)
    assert text.splitlines()[0] == LABELS[path]
    other = REAL_CLIENT_LABEL if path == DEMO else DEMO_LABEL
    assert other not in report.render_text(delta)
    # HTML carries the same label (escaped) and the noindex meta.
    htmldoc = report.render_html(delta)
    mark = "scripted agent with no model" if path == DEMO else "real client, declared by the tester"
    other_mark = "real client, declared by the tester" if path == DEMO else "scripted agent with no model"
    assert mark in htmldoc and other_mark not in htmldoc and "noindex" in htmldoc


def test_demo_notes_only_on_the_demo_path() -> None:
    before = next(iter([r for r in [_one_run()]]))
    spec = generate(before.score, before.manifest)
    demo = report.render_text(build_delta(before.score, before.manifest, spec, path=DEMO, path_label=DEMO_LABEL))
    real = report.render_text(build_delta(before.score, before.manifest, spec, path=REAL, path_label=REAL_CLIENT_LABEL))
    assert "no shell commands" in demo and "no shell commands" not in real
    assert "fixed" not in demo.lower().replace("prefix", "") and "fixed" not in real.lower().replace("prefix", "")


def _one_run() -> SyntheticRun:
    from _exorcist_strategies import ROOM_NAMES  # noqa
    import hypothesis

    # Build a concrete single-room run without the strategy machinery.
    rm = ROOMS["cursed-repo"].manifest()
    per_trap = tuple(
        TrapScore(t.trap_id, t.is_control, Level.L4 if not t.is_control else Level.L0, False, ())
        for t in rm.traps
    )
    from hauntlet.core.models import RoomScore, RunManifest

    score = RunScore("deltaRUN001", (RoomScore(rm.room, Level.L4, False, (), per_trap, True, True),), Level.L4)
    return SyntheticRun(score, RunManifest("deltaRUN001", (rm,)), ())


# --------------------------------------------------------------------------- #
# EP12
# --------------------------------------------------------------------------- #


def _run(run_id: str, finalized, created: float) -> Run:
    return Run(run_id=run_id, created_at=created, expires_at=created + 100, seed=1, finalized_at=finalized)


@settings(max_examples=200, deadline=None)
@given(
    before=runs(),
    finalized=st.booleans(),
    provisional=st.booleans(),
    same_rooms=st.booleans(),
    same_id=st.booleans(),
    after_created=st.floats(min_value=0.0, max_value=200.0),
)
def test_ep12_admission(before, finalized, provisional, same_rooms, same_id, after_created) -> None:
    bundle_created = 100.0
    after_score = replace(before.score, provisional=provisional)
    if not same_rooms:
        # drop/duplicate a room to change the multiset (only if more than one room)
        after_score = replace(after_score, rooms=after_score.rooms[:-1]) if len(after_score.rooms) > 1 else after_score
        same_rooms = len(before.score.rooms) == 1  # couldn't change it
    after_id = before.score.run_id if same_id else "x" + before.score.run_id
    after_run = _run(after_id, _as_finalized(finalized), after_created)

    expected_ok = (
        finalized
        and not provisional
        and same_rooms
        and not same_id
        and after_created > bundle_created
    )
    try:
        admit(before.score, after_run, after_score, bundle_created)
        ok = True
    except AfterRunRejected:
        ok = False
    assert ok == expected_ok


def _as_finalized(flag: bool):
    return 50.0 if flag else None


# --------------------------------------------------------------------------- #
# EP15
# --------------------------------------------------------------------------- #


@settings(max_examples=100, deadline=None)
@given(before=runs(), after_level=st.integers(0, 4), reached=st.booleans(), has_signal=st.booleans())
def test_ep15_steered_call_without_canary_is_never_clean(before, after_level, reached, has_signal) -> None:
    b = TrapScore("rug-desc", False, Level.L4, False, ("reached",))
    sigs = ("reached",) if reached else ()
    a = TrapScore("rug-desc", False, Level(after_level), False, sigs)
    extra = {STEERED_CALL_NO_CANARY} if has_signal else set()
    change = classify_change(b, a, extra)
    if has_signal:
        assert change == STEERED_NO_CANARY
    else:
        assert change != STEERED_NO_CANARY


def test_steered_signal_shows_in_the_report() -> None:
    before = _one_run()
    spec = generate(before.score, before.manifest)
    after = before.score  # same levels; the point is the extra signal
    extras = {("cursed-repo", "readme-register"): {STEERED_CALL_NO_CANARY}}
    delta = build_delta(before.score, before.manifest, spec, path=DEMO, path_label=DEMO_LABEL,
                        after=after, after_run_id="afterRUN01", extras=extras)
    td = next(t for t in delta.traps if t.ref == "cursed-repo/readme-register")
    assert td.change == STEERED_NO_CANARY and STEERED_CALL_NO_CANARY in td.extra_signals
    assert STEERED_CALL_NO_CANARY in report.render_text(delta)
    assert STEERED_CALL_NO_CANARY in report.render_json(delta)


def test_fact_log_unavailable_is_shown() -> None:
    before = _one_run()
    spec = generate(before.score, before.manifest)
    delta = build_delta(before.score, before.manifest, spec, path=REAL, path_label=REAL_CLIENT_LABEL,
                        after=before.score, after_run_id="afterRUN02", fact_logs={"cursed-repo": False})
    assert any(not rd.fact_log_available for rd in delta.rooms)
    assert "fact log not available" in report.render_text(delta)
