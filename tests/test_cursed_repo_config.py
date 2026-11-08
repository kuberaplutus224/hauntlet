"""Cursed Repo room configuration: validity, coverage and validate() rejections.

Covers:
  - Both configs validate and their manifests pass canary-core validation
    (Req 2.2, 3.5, 4.1)
  - The default room uses at least four surface kinds (Req 2.1)
  - cursed-repo-tests plants a trap in the test file (Req 3.1)
  - Several traps on one surface file are allowed (Req 2.4)
  - One rejection test per RoomConfig.validate() rule
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from hauntlet.core.models import RoomManifest
from hauntlet.core.room import Room, RoomContext, RoomMaterials, Transcript
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms.cursed_repo import config as cfg
from hauntlet.rooms.cursed_repo.config import (
    CURSED_REPO,
    CURSED_REPO_TESTS,
    RoomConfig,
    TrapDef,
)

CONFIGS = (CURSED_REPO, CURSED_REPO_TESTS)

SURFACE_KINDS = {
    "README.md": "readme",
    "AGENTS.md": "agents guide",
    "rangekit/clamp.py": "code comment",
    "pyproject.toml": "config",
    "docs/issues/42.md": "issue or TODO note",
    "tests/test_clamp.py": "test file",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_room(config: RoomConfig) -> Room:
    """A minimal Room whose manifest comes from the given config."""

    class _StubRoom:
        name = config.name

        def manifest(self) -> RoomManifest:
            return config.manifest()

        def setup(self, ctx: RoomContext) -> RoomMaterials:  # pragma: no cover
            raise NotImplementedError

        def collect(self, ctx: RoomContext, materials: RoomMaterials, transcript: Transcript | None) -> list:  # pragma: no cover
            raise NotImplementedError

        def teardown(self, ctx: RoomContext) -> None:  # pragma: no cover
            pass

    return _StubRoom()  # type: ignore[return-value]


def _trap(config: RoomConfig, trap_id: str) -> TrapDef:
    return next(t for t in config.traps if t.trap_id == trap_id)


def _with_trap(config: RoomConfig, trap_id: str, **changes: object) -> RoomConfig:
    """Return config with one trap's fields replaced."""
    traps = tuple(replace(t, **changes) if t.trap_id == trap_id else t for t in config.traps)
    return replace(config, traps=traps)


def _with_extra_trap(config: RoomConfig, **fields: object) -> RoomConfig:
    """Return config with one extra trap appended (defaults from a valid trap)."""
    base = TrapDef(
        trap_id="extra-trap",
        surface="README.md",
        slot="test_slot",
        snippet="extra.tmpl",
        source="test source",
        env_var=None,
        named_path=None,
        echo_goal=False,
    )
    return replace(config, traps=config.traps + (replace(base, **fields),))


# ---------------------------------------------------------------------------
# Valid configs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("config", CONFIGS, ids=lambda c: c.name)
def test_config_validates(config: RoomConfig) -> None:
    config.validate()  # must not raise


def test_manifests_pass_canary_core_validation() -> None:
    svc = RangeService(Store(":memory:"), {c.name: _stub_room(c) for c in CONFIGS})
    assert set(svc.rooms) == {"cursed-repo", "cursed-repo-tests"}


@pytest.mark.parametrize("config", CONFIGS, ids=lambda c: c.name)
def test_manifest_has_one_control_and_sourced_traps(config: RoomConfig) -> None:
    manifest = config.manifest()
    assert manifest.room == config.name

    controls = [t for t in manifest.traps if t.is_control]
    assert [(t.trap_id, t.surface) for t in controls] == [("security-notice", "SECURITY.md")]

    traps = [t for t in manifest.traps if not t.is_control]
    assert [t.trap_id for t in traps] == [t.trap_id for t in config.traps]
    for spec in traps:
        assert spec.source.strip(), f"{spec.trap_id} has no source"


def test_default_room_covers_at_least_four_surface_kinds() -> None:
    kinds = {SURFACE_KINDS[t.surface] for t in CURSED_REPO.traps}
    assert len(kinds) >= 4, kinds


def test_tests_room_has_trap_on_test_file() -> None:
    assert any(t.surface == "tests/test_clamp.py" for t in CURSED_REPO_TESTS.traps)


def test_two_traps_on_same_surface_are_accepted() -> None:
    config = _with_extra_trap(CURSED_REPO, trap_id="readme-second", surface="README.md", slot="test_slot")
    config.validate()  # must not raise
    assert sum(t.surface == "README.md" for t in config.traps) == 2


# ---------------------------------------------------------------------------
# validate() rejections, one per rule
# ---------------------------------------------------------------------------

def test_rejects_unknown_surface() -> None:
    bad = _with_trap(CURSED_REPO, "readme-register", surface="NOTES.md")
    with pytest.raises(ValueError, match="is not a repository file"):
        bad.validate()


def test_rejects_unknown_control_surface() -> None:
    bad = replace(CURSED_REPO, control=replace(CURSED_REPO.control, surface="NOTES.md"))
    with pytest.raises(ValueError, match="is not a repository file"):
        bad.validate()


def test_rejects_duplicate_surface_basename(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "REPO_FILES", cfg.REPO_FILES + ("docs/README.md",))
    bad = _with_extra_trap(CURSED_REPO, trap_id="docs-readme", surface="docs/README.md", slot="test_slot")
    with pytest.raises(ValueError, match="duplicate surface basenames"):
        bad.validate()


def test_rejects_unknown_slot() -> None:
    bad = _with_trap(CURSED_REPO, "readme-register", slot="bogus_slot")
    with pytest.raises(ValueError, match="unknown slot"):
        bad.validate()


def test_rejects_duplicate_slot() -> None:
    bad = _with_trap(CURSED_REPO, "todo-echo", slot="readme_slot")
    with pytest.raises(ValueError, match="duplicate slots"):
        bad.validate()


def test_rejects_absolute_named_path() -> None:
    bad = _with_trap(CURSED_REPO, "agents-preflight", named_path="/tmp/agent-preflight")
    with pytest.raises(ValueError, match="must be relative"):
        bad.validate()


def test_rejects_named_path_with_parent_dir() -> None:
    bad = _with_trap(CURSED_REPO, "agents-preflight", named_path="../agent-preflight")
    with pytest.raises(ValueError, match="contains '..'"):
        bad.validate()


def test_rejects_named_path_that_is_repo_file() -> None:
    bad = _with_trap(CURSED_REPO, "agents-preflight", named_path="docs/issues/42.md")
    with pytest.raises(ValueError, match="is a repository file"):
        bad.validate()


def test_rejects_named_path_in_task_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    # The real target file is also a repository file, so the repo-file rule
    # would fire first. Point the task scope at a non-repository path.
    monkeypatch.setattr(cfg, "TASK_SCOPE", frozenset({"rangekit/extra.py"}))
    bad = _with_trap(CURSED_REPO, "agents-preflight", named_path="rangekit/extra.py")
    with pytest.raises(ValueError, match="is in the task scope"):
        bad.validate()


def test_rejects_duplicate_named_path() -> None:
    bad = _with_trap(CURSED_REPO, "todo-echo", named_path=".agent-preflight")
    with pytest.raises(ValueError, match="duplicate named paths"):
        bad.validate()


def test_rejects_duplicate_env_var() -> None:
    bad = _with_trap(CURSED_REPO, "config-toolchain", env_var=_trap(CURSED_REPO, "readme-register").env_var)
    with pytest.raises(ValueError, match="duplicate env vars"):
        bad.validate()
