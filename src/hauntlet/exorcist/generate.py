"""Generate a guardrail bundle from a finalized run. Pure (Requirements 1, 2, 4, 5).

The content of every guardrail file is computed only from:

- the eligible traps' (content source, steered effects);
- the MCP rooms' tool lists;
- server names derived from room names (``mcp.json`` only).

Trap IDs appear only in citations, which go to the bundle manifest and never
into a guardrail file (Requirement 4.4).
"""

from __future__ import annotations

from collections.abc import Mapping

from hauntlet.core.models import RunManifest, RunScore
from hauntlet.exorcist import catalogue as cat
from hauntlet.exorcist import render as rnd
from hauntlet.exorcist.eligibility import classify
from hauntlet.exorcist.grammar import Rule
from hauntlet.exorcist.model import (
    EFFECT_ORDER,
    SOURCE_ORDER,
    BundleSpec,
    ClassifiedTrap,
    Effect,
    GuardrailItem,
    RoomThreats,
    Source,
    TrapThreat,
)
from hauntlet.exorcist.profiles import PROFILES

Eligible = tuple[ClassifiedTrap, TrapThreat]


class MissingProfile(KeyError):
    """A room in the run has no threat profile (should not happen; see test_threat_profiles)."""


def _profile(profiles: Mapping[str, RoomThreats], room: str) -> RoomThreats:
    try:
        return profiles[room]
    except KeyError:
        raise MissingProfile(f"room {room!r} has no threat profile; refusing to generate") from None


def _cites(traps: list[Eligible]) -> tuple[str, ...]:
    return tuple(sorted({c.ref for c, _ in traps}))


def _keys(traps: list[Eligible], effects: frozenset[Effect] | None) -> tuple[str, ...]:
    """The threat-class keys that selected an item, in fixed order."""
    out: list[str] = []
    if effects is None:
        sources = {t.source for _, t in traps}
        out += [f"source:{s}" for s in SOURCE_ORDER if s in sources]
    else:
        hit = set().union(*(t.effects & effects for _, t in traps)) if traps else set()
        out += [f"effect:{e}" for e in EFFECT_ORDER if e in hit]
    return tuple(out)


def _effect_keys(traps: list[Eligible], effects: frozenset[Effect]) -> tuple[str, ...]:
    return _keys(traps, effects)


def generate(
    score: RunScore, manifest: RunManifest, profiles: Mapping[str, RoomThreats] = PROFILES
) -> BundleSpec:
    classified = classify(score, manifest)
    for rm in manifest.rooms:
        _profile(profiles, rm.room)
    eligible: list[Eligible] = [
        (c, _profile(profiles, c.room).traps[c.trap_id]) for c in classified if c.eligible
    ]

    items: list[GuardrailItem] = []
    files: dict[str, bytes] = {}
    server_names: dict[str, str] = {}

    if eligible:
        _steering(eligible, items, files)
        _egress(eligible, items, files)
        _mcp(eligible, profiles, items, files, server_names)
        _sandbox(eligible, manifest, profiles, items, files)

    cited = {ref for item in items for ref in item.cites}
    no_guardrail = tuple(
        (c.ref, "no catalogue item matches this trap's threat class")
        for c, _ in eligible
        if c.ref not in cited
    )
    return BundleSpec(
        before_run_id=manifest.run_id,
        items=tuple(items),
        files=files,
        trap_classes=classified,
        no_guardrail=no_guardrail,
        permissions_suggestion=permissions_suggestion(eligible, profiles, server_names),
        mcp_server_names=server_names,
        rooms=tuple(rm.room for rm in manifest.rooms),
    )


# --------------------------------------------------------------------------- #
# item families
# --------------------------------------------------------------------------- #


def _steering(eligible: list[Eligible], items: list[GuardrailItem], files: dict[str, bytes]) -> None:
    sources = frozenset(t.source for _, t in eligible)
    chosen = {s.rule: s for s in cat.STEERING}
    picked = {s.rule: [e for e in eligible if s.selects(e[1])] for s in cat.STEERING}
    for fname, title, rules in cat.STEERING_FILES:
        present = [r for r in rules if picked[r]]
        if not present:
            continue
        path = f"{cat.STEERING_DIR}/{fname}"
        files[path] = rnd.steering_file(
            title, [(r, sources if r is Rule.DATA else frozenset()) for r in present]
        )
        for r in present:
            sel = chosen[r]
            items.append(
                GuardrailItem(
                    item_id=f"{path}#{r.value}",
                    path=path,
                    rule=r.value,
                    kind="steering",
                    selected_by=_keys(picked[r], sel.effects),
                    cites=_cites(picked[r]),
                    reason=sel.reason,
                    surfaces=cat.SURFACES["steering"],
                    enforced=False,
                    assumptions=sel.assumptions,
                )
            )


def _egress(eligible: list[Eligible], items: list[GuardrailItem], files: dict[str, bytes]) -> None:
    traps = [e for e in eligible if cat.selects(cat.EGRESS_EFFECTS, e[1])]
    if not traps:
        return
    files[cat.HOOK_FILE] = rnd.egress_hook_file()
    files[cat.GUARD_PATH] = rnd.guard_script()
    for name, _matcher in cat.EGRESS_HOOKS:
        items.append(
            GuardrailItem(
                item_id=f"{cat.HOOK_FILE}#{name}",
                path=cat.HOOK_FILE,
                rule=name,
                kind="hook",
                selected_by=_effect_keys(traps, cat.EGRESS_EFFECTS),
                cites=_cites(traps),
                reason=cat.EGRESS_REASON,
                surfaces=cat.SURFACES["hook"],
                enforced=True,
                assumptions=("A4",),
            )
        )


def _mcp(
    eligible: list[Eligible],
    profiles: Mapping[str, RoomThreats],
    items: list[GuardrailItem],
    files: dict[str, bytes],
    server_names: dict[str, str],
) -> None:
    rooms = sorted({c.room for c, _ in eligible if _profile(profiles, c.room).mcp is not None})
    entries: dict[str, dict] = {}
    for room in rooms:
        tools = _profile(profiles, room).mcp
        assert tools is not None
        name = rnd.server_name(room)
        server_names[room] = name
        entries[name] = rnd.mcp_entry(room, tools)
        traps = [e for e in eligible if e[0].room == room]
        for key, reason in (
            ("autoApprove", cat.MCP_AUTOAPPROVE_REASON),
            ("disabledTools", cat.MCP_DISABLED_REASON),
        ):
            items.append(
                GuardrailItem(
                    item_id=f"{cat.MCP_FILE}#{name}.{key}",
                    path=cat.MCP_FILE,
                    rule=f"{name}.{key}",
                    kind="mcp",
                    selected_by=(f"room:{room}",),
                    cites=_cites(traps),
                    reason=reason,
                    surfaces=cat.SURFACES["mcp"],
                    enforced=True,
                    assumptions=("A1",),
                )
            )
    if entries:
        files[cat.MCP_FILE] = rnd.mcp_file(entries)


def _sandbox(
    eligible: list[Eligible],
    manifest: RunManifest,
    profiles: Mapping[str, RoomThreats],
    items: list[GuardrailItem],
    files: dict[str, bytes],
) -> None:
    traps = [e for e in eligible if cat.selects(cat.SANDBOX_EFFECTS, e[1])]
    if not traps:
        return
    run_has_mcp = any(_profile(profiles, rm.room).mcp is not None for rm in manifest.rooms)
    files[cat.SANDBOX_FILE] = rnd.sandbox_file(run_has_mcp)
    items.append(
        GuardrailItem(
            item_id=f"{cat.SANDBOX_FILE}#networkAccess",
            path=cat.SANDBOX_FILE,
            rule="networkAccess",
            kind="sandbox",
            selected_by=_effect_keys(traps, cat.SANDBOX_EFFECTS),
            cites=_cites(traps),
            reason=cat.SANDBOX_REASON,
            surfaces=cat.SURFACES["sandbox"],
            enforced=True,
            assumptions=("A2", "A3"),
        )
    )
    if run_has_mcp:
        items.append(
            GuardrailItem(
                item_id=f"{cat.SANDBOX_FILE}#mcpSandboxing",
                path=cat.SANDBOX_FILE,
                rule="mcpSandboxing",
                kind="sandbox",
                selected_by=_effect_keys(traps, cat.SANDBOX_EFFECTS),
                cites=_cites(traps),
                reason="Stdio MCP server processes run inside the same sandbox as shell commands.",
                surfaces=cat.SURFACES["sandbox"],
                enforced=True,
                assumptions=("A3", "A5"),
            )
        )


# --------------------------------------------------------------------------- #
# permissions.yaml suggestion (Requirement 4.5): text for the manifest only
# --------------------------------------------------------------------------- #

PERMISSIONS_LABEL = (
    "user-level config (~/.kiro/settings/permissions.yaml): it affects every workspace, "
    "and you apply it yourself"
)


def permissions_suggestion(
    eligible: list[Eligible],
    profiles: Mapping[str, RoomThreats],
    server_names: Mapping[str, str],
) -> str:
    """YAML text with ``deny`` or ``ask`` rules only, each commented with its citations."""
    rules: list[tuple[tuple[str, ...], list[str]]] = []

    fetch = [e for e in eligible if cat.selects(cat.PERMS_FETCH_EFFECTS, e[1])]
    if fetch:
        rules.append((_cites(fetch), ["- capability: web_fetch", "  effect: ask"]))
        rules.append(
            (_cites(fetch), ["- capability: shell", '  match: ["curl *", "wget *"]', "  effect: ask"])
        )
    writes = [e for e in eligible if cat.selects(cat.PERMS_WRITE_EFFECTS, e[1])]
    if writes:
        rules.append((_cites(writes), ["- capability: fs_write", '  match: ["**"]', "  effect: ask"]))
    tool_traps = [e for e in eligible if cat.selects(cat.PERMS_TOOL_EFFECTS, e[1])]
    patterns: list[str] = []
    for room in sorted({c.room for c, _ in tool_traps}):
        tools = _profile(profiles, room).mcp
        if tools is None or room not in server_names:
            continue
        owners = {c.trap_id for c, _ in tool_traps if c.room == room}
        patterns += [
            f"{server_names[room]}/{tool}"
            for tool, trap in sorted(tools.steered_tools.items())
            if trap in owners
        ]
    if patterns:
        quoted = ", ".join(f'"{p}"' for p in patterns)
        rules.append((_cites(tool_traps), ["- capability: mcp", f"  match: [{quoted}]", "  effect: deny"]))

    if not rules:
        return ""
    lines = [
        "# Suggested permissions.yaml rules, generated by Hauntlet's Exorcist.",
        f"# This is {PERMISSIONS_LABEL}. Hauntlet never writes this file.",
        "# Format: https://kiro.dev/docs/permissions/ . A headless run treats ask as deny.",
        '# "Always allow" in an approval prompt saves allow rules to this file or to',
        "# ~/.kiro/workspace-roots/<hash>/permissions.yaml: review them and remove any",
        "# for the range's MCP servers before an after run.",
        "rules:",
    ]
    for cites, body in rules:
        lines.append(f"  # Addresses: {', '.join(cites)}")
        lines += [f"  {line}" for line in body]
    return "\n".join(lines) + "\n"


def eligible_classes(spec_or_eligible: list[Eligible]) -> frozenset[tuple[Source, frozenset[Effect]]]:
    """The set of eligible threat classes; EP2 says steering and hooks depend only on this."""
    return frozenset((t.source, t.effects) for _, t in spec_or_eligible)
