"""The top-level README's "Benchmark coverage" table lists exactly the
non-control traps of the cited rooms, so it cannot drift from the registry."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from hauntlet.rooms import default_rooms

README = Path(__file__).resolve().parent.parent / "README.md"
COVERED_ROOMS = ("cursed-repo", "cursed-repo-tests", "poltergeist", "poltergeist-legacy", "parlor")


def _section(title: str) -> str:
    text = README.read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert m is not None, f"README has no '## {title}' section"
    return m.group(1)


def _table_trap_ids() -> list[str]:
    # Data rows: "| <room cell> | `<trap id>` | ..."
    return re.findall(r"^\| [^|]+ \| `([^`]+)` \|", _section("Benchmark coverage"), re.MULTILINE)


def _registry_trap_ids() -> set[str]:
    rooms = default_rooms()
    return {
        t.trap_id
        for name in COVERED_ROOMS
        for t in rooms[name].manifest().traps
        if not t.is_control
    }


def test_table_lists_exactly_the_non_control_traps() -> None:
    assert set(_table_trap_ids()) == _registry_trap_ids()


def test_table_has_one_row_per_trap() -> None:
    dups = [t for t, c in Counter(_table_trap_ids()).items() if c > 1]
    assert not dups, f"duplicate rows for {dups}"
