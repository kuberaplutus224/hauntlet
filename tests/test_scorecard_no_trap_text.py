"""No trap text on the page (scorecard SP11, task 12.4).

Every registered room is run in-process with the naive and hardened reference
agents, and the demo-supported rooms through a full demo exorcism. No page
shares a run of 6 consecutive words with any room template or fixture (the
exorcist EP3 check), and no finding region uses a theme word (Requirement 11.2).

**Validates: scorecard Requirements 10.4, 11.2, SP11**
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pytest
from _scorecard_html import parse

from hauntlet.agents import get_agent
from hauntlet.core.runner import run_once
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.exorcist.service import ExorcistService
from hauntlet.rooms import default_rooms
from hauntlet.scorecard import copy, render_exorcism, render_run

REPO = Path(__file__).resolve().parent.parent
_WORD = re.compile(r"[a-z0-9]+")


def _six(text: str) -> set[tuple[str, ...]]:
    w = _WORD.findall(text.lower())
    return {tuple(w[i : i + 6]) for i in range(len(w) - 5)}


@lru_cache(maxsize=1)
def _template_grams() -> frozenset[tuple[str, ...]]:
    grams: set[tuple[str, ...]] = set()
    for sub in ("templates", "fixtures"):
        for path in (REPO / "src/hauntlet/rooms").glob(f"*/{sub}/**/*"):
            if path.is_file():
                try:
                    grams |= _six(path.read_text(encoding="utf-8"))
                except UnicodeDecodeError:
                    continue
    return frozenset(grams)


def _check(html: str) -> None:
    doc = parse(html)
    # Text nodes joined per node, so a 6-gram never spans two unrelated nodes.
    shared = set()
    for n in doc.nodes:
        shared |= _six(n.text) & _template_grams()
    assert not shared, sorted(shared)[:3]
    finding = " ".join(n.text for n in doc.nodes if n.inside(data_finding=True)).lower()
    # Whole words: the product name "Hauntlet" (and its command and dummy-secret
    # prefix) is a name, which 11.2 allows; "haunted" or "ghost" in a finding is not.
    for word in copy.THEME_WORDS:
        assert not re.search(rf"\b{word}(s|ed|ing|ly)?\b", finding), word


@pytest.fixture(scope="module")
def svc() -> RangeService:
    return RangeService(Store(":memory:"), default_rooms())


@pytest.mark.parametrize("room", sorted(default_rooms()))
@pytest.mark.parametrize("agent", ["naive", "hardened"])
def test_reference_runs(svc, tmp_path, room, agent) -> None:
    r = run_once(svc, room, get_agent(agent), tmp_path)
    _check(render_run(svc, r.score.run_id, path=f"reference:{agent}", agent_name=agent))


@pytest.mark.parametrize("room", ["threshold", "cursed-repo", "cursed-repo-tests", "poltergeist", "poltergeist-legacy"])
def test_demo_exorcisms(svc, tmp_path, room) -> None:
    ex = ExorcistService(svc, tmp_path / "ex")
    res = ex.demo(room)
    _check(render_exorcism(ex, res.bundle_dir))
