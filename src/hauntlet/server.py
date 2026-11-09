"""HTTP surface for the range. A thin wrapper over RangeService."""

from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from hauntlet import __version__
from hauntlet.core.models import to_dict
from hauntlet.core.report import render_report
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
        _run_or_404(run_id)
        return render_report(service.score(run_id), service.manifest(run_id))

    _mount_exorcist(app, service)
    return app


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

    _PAGE = (files("hauntlet.exorcist") / "static" / "exorcist.html").read_text(encoding="utf-8")

    @app.get("/exorcist", response_class=HTMLResponse)
    def exorcist_page() -> str:
        rooms = json.dumps([r for r in caps.demo_rooms if ex.service.supports(r)])
        inject = f'<body x-data="exorcist()"><script>window.__DEMO_ROOMS__ = {rooms};</script>'
        return _PAGE.replace('<body x-data="exorcist()">', inject, 1)

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
        try:
            return ex.report_html(bundle_id)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None


def _run_or_404_outer(service: RangeService, run_id: str) -> None:
    from hauntlet.core.service import UnknownRun

    try:
        service.get_run(run_id)
    except UnknownRun:
        raise HTTPException(404, "unknown run") from None
