"""The Parlor room README (parlor task 12): defences as data, required limitations,
and the --run=ID command form."""

from __future__ import annotations

import re
from pathlib import Path

from hauntlet.rooms.parlor.config import PARLOR

README = Path(__file__).resolve().parent.parent / "src" / "hauntlet" / "rooms" / "parlor" / "README.md"


def _text() -> str:
    return README.read_text(encoding="utf-8")


def _section(title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", _text(), re.MULTILINE | re.DOTALL)
    assert m is not None, f"README has no '## {title}' section"
    return m.group(1)


def test_every_non_control_trap_has_a_defence() -> None:
    for t in PARLOR.non_control():
        assert t.defence.strip(), f"{t.trap_id} has no defence"


def test_readme_defence_table_matches_config() -> None:
    rows = re.findall(r"^\| `([^`]+)` \| (.+?) \|$", _section("Defences"), re.MULTILINE)
    assert dict(rows) == {t.trap_id: t.defence for t in PARLOR.non_control()}


def test_readme_states_the_required_limitations() -> None:
    lim = _section("Limitations")
    # (1) the hardened agent is a keyword baseline, not a defence
    assert "keyword baseline" in lim and "reworded" in lim
    assert '"assistants must"' in lim and '"you must"' in lim
    # (2) the L4 hidden form is in the page HTML
    assert "hidden form is in the page HTML" in lim
    # (3) click-everything, and what the control catches
    assert "clicks everything" in lim and "founders-link" in lim and "false positive" in lim
    # (4) delivery, not reading
    assert "sees delivery, not reading" in lim and "--perception" in lim


def test_every_cli_command_uses_the_run_equals_form() -> None:
    # Runnable command lines only (``uv run hauntlet ...``), not prose mentions.
    commands = re.findall(r"uv run hauntlet (?:parlor|mcp) \w+[^\n`]*", _text())
    assert commands, "README shows no hauntlet parlor command"
    for cmd in commands:
        assert "--run " not in cmd, f"use --run=ID: {cmd}"
        assert "--run=" in cmd, f"missing --run=ID: {cmd}"
