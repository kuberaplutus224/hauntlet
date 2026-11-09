"""Exorcist data types (design.md "Data models"). All immutable.

Room packages import the threat-profile types from here (approved change D15),
so this module imports nothing from ``hauntlet.rooms``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType


class Source(StrEnum):
    """Where a trap's text lives (content source, Glossary)."""

    REPO_FILE = "repo_file"
    TOOL_DESCRIPTION = "tool_description"
    TOOL_OUTPUT = "tool_output"
    WEB_PAGE_TEXT = "web_page_text"
    WEB_PAGE_HIDDEN = "web_page_hidden"
    WEB_PAGE_ATTRIBUTE = "web_page_attribute"
    IMAGE = "image"


class Effect(StrEnum):
    """What a trap asks the agent to do (steered effect, Glossary)."""

    NETWORK_FETCH = "network_fetch"
    FILE_WRITE = "file_write"
    TOOL_CALL = "tool_call"
    ECHO = "echo"
    SECRET_SEND = "secret_send"
    FORM_SUBMIT = "form_submit"


#: Fixed orders, so everything rendered from sets is deterministic.
SOURCE_ORDER: tuple[Source, ...] = tuple(Source)
EFFECT_ORDER: tuple[Effect, ...] = tuple(Effect)


@dataclass(frozen=True)
class TrapThreat:
    """One non-control trap's threat profile: one source, one or more effects."""

    source: Source
    effects: frozenset[Effect]

    def __post_init__(self) -> None:
        if not isinstance(self.source, Source):
            raise TypeError(f"source must be a Source, got {self.source!r}")
        effects = frozenset(self.effects)
        if not effects:
            raise ValueError("a trap threat needs at least one steered effect")
        if not all(isinstance(e, Effect) for e in effects):
            raise TypeError(f"effects must be Effect values, got {sorted(map(str, effects))}")
        object.__setattr__(self, "effects", effects)


@dataclass(frozen=True)
class McpTools:
    """An MCP room's tools as the Exorcist sees them (D15)."""

    tools: tuple[str, ...]  # every tool the room's server advertises
    task_tools: tuple[str, ...]  # tools the genuine task needs
    steered_tools: Mapping[str, str]  # steered tool -> owning trap ID
    relay_tools: frozenset[str]  # steered tools that fetch a canary URL

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "task_tools", tuple(self.task_tools))
        object.__setattr__(self, "steered_tools", MappingProxyType(dict(self.steered_tools)))
        object.__setattr__(self, "relay_tools", frozenset(self.relay_tools))
        overlap = set(self.task_tools) & set(self.steered_tools)
        if overlap:
            raise ValueError(f"tools cannot be both task and steered: {sorted(overlap)}")
        stray = self.relay_tools - set(self.steered_tools)
        if stray:
            raise ValueError(f"relay tools must be steered tools: {sorted(stray)}")
        unknown = (set(self.task_tools) | set(self.steered_tools)) - set(self.tools)
        if unknown:
            raise ValueError(f"task and steered tools must be advertised: {sorted(unknown)}")

    def not_needed(self) -> tuple[str, ...]:
        """Advertised tools the task does not need, sorted (``disabledTools``)."""
        return tuple(sorted(set(self.tools) - set(self.task_tools)))


@dataclass(frozen=True)
class RoomThreats:
    """A room's threat profiles (D15), declared as data in the room's package."""

    traps: Mapping[str, TrapThreat]  # every non-control trap, never a control
    mcp: McpTools | None = None
    #: Names of the environment variables the room's real-client path provides
    #: (exorcist Requirement 8.9). The demo agent's environment is exactly these.
    real_client_env: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "traps", MappingProxyType(dict(self.traps)))
        object.__setattr__(self, "real_client_env", frozenset(self.real_client_env))
        if not self.traps:
            raise ValueError("a room needs at least one non-control trap profile")


# --------------------------------------------------------------------------- #
# Generator types
# --------------------------------------------------------------------------- #


class TrapClass(StrEnum):
    """Requirement 1.3: how the Exorcist classifies each trap of the before run."""

    FIRED = "fired"
    NOT_EXERCISED = "not_exercised"
    RESISTED = "resisted"
    L0_L2_NOT_ASSESSED = "l0_l2_not_assessed"
    CONTROL = "control"


#: Classes that get guardrail items (Requirement 1.4).
ELIGIBLE_CLASSES: frozenset[TrapClass] = frozenset({TrapClass.FIRED, TrapClass.NOT_EXERCISED})


@dataclass(frozen=True)
class ClassifiedTrap:
    room: str
    trap_id: str
    cls: TrapClass
    level: int  # the before level, 0..4
    signals: tuple[str, ...]  # the before signals

    @property
    def eligible(self) -> bool:
        return self.cls in ELIGIBLE_CLASSES

    @property
    def ref(self) -> str:
        """``room/trap_id``: how manifests and reports cite a trap."""
        return f"{self.room}/{self.trap_id}"


@dataclass(frozen=True)
class GuardrailItem:
    """One generated file or one entry in a generated file (Glossary)."""

    item_id: str  # e.g. "steering/untrusted-content.md#DATA"
    path: str  # relative path inside the bundle
    rule: str  # rule key or entry name within the file
    kind: str  # "steering" | "hook" | "mcp" | "sandbox"
    selected_by: tuple[str, ...]  # "source:<s>" / "effect:<e>" / "room:<r>" class keys
    cites: tuple[str, ...]  # "room/trap_id", sorted; manifest only
    reason: str
    surfaces: str  # which Kiro surfaces honour it (verified table)
    enforced: bool  # False for steering: advisory
    assumptions: tuple[str, ...] = ()  # "A1".."A5"


@dataclass(frozen=True)
class BundleSpec:
    """Everything the writer needs. ``files`` holds the guardrail files only."""

    before_run_id: str
    items: tuple[GuardrailItem, ...]
    files: Mapping[str, bytes]  # relative path under the bundle's .kiro/ tree -> bytes
    trap_classes: tuple[ClassifiedTrap, ...]
    no_guardrail: tuple[tuple[str, str], ...]  # (room/trap_id, reason)
    permissions_suggestion: str  # YAML text, manifest only (Requirement 4.5)
    mcp_server_names: Mapping[str, str]  # room -> server name in mcp.json
    rooms: tuple[str, ...]  # the before run's room names, in manifest order

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))
        object.__setattr__(self, "mcp_server_names", MappingProxyType(dict(self.mcp_server_names)))
