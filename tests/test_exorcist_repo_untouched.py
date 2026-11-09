"""Running the Exorcist never touches this repository's own .kiro tree (exorcist Requirement 3.5, task 13.5)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.exorcist.service import ExorcistService
from hauntlet.rooms import default_rooms

REPO = Path(__file__).resolve().parent.parent
REPO_KIRO = REPO / ".kiro"


def _tree_hash(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_repo_kiro_is_byte_identical_after_a_demo(tmp_path: Path) -> None:
    before = _tree_hash(REPO_KIRO)
    service = RangeService(Store(":memory:"), default_rooms(), base_url="http://range.test")
    ex = ExorcistService(service, tmp_path / "exorcist", reports_dir=tmp_path / "reports", clock=lambda: 1.0)
    for room in ("cursed-repo", "poltergeist"):
        ex.demo(room)
    assert _tree_hash(REPO_KIRO) == before
    # Everything the Exorcist wrote is under the given scratch root.
    assert (tmp_path / "exorcist").exists()
