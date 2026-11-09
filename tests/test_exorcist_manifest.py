"""Bundle manifest (exorcist Requirements 4.1–4.6, 7.1–7.3, task 7.3).

- every guardrail file's digest in ``bundle.json`` matches the written bytes;
- ``EXORCISM.md`` contains every cited trap, each cannot-fix item and each
  assumption;
- each real-client room gets cited manual steps; demo-only rooms say so;
- the Requirement 4.6 statement appears exactly when the egress hook or the
  SECRETS rule is in the bundle;
- an empty bundle says no trap was eligible and has no guardrail files.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from _exorcist_strategies import SyntheticRun, runs
from hypothesis import HealthCheck, given, settings

from hauntlet.core.levels import Level
from hauntlet.core.models import RoomScore, RunManifest, RunScore, TrapScore
from hauntlet.exorcist.generate import PERMISSIONS_LABEL, generate
from hauntlet.exorcist.grammar import Rule
from hauntlet.exorcist.manifest import DOCS, MANIFEST_JSON, MANIFEST_MD, REAL_CLIENT_ROOMS
from hauntlet.exorcist.texts import ASSUMPTIONS, CANNOT_FIX, DEMO_ENV_NOTE
from hauntlet.exorcist.writer import write_bundle
from hauntlet.rooms import default_rooms

ROOMS = default_rooms()


def _run(levels: dict[tuple[str, str], int], run_id: str = "manifestRUN") -> tuple[RunScore, RunManifest]:
    rooms = sorted({r for r, _ in levels})
    rms = tuple(ROOMS[r].manifest() for r in rooms)
    scores = []
    for rm in rms:
        per_trap = tuple(
            TrapScore(t.trap_id, t.is_control, Level(levels.get((rm.room, t.trap_id), 0)), False, ())
            for t in rm.traps
        )
        scores.append(RoomScore(rm.room, max(p.level for p in per_trap), False, (), per_trap, True, True))
    return RunScore(run_id, tuple(scores), Level.L0), RunManifest(run_id, rms)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(runs())
def test_manifest_matches_the_bundle(tmp_path_factory, run: SyntheticRun) -> None:
    spec = generate(run.score, run.manifest)
    tmp = tmp_path_factory.mktemp("m")
    bid, bdir = write_bundle(tmp / "exorcist", spec, created_at=42.0)
    doc = json.loads((bdir / MANIFEST_JSON).read_text())
    md = (bdir / MANIFEST_MD).read_text()

    # digests
    assert set(doc["digests"]) == set(spec.files)
    for rel, digest in doc["digests"].items():
        assert hashlib.sha256((bdir / rel).read_bytes()).hexdigest() == digest
    assert doc["bundle_id"] == bid and doc["before_run_id"] == run.manifest.run_id
    assert doc["created_at"] == 42.0

    # citations and classes
    for item in spec.items:
        for ref in item.cites:
            assert f"`{ref}`" in md or ref in md
    for c in spec.trap_classes:
        assert f"`{c.ref}`" in md

    # cannot-fix and assumptions, verbatim
    for title, text in CANNOT_FIX:
        assert title in md and text in md
    for key, text in ASSUMPTIONS.items():
        assert f"**{key}.** {text}" in md
    assert len(doc["cannot_fix"]) == len(CANNOT_FIX)

    # Requirement 4.6
    has_note = any(i.kind == "hook" or i.rule == Rule.SECRETS.value for i in spec.items)
    assert (DEMO_ENV_NOTE in md) == has_note
    assert (doc["demo_env_note"] == DEMO_ENV_NOTE) == has_note

    # Requirement 4.5: the suggestion is labelled and lives only in the manifest
    if spec.permissions_suggestion:
        assert PERMISSIONS_LABEL in md or "user-level config" in md
        assert spec.permissions_suggestion.strip() in md
    assert not list(bdir.rglob("permissions.yaml"))

    # Requirement 7.1: steps per room, with doc URLs; demo-only rooms say so
    for room in spec.rooms:
        if room in REAL_CLIENT_ROOMS:
            section = md.split(f"### `{room}` with real Kiro", 1)[1]
            assert DOCS["steering"] in section and DOCS["permissions"] in section
            assert "Always allow" in section
            assert "hauntlet exorcist delta --bundle" in section
        else:
            assert f"### `{room}`\n\nThis room has no real-client entry point." in md


def test_empty_bundle_says_no_trap_was_eligible(tmp_path: Path) -> None:
    spec = generate(*_run({("cursed-repo", "security-notice"): 0}))
    _bid, bdir = write_bundle(tmp_path / "exorcist", spec, created_at=1.0)
    assert not (bdir / ".kiro").exists()
    md = (bdir / MANIFEST_MD).read_text()
    assert "No trap was eligible" in md
    assert json.loads((bdir / MANIFEST_JSON).read_text())["items"] == []


@pytest.mark.parametrize(
    ("levels", "expect_note"),
    [
        ({("cursed-repo", "todo-echo"): 2}, False),  # echo only: no hook, no SECRETS
        ({("cursed-repo", "agents-preflight"): 3}, True),  # file_write selects the hook
        ({("poltergeist", "rug-desc"): 4}, True),  # secret_send selects SECRETS and the hook
    ],
)
def test_demo_env_note_presence(tmp_path: Path, levels, expect_note: bool) -> None:
    spec = generate(*_run(levels))
    _bid, bdir = write_bundle(tmp_path / "exorcist", spec, created_at=1.0)
    assert (DEMO_ENV_NOTE in (bdir / MANIFEST_MD).read_text()) == expect_note


def test_poltergeist_steps_cover_mcp_sandbox_and_hook(tmp_path: Path) -> None:
    spec = generate(*_run({("poltergeist", "rug-desc"): 4}))
    _bid, bdir = write_bundle(tmp_path / "exorcist", spec, created_at=1.0)
    section = (bdir / MANIFEST_MD).read_text().split("### `poltergeist` with real Kiro", 1)[1]
    for needle in ("<after-run-id>", DOCS["mcp"], DOCS["sandbox"], DOCS["headless"], "(A4)", "(A1)"):
        assert needle in section, needle
    # Checkpoint-8 review: the interactive IDE is the supported path for MCP rooms,
    # a headless run denies the task's calls, and nothing suggests auto-approving.
    assert "Use the interactive IDE" in section
    assert "headless CLI run treats every ask as a deny" in section
    assert "every MCP call asks for approval" in section
    assert "--no-interactive" not in section
    assert "Do not add tools to `autoApprove`." in section
    suggestions = [
        s for s in re.split(r"(?<=[.!?])\s+", section)
        if re.search(r"\badd\b[^.]*autoApprove", s, re.IGNORECASE) and not s.startswith("Do not add")
    ]
    assert suggestions == [], suggestions


def test_file_room_steps_may_use_headless(tmp_path: Path) -> None:
    # Parlor has no MCP server, so headless stays an option there.
    spec = generate(*_run({("parlor", "notice-visible"): 1}))
    _bid, bdir = write_bundle(tmp_path / "exorcist", spec, created_at=1.0)
    section = (bdir / MANIFEST_MD).read_text().split("### `parlor` with real Kiro", 1)[1]
    assert "--no-interactive" in section and "--sandbox" in section
