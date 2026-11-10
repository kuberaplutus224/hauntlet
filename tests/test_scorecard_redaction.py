"""No canary value on the page (scorecard SP10, page half; task 12.4).

Events whose details carry the run's canary values (raw, and inside a ``/c/``
URL with a dummy secret in the query) are rendered. Neither the HTML nor the
embedded ``#sc-data`` JSON holds any full value, anything after
``HAUNTLET-DUMMY-`` or ``hauntlet-mark-``, or any URL or page token.

**Validates: scorecard Requirements 10.1–10.3, SP10**
"""

from __future__ import annotations

from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings

from hauntlet.core.canary import DUMMY_PREFIX, MARKER_PREFIX
from hauntlet.scorecard.build import build
from hauntlet.scorecard.render import render


def leaks(text: str, canaries) -> list[str]:
    low = text.lower()
    bad = []
    for c in canaries:
        if c.kind == "secret":
            tail = c.value[len(DUMMY_PREFIX) + 1 :].lower()
            if c.value.lower() in low or tail in low:
                bad.append(c.value)
        elif c.kind == "marker":
            if c.value[len(MARKER_PREFIX) + 1 :].lower() in low:
                bad.append(c.value)
        elif c.value in text:
            bad.append(c.value)
    return bad


@settings(max_examples=120, deadline=None)
@given(case=scorecard_inputs())
def test_sp10_no_canary_value_in_the_page(case) -> None:
    html = render(build(case.inp))
    assert not leaks(html, case.before.canaries)


def test_every_canary_kind_in_every_channel_is_redacted() -> None:
    """Example: all of a run's canary values, raw and percent-encoded, in every channel."""
    from urllib.parse import quote

    from _exorcist_strategies import runs
    from _scorecard_strategies import CREATED, REGISTERED
    from hypothesis import find

    from hauntlet.core.models import Event, Run
    from hauntlet.redact import redactor
    from hauntlet.scorecard.facts import normalise_event
    from hauntlet.scorecard.inputs import RunInput, ScorecardInput

    run = find(runs(), lambda r: len(r.canaries) >= 3)
    red = redactor(run.canaries)
    rm = run.manifest.rooms[0]
    events = []
    for i, c in enumerate(run.canaries):
        for ch in ("network", "filesystem", "transcript"):
            events.append(Event(run.score.run_id, rm.room, rm.traps[0].trap_id, ch, "acted", CREATED + i,
                                f"saw {c.value} and /c/{c.value}?k={quote(c.value)}"))
    facts = tuple(normalise_event(e, run.manifest, red) for e in events)
    inp = ScorecardInput("not-recorded", RunInput(Run(run.score.run_id, CREATED, CREATED + 900, 0, finalized_at=CREATED + 9),
                                                  run.score, run.manifest, facts), REGISTERED, CREATED + 500)
    html = render(build(inp))
    assert not leaks(html, run.canaries)
    assert "HAUNTLET-DUMMY-…" in html or not any(c.kind == "secret" for c in run.canaries)


def test_real_runs_through_sources_are_redacted(tmp_path) -> None:
    """Every registered room, naive agent, with its live fact log kept beside the
    store, rendered through ``sources`` with the run's D30 canaries."""
    from hauntlet.agents import get_agent
    from hauntlet.core.runner import run_once
    from hauntlet.core.service import RangeService
    from hauntlet.core.store import Store
    from hauntlet.paths import scratch_root_beside
    from hauntlet.rooms import default_rooms
    from hauntlet.scorecard import render_run

    db = tmp_path / "range" / "range.db"
    svc = RangeService(Store(db), default_rooms())
    raw_leaks = 0
    for room in default_rooms():
        r = run_once(svc, room, get_agent("naive"), scratch_root_beside(db), keep_workspace=True)
        canaries = svc.canaries(r.score.run_id)
        raw = " ".join(e.detail for e in svc.events(r.score.run_id))
        for f in scratch_root_beside(db).glob(f"{room}-{r.score.run_id}/*-facts.jsonl"):
            raw += f.read_text(encoding="utf-8")
        raw_leaks += len(leaks(raw, canaries))
        html = render_run(svc, r.score.run_id, path="reference:naive", db_path=db)
        assert not leaks(html, canaries), room
    assert raw_leaks, "the raw facts do carry canary values, so this test means something"
