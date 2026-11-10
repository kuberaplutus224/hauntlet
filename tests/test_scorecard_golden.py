"""Golden scorecard pages (scorecard task 20.3).

The three pages the maintainer reviewed on 2026-11-09 (the Cursed Repo and
Poltergeist demo exorcisms as served, and the sample), rendered with every
source of chance pinned (``_scorecard_golden_support``), must match the files in
``tests/fixtures/scorecard_golden/`` byte for byte. The sample golden must also
equal ``docs/sample-report.html``, which the ``scorecard-refresh`` hook keeps
current.

A failure means the page changed. If the change is intended, re-render with
``HAUNTLET_UPDATE_GOLDEN=1``, look at the new pages, and commit them with the
change. Never re-capture to make an unexplained difference go away.

**Validates: scorecard Requirements 13.4, 13.6**
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

import pytest
from _scorecard_golden_support import NAMES, golden_pages

GOLDEN = Path(__file__).parent / "fixtures" / "scorecard_golden"
DOCS_SAMPLE = Path(__file__).resolve().parents[1] / "docs" / "sample-report.html"
UPDATE = os.environ.get("HAUNTLET_UPDATE_GOLDEN") == "1"


@pytest.fixture(scope="module")
def pages(tmp_path_factory) -> dict[str, str]:
    return golden_pages(tmp_path_factory.mktemp("golden"))


def _first_difference(a: str, b: str) -> str:
    diff = difflib.unified_diff(a.split(">"), b.split(">"), "golden", "rendered", lineterm="", n=1)
    return "\n".join(list(diff)[:12])


@pytest.mark.parametrize("name", NAMES)
def test_page_matches_its_golden(pages, name) -> None:
    path = GOLDEN / name
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pages[name], encoding="utf-8")
        return
    assert path.is_file(), f"missing golden {path} (capture with HAUNTLET_UPDATE_GOLDEN=1)"
    golden = path.read_text(encoding="utf-8")
    assert pages[name] == golden, _first_difference(golden, pages[name])


def test_sample_golden_is_the_committed_sample() -> None:
    assert (GOLDEN / "sample-report.html").read_bytes() == DOCS_SAMPLE.read_bytes()
