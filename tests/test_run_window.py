"""Tests for the timestamp-derived run window (Task 13.4).

Covers:
- window_close() formula for unfinalized and finalized runs
- expired / late_by_secs stamping on events recorded before and after window_close
"""

from __future__ import annotations

import pytest

from hauntlet.core.models import Run
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms import default_rooms


# ---------------------------------------------------------------------------
# Fake clock (mirrors conftest.FakeClock; defined here for isolation)
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
        default_ttl=60,
    )


def _url_canary(desc, trap_id: str):
    return next(c for c in desc.canaries if c.trap_id == trap_id and c.kind == "url")


# ---------------------------------------------------------------------------
# 1. window_close formula — unfinalized run
# ---------------------------------------------------------------------------

def test_window_close_unfinalized_is_expires_at_plus_grace() -> None:
    """Unfinalized: window_close = expires_at + grace_window_secs."""
    run = Run(
        run_id="r1",
        created_at=1000.0,
        expires_at=1100.0,
        seed=0,
        finalized_at=None,
        grace_window_secs=30.0,
    )
    assert run.window_close() == 1130.0


def test_window_close_unfinalized_custom_grace() -> None:
    run = Run(
        run_id="r2",
        created_at=1000.0,
        expires_at=1200.0,
        seed=0,
        finalized_at=None,
        grace_window_secs=0.0,
    )
    assert run.window_close() == 1200.0


# ---------------------------------------------------------------------------
# 2. window_close formula — finalized before expires_at
# ---------------------------------------------------------------------------

def test_window_close_finalized_before_expiry_uses_finalized_at() -> None:
    """finalized_at < expires_at → window_close = finalized_at + grace."""
    run = Run(
        run_id="r3",
        created_at=1000.0,
        expires_at=1100.0,
        seed=0,
        finalized_at=1050.0,   # finalized early
        grace_window_secs=30.0,
    )
    # min(1050, 1100) + 30 = 1080
    assert run.window_close() == 1080.0


# ---------------------------------------------------------------------------
# 3. window_close formula — finalized after expires_at (min clamp)
# ---------------------------------------------------------------------------

def test_window_close_finalized_after_expiry_clamps_to_expires_at() -> None:
    """finalized_at > expires_at → window_close = expires_at + grace (min wins)."""
    run = Run(
        run_id="r4",
        created_at=1000.0,
        expires_at=1100.0,
        seed=0,
        finalized_at=1200.0,   # finalized after expiry
        grace_window_secs=30.0,
    )
    # min(1200, 1100) + 30 = 1130
    assert run.window_close() == 1130.0


# ---------------------------------------------------------------------------
# 4. Events recorded BEFORE window_close get expired=False, late_by_secs=0
# ---------------------------------------------------------------------------

def test_hit_before_window_close_is_not_expired() -> None:
    """A canary hit that arrives before window_close must not be marked expired."""
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    desc = svc.start_run(["threshold"], ttl=60, grace_window_secs=30.0)

    # window_close = created_at + 60 + 30 = created_at + 90
    # Advance to 1 second before window_close (89 seconds in)
    clock.advance(89.0)

    url = _url_canary(desc, "notes-instruction").value
    events = svc.record_hit(url)
    assert events is not None
    assert all(not e.expired for e in events), "expected expired=False before window_close"
    assert all(e.late_by_secs == 0.0 for e in events), "expected late_by_secs=0 before window_close"


def test_hit_exactly_at_window_open_is_not_expired() -> None:
    """A hit at t=created_at (immediately after start) is well within the window."""
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    desc = svc.start_run(["threshold"], ttl=60, grace_window_secs=30.0)
    # clock has not advanced — hit is at creation time
    url = _url_canary(desc, "notes-instruction").value
    events = svc.record_hit(url)
    assert events is not None
    assert all(not e.expired for e in events)
    assert all(e.late_by_secs == 0.0 for e in events)


# ---------------------------------------------------------------------------
# 5. Events recorded AT or AFTER window_close get expired=True + correct late_by_secs
# ---------------------------------------------------------------------------

def test_hit_at_window_close_is_expired() -> None:
    """A hit at exactly window_close is expired (boundary is inclusive)."""
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    desc = svc.start_run(["threshold"], ttl=60, grace_window_secs=30.0)

    # window_close = start + 60 + 30 = start + 90
    clock.advance(90.0)

    url = _url_canary(desc, "notes-instruction").value
    events = svc.record_hit(url)
    assert events is not None
    assert all(e.expired for e in events), "expected expired=True at window_close"
    assert all(e.late_by_secs == 0.0 for e in events), "exactly at boundary: late_by_secs should be 0"


def test_hit_after_window_close_has_correct_late_by_secs() -> None:
    """A hit 15 seconds after window_close should have late_by_secs=15."""
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    desc = svc.start_run(["threshold"], ttl=60, grace_window_secs=30.0)

    # window_close = start + 90; advance 105s → 15s past window_close
    clock.advance(105.0)

    url = _url_canary(desc, "notes-instruction").value
    events = svc.record_hit(url)
    assert events is not None
    assert all(e.expired for e in events)
    assert all(abs(e.late_by_secs - 15.0) < 0.001 for e in events), (
        f"expected late_by_secs≈15.0, got {[e.late_by_secs for e in events]}"
    )


def test_hit_after_finalize_grace_window_expires() -> None:
    """After finalize + grace window, hits are expired with correct late_by_secs."""
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    desc = svc.start_run(["threshold"], ttl=120, grace_window_secs=10.0)

    # Finalize at t+20 → window_close = min(20, 120) + 10 = 30 seconds after start
    clock.advance(20.0)
    svc.finalize(desc.run.run_id, [], transcript_provided=False)

    # Advance 25 more seconds (total 45s from start; 15s past window_close at t+30)
    clock.advance(25.0)

    url = _url_canary(desc, "notes-instruction").value
    events = svc.record_hit(url)
    assert events is not None
    assert all(e.expired for e in events)
    # window_close was at start+30; current time is start+45 → late by 15s
    assert all(abs(e.late_by_secs - 15.0) < 0.001 for e in events), (
        f"expected late_by_secs≈15.0, got {[e.late_by_secs for e in events]}"
    )


def test_expired_events_are_not_scored() -> None:
    """Expired events are stored but must not contribute to the run score."""
    clock = FakeClock(t=1_000_000.0)
    svc = _service(clock)
    desc = svc.start_run(["threshold"], ttl=10, grace_window_secs=30.0)

    # Advance well past window_close (10 + 30 = 40s)
    clock.advance(50.0)

    url = _url_canary(desc, "notes-instruction").value
    events = svc.record_hit(url)
    assert events is not None and all(e.expired for e in events)

    from hauntlet.core.levels import Level
    score = svc.score(desc.run.run_id)
    assert score.overall_worst == Level.L0
    assert score.ignored_events == len(events)
