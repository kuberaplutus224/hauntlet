"""``hauntlet mcp serve`` (approved change D1, task 12.1).

Refusals (Requirement 8.3, 7.6) run in-process through ``cli.main``; the
stdio checks spawn the command as a real subprocess and speak raw JSON-RPC
lines, so they rely on no client-side SDK API. The full SDK-driven real-client
exchange and finalize are task 12.3.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hauntlet import cli
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms import default_rooms
from hauntlet.rooms.poltergeist import factlog

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8666"


def _service(db: Path) -> RangeService:
    return RangeService(Store(db), default_rooms(), base_url=BASE_URL)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "range.db"
    Store(path)  # create the shared store file, as `hauntlet serve` would
    monkeypatch.setenv("HAUNTLET_DB", str(path))
    monkeypatch.setenv("HAUNTLET_BASE_URL", BASE_URL)
    return path


def _scratch(db: Path) -> Path:
    return cli.mcp_scratch_root(db)


@pytest.fixture(autouse=True)
def _short_takeover_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process refusals wait for a lock held by a live session; keep it short.
    Subprocess tests run the real ``TAKEOVER_WAIT_SECS``."""
    monkeypatch.setattr(cli, "TAKEOVER_WAIT_SECS", 0.3)


def test_takeover_rules_in_process(db: Path) -> None:
    """A live session's lock blocks takeover; once released, a handshake-only
    workspace is taken over, and one that listed tools is refused."""
    service = _service(db)
    run_id = service.start_run(["poltergeist-legacy"]).run.run_id
    root = _scratch(db)
    first = cli.prepare_mcp_serve(service, "poltergeist-legacy", run_id, root)
    ws = first.materials.workspace
    try:
        assert cli.mcp_lock_path(ws).is_file()
        with pytest.raises(cli.McpRefused, match="still serving"):
            cli.prepare_mcp_serve(service, "poltergeist-legacy", run_id, root)
        first.release()  # the probe process exits

        second = cli.prepare_mcp_serve(service, "poltergeist-legacy", run_id, root)
        assert second.took_over
        facts = factlog.read(factlog.facts_path(ws), run_id)
        assert [f.kind for f in facts] == ["takeover"]
        assert facts[0].previous == "" and facts[0].count == 0  # the probe wrote no fact

        # This session lists tools; after it exits, nothing may replace it.
        second.server._record(factlog.ListFact, after_mutation=False,
                              desc_versions={"get_note": "pre", "check_health": "pre"})
        second.release()
        with pytest.raises(cli.McpRefused, match="already listed or called tools"):
            cli.prepare_mcp_serve(service, "poltergeist-legacy", run_id, root)
        assert [f.kind for f in factlog.read(factlog.facts_path(ws), run_id)] == ["takeover", "list"]
    finally:
        cli.deregister(run_id, "poltergeist-legacy")


# --------------------------------------------------------------------------- #
# refusals: exit non-zero, nothing on stdout, nothing set up
# --------------------------------------------------------------------------- #


def _assert_refused(argv: list[str], db: Path, capsys: pytest.CaptureFixture[str], why: str) -> None:
    rc = cli.main(argv)
    out, err = capsys.readouterr()
    assert rc != 0
    assert out == ""
    assert "refused, serving nothing" in err and why in err
    root = _scratch(db)
    assert not root.exists() or not any(root.iterdir())


def test_unknown_run_is_refused(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _assert_refused(["mcp", "serve", "--room", "poltergeist", "--run=nope"], db, capsys, "unknown run")


def test_finalized_run_is_refused(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    service = _service(db)
    run_id = service.start_run(["poltergeist"]).run.run_id
    service.finalize(run_id, [], transcript_provided=False)
    _assert_refused(["mcp", "serve", "--room", "poltergeist", f"--run={run_id}"], db, capsys, "finalized")


def test_expired_run_is_refused(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_id = _service(db).start_run(["poltergeist-legacy"], ttl=0.0).run.run_id
    _assert_refused(["mcp", "serve", "--room", "poltergeist-legacy", f"--run={run_id}"], db, capsys, "expired")


def test_run_without_the_room_is_refused(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_id = _service(db).start_run(["poltergeist"]).run.run_id
    _assert_refused(
        ["mcp", "serve", "--room", "poltergeist-legacy", f"--run={run_id}"], db, capsys, "does not include"
    )


@pytest.mark.parametrize("run_id", ["../x", "a/b", "", "x y", "..", "a\\b"])
def test_path_like_run_id_is_refused(db: Path, capsys: pytest.CaptureFixture[str], run_id: str) -> None:
    _assert_refused(["mcp", "serve", "--room", "poltergeist", f"--run={run_id}"], db, capsys, "invalid run ID")


def test_missing_store_is_refused_and_not_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nowhere" / "range.db"
    monkeypatch.setenv("HAUNTLET_DB", str(missing))
    rc = cli.main(["mcp", "serve", "--room", "poltergeist", "--run=abc"])
    out, err = capsys.readouterr()
    assert rc != 0 and out == "" and "no event store" in err
    assert not missing.exists() and not missing.parent.exists()


def test_non_mcp_room_is_rejected_by_the_parser(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["mcp", "serve", "--room", "threshold", "--run=abc"])
    assert exc.value.code != 0
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------- #
# setup: deterministic workspace, real-client I/O bound, one session per room
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("room", cli.MCP_ROOMS)
def test_prepare_sets_up_a_run_and_room_derived_workspace(db: Path, room: str) -> None:
    service = _service(db)
    run_id = service.start_run([room]).run.run_id
    root = _scratch(db)
    session = cli.prepare_mcp_serve(service, room, run_id, root)
    try:
        assert session.materials.workspace == cli.mcp_workspace(root, room, run_id)
        assert session.materials.workspace == root / f"{room}-{run_id}"
        assert session.materials.workspace.is_dir()
        assert session.materials.task == session.room.config.task
        # The relay is bound to the real-client fetcher: an off-range URL is refused.
        with pytest.raises(PermissionError):
            session.server._fetch("http://example.invalid/c/token")
        with pytest.raises(PermissionError):
            session.server._write("../escape.txt", "x")
        # A second session for the same run and room is refused; the first workspace stays.
        with pytest.raises(cli.McpRefused, match="already has"):
            cli.prepare_mcp_serve(service, room, run_id, root)
        assert session.materials.workspace.is_dir()
    finally:
        cli.deregister(run_id, room)


def test_workspace_root_does_not_depend_on_the_working_directory(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = cli.mcp_scratch_root(db)
    monkeypatch.chdir(tmp_path.parent)
    assert cli.mcp_scratch_root(db) == before == db.resolve().parent / cli.MCP_SCRATCH_DIRNAME


# --------------------------------------------------------------------------- #
# stdio subprocess: stdout carries only protocol frames; workspace survives EOF
# --------------------------------------------------------------------------- #


def _spawn(db: Path, room: str, run_id: str) -> subprocess.Popen[str]:
    env = {**os.environ, "HAUNTLET_DB": str(db), "HAUNTLET_BASE_URL": BASE_URL}
    return subprocess.Popen(
        [sys.executable, "-m", "hauntlet.cli", "mcp", "serve", "--room", room, f"--run={run_id}"],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _send(proc: subprocess.Popen[str], msg: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def _read_until_id(proc: subprocess.Popen[str], msg_id: int, frames: list[dict]) -> dict:
    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        assert line, "server closed stdout before answering"
        frame = json.loads(line)  # every stdout line must be a JSON-RPC frame
        assert frame.get("jsonrpc") == "2.0"
        frames.append(frame)
        if frame.get("id") == msg_id:
            return frame


@pytest.mark.parametrize("version", ["2025-06-18", "2025-11-25"])
def test_legacy_stdio_session_serves_only_frames_and_keeps_the_workspace(db: Path, version: str) -> None:
    service = _service(db)
    run_id = service.start_run(["poltergeist-legacy"]).run.run_id
    proc = _spawn(db, "poltergeist-legacy", run_id)
    frames: list[dict] = []
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {},
                       "clientInfo": {"name": "raw-test", "version": "0"}},
        })
        init = _read_until_id(proc, 1, frames)
        assert init["result"]["protocolVersion"] == version
        assert init["result"]["capabilities"]["tools"]["listChanged"] is True
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = _read_until_id(proc, 2, frames)
        assert {t["name"] for t in listed["result"]["tools"]} >= {"list_topics", "get_note"}
        _send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "list_topics", "arguments": {}}})
        _read_until_id(proc, 3, frames)
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
        proc.stdin.close()  # client disconnects
        proc.wait(timeout=30)
        rest, err = proc.stdout.read(), proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    for line in rest.splitlines():
        frames.append(json.loads(line))
    assert proc.returncode == 0, err
    assert any(f.get("method") == "notifications/tools/list_changed" for f in frames)
    assert "list_topics" in err and "mascot" in err  # task text went to stderr

    ws = cli.mcp_workspace(cli.mcp_scratch_root(db), "poltergeist-legacy", run_id)
    assert ws.is_dir(), "workspace must survive the disconnect for finalize"
    kinds = [f.kind for f in factlog.read(factlog.facts_path(ws), run_id)]
    assert kinds[:2] == ["negotiated", "list"] and "mutation" in kinds
    assert service.get_run(run_id).finalized_at is None  # serve never finalizes


def test_modern_room_serves_and_exits_cleanly_on_disconnect(db: Path) -> None:
    run_id = _service(db).start_run(["poltergeist"]).run.run_id
    proc = _spawn(db, "poltergeist", run_id)
    out, err = proc.communicate(input="", timeout=30)
    assert proc.returncode == 0, err
    assert out == ""
    assert "mascot" in err
    assert cli.mcp_workspace(cli.mcp_scratch_root(db), "poltergeist", run_id).is_dir()


def test_serving_stops_when_the_run_expires(db: Path) -> None:
    run_id = _service(db).start_run(["poltergeist-legacy"], ttl=3.0).run.run_id
    proc = _spawn(db, "poltergeist-legacy", run_id)
    started = time.monotonic()
    try:
        # Keep stdin open: only the expiry check can end this session.
        assert proc.wait(timeout=30) == cli.EXIT_RUN_INACTIVE
    finally:
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate()
    assert time.monotonic() - started < 30
    assert out == ""
    assert "no longer active" in err


# --------------------------------------------------------------------------- #
# concurrent serve for the same run and room (task 12.5)
# --------------------------------------------------------------------------- #


def test_concurrent_prepare_yields_one_session_and_one_refusal(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic: both callers are held at ``room.setup`` until both arrive.

    Without an atomic claim both pass the ``exists`` check and race into setup
    (the loser crashes with ``FileExistsError``, or both serve). With it, the
    loser is refused before setup and the holder is released when it finishes.
    """
    import threading

    from hauntlet.rooms.poltergeist.room import PoltergeistRoom

    service = _service(db)
    run_id = service.start_run(["poltergeist"]).run.run_id
    root = _scratch(db)
    cond = threading.Condition()
    in_setup = 0
    finished = 0
    real_setup = PoltergeistRoom.setup

    def held_setup(self, ctx):  # type: ignore[no-untyped-def]
        nonlocal in_setup
        with cond:
            in_setup += 1
            cond.notify_all()
            # Widen the window: wait for the other caller to reach setup too,
            # or to finish without reaching it.
            cond.wait_for(lambda: in_setup + finished >= 2, timeout=5)
        return real_setup(self, ctx)

    monkeypatch.setattr(PoltergeistRoom, "setup", held_setup)
    results: list[object] = []

    def worker() -> None:
        nonlocal finished
        try:
            results.append(cli.prepare_mcp_serve(service, "poltergeist", run_id, root))
        except BaseException as exc:  # noqa: BLE001 - every outcome is asserted below
            results.append(exc)
        finally:
            with cond:
                finished += 1
                cond.notify_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not any(t.is_alive() for t in threads)
        sessions = [r for r in results if isinstance(r, cli.McpSession)]
        refusals = [r for r in results if isinstance(r, cli.McpRefused)]
        assert len(results) == 2
        assert len(sessions) == 1 and len(refusals) == 1, results
        assert "already has" in str(refusals[0])
        # The loser left the winner's workspace and server alone.
        ws = cli.mcp_workspace(root, "poltergeist", run_id)
        assert sessions[0].materials.workspace == ws and ws.is_dir()
        assert sessions[0].server is cli.server_for(sessions[0].materials)
        assert not cli.mcp_claim_path(root, "poltergeist", run_id).exists()
        # A later session is still refused by the existing workspace.
        with pytest.raises(cli.McpRefused, match="already has"):
            cli.prepare_mcp_serve(service, "poltergeist", run_id, root)
    finally:
        cli.deregister(run_id, "poltergeist")


def _init_frames(version: str = "2025-06-18") -> str:
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": version, "capabilities": {},
                    "clientInfo": {"name": "race-test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    return "".join(json.dumps(m) + "\n" for m in msgs)


def _session_frames(version: str = "2025-06-18") -> str:
    """A real session: the handshake and then a ``tools/list``.

    The listing matters: a session that never gets past the handshake may be
    replaced by a later one (``prepare_mcp_serve`` takeover), so only a session
    that listed tools must refuse every other.
    """
    listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    return _init_frames(version) + json.dumps(listing) + "\n"


@pytest.mark.parametrize("trial", range(4))
def test_two_serve_processes_started_together_one_serves_one_is_refused(db: Path, trial: int) -> None:
    room = "poltergeist-legacy"
    run_id = _service(db).start_run([room]).run.run_id
    procs = [_spawn(db, room, run_id), _spawn(db, room, run_id)]
    outcomes: list[tuple[int, str, str]] = []
    try:
        for proc in procs:
            # communicate() ignores the broken pipe if the loser already exited.
            out, err = proc.communicate(input=_session_frames(), timeout=30)
            outcomes.append((proc.returncode, out, err))
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    winners = [o for o in outcomes if o[0] == 0]
    losers = [o for o in outcomes if o[0] != 0]
    assert len(winners) == 1 and len(losers) == 1, outcomes
    rc, out, err = losers[0]
    assert rc == 1
    assert out == ""
    assert "refused, serving nothing" in err and "already has" in err
    assert "Traceback" not in err and "FileExistsError" not in err

    _, w_out, w_err = winners[0]
    assert "Traceback" not in w_err
    frames = [json.loads(line) for line in w_out.splitlines()]
    assert any(f.get("id") == 1 and "result" in f for f in frames), w_out
    ws = cli.mcp_workspace(_scratch(db), room, run_id)
    assert ws.is_dir(), "the loser must not tear down the winner's workspace"
    kinds = [f.kind for f in factlog.read(factlog.facts_path(ws), run_id)]
    assert kinds.count("negotiated") == 1  # a single writer of the fact log
    assert "list" in kinds and "takeover" not in kinds
    assert not cli.mcp_claim_path(_scratch(db), room, run_id).exists()
