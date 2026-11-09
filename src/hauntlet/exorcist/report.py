"""Render a ``Delta`` as JSON, HTML or text (Requirement 10).

The first line names the re-run path. The before result is shown in full in
every state. The word "fixed" never appears. On the demo path the report adds
the notes about the inert sandbox, the ungated task tools and the empty demo
environment.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict

from hauntlet.exorcist.delta import DEMO, Delta, RoomState
from hauntlet.exorcist.texts import ASSUMPTIONS, CANNOT_FIX

DEMO_NOTES = (
    "sandbox.json does not affect the demo agent: it proposes no shell commands.",
    "The task's own tool calls are not gated in the demo, so the demo cannot show a bundle "
    "breaking the task; on a real client the empty autoApprove makes those calls ask too.",
)


def _level(n: int | None) -> str:
    return "n/a" if n is None else f"L{n}"


def _signals(sigs: tuple[str, ...], extra: tuple[str, ...] = ()) -> str:
    all_sigs = list(sigs) + list(extra)
    return ", ".join(all_sigs) if all_sigs else "-"


# --------------------------------------------------------------------------- #
# text
# --------------------------------------------------------------------------- #


def render_text(delta: Delta) -> str:
    out: list[str] = [delta.path_label, ""]
    out.append(f"before run: {delta.before_run_id}")
    out.append(f"after run:  {delta.after_run_id or 'not run yet'}")
    if delta.demo_env_note:
        out += ["", delta.demo_env_note]
    out.append("")
    out.append("Per room (before -> after):")
    for rd in delta.rooms:
        out.append(f"  {rd.room}:")
        out.append(f"    before: {_room_line(rd.before)}")
        out.append(f"    after:  {_room_line(rd.after)}")
        if not rd.fact_log_available:
            out.append("    fact log not available for this room")
        for cost in rd.costs:
            out.append(f"    cost: {cost}")
    out.append("")
    out.append("Per trap:")
    for td in delta.traps:
        out.append(f"  {td.ref} [{td.cls.value}]:")
        out.append(f"    before: {_level(td.before_level)} ({_signals(td.before_signals)})")
        out.append(
            f"    after:  {_level(td.after_level)} ({_signals(td.after_signals, td.extra_signals)})"
            f"  [{td.change}]"
        )
        if td.cites:
            out.append(f"    generated for this trap: {', '.join(td.cites)}")
        out.append(f"    changed by: {_changed_by_text(td)}")
    if delta.path == DEMO:
        out += ["", "Notes:"] + [f"  - {n}" for n in DEMO_NOTES]
    if delta.attributions:
        out += ["", "Attributions (items the demo config applied):"] + [
            f"  - {a}" for a in delta.attributions
        ]
    if delta.not_interpreted:
        out += ["", "Not interpreted by the demo agent:"] + [f"  - {n}" for n in delta.not_interpreted]
    out += ["", "What configuration cannot fix:"]
    out += [f"  {i}. {t} {x}" for i, (t, x) in enumerate(CANNOT_FIX, 1)]
    out += ["", "Assumptions:"] + [f"  - {k}. {v}" for k, v in ASSUMPTIONS.items()]
    return "\n".join(out) + "\n"


def _needs_a4(item_id: str) -> bool:
    return "credential-egress" in item_id or item_id.endswith("#SECRETS")


def _changed_by_items(td) -> list[str]:
    """The items that changed this trap, each marked when it depends on A4."""
    return [f"{i} (depends on A4)" if _needs_a4(i) else i for i in td.changed_by]


def _changed_by_text(td) -> str:
    if not td.changed_observed:
        return "not observable (real client)"
    items = _changed_by_items(td)
    return ", ".join(items) if items else "none"


def _room_line(state: RoomState | None) -> str:
    if state is None:
        return "not run yet"
    fps = ", ".join(state.false_positives) or "none"
    return (
        f"worst {_level(state.worst_level)}, detected={state.detected}, "
        f"task_completed={state.task_completed}, false_positives={fps}"
    )


# --------------------------------------------------------------------------- #
# json
# --------------------------------------------------------------------------- #


def render_json(delta: Delta) -> str:
    doc = asdict(delta)
    for td_doc, td in zip(doc["traps"], delta.traps):
        td_doc["changed_by_display"] = _changed_by_items(td) if td.changed_observed else None
    doc["cannot_fix"] = [{"title": t, "text": x} for t, x in CANNOT_FIX]
    doc["assumptions"] = ASSUMPTIONS
    doc["demo_notes"] = list(DEMO_NOTES) if delta.path == DEMO else []
    return json.dumps(doc, indent=2, ensure_ascii=False, default=_enum) + "\n"


def _enum(value: object) -> str:
    return getattr(value, "value", str(value))


# --------------------------------------------------------------------------- #
# html
# --------------------------------------------------------------------------- #


def render_html(delta: Delta) -> str:
    e = html.escape
    rows = []
    rows.append("<!doctype html><html><head><meta charset='utf-8'>")
    rows.append("<meta name='robots' content='noindex, nofollow'>")
    rows.append("<title>Exorcist delta</title></head><body>")
    rows.append(f"<p class='path'><strong>{e(delta.path_label)}</strong></p>")
    rows.append(f"<p>before run: <code>{e(delta.before_run_id)}</code><br>")
    rows.append(f"after run: <code>{e(delta.after_run_id or 'not run yet')}</code></p>")
    if delta.demo_env_note:
        rows.append(f"<p>{e(delta.demo_env_note)}</p>")

    rows.append("<h2>Per room</h2><table border='1'><tr><th>room</th><th>before</th><th>after</th><th>costs</th></tr>")
    for rd in delta.rooms:
        after = _room_line(rd.after)
        if not rd.fact_log_available:
            after += " (fact log not available)"
        costs = "; ".join(rd.costs) or "-"
        rows.append(
            f"<tr><td>{e(rd.room)}</td><td>{e(_room_line(rd.before))}</td>"
            f"<td>{e(after)}</td><td>{e(costs)}</td></tr>"
        )
    rows.append("</table>")

    rows.append(
        "<h2>Per trap</h2><table border='1'><tr><th>trap</th><th>class</th>"
        "<th>before</th><th>after</th><th>change</th>"
        "<th>generated for this trap</th><th>changed by</th></tr>"
    )
    for td in delta.traps:
        before = f"{_level(td.before_level)} ({_signals(td.before_signals)})"
        after = f"{_level(td.after_level)} ({_signals(td.after_signals, td.extra_signals)})"
        rows.append(
            f"<tr><td>{e(td.ref)}</td><td>{e(td.cls.value)}</td><td>{e(before)}</td>"
            f"<td>{e(after)}</td><td>{e(td.change)}</td><td>{e(', '.join(td.cites) or '-')}</td>"
            f"<td>{e(_changed_by_text(td))}</td></tr>"
        )
    rows.append("</table>")

    if delta.path == DEMO:
        rows.append("<h2>Notes</h2><ul>" + "".join(f"<li>{e(n)}</li>" for n in DEMO_NOTES) + "</ul>")
    if delta.attributions:
        rows.append(
            "<h2>Attributions</h2><ul>" + "".join(f"<li><code>{e(a)}</code></li>" for a in delta.attributions) + "</ul>"
        )
    if delta.not_interpreted:
        rows.append(
            "<h2>Not interpreted by the demo agent</h2><ul>"
            + "".join(f"<li>{e(n)}</li>" for n in delta.not_interpreted)
            + "</ul>"
        )
    rows.append("<h2>What configuration cannot fix</h2><ol>")
    rows += [f"<li><strong>{e(t)}</strong> {e(x)}</li>" for t, x in CANNOT_FIX]
    rows.append("</ol><h2>Assumptions</h2><ul>")
    rows += [f"<li><strong>{e(k)}.</strong> {e(v)}</li>" for k, v in ASSUMPTIONS.items()]
    rows.append("</ul></body></html>")
    return "\n".join(rows) + "\n"


def render_all(delta: Delta) -> dict[str, bytes]:
    return {
        "json": render_json(delta).encode("utf-8"),
        "html": render_html(delta).encode("utf-8"),
        "txt": render_text(delta).encode("utf-8"),
    }
