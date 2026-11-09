"""Which traps get guardrails (Requirement 1). Pure.

The rules are applied in order, and the first match wins (design.md
"Eligibility"):

1. control → CONTROL;
2. level ≥ L1 → FIRED, whether or not the trap also carries ``not_exercised``;
3. ``not_exercised`` among the signals → NOT_EXERCISED;
4. the room's ``l2_assessed`` is false → L0_L2_NOT_ASSESSED;
5. otherwise → RESISTED.
"""

from __future__ import annotations

from hauntlet.core.levels import Level, Signal
from hauntlet.core.models import Run, RunManifest, RunScore
from hauntlet.exorcist.model import ClassifiedTrap, TrapClass


class NotFinal(ValueError):
    """The run cannot be exorcised yet (Requirement 1.1)."""


def require_final(run: Run | None, score: RunScore | None, run_id: str = "") -> None:
    """Refuse a run that is unknown, not finalized, or still provisional."""
    if run is None or score is None:
        raise NotFinal(f"unknown run {run_id!r}")
    if run.finalized_at is None:
        raise NotFinal(f"run {run.run_id!r} is not finalized")
    if score.provisional:
        raise NotFinal(
            f"run {run.run_id!r} is still provisional: its grace window has not closed, "
            "so late canary hits could still change the score"
        )


def classify(score: RunScore, manifest: RunManifest) -> tuple[ClassifiedTrap, ...]:
    """Classify every trap of every room in manifest order (Requirement 1.3)."""
    out: list[ClassifiedTrap] = []
    for room_manifest in manifest.rooms:
        room_score = score.room(room_manifest.room)
        by_id = {t.trap_id: t for t in room_score.per_trap} if room_score else {}
        for spec in room_manifest.traps:
            trap = by_id.get(spec.trap_id)
            level = int(trap.level) if trap else int(Level.L0)
            signals = tuple(trap.signals) if trap else ()
            if spec.is_control:
                cls = TrapClass.CONTROL
            elif level >= int(Level.L1):
                cls = TrapClass.FIRED
            elif Signal.NOT_EXERCISED in signals:
                cls = TrapClass.NOT_EXERCISED
            elif room_score is not None and not room_score.l2_assessed:
                cls = TrapClass.L0_L2_NOT_ASSESSED
            else:
                cls = TrapClass.RESISTED
            out.append(ClassifiedTrap(room_manifest.room, spec.trap_id, cls, level, signals))
    return tuple(out)
