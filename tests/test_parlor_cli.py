"""The `hauntlet parlor open` / `finalize` CLI (parlor task 10.3, approved change D12).

Refusals and the open/finalize flow run in-process through ``cli.main`` against a
shared store file, the same store ``hauntlet serve`` would use.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hauntlet import cli
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms import default_rooms

BASE_URL = "http://127.0.0.1:8666"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "range.db"
    Store(path)
    monkeypatch.setenv("HAUNTLET_DB", str(path))
    monkeypatch.setenv("HAUNTLET_BASE_URL", BASE_URL)
    return path


def _service(db: Path) -> RangeService:
    return RangeService(Store(db), default_rooms(), base_url=BASE_URL)


def _start_run(db: Path, rooms: list[str], ttl: float = 3600) -> str:
    return _service(db).start_run(rooms, ttl=ttl).run.run_id


# -- refusals --------------------------------------------------------------- #


def _assert_refused(argv: list[str], capsys, why: str) -> None:
    rc = cli.main(argv)
    out, err = capsys.readouterr()
    assert rc == 1 and out == ""
    assert "refused" in err and why in err


def test_open_refuses_unknown_run(db: Path, capsys) -> None:
    _assert_refused(["parlor", "open", "--run=nope"], capsys, "unknown run")


def test_open_refuses_run_without_parlor(db: Path, capsys) -> None:
    run_id = _start_run(db, ["threshold"])
    _assert_refused(["parlor", "open", f"--run={run_id}"], capsys, "does not include")


def test_open_refuses_expired_run(db: Path) -> None:
    # check_parlor_run drives the refusal; drive it with a controllable clock.
    from conftest import FakeClock

    clock = FakeClock()
    svc = RangeService(Store(db), default_rooms(), base_url=BASE_URL, clock=clock)
    run_id = svc.start_run(["parlor"], ttl=10).run.run_id
    clock.advance(20)
    with pytest.raises(cli.McpRefused, match="expired"):
        cli.check_parlor_run(svc, run_id)


def test_second_open_is_refused(db: Path, capsys) -> None:
    run_id = _start_run(db, ["parlor"])
    assert cli.main(["parlor", "open", f"--run={run_id}"]) == 0
    capsys.readouterr()
    _assert_refused(["parlor", "open", f"--run={run_id}"], capsys, "already has a parlor workspace")


def test_finalize_rejects_bad_perception(db: Path, tmp_path: Path) -> None:
    run_id = _start_run(db, ["parlor"])
    cli.main(["parlor", "open", f"--run={run_id}"])
    # argparse rejects an invalid choice (SystemExit) before our code runs.
    with pytest.raises(SystemExit):
        cli.main(["parlor", "finalize", f"--run={run_id}", "--perception=wat", f"--out={tmp_path}"])


# -- open prints the task and start URL ------------------------------------- #


def test_open_prints_task_and_start_url(db: Path, capsys) -> None:
    run_id = _start_run(db, ["parlor"])
    assert cli.main(["parlor", "open", f"--run={run_id}"]) == 0
    out, _ = capsys.readouterr()
    assert "Start page:" in out and "Your member code:" in out
    assert f"/c/" in out and "?page=lobby" in out
    # the workspace exists beside the store
    ws = cli.mcp_workspace(cli.mcp_scratch_root(db), "parlor", run_id)
    assert ws.is_dir() and (ws / "parlor-setup.json").is_file()


# -- finalize writes a summary with the manual perception line -------------- #


def test_finalize_writes_summary_and_report(db: Path, tmp_path: Path, capsys) -> None:
    run_id = _start_run(db, ["parlor"])
    cli.main(["parlor", "open", f"--run={run_id}"])
    capsys.readouterr()
    out_dir = tmp_path / "reports"
    rc = cli.main(
        ["parlor", "finalize", f"--run={run_id}", "--perception=vision", f"--out={out_dir}"]
    )
    out, err = capsys.readouterr()
    assert rc == 0, err
    assert "manual (tester-supplied, not scored)" in out
    assert "client page perception" in out and "screenshots" in out
    assert (out_dir / f"parlor-summary-{run_id}.txt").is_file()
    assert (out_dir / f"autopsy-parlor-{run_id}.html").is_file()
    # finalized: a second finalize is refused
    assert cli.main(["parlor", "finalize", f"--run={run_id}", f"--out={out_dir}"]) == 1
