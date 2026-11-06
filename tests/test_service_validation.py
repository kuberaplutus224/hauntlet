"""Manifest validation at construction and finalize rejection tests.

Covers:
  - Invalid manifest variants (a)–(e) → InvalidRoom raised at RangeService construction (Req 3.1)
  - Valid manifest accepted without error (Req 3.1)
  - Re-finalizing a finalized run raises InvalidObservation (Req 1.3)
  - Finalizing after window_close raises InvalidObservation("run closed") (Req 1.3)
"""

from __future__ import annotations

import pytest

from hauntlet.core.models import RoomManifest, TrapSpec
from hauntlet.core.room import Room, RoomContext, RoomMaterials, Transcript
from hauntlet.core.service import InvalidObservation, InvalidRoom, RangeService
from hauntlet.core.store import Store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_room(room_name: str, traps: list[TrapSpec]) -> Room:
    """Build a minimal Room stub with the given trap list."""
    manifest = RoomManifest(room=room_name, traps=tuple(traps))

    class _StubRoom:
        name = room_name

        def manifest(self) -> RoomManifest:
            return manifest

        def setup(self, ctx: RoomContext) -> RoomMaterials:  # pragma: no cover
            raise NotImplementedError

        def collect(self, ctx: RoomContext, materials: RoomMaterials, transcript: Transcript | None) -> list:  # pragma: no cover
            raise NotImplementedError

        def teardown(self, ctx: RoomContext) -> None:  # pragma: no cover
            pass

    return _StubRoom()  # type: ignore[return-value]


def _valid_traps() -> list[TrapSpec]:
    """A minimal set of traps that satisfies all validation rules."""
    return [
        TrapSpec(trap_id="trap-1", surface="NOTES.md", source="arXiv:2607.05744", is_control=False),
        TrapSpec(trap_id="ctrl-1", surface="README.md", source="", is_control=True),
    ]


def _service_with(*rooms: Room) -> RangeService:
    """Construct a RangeService with the given rooms against an in-memory store."""
    return RangeService(Store(":memory:"), {r.name: r for r in rooms})


class FakeClock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ---------------------------------------------------------------------------
# Variant (a): no is_control=True trap
# ---------------------------------------------------------------------------

def test_invalid_manifest_no_control_trap() -> None:
    """RangeService rejects a room whose manifest has no control trap."""
    room = _make_room(
        "no-control",
        [
            TrapSpec(trap_id="trap-1", surface="NOTES.md", source="arXiv:2607.05744", is_control=False),
            TrapSpec(trap_id="trap-2", surface="README.md", source="arXiv:2607.05744", is_control=False),
        ],
    )
    with pytest.raises(InvalidRoom, match="no control trap"):
        _service_with(room)


# ---------------------------------------------------------------------------
# Variant (b): no is_control=False trap
# ---------------------------------------------------------------------------

def test_invalid_manifest_no_non_control_trap() -> None:
    """RangeService rejects a room whose manifest has only control traps."""
    room = _make_room(
        "all-controls",
        [
            TrapSpec(trap_id="ctrl-1", surface="NOTES.md", source="", is_control=True),
            TrapSpec(trap_id="ctrl-2", surface="README.md", source="", is_control=True),
        ],
    )
    with pytest.raises(InvalidRoom, match="no non-control trap"):
        _service_with(room)


# ---------------------------------------------------------------------------
# Variant (c): duplicate trap IDs
# ---------------------------------------------------------------------------

def test_invalid_manifest_duplicate_trap_ids() -> None:
    """RangeService rejects a room with duplicate trap IDs."""
    room = _make_room(
        "dup-ids",
        [
            TrapSpec(trap_id="trap-1", surface="NOTES.md", source="arXiv:2607.05744", is_control=False),
            TrapSpec(trap_id="trap-1", surface="README.md", source="arXiv:2607.05744", is_control=False),
            TrapSpec(trap_id="ctrl-1", surface="AGENTS.md", source="", is_control=True),
        ],
    )
    with pytest.raises(InvalidRoom, match="duplicate trap IDs"):
        _service_with(room)


# ---------------------------------------------------------------------------
# Variant (d): a trap uses the reserved ID "__task__"
# ---------------------------------------------------------------------------

def test_invalid_manifest_reserved_task_id() -> None:
    """RangeService rejects a room where a trap uses the reserved ID '__task__'."""
    room = _make_room(
        "reserved-id",
        [
            TrapSpec(trap_id="__task__", surface="NOTES.md", source="arXiv:2607.05744", is_control=False),
            TrapSpec(trap_id="ctrl-1", surface="README.md", source="", is_control=True),
        ],
    )
    with pytest.raises(InvalidRoom, match="reserved"):
        _service_with(room)


# ---------------------------------------------------------------------------
# Variant (e): non-control trap with an empty source citation
# ---------------------------------------------------------------------------

def test_invalid_manifest_empty_source_on_non_control() -> None:
    """RangeService rejects a room where a non-control trap has an empty source."""
    room = _make_room(
        "no-source",
        [
            TrapSpec(trap_id="trap-1", surface="NOTES.md", source="", is_control=False),
            TrapSpec(trap_id="ctrl-1", surface="README.md", source="", is_control=True),
        ],
    )
    with pytest.raises(InvalidRoom, match="source citation"):
        _service_with(room)


# ---------------------------------------------------------------------------
# Valid manifest accepted
# ---------------------------------------------------------------------------

def test_valid_manifest_is_accepted() -> None:
    """RangeService accepts a manifest that satisfies all five validation rules."""
    room = _make_room("valid-room", _valid_traps())
    svc = _service_with(room)  # must not raise
    assert "valid-room" in svc.rooms


# ---------------------------------------------------------------------------
# Re-finalizing a finalized run raises
# ---------------------------------------------------------------------------

def test_double_finalize_raises() -> None:
    """Calling finalize on an already-finalized run raises InvalidObservation."""
    room = _make_room("valid-room", _valid_traps())
    svc = _service_with(room)
    desc = svc.start_run(["valid-room"])
    svc.finalize(desc.run.run_id, [], transcript_provided=False)
    with pytest.raises(InvalidObservation, match="already finalized"):
        svc.finalize(desc.run.run_id, [], transcript_provided=False)


# ---------------------------------------------------------------------------
# Finalizing after window_close raises "run closed"
# ---------------------------------------------------------------------------

def test_finalize_after_window_close_raises_run_closed() -> None:
    """Calling finalize after the run's window_close timestamp raises 'run closed'."""
    clock = FakeClock()
    room = _make_room("valid-room", _valid_traps())
    svc = RangeService(
        Store(":memory:"),
        {"valid-room": room},
        clock=clock,
        default_ttl=10,
    )
    desc = svc.start_run(["valid-room"], grace_window_secs=0.0)
    # Advance past expires_at (10 s) + grace window (0 s)
    clock.advance(11)
    with pytest.raises(InvalidObservation, match="run closed"):
        svc.finalize(desc.run.run_id, [], transcript_provided=False)
