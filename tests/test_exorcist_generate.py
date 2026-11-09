"""Generator properties (exorcist task 6.7): EP2, EP3, EP4, EP5, EP16, plus payload safety.

- **EP2:** steering and hook bytes depend only on the eligible threat classes.
  Permuting levels and signals among same-class traps of a room, with a fresh
  run ID and fresh canaries, gives byte-identical steering and hook files. Two
  different rooms with the same eligible classes do too.
- **EP3:** no guardrail file contains:
  - a canary value of the run;
  - ``hauntlet-mark-`` or ``HAUNTLET-DUMMY-``;
  - a six-word run shared with any room template or fixture.

  Steering and hook files, including the guard script, also contain no trap ID
  and no room name.
- **EP4:** every generated bundle passes ``validate``. Every hook matcher is a
  documented selector or a compilable regex.
- **EP5:** a run with more eligible traps keeps every item of the smaller run,
  and nothing loosens a control.
- **EP16:** there is never a ``permissions.yaml`` file. The suggestion uses only
  ``deny`` or ``ask`` and carries the user-level label.

_Requirements (exorcist): 1.4–1.6, 2.1–2.7, 4.1–4.5, 5.1–5.4, 6.3, 6.4_
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from _exorcist_strategies import ROOMS, SyntheticRun, runs
from hypothesis import given, settings
from hypothesis import strategies as st

from hauntlet.core.canary import mint_canaries
from hauntlet.core.levels import Level
from hauntlet.core.models import RoomScore, RunManifest, RunScore, TrapScore
from hauntlet.exorcist import catalogue as cat
from hauntlet.exorcist.generate import PERMISSIONS_LABEL, generate
from hauntlet.exorcist.profiles import PROFILES
from hauntlet.exorcist.validate import BundleInvalid, matcher_ok, validate

REPO = Path(__file__).resolve().parent.parent
ROOM_NAMES = sorted(ROOMS)
TRAP_IDS = sorted({t.trap_id for r in ROOMS.values() for t in r.manifest().traps})
_WORD = re.compile(r"[a-z0-9]+")


def _six_grams(text: str) -> set[tuple[str, ...]]:
    words = _WORD.findall(text.lower())
    return {tuple(words[i : i + 6]) for i in range(len(words) - 5)}


def _template_grams() -> set[tuple[str, ...]]:
    grams: set[tuple[str, ...]] = set()
    for sub in ("templates", "fixtures"):
        for path in (REPO / "src/hauntlet/rooms").glob(f"*/{sub}/**/*"):
            if path.is_file():
                try:
                    grams |= _six_grams(path.read_text(encoding="utf-8"))
                except UnicodeDecodeError:
                    continue
    return grams


TEMPLATE_GRAMS = _template_grams()


def _steering_and_hooks(files) -> dict[str, bytes]:
    return {p: b for p, b in files.items() if p.startswith((".kiro/steering/", ".kiro/hooks/"))}


# --------------------------------------------------------------------------- #
# EP2
# --------------------------------------------------------------------------- #


def _same_class_groups(room: str) -> list[list[str]]:
    groups: dict[tuple, list[str]] = {}
    for trap_id, threat in PROFILES[room].traps.items():
        groups.setdefault((threat.source, threat.effects), []).append(trap_id)
    return [sorted(g) for g in groups.values()]


@st.composite
def permuted_pairs(draw) -> tuple[SyntheticRun, SyntheticRun]:
    a: SyntheticRun = draw(runs())
    new_id = draw(st.text(alphabet="ABCDEFGHJKMNPQRSTUVWXYZ0123456789", min_size=10, max_size=10))
    rooms = []
    for rs in a.score.rooms:
        by_id = {t.trap_id: t for t in rs.per_trap}
        permuted = dict(by_id)
        for group in _same_class_groups(rs.room):
            order = draw(st.permutations(group))
            for src, dst in zip(group, order):
                old = by_id[src]
                permuted[dst] = replace(old, trap_id=dst, is_control=by_id[dst].is_control)
        rooms.append(replace(rs, per_trap=tuple(permuted[t.trap_id] for t in rs.per_trap)))
    manifest = RunManifest(run_id=new_id, rooms=a.manifest.rooms)
    score = replace(a.score, run_id=new_id, rooms=tuple(rooms))
    return a, SyntheticRun(score, manifest, tuple(mint_canaries(manifest)))


@settings(max_examples=150, deadline=None)
@given(permuted_pairs())
def test_ep2_steering_and_hooks_depend_only_on_classes(pair) -> None:
    a, b = pair
    assert _steering_and_hooks(generate(a.score, a.manifest).files) == _steering_and_hooks(
        generate(b.score, b.manifest).files
    )


def _single_trap_run(room: str, trap_id: str, run_id: str) -> tuple[RunScore, RunManifest]:
    rm = ROOMS[room].manifest()
    per_trap = tuple(
        TrapScore(t.trap_id, t.is_control, Level.L3 if t.trap_id == trap_id else Level.L0, False,
                  ("acted",) if t.trap_id == trap_id else ())
        for t in rm.traps
    )
    rs = RoomScore(room, Level.L3, False, (), per_trap, True, True)
    return RunScore(run_id, (rs,), Level.L3), RunManifest(run_id, (rm,))


def test_ep2_different_rooms_same_class_same_bytes() -> None:
    # (repo_file, {file_write}) in two different rooms with different trap IDs.
    a = generate(*_single_trap_run("cursed-repo", "agents-preflight", "runAAAAAAAA"))
    b = generate(*_single_trap_run("cursed-repo-tests", "tests-ci-ack", "runBBBBBBBB"))
    assert _steering_and_hooks(a.files) == _steering_and_hooks(b.files)
    assert [i.item_id for i in a.items] == [i.item_id for i in b.items]
    assert {c for i in a.items for c in i.cites} == {"cursed-repo/agents-preflight"}
    assert {c for i in b.items for c in i.cites} == {"cursed-repo-tests/tests-ci-ack"}


# --------------------------------------------------------------------------- #
# EP3, EP4, EP16
# --------------------------------------------------------------------------- #


@settings(max_examples=200, deadline=None)
@given(runs())
def test_ep3_ep4_ep16_content_and_format(run: SyntheticRun) -> None:
    spec = generate(run.score, run.manifest)
    validate(spec.files)  # EP4: raises on any format problem
    if cat.MCP_FILE in spec.files:  # Requirement 2.3: no tool ever skips approval
        servers = json.loads(spec.files[cat.MCP_FILE])["mcpServers"]
        assert servers and all(entry["autoApprove"] == [] for entry in servers.values())

    values = [c.value for c in run.canaries if c.value]
    for path, data in spec.files.items():
        text = data.decode("utf-8")
        for v in values:
            assert v not in text, f"{path} carries a canary value"
        assert "hauntlet-mark-" not in text and "HAUNTLET-DUMMY-" not in text, path
        shared = _six_grams(text) & TEMPLATE_GRAMS
        assert not shared, f"{path} shares template wording: {sorted(shared)[:3]}"
        if path.startswith((".kiro/steering/", ".kiro/hooks/")):
            for name in ROOM_NAMES:
                assert name not in text, f"{path} names room {name!r}"
            for trap_id in TRAP_IDS:
                assert trap_id not in text, f"{path} names trap {trap_id!r}"
        if path.endswith(".json") and "/hooks/" in path:
            for hook in json.loads(text)["hooks"]:
                assert matcher_ok(hook["matcher"])

    # EP16
    assert not any(Path(p).name == "permissions.yaml" for p in spec.files)
    sugg = spec.permissions_suggestion
    if sugg:
        assert PERMISSIONS_LABEL in sugg
        effects = re.findall(r"effect:\s*(\w+)", sugg)
        assert effects and set(effects) <= {"deny", "ask"}
        for v in values:
            assert v not in sugg
        assert "hauntlet-mark-" not in sugg and "HAUNTLET-DUMMY-" not in sugg

    # Requirement 1.5/1.6: no item cites a non-eligible trap; nothing eligible means no files.
    eligible = {c.ref for c in spec.trap_classes if c.eligible}
    assert {ref for i in spec.items for ref in i.cites} <= eligible
    if not eligible:
        assert spec.files == {} and spec.items == () and sugg == ""
    else:
        cited = {ref for i in spec.items for ref in i.cites}
        assert cited | {ref for ref, _ in spec.no_guardrail} == eligible
    # Requirement 4.4: citations never reach a guardrail file.
    for path, data in spec.files.items():
        if path.startswith((".kiro/steering/", ".kiro/hooks/")):
            assert all(ref not in data.decode() for ref in eligible), path


# --------------------------------------------------------------------------- #
# EP5
# --------------------------------------------------------------------------- #

_LOOSENING = (
    re.compile(r'"autoApprove":\s*\[\s*"'),  # any non-empty autoApprove
    re.compile(r'"networkAccess":\s*"(?!DEFAULT_BLOCKED")'),
    re.compile(r'"disabled":\s*true'),
    re.compile(r"effect:\s*allow"),
)


@st.composite
def superset_pairs(draw) -> tuple[SyntheticRun, SyntheticRun]:
    a: SyntheticRun = draw(runs())
    rooms = []
    for rs in a.score.rooms:
        per_trap = []
        for t in rs.per_trap:
            if not t.is_control and draw(st.booleans()):
                t = replace(t, level=max(t.level, Level(draw(st.integers(1, 4)))))
            per_trap.append(t)
        rooms.append(replace(rs, per_trap=tuple(per_trap)))
    return a, SyntheticRun(replace(a.score, rooms=tuple(rooms)), a.manifest, a.canaries)


@settings(max_examples=150, deadline=None)
@given(superset_pairs())
def test_ep5_monotone_tightening(pair) -> None:
    small, big = pair
    s, b = generate(small.score, small.manifest), generate(big.score, big.manifest)
    assert {i.item_id for i in s.items} <= {i.item_id for i in b.items}
    for spec in (s, b):
        blob = "\n".join(d.decode() for d in spec.files.values()) + spec.permissions_suggestion
        for rx in _LOOSENING:
            assert not rx.search(blob), rx.pattern
        for path, data in spec.files.items():
            if path.startswith(".kiro/steering/"):
                assert "may " not in data.decode().lower() and "allowed to" not in data.decode().lower()


# --------------------------------------------------------------------------- #
# Examples
# --------------------------------------------------------------------------- #


def test_validate_rejects_bad_files() -> None:
    good = generate(*_single_trap_run("poltergeist", "rug-desc", "runCCCCCCCC")).files
    validate(good)
    mcp = json.loads(good[cat.MCP_FILE])
    server = next(iter(mcp["mcpServers"]))

    def bad(path: str, data: bytes, rule: str) -> None:
        with pytest.raises(BundleInvalid, match=rule):
            validate({**good, path: data})

    def mcp_with(**kw) -> bytes:
        doc = json.loads(good[cat.MCP_FILE])
        doc["mcpServers"][server].update(kw)
        return json.dumps(doc).encode()

    bad(cat.MCP_FILE, mcp_with(autoApprove=["*"]), "must be empty")
    bad(cat.MCP_FILE, mcp_with(autoApprove=["get_note"]), "must be empty")
    bad(cat.MCP_FILE, mcp_with(autoApprove=["list_topics", "submit_answer"]), "must be empty")
    bad(cat.MCP_FILE, mcp_with(disabled=True), "must not be disabled")
    bad(cat.MCP_FILE, mcp_with(oauth={}), "only")
    bad(cat.SANDBOX_FILE, b'{"enabled": true, "networkAccess": "DEFAULT_ALLOWED"}', "DEFAULT_BLOCKED")
    bad(cat.SANDBOX_FILE, b'{"enabled": false}', "enabled must be true")
    bad(".kiro/steering/x.md", b"\n---\ninclusion: always\n---\n", "very first")
    bad(".kiro/steering/x.md", b"---\ninclusion: manual\n---\n", "inclusion: always")
    bad(".kiro/settings/permissions.yaml", b"rules: []\n", "file kind")
    hooks = json.loads(good[cat.HOOK_FILE])
    hooks["hooks"][0]["matcher"] = "("
    bad(cat.HOOK_FILE, json.dumps(hooks).encode(), "neither a selector")
    hooks["hooks"][0]["matcher"] = "web"
    hooks["hooks"][0]["trigger"] = "preToolUse"
    bad(cat.HOOK_FILE, json.dumps(hooks).encode(), "unknown trigger")
    bad(cat.HOOK_FILE, b"[]", "exactly version and hooks")


def test_poltergeist_bundle_shape() -> None:
    spec = generate(*_single_trap_run("poltergeist", "rug-desc", "runDDDDDDDD"))
    mcp = json.loads(spec.files[cat.MCP_FILE])["mcpServers"]["hauntlet_poltergeist"]
    assert mcp["autoApprove"] == []
    assert mcp["disabledTools"] == ["check_health", "report_telemetry", "save_note"]
    assert mcp["args"][-2:] == ["--run", "<after-run-id>"]
    assert json.loads(spec.files[cat.SANDBOX_FILE]) == {
        "enabled": True, "networkAccess": "DEFAULT_BLOCKED", "mcpSandboxing": True,
    }
    assert 'match: ["hauntlet_poltergeist/report_telemetry"]' in spec.permissions_suggestion
    assert all("A1" in i.assumptions for i in spec.items if i.kind == "mcp")
    assert all("A4" in i.assumptions for i in spec.items if i.kind == "hook")


def test_payload_safety_on_guards_and_rendered_files(tmp_path: Path) -> None:
    spec = generate(*_single_trap_run("poltergeist", "rug-desc", "runEEEEEEEE"))
    spec2 = generate(*_single_trap_run("cursed-repo", "readme-register", "runFFFFFFFF"))
    for i, s in enumerate((spec, spec2)):
        for rel, data in s.files.items():
            out = tmp_path / str(i) / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
    script = REPO / "scripts/check_payload_safety.py"
    for target in (REPO / "src/hauntlet/exorcist/guards", tmp_path):
        r = subprocess.run([sys.executable, str(script), str(target)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_guard_name_rule_matches_the_grammar() -> None:
    from hauntlet.exorcist import grammar

    text = (REPO / "src/hauntlet/exorcist/guards/credential_egress.py").read_text()
    assert f're.compile(r"{grammar.CREDENTIAL_NAME.pattern}", re.IGNORECASE)' in text
    assert f"MIN_SECRET_LEN = {grammar.MIN_SECRET_LEN}" in text
