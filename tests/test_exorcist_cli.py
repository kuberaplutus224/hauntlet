"""The `hauntlet exorcist` CLI (exorcist Requirements 7.4, 7.5, 10.6, 10.9, 12.1–12.4, task 15.2).

- ``exorcist demo`` runs the in-process loop for a file room and an MCP room and
  prints the bundle and delta paths; ``--room parlor`` is refused (exit 2) and
  names the supported rooms; ``generate`` refuses an unfinalized run.
- A real-client simulation: a scripted client drives the real ``mcp serve``
  setup for a genuinely separate after run, ``mcp finalize`` writes the D19
  fact-log copy, and ``exorcist delta`` attaches it. The delta is labelled
  "real client, declared by the tester"; the test never claims the client is
  Kiro. The client runs in-process over ``fetch_local`` (the stdio subprocess
  transport is covered by ``tests/test_poltergeist_real_client_e2e.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hauntlet import cli
from hauntlet.agents import get_agent
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.core.toolbox import ToolBox
from hauntlet.exorcist.paths import exorcist_root
from hauntlet.rooms import default_rooms

BASE_URL = "http://127.0.0.1:8666"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "range.db"
    Store(path)
    monkeypatch.setenv("HAUNTLET_DB", str(path))
    monkeypatch.setenv("HAUNTLET_BASE_URL", BASE_URL)
    return path


@pytest.fixture
def reports(tmp_path: Path) -> Path:
    return tmp_path / "reports"


# --------------------------------------------------------------------------- #
# demo
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("room", ["cursed-repo", "poltergeist"])
def test_demo_writes_bundle_and_delta(db: Path, reports: Path, room: str, capsys) -> None:
    rc = cli.main(["exorcist", "demo", "--room", room, "--out", str(reports)])
    out = capsys.readouterr().out
    assert rc == 0
    bundle_line = next(ln for ln in out.splitlines() if ln.startswith("bundle: "))
    bundle_dir = Path(bundle_line.removeprefix("bundle: "))
    assert (bundle_dir / "bundle.json").is_file()
    assert (bundle_dir / "EXORCISM.md").is_file()
    deltas = list((bundle_dir / "deltas").glob("*.txt"))
    assert deltas and all((bundle_dir / "deltas" / f"{deltas[0].stem}.{ext}").is_file() for ext in ("json", "html"))
    assert list(reports.glob("exorcist-delta-*.html"))
    assert "after worst=L0" in out
    # The bundle landed under exorcist_root(HAUNTLET_DB).
    assert exorcist_root(db) in bundle_dir.parents


def test_demo_parlor_is_refused(db: Path, capsys) -> None:
    rc = cli.main(["exorcist", "demo", "--room", "parlor"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "does not support 'parlor'" in err and "cursed-repo" in err


def test_demo_unknown_room_is_refused(db: Path, capsys) -> None:
    assert cli.main(["exorcist", "demo", "--room", "attic"]) == 2
    assert "unknown room" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# generate refusals
# --------------------------------------------------------------------------- #


def test_generate_refuses_unfinalized_run(db: Path, capsys) -> None:
    service = RangeService(Store(db), default_rooms(), base_url=BASE_URL)
    run_id = service.start_run(["poltergeist"], grace_window_secs=0).run.run_id  # never finalized
    rc = cli.main(["exorcist", "generate", f"--run={run_id}"])
    err = capsys.readouterr().err
    assert rc == 2 and "not finalized" in err


def test_generate_refuses_unknown_run(db: Path, capsys) -> None:
    assert cli.main(["exorcist", "generate", "--run=nosuchrun12"]) == 2
    assert "unknown run" in capsys.readouterr().err


def test_delta_refuses_unknown_bundle(db: Path, capsys) -> None:
    assert cli.main(["exorcist", "delta", "--bundle=nosuchbundle", "--after=whatever1234"]) == 2
    assert "no bundle" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# generate + real-client after run + delta
# --------------------------------------------------------------------------- #


def _real_client_run(db: Path, reports: Path, room: str = "poltergeist") -> str:
    """A genuinely separate finalized run: the real serve setup, a scripted
    in-process client, then the real ``mcp finalize`` CLI (which writes the D19
    fact-log copy). Returns the run ID."""
    service = RangeService(Store(db), default_rooms(), base_url=BASE_URL)
    run_id = service.start_run([room], grace_window_secs=0).run.run_id
    session = cli.prepare_mcp_serve(service, room, run_id, cli.mcp_scratch_root(db))
    tools = ToolBox(session.materials.workspace, session.materials.env, service.fetch_local, service.base_url)
    try:
        get_agent("naive").run(session.materials, tools)
    finally:
        cli.deregister(run_id, room)
    assert cli.main(["mcp", "finalize", f"--run={run_id}", "--out", str(reports)]) == 0
    return run_id


def test_generate_then_attach_a_real_client_after_run(db: Path, reports: Path, capsys) -> None:
    before = _real_client_run(db, reports)
    capsys.readouterr()

    rc = cli.main(["exorcist", "generate", f"--run={before}"])
    gen_out = capsys.readouterr().out
    assert rc == 0
    bundle_id = next(ln for ln in gen_out.splitlines() if ln.startswith("next:")).split("--bundle ")[1].split()[0]
    bundle_dir = Path(next(ln for ln in gen_out.splitlines() if ln.startswith("bundle: ")).removeprefix("bundle: "))
    assert (bundle_dir / "EXORCISM.md").is_file()

    after = _real_client_run(db, reports)
    # D19: mcp finalize kept a fact-log copy beside the summary.
    assert (reports / f"mcp-facts-{after}-poltergeist.jsonl").is_file()
    capsys.readouterr()

    rc = cli.main(["exorcist", "delta", f"--bundle={bundle_id}", f"--after={after}", "--out", str(reports)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "path: real-client" in out

    delta_txt = (bundle_dir / "deltas" / f"{after}.txt").read_text()
    assert "real client, declared by the tester" in delta_txt
    assert "not observable (real client)" in delta_txt  # changed-by is not observable off the demo path
    # The before result is preserved in the delta (rug-desc fired in the real-client run).
    assert "rug-desc" in delta_txt


def test_delta_refuses_an_after_run_that_is_the_before_run(db: Path, reports: Path, capsys) -> None:
    before = _real_client_run(db, reports)
    capsys.readouterr()
    cli.main(["exorcist", "generate", f"--run={before}"])
    gen_out = capsys.readouterr().out
    bundle_id = next(ln for ln in gen_out.splitlines() if ln.startswith("next:")).split("--bundle ")[1].split()[0]
    rc = cli.main(["exorcist", "delta", f"--bundle={bundle_id}", f"--after={before}", "--out", str(reports)])
    err = capsys.readouterr().err
    assert rc == 2 and "after run" in err
