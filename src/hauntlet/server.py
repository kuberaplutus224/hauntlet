"""HTTP surface for the range. A thin wrapper over RangeService."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field, field_validator

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


#: D33 request caps. Over a cap is refused (413 or 422), never truncated.
MAX_BODY_BYTES = 64 * 1024
MAX_DETAIL_CHARS = 4096
MAX_OBSERVATIONS = 500


class StartRun(BaseModel):
    rooms: list[str] = Field(default_factory=lambda: ["threshold"])
    ttl_seconds: float | None = Field(default=None, gt=0, le=24 * 3600)
    grace_window_secs: float = Field(default=30.0, ge=0, le=300)

    @field_validator("rooms")
    @classmethod
    def _one_of_each(cls, rooms: list[str]) -> list[str]:
        # D33: at most one of each room; unknown rooms are refused later (400).
        if len(set(rooms)) != len(rooms):
            raise ValueError("each room may appear at most once")
        return rooms


class ObservationIn(BaseModel):
    room: str
    trap_id: str
    channel: str
    signal: str
    detail: str = Field(default="", max_length=MAX_DETAIL_CHARS)


class Finalize(BaseModel):
    observations: list[ObservationIn] = Field(default_factory=list, max_length=MAX_OBSERVATIONS)
    transcript_provided: bool = False


def _log_client_key(request: Request, key: str) -> None:
    """D34 check (``HAUNTLET_LOG_CLIENT_KEY=1``, off by default): one line per request.

    It shows the derived key, how many ``X-Forwarded-For`` entries arrived, and
    whether ``CF-Connecting-IP`` / ``True-Client-IP`` are present. Their values are
    never logged, beyond what the key itself is.
    """
    import logging

    from hauntlet.limits import forwarded_entries

    log = logging.getLogger("hauntlet.client_key")
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("hauntlet client key: %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    h = request.headers
    log.info(
        "key=%s xff_entries=%d cf_connecting_ip=%s true_client_ip=%s %s %s",
        key, len(forwarded_entries(h)),
        "present" if "cf-connecting-ip" in h else "absent",
        "present" if "true-client-ip" in h else "absent",
        request.method, request.url.path,
    )


def _flag(name: str) -> bool:
    return os.environ.get(name, "") == "1"


def _env_num(name: str, default, cast=float):
    try:
        v = cast(os.environ[name])
    except (KeyError, ValueError):
        return default
    return v if v > 0 else default


def _base_url() -> str:
    """``HAUNTLET_BASE_URL``, else Render's ``RENDER_EXTERNAL_URL``, else local. Empty means unset."""
    return (
        os.environ.get("HAUNTLET_BASE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or "http://127.0.0.1:8666"
    ).rstrip("/")


class _BodyLimit:
    """ASGI: refuse a request body over ``limit`` bytes with 413 (D33).

    Checks ``Content-Length`` first, then counts the bytes actually received, so a
    chunked body cannot get around it. The body is buffered (at most ``limit``) and
    replayed to the app.
    """

    def __init__(self, app, limit: int) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers", ()):
            if k == b"content-length":
                try:
                    if int(v) > self.limit:
                        return await _too_large(scope, receive, send)
                except ValueError:
                    return await _too_large(scope, receive, send)
        chunks, size, more = [], 0, True
        while more:
            msg = await receive()
            if msg["type"] != "http.request":
                return await self.app(scope, _replay([msg]), send)
            chunk = msg.get("body", b"")
            size += len(chunk)
            if size > self.limit:
                return await _too_large(scope, receive, send)
            chunks.append(chunk)
            more = msg.get("more_body", False)
        return await self.app(scope, _replay([{"type": "http.request", "body": b"".join(chunks), "more_body": False}], receive), send)


def _replay(messages, then=None):
    queue = list(messages)

    async def receive():
        if queue:
            return queue.pop(0)
        if then is not None:
            return await then()
        return {"type": "http.disconnect"}

    return receive


async def _too_large(scope, receive, send):
    resp = PlainTextResponse(f"request body over {MAX_BODY_BYTES} bytes", status_code=413)
    await resp(scope, receive, send)


#: D35 headers on every response. No ``script-src`` yet: the scorecard inlines its
#: script and uses Alpine's standard build, which evaluates expressions, so a
#: script policy needs hashes and the Alpine CSP build first (design, D35).
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
BASE_CSP = "frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"


def _db_path() -> Path:
    return Path(os.environ.get("HAUNTLET_DB", ".hauntlet/range.db"))


def _reports_dir() -> Path:
    """D32: where finalize keeps fact-log copies (the CLI's ``--out`` default).

    Read by the scorecard only, through ``sources``' checks (no symlinks, under
    this directory). No route serves a file from it."""
    from hauntlet.paths import DEFAULT_REPORTS_DIR

    return Path(os.environ.get("HAUNTLET_REPORTS_DIR", DEFAULT_REPORTS_DIR))


def create_app(service: RangeService | None = None) -> FastAPI:
    if service is None:
        db = os.environ.get("HAUNTLET_DB", ".hauntlet/range.db")
        service = RangeService(
            Store(db),
            default_rooms(),
            base_url=_base_url(),
            # D11: serve page-room workspaces that another process (for example
            # `hauntlet parlor open`) set up beside the shared store.
            page_scratch_root=scratch_root_beside(Path(db)),
        )
    from hauntlet.limits import RunCap, Window, client_key

    hosted = _flag("HAUNTLET_HOSTED")
    trust_proxy = _flag("HAUNTLET_TRUST_PROXY")
    # D35: no API docs on the hosted range.
    docs = {} if not hosted else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="Hauntlet", version=__version__, **docs)
    app.state.service = service
    app.state.hosted = hosted
    app.add_middleware(_BodyLimit, limit=MAX_BODY_BYTES)

    ip_header = os.environ.get("HAUNTLET_CLIENT_IP_HEADER", "").strip() or None
    log_keys = _flag("HAUNTLET_LOG_CLIENT_KEY")

    def key_of(request: Request) -> str:
        return client_key(
            request.headers, request.client.host if request.client else None, trust_proxy, ip_header,
        )

    app.state.client_key = key_of

    @app.middleware("http")
    async def noindex(request: Request, call_next):
        if log_keys:
            _log_client_key(request, key_of(request))
        response = await call_next(request)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        for k, v in SECURITY_HEADERS.items():
            response.headers[k] = v
        # A page that sets a stricter policy of its own (Parlor) keeps it.
        response.headers.setdefault("Content-Security-Policy", BASE_CSP)
        return response

    # D33 (hosted): cap unfinished runs and sweep old ones; D34: runs per client per hour.
    def _open(run_id: str) -> bool:
        run = service.store.get_run(run_id)
        return run is not None and run.finalized_at is None and run.is_active(service.clock())

    run_cap = RunCap(int(_env_num("HAUNTLET_MAX_OPEN_RUNS", 50, int)), _open)
    run_quota = Window(int(_env_num("HAUNTLET_RUNS_PER_HOUR", 10, int)), 3600.0, service.clock)
    retention = _env_num("HAUNTLET_RUN_RETENTION_SECS", 86400.0)
    last_sweep = [float("-inf")]

    def sweep_runs() -> int:
        """Lazy, at most once a minute: delete runs whose window closed over ``retention`` ago."""
        now = service.clock()
        if now - last_sweep[0] < 60:
            return 0
        last_sweep[0] = now
        return service.store.delete_closed_before(now - retention)

    app.state.sweep_runs = sweep_runs
    app.state.run_cap = run_cap

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
    def start_run(body: StartRun, request: Request) -> dict:
        if hosted:
            sweep_runs()
            if not run_quota.hit(key_of(request)):
                raise HTTPException(429, "too many runs from this client; try again later")
        created: list = []

        def create() -> str:
            desc = service.start_run(body.rooms, ttl=body.ttl_seconds, grace_window_secs=body.grace_window_secs)
            created.append(desc)
            return desc.run.run_id

        try:
            if hosted:
                if run_cap.admit(create) is None:
                    raise HTTPException(429, "too many unfinished runs on this range; try again later")
            else:
                create()
        except KeyError as exc:
            raise HTTPException(400, str(exc)) from None
        desc = created[0]
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
                reports_dir=_reports_dir(),
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

    from hauntlet.limits import Slots

    max_streams, poll = _stream_caps()
    slots = threading.BoundedSemaphore(max_streams)
    # D34: per client, at most this many open streams (hosted); every stream closes
    # after ``max_secs`` (the browser reconnects with Last-Event-ID while the run is active).
    per_client = Slots(int(_env_num("HAUNTLET_STREAMS_PER_CLIENT", 2, int)))
    max_secs = _env_num("HAUNTLET_STREAM_MAX_SECS", 600.0)
    db = Path(os.environ.get("HAUNTLET_DB", ".hauntlet/range.db"))
    app.state.stream_slots = slots
    app.state.stream_per_client = per_client

    @app.get("/runs/{run_id}/facts/stream")
    async def facts_stream_route(run_id: str, request: Request):
        try:
            check_run_id(run_id)
            service.get_run(run_id)
        except UnknownRun:
            raise HTTPException(404, "unknown run") from None
        key = app.state.client_key(request)
        hosted = app.state.hosted
        if hosted and not per_client.take(key):
            return PlainTextResponse("too many live streams from this client", status_code=429)
        if not slots.acquire(blocking=False):
            if hosted:
                per_client.give(key)
            return PlainTextResponse("too many live streams; try again shortly", status_code=429)

        released = threading.Event()

        def release() -> None:
            # Idempotent: runs from the body's finally and as a background task, so a
            # client that leaves before the body starts still frees its slot.
            if not released.is_set():
                released.set()
                slots.release()
                if hosted:
                    per_client.give(key)

        async def body():
            try:
                async for chunk in facts_stream(
                    service, run_id, db_path=db, reports_dir=_reports_dir(), poll_secs=poll, max_secs=max_secs,
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
        # D32 follow-up: read the fact-log copies from the reports directory, never
        # write there (the retention sweep covers only the exorcist root).
        ExorcistService(
            service, exorcist_root(Path(db)), reports_dir=_reports_dir(), clock=service.clock,
            write_reports=False,
        ),
        caps,
        clock=service.clock,
    )
    app.state.exorcist = ex

    from hauntlet.scorecard import exorcism_file_renderer

    # D23: delta HTML files written by the hosted service are scorecard pages too.
    ex.service.html_renderer = exorcism_file_renderer(ex.service, db_path=Path(db), reports_dir=_reports_dir())

    @app.get("/exorcist", response_class=HTMLResponse)
    def exorcist_page() -> str:
        # D23: the scorecard frame with one demo button per offered room.
        return render_launcher([r for r in caps.demo_rooms if ex.service.supports(r)])

    from hauntlet.limits import Window

    demo_quota = Window(int(_env_num("HAUNTLET_DEMOS_PER_MINUTE_PER_CLIENT", 3, int)), 60.0, service.clock)

    @app.post("/exorcist/demo")
    def exorcist_demo(body: _DemoRequest, request: Request) -> dict:
        # D34 (hosted): a per-client quota under the global one, so one client cannot
        # spend everyone's demos.
        if app.state.hosted and not demo_quota.hit(app.state.client_key(request)):
            raise HTTPException(429, "too many demos from this client; try again in a minute")
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
            ex.service, bundle_dir, served=True, db_path=Path(db), reports_dir=_reports_dir(),
            download_url=f"/exorcisms/{bundle_id}/bundle",
        )


def _run_or_404_outer(service: RangeService, run_id: str) -> None:
    from hauntlet.core.service import UnknownRun

    try:
        service.get_run(run_id)
    except UnknownRun:
        raise HTTPException(404, "unknown run") from None
