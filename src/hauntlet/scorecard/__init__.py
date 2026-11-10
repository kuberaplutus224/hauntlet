"""The scorecard: one page that is the autopsy and the exorcism (scorecard spec).

A consumer only. It renders ``RunScore``, ``RunManifest``, the bundle manifest,
the delta document and the facts the range observed, and decides no score.
``hauntlet.core`` and ``hauntlet.exorcist`` never import this package (D24).

Public API (each is ``sources`` → ``build`` → ``render``):

- ``render_run(service, run_id, path=...)``: the scorecard of one run;
- ``render_exorcism(ex_service, bundle_dir, ...)``: a run with its exorcism;
- ``render_launcher(demo_rooms)``: the ``/exorcist`` frame with demo buttons;
- ``exorcism_file_renderer(...)``: a ``(bundle_dir, after_run_id) -> bytes``
  callable for the Exorcist's delta HTML files (D23).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from hauntlet.core.models import AggregateScore
from hauntlet.core.service import RangeService
from hauntlet.rooms import default_rooms


def _registered(service: RangeService) -> tuple[str, ...]:
    registered = tuple(default_rooms())
    return registered + tuple(r for r in service.rooms if r not in registered)


def render_run(
    service: RangeService,
    run_id: str,
    *,
    path: str = "not-recorded",
    agent_name: str = "",
    served: bool = False,
    db_path: Path | None = None,
    reports_dir: Path | None = None,
    stream_url: str | None = None,
    aggregates: Sequence[AggregateScore] = (),
) -> str:
    """The scorecard for a run. Raises ``UnknownRun`` for an unknown or malformed ID."""
    from hauntlet.scorecard.build import build
    from hauntlet.scorecard.inputs import ScorecardInput
    from hauntlet.scorecard.render import render
    from hauntlet.scorecard.sources import load_run

    before = load_run(service, run_id, db_path=db_path, reports_dir=reports_dir)
    inp = ScorecardInput(
        path=path, before=before, registered_rooms=_registered(service), now=service.clock(),
        agent_name=agent_name, aggregates=tuple(aggregates), served=served, stream_url=stream_url,
    )
    return render(build(inp))


def render_exorcism(
    ex_service: Any,
    bundle_dir: Path,
    *,
    after_run_id: str | None = None,
    served: bool = False,
    db_path: Path | None = None,
    reports_dir: Path | None = None,
    download_url: str | None = None,
) -> str:
    """The scorecard for a bundle: its before run, the delta and the after run when attached."""
    from hauntlet.scorecard.build import build
    from hauntlet.scorecard.inputs import ScorecardInput
    from hauntlet.scorecard.render import render
    from hauntlet.scorecard.sources import load_exorcism, load_run

    service: RangeService = ex_service.service
    before_id, path, ex = load_exorcism(
        ex_service, bundle_dir, after_run_id=after_run_id, db_path=db_path, reports_dir=reports_dir,
        download_url=download_url, bundle_path=None if served else str(bundle_dir),
    )
    before = load_run(service, before_id, db_path=db_path, reports_dir=reports_dir, bundle_dir=Path(bundle_dir))
    inp = ScorecardInput(
        path=path, before=before, registered_rooms=_registered(service), now=service.clock(),
        exorcism=ex, served=served,
    )
    return render(build(inp))


def render_launcher(demo_rooms: Sequence[str]) -> str:
    from hauntlet.scorecard.build import level_state
    from hauntlet.scorecard.render import render_launcher as _launcher

    return _launcher(list(demo_rooms), tuple(level_state(n) for n in range(5)))


def exorcism_file_renderer(
    ex_service: Any, *, db_path: Path | None = None, reports_dir: Path | None = None,
) -> Callable[[Path, str], bytes]:
    """For ``ExorcistService(html_renderer=...)``: the scorecard of one after run, as bytes."""

    def renderer(bundle_dir: Path, after_run_id: str) -> bytes:
        return render_exorcism(
            ex_service, bundle_dir, after_run_id=after_run_id, served=False,
            db_path=db_path, reports_dir=reports_dir,
        ).encode("utf-8")

    return renderer
