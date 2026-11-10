"""Fact logs stay readable after finalize for pages served by ``hauntlet serve`` (approved change D32).

- ``hauntlet mcp finalize`` (D19 copy) and ``hauntlet parlor finalize`` (D32
  copy, ``parlor-facts-<run>.jsonl``) tear the workspace down; afterwards
  ``GET /runs/{id}/report`` still shows the run's fact-log rows, and never "fact
  log not available";
- the served page and its stream hold no canary value, though the copied logs do;
- a symlinked Parlor fact log is not copied, and a failed copy keeps the workspace;
- the reports directory is read only through the scorecard's checks: no route
  serves a file from it.

**Validates: scorecard Requirements 8.3, 8.9, 10.1–10.3, D32**
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_scorecard_redaction import leaks

from hauntlet import cli
from hauntlet.agents import get_agent
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.core.toolbox import ToolBox
from hauntlet.paths import reports_parlor_facts_path, scratch_root_beside
from hauntlet.rooms import default_rooms
from hauntlet.rooms.parlor import factlog as parlor_factlog
from hauntlet.server import create_app

BASE_URL = "http://127.0.0.1:8666"
NA = "fact log not available"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "range.db"
    Store(db)
    out = tmp_path / "reports"
    monkeypatch.setenv("HAUNTLET_DB", str(db))
    monkeypatch.setenv("HAUNTLET_BASE_URL", BASE_URL)
    monkeypatch.setenv("HAUNTLET_REPORTS_DIR", str(out))
    service = RangeService(Store(db), default_rooms(), base_url=BASE_URL, page_scratch_root=scratch_root_beside(db))
    return service, TestClient(create_app(service)), db, out


@pytest.mark.parametrize("room", cli.MCP_ROOMS)
def test_mcp_report_after_finalize_shows_the_log(env, room, capsys) -> None:
    service, client, db, out = env
    run_id = service.start_run([room]).run.run_id
    session = cli.prepare_mcp_serve(service, room, run_id, cli.mcp_scratch_root(db))
    tools = ToolBox(session.materials.workspace, session.materials.env, service.fetch_local, service.base_url)
    try:
        get_agent("naive").run(session.materials, tools)
    finally:
        cli.deregister(run_id, room)
    assert cli.main(["mcp", "finalize", f"--run={run_id}", "--out", str(out)]) == 0
    capsys.readouterr()
    assert not session.materials.workspace.exists()

    page = client.get(f"/runs/{run_id}/report").text
    assert NA not in page
    assert "Client called" in page and "MCP server changed the description of" in page
    canaries = service.canaries(run_id)
    copy_text = cli.mcp_facts_copy_path(out, run_id, room).read_text(encoding="utf-8")
    assert leaks(copy_text, canaries), "the copy holds canary values, so the check means something"
    assert not leaks(page, canaries)
    stream = client.get(f"/runs/{run_id}/facts/stream").text
    assert "Client called" in stream and not leaks(stream, canaries)


def _browsed_parlor_run(service: RangeService, client: TestClient, capsys) -> str:
    run_id = client.post("/runs", json={"rooms": ["parlor"], "ttl_seconds": 3600}).json()["run"]["run_id"]
    assert cli.main(["parlor", "open", f"--run={run_id}"]) == 0
    capsys.readouterr()
    cans = service.canaries(run_id)
    token = next(c.value for c in cans if c.kind == "page")
    secret = next(c.value for c in cans if c.kind == "secret" and c.trap_id == "sign-image")
    for q in ({"page": "lobby"}, {"page": "ledger"}, {"img": "sign"}):
        assert client.get(f"/c/{token}", params=q).status_code == 200
    client.get(f"/c/{token}", params={"do": "guestbook", "answer": "Agatha", "member_code": secret})
    return run_id


def test_parlor_report_after_finalize_shows_the_log(env, capsys) -> None:
    service, client, db, out = env
    run_id = _browsed_parlor_run(service, client, capsys)
    workspace = cli.mcp_workspace(scratch_root_beside(db), "parlor", run_id)
    log = parlor_factlog.facts_path(workspace)
    at_finalize = log.read_bytes()
    assert at_finalize
    assert cli.main(["parlor", "finalize", f"--run={run_id}", f"--out={out}"]) == 0
    capsys.readouterr()
    assert not workspace.exists()

    copy = reports_parlor_facts_path(out, run_id)
    assert copy == out / f"parlor-facts-{run_id}.jsonl" and copy.read_bytes() == at_finalize
    page = client.get(f"/runs/{run_id}/report").text
    assert NA not in page
    assert "Browser fetched page lobby" in page and "Browser submitted the form" in page
    canaries = service.canaries(run_id)
    assert leaks(copy.read_text(encoding="utf-8"), canaries)
    assert not leaks(page, canaries)


def test_symlinked_parlor_log_is_not_copied(env, tmp_path, capsys) -> None:
    service, client, db, out = env
    run_id = _browsed_parlor_run(service, client, capsys)
    workspace = cli.mcp_workspace(scratch_root_beside(db), "parlor", run_id)
    log = parlor_factlog.facts_path(workspace)
    elsewhere = tmp_path / "elsewhere.jsonl"
    elsewhere.write_bytes(log.read_bytes())
    log.unlink()
    log.symlink_to(elsewhere)
    assert cli.main(["parlor", "finalize", f"--run={run_id}", f"--out={out}"]) == 0
    capsys.readouterr()
    assert not reports_parlor_facts_path(out, run_id).exists()
    assert NA in client.get(f"/runs/{run_id}/report").text  # honest: nothing to read


def test_failed_parlor_copy_keeps_the_workspace(env, capsys, monkeypatch) -> None:
    service, client, db, out = env
    run_id = _browsed_parlor_run(service, client, capsys)
    workspace = cli.mcp_workspace(scratch_root_beside(db), "parlor", run_id)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(cli, "_copy_parlor_fact_log", boom)
    assert cli.main(["parlor", "finalize", f"--run={run_id}", f"--out={out}"]) == 1
    assert "workspace kept" in capsys.readouterr().err
    assert workspace.is_dir()


def test_no_route_serves_the_reports_dir(env, capsys) -> None:
    _service, client, _db, out = env
    out.mkdir(parents=True, exist_ok=True)
    (out / "secret.txt").write_text("x")
    for path in ("/reports/secret.txt", "/secret.txt", "/runs/secret.txt/report", "/c/..%2Freports%2Fsecret.txt"):
        assert client.get(path).status_code == 404, path


# --------------------------------------------------------------------------- #
# D32 follow-up: the hosted range reads the reports directory, never writes it
# --------------------------------------------------------------------------- #


def test_hosted_demos_write_nothing_to_the_reports_dir(env) -> None:
    _service, client, _db, out = env
    for room in ("cursed-repo", "poltergeist"):
        r = client.post("/exorcist/demo", json={"room": room})
        assert r.status_code == 200
        assert client.get(r.json()["report_url"]).status_code == 200
    assert not out.exists() or not any(out.iterdir()), sorted(p.name for p in out.iterdir())


@pytest.mark.parametrize("room", cli.MCP_ROOMS)
def test_hosted_attach_reads_the_d19_copy_and_writes_no_delta_there(env, room, capsys) -> None:
    import json

    service, client, db, out = env
    before = client.post("/runs", json={"rooms": [room], "grace_window_secs": 0}).json()["run"]["run_id"]
    assert client.post(f"/runs/{before}/finalize", json={"observations": []}).status_code == 200
    bundle_id = client.post(f"/runs/{before}/exorcise").json()["bundle_id"]

    after = client.post("/runs", json={"rooms": [room], "grace_window_secs": 0}).json()["run"]["run_id"]
    session = cli.prepare_mcp_serve(service, room, after, cli.mcp_scratch_root(db))
    tools = ToolBox(session.materials.workspace, session.materials.env, service.fetch_local, service.base_url)
    try:
        get_agent("naive").run(session.materials, tools)
    finally:
        cli.deregister(after, room)
    assert cli.main(["mcp", "finalize", f"--run={after}", "--out", str(out)]) == 0
    capsys.readouterr()
    assert cli.mcp_facts_copy_path(out, after, room).is_file() and not session.materials.workspace.exists()
    before_listing = sorted(p.name for p in out.iterdir())

    r = client.post(f"/exorcisms/{bundle_id}/after", json={"run_id": after})
    assert r.status_code == 200, r.text
    (delta_json,) = db.parent.glob(f"**/{bundle_id}/deltas/{after}.json")
    delta = json.loads(delta_json.read_text())
    (rd,) = delta["rooms"]
    assert rd["fact_log_available"] is True, "the hosted attach read the D19 copy"
    assert sorted(p.name for p in out.iterdir()) == before_listing, "nothing new in the reports dir"
    assert not list(out.glob("exorcist-delta-*.html"))
    # The before run was finalized without ever being served, so it honestly has
    # no fact log; the after run's evidence (read from the D19 copy) is shown.
    page = client.get(f"/exorcisms/{bundle_id}/report").text
    evidence = page.split('id="h-evidence"', 1)[1]
    before_part, after_part = evidence.split("After run", 1)
    assert NA in before_part and NA not in after_part
    assert "Client called" in after_part


def test_the_cli_still_writes_its_delta_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAUNTLET_DB", str(tmp_path / "db" / "range.db"))
    out = tmp_path / "reports"
    assert cli.main(["exorcist", "demo", "--room", "cursed-repo", "--out", str(out)]) == 0
    assert len(list(out.glob("exorcist-delta-*.html"))) == 1
