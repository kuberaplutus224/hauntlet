"""Behaviour changes only through config (exorcist Requirements 8.6, 9.2, 9.3, 9.4; EP8; task 13.3, 13.5).

- **EP8 / 9.3:** every action whose outcome differs from the baseline carries an
  attribution; for each attributed item, removing only that item from the
  bundle restores the baseline outcome of the actions it alone denied.
- **9.2 golden:** the demo agent's action trace and per-trap levels are pinned,
  under the baseline and under the generated bundle, for every demo room.
- **4.6:** no Poltergeist after-change is attributed to the credential-egress
  hook or the SECRETS rule; a file-room guard/SECRETS attribution cites A4 in
  the manifest.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from _demo_support import DEMO_ROOMS, drive

from hauntlet.agents.demo import DemoAgent, baseline_for
from hauntlet.exorcist.generate import generate
from hauntlet.exorcist.manifest import MANIFEST_MD
from hauntlet.exorcist.profiles import profile_for, real_client_env
from hauntlet.exorcist.writer import write_bundle

MCP_ROOMS = ("poltergeist", "poltergeist-legacy")


def _key(entry) -> tuple[str, str, str]:
    tool_id, where, source, _proceeded, _ids = entry
    return (tool_id, where, source)


def _trace(room: str, config_dir: Path, scratch: Path) -> list:
    agent = DemoAgent(config_dir, real_client_env)
    drive(room, scratch, agent)
    return agent.trace


@pytest.fixture
def built(tmp_path_factory):
    """Per room: baseline trace, bundle dir, bundle spec, bundle trace."""
    def build(room: str):
        tmp = tmp_path_factory.mktemp("c")
        base_dir = baseline_for(tmp / "baseline", room)
        base_agent = DemoAgent(base_dir, real_client_env)
        base = drive(room, tmp / "before", base_agent)
        spec = generate(base.score, base.manifest)
        _bid, bundle = write_bundle(tmp / "ex", spec, created_at=1.0)
        bundle_agent = DemoAgent(bundle, real_client_env)
        bdriven = drive(room, tmp / "after", bundle_agent)
        return {
            "tmp": tmp, "baseline_trace": base_agent.trace, "bundle": bundle, "spec": spec,
            "bundle_trace": bundle_agent.trace, "before": base, "after": bdriven,
        }
    return build


@pytest.mark.parametrize("room", DEMO_ROOMS)
def test_every_differing_outcome_has_an_attribution(built, room: str) -> None:
    b = built(room)
    base = {_key(e): e[3] for e in b["baseline_trace"]}  # key -> proceeded
    assert all(proceeded for proceeded in base.values()), "baseline obeys everything"
    for entry in b["bundle_trace"]:
        tool_id, where, source, proceeded, ids = entry
        if base.get((tool_id, where, source)) and not proceeded:
            assert ids, f"a differing outcome with no attribution: {entry}"
        if not proceeded:
            assert ids  # 9.3: no skip without an attribution


@pytest.mark.parametrize("room", DEMO_ROOMS)
def test_removing_all_guardrails_restores_the_baseline(built, room: str) -> None:
    # The strongest causal proof: with the config stripped, the demo behaves
    # exactly as on the baseline. So only the config can change its behaviour.
    b = built(room)
    stripped = b["tmp"] / "stripped"
    shutil.copytree(b["bundle"], stripped)
    shutil.rmtree(stripped / ".kiro", ignore_errors=True)
    baseline_for(stripped, room)  # re-add the bare baseline (autoApprove ["*"] for MCP)
    trace = _trace(room, stripped, b["tmp"] / "stripped-run")
    assert [_norm(e) for e in trace] == [_norm(e) for e in b["baseline_trace"]]


@pytest.mark.parametrize("room", DEMO_ROOMS)
def test_each_attributed_item_is_necessary_and_only_relaxes(built, room: str) -> None:
    b = built(room)
    bundle_outcome = {_key(e): e[3] for e in b["bundle_trace"]}
    items = {i for _t, _w, _s, _p, ids in b["bundle_trace"] for i in ids}
    assert items, "the bundle denied at least one action"
    for item_id in sorted(items):
        variant = b["tmp"] / f"v-{abs(hash(item_id))}"
        _remove_item(b["bundle"], variant, item_id)
        trace = _trace(room, variant, b["tmp"] / f"vr-{abs(hash(item_id))}")
        # The removed item no longer attributes any action.
        assert all(item_id not in ids for *_x, ids in trace), f"{item_id} still attributed after removal"
        # Removing a defence only relaxes: nothing that proceeded now skips.
        variant_outcome = {_key(e): e[3] for e in trace}
        for key, proceeded in bundle_outcome.items():
            if proceeded:
                assert variant_outcome.get(key) is True, f"removing {item_id} tightened {key}"


@pytest.mark.parametrize("room", DEMO_ROOMS)
def test_solo_denied_actions_are_restored_by_removing_their_item(built, room: str) -> None:
    # EP8's literal clause, where it applies: an action denied by exactly one
    # item proceeds once that item is removed. May be vacuous when defences overlap.
    b = built(room)
    solo: dict[str, list[tuple]] = {}
    for tool_id, where, source, proceeded, ids in b["bundle_trace"]:
        if not proceeded and len(ids) == 1:
            solo.setdefault(ids[0], []).append((tool_id, where, source))
    for item_id, actions in solo.items():
        variant = b["tmp"] / f"s-{abs(hash(item_id))}"
        _remove_item(b["bundle"], variant, item_id)
        outcome = {_key(e): e[3] for e in _trace(room, variant, b["tmp"] / f"sr-{abs(hash(item_id))}")}
        for key in actions:
            assert outcome.get(key) is True, f"removing {item_id} did not restore {key}"


def _norm(entry) -> tuple:
    # Compare traces ignoring denier IDs (baseline has none); outcomes must match.
    tool_id, where, source, proceeded, _ids = entry
    return (tool_id, where, source, proceeded)


@pytest.mark.parametrize("room", DEMO_ROOMS)
def test_golden_trace_and_levels(built, room: str) -> None:
    b = built(room)
    # Baseline obeys every proposed action; the bundle denies the trap actions.
    assert all(e[3] for e in b["baseline_trace"])
    assert any(not e[3] for e in b["bundle_trace"])
    before = _levels(b["before"].score, room)
    after = _levels(b["after"].score, room)
    # Requirement 8.3 / prediction: before is L3+ ; after is clean with Detected.
    assert max(before.values()) >= 3
    rs_after = b["after"].score.room(room)
    assert int(rs_after.worst_level) == 0 and rs_after.detected and rs_after.task_completed
    assert rs_after.false_positives == ()


@pytest.mark.parametrize("room", MCP_ROOMS)
def test_poltergeist_changes_not_attributed_to_guard_or_secrets(built, room: str) -> None:
    b = built(room)
    for _t, _w, _s, proceeded, ids in b["bundle_trace"]:
        if not proceeded:
            assert not any("credential-egress" in i for i in ids), ids
            assert not any(i.endswith("#SECRETS") for i in ids), ids


@pytest.mark.parametrize("room", DEMO_ROOMS)
def test_changed_by_is_precise_and_poltergeist_excludes_guard_secrets_sandbox(tmp_path, room: str) -> None:
    """Requirement 4.6: 'changed by' holds only items that actually denied the trap's actions.

    Every changed-by item is in the global demo attributions, and in the
    Poltergeist rooms no trap's changed-by names a credential-egress hook, the
    SECRETS rule or a sandbox item (the empty environment and the absence of
    shell actions mean none of them fire there).
    """
    from hauntlet.core.service import RangeService
    from hauntlet.core.store import Store
    from hauntlet.exorcist import report as exreport
    from hauntlet.exorcist.service import ExorcistService
    from hauntlet.rooms import default_rooms

    svc = RangeService(Store(":memory:"), default_rooms(), base_url="http://range.test")
    ex = ExorcistService(svc, tmp_path / "ex", clock=lambda: 1.0)
    res = ex.demo(room)
    global_attrib = set(res.after.denials)
    mcp = profile_for(room).mcp is not None
    saw_changed = False
    for td in res.delta.traps:
        assert td.changed_observed
        saw_changed = saw_changed or bool(td.changed_by)
        for item in td.changed_by:
            assert item in global_attrib, f"{td.ref}: {item} not in global attributions"
            if mcp:
                assert "credential-egress" not in item, f"{td.ref}: guard in changed_by"
                assert not item.endswith("#SECRETS"), f"{td.ref}: SECRETS in changed_by"
                assert "sandbox.json" not in item, f"{td.ref}: sandbox in changed_by"
    assert saw_changed, "the bundle changed at least one trap"
    # The report renames the generated list and marks A4-dependent items.
    text = exreport.render_text(res.delta)
    assert "generated for this trap:" in text and "changed by:" in text and "guardrails:" not in text
    if not mcp:
        assert "(depends on A4)" in text  # file-room guard/SECRETS attributions are marked


@pytest.mark.parametrize("room", ["threshold", "cursed-repo", "cursed-repo-tests"])
def test_file_room_guard_and_secrets_cite_a4(built, room: str) -> None:
    b = built(room)
    md = (b["bundle"] / MANIFEST_MD).read_text()
    for item in b["spec"].items:
        if item.kind == "hook" or item.rule == "SECRETS":
            assert "A4" in item.assumptions
    # The manifest states A4 next to those items.
    assert "A4" in md


def _levels(score, room: str) -> dict[str, int]:
    rs = score.room(room)
    return {t.trap_id: int(t.level) for t in rs.per_trap if not t.is_control}


# --------------------------------------------------------------------------- #
# removing a single guardrail item from a written bundle
# --------------------------------------------------------------------------- #


def _remove_item(bundle: Path, dest: Path, item_id: str) -> None:
    """Copy ``bundle`` to ``dest`` with the one guardrail item removed.

    Steering bullets and MCP/sandbox keys are not digest-gated by the
    interpreter, so editing them in place is enough; a removed hook entry leaves
    the guard script (which is digest-gated) untouched.
    """
    shutil.copytree(bundle, dest)
    rel, _, rule = item_id.partition("#")
    path = dest / rel
    if rel.endswith(".md"):
        from hauntlet.exorcist.grammar import Rule, parse

        target = Rule(rule)
        kept = []
        for ln in path.read_text().splitlines():
            if ln.startswith("- "):
                parsed = parse(ln[2:])
                if parsed is not None and parsed[0] is target:
                    continue  # drop this bullet
            kept.append(ln)
        path.write_text("\n".join(kept) + "\n")
    elif rel.endswith("credential-egress.json"):
        doc = json.loads(path.read_text())
        doc["hooks"] = [h for h in doc["hooks"] if h["name"] != rule]
        path.write_text(json.dumps(doc, indent=2) + "\n")
    elif rel.endswith("mcp.json"):
        doc = json.loads(path.read_text())
        server, _, key = rule.partition(".")
        if key == "autoApprove":
            doc["mcpServers"][server]["autoApprove"] = ["*"]  # baseline: obey everything
        elif key == "disabledTools":
            doc["mcpServers"][server]["disabledTools"] = []
        path.write_text(json.dumps(doc, indent=2) + "\n")
    elif rel.endswith("sandbox.json"):
        path.unlink()  # baseline has no sandbox
    else:  # pragma: no cover
        raise AssertionError(f"unknown item to remove: {item_id}")
