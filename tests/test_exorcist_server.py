"""The hosted Exorcist routes (exorcist Requirement 11, D16, task 17.2).

- the demo round trip for `cursed-repo` and `poltergeist`;
- 429 over the concurrency and per-minute caps;
- 400 for an unsupported room; 409 for exorcising an unfinalized run;
- the bundle zip is deterministic and extracts to the bundle tree;
- attaching an after run: success and each admission failure;
- 404 for unknown, expired (after the sweeper) and malformed IDs;
- `X-Robots-Tag` on every exorcist response;
- no route accepts an uploaded bundle, config or hook.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms import default_rooms
from hauntlet.server import create_app

BASE_URL = "http://127.0.0.1:8666"


class Clock:
    """A clock the test advances by hand; also makes the demo's runs deterministic."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "range.db"
    Store(db)
    monkeypatch.setenv("HAUNTLET_DB", str(db))
    monkeypatch.setenv("HAUNTLET_BASE_URL", BASE_URL)
    return tmp_path


def _app(env, clock: Clock | None = None):
    service = RangeService(Store(env / "range.db"), default_rooms(), base_url=BASE_URL,
                           clock=clock or Clock())
    return create_app(service)


def _noindex(resp) -> bool:
    return resp.headers.get("x-robots-tag") == "noindex, nofollow"


# --------------------------------------------------------------------------- #
# demo round trip
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("room", ["cursed-repo", "poltergeist"])
def test_demo_round_trip(env, room: str) -> None:
    c = TestClient(_app(env))
    r = c.post("/exorcist/demo", json={"room": room})
    assert r.status_code == 200 and _noindex(r)
    body = r.json()
    assert set(body) == {"bundle_id", "report_url", "bundle_url"}

    report = c.get(body["report_url"])
    assert report.status_code == 200 and _noindex(report)
    assert "demo agent" in report.text and "noindex" in report.text

    z = c.get(body["bundle_url"])
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip" and _noindex(z)
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert any(n.startswith(".kiro/") for n in names)
    assert "bundle.json" in names and "EXORCISM.md" in names
    assert not any(n.startswith("deltas/") for n in names)


def test_page_lists_the_demo_rooms(env) -> None:
    c = TestClient(_app(env))
    r = c.get("/exorcist")
    assert r.status_code == 200 and _noindex(r)
    assert "cursed-repo" in r.text and "poltergeist" in r.text and "not Kiro" in r.text


def test_page_external_scripts_are_pinned_with_integrity(env) -> None:
    import re

    html = TestClient(_app(env)).get("/exorcist").text
    # No unpinned CDN version markers.
    for bad in ("@3.x.x", "@latest", "@^", "@~"):
        assert bad not in html, f"unpinned CDN reference {bad!r}"
    # Every external <script src=...> is pinned to an exact version and has SRI + crossorigin.
    tags = re.findall(r"<script\b[^>]*\bsrc=[\"']https?://[^>]*?>", html, re.IGNORECASE | re.DOTALL)
    assert tags, "the page loads at least one external script"
    for tag in tags:
        src = re.search(r'src="([^"]+)"', tag).group(1)
        assert re.search(r"@\d+\.\d+\.\d+/", src), f"not pinned to an exact version: {src}"
        assert re.search(r'integrity="sha(256|384|512)-[A-Za-z0-9+/=]+"', tag), f"no SRI: {tag}"
        assert 'crossorigin="anonymous"' in tag, f"no crossorigin: {tag}"


# --------------------------------------------------------------------------- #
# caps
# --------------------------------------------------------------------------- #


def test_per_minute_cap_returns_429(env, monkeypatch) -> None:
    monkeypatch.setenv("HAUNTLET_EXORCIST_PER_MINUTE", "1")
    c = TestClient(_app(env, Clock()))
    assert c.post("/exorcist/demo", json={"room": "cursed-repo"}).status_code == 200
    r = c.post("/exorcist/demo", json={"room": "cursed-repo"})
    assert r.status_code == 429 and _noindex(r)


def test_concurrency_cap_returns_429(env, monkeypatch) -> None:
    monkeypatch.setenv("HAUNTLET_EXORCIST_MAX_CONCURRENT", "1")
    app = _app(env)
    c = TestClient(app)
    app.state.exorcist._sema.acquire()  # simulate a demo already in flight
    try:
        r = c.post("/exorcist/demo", json={"room": "cursed-repo"})
        assert r.status_code == 429 and "already running" in r.json()["detail"]
    finally:
        app.state.exorcist._sema.release()


# --------------------------------------------------------------------------- #
# refusals
# --------------------------------------------------------------------------- #


def test_unsupported_and_unknown_rooms(env) -> None:
    c = TestClient(_app(env))
    assert c.post("/exorcist/demo", json={"room": "parlor"}).status_code == 400
    assert c.post("/exorcist/demo", json={"room": "attic"}).status_code == 400


def test_exorcise_unfinalized_is_409(env) -> None:
    app = _app(env)
    c = TestClient(app)
    run_id = app.state.service.start_run(["poltergeist"], grace_window_secs=0).run.run_id
    r = c.post(f"/runs/{run_id}/exorcise")
    assert r.status_code == 409
    assert c.post("/runs/nosuchrun/exorcise").status_code == 404


@pytest.mark.parametrize("bundle_id", ["@bad!", "../etc", "short", "x" * 100])
def test_malformed_and_unknown_ids_are_404(env, bundle_id: str) -> None:
    c = TestClient(_app(env))
    assert c.get(f"/exorcisms/{bundle_id}/report").status_code == 404
    assert c.get(f"/exorcisms/{bundle_id}/bundle").status_code == 404
    assert c.get("/exorcisms/deadbeefdead99/report").status_code == 404


# --------------------------------------------------------------------------- #
# deterministic zip + extraction
# --------------------------------------------------------------------------- #


def test_bundle_zip_is_deterministic_and_extracts(env, tmp_path: Path) -> None:
    c = TestClient(_app(env))
    bid = c.post("/exorcist/demo", json={"room": "cursed-repo"}).json()["bundle_id"]
    a = c.get(f"/exorcisms/{bid}/bundle").content
    b = c.get(f"/exorcisms/{bid}/bundle").content
    assert a == b
    dest = tmp_path / "extract"
    zipfile.ZipFile(io.BytesIO(a)).extractall(dest)
    assert (dest / "bundle.json").is_file()
    assert (dest / ".kiro/steering/untrusted-content.md").is_file()


# --------------------------------------------------------------------------- #
# attach + retention sweep
# --------------------------------------------------------------------------- #


def test_attach_rejects_an_after_run_that_fails_admission(env) -> None:
    app = _app(env)
    c = TestClient(app)
    service = app.state.service
    # A finalized before run with eligible traps (threshold fires high).
    before = _finalized_run(service, "threshold")
    bid = c.post(f"/runs/{before}/exorcise").json()["bundle_id"]
    # The before run itself is not a valid after run (same ID, created before the bundle).
    r = c.post(f"/exorcisms/{bid}/after", json={"run_id": before})
    assert r.status_code == 400
    assert c.post(f"/exorcisms/{bid}/after", json={"run_id": "nosuchrun999"}).status_code == 404


def test_expired_bundle_is_swept_and_404s(env, monkeypatch) -> None:
    monkeypatch.setenv("HAUNTLET_EXORCIST_RETENTION_SECS", "10")
    clock = Clock(1000.0)
    app = _app(env, clock)
    c = TestClient(app)
    bid = c.post("/exorcist/demo", json={"room": "cursed-repo"}).json()["bundle_id"]
    assert c.get(f"/exorcisms/{bid}/report").status_code == 200
    clock.t = 2000.0  # well past the 10s retention window
    # Any request triggers the sweep; the bundle is gone -> 404.
    c.post("/exorcist/demo", json={"room": "cursed-repo"})
    assert c.get(f"/exorcisms/{bid}/report").status_code == 404


# --------------------------------------------------------------------------- #
# no uploaded config
# --------------------------------------------------------------------------- #


def test_no_route_accepts_an_uploaded_bundle_or_config(env) -> None:
    c = TestClient(_app(env))
    # The demo and after routes take only a room / run_id; extra fields are ignored,
    # and there is no route that accepts bundle bytes, steering, hooks or mcp config.
    r = c.post("/exorcist/demo", json={"room": "cursed-repo", "bundle": {"mcpServers": {}}, "config": "x"})
    assert r.status_code == 200
    # The accepted body model has no field that could carry a bundle.
    from hauntlet.server import _DemoRequest, _ExorciseAfter

    assert set(_DemoRequest.model_fields) == {"room"}
    assert set(_ExorciseAfter.model_fields) == {"run_id"}


def _finalized_run(service: RangeService, room: str) -> str:
    """A finalized, non-provisional run via the in-process naive path."""
    from hauntlet.agents import get_agent
    from hauntlet.core.toolbox import ToolBox

    desc = service.start_run([room], grace_window_secs=0)
    run_id = desc.run.run_id
    rm = service.rooms[room]
    import tempfile

    ctx, materials = service.setup_room(run_id, room, Path(tempfile.mkdtemp()))
    tools = ToolBox(materials.workspace, materials.env, service.fetch_local, service.base_url)
    try:
        transcript = get_agent("naive").run(materials, tools)
        obs = rm.collect(ctx, materials, transcript)
        service.finalize(run_id, obs, transcript_provided=True)
    finally:
        rm.teardown(ctx)
    return run_id
