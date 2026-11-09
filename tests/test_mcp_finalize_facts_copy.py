"""``hauntlet mcp finalize`` keeps a copy of each room's fact log (approved change D19).

The Exorcist reads the copy, after the workspace is torn down, to report a
steered tool call whose canary never arrived (exorcist Requirement 10.9).

- After a full session, the copy exists beside the run summary and is
  byte-identical to the workspace log as it was at finalize time. The workspace
  is still removed.
- The summary, report and printed output are as before. The only new file in
  the reports directory is the copy.
- A room that was never served has no fact log, so nothing is copied, and the
  run still finalizes.
- A failed copy keeps the workspace and exits non-zero, like any other write
  failure.

_Requirements (exorcist): 10.9, 14.1 (f), D19_
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hauntlet import cli
from hauntlet.agents import get_agent
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.core.toolbox import ToolBox
from hauntlet.rooms import default_rooms
from hauntlet.rooms.poltergeist import factlog

BASE_URL = "http://127.0.0.1:8666"


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


def _served_naive_run(db: Path, room: str) -> tuple[RangeService, str, Path]:
    service = RangeService(Store(db), default_rooms(), base_url=BASE_URL)
    run_id = service.start_run([room]).run.run_id
    session = cli.prepare_mcp_serve(service, room, run_id, cli.mcp_scratch_root(db))
    tools = ToolBox(session.materials.workspace, session.materials.env, service.fetch_local, service.base_url)
    try:
        get_agent("naive").run(session.materials, tools)
    finally:
        cli.deregister(run_id, room)
    return service, run_id, session.materials.workspace


@pytest.mark.parametrize("room", cli.MCP_ROOMS)
def test_copy_is_byte_identical_and_the_workspace_is_removed(
    db: Path, out: Path, room: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _service, run_id, workspace = _served_naive_run(db, room)
    at_finalize = factlog.facts_path(workspace).read_bytes()
    assert at_finalize, "the session wrote facts"

    rc = cli.main(["mcp", "finalize", f"--run={run_id}", "--out", str(out)])
    stdout, err = capsys.readouterr()
    assert rc == 0, err

    copy = cli.mcp_facts_copy_path(out, run_id, room)
    assert copy == out / f"mcp-facts-{run_id}-{room}.jsonl"
    assert copy.read_bytes() == at_finalize
    assert not workspace.exists()

    # Existing outputs are unchanged: the same two files plus the copy, and
    # the printed paths are the same last lines as before D19.
    assert sorted(p.name for p in out.iterdir()) == sorted(
        [f"mcp-summary-{run_id}.txt", f"autopsy-mcp-{run_id}.html", copy.name]
    )
    assert stdout.rstrip().endswith(
        f"summary: {out / f'mcp-summary-{run_id}.txt'}\nreport: {out / f'autopsy-mcp-{run_id}.html'}"
    )
    assert "mcp-facts" not in stdout


def test_never_served_room_copies_nothing(db: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    service = RangeService(Store(db), default_rooms(), base_url=BASE_URL)
    run_id = service.start_run(["poltergeist"]).run.run_id
    assert cli.main(["mcp", "finalize", f"--run={run_id}", "--out", str(out)]) == 0
    capsys.readouterr()
    assert not cli.mcp_facts_copy_path(out, run_id, "poltergeist").exists()


def test_failed_copy_keeps_the_workspace(
    db: Path, out: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _service, run_id, workspace = _served_naive_run(db, "poltergeist")

    def boom(*_a, **_k) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(cli, "_copy_fact_log", boom)
    rc = cli.main(["mcp", "finalize", f"--run={run_id}", "--out", str(out)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "workspace kept" in err
    assert factlog.facts_path(workspace).is_file()
