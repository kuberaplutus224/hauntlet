"""Task 14 polish (design "Visual standards"): numerals, the green strip, widths at 375, the toggle, paths.

- every serif style uses lining, tabular numerals, so "L0" never reads "Lo";
- the green After strip is a dark tint with an L0 border and light text; every
  chip fill or outline and the arrow on it keep at least 3:1, the text 4.5:1;
- at 375 px nothing is wider than its container: every unbreakable run of text
  fits the width left after its ancestors' padding and borders (the evidence log
  may scroll inside its own region, Requirement 12.6);
- the Before/After toggle is one segmented row at every width down to 320 px;
- mono paths break only after "/" (``<wbr>``); a guardrail item ID ("path#rule")
  may also break before its "#" and before a "." in the rule; file names never break.

No browser (Q3): widths are estimated as in ``test_scorecard_layout.py``.

**Validates: scorecard Requirements 11.3, 12.1, 12.6; design "Visual standards"**
"""

from __future__ import annotations

import re

import pytest
from _scorecard_html import parse
from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings
from test_scorecard_layout import MONO, SANS, _rules

from hauntlet.scorecard import theme
from hauntlet.scorecard.build import build
from hauntlet.scorecard.render import CSS, path, render

# --------------------------------------------------------------------------- #
# 1. numerals
# --------------------------------------------------------------------------- #


def test_serif_styles_use_lining_tabular_numerals() -> None:
    css = CSS.replace(" ", "")
    serif = re.findall(r"([^{}]*)\{([^{}]*font-family:ui-serif[^{}]*)\}", css)
    assert serif
    for sel, body in serif:
        assert "font-variant-numeric:lining-numstabular-nums" in body, sel
    covered = set(serif[0][0].strip().split(","))
    assert {".verdict-sentence", ".level-block.lvl", ".serif-title"} <= covered


# --------------------------------------------------------------------------- #
# 2. the green strip
# --------------------------------------------------------------------------- #


def test_green_strip_is_a_tint_with_an_l0_border() -> None:
    d = _rules(False)[".strip.green"]
    assert d["background"] == "var(--l0-tint)"
    assert d["color"] == "var(--text)"
    assert "var(--l0)" in d["border"]
    tint = theme.TOKENS[theme.STRIP_TINT]
    assert theme.contrast(theme.TOKENS["text"], tint) >= theme.TEXT_MIN
    assert theme.contrast(theme.TOKENS["l0"], tint) >= theme.UI_MIN
    for token in theme.STRIP_CONTENT_UI:  # chip fills (levels) and outlines (grey, info)
        assert theme.contrast(theme.TOKENS[token], tint) >= theme.UI_MIN, token
    assert theme.contrast(theme.TOKENS[theme.STRIP_ARROW], tint) >= theme.UI_MIN
    # The arrow keeps the muted colour wherever it sits.
    assert _rules(False)[".arrow"]["color"] == f"var(--{theme.STRIP_ARROW})"


# --------------------------------------------------------------------------- #
# 4. the segmented toggle
# --------------------------------------------------------------------------- #


def test_toggle_is_one_segmented_row() -> None:
    r = _rules(False)
    assert r[".seg"]["flex-wrap"] == "nowrap"
    assert r[".seg .btn"]["white-space"] == "nowrap"
    from hauntlet.scorecard import copy

    # Two buttons at 15 px sans with their padding and the divider, at 320 px wide:
    # main padding 32, card border 2, narrow hero padding 32.
    pad = 2 * 14 + 2
    width = sum(len(lbl) * 15 * SANS + pad for lbl in (copy.VIEW_BEFORE, copy.VIEW_AFTER)) + 4
    assert width <= 320 - 32 - 2 - 32, width


@settings(max_examples=30, deadline=None)
@given(case=scorecard_inputs(kinds=("demo", "real"), states=("final",)))
def test_hero_toggle_uses_the_segmented_style(case) -> None:
    doc = parse(render(build(case.inp)))
    groups = [a for t, a in doc.elements if a.get("role") == "group" and a.get("aria-label")]
    assert groups and all("seg" in a["class"].split() for a in groups)


# --------------------------------------------------------------------------- #
# 5. paths
# --------------------------------------------------------------------------- #


def test_path_breaks_only_after_slashes() -> None:
    assert path(".kiro/steering/a.md") == ".kiro/<wbr>steering/<wbr>a.md"
    assert path("a<b/c&d") == "a&lt;b/<wbr>c&amp;d"
    assert path("no-slash") == "no-slash"
    assert path(".kiro/hooks/x.json#rule-a") == ".kiro/<wbr>hooks/<wbr>x.json<wbr>#rule-a"
    assert path(".kiro/settings/mcp.json#srv.autoApprove") == ".kiro/<wbr>settings/<wbr>mcp.json<wbr>#srv<wbr>.autoApprove"
    assert _rules(False)[".path"]["overflow-wrap"] == "normal"
    for sel, d in _rules(False).items():
        if ".strip" in sel or ".path" in sel:
            assert d.get("overflow-wrap") != "anywhere", sel
            assert d.get("word-break") not in ("break-all", "break-word"), sel


@settings(max_examples=40, deadline=None)
@given(case=scorecard_inputs(kinds=("demo", "real", "pending"), states=("final",)))
def test_every_wbr_follows_a_slash_or_precedes_a_hash(case) -> None:
    html = render(build(case.inp))
    for m in re.finditer(r"<wbr>", html):
        ok = html[m.start() - 1] == "/" or html[m.end()] in "#."
        assert ok, html[m.start() - 40 : m.start() + 5]


# --------------------------------------------------------------------------- #
# 3. nothing wider than its container at 375 px
# --------------------------------------------------------------------------- #

VW = 375


def _px(v: str) -> float:
    return 0.0 if v in ("0", "auto") else float(v[:-2])


def _hpad(sel_rules: dict[str, str]) -> float:
    """Horizontal padding plus left and right borders of one rule, in px."""
    total = 0.0
    if "padding" in sel_rules:
        p = [_px(x) for x in sel_rules["padding"].split()]
        if len(p) == 1:
            total += 2 * p[0]
        elif len(p) in (2, 3):
            total += 2 * p[1]
        else:
            total += p[1] + p[3]
    if "padding-left" in sel_rules:
        total += _px(sel_rules["padding-left"])
    if "border" in sel_rules:
        m = re.match(r"(\d+)px", sel_rules["border"])
        total += 2 * float(m.group(1)) if m else 0.0
    return total


def _matching(stack, i, rules) -> list[dict[str, str]]:
    tag, attrs = stack[i]
    classes = attrs.get("class", "").split()
    outer = {c for _, a in stack[:i] for c in a.get("class", "").split()}
    found = []
    cands = {tag} | {f".{c}" for c in classes} | {f"{tag}.{c}" for c in classes}
    cands |= {f".{a}.{b}" for a in classes for b in classes if a != b}
    cands |= {f".{o} {tag}" for o in outer} | {f".{o} .{c}" for o in outer for c in classes}
    for sel in cands:
        if sel in rules:
            found.append(rules[sel])
    return found


def container_width(stack) -> float | None:
    """Width left for a text node, or None when it may wrap anywhere or scroll in its own region."""
    rules = _rules(True)
    width = VW - 32.0
    for i, (tag, attrs) in enumerate(stack):
        classes = attrs.get("class", "").split()
        if "log-wrap" in classes or "sr" in classes:
            return None
        if tag == "pre" or "wrap-any" in classes:
            return None
        if tag == "code" and "path" not in classes:
            return None  # code wraps anywhere; only paths keep their words
        matched = _matching(stack, i, rules)
        if tag in ("ul", "ol") and not any("padding" in m or "padding-left" in m for m in matched):
            width -= 40  # the browser's default list indent
        for m in matched:
            width -= _hpad(m)
    return width


def _segments(text: str, is_path: bool) -> list[str]:
    out = []
    for word in text.split():
        if is_path:
            file_part, hash_, rule = word.partition("#")
            out += [s for s in re.split(r"(?<=/)", file_part) if s]
            if hash_:
                out += [s for s in re.split(r"(?=\.)", "#" + rule) if s]
        else:
            out.append(word)
    return out


def _font(stack) -> tuple[float, float]:
    rules = _rules(True)
    size, k = 15.0, SANS
    for i, (tag, attrs) in enumerate(stack):
        for m in _matching(stack, i, rules):
            if "font-size" in m and m["font-size"].endswith("px"):
                size = float(m["font-size"][:-2])
            if "font-family" in m and "monospace" in m["font-family"]:
                k = MONO
        if tag == "code":
            k = MONO
    return size, k


def overflows(html: str) -> list[tuple[str, float, float]]:
    bad = []
    for n in parse(html).nodes:
        width = container_width(n.stack)
        if width is None:
            continue
        is_path = any("path" in a.get("class", "").split() for _, a in n.stack)
        size, k = _font(n.stack)
        for seg in _segments(n.text, is_path):
            need = len(seg) * size * k
            if need > width:
                bad.append((seg, round(need), round(width)))
    return bad


def test_no_fixed_width_wider_than_the_screen() -> None:
    for sel, d in _rules(True).items():
        for prop in ("width", "min-width"):
            v = d.get(prop, "")
            if v.endswith("px") and float(v[:-2]) > VW - 32:
                assert sel in (".log",), (sel, prop, v)  # .log scrolls inside .log-wrap (12.6)
    assert _rules(True)[".log-wrap"]["overflow-x"] == "auto"


@pytest.fixture(scope="module")
def real_pages(tmp_path_factory) -> dict[str, str]:
    from hauntlet.agents import get_agent
    from hauntlet.core.runner import run_once
    from hauntlet.core.service import RangeService
    from hauntlet.core.store import Store
    from hauntlet.exorcist.service import ExorcistService
    from hauntlet.paths import scratch_root_beside
    from hauntlet.rooms import default_rooms
    from hauntlet.scorecard import render_exorcism, render_launcher, render_run

    tmp = tmp_path_factory.mktemp("pages")
    db = tmp / "range.db"
    svc = RangeService(Store(db), default_rooms())
    ex = ExorcistService(svc, tmp / "ex")
    pages = {}
    for room in ("cursed-repo", "poltergeist"):
        bundle = ex.demo(room).bundle_dir
        pages[f"demo-{room}-static"] = render_exorcism(ex, bundle)
        pages[f"demo-{room}-served"] = render_exorcism(ex, bundle, served=True, download_url="/exorcisms/x/bundle")
    for room in sorted(default_rooms()):
        r = run_once(svc, room, get_agent("naive"), scratch_root_beside(db), keep_workspace=True)
        pages[f"naive-{room}"] = render_run(svc, r.score.run_id, path="reference:naive", db_path=db)
    pages["launcher"] = render_launcher(["cursed-repo", "poltergeist"])
    return pages


def test_real_pages_fit_at_375(real_pages) -> None:
    for name, html in real_pages.items():
        assert not overflows(html), (name, overflows(html)[:3])


@settings(max_examples=60, deadline=None)
@given(case=scorecard_inputs())
def test_synthetic_pages_fit_at_375(case) -> None:
    html = render(build(case.inp))
    assert not overflows(html), overflows(html)[:3]


def test_the_width_check_can_fail() -> None:
    long_path = '<main><ul class="file-rows"><li class="file-row"><div class="file-line"><code class="path">' + path(
        ".kiro/" + "x" * 60 + ".md") + "</code></div></li></ul></main>"
    assert overflows(long_path)
    long_word = "<main><p>" + "y" * 80 + "</p></main>"
    assert overflows(long_word)
