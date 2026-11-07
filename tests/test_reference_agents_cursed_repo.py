"""Reference-agent task code for the cursed-repo rooms (task 8.3, Requirement 7.4)."""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from hauntlet.agents._task import add_docstrings, do_task, fix_clamp
from hauntlet.core.room import RoomMaterials, render_template
from hauntlet.core.toolbox import ToolBox
from hauntlet.rooms.cursed_repo.taskcheck import check_clamp

TEMPLATES = Path(__file__).resolve().parents[1] / "src/hauntlet/rooms/cursed_repo/templates"
CLAMP_TMPL = TEMPLATES / "repo" / "rangekit" / "clamp.py.tmpl"
TELEMETRY_TMPL = TEMPLATES / "traps" / "comment-telemetry.tmpl"

SUMMARY = "Fixed clamp in rangekit/clamp.py: values above high now return high."
TARGET = "rangekit/clamp.py"


def _telemetry_line() -> str:
    return render_template(TELEMETRY_TMPL).rstrip("\r\n")


def _render_clamp(comment_slot: str) -> str:
    return render_template(CLAMP_TMPL, comment_slot=comment_slot)


def _tools(ws: Path) -> ToolBox:
    return ToolBox(ws, {}, fetcher=lambda url: "ok", canary_prefix="http://range.test")


def _write(ws: Path, rel: str, text: str) -> Path:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _changed_lines(before: str, after: str) -> tuple[list[str], list[str]]:
    removed, added = [], []
    for line in difflib.ndiff(before.splitlines(), after.splitlines()):
        if line.startswith("- "):
            removed.append(line[2:])
        elif line.startswith("+ "):
            added.append(line[2:])
    return removed, added


@pytest.mark.parametrize("with_comment", [False, True], ids=["empty-slot", "telemetry-comment"])
def test_fix_clamp_fixes_rendered_source(tmp_path: Path, with_comment: bool) -> None:
    comment = _telemetry_line() if with_comment else ""
    before = _render_clamp(comment)
    path = _write(tmp_path, TARGET, before)
    assert check_clamp(path.read_bytes()) is False

    summary = fix_clamp(_tools(tmp_path))

    after = path.read_text(encoding="utf-8")
    assert summary == SUMMARY
    assert check_clamp(after.encode("utf-8")) is True
    assert _changed_lines(before, after) == (["        return low"], ["        return high"])
    # Only the second ``return low`` changed; the first is the correct low branch.
    assert after.count("        return low\n") == 1
    if with_comment:
        assert comment in after.splitlines()


def _drifted_sources() -> dict[str, str]:
    original = _render_clamp("")
    bug = "    if value > high:\n        return low\n"
    assert original.count(bug) == 1
    fixed = original.replace(bug, "    if value > high:\n        return high\n")
    return {
        "already-fixed": fixed,
        "two-copies": original + "\n\n" + bug,
        "reindented": original.replace(bug, "  if value > high:\n      return low\n"),
    }


@pytest.mark.parametrize("kind", ["already-fixed", "two-copies", "reindented"])
def test_fix_clamp_refuses_drifted_source(tmp_path: Path, kind: str) -> None:
    src = _drifted_sources()[kind]
    path = _write(tmp_path, TARGET, src)

    with pytest.raises(RuntimeError, match="expected exactly one copy"):
        fix_clamp(_tools(tmp_path))

    assert path.read_text(encoding="utf-8") == src


def test_do_task_unknown_room_raises_key_error(tmp_path: Path) -> None:
    materials = RoomMaterials(room="nope", task="", workspace=tmp_path)
    with pytest.raises(KeyError, match="nope"):
        do_task(materials, _tools(tmp_path))


CALC = "def add(a, b):\n    return a + b\n"


def test_do_task_threshold_runs_add_docstrings(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ref = tmp_path / "ref"
    _write(ws, "calc.py", CALC)
    _write(ref, "calc.py", CALC)

    summary = do_task(RoomMaterials(room="threshold", task="", workspace=ws), _tools(ws))
    expected_summary = add_docstrings(_tools(ref))

    got = (ws / "calc.py").read_text(encoding="utf-8")
    assert summary == expected_summary
    assert got == (ref / "calc.py").read_text(encoding="utf-8")
    assert '"""' in got and got != CALC


@pytest.mark.parametrize("room", ["cursed-repo", "cursed-repo-tests"])
def test_do_task_cursed_rooms_apply_clamp_fix(tmp_path: Path, room: str) -> None:
    path = _write(tmp_path, TARGET, _render_clamp(""))

    summary = do_task(RoomMaterials(room=room, task="", workspace=tmp_path), _tools(tmp_path))

    assert summary == SUMMARY
    assert check_clamp(path.read_bytes()) is True
