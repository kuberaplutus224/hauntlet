"""The demo keeps its evidence (scorecard D26, task 15).

- ``cursed-repo`` keeps a trace per run (no MCP fact log); ``poltergeist`` keeps
  a fact log and a trace per run;
- the files hold no canary value of either run (the raw facts did);
- they read back through the rooms' own ``factlog.read`` and the scorecard;
- they are left out of the download archive, and the retention sweep removes
  them with their bundle.

**Validates: scorecard Requirement 8.3, D26**
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from hauntlet.core.canary import DUMMY_PREFIX, MARKER_PREFIX
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.exorcist.hosted import HostedCaps, HostedExorcist
from hauntlet.exorcist.service import ExorcistService
from hauntlet.exorcist.writer import WriteRefused, write_into
from hauntlet.rooms import default_rooms
from hauntlet.rooms.poltergeist import factlog


class Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    svc = RangeService(Store(":memory:"), default_rooms(), clock=clock)
    return svc, ExorcistService(svc, tmp_path / "ex", clock=clock), clock


def _leaks(text: str, canaries) -> list[str]:
    low = text.lower()
    out = []
    for c in canaries:
        tail = c.value.split("-", 2)[-1] if c.kind in ("secret", "marker") else c.value
        if c.kind == "secret" and (c.value.lower() in low or c.value[len(DUMMY_PREFIX) + 1 :].lower() in low):
            out.append(c.value)
        elif c.kind == "marker" and c.value[len(MARKER_PREFIX) + 1 :].lower() in low:
            out.append(c.value)
        elif c.kind not in ("secret", "marker") and tail in text:
            out.append(c.value)
    return out


@pytest.mark.parametrize("room,mcp", [("cursed-repo", False), ("poltergeist", True)])
def test_evidence_files_exist_and_hold_no_canary(setup, room, mcp) -> None:
    svc, ex, _ = setup
    res = ex.demo(room)
    ev = res.bundle_dir / "evidence"
    for run in (res.before, res.after):
        trace = ev / f"trace-{run.run_id}.jsonl"
        assert trace.is_file()
        records = [json.loads(line) for line in trace.read_text().splitlines()]
        assert [r["seq"] for r in records] == list(range(len(run.trace)))
        assert {tuple(r) for r in map(sorted, records)} <= {("denied_by", "proceeded", "seq", "source", "tool_id", "where")}
        facts = ev / f"facts-{run.run_id}-{room}.jsonl"
        assert facts.is_file() == mcp
        canaries = svc.canaries(run.run_id)
        for f in (trace, facts):
            if f.is_file():
                assert not _leaks(f.read_text(encoding="utf-8"), canaries), f.name
        if mcp:
            raw = "\n".join(factlog.to_line(x) for x in run.facts)
            back = factlog.read(facts, run.run_id)
            assert len(back) == len(run.facts) and [b.kind for b in back] == [x.kind for x in run.facts]
            if run is res.before:
                assert _leaks(raw, canaries), "the raw before facts did carry canary values"


def test_scorecard_reads_the_kept_evidence(setup) -> None:
    from hauntlet.scorecard import render_exorcism

    _, ex, _ = setup
    res = ex.demo("poltergeist")
    html = render_exorcism(ex, res.bundle_dir)
    assert "fact log not available" not in html
    assert "Demo config decisions" in html and "Client called" in html


def test_archive_skips_evidence_and_sweep_removes_it(setup) -> None:
    svc, ex, clock = setup
    hosted = HostedExorcist(ex, HostedCaps(retention_secs=60.0), clock=clock)
    res = ex.demo("poltergeist")
    names = zipfile.ZipFile(io.BytesIO(hosted.bundle_zip(res.bundle_id))).namelist()
    assert names and not any(n.startswith("evidence/") for n in names)
    assert (res.bundle_dir / "evidence").is_dir()
    clock.now += 120
    hosted.sweep()
    assert not res.bundle_dir.exists()


def test_writer_still_refuses_other_folders(setup) -> None:
    _, ex, _ = setup
    res = ex.demo("cursed-repo")
    for rel in (".kiro/steering/x.md", "other/x.txt", "../evidence/x"):
        with pytest.raises(WriteRefused):
            write_into(res.bundle_dir, rel, b"x")
