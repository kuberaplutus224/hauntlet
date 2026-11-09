"""The task driver never acts on trap content (exorcist Requirement 8.1, 9.7, EP14, task 11.3).

Run the demo agent under the bundle generated from its own baseline run, so
every obedience action is skipped and only the task driver's own writes and
fetches reach the toolbox. For every demo room and two seeds:

- no write or fetch the driver makes carries a canary value of the run;
- the driver's writes and fetches are identical across seeds once the room's
  task data is masked (these rooms carry no per-run task data, so they are
  identical as-is).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _demo_support import DEMO_ROOMS, canary_values, drive

from hauntlet.agents.demo import DemoAgent, baseline_for
from hauntlet.core.toolbox import ToolBox
from hauntlet.exorcist.generate import generate
from hauntlet.exorcist.profiles import real_client_env
from hauntlet.exorcist.writer import write_bundle


class CapturingToolBox(ToolBox):
    """Records the (rel, content) of every write and the URL of every fetch."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.writes: list[tuple[str, str]] = []
        self.fetches: list[str] = []

    def write_file(self, rel: str, content: str) -> None:
        self.writes.append((rel, content))
        super().write_file(rel, content)

    def fetch(self, url: str) -> str:
        self.fetches.append(url)
        return super().fetch(url)


def _run_under_bundle(room: str, scratch: Path) -> CapturingToolBox:
    base = drive(room, scratch / "base", DemoAgent(baseline_for(scratch / "b", room), real_client_env))
    spec = generate(base.score, base.manifest)
    _bid, bundle = write_bundle(scratch / "ex", spec, created_at=1.0)
    driven = drive(room, scratch / "run", DemoAgent(bundle, real_client_env), toolbox_cls=CapturingToolBox)
    tb = driven.tools
    assert isinstance(tb, CapturingToolBox)
    tb._canaries = canary_values(driven.canaries)  # type: ignore[attr-defined]
    return tb


@pytest.mark.parametrize("room", DEMO_ROOMS)
def test_driver_actions_carry_no_canary_value(tmp_path: Path, room: str) -> None:
    tb = _run_under_bundle(room, tmp_path / room)
    values = tb._canaries  # type: ignore[attr-defined]
    for rel, content in tb.writes:
        for v in values:
            assert v not in content, f"driver wrote canary {v!r} into {rel}"
            assert v not in rel
    for url in tb.fetches:
        for v in values:
            assert v not in url, f"driver fetched canary {v!r}"


@pytest.mark.parametrize("room", DEMO_ROOMS)
def test_driver_actions_are_identical_across_seeds(tmp_path: Path, room: str) -> None:
    a = _run_under_bundle(room, tmp_path / "a")
    b = _run_under_bundle(room, tmp_path / "b")
    # No per-run task data in these rooms, so the driver's writes and fetches match exactly.
    assert a.writes == b.writes
    assert a.fetches == b.fetches
