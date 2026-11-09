"""Threat-profile coverage (exorcist approved change D15, task 5.4).

For every registered room:

- every non-control trap has a profile;
- no profile names an unknown trap or a control;
- every effect set is non-empty;
- each file room's ``real_client_env`` equals the environment keys its
  ``setup`` plants;
- the rooms whose real clients get nothing (Poltergeist, Parlor) declare none.

For MCP rooms:

- task tools and steered tools are advertised tool names;
- the two sets are disjoint;
- ``relay_tools`` is a subset of ``steered_tools``;
- each steered tool's trap is a non-control trap;
- every advertised tool is either a task tool or not needed by the task, so the
  generator can compute ``disabledTools``.

_Requirements (exorcist): 8.9, 13.1, 13.2_
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.exorcist.model import Effect, McpTools, RoomThreats, Source, TrapThreat
from hauntlet.exorcist.profiles import PROFILES, profile_for, real_client_env
from hauntlet.rooms import default_rooms
from hauntlet.rooms.poltergeist.server import TOOL_ARGS

ROOMS = default_rooms()
FILE_ROOMS = ("threshold", "cursed-repo", "cursed-repo-tests")
NO_ENV_ROOMS = ("poltergeist", "poltergeist-legacy", "parlor")
MCP_ROOMS = ("poltergeist", "poltergeist-legacy")

rooms = pytest.mark.parametrize("name", sorted(ROOMS))


def test_every_registered_room_has_exactly_one_profile() -> None:
    assert set(PROFILES) == set(ROOMS)
    assert set(FILE_ROOMS) | set(NO_ENV_ROOMS) == set(ROOMS)


@rooms
def test_profiles_cover_exactly_the_non_control_traps(name: str) -> None:
    manifest = ROOMS[name].manifest()
    non_control = {t.trap_id for t in manifest.traps if not t.is_control}
    controls = {t.trap_id for t in manifest.traps if t.is_control}
    profile = profile_for(name)
    assert set(profile.traps) == non_control
    assert not set(profile.traps) & controls
    for trap_id, threat in profile.traps.items():
        assert isinstance(threat.source, Source), trap_id
        assert threat.effects and all(isinstance(e, Effect) for e in threat.effects), trap_id


@pytest.mark.parametrize("name", FILE_ROOMS)
def test_file_room_env_names_match_what_setup_plants(name: str, tmp_path: Path) -> None:
    service = RangeService(Store(":memory:"), ROOMS)
    run_id = service.start_run([name]).run.run_id
    ctx, materials = service.setup_room(run_id, name, tmp_path)
    try:
        assert profile_for(name).real_client_env == frozenset(materials.env)
        assert real_client_env(materials) == materials.env
        assert materials.env, "file rooms plant dummy keys"
    finally:
        ROOMS[name].teardown(ctx)


@pytest.mark.parametrize("name", NO_ENV_ROOMS)
def test_rooms_whose_real_clients_get_no_env_declare_none(name: str, tmp_path: Path) -> None:
    assert profile_for(name).real_client_env == frozenset()
    service = RangeService(Store(":memory:"), ROOMS)
    run_id = service.start_run([name]).run.run_id
    ctx, materials = service.setup_room(run_id, name, tmp_path)
    try:
        assert real_client_env(materials) == {}
    finally:
        ROOMS[name].teardown(ctx)


@pytest.mark.parametrize("name", MCP_ROOMS)
def test_mcp_tool_lists(name: str) -> None:
    mcp = profile_for(name).mcp
    assert mcp is not None
    advertised = set(TOOL_ARGS)
    assert set(mcp.tools) == advertised
    assert set(mcp.not_needed()) == advertised - set(mcp.task_tools)
    assert set(mcp.task_tools) <= advertised
    assert set(mcp.steered_tools) <= advertised
    assert not set(mcp.task_tools) & set(mcp.steered_tools)
    assert mcp.relay_tools <= set(mcp.steered_tools)
    assert mcp.relay_tools, "the rug-pull trap steers a relay tool"
    non_control = {t.trap_id for t in ROOMS[name].manifest().traps if not t.is_control}
    assert set(mcp.steered_tools.values()) <= non_control


@pytest.mark.parametrize("name", sorted(set(ROOMS) - set(MCP_ROOMS)))
def test_non_mcp_rooms_have_no_tool_lists(name: str) -> None:
    assert profile_for(name).mcp is None


def test_unknown_room_names_the_known_rooms() -> None:
    with pytest.raises(KeyError, match="known rooms"):
        profile_for("attic")


def test_model_rejects_invalid_profiles() -> None:
    with pytest.raises(ValueError):
        TrapThreat(Source.REPO_FILE, frozenset())
    with pytest.raises(TypeError):
        TrapThreat("repo_file", frozenset({Effect.ECHO}))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        McpTools(tools=("a",), task_tools=("a",), steered_tools={"a": "t"}, relay_tools=frozenset())
    with pytest.raises(ValueError):
        McpTools(tools=("a", "b"), task_tools=("a",), steered_tools={"b": "t"}, relay_tools=frozenset({"c"}))
    with pytest.raises(ValueError):
        McpTools(tools=("a",), task_tools=("a",), steered_tools={"b": "t"}, relay_tools=frozenset())
    with pytest.raises(ValueError):
        RoomThreats(traps={})
