"""Hypothesis strategies shared by the Exorcist property tests (design "Correctness properties").

``runs()`` draws a synthetic before run over the registered rooms' real
manifests:

- one to three distinct rooms;
- for every trap, a random level and signal set, including ``not_exercised``;
- per room: random ``l2_assessed``, ``detected``, ``task_completed`` and false
  positives;
- canary values minted with the real ``mint_canaries``.

It returns ``SyntheticRun(score, manifest, canaries)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import strategies as st

from hauntlet.core.canary import mint_canaries
from hauntlet.core.levels import Level, Signal
from hauntlet.core.models import Canary, RoomScore, RunManifest, RunScore, TrapScore
from hauntlet.rooms import default_rooms

ROOMS = default_rooms()
ROOM_NAMES = sorted(ROOMS)
#: Signals a trap can carry in a score (task_done belongs to __task__ only).
TRAP_SIGNALS = tuple(s.value for s in Signal if s is not Signal.TASK_DONE)

run_ids = st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", min_size=8, max_size=16)


@dataclass(frozen=True)
class SyntheticRun:
    score: RunScore
    manifest: RunManifest
    canaries: tuple[Canary, ...]


@st.composite
def trap_scores(draw, trap_id: str, is_control: bool) -> TrapScore:
    level = Level(draw(st.integers(0, 4)))
    signals = tuple(sorted(draw(st.sets(st.sampled_from(TRAP_SIGNALS), max_size=4))))
    return TrapScore(trap_id, is_control, level, Signal.FLAGGED in signals, signals)


@st.composite
def runs(draw, room_names: st.SearchStrategy[list[str]] | None = None) -> SyntheticRun:
    names = draw(
        room_names
        if room_names is not None
        else st.lists(st.sampled_from(ROOM_NAMES), min_size=1, max_size=3, unique=True)
    )
    run_id = draw(run_ids)
    manifest = RunManifest(run_id=run_id, rooms=tuple(ROOMS[n].manifest() for n in names))
    room_scores = []
    for rm in manifest.rooms:
        per_trap = tuple(draw(trap_scores(t.trap_id, t.is_control)) for t in rm.traps)
        controls = [t.trap_id for t in rm.traps if t.is_control]
        fps = tuple(sorted(draw(st.sets(st.sampled_from(controls))))) if controls else ()
        worst = max((t.level for t in per_trap if not t.is_control), default=Level.L0)
        room_scores.append(
            RoomScore(
                room=rm.room,
                worst_level=worst,
                detected=draw(st.booleans()),
                false_positives=fps,
                per_trap=per_trap,
                task_completed=draw(st.booleans()),
                l2_assessed=draw(st.booleans()),
            )
        )
    overall = max((r.worst_level for r in room_scores), default=Level.L0)
    score = RunScore(run_id=run_id, rooms=tuple(room_scores), overall_worst=overall)
    return SyntheticRun(score, manifest, tuple(mint_canaries(manifest)))
