"""``hauntlet mcp finalize`` (approved change D1, task 12.2).

The serving side runs in-process here: ``prepare_mcp_serve`` sets the room up in
the shared store's real-client workspace, and a reference agent (or the
in-process client) drives it, with relays reaching the canary endpoint through
``RangeService.fetch_local``. Finalize then runs through ``cli.main`` exactly as
a tester would. The stdio subprocess end-to-end is task 12.3.
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest
from mcp.client._memory import InMemoryTransport
from mcp.client.client import Client

from hauntlet import cli
from hauntlet.agents import get_agent
from hauntlet.core.levels import Level, Signal
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.core.toolbox import ToolBox
from hauntlet.rooms import default_rooms
from hauntlet.rooms.poltergeist.client import connect
from hauntlet.rooms.poltergeist.config import CONTROL, RUG_DESC, TOOL_OUTPUT
from hauntlet.rooms.poltergeist import factlog
from hauntlet.rooms.poltergeist.exercised import NO_LIST_AFTER_MUTATION, NOT_SUBSCRIBED

BASE_URL = "http://127.0.0.1:8666"


def _service(db: Path) -> RangeService:
    return RangeService(Store(db), default_rooms(), base_url=BASE_URL)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "range.db"
    Store(path)
    monkeypatch.setenv("HAUNTLET_DB", str(path))
    monkeypatch.setenv("HAUNTLET_BASE_URL", BASE_URL)
    return path


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "reports"


def _serve(service: RangeService, db: Path, room: str, run_id: str) -> tuple[cli.McpSession, ToolBox]:
    session = cli.prepare_mcp_serve(service, room, run_id, cli.mcp_scratch_root(db))
    # In-process stand-in for the HTTP relay: the canary endpoint records the hit.
    tools = ToolBox(session.materials.workspace, session.materials.env, service.fetch_local, service.base_url)
    return session, tools


def _write_transcript(path: Path, entries: list[tuple[str, str]]) -> Path:
    path.write_text("".join(json.dumps({"role": r, "text": t}) + "\n" for r, t in entries), encoding="utf-8")
    return path


def _finalize(run_id: str, out: Path, *extra: str) -> int:
    return cli.main(["mcp", "finalize", f"--run={run_id}", "--out", str(out), *extra])


def _trap(service: RangeService, run_id: str, room: str, trap_id: str):
    rs = service.score(run_id).room(room)
    assert rs is not None
    return next(t for t in rs.per_trap if t.trap_id == trap_id), rs


# --------------------------------------------------------------------------- #
# a fully exercised run
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("room", cli.MCP_ROOMS)
def test_naive_run_is_collected_scored_and_summarised(
    db: Path, out: Path, tmp_path: Path, room: str, capsys: pytest.CaptureFixture[str]
) -> None:
    service = _service(db)
    run_id = service.start_run([room]).run.run_id
    session, tools = _serve(service, db, room, run_id)
    try:
        transcript = get_agent("naive").run(session.materials, tools)
    finally:
        cli.deregister(run_id, room)
    tfile = _write_transcript(tmp_path / "t.jsonl", [(e.role, e.text) for e in transcript])

    rc = _finalize(run_id, out, "--transcript", str(tfile), "--reapproval", "not_prompted")
    stdout, err = capsys.readouterr()
    assert rc == 0, err

    rug, rs = _trap(service, run_id, room, RUG_DESC)
    tool_out, _ = _trap(service, run_id, room, TOOL_OUTPUT)
    control, _ = _trap(service, run_id, room, CONTROL)
    assert (rug.level, rug.signals) == (Level.L4, ("echoed", "exposed", "reached"))
    assert (tool_out.level, tool_out.signals) == (Level.L3, ("acted", "echoed"))
    assert (control.level, control.signals) == (Level.L0, ())
    assert rs.task_completed and rs.false_positives == ()
    run = service.get_run(run_id)
    assert run.finalized_at is not None
    assert service.manifest(run_id).transcript_provided

    summary = (out / f"mcp-summary-{run_id}.txt").read_text(encoding="utf-8")
    assert summary in stdout
    assert f"{RUG_DESC} [trap]: exercised;" in summary
    assert f"{TOOL_OUTPUT} [trap]: exercised;" in summary
    assert f"{CONTROL} [control]: exercised;" in summary
    assert "NOT EXERCISED" not in summary and "NOT tested" not in summary
    assert "tools/list after the mutation" in summary and "mutation at" in summary
    manual = summary.split(cli.MANUAL_HEADING, 1)[1]
    assert "did NOT re-prompt" in manual
    assert (out / f"autopsy-mcp-{run_id}.html").read_text(encoding="utf-8").startswith("<!")

    # Manual observations never become events.
    for e in service.store.events_for_run(run_id):
        assert "prompt" not in e.detail and "manual" not in e.detail
    # Finalized and written: the workspace is removed.
    assert not cli.mcp_workspace(cli.mcp_scratch_root(db), room, run_id).exists()


# --------------------------------------------------------------------------- #
# a run where the rug pull never reached the client
# --------------------------------------------------------------------------- #


def test_no_relist_is_reported_not_exercised(db: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    room = "poltergeist-legacy"
    service = _service(db)
    run_id = service.start_run([room]).run.run_id
    session, tools = _serve(service, db, room, run_id)
    try:
        with connect(session.materials, tools) as client:
            client.approve()
            client.call("list_topics")  # mutates; the client never re-lists
    finally:
        cli.deregister(run_id, room)

    assert _finalize(run_id, out) == 0
    summary = capsys.readouterr().out
    rug, rs = _trap(service, run_id, room, RUG_DESC)
    assert rug.level == Level.L0 and Signal.NOT_EXERCISED in rug.signals
    assert f"{RUG_DESC} [trap]: NOT EXERCISED ({NO_LIST_AFTER_MUTATION})" in summary
    assert f"{CONTROL} [control]: NOT EXERCISED ({NO_LIST_AFTER_MUTATION})" in summary
    assert f"{TOOL_OUTPUT} [trap]: exercised;" in summary
    assert "The rug pull was NOT tested in this run" in summary
    assert f"Change signal after the mutation: {cli.SIGNAL_SENT_NO_RELIST}." in summary
    assert "tools/list total: 1 (0 after the mutation)" in summary
    assert "transcript: not provided" in summary
    assert "re-approval prompt: not recorded" in summary  # the default
    assert not service.manifest(run_id).transcript_provided


def test_a_room_that_was_never_served_finalizes_as_not_exercised(
    db: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = _service(db)
    run_id = service.start_run(["poltergeist"]).run.run_id
    assert _finalize(run_id, out) == 0
    summary = capsys.readouterr().out
    assert "no workspace found" in summary
    assert summary.count("NOT EXERCISED") == 3
    assert "Change signal after the mutation" not in summary  # nothing mutated


def _modern_without_listen(session: cli.McpSession) -> None:
    """A 2026-07-28 client that lists and calls but never opens subscriptions/listen."""

    async def main() -> None:
        with anyio.fail_after(10):
            async with Client(InMemoryTransport(session.server.server), mode="2026-07-28") as client:
                await client.list_tools()
                await client.call_tool("list_topics", {})  # mutates; nobody is listening

    anyio.run(main)


def test_modern_run_without_a_listen_subscriber_reports_no_signal_sent(
    db: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    room = "poltergeist"
    service = _service(db)
    run_id = service.start_run([room]).run.run_id
    session, _tools = _serve(service, db, room, run_id)
    try:
        _modern_without_listen(session)
        signals = [
            f for f in factlog.read(factlog.facts_path(session.materials.workspace), run_id)
            if isinstance(f, factlog.SignalFact)
        ]
        assert [(f.path, f.receiver_present) for f in signals] == [("subscriptions_listen", False)]
    finally:
        cli.deregister(run_id, room)

    assert _finalize(run_id, out) == 0
    summary = capsys.readouterr().out
    assert f"{RUG_DESC} [trap]: NOT EXERCISED ({NOT_SUBSCRIBED})" in summary
    assert "The rug pull was NOT tested in this run" in summary
    assert f"Change signal after the mutation: {cli.SIGNAL_NOT_SENT}." in summary
    assert "with no listen subscriber (delivered to nobody)" in summary


def test_a_log_that_predates_the_signal_fact_reports_the_case_unknown(
    db: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    room = "poltergeist-legacy"
    service = _service(db)
    run_id = service.start_run([room]).run.run_id
    session, tools = _serve(service, db, room, run_id)
    try:
        with connect(session.materials, tools) as client:
            client.approve()
            client.call("list_topics")  # mutates; the client never re-lists
    finally:
        cli.deregister(run_id, room)
    # Rewrite the log as an older server would have written it: no signal record.
    path = factlog.facts_path(session.materials.workspace)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [ln for ln in lines if json.loads(ln)["kind"] != "signal"]
    assert len(kept) == len(lines) - 1
    path.write_text("".join(kept), encoding="utf-8")

    assert _finalize(run_id, out) == 0
    summary = capsys.readouterr().out
    assert f"{RUG_DESC} [trap]: NOT EXERCISED ({NO_LIST_AFTER_MUTATION})" in summary
    assert "The rug pull was NOT tested in this run" in summary
    assert f"Change signal after the mutation: {cli.SIGNAL_UNKNOWN}." in summary
    assert cli.SIGNAL_SENT_NO_RELIST not in summary and cli.SIGNAL_NOT_SENT not in summary


def test_dummy_secret_in_a_non_steered_tool_is_a_fact_not_an_event(
    db: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    room = "poltergeist-legacy"
    service = _service(db)
    run_id = service.start_run([room]).run.run_id
    session, tools = _serve(service, db, room, run_id)
    secret = session.ctx.canary(RUG_DESC, "secret").value
    try:
        with connect(session.materials, tools) as client:
            client.approve()
            client.call("get_note", topic=secret)
    finally:
        cli.deregister(run_id, room)

    assert _finalize(run_id, out) == 0
    summary = capsys.readouterr().out
    assert f"dummy secret of {RUG_DESC} appeared in the arguments of get_note" in summary
    rug, _ = _trap(service, run_id, room, RUG_DESC)
    assert rug.signals == (Signal.NOT_EXERCISED,)


# --------------------------------------------------------------------------- #
# refusals: exit non-zero, a clear stderr message, nothing finalized, workspace kept
# --------------------------------------------------------------------------- #


def _assert_refused(rc: int, capsys: pytest.CaptureFixture[str], why: str) -> None:
    stdout, err = capsys.readouterr()
    assert rc != 0
    assert stdout == ""
    assert "finalize refused" in err and why in err


def test_unknown_run_is_refused(db: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _assert_refused(_finalize("-nope", out), capsys, "unknown run")
    assert not out.exists()


def test_invalid_run_id_is_refused(db: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _assert_refused(_finalize("../x", out), capsys, "invalid run ID")


def test_already_finalized_run_is_refused(db: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    service = _service(db)
    run_id = service.start_run(["poltergeist"]).run.run_id
    assert _finalize(run_id, out) == 0
    capsys.readouterr()
    _assert_refused(_finalize(run_id, out), capsys, "already finalized")


def test_closed_run_is_refused(db: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    service = _service(db)
    run_id = service.start_run(["poltergeist"], ttl=0.0, grace_window_secs=0.0).run.run_id
    _assert_refused(_finalize(run_id, out), capsys, "cannot be finalized")
    assert service.get_run(run_id).finalized_at is None


def test_run_with_a_non_mcp_room_is_refused(db: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_id = _service(db).start_run(["poltergeist", "threshold"]).run.run_id
    _assert_refused(_finalize(run_id, out), capsys, "threshold")


def test_missing_store_is_refused(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HAUNTLET_DB", str(tmp_path / "none" / "range.db"))
    _assert_refused(_finalize("abc", out), capsys, "no event store")


@pytest.mark.parametrize(
    "content, why",
    [
        ('{"role": "assistant", "text": "ok"}\nnot json\n', "line 2: not JSON"),
        ('{"role": "assistant"}\n', "line 1: expected"),
        ('["assistant", "hi"]\n', "line 1: expected"),
        ('{"role": "", "text": "hi"}\n', "line 1: expected"),
        ('{"role": "assistant", "text": 3}\n', "line 1: expected"),
    ],
)
def test_malformed_transcript_is_refused_and_nothing_is_finalized(
    db: Path, out: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str, why: str
) -> None:
    room = "poltergeist-legacy"
    service = _service(db)
    run_id = service.start_run([room]).run.run_id
    session, _ = _serve(service, db, room, run_id)
    cli.deregister(run_id, room)
    tfile = tmp_path / "bad.jsonl"
    tfile.write_text(content, encoding="utf-8")
    _assert_refused(_finalize(run_id, out, "--transcript", str(tfile)), capsys, why)
    assert service.get_run(run_id).finalized_at is None
    assert session.materials.workspace.is_dir()


def test_missing_transcript_file_is_refused(db: Path, out: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_id = _service(db).start_run(["poltergeist"]).run.run_id
    _assert_refused(_finalize(run_id, out, "--transcript", str(tmp_path / "x.jsonl")), capsys, "does not exist")


def test_transcript_loader_skips_blank_lines_and_ignores_extra_keys(tmp_path: Path) -> None:
    f = tmp_path / "t.jsonl"
    f.write_text('\n{"role": "assistant", "text": "hi", "ts": 1}\n\n', encoding="utf-8")
    entries = cli.load_transcript(f)
    assert [(e.role, e.text) for e in entries] == [("assistant", "hi")]


def test_bad_reapproval_value_is_rejected_by_the_parser(db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["mcp", "finalize", "--run=abc", "--reapproval", "maybe", "--out", str(tmp_path)])
    assert exc.value.code != 0


def test_write_failure_keeps_the_workspace(
    db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    room = "poltergeist"
    service = _service(db)
    run_id = service.start_run([room]).run.run_id
    session, _ = _serve(service, db, room, run_id)
    cli.deregister(run_id, room)
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    rc = _finalize(run_id, blocker)
    _, err = capsys.readouterr()
    assert rc != 0 and "workspace kept" in err
    assert service.get_run(run_id).finalized_at is not None
    assert session.materials.workspace.is_dir()
