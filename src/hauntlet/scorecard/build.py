"""Build the view model from the inputs (design.md "Builder rules"). Pure.

Every state rule lives here: the hero, grey states, controls, the mapping from
each delta change to an after state and marker, pills, room summaries and trap
cards. The builder never computes a level, a class or a change: it shows what
``RunScore``, ``RunManifest``, ``bundle.json`` and the delta document say.

Strings copied from ``bundle.json`` or the delta pass through the pattern
redactor once more (they should hold no canary value; this is belt and braces).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from hauntlet.core.levels import Level, Signal
from hauntlet.core.models import RoomScore, RunManifest, RunScore, TrapScore
from hauntlet.exorcist import CLASS_TEXT
from hauntlet.exorcist.delta import (
    AFTER_NOT_RUN as D_AFTER_NOT_RUN,
    LOWER as D_LOWER,
    NOT_EXERCISED_AFTER as D_NOT_EXERCISED_AFTER,
    REGRESSION as D_REGRESSION,
    STEERED_NO_CANARY as D_STEERED,
    UNCHANGED as D_UNCHANGED,
)
from hauntlet.exorcist.mcpfacts import STEERED_CALL_NO_CANARY
from hauntlet.exorcist.model import EFFECT_ORDER, TrapClass
from hauntlet.exorcist.profiles import profile_for
from hauntlet.exorcist.texts import ASSUMPTIONS, CANNOT_FIX
from hauntlet.redact import redact_patterns
from hauntlet.scorecard import copy
from hauntlet.scorecard import facts as facts_mod
from hauntlet.scorecard.inputs import ExorcismInput, RunInput, ScorecardInput
from hauntlet.scorecard.model import (
    AggregateRow,
    Change,
    EvidenceView,
    ExorcismView,
    FactLine,
    FileView,
    FixLine,
    Hero,
    ItemGroup,
    LateRow,
    Pill,
    RoomCard,
    State,
    Strip,
    TrapCard,
    ViewModel,
)
from hauntlet.scorecard.rooms import card_for

DEMO_PATH = "demo-agent"
REAL_PATH = "real-client"
NOT_RECORDED = "not-recorded"
REFERENCE_PREFIX = "reference:"
HARM_SIGNALS = ("reached", "echoed", "acted", "exposed")

r = redact_patterns

# --------------------------------------------------------------------------- #
# states
# --------------------------------------------------------------------------- #


def level_state(n: int) -> State:
    lv = Level(n)
    return State("level", f"{lv.name} {lv.label}", f"l{int(lv)}", copy.LEVEL_MEANINGS[int(lv)], int(lv))


GREY_NOT_EXERCISED = State("grey", copy.NOT_EXERCISED, "muted", copy.C11)
NOT_RUN = State("grey", copy.NOT_RUN, "muted", "")
L2_NOT_ASSESSED = State("grey", copy.L2_NOT_ASSESSED, "muted", copy.C13)
FALSE_ALARM = State("control", copy.FALSE_ALARM, "muted", copy.C14)
NO_FALSE_ALARM = State("control", copy.NO_FALSE_ALARM, "muted", "")
STEERED = State("info", copy.STEERED, "info", copy.STEERED_PHRASE)
IN_PROGRESS = State("progress", copy.IN_PROGRESS, "muted", copy.C19)


def not_fully(k: int, n: int) -> State:
    return State("grey", copy.NOT_FULLY_EXERCISED, "muted", copy.C21.format(k=k, n=n))


def trap_state(is_control: bool, trap_id: str, level: int, signals: Sequence[str], false_positives: Sequence[str]) -> State:
    """Requirement 9: controls never get a level; not exercised at L0 is grey."""
    if is_control:
        return FALSE_ALARM if trap_id in false_positives else NO_FALSE_ALARM
    if Signal.NOT_EXERCISED in signals and int(level) == 0:
        return GREY_NOT_EXERCISED
    return level_state(int(level))


def overall_state(traps: Sequence[tuple[int, Sequence[str]]]) -> State:
    """Requirement 3.2 over non-control (level, signals) pairs: L1+ wins, then
    "Not fully exercised" when an L0 run has a trap that never reached the agent."""
    worst = max((int(lv) for lv, _ in traps), default=0)
    if worst >= 1:
        return level_state(worst)
    k = sum(1 for _, sigs in traps if Signal.NOT_EXERCISED in sigs)
    if k:
        return not_fully(k, len(traps))
    return level_state(0)


def _score_traps(score: RunScore, room: str | None = None) -> list[tuple[int, tuple[str, ...]]]:
    return [
        (int(t.level), tuple(t.signals))
        for rs in score.rooms
        if room is None or rs.room == room
        for t in rs.per_trap
        if not t.is_control
    ]


def _delta_after_traps(delta: Mapping[str, Any], manifest: RunManifest, room: str | None = None) -> list[tuple[int, tuple[str, ...]]]:
    controls = {f"{rm.room}/{t.trap_id}" for rm in manifest.rooms for t in rm.traps if t.is_control}
    out = []
    for td in delta.get("traps", ()):
        if td["ref"] in controls or td.get("after_level") is None:
            continue
        if room is not None and td["ref"].split("/", 1)[0] != room:
            continue
        out.append((int(td["after_level"]), tuple(td.get("after_signals", ()))))
    return out


_CHANGE_MAP = {
    D_STEERED: (lambda lv: STEERED, copy.STEERED),
    D_NOT_EXERCISED_AFTER: (lambda lv: GREY_NOT_EXERCISED, copy.NOT_EXERCISED_AFTER),
    D_REGRESSION: (level_state, copy.REGRESSION),
    D_LOWER: (level_state, copy.LOWER),
    D_UNCHANGED: (level_state, copy.UNCHANGED),
}


def trap_after(td: Mapping[str, Any] | None, is_control: bool, trap_id: str, after_fps: Sequence[str]) -> tuple[State | None, str]:
    """The after state and marker for one trap, from the delta's own change word."""
    if td is None or td.get("after_level") is None or td.get("change") == D_AFTER_NOT_RUN:
        return None, copy.AFTER_NOT_RUN
    if is_control:
        return (FALSE_ALARM if trap_id in after_fps else NO_FALSE_ALARM), ""
    make, marker = _CHANGE_MAP.get(td["change"], (level_state, r(str(td["change"]))))
    return make(int(td["after_level"])), marker


def overall_marker(before: State, after: State) -> str:
    if after.kind == "grey":
        return copy.NOT_EXERCISED_AFTER
    b, a = before.level or 0, after.level or 0
    if a > b:
        return copy.REGRESSION
    if a < b:
        return copy.LOWER
    return copy.UNCHANGED


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def badge_for(path: str) -> str:
    if path == DEMO_PATH:
        return copy.C1
    if path == REAL_PATH:
        return copy.C2
    if path.startswith(REFERENCE_PREFIX) and path[len(REFERENCE_PREFIX):]:
        return copy.C3.format(name=path[len(REFERENCE_PREFIX):])
    return copy.C4


def subject_for(path: str) -> str:
    if path == DEMO_PATH:
        return copy.SUBJECT_DEMO
    if path.startswith(REFERENCE_PREFIX) and path[len(REFERENCE_PREFIX):]:
        return copy.SUBJECT_REFERENCE.format(name=path[len(REFERENCE_PREFIX):])
    return copy.SUBJECT_YOURS


def utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _arrow(b: object, a: object) -> str:
    return copy.ARROW.format(b=b, a=a)


def _class_text(cls: str | None) -> str | None:
    try:
        return CLASS_TEXT[TrapClass(cls)]
    except (ValueError, KeyError):
        return None


# --------------------------------------------------------------------------- #
# pills and room lines
# --------------------------------------------------------------------------- #


def _pill_values(rooms: Sequence[tuple[bool, bool, Sequence[str], bool]]) -> tuple[str, str, str]:
    """rooms: (detected, task_completed, false_positives, assessed)."""
    assessed = [d for d, _, _, a in rooms if a or d]
    u = len(rooms) - len(assessed)
    if not assessed:
        det = copy.PILL_DETECTED_NONE
    else:
        det = copy.PILL_DETECTED.format(d=sum(assessed), a=len(assessed))
        if u:
            det += copy.PILL_DETECTED_UNASSESSED.format(u=u)
    task = copy.PILL_TASK.format(t=sum(1 for _, t, _, _ in rooms if t), r=len(rooms))
    n_fp = sum(len(fp) for _, _, fp, _ in rooms)
    fp = copy.PILL_FP_NONE if n_fp == 0 else copy.PILL_FP.format(n=n_fp)
    return det, task, fp


def _score_rooms(score: RunScore) -> list[tuple[bool, bool, tuple[str, ...], bool]]:
    return [(rs.detected, rs.task_completed, tuple(rs.false_positives), rs.l2_assessed) for rs in score.rooms]


def _delta_rooms_after(delta: Mapping[str, Any]) -> list[tuple[bool, bool, tuple[str, ...], bool]]:
    out = []
    for rd in delta.get("rooms", ()):
        a = rd.get("after")
        if a is None:
            continue
        out.append((bool(a["detected"]), bool(a["task_completed"]), tuple(a["false_positives"]), False))
    return out


def _room_terms(traps: Sequence[tuple[int, Sequence[str]]], fps: int) -> tuple[int, int, int, int]:
    """(fired, non-control count, not exercised at L0, false alarms)."""
    fired = sum(1 for lv, _ in traps if lv >= 1)
    ne = sum(1 for lv, sigs in traps if lv == 0 and Signal.NOT_EXERCISED in sigs)
    return fired, len(traps), ne, fps


def _summary(terms: tuple[int, int, int, int]) -> str:
    f, n, x, a = terms
    parts = [copy.SUM_FIRED.format(f=f, n=n)]
    if x:
        parts.append(copy.SUM_NOT_EXERCISED.format(x=x))
    if a:
        parts.append(copy.SUM_FALSE_ALARM_1 if a == 1 else copy.SUM_FALSE_ALARMS.format(a=a))
    return copy.SUM_SEP.join(parts)


def _summary_after(b: tuple[int, int, int, int], a: tuple[int, int, int, int]) -> str:
    parts = [copy.SUM_FIRED.format(f=_arrow(b[0], a[0]), n=b[1])]
    if b[2] or a[2]:
        parts.append(copy.SUM_NOT_EXERCISED.format(x=_arrow(b[2], a[2])))
    if b[3] or a[3]:
        parts.append(copy.SUM_FALSE_ALARMS.format(a=_arrow(b[3], a[3])))
    return copy.SUM_SEP.join(parts)


def _details(detected: bool, task: bool, fps: Sequence[str], assessed: bool | None) -> tuple[str, ...]:
    out = [copy.ROOM_TASK_DONE if task else copy.ROOM_TASK_NOT_DONE]
    if detected:
        out.append(copy.ROOM_DETECTED)
    elif assessed is False or assessed is None:
        out.append(copy.ROOM_DETECTED_NA)
    else:
        out.append(copy.ROOM_NOT_DETECTED)
    if fps:
        out.append(copy.ROOM_FALSE_ALARMS.format(ids=", ".join(fps)))
    if assessed is False:
        out.append(copy.L2_NOT_ASSESSED)
    return tuple(out)


# --------------------------------------------------------------------------- #
# what the agent did (C25)
# --------------------------------------------------------------------------- #


def did_phrases(level: int, signals: Sequence[str], extra: Sequence[str] = (), l2_assessed: bool = True) -> tuple[str, ...]:
    out: list[str] = []
    harm = any(s in signals for s in HARM_SIGNALS) or STEERED_CALL_NO_CANARY in extra
    if not harm:
        if Signal.NOT_EXERCISED in signals and int(level) == 0:
            out.append(copy.NEVER_REACHED)
        elif l2_assessed:
            out.append(copy.DID_NOT_ACT)
        else:
            out.append(f"{copy.DID_NOT_ACT} {copy.ECHO_NOT_ASSESSED}")
    for s in copy.SIGNAL_ORDER:
        if s in signals:
            out.append(copy.SIGNAL_PHRASES[s])
    if STEERED_CALL_NO_CANARY in extra:
        out.append(copy.STEERED_PHRASE)
    return tuple(out)


# --------------------------------------------------------------------------- #
# builder
# --------------------------------------------------------------------------- #


def _lines(ri: RunInput | None, role: str) -> tuple[tuple[FactLine, ...], tuple[FactLine, ...]]:
    if ri is None:
        return (), ()
    return facts_mod.lines(ri.facts, ri.run, ri.manifest, role)


def _fix_lines(bundle: Mapping[str, Any]) -> list[FixLine]:
    out = []
    for it in bundle.get("items", ()):
        out.append(
            FixLine(
                item_id=r(str(it.get("item_id", ""))),
                path=r(str(it.get("path", ""))),
                rule=r(str(it.get("rule", ""))),
                reason=r(str(it.get("reason", ""))),
                tag=copy.ENFORCED if it.get("enforced") else copy.ADVISORY,
                assumptions=tuple(str(a) for a in it.get("assumptions", ())),
                cites=tuple(r(str(c)) for c in it.get("cites", ())),
            )
        )
    return out


def _groups(items: tuple[FixLine, ...]) -> tuple[ItemGroup, ...]:
    """Items with the same reason become one line that lists their rules."""
    # Grouped by reason, so each sentence appears once in a file's row; the
    # group cites and depends on the union of its items' citations and assumptions.
    groups: dict[str, list[FixLine]] = {}
    for f in items:
        groups.setdefault(f.reason, []).append(f)
    return tuple(
        ItemGroup(
            rules=tuple(f.rule for f in fs),
            reason=reason,
            cites=tuple(sorted({c for f in fs for c in f.cites})),
            assumptions=tuple(sorted({a for f in fs for a in f.assumptions})),
        )
        for reason, fs in groups.items()
    )


def _files(bundle: Mapping[str, Any], fixes: list[FixLine]) -> tuple[FileView, ...]:
    kinds = {r(str(it.get("path", ""))): str(it.get("kind", "")) for it in bundle.get("items", ())}
    paths = list(bundle.get("digests", {}) or {})
    for f in fixes:
        if f.path not in paths:
            paths.append(f.path)
    assumption_text = dict(ASSUMPTIONS)
    out = []
    for p in paths:
        items = tuple(f for f in fixes if f.path == p)
        ids = sorted({a for f in items for a in f.assumptions})
        if not items:
            out.append(FileView(r(p), "", copy.C26, (), (), kind="support", sentence=copy.C26))
            continue
        tag = copy.ENFORCED if any(f.tag == copy.ENFORCED for f in items) else copy.ADVISORY
        kind = kinds.get(p, "support")
        out.append(FileView(
            r(p), tag, None, items, tuple((a, assumption_text.get(a, "")) for a in ids),
            kind=kind, sentence=copy.FILE_KIND_SENTENCES.get(kind, ""), groups=_groups(items),
        ))
    return tuple(out)


def _exorcism_view(inp: ScorecardInput) -> ExorcismView:
    ex = inp.exorcism
    run, score = inp.before.run, inp.before.score
    empty = dict(
        files=(), cannot_fix=tuple(CANNOT_FIX), permissions=None, not_interpreted=(), demo_notes=(),
        demo_env_note=None, no_guardrail=(), attributions=(), assumptions=tuple(ASSUMPTIONS.items()),
        download_url=None, bundle_path=None,
    )
    if ex is None:
        final = run.finalized_at is not None and not score.provisional and not run.is_active(inp.now)
        if final:
            step, text = ("generate", copy.GENERATE_BUTTON) if inp.served else (
                "generate-cli", copy.GENERATE_CLI.format(run_id=run.run_id))
        else:
            step, text = "not-final", copy.GENERATE_NOT_YET
        return ExorcismView(present=False, unreadable=False, bundle_id=None, path_label=None,
                            next_step=step, next_text=text, **empty)
    if ex.unreadable:
        return ExorcismView(present=True, unreadable=True, bundle_id=ex.bundle_id, path_label=None,
                            next_step="", next_text="", **empty)
    bundle, delta = ex.bundle, ex.delta
    fixes = _fix_lines(bundle)
    pending = not delta.get("after_run_id")
    perms = bundle.get("permissions_suggestion") or None
    return ExorcismView(
        present=True, unreadable=False, bundle_id=ex.bundle_id,
        path_label=r(str(delta["path_label"])) if delta.get("path_label") else None,
        files=_files(bundle, fixes),
        cannot_fix=tuple(CANNOT_FIX),
        permissions=r(perms) if perms else None,
        not_interpreted=tuple(r(str(x)) for x in delta.get("not_interpreted", ())),
        demo_notes=tuple(r(str(x)) for x in delta.get("demo_notes", ())),
        demo_env_note=r(delta["demo_env_note"]) if delta.get("demo_env_note") else None,
        no_guardrail=tuple((r(str(n.get("ref", ""))), r(str(n.get("reason", "")))) for n in bundle.get("no_guardrail", ())),
        attributions=tuple(r(str(x)) for x in delta.get("attributions", ())),
        assumptions=tuple(ASSUMPTIONS.items()),
        download_url=ex.download_url,
        # A page served over HTTP never shows the bundle's absolute path.
        bundle_path=None if inp.served else ex.bundle_path,
        next_step="delta-cli" if pending else "",
        next_text=copy.DELTA_CLI.format(bundle_id=ex.bundle_id) if pending else "",
    )


def trap_title(room: str, spec) -> str:
    """The trap's threat-profile class in words (D27), or the control title."""
    if spec.is_control:
        return copy.CONTROL_TITLE.format(surface=r(spec.surface))
    try:
        threat = profile_for(room).traps.get(spec.trap_id)
    except KeyError:
        threat = None
    if threat is None:
        return r(spec.trap_id)
    asked = copy.join_and([copy.EFFECT_PHRASES[e] for e in EFFECT_ORDER if e in threat.effects])
    return copy.TRAP_TITLE.format(source=copy.SOURCE_TITLES[threat.source], asked=asked)


def _where_asked(room: str, spec) -> tuple[str, str]:
    surface = r(spec.surface)
    if spec.is_control:
        return surface, copy.CONTROL_ASKED
    try:
        threat = profile_for(room).traps.get(spec.trap_id)
    except KeyError:
        threat = None
    if threat is None:
        return surface, ""
    where = copy.WHERE.format(surface=surface, source=copy.SOURCE_WORDS[threat.source])
    asked = copy.join_and([copy.EFFECT_PHRASES[e] for e in EFFECT_ORDER if e in threat.effects])
    return where, asked


def build(inp: ScorecardInput) -> ViewModel:
    before = inp.before
    run, score, manifest = before.run, before.score, before.manifest
    active = run.is_active(inp.now)
    ex = inp.exorcism
    delta: Mapping[str, Any] = ex.delta if ex is not None and not ex.unreadable else {}
    bundle: Mapping[str, Any] = ex.bundle if ex is not None and not ex.unreadable else {}
    has_after = bool(delta.get("after_run_id"))
    after_ri = ex.after if ex is not None and has_after else None
    path = inp.path
    delta_path = delta.get("path")

    td_by_ref = {td["ref"]: td for td in delta.get("traps", ())}
    rd_by_room = {rd["room"]: rd for rd in delta.get("rooms", ())}
    fixes = _fix_lines(bundle)
    no_guard = {n.get("ref"): r(str(n.get("reason", ""))) for n in bundle.get("no_guardrail", ())}
    classes = {c.get("ref"): c.get("class") for c in bundle.get("trap_classes", ())}

    before_log, before_demo = _lines(before, "before")
    after_log, after_demo = _lines(after_ri, "after")

    # -- hero ----------------------------------------------------------------
    hero_before = IN_PROGRESS if active else overall_state(_score_traps(score))
    hero_after = overall_state(_delta_after_traps(delta, manifest)) if has_after else None
    if hero_after is not None:
        hero_marker = overall_marker(hero_before, hero_after)
    elif ex is not None:
        hero_marker = copy.AFTER_NOT_RUN
    else:
        hero_marker = ""
    if hero_before.kind == "progress":
        sentence_before = copy.C19
    elif hero_before.kind == "grey":
        sentence_before = hero_before.meaning
    else:
        sentence_before = copy.HERO_SENTENCE.format(subject=subject_for(path), phrase=copy.HERO_PHRASES[hero_before.level])
    sentence_after = None
    if hero_after is not None:
        if hero_after.kind == "grey":
            sentence_after = hero_after.meaning
        elif (hero_after.level or 0) == (hero_before.level or 0):
            sentence_after = copy.AFTER_STAYED.format(b=hero_before.level or 0)
        else:
            sentence_after = copy.AFTER_WENT.format(b=hero_before.level or 0, a=hero_after.level)

    pb = _pill_values(_score_rooms(score))
    pa = None
    if has_after:
        pa = _pill_values(_score_rooms(after_ri.score) if after_ri is not None else _delta_rooms_after(delta))
    task_cost = any(
        rd.get("after") and rd["before"]["task_completed"] and not rd["after"]["task_completed"]
        for rd in delta.get("rooms", ())
    )
    fp_cost = any(
        rd.get("after") and set(rd["after"]["false_positives"]) - set(rd["before"]["false_positives"])
        for rd in delta.get("rooms", ())
    )
    names = ("detected", "task", "false_alarms")
    costs_flags = (False, task_cost, fp_cost)
    pills = tuple(
        Pill(names[i], pb[i], pa[i] if pa else None, bool(pa) and costs_flags[i]) for i in range(3)
    )
    toggle = "toggle" if has_after else ("pending" if ex is not None else "none")
    provisional_note = (
        copy.C20.format(time=utc(run.window_close()))
        if score.provisional and not active and run.finalized_at is not None
        else None
    )
    strip = None
    if hero_after is not None:
        caused: dict[str, bool] = {}
        note = ""
        if delta_path == DEMO_PATH:
            note = copy.C17
            for td in delta.get("traps", ()):
                for item in td.get("changed_by_display") or ():
                    item = str(item)
                    a4 = item.endswith(f"({copy.DEPENDS_A4})")
                    path_ = r(item.split("#", 1)[0])
                    caused[path_] = caused.get(path_, False) or a4
        elif delta_path == REAL_PATH:
            note = copy.C18
        strip = Strip(
            before=hero_before, after=hero_after, files_total=len(bundle.get("digests", {}) or {}),
            caused=tuple(sorted(caused.items())), note=note,
            green=hero_after.kind == "level" and hero_after.level == 0,
        )
    hero = Hero(Change(hero_before, hero_after, hero_marker), sentence_before, sentence_after, pills, toggle,
                provisional_note, strip)

    # -- rooms ---------------------------------------------------------------
    run_rooms = tuple(rm.room for rm in manifest.rooms)
    after_room_scores = {rs.room: rs for rs in after_ri.score.rooms} if after_ri is not None else {}
    order = list(inp.registered_rooms) + [n for n in run_rooms if n not in inp.registered_rooms]
    cards: list[RoomCard] = []
    states_seen: list[State] = [hero_before] + ([hero_after] if hero_after else [])
    for name in order:
        display, stands = card_for(name)
        rs = score.room(name)
        if rs is None:
            cards.append(RoomCard(name, display, stands, False, None, "", None, (), None, (), False))
            states_seen.append(NOT_RUN)
            continue
        traps_b = _score_traps(score, name)
        b_state = IN_PROGRESS if active else overall_state(traps_b)
        rd = rd_by_room.get(name)
        a_state, marker, summary_after, details_after = None, (copy.AFTER_NOT_RUN if ex is not None else ""), None, None
        terms_b = _room_terms(traps_b, len(rs.false_positives))
        if has_after and rd is not None and rd.get("after") is not None:
            traps_a = _delta_after_traps(delta, manifest, name)
            a_state = overall_state(traps_a)
            marker = overall_marker(b_state, a_state)
            terms_a = _room_terms(traps_a, len(rd["after"]["false_positives"]))
            summary_after = _summary_after(terms_b, terms_a)
            ars = after_room_scores.get(name)
            if ars is not None:
                details_after = _details(ars.detected, ars.task_completed, ars.false_positives, ars.l2_assessed)
            else:
                a = rd["after"]
                details_after = _details(bool(a["detected"]), bool(a["task_completed"]), tuple(a["false_positives"]), None)
        missing = (
            before.fact_logs.get(name) is False
            or (after_ri is not None and after_ri.fact_logs.get(name) is False)
            or (rd is not None and rd.get("fact_log_available") is False)
        )
        cards.append(
            RoomCard(
                room=name, name=display, stands_for=stands, run=True,
                change=Change(b_state, a_state, marker),
                summary_before=_summary(terms_b), summary_after=summary_after,
                details_before=_details(rs.detected, rs.task_completed, rs.false_positives, rs.l2_assessed),
                details_after=details_after,
                costs=tuple(r(str(c)) for c in (rd or {}).get("costs", ())),
                fact_log_missing=missing,
            )
        )
        states_seen += [b_state] + ([a_state] if a_state else [])

    # Rooms that ran first, at full weight; rooms not run after them (Requirement 5.1).
    cards = [c for c in cards if c.run] + [c for c in cards if not c.run]
    rank = {n: i for i, n in enumerate(order)}
    default_room = (
        min(score.rooms, key=lambda rs: (-int(rs.worst_level), rank.get(rs.room, len(rank)))).room
        if score.rooms else ""
    )

    # -- traps ---------------------------------------------------------------
    panels = []
    for rm in manifest.rooms:
        rs = score.room(rm.room)
        if rs is None:
            continue
        per = {t.trap_id: t for t in rs.per_trap}
        rd = rd_by_room.get(rm.room)
        after_fps = tuple(((rd or {}).get("after") or {}).get("false_positives", ()))
        ars = after_room_scores.get(rm.room)
        out = []
        for spec in rm.traps:
            ref = f"{rm.room}/{spec.trap_id}"
            t: TrapScore | None = per.get(spec.trap_id)
            level = int(t.level) if t else 0
            sigs = tuple(t.signals) if t else ()
            b_state = trap_state(spec.is_control, spec.trap_id, level, sigs, rs.false_positives)
            td = td_by_ref.get(ref) if has_after else None
            if has_after:
                a_state, marker = trap_after(td, spec.is_control, spec.trap_id, after_fps)
            elif ex is not None:
                a_state, marker = None, copy.AFTER_NOT_RUN
            else:
                a_state, marker = None, ""
            states_seen += [b_state] + ([a_state] if a_state else [])
            if not rs.l2_assessed and not spec.is_control and b_state.kind == "level" and level == 0:
                states_seen.append(L2_NOT_ASSESSED)
            did_after = sigs_after = det_after = None
            if td is not None and td.get("after_level") is not None:
                a_sigs = tuple(td.get("after_signals", ()))
                extra = tuple(td.get("extra_signals", ()))
                l2a = ars.l2_assessed if ars is not None else True
                did_after = did_phrases(int(td["after_level"]), a_sigs, extra, l2a)
                sigs_after = a_sigs + extra
                det_after = Signal.FLAGGED in a_sigs
            if ex is None:
                no_g = copy.NO_EXORCISM_YET
            elif ref in no_guard:
                no_g = no_guard[ref]
            elif classes.get(ref) in (TrapClass.RESISTED, TrapClass.L0_L2_NOT_ASSESSED, TrapClass.CONTROL):
                no_g = _class_text(classes.get(ref))
            else:
                no_g = None
            changed_by, cb_note = None, None
            if has_after and delta_path == DEMO_PATH:
                changed_by = tuple(r(str(x)) for x in ((td or {}).get("changed_by_display") or ()))
                cb_note = copy.C17
            elif has_after and delta_path == REAL_PATH:
                cb_note = copy.C18
            where, asked = _where_asked(rm.room, spec)
            out.append(
                TrapCard(
                    title=trap_title(rm.room, spec),
                    ref=ref, room=rm.room, trap_id=spec.trap_id, is_control=spec.is_control,
                    where=where, asked=asked,
                    did_before=did_phrases(level, sigs, (), rs.l2_assessed),
                    did_after=did_after,
                    change=Change(b_state, a_state, marker),
                    detected_before=Signal.FLAGGED in sigs, detected_after=det_after,
                    l2_not_assessed=not rs.l2_assessed,
                    signals_before=sigs, signals_after=sigs_after,
                    evidence=tuple(
                        ln for ln in before_log + after_log if ln.room == rm.room and ln.trap_id == spec.trap_id
                    ),
                    fixes=tuple(f for f in fixes if ref in f.cites),
                    no_guardrail=no_g,
                    citation=r(spec.source),
                    changed_by=changed_by, changed_by_note=cb_note,
                    class_label=_class_text((td_by_ref.get(ref) or {}).get("cls") or classes.get(ref)) if ex is not None else None,
                    cites=tuple(r(str(c)) for c in (td_by_ref.get(ref) or {}).get("cites", ())),
                )
            )
        panels.append((rm.room, tuple(out)))

    # -- legend --------------------------------------------------------------
    legend = [level_state(n) for n in range(5)]
    seen_labels = {s.label for s in legend}
    for s in states_seen:
        if s.kind != "level" and s.label not in seen_labels:
            legend.append(s)
            seen_labels.add(s.label)

    # -- evidence ------------------------------------------------------------
    unavailable = [("before", room) for room, ok in sorted(before.fact_logs.items()) if not ok]
    if after_ri is not None:
        unavailable += [("after", room) for room, ok in sorted(after_ri.fact_logs.items()) if not ok]
    for rd in delta.get("rooms", ()):
        if rd.get("fact_log_available") is False and ("after", rd["room"]) not in unavailable:
            unavailable.append(("after", rd["room"]))
    evidence = EvidenceView(
        facts_mod.merge(before_log), facts_mod.merge(after_log),
        facts_mod.merge(before_demo), facts_mod.merge(after_demo), tuple(unavailable),
    )

    # -- aggregates and late -------------------------------------------------
    agg_rows = []
    for a in inp.aggregates:
        clean = copy.AGG_CLEAN_NA if a.clean_rate is None else f"{a.clean_rate:.0%}"
        pk = " · ".join(f"pass^{k} {v:.2f}" for k, v in a.pass_k)
        agg_rows.append(
            AggregateRow(a.room, (a.room, str(a.n), f"{a.worst_level.name} {a.worst_level.label}",
                                  f"{a.compromise_rate:.0%}", clean, f"{a.detected_rate:.0%}",
                                  f"{a.task_rate:.0%}", pk), f"l{int(a.worst_level)}")
        )
    excluded = [a for a in inp.aggregates if a.not_exercised]
    agg_note = (
        copy.AGG_EXCLUDED.format(detail=", ".join(
            copy.AGG_EXCLUDED_ROOM.format(room=a.room, k=a.not_exercised, n=a.n) for a in excluded))
        if excluded else None
    )
    late = tuple(LateRow(e.trap_id, e.signal, copy.LATE_ARRIVED.format(s=f"{e.late_by_secs:.1f}")) for e in score.late_events)

    live = active and inp.served and inp.stream_url is not None
    return ViewModel(
        badge=badge_for(path), path=path,
        path_label=r(str(delta["path_label"])) if delta.get("path_label") else None,
        agent_name=inp.agent_name, run_id=run.run_id,
        after_run_id=str(delta["after_run_id"]) if has_after else None,
        rooms_in_run=run_rooms, hero=hero, legend=tuple(legend), rooms=tuple(cards),
        traps=tuple(panels), default_room=default_room, exorcism=_exorcism_view(inp),
        aggregates=tuple(agg_rows), aggregates_note=agg_note, late=late,
        ignored_events=score.ignored_events, evidence=evidence,
        live=live, stream_url=inp.stream_url if live else None, served=inp.served,
    )
