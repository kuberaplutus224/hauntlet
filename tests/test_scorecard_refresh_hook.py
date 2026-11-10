"""The scorecard-refresh hook watches the scorecard (scorecard D25, task 18).

**Validates: scorecard Requirements 13.4, 13.5, D25**
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".kiro" / "hooks" / "scorecard-refresh.json"


def _hook() -> dict:
    (hook,) = json.loads(HOOK.read_text(encoding="utf-8"))["hooks"]
    return hook


@pytest.mark.parametrize(
    "path,fires",
    [
        ("src/hauntlet/scorecard/render.py", True),
        ("src/hauntlet/scorecard/static/scorecard.css", True),
        ("src/hauntlet/exorcist/texts.py", True),
        ("src/hauntlet/core/report.py", True),
        ("src/hauntlet/core/scorer.py", True),
        ("src/hauntlet/core/aggregate.py", True),
        ("src/hauntlet/rooms/parlor/room.py", False),
        ("src/hauntlet/exorcist/service.py", False),
        ("src/hauntlet/core/service.py", False),
    ],
)
def test_matcher(path, fires) -> None:
    hook = _hook()
    # Kiro tests the matcher as an unanchored regex against the saved file's path.
    assert bool(re.search(hook["matcher"], "/Users/x/hauntlet/" + path)) is fires


def test_command_and_timeout_unchanged() -> None:
    hook = _hook()
    assert hook["trigger"] == "PostFileSave"
    assert hook["action"] == {"type": "command", "command": "uv run hauntlet sample-report --out docs/sample-report.html"}
    assert hook["timeout"] == 60
