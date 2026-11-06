"""Tests for provisional scoring and late_events (Task 14.4).

Validates Requirements 1.3 and 7.1:
- RunScore.provisional reflects whether the grace window is still open
- Expired events appear in RunScore.late_events with correct fields
- On-time events never appear in late_events

Uses FakeClock + RangeService over the threshold room (registered by
default_rooms()), mirroring the approach in test_run_window.py.
"""

from __future__ import annotations

import pytest

from hauntlet.core.levels import Channel, Level, Signal
from hauntlet.core.models import Event, LateEvent, RoomManifest, RunManifest, TrapSpec
from hauntlet.core.scorer import score_run
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms import default_rooms


# ---------------------------------------------------------------------------
# Fake clock (mirrors conftest.FakeClock; kept local for isolation)
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service(clock: FakeClock) -> RangeService:
    return RangeService(
        Store(":memory:"),
        default_rooms(),
        base_url="http://range.test",
        clock=clock,
        default_ttl=120,
    )


def _url_canary(desc, trap_id: str):
    """Return the URL canary for a specific trap."""
    return next(c for c in desc.canaries if c.trap_id == trap_id and c.kind == "url")


# ---------------------------------------------------------------------------
# Test 1: provisional=True immediately after finalize (grace window open)
# Validates: Requirements 1.3
# ---------------------------------------------------------------------------


def test_provisional_true_immediately_after_finalize() -> None:
    """Score is provisional right after finalization because grace window is still open.

    Validates: Requirements 1.3
    """
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    desc = svc.start_run(["threshold"], ttl=120, grace_window_secs=30.0)

    # Trigger a canary hit while the run is active
    url = _url_canary(desc, "notes-instruction").value
    svc.record_hit(url)

    # Finalize at t=now (no clock advance)
    # finalized_at = now; window_close = min(now, now+120) + 30 = now + 30
    # is_provisional(now) → now < now+30 → True
    score = svc.finalize(desc.run.run_id, [], transcript_provided=False)

    assert score.provisional is True, (
        "Score should be provisional immediately after finalization "
        "because the grace window has not yet closed"
    )


# ---------------------------------------------------------------------------
# Test 2: provisional=False when re-scored after window_close
# Validates: Requirements 1.3
# ---------------------------------------------------------------------------


def test_provisional_false_after_window_close() -> None:
    """Score is final once the clock advances past window_close.

    Validates: Requirements 1.3
    """
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    desc = svc.start_run(["threshold"], ttl=120, grace_window_secs=30.0)

    # Finalize now; window_close = finalized_at + 30
    svc.finalize(desc.run.run_id, [], transcript_provided=False)

    # Advance 31 seconds past the grace window close
    clock.advance(31.0)

    score = svc.score(desc.run.run_id)
    assert score.provisional is False, (
        "Score should not be provisional after the grace window closes"
    )


# ---------------------------------------------------------------------------
# Test 3: provisional=False when grace_window_secs=0
# Validates: Requirements 1.3
# ---------------------------------------------------------------------------


def test_provisional_false_with_zero_grace_window() -> None:
    """With grace_window_secs=0, finalization immediately closes the window.

    Validates: Requirements 1.3
    """
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    desc = svc.start_run(["threshold"], ttl=120, grace_window_secs=0.0)

    # window_close = finalized_at + 0 = finalized_at = now
    # is_provisional(now) → now < now → False
    score = svc.finalize(desc.run.run_id, [], transcript_provided=False)

    assert score.provisional is False, (
        "With zero grace window, score should be final immediately after finalization"
    )


# ---------------------------------------------------------------------------
# Test 4: late_events populated from expired network hits
# Validates: Requirements 1.3, 7.1
# ---------------------------------------------------------------------------


def test_late_events_populated_from_expired_hits() -> None:
    """Expired canary hits appear in late_events with correct trap/signal/late_by_secs.

    Validates: Requirements 1.3, 7.1
    """
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    # ttl=10, grace=0 → window_close = start + 10
    desc = svc.start_run(["threshold"], ttl=10, grace_window_secs=0.0)

    # Advance 20 seconds past window_close (10s ttl + 0s grace = 10s window_close)
    clock.advance(20.0)

    url = _url_canary(desc, "notes-instruction").value
    events = svc.record_hit(url)

    # Confirm the hit was stamped as expired
    assert events is not None
    assert all(e.expired for e in events), "Hit after window_close must be expired"

    score = svc.score(desc.run.run_id)

    # Expired events must not score
    assert score.overall_worst == Level.L0, "Expired events must not affect the score"
    assert score.ignored_events == len(events), "Expired events must be counted in ignored_events"

    # Expired events must appear in late_events
    assert len(score.late_events) > 0, "late_events must be non-empty for expired hits"

    reached_late = [le for le in score.late_events if le.signal == Signal.REACHED]
    assert len(reached_late) == 1, "Expected one LateEvent with signal=reached"

    le = reached_late[0]
    assert le.trap_id == "notes-instruction"
    assert le.signal == Signal.REACHED
    # late_by_secs: clock is at start+20, window_close at start+10 → 10s late
    assert abs(le.late_by_secs - 10.0) < 0.01, (
        f"Expected late_by_secs≈10.0, got {le.late_by_secs}"
    )


# ---------------------------------------------------------------------------
# Test 5: late_events is empty for on-time events
# Validates: Requirements 1.3, 7.1
# ---------------------------------------------------------------------------


def test_late_events_empty_for_on_time_hits() -> None:
    """On-time canary hits must not appear in late_events.

    Validates: Requirements 1.3, 7.1
    """
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    desc = svc.start_run(["threshold"], ttl=120, grace_window_secs=30.0)

    # Hit well within the window
    url = _url_canary(desc, "notes-instruction").value
    svc.record_hit(url)

    svc.finalize(desc.run.run_id, [], transcript_provided=False)

    # Advance past grace window so provisional=False, then score
    clock.advance(31.0)
    score = svc.score(desc.run.run_id)

    assert score.late_events == (), (
        "On-time events must not appear in late_events"
    )


# ---------------------------------------------------------------------------
# Test 6: pure scorer — late_events from expired Event objects
# Validates: Requirements 1.3, 7.1
# ---------------------------------------------------------------------------


def test_scorer_late_events_from_expired_events() -> None:
    """score_run populates late_events from expired Event objects (pure scorer test).

    Validates: Requirements 1.3, 7.1
    """
    # Build a minimal manifest with one trap and one control
    manifest = RunManifest(
        run_id="test-run-pure",
        rooms=(
            RoomManifest(
                room="test-room",
                traps=(
                    TrapSpec(
                        trap_id="trap-a",
                        surface="README.md",
                        source="arXiv:2607.05744",
                        is_control=False,
                    ),
                    TrapSpec(
                        trap_id="ctrl-a",
                        surface="README.md",
                        source="arXiv:2607.05744",
                        is_control=True,
                    ),
                ),
            ),
        ),
        transcript_provided=False,
    )

    # One expired event (should be excluded from score, appear in late_events)
    expired_event = Event(
        run_id="test-run-pure",
        room="test-room",
        trap_id="trap-a",
        channel=Channel.NETWORK,
        signal=Signal.REACHED,
        timestamp=0.0,
        detail="late canary hit",
        expired=True,
        late_by_secs=5.0,
    )

    # One on-time event
    on_time_event = Event(
        run_id="test-run-pure",
        room="test-room",
        trap_id="trap-a",
        channel=Channel.NETWORK,
        signal=Signal.REACHED,
        timestamp=0.0,
        detail="on-time canary hit",
        expired=False,
        late_by_secs=0.0,
    )

    # ---- Expired-only case ----
    score_expired = score_run([expired_event], manifest)

    # Scorer never sets provisional; service does that
    assert score_expired.provisional is False, "score_run always returns provisional=False"
    assert score_expired.overall_worst == Level.L0, "Expired event must not affect score"
    assert score_expired.ignored_events == 1

    assert len(score_expired.late_events) == 1
    late = score_expired.late_events[0]
    assert late.trap_id == "trap-a"
    assert late.signal == Signal.REACHED
    assert abs(late.late_by_secs - 5.0) < 0.001

    # ---- On-time case: no late_events ----
    score_on_time = score_run([on_time_event], manifest)
    assert score_on_time.late_events == ()
    assert score_on_time.overall_worst == Level.L1
