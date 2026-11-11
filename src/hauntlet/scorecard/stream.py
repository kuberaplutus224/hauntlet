"""The live evidence stream (approved change D22): ``GET /runs/{run_id}/facts/stream``.

Server-Sent Events. Every poll, the stream loads the run through
``sources.load_run`` (redacted, with fact-log paths built only from the
store-validated run, design "Fact-log path"), builds the same evidence rows the
page shows (``facts.page_rows``), and sends each row whose ID it has not sent:

    id: <fact_id>
    event: fact
    data: {FactLine as JSON}

Once the run is finalized it sends ``event: finalized`` once. When the grace
window closes (or the run expired) it sends any last rows, then ``event: done``,
and ends. A finished run gets every row, ``finalized`` and ``done`` in one pass,
which is exactly what its page embeds (SP16).

A row that later merges another identical fact (×N) is not sent again: its first
ID was sent, and the merged IDs are marked sent. ``Last-Event-ID`` marks every row
up to and including that ID as sent. The stream records no event and serves no
room content.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict
from pathlib import Path

from anyio import to_thread

from hauntlet.core.service import RangeService
from hauntlet.scorecard.facts import page_rows
from hauntlet.scorecard.model import FactLine
from hauntlet.scorecard.sources import load_run

KEEPALIVE_SECS = 15.0
LIFETIME_SLACK_SECS = 5.0


def _rows(service: RangeService, run_id: str, db_path: Path | None, reports_dir: Path | None = None):
    ri = load_run(service, run_id, db_path=db_path, reports_dir=reports_dir)
    log, demo = page_rows(ri.facts, ri.run, ri.manifest, "before")
    return ri.run, list(log) + list(demo)


def _event(name: str, data: object, event_id: str | None = None) -> str:
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {name}\ndata: {json.dumps(data, ensure_ascii=False, sort_keys=True)}\n\n"


def _ids(row: FactLine) -> tuple[str, ...]:
    return row.ids or (row.fact_id,)


async def facts_stream(
    service: RangeService,
    run_id: str,
    *,
    db_path: Path | None,
    poll_secs: float,
    reports_dir: Path | None = None,
    max_secs: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    is_disconnected: Callable[[], Awaitable[bool]],
    last_event_id: str | None = None,
    clock: Callable[[], float] | None = None,
) -> AsyncIterator[str]:
    """The SSE body. The caller has already checked that the run exists."""
    clock = clock or service.clock
    sent: set[str] = set()
    finalized_sent = False
    idle = 0.0
    yield "retry: 3000\n\n"
    started = monotonic()

    run, rows = await to_thread.run_sync(_rows, service, run_id, db_path, reports_dir)
    if last_event_id:
        for i, row in enumerate(rows):
            if last_event_id in _ids(row):
                for r in rows[: i + 1]:
                    sent.update(_ids(r))
                break

    while True:
        new = [r for r in rows if r.fact_id not in sent]
        for row in new:
            sent.update(_ids(row))
            yield _event("fact", asdict(row), row.fact_id)
        if new:
            idle = 0.0
        if run.finalized_at is not None and not finalized_sent:
            finalized_sent = True
            yield _event("finalized", {})
        now = clock()
        closed = now >= run.window_close()
        too_long = now >= run.expires_at + run.grace_window_secs + LIFETIME_SLACK_SECS
        if closed or too_long:
            # One last read, so facts that landed after this poll's read are not lost.
            _run, rows = await to_thread.run_sync(_rows, service, run_id, db_path, reports_dir)
            for row in rows:
                if row.fact_id not in sent:
                    sent.update(_ids(row))
                    yield _event("fact", asdict(row), row.fact_id)
            yield _event("done", {})
            return
        if await is_disconnected():
            return
        if max_secs is not None and monotonic() - started >= max_secs:
            # D34: a stream is not held for a run's whole TTL. No ``done``: the browser
            # reconnects with Last-Event-ID; once the run is over, that stream ends with
            # ``done`` and the page stops.
            yield _event("timeout", {})
            return
        if idle >= KEEPALIVE_SECS:
            idle = 0.0
            yield ": keepalive\n\n"
        await asyncio.sleep(poll_secs)
        idle += poll_secs
        run, rows = await to_thread.run_sync(_rows, service, run_id, db_path, reports_dir)
