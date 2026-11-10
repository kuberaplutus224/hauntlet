"""Static accessibility checks (scorecard SP14, example; task 12.4). No browser (Q3).

- every chip, pill and tag has text;
- every click binding sits on a ``button``, ``a`` or ``summary``; state is exposed
  with ``aria-pressed`` or ``details``;
- every interactive selector gets ``min-height``/``min-width`` of 44px;
- focus is visible (``:focus-visible`` with an ``--accent-text`` outline);
- a ``prefers-reduced-motion: reduce`` block turns off animation and transition;
  every transition sits under ``no-preference``;
- landmarks, one ``h1``, headings that never skip a level, ``lang="en"``;
- the live region is polite;
- fonts are system stacks; the serif stack is used only for the hero and "The exorcism".

**Validates: scorecard Requirements 11.1, 12.2–12.5, 12.7–12.9, SP14**
"""

from __future__ import annotations

import re

from _scorecard_html import parse
from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings

from hauntlet.scorecard import render_launcher
from hauntlet.scorecard.build import build
from hauntlet.scorecard.render import CSS, render

CLICK = re.compile(r"^(@click|x-on:click)")


def _check_doc(html: str) -> None:
    doc = parse(html)
    assert html.startswith("<!doctype html>\n<html lang=\"en\">")
    tags = [t for t, _ in doc.elements]
    assert tags.count("h1") == 1 and "header" in tags and "main" in tags and "footer" in tags
    prev = 1
    for lv in doc.headings[1:]:
        assert lv <= prev + 1, doc.headings
        prev = lv
    for tag, attrs in doc.elements:
        if any(CLICK.match(k) for k in attrs):
            assert tag in ("button", "a", "summary"), (tag, attrs)
        if tag == "button":
            assert attrs.get("type") == "button"
        if ":aria-pressed" in attrs:
            assert attrs.get("aria-pressed") in ("true", "false")
        if "aria-live" in attrs:
            assert attrs["aria-live"] == "polite"
    labelled = [n for n in doc.nodes if n.inside(data_chip=True) or n.inside(data_tag=True) or n.inside(data_pill=True)]
    n_marked = sum(1 for _, a in doc.elements if {"data-chip", "data-tag", "data-pill"} & set(a))
    marked_with_text = {id(s) for n in labelled for s in n.stack if {"data-chip", "data-tag", "data-pill"} & set(s[1])}
    assert len(marked_with_text) == n_marked, "every chip, tag and pill has text"


@settings(max_examples=40, deadline=None)
@given(case=scorecard_inputs())
def test_sp14_pages(case) -> None:
    _check_doc(render(build(case.inp)))


def test_sp14_launcher() -> None:
    _check_doc(render_launcher(["cursed-repo", "poltergeist"]))


def test_targets_focus_motion_and_fonts() -> None:
    css = CSS.replace(" ", "")
    m = re.search(r"button,summary,a\.btn,\.room-card\{([^}]*)\}", css)
    assert m and "min-height:44px" in m.group(1) and "min-width:44px" in m.group(1)
    focus = re.search(r"button:focus-visible,summary:focus-visible,a:focus-visible\{([^}]*)\}", css)
    assert focus and "outline:3pxsolidvar(--accent-text)" in focus.group(1)
    reduce = re.search(r"@media\(prefers-reduced-motion:reduce\)\{(.*?)\}\}", css)
    assert reduce and "animation:none" in reduce.group(1) and "transition:none" in reduce.group(1)
    outside = re.sub(r"@media\(prefers-reduced-motion:no-preference\)\{.*?\}\}", "", css)
    outside = re.sub(r"@media\(prefers-reduced-motion:reduce\)\{.*?\}\}", "", outside)
    assert "transition:" not in outside and "animation:" not in outside
    assert "@font-face" not in css and "@import" not in css
    assert 'font-family:ui-serif,"NewYork",Charter,"BitstreamCharter",Cambria,"TimesNewRoman",serif' in css
    assert "Georgia" not in css  # Georgia has old-style numerals: "L0" reads "Lo"
    # Amended 11.1: only the hero (level and sentence) and "The exorcism" title are serif.
    serif_rules = re.findall(r"([^{}]*)\{[^{}]*font-family:ui-serif,", css)
    assert len(serif_rules) == 1
    assert set(serif_rules[0].strip().split(",")) == {".verdict-sentence", ".level-block.lvl", ".serif-title"}
    label = re.search(r"h2\.label\{([^}]*)\}", css).group(1)
    assert "font-size:13px" in label and "text-transform:uppercase" in label and "color:var(--muted)" in label
    assert "ui-sans-serif,system-ui,sans-serif" in css
