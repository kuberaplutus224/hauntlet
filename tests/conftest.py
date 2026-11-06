from __future__ import annotations

import json
from pathlib import Path

import pytest

from hauntlet.core.models import Event, RunManifest, manifest_from_dict
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms import default_rooms

FIXTURES = Path(__file__).parent / "fixtures"


def load_golden() -> tuple[RunManifest, list[dict]]:
    data = json.loads((FIXTURES / "scorer_golden.json").read_text())
    return manifest_from_dict(data["manifest"]), data["cases"]


def make_event(manifest: RunManifest, raw: dict, ts: float = 0.0) -> Event:
    return Event(
        run_id=raw.get("run_id", manifest.run_id),
        room=raw["room"],
        trap_id=raw["trap_id"],
        channel=raw["channel"],
        signal=raw["signal"],
        timestamp=ts,
        detail=raw.get("detail", ""),
        expired=raw.get("expired", False),
    )


class FakeClock:
    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(clock: FakeClock) -> RangeService:
    return RangeService(Store(":memory:"), default_rooms(), base_url="http://range.test", clock=clock, default_ttl=60)
