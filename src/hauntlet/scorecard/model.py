"""The view model (design.md "View model"): plain, frozen, JSON-ready data.

The builder (``build.py``) produces it; the renderer turns it into HTML and
reads nothing else. Every state rule lives in the builder, so tests check this
data, not markup.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class State:
    kind: str  # "level" | "grey" | "control" | "info" | "progress"
    label: str  # chip text, e.g. "L3 Acted", "Not exercised", "False alarm"
    token: str  # CSS token: "l0".."l4", "muted", "info"
    meaning: str  # legend text, or ""
    level: int | None = None  # 0..4 only when kind == "level"


@dataclass(frozen=True)
class Change:
    before: State
    after: State | None  # None: after not run yet (or no exorcism)
    marker: str  # "", a change marker from copy.py, C15


@dataclass(frozen=True)
class Pill:
    name: str  # "detected" | "task" | "false_alarms"
    before: str
    after: str | None
    cost: bool  # the after value is a cost of the bundle (Requirement 9.5)


@dataclass(frozen=True)
class Strip:
    """The After view's main element: before → after, the bundle size, and what caused it."""

    before: State
    after: State
    files_total: int
    caused: tuple[tuple[str, bool], ...]  # (file path, depends on A4); demo path only
    note: str  # C17 above the files (demo), C18 (real client)
    green: bool  # only when the after state is L0 Clean (Requirement 9.6)


@dataclass(frozen=True)
class Hero:
    change: Change
    sentence_before: str
    sentence_after: str | None
    pills: tuple[Pill, ...]
    toggle: str  # "toggle" | "pending" | "none"
    provisional_note: str | None
    strip: Strip | None = None


@dataclass(frozen=True)
class RoomCard:
    room: str
    name: str
    stands_for: str
    run: bool  # False: "Not run"
    change: Change | None  # None when not run
    summary_before: str
    summary_after: str | None
    details_before: tuple[str, ...]  # task, detected, false alarms, L2 tags (core-report parity)
    details_after: tuple[str, ...] | None
    costs: tuple[str, ...]  # delta costs, verbatim
    fact_log_missing: bool


@dataclass(frozen=True)
class FixLine:
    item_id: str
    path: str
    rule: str
    reason: str
    tag: str  # "Advisory" | "Enforced"
    assumptions: tuple[str, ...]
    cites: tuple[str, ...]


@dataclass(frozen=True)
class FactLine:
    fact_id: str
    room: str
    trap_id: str | None
    time: str  # "+1.2 s" | "at finalize" | "" (demo decisions)
    who: str
    text: str
    tag: str
    note: str
    run_role: str  # "before" | "after"
    source: str  # "event" | "mcp" | "parlor" | "demo"
    count: int = 1  # adjacent identical rows merged into this one (×N)
    ids: tuple[str, ...] = ()  # every merged fact ID, this one first


@dataclass(frozen=True)
class TrapCard:
    title: str  # the threat-profile class in words, or the control title
    ref: str
    room: str
    trap_id: str
    is_control: bool
    where: str
    asked: str
    did_before: tuple[str, ...]
    did_after: tuple[str, ...] | None
    change: Change
    detected_before: bool
    detected_after: bool | None
    l2_not_assessed: bool
    signals_before: tuple[str, ...]
    signals_after: tuple[str, ...] | None  # after signals plus extra signals
    evidence: tuple[FactLine, ...]
    fixes: tuple[FixLine, ...]
    no_guardrail: str | None
    citation: str
    changed_by: tuple[str, ...] | None  # changed_by_display; None when not shown
    changed_by_note: str | None  # C17, C18, or None
    class_label: str | None
    cites: tuple[str, ...]  # items generated for the trap (delta ``cites``), verbatim


@dataclass(frozen=True)
class ItemGroup:
    """Items of one file with the same reason, citations and assumptions: one line."""

    rules: tuple[str, ...]
    reason: str
    cites: tuple[str, ...]
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class FileView:
    path: str
    tag: str  # "Advisory" | "Enforced" | "" (support file)
    note: str | None  # C26 for a support file
    items: tuple[FixLine, ...]
    assumptions: tuple[tuple[str, str], ...]  # (id, text)
    kind: str = "support"  # "steering" | "hook" | "mcp" | "sandbox" | "support"
    sentence: str = ""  # copy.FILE_KIND_SENTENCES[kind]
    groups: tuple[ItemGroup, ...] = ()


@dataclass(frozen=True)
class ExorcismView:
    present: bool
    unreadable: bool  # C27
    bundle_id: str | None
    path_label: str | None
    files: tuple[FileView, ...]
    cannot_fix: tuple[tuple[str, str], ...]
    permissions: str | None
    not_interpreted: tuple[str, ...]
    demo_notes: tuple[str, ...]
    demo_env_note: str | None
    no_guardrail: tuple[tuple[str, str], ...]
    attributions: tuple[str, ...]
    assumptions: tuple[tuple[str, str], ...]
    download_url: str | None
    bundle_path: str | None
    next_step: str  # "generate" | "generate-cli" | "not-final" | "delta-cli" | ""
    next_text: str


@dataclass(frozen=True)
class EvidenceView:
    before: tuple[FactLine, ...]  # timed, then finalize-time, in order
    after: tuple[FactLine, ...]
    demo_before: tuple[FactLine, ...]
    demo_after: tuple[FactLine, ...]
    unavailable: tuple[tuple[str, str], ...]  # (run_role, room)


@dataclass(frozen=True)
class AggregateRow:
    room: str
    cells: tuple[str, ...]  # in ``copy.AGG_HEADERS`` order
    worst_token: str


@dataclass(frozen=True)
class LateRow:
    trap_id: str
    signal: str
    arrived: str


@dataclass(frozen=True)
class ViewModel:
    badge: str
    path: str
    path_label: str | None
    agent_name: str
    run_id: str
    after_run_id: str | None
    rooms_in_run: tuple[str, ...]
    hero: Hero
    legend: tuple[State, ...]
    rooms: tuple[RoomCard, ...]
    traps: tuple[tuple[str, tuple[TrapCard, ...]], ...]  # (room, cards) for run rooms, in run order
    default_room: str
    exorcism: ExorcismView
    aggregates: tuple[AggregateRow, ...]
    aggregates_note: str | None
    late: tuple[LateRow, ...]
    ignored_events: int
    evidence: EvidenceView
    live: bool
    stream_url: str | None
    served: bool

    def traps_for(self, room: str) -> tuple[TrapCard, ...]:
        for name, cards in self.traps:
            if name == room:
                return cards
        return ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
