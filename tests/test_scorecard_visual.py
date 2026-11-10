"""Visual-standard rules that are about content, not pixels (design "Visual standards"; task 14).

- each exorcism file is one row (mono path · chip · one sentence), and no
  sentence repeats within a row; identical items are one grouped line;
- a page served over HTTP never shows the bundle's absolute path;
- a separator comes before every evidence note, and merged rows keep every ID;
- trap cards are titled by their threat-profile class, with the ID in mono;
- run rooms come first; the hero strip is green only after an L0 Clean result.

**Validates: scorecard Requirements 5.1, 7.1–7.3, 8.2, 9.6; design "Visual standards"**
"""

from __future__ import annotations

from collections import Counter

import pytest
from _scorecard_html import parse
from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings

from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.exorcist.service import ExorcistService
from hauntlet.rooms import default_rooms
from hauntlet.scorecard import copy, render_exorcism
from hauntlet.scorecard.build import build, trap_title
from hauntlet.scorecard.render import render


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    svc = RangeService(Store(":memory:"), default_rooms())
    ex = ExorcistService(svc, tmp_path_factory.mktemp("ex"))
    return ex, {room: ex.demo(room).bundle_dir for room in ("cursed-repo", "poltergeist")}


def _rows(doc) -> list[list[str]]:
    rows: dict[int, list[str]] = {}
    for n in doc.nodes:
        for tag, attrs in n.stack:
            if tag == "li" and "data-file-row" in attrs:
                rows.setdefault(id(attrs), []).append(n.text)
                break
    return list(rows.values())


def _sentences(texts: list[str]) -> list[str]:
    return [t for t in texts if len(t.split()) >= 3]


@pytest.mark.parametrize("room", ["cursed-repo", "poltergeist"])
def test_file_rows_never_repeat_a_sentence(demo, room) -> None:
    ex, dirs = demo
    doc = parse(render_exorcism(ex, dirs[room], served=True, download_url="/exorcisms/x/bundle"))
    rows = _rows(doc)
    assert rows
    for texts in rows:
        dup = [s for s, n in Counter(_sentences(texts)).items() if n > 1]
        assert not dup, dup
        assert texts[0].startswith(".kiro/")  # the row starts with its path
        assert any(s in copy.FILE_KIND_SENTENCES.values() for s in texts)


def test_credential_egress_hooks_are_one_line(demo) -> None:
    ex, dirs = demo
    vm_html = render_exorcism(ex, dirs["cursed-repo"])
    doc = parse(vm_html)
    rows = [r for r in _rows(doc) if r[0] == ".kiro/hooks/credential-egress.json"]
    assert len(rows) == 1
    rules = [t for t in rows[0] if t.startswith("credential-egress-")]
    assert sorted(rules) == ["credential-egress-mcp", "credential-egress-shell", "credential-egress-web", "credential-egress-write"]
    reasons = [t for t in rows[0] if t.startswith("A planted credential could leave")]
    assert len(reasons) == 1


@settings(max_examples=60, deadline=None)
@given(case=scorecard_inputs(kinds=("pending", "demo", "real"), states=("final",)))
def test_groups_hold_every_item_once(case) -> None:
    vm = build(case.inp)
    for f in vm.exorcism.files:
        assert sorted(r for g in f.groups for r in g.rules) == sorted(i.rule for i in f.items)
        reasons = [g.reason for g in f.groups]
        assert len(reasons) == len(set(reasons))
        assert f.sentence and f.sentence not in reasons


def test_served_pages_hide_the_bundle_path(demo) -> None:
    ex, dirs = demo
    path = str(dirs["cursed-repo"])
    served = render_exorcism(ex, dirs["cursed-repo"], served=True, download_url="/exorcisms/x/bundle")
    assert path not in served and str(dirs["cursed-repo"].parent) not in served
    assert copy.DOWNLOAD in served and 'class="btn primary" href="/exorcisms/x/bundle"' in served
    # Served without a download link: still no path.

    bare = render_exorcism(ex, dirs["cursed-repo"], served=True)
    assert path not in bare
    static = render_exorcism(ex, dirs["cursed-repo"])
    assert path in static and copy.DOWNLOAD not in static


@settings(max_examples=80, deadline=None)
@given(case=scorecard_inputs())
def test_evidence_separator_and_merging(case) -> None:
    vm = build(case.inp)
    html = render(vm)
    doc = parse(html)
    # Every note is preceded by the separator node.
    for i, n in enumerate(doc.nodes):
        if any(a.get("class") == "note" for _, a in n.stack[-1:]):
            assert doc.nodes[i - 1].text == copy.SEP, (doc.nodes[i - 1].text, n.text)
    ev = vm.evidence
    for group in (ev.before, ev.after, ev.demo_before, ev.demo_after):
        keys = [(x.room, x.time, x.who, x.text, x.tag, x.note) for x in group]
        assert len(keys) == len(set(keys)), "rows that would look the same are merged"
        for ln in group:
            assert ln.ids[0] == ln.fact_id and len(ln.ids) == ln.count
    import json

    seen = set(json.loads(doc.scripts["sc-data"])["seenIds"])
    assert {i for g in (ev.before, ev.after, ev.demo_before, ev.demo_after) for ln in g for i in ln.ids} <= seen


@settings(max_examples=40, deadline=None)
@given(case=scorecard_inputs())
def test_titles_room_order_and_strip_colour(case) -> None:
    vm = build(case.inp)
    for room, cards in vm.traps:
        for c in cards:
            spec = case.before.manifest.room(room).trap(c.trap_id)
            assert c.title == trap_title(room, spec) and c.title != c.trap_id
    ran = [c.run for c in vm.rooms]
    assert ran == sorted(ran, reverse=True), "run rooms first"
    st = vm.hero.strip
    if st is not None:
        assert st.green == (st.after.kind == "level" and st.after.level == 0)
        if case.delta["path"] == "real-client":
            assert st.caused == () and st.note == copy.C18
    html = render(vm)
    doc = parse(html)
    for room, cards in vm.traps:
        for c in cards:
            ids = [n.text for n in doc.nodes if n.inside("article", data_trap=c.trap_id) and n.inside("code", class_="id")]
            assert c.trap_id in ids
