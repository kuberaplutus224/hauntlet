"""The Poltergeist room configs: shape, validation and canary-core compatibility.

Both registered rooms (``poltergeist`` and ``poltergeist-legacy``) share one
tool set, trap set and task, and differ only in ``RevisionSettings``. These
tests pin that shape and check that each ``RoomConfig.validate()`` rule
rejects a config broken in exactly one way.

Covers:
  - Both configs validate; both manifests pass canary-core validation (Req 2.3, 6.1)
  - One control, two non-control traps, unique IDs, no ``__task__``,
    non-empty sources, tool description / tool output surfaces (Req 2.3, 6.1, 6.2)
  - One rejection per ``validate()`` rule (Req 2.3)
  - The two configs differ only in ``RevisionSettings`` (Req 5.3)
"""

from __future__ import annotations

import dataclasses

import pytest

from hauntlet.core.models import RoomManifest, TrapSpec
from hauntlet.core.room import Observation, Room, RoomContext, RoomMaterials, Transcript
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms.poltergeist.config import (
    POLTERGEIST,
    POLTERGEIST_LEGACY,
    RoomConfig,
)

CONFIGS = pytest.mark.parametrize(
    "cfg", [POLTERGEIST, POLTERGEIST_LEGACY], ids=lambda c: c.name
)

TOOL_NAMES = (
    "list_topics",
    "get_note",
    "submit_answer",
    "report_telemetry",
    "save_note",
    "check_health",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_room(cfg: RoomConfig) -> Room:
    """A minimal room whose manifest is the config's manifest."""

    class _StubRoom:
        name = cfg.name

        def manifest(self) -> RoomManifest:
            return cfg.manifest()

        def setup(self, ctx: RoomContext) -> RoomMaterials:  # pragma: no cover
            raise NotImplementedError

        def collect(
            self, ctx: RoomContext, materials: RoomMaterials, transcript: Transcript | None
        ) -> list[Observation]:  # pragma: no cover
            raise NotImplementedError

        def teardown(self, ctx: RoomContext) -> None:  # pragma: no cover
            pass

    return _StubRoom()  # type: ignore[return-value]


def _with_tool(cfg: RoomConfig, name: str, **changes) -> RoomConfig:
    """Return ``cfg`` with one tool's fields replaced."""
    tools = tuple(
        dataclasses.replace(t, **changes) if t.name == name else t for t in cfg.tools
    )
    assert tools != cfg.tools, f"no tool {name!r} changed"
    return dataclasses.replace(cfg, tools=tools)


def _with_revision(cfg: RoomConfig, **changes) -> RoomConfig:
    return dataclasses.replace(cfg, revision=dataclasses.replace(cfg.revision, **changes))


# ---------------------------------------------------------------------------
# Both configs are valid
# ---------------------------------------------------------------------------

@CONFIGS
def test_config_validates(cfg: RoomConfig) -> None:
    cfg.validate()


def test_both_manifests_pass_canary_core_validation() -> None:
    """RangeService validates every room manifest at construction."""
    rooms = {c.name: _stub_room(c) for c in (POLTERGEIST, POLTERGEIST_LEGACY)}
    svc = RangeService(Store(":memory:"), rooms)
    assert set(svc.rooms) == {"poltergeist", "poltergeist-legacy"}


@CONFIGS
def test_manifest_shape(cfg: RoomConfig) -> None:
    manifest = cfg.manifest()
    assert manifest.room == cfg.name
    traps = manifest.traps
    ids = [t.trap_id for t in traps]

    assert len(ids) == len(set(ids))
    assert "__task__" not in ids
    assert [t.trap_id for t in traps if t.is_control] == [cfg.control_trap_id] == ["health-typo"]
    non_control = [t for t in traps if not t.is_control]
    assert len(non_control) == 2
    assert all(t.source.strip() for t in non_control)
    assert {t.surface for t in traps} == {"tool description", "tool output"}


@CONFIGS
def test_manifest_order_is_non_control_then_control(cfg: RoomConfig) -> None:
    assert [t.trap_id for t in cfg.manifest().traps] == ["rug-desc", "tool-output", "health-typo"]
    surfaces = {t.trap_id: t.surface for t in cfg.manifest().traps}
    assert surfaces == {
        "rug-desc": "tool description",
        "tool-output": "tool output",
        "health-typo": "tool description",
    }


@CONFIGS
def test_non_control_sources_are_marked_to_verify(cfg: RoomConfig) -> None:
    """Placeholder marker until task 14.3 verifies the citations and drops it."""
    for trap in cfg.manifest().traps:
        if not trap.is_control:
            assert trap.source.endswith("(to verify)"), trap.trap_id


# ---------------------------------------------------------------------------
# Tools and revisions
# ---------------------------------------------------------------------------

@CONFIGS
def test_tool_names(cfg: RoomConfig) -> None:
    assert tuple(t.name for t in cfg.tools) == TOOL_NAMES


@CONFIGS
def test_save_note_named_path(cfg: RoomConfig) -> None:
    save_note = cfg.tool("save_note")
    assert save_note is not None
    assert save_note.named_path == "sync-ack.txt"
    assert [t.name for t in cfg.tools if t.named_path is not None] == ["save_note"]


@CONFIGS
def test_only_get_note_and_check_health_mutate(cfg: RoomConfig) -> None:
    mutating = {t.name for t in cfg.tools if t.desc_post_tmpl is not None}
    assert mutating == {"get_note", "check_health"}


def test_modern_revision() -> None:
    rev = POLTERGEIST.revision
    assert rev.name == "poltergeist"
    assert rev.modern_versions == ("2026-07-28",)
    assert rev.handshake_versions == ()
    assert rev.signal == "subscriptions_listen"


def test_legacy_revision() -> None:
    rev = POLTERGEIST_LEGACY.revision
    assert rev.name == "poltergeist-legacy"
    assert rev.handshake_versions == ("2025-11-25", "2025-06-18")
    assert rev.modern_versions == ()
    assert rev.signal == "list_changed"


def test_configs_differ_only_in_revision() -> None:
    a, b = POLTERGEIST, POLTERGEIST_LEGACY
    assert a.tools == b.tools
    assert a.traps == b.traps
    assert a.control_trap_id == b.control_trap_id
    assert a.task_topic == b.task_topic
    assert a.task == b.task
    assert a.revision != b.revision
    assert dataclasses.replace(b, revision=a.revision) == a


# ---------------------------------------------------------------------------
# One rejection per validate() rule
# ---------------------------------------------------------------------------

def _broken(cfg: RoomConfig) -> list[tuple[str, RoomConfig, str]]:
    """(case id, config broken one way, expected message fragment)."""
    extra_trap = TrapSpec("orphan", "tool output", "arXiv 2604.05969 (test)")
    return [
        (
            "no-versions",
            _with_revision(cfg, handshake_versions=(), modern_versions=()),
            "speaks no protocol versions",
        ),
        ("unknown-signal", _with_revision(cfg, signal="carrier_pigeon"), "unknown change signal"),
        (
            "duplicate-tool-name",
            dataclasses.replace(cfg, tools=cfg.tools + (cfg.tool("submit_answer"),)),
            "duplicate tool names ['submit_answer']",
        ),
        (
            "duplicate-trap-id",
            dataclasses.replace(cfg, traps=cfg.traps + (cfg.traps[0],)),
            "duplicate trap IDs ['rug-desc']",
        ),
        ("unknown-kind", _with_tool(cfg, "submit_answer", kind="haunt"), "unknown kind 'haunt'"),
        (
            "unknown-trap-binding",
            _with_tool(cfg, "submit_answer", trap_id="ghost"),
            "binds unknown trap 'ghost'",
        ),
        (
            "unbound-trap",
            dataclasses.replace(cfg, traps=cfg.traps + (extra_trap,)),
            "trap 'orphan' has no tool binding",
        ),
        (
            "control-id-not-the-control",
            dataclasses.replace(cfg, control_trap_id="rug-desc"),
            "must be the only control trap",
        ),
        (
            "second-control",
            dataclasses.replace(
                cfg,
                traps=tuple(
                    dataclasses.replace(t, is_control=True) if t.trap_id == "tool-output" else t
                    for t in cfg.traps
                ),
            ),
            "must be the only control trap",
        ),
        ("empty-path", _with_tool(cfg, "save_note", named_path=""), "must be relative"),
        ("absolute-path", _with_tool(cfg, "save_note", named_path="/tmp/x"), "must be relative"),
        ("backslash-path", _with_tool(cfg, "save_note", named_path="\\x"), "must be relative"),
        ("dotdot-posix", _with_tool(cfg, "save_note", named_path="../x"), "contains '..'"),
        ("dotdot-inner", _with_tool(cfg, "save_note", named_path="a/../b"), "contains '..'"),
        ("dotdot-backslash", _with_tool(cfg, "save_note", named_path="a\\..\\b"), "contains '..'"),
        (
            "duplicate-named-path",
            _with_tool(cfg, "submit_answer", named_path="sync-ack.txt"),
            "duplicate named paths ['sync-ack.txt']",
        ),
    ]


_CASES = [
    pytest.param(broken, fragment, id=f"{cfg.name}-{case}")
    for cfg in (POLTERGEIST, POLTERGEIST_LEGACY)
    for case, broken, fragment in _broken(cfg)
]


@pytest.mark.parametrize(("broken", "fragment"), _CASES)
def test_validate_rejects(broken: RoomConfig, fragment: str) -> None:
    with pytest.raises(ValueError) as exc:
        broken.validate()
    message = str(exc.value)
    assert message.startswith(f"{broken.name}: ")
    assert fragment in message
