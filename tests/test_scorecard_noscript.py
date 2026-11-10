"""Works without scripts (scorecard SP3, task 12.4).

Parsing the HTML without running any script finds every section, the trap
cards of every run room, both views' values, and every fact. Nothing is hidden
by markup: no ``hidden`` attribute, no inline ``display:none``, no ``x-cloak``;
the only hiding is ``x-show`` (which needs Alpine) and ``.js``-scoped CSS.

**Validates: scorecard Requirements 1.4, 13.7, SP3**
"""

from __future__ import annotations

from _scorecard_html import parse
from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings

from hauntlet.scorecard.build import build
from hauntlet.scorecard.render import CSS, render


@settings(max_examples=80, deadline=None)
@given(case=scorecard_inputs())
def test_sp3_everything_is_in_the_document(case) -> None:
    vm = build(case.inp)
    html = render(vm)
    doc = parse(html)
    ids = {a.get("id") for _, a in doc.elements}
    assert {"verdict", "levels", "rooms", "traps", "exorcism", "evidence"} <= ids
    for room, cards in vm.traps:
        arts = [a for t, a in doc.elements if t == "article" and "data-trap" in a]
        panel = [n for n in doc.nodes if n.inside("section", data_room=room)]
        assert panel
        for c in cards:
            assert any(a["data-trap"] == c.trap_id for a in arts)
    if vm.hero.toggle == "toggle":
        befores = [a for _, a in doc.elements if "v-before" in a.get("class", "")]
        afters = [a for _, a in doc.elements if "v-after" in a.get("class", "")]
        assert befores and len(afters) >= len(befores)
    fact_ids = [a["data-fact-id"] for t, a in doc.elements if t == "li" and "data-fact-id" in a]
    expected = [ln.fact_id for ln in vm.evidence.before + vm.evidence.demo_before]
    if vm.after_run_id:
        expected += [ln.fact_id for ln in vm.evidence.after + vm.evidence.demo_after]
    assert sorted(fact_ids) == sorted(expected)
    for t, a in doc.elements:
        assert "hidden" not in a and "x-cloak" not in a
        assert "display:none" not in a.get("style", "").replace(" ", "")


def test_css_hides_only_under_js() -> None:
    import re

    for rule in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS):
        selector, body = rule
        if "display:none" in body.replace(" ", ""):
            # Content is hidden only once Alpine runs; controls that need a script
            # (toggle, replay, demo buttons) are hidden until then.
            sel = selector.strip()
            assert sel.startswith(".js ") or sel == ".needs-js", sel
