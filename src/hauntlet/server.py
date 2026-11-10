"""HTTP surface for the range. A thin wrapper over RangeService."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from hauntlet import __version__
from hauntlet.core.models import to_dict
from hauntlet.scorecard import render_exorcism, render_launcher, render_run
from hauntlet.core.room import Observation
from hauntlet.core.service import InvalidObservation, RangeService, RunClosed, UnknownRun
from hauntlet.core.store import Store
from hauntlet.paths import scratch_root_beside
from hauntlet.rooms import default_rooms

#: Canary kinds that have a ``/c/{value}`` URL: trap call-home links and, from
#: approved change D11, a page room's page token.
_URL_KINDS = ("url", "page")


class StartRun(BaseModel):
    rooms: list[str] = Field(default_factory=lambda: ["threshold"])
    ttl_seconds: float | None = Field(default=None, gt=0, le=24 * 3600)
    grace_window_secs: float = Field(default=30.0, ge=0, le=300)


class ObservationIn(BaseModel):
    room: str
    trap_id: str
    channel: str
    signal: str
    detail: str = ""


class Finalize(BaseModel):
    observations: list[ObservationIn] = Field(default_factory=list)
    transcript_provided: bool = False


def _db_path() -> Path:
    return Path(os.environ.get("HAUNTLET_DB", ".hauntlet/range.db"))


def create_app(service: RangeService | None = None) -> FastAPI:
    if service is None:
        db = os.environ.get("HAUNTLET_DB", ".hauntlet/range.db")
        service = RangeService(
            Store(db),
            default_rooms(),
            base_url=os.environ.get("HAUNTLET_BASE_URL", "http://127.0.0.1:8666"),
            # D11: serve page-room workspaces that another process (for example
            # `hauntlet parlor open`) set up beside the shared store.
            page_scratch_root=scratch_root_beside(Path(db)),
        )
    app = FastAPI(title="Hauntlet", version=__version__)
    app.state.service = service

    @app.middleware("http")
    async def noindex(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    def _run_or_404(run_id: str):
        try:
            return service.get_run(run_id)
        except UnknownRun:
            raise HTTPException(404, "unknown run") from None

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "rooms": sorted(service.rooms)}

    def _run_dict(run) -> dict:
        """Serialize a Run, adding the computed window_close field."""
        d = to_dict(run)
        d["window_close"] = run.window_close()
        return d

    @app.post("/runs", status_code=201)
    def start_run(body: StartRun) -> dict:
        try:
            desc = service.start_run(body.rooms, ttl=body.ttl_seconds, grace_window_secs=body.grace_window_secs)
        except KeyError as exc:
            raise HTTPException(400, str(exc)) from None
        return {
            "run": _run_dict(desc.run),
            "manifest": to_dict(desc.manifest),
            "canaries": [
                {**to_dict(c), "url": f"{service.base_url}/c/{c.value}" if c.kind in _URL_KINDS else None}
                for c in desc.canaries
            ],
        }

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        return _run_dict(_run_or_404(run_id))

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots() -> str:
        return "User-agent: *\nDisallow: /\n"

    @app.get("/c/{token}", response_class=PlainTextResponse)
    def canary(token: str, request: Request) -> Response:
        # A trap's URL canary: record the hit and answer "ok", exactly as before D11.
        if service.record_hit(token, request.url.query) is not None:
            return PlainTextResponse("ok")
        # D11: a page room's page token. Serves content, records no event.
        page = service.serve_page(token, request.url.query)
        if page is not None:
            return Response(page.body, media_type=page.content_type, headers=dict(page.headers))
        raise HTTPException(404, "not found")

    @app.post("/runs/{run_id}/finalize")
    def finalize(run_id: str, body: Finalize) -> dict:
        _run_or_404(run_id)
        try:
            score = service.finalize(
                run_id,
                [Observation(**o.model_dump()) for o in body.observations],
                transcript_provided=body.transcript_provided,
            )
        except RunClosed as exc:
            raise HTTPException(409, str(exc)) from None
        except InvalidObservation as exc:
            raise HTTPException(400, str(exc)) from None
        return to_dict(score)

    @app.get("/runs/{run_id}/score")
    def score(run_id: str) -> dict:
        _run_or_404(run_id)
        return to_dict(service.score(run_id))

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    def report(run_id: str) -> str:
        # D23: the scorecard. Who ran the agent is not recorded for API runs (Q1: C4).
        run = _run_or_404(run_id)
        live = run.is_active(service.clock())
        try:
            return render_run(
                service, run_id, path="not-recorded", served=True, db_path=_db_path(),
                stream_url=f"/runs/{run_id}/facts/stream" if live else None,
            )
        except UnknownRun:
            raise HTTPException(404, "unknown run") from None

    _mount_stream(app, service)
    _mount_exorcist(app, service)
    return app


def _stream_caps() -> tuple[int, float]:
    def _num(name: str, default, cast):
        try:
            v = cast(os.environ[name])
        except (KeyError, ValueError):
            return default
        return v if v > 0 else default

    return _num("HAUNTLET_STREAM_MAX", 20, int), _num("HAUNTLET_STREAM_POLL_SECS", 0.5, float)


def _mount_stream(app: FastAPI, service: RangeService) -> None:
    """D22: the live evidence stream for a run. Redacted rows only; records nothing."""
    import threading

    from fastapi.responses import StreamingResponse
    from starlette.background import BackgroundTask

    from hauntlet.core.service import UnknownRun
    from hauntlet.scorecard.sources import check_run_id
    from hauntlet.scorecard.stream import facts_stream

    max_streams, poll = _stream_caps()
    slots = threading.BoundedSemaphore(max_streams)
    db = Path(os.environ.get("HAUNTLET_DB", ".hauntlet/range.db"))
    app.state.stream_slots = slots

    @app.get("/runs/{run_id}/facts/stream")
    async def facts_stream_route(run_id: str, request: Request):
        try:
            check_run_id(run_id)
            service.get_run(run_id)
        except UnknownRun:
            raise HTTPException(404, "unknown run") from None
        if not slots.acquire(blocking=False):
            return PlainTextResponse("too many live streams; try again shortly", status_code=429)

        released = threading.Event()

        def release() -> None:
            # Idempotent: runs from the body's finally and as a background task, so a
            # client that leaves before the body starts still frees its slot.
            if not released.is_set():
                released.set()
                slots.release()

        async def body():
            try:
                async for chunk in facts_stream(
                    service, run_id, db_path=db, poll_secs=poll,
                    is_disconnected=request.is_disconnected,
                    last_event_id=request.headers.get("last-event-id"),
                ):
                    yield chunk
            finally:
                release()

        return StreamingResponse(
            body(), media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            background=BackgroundTask(release),
        )


class _ExorciseAfter(BaseModel):
    run_id: str


class _DemoRequest(BaseModel):
    room: str


def _exorcist_caps() -> "HostedCaps":
    from hauntlet.exorcist.hosted import HostedCaps

    def _num(name: str, default: float) -> float:
        try:
            return type(default)(os.environ[name])
        except (KeyError, ValueError):
            return default

    rooms = os.environ.get("HAUNTLET_EXORCIST_DEMO_ROOMS", "cursed-repo,poltergeist")
    return HostedCaps(
        max_concurrent=int(_num("HAUNTLET_EXORCIST_MAX_CONCURRENT", 1)),
        per_minute=int(_num("HAUNTLET_EXORCIST_PER_MINUTE", 6)),
        retention_secs=_num("HAUNTLET_EXORCIST_RETENTION_SECS", 3600.0),
        demo_rooms=tuple(r.strip() for r in rooms.split(",") if r.strip()),
    )


def _mount_exorcist(app: FastAPI, service: RangeService) -> None:
    """D16 and its amendment: the hosted Exorcist routes, built beside RangeService."""
    from hauntlet.exorcist.delta import AfterRunRejected
    from hauntlet.exorcist.eligibility import NotFinal
    from hauntlet.exorcist.hosted import HostedExorcist, NotFound, Overloaded
    from hauntlet.exorcist.paths import exorcist_root
    from hauntlet.exorcist.service import DemoUnsupported, ExorcistService

    db = os.environ.get("HAUNTLET_DB", ".hauntlet/range.db")
    caps = _exorcist_caps()
    ex = HostedExorcist(
        ExorcistService(service, exorcist_root(Path(db)), reports_dir=None, clock=service.clock),
        caps,
        clock=service.clock,
    )
    app.state.exorcist = ex

    from hauntlet.scorecard import exorcism_file_renderer

    # D23: delta HTML files written by the hosted service are scorecard pages too.
    ex.service.html_renderer = exorcism_file_renderer(ex.service, db_path=Path(db))

    @app.get("/exorcist", response_class=HTMLResponse)
    def exorcist_page() -> str:
        # D23: the scorecard frame with one demo button per offered room.
        return render_launcher([r for r in caps.demo_rooms if ex.service.supports(r)])

    @app.post("/exorcist/demo")
    def exorcist_demo(body: _DemoRequest) -> dict:
        try:
            return ex.demo(body.room)
        except DemoUnsupported as exc:
            raise HTTPException(400, str(exc)) from None
        except Overloaded as exc:
            raise HTTPException(429, str(exc)) from None

    @app.post("/runs/{run_id}/exorcise")
    def exorcise(run_id: str) -> dict:
        _run_or_404_outer(service, run_id)
        try:
            return ex.exorcise(run_id)
        except NotFinal as exc:
            raise HTTPException(409, str(exc)) from None
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except Overloaded as exc:
            raise HTTPException(429, str(exc)) from None

    @app.get("/exorcisms/{bundle_id}/bundle")
    def exorcism_bundle(bundle_id: str) -> Response:
        try:
            data = ex.bundle_zip(bundle_id)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        return Response(
            data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="exorcism-{bundle_id}.zip"'},
        )

    @app.post("/exorcisms/{bundle_id}/after")
    def exorcism_after(bundle_id: str, body: _ExorciseAfter) -> dict:
        from hauntlet.core.service import UnknownRun

        try:
            ex.attach(bundle_id, body.run_id)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except UnknownRun:
            raise HTTPException(404, f"unknown after run {body.run_id!r}") from None
        except AfterRunRejected as exc:
            raise HTTPException(400, str(exc)) from None
        return {"report_url": f"/exorcisms/{bundle_id}/report"}

    @app.get("/exorcisms/{bundle_id}/report", response_class=HTMLResponse)
    def exorcism_report(bundle_id: str) -> str:
        # D23: the scorecard of the exorcism, rendered from the bundle's files.
        try:
            bundle_dir = ex.bundle_dir(bundle_id)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        return render_exorcism(
            ex.service, bundle_dir, served=True, db_path=Path(db),
            download_url=f"/exorcisms/{bundle_id}/bundle",
        )


def _run_or_404_outer(service: RangeService, run_id: str) -> None:
    from hauntlet.core.service import UnknownRun

    try:
        service.get_run(run_id)
    except UnknownRun:
        raise HTTPException(404, "unknown run") from None
