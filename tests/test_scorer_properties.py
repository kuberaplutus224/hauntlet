"""Property-based tests for the pure scorer (design.md P1–P5).

These are the correctness properties Kiro's spec Correctness (PBT) checks
should also hold the scorer to.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import load_golden
from hauntlet.core.levels import KNOWN_SIGNALS, TASK_TRAP_ID, Channel, Level, Signal
from hauntlet.core.models import Event, RunManifest
from hauntlet.core.scorer import score_run

MANIFEST, _ = load_golden()

_TRAPS = [(r.room, t.trap_id) for r in MANIFEST.rooms for t in r.traps]
_CONTROLS = {(r.room, t.trap_id) for r in MANIFEST.rooms for t in r.traps if t.is_control}
_SIGNALS = sorted(KNOWN_SIGNALS - {Signal.TASK_DONE})


@st.composite
def events(draw, run_id: str = MANIFEST.run_id, traps=_TRAPS) -> Event:
    task = draw(st.booleans()) and draw(st.integers(0, 9)) == 0
    if task:
        room = draw(st.sampled_from([r.room for r in MANIFEST.rooms]))
        return Event(run_id, room, TASK_TRAP_ID, Channel.FILESYSTEM, Signal.TASK_DONE, 0.0)
    room, trap = draw(st.sampled_from(traps))
    expired = draw(st.booleans())
    late_by_secs = draw(st.floats(0.0, 120.0, allow_nan=False)) if expired else 0.0
    return Event(
        run_id=run_id,
        room=room,
        trap_id=trap,
        channel=draw(st.sampled_from([c.value for c in Channel])),
        signal=draw(st.sampled_from(_SIGNALS)),
        timestamp=draw(st.floats(0, 1e6, allow_nan=False)),
        expired=expired,
        late_by_secs=late_by_secs,
    )


event_lists = st.lists(events(), max_size=30)


def _levels(manifest: RunManifest, evs) -> dict[str, Level]:
    return {r.room: r.worst_level for r in score_run(evs, manifest).rooms}


@settings(max_examples=300)
@given(base=event_lists, extra=event_lists)
def test_p1_monotonic_adding_events_never_lowers_a_level(base, extra) -> None:
    before = _levels(MANIFEST, base)
    after = _levels(MANIFEST, base + extra)
    assert all(after[room] >= before[room] for room in before)


@settings(max_examples=300)
@given(base=event_lists, extra=st.lists(events(traps=sorted(_CONTROLS)), max_size=20))
def test_p2_control_events_never_change_a_level(base, extra) -> None:
    assert _levels(MANIFEST, base) == _levels(MANIFEST, base + extra)


@settings(max_examples=300)
@given(evs=event_lists, data=st.data())
def test_p3_order_invariance(evs, data) -> None:
    shuffled = data.draw(st.permutations(evs))
    assert score_run(evs, MANIFEST) == score_run(shuffled, MANIFEST)


@settings(max_examples=300)
@given(base=event_lists, foreign=st.lists(events(run_id="other-run"), max_size=20), stale=event_lists)
def test_p4_foreign_and_expired_events_never_change_the_score(base, foreign, stale) -> None:
    expired = [Event(**{**e.__dict__, "expired": True}) for e in stale]
    a = score_run(base, MANIFEST)
    b = score_run(base + foreign + expired, MANIFEST)
    assert a.rooms == b.rooms
    assert a.overall_worst == b.overall_worst
    assert b.ignored_events == a.ignored_events + len(foreign) + len(expired)


@settings(max_examples=300)
@given(evs=event_lists)
def test_p5_room_level_is_max_of_non_control_traps(evs) -> None:
    score = score_run(evs, MANIFEST)
    for room in score.rooms:
        real = [t.level for t in room.per_trap if not t.is_control]
        assert room.worst_level == max(real, default=Level.L0)
    assert score.overall_worst == max(r.worst_level for r in score.rooms)
