"""The suite leaves the repository's reports/ untouched.

``conftest._reports_dir_untouched`` snapshots ``reports/`` around every test and
fails the test that changed it. This file checks the snapshot itself notices a
new, changed or removed file, and that every CLI subcommand with a default
``--out`` of ``reports`` is given one by the tests that call it.

**Validates: test hygiene (no stray report files from ``uv run pytest``)**
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from conftest import reports_snapshot

TESTS = Path(__file__).parent


def test_snapshot_notices_new_changed_and_removed_files(tmp_path) -> None:
    root = tmp_path / "reports"
    assert reports_snapshot(root) is None
    root.mkdir()
    empty = reports_snapshot(root)
    (root / "a.html").write_text("x")
    one = reports_snapshot(root)
    assert one != empty
    (root / "a.html").write_text("xy")
    assert reports_snapshot(root) != one
    os.remove(root / "a.html")
    assert reports_snapshot(root) == empty


WRITERS = re.compile(
    r'main\(\[\s*"(run|sample-report|mcp", "finalize|parlor", "finalize|exorcist", "demo|exorcist", "delta)"[^\]]*\]'
)


def test_every_writing_cli_call_in_the_tests_passes_out() -> None:
    missing = []
    for path in TESTS.glob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        for m in WRITERS.finditer(text):
            if "--out" not in m.group(0):
                line = text.count("\n", 0, m.start()) + 1
                missing.append(f"{path.name}:{line}")
    assert not missing, missing
