"""Template safety and wording checks for the Cursed Repo rooms.

Requirements 6.2 (dummy secrets never in templates), 6.3 (payload guard passes)
and 7.2 (the hardened agent recognises every trap and not the control).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from hauntlet.agents.hardened import _DIRECTED
from hauntlet.core.room import render_template
from hauntlet.rooms.cursed_repo.config import CURSED_REPO, CURSED_REPO_TESTS, SLOTS, TrapDef

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_payload_safety import check_file  # noqa: E402

TEMPLATES = ROOT / "src" / "hauntlet" / "rooms" / "cursed_repo" / "templates"
REPO_DIR = TEMPLATES / "repo"
TRAPS_DIR = TEMPLATES / "traps"
CONTROL = TEMPLATES / "control" / "SECURITY.md.tmpl"

ALL_FILES = sorted(p for p in TEMPLATES.rglob("*") if p.is_file())
REPO_TEMPLATES = sorted(p for p in REPO_DIR.rglob("*.tmpl") if p.is_file())
ALL_TRAPS: tuple[TrapDef, ...] = CURSED_REPO.traps + CURSED_REPO_TESTS.traps


def _flat(text: str) -> str:
    """Collapse whitespace the way the hardened agent does before matching."""
    return " ".join(text.split())


def _rel(path: Path) -> str:
    return path.relative_to(TEMPLATES).as_posix()


def _snippet(trap: TrapDef) -> str:
    return (TRAPS_DIR / trap.snippet).read_text(encoding="utf-8")


def test_template_tree_is_populated() -> None:
    # Guards every other test here against passing vacuously on a wrong path.
    assert len(REPO_TEMPLATES) >= 7
    assert len([p for p in TRAPS_DIR.glob("*.tmpl") if p.is_file()]) >= 6
    assert CONTROL.is_file()
    assert len(ALL_TRAPS) == 6
    for trap in ALL_TRAPS:
        assert (TRAPS_DIR / trap.snippet).is_file(), trap.snippet


@pytest.mark.parametrize("path", ALL_FILES, ids=_rel)
def test_payload_guard_reports_nothing(path: Path) -> None:
    assert check_file(path) == []


def test_payload_guard_script_passes_on_templates_dir() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_payload_safety.py", str(TEMPLATES)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("trap", ALL_TRAPS, ids=lambda t: t.trap_id)
def test_trap_snippet_matches_hardened_pattern(trap: TrapDef) -> None:
    assert _DIRECTED.search(_flat(_snippet(trap))) is not None


def test_control_does_not_match_hardened_pattern() -> None:
    text = render_template(CONTROL, control_url="CONTROL_URL")
    assert _DIRECTED.search(_flat(text)) is None


@pytest.mark.parametrize("path", REPO_TEMPLATES, ids=_rel)
def test_empty_slot_repo_file_does_not_match_hardened_pattern(path: Path) -> None:
    text = render_template(path, **{slot: "" for slot in SLOTS})
    assert _DIRECTED.search(_flat(text)) is None


@pytest.mark.parametrize("trap", ALL_TRAPS, ids=lambda t: t.trap_id)
def test_env_var_reference_in_snippet(trap: TrapDef) -> None:
    text = _snippet(trap)
    if trap.env_var is not None:
        assert f"<value of {trap.env_var}>" in text
    else:
        assert "<value of " not in text


@pytest.mark.parametrize("path", ALL_FILES, ids=_rel)
def test_no_template_contains_a_dummy_secret(path: Path) -> None:
    assert "HAUNTLET-DUMMY" not in path.read_text(encoding="utf-8")
