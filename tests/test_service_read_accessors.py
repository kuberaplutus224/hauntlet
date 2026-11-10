"""Read-only RangeService accessors (scorecard D21, D30; task 2.2).

**Validates: scorecard Requirements 15.1 (a), (i), D21, D30**
"""

from __future__ import annotations

import pytest

from hauntlet.agents import get_agent
from hauntlet.core.models import to_dict
from hauntlet.core.runner import run_once
from hauntlet.core.service import UnknownRun


def test_events_and_canaries_mirror_the_store(service, tmp_path) -> None:
    r = run_once(service, "threshold", get_agent("naive"), tmp_path)
    run_id = r.score.run_id
    before = to_dict(service.score(run_id))

    events = service.events(run_id)
    canaries = service.canaries(run_id)

    assert events == service.store.events_for_run(run_id)
    assert events, "a naive threshold run records events"
    assert canaries == service.store.canaries_for_run(run_id)
    assert {c.kind for c in canaries} >= {"url", "secret", "marker"}
    # Read-only: reading changes no score.
    assert to_dict(service.score(run_id)) == before


@pytest.mark.parametrize("name", ["events", "canaries"])
def test_unknown_run_raises(service, name: str) -> None:
    with pytest.raises(UnknownRun):
        getattr(service, name)("no-such-run-00")
