"""The reference agents drive the Parlor pages through fetch_local (parlor task 8.6).

Under the selftest path (a fresh scratch root, ``run_once`` -> ``setup_room``),
both agents fetch the lobby, ledger and image through ``ToolBox.fetch`` ->
``RangeService.fetch_local`` -> ``serve_page``, with no failed fetch, and the
recorded workspace's fact log holds the page and image deliveries.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hauntlet import cli
from hauntlet.core.runner import run_once
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms import default_rooms
from hauntlet.rooms.parlor import factlog
from hauntlet.agents import get_agent

BASE = "http://range.test"


@pytest.mark.parametrize("agent", ["naive", "hardened"])
def test_agents_browse_pages_through_fetch_local(agent: str) -> None:
    svc = RangeService(Store(":memory:"), default_rooms(), base_url=BASE)
    root = Path(tempfile.mkdtemp())
    res = run_once(svc, "parlor", get_agent(agent), root, keep_workspace=True)

    page_fetches = [c for c in res.tool_calls if c.startswith("fetch ") and "/c/" in c]
    assert page_fetches, "the agent made no page-token fetch"
    assert not any("refused" in e.text for e in res.transcript), "a page fetch was refused"

    workspace = root / f"parlor-{res.score.run_id}"
    facts = factlog.read(factlog.facts_path(workspace), res.score.run_id)
    page_ids = {f.page_id for f in facts if isinstance(f, factlog.PageFact)}
    assert {"lobby", "ledger"} <= page_ids
    assert any(isinstance(f, factlog.ImageFact) for f in facts)


def test_selftest_passes_with_parlor_registered() -> None:
    assert "parlor" in default_rooms()
    assert cli.main(["selftest", "-n", "1"]) == 0
