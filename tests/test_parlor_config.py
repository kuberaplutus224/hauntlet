"""Parlor room configuration (parlor task 4.3).

``PARLOR.validate()`` accepts the shipped config and rejects each broken
variant; the manifest passes canary-core's own validation.
"""

from __future__ import annotations

import dataclasses

import pytest

from hauntlet.core.service import RangeService, _validate_manifest
from hauntlet.core.store import Store
from hauntlet.rooms.parlor import ParlorRoom
from hauntlet.rooms.parlor.config import (
    PAGES,
    PARLOR,
    SURFACES,
    PageDef,
    RoomConfig,
    TrapPlacement,
)


def test_shipped_config_is_valid() -> None:
    PARLOR.validate()  # does not raise


def test_manifest_passes_core_validation() -> None:
    _validate_manifest("parlor", PARLOR.manifest())


def test_manifest_has_one_control_and_every_surface() -> None:
    m = PARLOR.manifest()
    controls = [t for t in m.traps if t.is_control]
    assert len(controls) == 1
    non_control_surfaces = sorted(t.surface for t in m.traps if not t.is_control)
    assert non_control_surfaces == sorted(SURFACES)
    assert all(t.source.strip() for t in m.traps if not t.is_control)


def test_room_registers_and_validates_on_construction() -> None:
    RangeService(Store(":memory:"), {"parlor": ParlorRoom()})


def _with_traps(*traps: TrapPlacement, **over) -> RoomConfig:
    return dataclasses.replace(PARLOR, traps=tuple(traps), **over)


def test_rejects_missing_surface() -> None:
    # Drop the visible-text trap: surfaces no longer cover the full set.
    kept = tuple(t for t in PARLOR.traps if t.surface != "visible text")
    with pytest.raises(ValueError, match="surface"):
        _with_traps(*kept).validate()


def test_rejects_two_controls() -> None:
    extra = dataclasses.replace(PARLOR.trap("founders-link"), trap_id="founders-link-2")
    with pytest.raises(ValueError, match="control"):
        _with_traps(*PARLOR.traps, extra).validate()


def test_rejects_trap_on_unreachable_page() -> None:
    cfg = dataclasses.replace(
        PARLOR,
        pages=(PageDef("lobby", "pages/lobby.html.tmpl", False), PageDef("orphan", "pages/ledger.html.tmpl", False)),
    )
    # ledger traps now sit on a page that is neither the start nor linked from it
    bad = dataclasses.replace(cfg, pages=(PageDef("lobby", "pages/lobby.html.tmpl", False),))
    with pytest.raises(ValueError, match="unknown page|unreachable"):
        bad.validate()


def test_rejects_site_action_without_named_path() -> None:
    aria = dataclasses.replace(PARLOR.trap("aria-note"), named_path=None)
    others = tuple(t for t in PARLOR.traps if t.trap_id != "aria-note")
    with pytest.raises(ValueError, match="named_path"):
        _with_traps(*others, aria).validate()


def test_rejects_named_path_escape() -> None:
    aria = dataclasses.replace(PARLOR.trap("aria-note"), named_path="../escape.txt")
    others = tuple(t for t in PARLOR.traps if t.trap_id != "aria-note")
    with pytest.raises(ValueError, match="relative"):
        _with_traps(*others, aria).validate()


def test_rejects_member_code_trap_without_secret_action() -> None:
    bad = dataclasses.replace(PARLOR, member_code_trap_id="notice-visible")
    with pytest.raises(ValueError, match="member_code_trap_id"):
        bad.validate()
