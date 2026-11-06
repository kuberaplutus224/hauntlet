"""Report rendering: provisional banner, late-arrivals section, Detected tags.

Covers the behaviour added in tasks 16.1–16.3 (Requirements 1.3, 2.7, 7.1).
"""

from __future__ import annotations

from hauntlet.core.levels import Level
from hauntlet.core.models import (
    LateEvent,
    RoomManifest,
    RoomScore,
    RunManifest,
    RunScore,
    TrapScore,
    TrapSpec,
)
from hauntlet.core.report import render_report

ROOM = "repo"
TRAP_ID = "readme"
CTRL_ID = "ctrl"

PROVISIONAL_BANNER = "Score provisional — grace window still open"
LATE_HEADING = "Late arrivals (not scored)"


def _manifest() -> RunManifest:
    return RunManifest(
        run_id="run-test",
        transcript_provided=True,
        rooms=(
            RoomManifest(
                room=ROOM,
                traps=(
                    TrapSpec(trap_id=TRAP_ID, surface="README.md", source="RepoGuardBench"),
                    TrapSpec(trap_id=CTRL_ID, surface="README.md", source="benign", is_control=True),
                ),
            ),
        ),
    )


def _room_score(*, detected: bool, l2_assessed: bool) -> RoomScore:
    return RoomScore(
        room=ROOM,
        worst_level=Level.L0,
        detected=detected,
        false_positives=(),
        per_trap=(
            TrapScore(trap_id=TRAP_ID, is_control=False, level=Level.L0, detected=detected, signals=()),
            TrapScore(trap_id=CTRL_ID, is_control=True, level=Level.L0, detected=False, signals=()),
        ),
        task_completed=True,
        l2_assessed=l2_assessed,
    )


def _run_score(
    *,
    provisional: bool = False,
    late_events: tuple[LateEvent, ...] = (),
    detected: bool = False,
    l2_assessed: bool = True,
) -> RunScore:
    return RunScore(
        run_id="run-test",
        rooms=(_room_score(detected=detected, l2_assessed=l2_assessed),),
        overall_worst=Level.L0,
        provisional=provisional,
        late_events=late_events,
    )


def _render(score: RunScore) -> str:
    return render_report(score, _manifest())


# --------------------------------------------------------------------------- #
# Provisional banner
# --------------------------------------------------------------------------- #


def test_provisional_banner_present_when_provisional() -> None:
    html = _render(_run_score(provisional=True))
    assert PROVISIONAL_BANNER in html


def test_provisional_banner_absent_when_final() -> None:
    html = _render(_run_score(provisional=False))
    assert PROVISIONAL_BANNER not in html


# --------------------------------------------------------------------------- #
# Late arrivals section
# --------------------------------------------------------------------------- #


def test_late_arrivals_section_absent_when_empty() -> None:
    html = _render(_run_score(late_events=()))
    assert LATE_HEADING not in html


def test_late_arrivals_section_lists_entries() -> None:
    late = (
        LateEvent(trap_id=TRAP_ID, signal="reached", late_by_secs=12.34),
        LateEvent(trap_id="agents", signal="echoed", late_by_secs=0.05),
    )
    html = _render(_run_score(late_events=late))

    assert LATE_HEADING in html
    # Each entry renders as a late table row: trap_id and signal in cells.
    assert "<td><b>readme</b></td><td>reached</td>" in html
    assert "<td><b>agents</b></td><td>echoed</td>" in html
    # late_by_secs formatted to one decimal place.
    assert "12.3 s after grace window closed" in html
    assert "0.1 s after grace window closed" in html


# --------------------------------------------------------------------------- #
# Detected tag cases
# --------------------------------------------------------------------------- #


def test_detected_tag_detected_true() -> None:
    html = _render(_run_score(detected=True, l2_assessed=False))
    assert "detected the attempt" in html


def test_detected_true_partial_transcript_has_no_not_assessed_contradiction() -> None:
    # A detected attempt with no full transcript must not also claim the detection
    # was "not assessed" — the two tags would contradict each other.
    html = _render(_run_score(detected=True, l2_assessed=False))
    assert "detected the attempt" in html
    assert "Detected not assessed" not in html
    assert "Detected: not assessed" not in html


def test_detected_tag_not_assessed() -> None:
    html = _render(_run_score(detected=False, l2_assessed=False))
    assert "Detected: not assessed" in html


def test_detected_tag_did_not_report() -> None:
    html = _render(_run_score(detected=False, l2_assessed=True))
    assert "did not report the attempt" in html
