"""Deterministic golden scorecard pages (scorecard task 20; test-only factories).

``golden_pages(root)`` renders three pages with every source of chance pinned:

- ``demo-cursed-repo.html`` and ``demo-poltergeist.html``: a full hosted demo
  exorcism each, rendered as served over HTTP (so no bundle path appears);
- ``sample-report.html``: what ``hauntlet sample-report`` writes.

Pinned, all from the test side (no product code changes):

- one shared clock that advances 0.25 s per call, used by ``RangeService``, the
  ``ExorcistService`` and the Poltergeist server's fact log (the room builds its
  server with ``time.time`` as a default argument, so the test swaps in a
  ``PoltergeistServer`` bound to this clock);
- run IDs from a counter (``goldenRun0001``, …), seeds fixed at 0;
- bundle IDs from a counter (``goldenBundle01``, …) via ``writer.new_bundle_id``.

Canary values stay random. They never reach the page (redaction, SP10), so the
bytes do not depend on them; rendering twice and comparing proves it.
"""

from __future__ import annotations

import functools
import itertools
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

CLOCK_START = 1_800_000_000.0
TICK = 0.25
NAMES = ("demo-cursed-repo.html", "demo-poltergeist.html", "sample-report.html")


class TickClock:
    def __init__(self, start: float = CLOCK_START, tick: float = TICK) -> None:
        self.now = start
        self.tick = tick

    def __call__(self) -> float:
        self.now += self.tick
        return self.now


def golden_pages(root: Path) -> dict[str, str]:
    from hauntlet.cli import main
    from hauntlet.core.service import RangeService
    from hauntlet.core.store import Store
    from hauntlet.exorcist import writer
    from hauntlet.exorcist.service import ExorcistService
    from hauntlet.rooms import default_rooms
    from hauntlet.rooms.poltergeist import room as polt_room
    from hauntlet.rooms.poltergeist.server import PoltergeistServer
    from hauntlet.scorecard import exorcism_file_renderer, render_exorcism

    root = Path(root)
    clock = TickClock()
    run_ids = (f"goldenRun{n:04d}" for n in itertools.count(1))
    bundle_ids = (f"goldenBundle{n:02d}" for n in itertools.count(1))
    pages: dict[str, str] = {}
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(polt_room, "PoltergeistServer", functools.partial(PoltergeistServer, clock=clock)))
        stack.enter_context(mock.patch.object(writer, "new_bundle_id", lambda: next(bundle_ids)))
        svc = RangeService(
            Store(":memory:"), default_rooms(), clock=clock,
            run_id_factory=lambda: next(run_ids), seed_factory=lambda: 0,
        )
        ex = ExorcistService(svc, root / "exorcist", clock=clock)
        ex.html_renderer = exorcism_file_renderer(ex)
        for room in ("cursed-repo", "poltergeist"):
            res = ex.demo(room)
            pages[f"demo-{room}.html"] = render_exorcism(
                ex, res.bundle_dir, served=True, download_url=f"/exorcisms/{res.bundle_id}/bundle",
            )
    sample = root / "sample-report.html"
    assert main(["sample-report", "--out", str(sample)]) == 0
    pages["sample-report.html"] = sample.read_text(encoding="utf-8")
    return pages
