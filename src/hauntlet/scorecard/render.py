"""Render the view model as one self-contained HTML page (design.md "Renderer"). Pure.

- The server renders everything: every section, every run room's trap cards,
  both Before and After values, and the full evidence log. Alpine only shows
  and hides (``x-show``) and appends live lines.
- Every value goes through ``t()`` (``html.escape`` with quotes). Data never
  goes into an Alpine attribute; values Alpine needs sit in escaped ``data-*``
  attributes and are read with ``$el.dataset``.
- Each piece of text is its own text node (a value, a fixed label, or glue such
  as "→"), so the SP1 test can check every node against the sources.
- CSS and the component script are inlined; the only external resource is the
  pinned Alpine script with SRI, the same tag ``exorcist.html`` uses.
"""

from __future__ import annotations

import json
import re
from html import escape
from importlib.resources import files

from hauntlet.scorecard import copy
from hauntlet.scorecard.model import (
    Change,
    ExorcismView,
    FactLine,
    FileView,
    FixLine,
    RoomCard,
    State,
    TrapCard,
    ViewModel,
)
from hauntlet.scorecard.rooms import card_for

ALPINE_TAG = (
    '<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js"\n'
    '        integrity="sha384-l8f0VcPi/M1iHPv8egOnY/15TDwqgbOR1anMIJWvU6nLRgZVLTLSaNqi/TOoT5Fh"\n'
    '        crossorigin="anonymous"></script>'
)

_STATIC = files("hauntlet.scorecard") / "static"
CSS = (_STATIC / "scorecard.css").read_text(encoding="utf-8")
JS = (_STATIC / "scorecard.js").read_text(encoding="utf-8")

MARK = (
    '<svg class="mark" viewBox="0 0 28 30" aria-hidden="true" focusable="false">'
    '<path fill="currentColor" d="M14 1C7 1 3 6 3 13v16l3.6-3 3.7 3 3.7-3 3.7 3 3.7-3 3.6 3V13C25 6 21 1 14 1z'
    'M10 11.5a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm8 0a2 2 0 1 1 0 4 2 2 0 0 1 0-4z"/></svg>'
)


def t(value: object) -> str:
    """The one escaping path for every value."""
    return escape(str(value), quote=True)


def _json_for_script(doc: object) -> str:
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True)
    for ch, rep in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        raw = raw.replace(ch, rep)
    return raw


# --------------------------------------------------------------------------- #
# pieces
# --------------------------------------------------------------------------- #


def chip(state: State, big: bool = False) -> str:
    cls = f"lv{state.level}" if state.kind == "level" else ("info" if state.kind == "info" else "grey")
    size = " big" if big else ""
    return f'<span class="chip {cls}{size}" data-chip>{t(state.label)}</span>'


def _marker(marker: str) -> str:
    if not marker:
        return ""
    cls = "marker reg" if marker == copy.REGRESSION else "marker"
    return f'<span class="{cls}">{t(marker)}</span>'


ARROW = '<span class="arrow">→</span>'


def split(split_views: bool, before: str, after: str, tag: str = "span") -> str:
    """Both views in the document; Alpine shows one. Without scripts both show, prefixed."""
    if not split_views:
        return before
    return (
        f'<{tag} class="v v-before" x-show="view === \'before\'"><span class="vp">{t(copy.PREFIX_BEFORE)}</span>{before}</{tag}>'
        f'<{tag} class="v v-after" x-show="view === \'after\'"><span class="vp">{t(copy.PREFIX_AFTER)}</span>{after}</{tag}>'
    )


def change_html(change: Change, split_views: bool, big: bool = False) -> str:
    before = chip(change.before, big)
    if change.after is None:
        after = before + _marker(change.marker)
    else:
        after = before + ARROW + chip(change.after, big) + _marker(change.marker)
    return split(split_views, before, after)


def _signals(signals) -> str:
    """Each signal its own node, joined by glue."""
    if not signals:
        return f"<span>{t(copy.NONE)}</span>"
    return '<span class="sep">, </span>'.join(f"<code>{t(x)}</code>" for x in signals)


def _list(items, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f"<ul{c}>" + "".join(f"<li>{t(i)}</li>" for i in items) + "</ul>"


def _code_list(items) -> str:
    return '<ul class="chips">' + "".join(f"<li><code>{t(i)}</code></li>" for i in items) + "</ul>"


# --------------------------------------------------------------------------- #
# header and hero
# --------------------------------------------------------------------------- #


def _header(vm: ViewModel) -> str:
    rooms = '<span class="sep">, </span>'.join(f"<b>{t(r)}</b>" for r in vm.rooms_in_run)
    parts = [
        f'<span class="meta"><span>{t(copy.RUN_LABEL)}</span> <code>{t(vm.run_id)}</code></span>',
        f'<span class="meta"><span>{t(copy.ROOMS_LABEL)}</span> {rooms}</span>',
    ]
    if vm.after_run_id:
        parts.append(f'<span class="meta"><span>{t(copy.AFTER_RUN_LABEL)}</span> <code>{t(vm.after_run_id)}</code></span>')
    if vm.agent_name:
        parts.append(f'<span class="meta"><span>{t(copy.AGENT_LABEL)}</span> <b>{t(vm.agent_name)}</b></span>')
    return (
        f'<header class="frame"><p class="badge" role="note">{t(vm.badge)}</p>'
        f'<div class="brand">{MARK}<h1 class="frame-title">{t(copy.PRODUCT)}</h1>{"".join(parts)}</div></header>'
    )


def _hero(vm: ViewModel) -> str:
    h = vm.hero
    sv = h.toggle == "toggle"
    sentence = split(sv, f"<span>{t(h.sentence_before)}</span>", f"<span>{t(h.sentence_after or '')}</span>")
    pills = []
    for p in h.pills:
        after = None
        if p.after is not None:
            cost = f'<span class="cost">{t(copy.COST)}</span>' if p.cost else ""
            after = f"<span>{t(p.before)}</span>{ARROW}<span>{t(p.after)}</span>{cost}"
        body = split(sv, f"<span>{t(p.before)}</span>", after) if after else f"<span>{t(p.before)}</span>"
        pills.append(f'<li class="pill" data-pill="{t(p.name)}">{body}</li>')
    out = [
        '<section id="verdict" aria-labelledby="h-verdict">',
        f'<h2 id="h-verdict">{t(copy.SECTION_VERDICT)}</h2>',
        '<div class="card verdict">',
        f"<div>{change_html(h.change, sv, big=True)}</div>",
        "<div>",
        f'<p class="verdict-sentence">{sentence}</p>',
    ]
    if h.provisional_note:
        out.append(f'<p class="muted">{t(h.provisional_note)}</p>')
    out.append(f'<ul class="pills" data-finding>{"".join(pills)}</ul>')
    if h.toggle == "toggle":
        out.append(
            f'<div class="toggle needs-js" role="group" aria-label="{t(copy.VIEW_GROUP)}">'
            '<button type="button" class="btn" aria-pressed="true" :aria-pressed="(view === \'before\').toString()" '
            f'@click="view = \'before\'">{t(copy.VIEW_BEFORE)}</button>'
            '<button type="button" class="btn" aria-pressed="false" :aria-pressed="(view === \'after\').toString()" '
            f'@click="view = \'after\'">{t(copy.VIEW_AFTER)}</button></div>'
        )
    elif h.toggle == "pending":
        out.append(f'<p class="muted">{t(copy.AFTER_NOT_RUN)}</p>')
    if vm.path_label:
        out.append(f'<p class="muted">{t(vm.path_label)}</p>')
    out.append(f'<p class="limits">{t(copy.C5)}</p>')
    out.append("</div></div></section>")
    return "".join(out)


def _legend(vm: ViewModel) -> str:
    items = []
    for s in vm.legend:
        meaning = f"<span>{t(s.meaning)}</span>" if s.meaning else ""
        items.append(f"<li>{chip(s)}{meaning}</li>")
    return (
        '<section id="levels" aria-labelledby="h-levels">'
        f'<h2 id="h-levels">{t(copy.SECTION_LEVELS)}</h2><ul class="legend">{"".join(items)}</ul></section>'
    )


# --------------------------------------------------------------------------- #
# rooms and traps
# --------------------------------------------------------------------------- #


def _room_card(c: RoomCard, vm: ViewModel, sv: bool) -> str:
    stands = f'<span class="stands">{t(c.stands_for)}</span>' if c.stands_for else ""
    if not c.run:
        return (
            f'<div class="room-card" data-room="{t(c.room)}" aria-disabled="true">'
            f"<b>{t(c.name)}</b>{stands}<span>{chip_not_run()}</span></div>"
        )
    pressed = "true" if c.room == vm.default_room else "false"
    # summary_after already reads "before → after" for each term (Requirement 5.4).
    summary = f"<span>{t(c.summary_before)}</span>"
    if c.summary_after is not None:
        summary = split(sv, summary, f"<span>{t(c.summary_after)}</span>")
    return (
        f'<button type="button" class="room-card" data-room="{t(c.room)}" aria-pressed="{pressed}" '
        ':aria-pressed="(room === $el.dataset.room).toString()" @click="room = $el.dataset.room">'
        f"<b>{t(c.name)}</b>{stands}<span>{change_html(c.change, sv)}</span>"
        f'<span class="sum">{summary}</span></button>'
    )


def chip_not_run() -> str:
    return f'<span class="chip grey" data-chip>{t(copy.NOT_RUN)}</span>'


def _rooms(vm: ViewModel) -> str:
    sv = vm.hero.toggle == "toggle"
    cards = "".join(_room_card(c, vm, sv) for c in vm.rooms)
    return (
        '<section id="rooms" aria-labelledby="h-rooms">'
        f'<h2 id="h-rooms">{t(copy.SECTION_ROOMS)}</h2><div class="rooms">{cards}</div></section>'
    )


def _fix(f: FixLine) -> str:
    cls = "tag enforced" if f.tag == copy.ENFORCED else "tag"
    assumptions = "".join(f'<span class="tag">{t(a)}</span>' for a in f.assumptions)
    return (
        f'<li><span class="tagline"><span class="{cls}" data-tag>{t(f.tag)}</span><code>{t(f.item_id)}</code>'
        f"{assumptions}</span><span>{t(f.reason)}</span></li>"
    )


def _fact(ln: FactLine, idx: int) -> str:
    tag = f'<span class="tg" data-tag>{t(ln.tag)}</span>' if ln.tag else "<span></span>"
    note = f'<span class="note">{t(ln.note)}</span>' if ln.note else ""
    return (
        f'<li data-room="{t(ln.room)}" data-fact-id="{t(ln.fact_id)}" data-idx="{idx}" '
        'x-show="visibleLine($el)">'
        f'<span class="t">{t(ln.time)}</span><span class="who">{t(ln.who)}</span>'
        f"<span><span>{t(ln.text)}</span>{note}</span>{tag}</li>"
    )


def _evidence_list(lines: tuple[FactLine, ...]) -> str:
    if not lines:
        return f'<p class="na">{t(copy.NO_FACTS)}</p>'
    return '<ul class="details">' + "".join(
        f'<li><span class="t">{t(ln.time)}</span> <span>{t(ln.text)}</span>'
        + (f' <span class="tag" data-tag>{t(ln.tag)}</span>' if ln.tag else "")
        + (f' <span class="note">{t(ln.note)}</span>' if ln.note else "")
        + "</li>"
        for ln in lines
    ) + "</ul>"


def _trap(tc: TrapCard, sv: bool) -> str:
    head = [f"<h3>{t(tc.trap_id)}</h3>"]
    if tc.is_control:
        head.append(f'<span class="tag" data-tag>{t(copy.CONTROL_MARK)}</span>')
    if tc.class_label:
        head.append(f'<span class="muted"><span>{t(copy.CLASS_HEADING)}</span><span>: </span><span>{t(tc.class_label)}</span></span>')
    asked = (
        f'<p><span class="muted">{t(copy.ASKED_PREFIX)}</span> <span>{t(tc.asked)}</span></p>' if tc.asked else ""
    )
    did_before = _list(tc.did_before)
    did_after = did_before
    if tc.did_after is not None:
        did_after = (
            f'<p class="muted">{t(copy.VIEW_BEFORE)}</p>{did_before}'
            f'<p class="muted">{t(copy.VIEW_AFTER)}</p>{_list(tc.did_after)}'
        )
    result_b = [chip(tc.change.before)]
    if tc.change.before.meaning:
        result_b.append(f"<span>{t(tc.change.before.meaning)}</span>")
    if tc.detected_before:
        result_b.append(f'<span class="tag" data-tag>{t(copy.DETECTED)}</span>')
    if tc.l2_not_assessed and not tc.is_control and tc.change.before.kind == "level" and tc.change.before.level == 0:
        result_b.append(f'<span class="tag" data-tag>{t(copy.L2_NOT_ASSESSED)}</span>')
    before_html = '<span class="tagline">' + "".join(result_b) + "</span>"
    after_html = before_html
    if tc.change.after is not None:
        ra = [chip(tc.change.before), ARROW, chip(tc.change.after), _marker(tc.change.marker)]
        if tc.change.after.meaning:
            ra.append(f"<span>{t(tc.change.after.meaning)}</span>")
        if tc.detected_after:
            ra.append(f'<span class="tag" data-tag>{t(copy.DETECTED)}</span>')
        after_html = '<span class="tagline">' + "".join(ra) + "</span>"
    elif tc.change.marker and sv:
        after_html = '<span class="tagline">' + chip(tc.change.before) + _marker(tc.change.marker) + "</span>"

    changed = ""
    if tc.changed_by_note is not None and sv:
        if tc.changed_by is None:
            inner = f'<p class="muted">{t(tc.changed_by_note)}</p>'
        else:
            chips = "".join(
                f'<li class="{"a4" if "depends on A4" in c else ""}"><code>{t(c)}</code></li>' for c in tc.changed_by
            ) or f"<li>{t(copy.NONE)}</li>"
            inner = f'<p><strong>{t(tc.changed_by_note)}</strong></p><ul class="chips">{chips}</ul>'
        changed = f'<div class="v v-after" x-show="view === \'after\'">{inner}</div>'

    sig_b = _signals(tc.signals_before)
    sigs = sig_b
    if tc.signals_after is not None:
        sigs = split(sv, sig_b, f"{sig_b}{ARROW}{_signals(tc.signals_after)}")
    fixes = "".join(_fix(f) for f in tc.fixes)
    fix_block = f'<ul class="details">{fixes}</ul>' if fixes else ""
    if tc.no_guardrail:
        fix_block += f'<p class="na">{t(tc.no_guardrail)}</p>'
    details = (
        f"<details><summary>{t(copy.EVIDENCE_AND_FIX)}</summary>"
        f"<h4>{t(copy.EVIDENCE_HEADING)}</h4>{_evidence_list(tc.evidence)}"
        f"<h4>{t(copy.SIGNALS_HEADING)}</h4><p>{sigs}</p>"
        f"<h4>{t(copy.FIX_HEADING)}</h4>{fix_block}"
        f"<h4>{t(copy.SOURCE_HEADING)}</h4><p>{t(tc.citation)}</p></details>"
    )
    return (
        f'<article class="card" data-trap="{t(tc.trap_id)}" data-finding>'
        f'<div class="tagline">{"".join(head)}</div><div class="steps">'
        f'<div class="step raised"><h4>{t(copy.STEP_WHERE)}</h4><p>{t(tc.where)}</p>{asked}</div>'
        f'<div class="step raised"><h4>{t(copy.STEP_DID)}</h4>{split(sv, did_before, did_after, "div")}</div>'
        f'<div class="step raised"><h4>{t(copy.STEP_RESULT)}</h4>{split(sv, before_html, after_html, "div")}</div>'
        f"</div>{changed}{details}</article>"
    )


def _panels(vm: ViewModel) -> str:
    sv = vm.hero.toggle == "toggle"
    cards = {c.room: c for c in vm.rooms}
    out = []
    for room, traps in vm.traps:
        c = cards.get(room)
        name = card_for(room)[0]
        extra = []
        if c is not None:
            if c.details_after is not None:
                extra.append(split(sv, _list(c.details_before, "details"), _list(c.details_after, "details"), "div"))
            else:
                extra.append(_list(c.details_before, "details"))
            if c.costs:
                extra.append(f"<h3>{t(copy.COSTS_HEADING)}</h3>" + _list(c.costs, "details"))
            if c.fact_log_missing:
                extra.append(f'<p class="na">{t(copy.FACT_LOG_NA.format(room=room))}</p>')
        hid = f"h-room-{room}"
        out.append(
            f'<section class="room-panel" data-room="{t(room)}" aria-labelledby="{t(hid)}" '
            'x-show="room === $el.dataset.room">'
            f'<h2 id="{t(hid)}">{t(copy.SECTION_TRAPS.format(room=name))}</h2>'
            f'<div data-finding>{"".join(extra)}</div>{"".join(_trap(tc, sv) for tc in traps)}</section>'
        )
    return f'<div id="traps">{"".join(out)}</div>'


# --------------------------------------------------------------------------- #
# exorcism
# --------------------------------------------------------------------------- #


def _file(f: FileView) -> str:
    tag = ""
    if f.tag:
        cls = "tag enforced" if f.tag == copy.ENFORCED else "tag"
        tag = f'<span class="{cls}" data-tag>{t(f.tag)}</span>'
    note = f'<p class="muted">{t(f.note)}</p>' if f.note else ""
    items = "".join(
        f'<li><code>{t(i.rule)}</code> <span>{t(i.reason)}</span>'
        f'<span class="muted"> {t(copy.CITES)}</span>{_code_list(i.cites)}</li>'
        for i in f.items
    )
    items = f'<ul class="details">{items}</ul>' if items else ""
    assumptions = "".join(f"<li><strong>{t(a)}</strong> <span>{t(x)}</span></li>" for a, x in f.assumptions)
    assumptions = f'<ul class="details">{assumptions}</ul>' if assumptions else ""
    return f'<div class="card"><div class="tagline"><h3><code>{t(f.path)}</code></h3>{tag}</div>{note}{items}{assumptions}</div>'


def _cannot_fix(ex: ExorcismView) -> str:
    items = "".join(f"<li><strong>{t(a)}</strong> <span>{t(b)}</span></li>" for a, b in ex.cannot_fix)
    assumptions = "".join(f"<li><strong>{t(a)}</strong> <span>{t(b)}</span></li>" for a, b in ex.assumptions)
    return (
        f"<details><summary>{t(copy.CANNOT_FIX_SUMMARY.format(n=len(ex.cannot_fix)))}</summary><ol>{items}</ol></details>"
        f"<details><summary>{t(copy.ASSUMPTIONS_HEADING)}</summary><ul>{assumptions}</ul></details>"
    )


def _exorcism(vm: ViewModel) -> str:
    ex = vm.exorcism
    out = ['<section id="exorcism" aria-labelledby="h-exorcism">', f'<h2 id="h-exorcism">{t(copy.SECTION_EXORCISM)}</h2>', "<div data-finding>"]
    if not ex.present:
        if ex.next_step == "generate":
            out.append(
                f'<button type="button" class="btn primary" @click="generate()">{t(ex.next_text)}</button>'
            )
        elif ex.next_step == "generate-cli":
            out.append(f"<pre><code>{t(ex.next_text)}</code></pre>")
        else:
            out.append(f'<p class="muted">{t(ex.next_text)}</p>')
    elif ex.unreadable:
        out.append(f'<p class="na">{t(copy.C27)}</p>')
    else:
        out.append(f"<p>{t(copy.FILES_INTRO)}</p>")
        if ex.download_url:
            out.append(f'<p><a class="btn primary" href="{t(ex.download_url)}">{t(copy.DOWNLOAD)}</a></p>')
        elif ex.bundle_path:
            out.append(f'<p class="muted">{t(copy.BUNDLE_DIR.format(path=ex.bundle_path))}</p>')
        out.append('<div class="files">' + "".join(_file(f) for f in ex.files) + "</div>")
        if ex.no_guardrail:
            out.append(f"<h3>{t(copy.NO_GUARDRAIL_HEADING)}</h3><ul>")
            out += [f"<li><code>{t(ref)}</code> <span>{t(why)}</span></li>" for ref, why in ex.no_guardrail]
            out.append("</ul>")
        if ex.attributions:
            out.append(f"<h3>{t(copy.ATTRIBUTIONS_HEADING)}</h3>{_code_list(ex.attributions)}")
        if ex.not_interpreted:
            out.append(f"<h3>{t(copy.NOT_INTERPRETED_HEADING)}</h3>{_list(ex.not_interpreted)}")
        if ex.demo_notes or ex.demo_env_note:
            out.append(f"<h3>{t(copy.DEMO_NOTES_HEADING)}</h3>{_list(ex.demo_notes)}")
            if ex.demo_env_note:
                out.append(f"<p>{t(ex.demo_env_note)}</p>")
        if ex.permissions:
            out.append(
                f"<details><summary>{t(copy.PERMISSIONS_HEADING)}</summary>"
                f'<p class="muted">{t(copy.PERMISSIONS_LABEL)}</p><pre><code>{t(ex.permissions)}</code></pre></details>'
            )
        if ex.next_step == "delta-cli":
            out.append(f"<p>{t(copy.DELTA_CLI_INTRO)}</p><pre><code>{t(ex.next_text)}</code></pre>")
    out.append(_cannot_fix(ex))
    out.append("</div></section>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# evidence, aggregates, late
# --------------------------------------------------------------------------- #

_OFFSET = re.compile(r"^\+(-?\d+(?:\.\d+)?) s$")


def _gaps(lines: list[FactLine]) -> list[int]:
    """Replay delays in ms: recorded gaps, scaled to at most 10 s, each clamped to 50–1500 ms."""
    if not lines:
        return []
    times, last = [], 0.0
    for ln in lines:
        m = _OFFSET.match(ln.time)
        last = float(m.group(1)) if m else last + 0.3
        times.append(last)
    raw = [0.0] + [max(0.0, b - a) for a, b in zip(times, times[1:])]
    total = sum(raw) or 1.0
    scale = min(1.0, 10.0 / total)
    return [0] + [int(min(1500, max(50, g * scale * 1000))) for g in raw[1:]]


def _evidence(vm: ViewModel) -> tuple[str, list[FactLine]]:
    ev = vm.evidence
    order: list[FactLine] = []
    out = [
        '<section id="evidence" aria-labelledby="h-evidence">',
        f'<h2 id="h-evidence">{t(copy.SECTION_EVIDENCE)}</h2>',
        f"<p>{t(copy.C16)}</p>",
        '<div class="toggle needs-js" role="group">',
        '<button type="button" class="btn" aria-pressed="true" :aria-pressed="(logScope === \'room\').toString()" '
        f'@click="logScope = \'room\'">{t(copy.EVIDENCE_SCOPE_ROOM)}</button>',
        '<button type="button" class="btn" aria-pressed="false" :aria-pressed="(logScope === \'all\').toString()" '
        f'@click="logScope = \'all\'">{t(copy.EVIDENCE_SCOPE_ALL)}</button>',
    ]
    if vm.live:
        out.append(f'<span class="tag" data-tag x-show="live">{t(copy.C23)}</span>')
    else:
        out.append(f'<button type="button" class="btn" @click="replay()">{t(copy.REPLAY)}</button>')
        out.append(f'<span class="muted">{t(copy.C22)}</span>')
    out.append("</div>")
    out.append('<p class="sr" aria-live="polite" x-text="announce"></p>')
    if vm.live:
        out.append(f'<p x-show="verdictReady"><a class="btn primary" href="">{t(copy.SHOW_VERDICT)}</a></p>')
    na = {}
    for role, room in ev.unavailable:
        na.setdefault(role, []).append(room)
    groups = [("before", ev.before, ev.demo_before)]
    if vm.after_run_id:
        groups.append(("after", ev.after, ev.demo_after))
    out.append('<div data-finding>')
    for role, log, demo in groups:
        if vm.after_run_id:
            out.append(f"<h3>{t(copy.BEFORE_RUN_FACTS if role == 'before' else copy.AFTER_RUN_FACTS)}</h3>")
        for room in na.get(role, ()):
            out.append(f'<p class="na">{t(copy.FACT_LOG_NA.format(room=room))}</p>')
        items = []
        for ln in log:
            items.append(_fact(ln, len(order)))
            order.append(ln)
        if role == "before" and vm.live:
            items.append(
                '<template x-for="ln in liveLines" :key="ln.fact_id"><li>'
                '<span class="t" x-text="ln.time"></span><span class="who" x-text="ln.who"></span>'
                '<span><span x-text="ln.text"></span> <span class="note" x-text="ln.note"></span></span>'
                '<span class="tg" x-text="ln.tag"></span></li></template>'
            )
        out.append(f'<div class="log-wrap"><ol class="log">{"".join(items)}</ol></div>')
        if demo:
            out.append(f"<h3>{t(copy.DEMO_DECISIONS)}</h3>")
            ditems = []
            for ln in demo:
                ditems.append(_fact(ln, len(order)))
                order.append(ln)
            out.append(f'<div class="log-wrap"><ol class="log">{"".join(ditems)}</ol></div>')
    out.append("</div></section>")
    return "".join(out), order


def _aggregates(vm: ViewModel) -> str:
    if not vm.aggregates:
        return ""
    head = "".join(f"<th>{t(h)}</th>" for h in copy.AGG_HEADERS)
    rows = "".join("<tr>" + "".join(f"<td>{t(c)}</td>" for c in row.cells) + "</tr>" for row in vm.aggregates)
    note = f'<p class="muted">{t(vm.aggregates_note)}</p>' if vm.aggregates_note else ""
    return (
        '<section id="aggregates" aria-labelledby="h-agg">'
        f'<h2 id="h-agg">{t(copy.SECTION_AGGREGATES)}</h2>'
        f'<div class="scroll"><table><tr>{head}</tr>{rows}</table></div>'
        f'<p class="muted">{t(copy.AGG_NOTE)}</p>{note}</section>'
    )


def _late(vm: ViewModel) -> str:
    out = ""
    if vm.late:
        head = "".join(f"<th>{t(h)}</th>" for h in copy.LATE_HEADERS)
        rows = "".join(f"<tr><td>{t(r.trap_id)}</td><td>{t(r.signal)}</td><td>{t(r.arrived)}</td></tr>" for r in vm.late)
        out += (
            '<section id="late" aria-labelledby="h-late">'
            f'<h2 id="h-late">{t(copy.SECTION_LATE)}</h2>'
            f'<div class="scroll"><table><tr>{head}</tr>{rows}</table></div>'
            f'<p class="muted">{t(copy.LATE_NOTE)}</p></section>'
        )
    if vm.ignored_events:
        out += f'<p class="muted">{t(copy.IGNORED.format(n=vm.ignored_events))}</p>'
    return out


# --------------------------------------------------------------------------- #
# documents
# --------------------------------------------------------------------------- #


def _document(header: str, body: str, data: dict) -> str:
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{t(copy.TITLE)}</title><style>{CSS}</style>"
        f"<script>{JS}</script>\n{ALPINE_TAG}</head>\n<body>{header}"
        f'<main x-data="scorecard()">{body}'
        f'<script type="application/json" id="sc-data">{_json_for_script(data)}</script></main>'
        f"<footer><p>{t(copy.FOOTER)}</p></footer></body></html>\n"
    )


def render(vm: ViewModel) -> str:
    evidence, order = _evidence(vm)
    body = (
        _hero(vm) + _legend(vm) + _rooms(vm) + _panels(vm) + _exorcism(vm) + _aggregates(vm) + _late(vm) + evidence
    )
    data = {
        "defaultRoom": vm.default_room,
        "hasAfter": bool(vm.after_run_id),
        "runId": vm.run_id,
        "streamUrl": vm.stream_url,
        "seenIds": [ln.fact_id for ln in order],
        "replayGaps": _gaps(order),
    }
    return _document(_header(vm), body, data)


def render_launcher(demo_rooms: list[str], legend: tuple[State, ...]) -> str:
    from hauntlet.scorecard.build import badge_for

    buttons = "".join(
        f'<button type="button" class="btn primary" data-room="{t(r)}" :disabled="busy" '
        f'@click="launch($el.dataset.room)">{t(copy.LAUNCH_BUTTON.format(room=card_for(r)[0]))}</button> '
        for r in demo_rooms
    )
    header = (
        f'<header class="frame"><p class="badge" role="note">{t(badge_for("demo-agent"))}</p>'
        f'<div class="brand">{MARK}<h1 class="frame-title">{t(copy.PRODUCT)}</h1></div></header>'
    )
    items = "".join(
        f"<li>{chip(s)}" + (f"<span>{t(s.meaning)}</span>" if s.meaning else "") + "</li>" for s in legend
    )
    body = (
        '<section id="exorcism" aria-labelledby="h-exorcism">'
        f'<h2 id="h-exorcism">{t(copy.SECTION_EXORCISM)}</h2><p>{t(copy.LAUNCH_INTRO)}</p>'
        f'<div class="toggle needs-js">{buttons}</div>'
        f'<p x-show="busy">{t(copy.RUNNING)}</p><p class="na" x-show="error" x-text="error"></p></section>'
        '<section id="levels" aria-labelledby="h-levels">'
        f'<h2 id="h-levels">{t(copy.SECTION_LEVELS)}</h2><ul class="legend">{items}</ul></section>'
    )
    return _document(header, body, {"defaultRoom": "", "seenIds": [], "replayGaps": []})
