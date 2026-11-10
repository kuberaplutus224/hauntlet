"""What the builder receives (design.md "Inputs"). ``sources.py`` is the only module
that does I/O to produce these; tests build them directly.

The delta is its ``render_json`` document (parsed), never the ``Delta``
dataclass, so the page shows exactly what the JSON output says. Demo-config
decisions travel in ``RunInput.facts`` with ``source == "demo"``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from hauntlet.core.models import AggregateScore, Run, RunManifest, RunScore
from hauntlet.scorecard.facts import Fact

PATHS = ("demo-agent", "real-client", "not-recorded")  # plus "reference:<name>"


@dataclass(frozen=True)
class RunInput:
    run: Run
    score: RunScore
    manifest: RunManifest
    facts: tuple[Fact, ...] = ()  # redacted, normalised (facts.py)
    #: room -> fact log available; only MCP and Parlor rooms appear.
    fact_logs: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", tuple(self.facts))
        object.__setattr__(self, "fact_logs", MappingProxyType(dict(self.fact_logs)))


@dataclass(frozen=True)
class ExorcismInput:
    bundle_id: str
    bundle: Mapping[str, Any]  # parsed bundle.json, unchanged ({} when unreadable)
    delta: Mapping[str, Any]  # parsed render_json document ({} when unreadable)
    after: RunInput | None = None  # None while the after run is pending, or gone from the store
    download_url: str | None = None  # "/exorcisms/{id}/bundle" when served by the range
    bundle_path: str | None = None  # the bundle directory, for static exports
    unreadable: bool = False  # C27


@dataclass(frozen=True)
class ScorecardInput:
    path: str  # "demo-agent" | "real-client" | "reference:<name>" | "not-recorded"
    before: RunInput
    registered_rooms: tuple[str, ...]
    now: float
    agent_name: str = ""
    exorcism: ExorcismInput | None = None
    aggregates: tuple[AggregateScore, ...] = ()
    served: bool = False
    stream_url: str | None = None
