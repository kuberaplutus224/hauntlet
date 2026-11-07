"""D9: ``hauntlet sample-report`` is byte-for-byte deterministic, while the
default RangeService keeps drawing random run IDs.

**Validates: Requirements 12.3(g), 12 D9**
"""
from __future__ import annotations

from hauntlet.cli import SAMPLE_RUN_ID, main
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms import default_rooms


def test_sample_report_renders_identical_bytes_twice(tmp_path):
    a, b = tmp_path / "a.html", tmp_path / "b.html"
    assert main(["sample-report", "--out", str(a)]) == 0
    assert main(["sample-report", "--out", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()
    assert f"<code>{SAMPLE_RUN_ID}</code>".encode() in a.read_bytes()


def test_default_service_still_draws_random_run_ids():
    service = RangeService(Store(":memory:"), default_rooms())
    first = service.start_run(["threshold"]).run
    second = service.start_run(["threshold"]).run
    assert first.run_id != second.run_id
