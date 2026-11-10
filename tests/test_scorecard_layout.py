"""Where the verdict lands on screen, estimated without a browser (design "Visual standards"; Q3).

The estimate stacks block heights from the top of the page: line height ×
wrapped lines, plus padding, margins and borders. Every number is read from the
stylesheet, and text is wrapped word by word with average character widths of
0.55 em (sans), 0.52 em (serif) and 0.6 em (mono), so a change to the CSS or to
the copy moves the estimate. It checks:

- at 1280 px wide, the hero chip and sentence (Before view) and the
  before → after strip (After view) end above 900 px;
- at 375 × 667, the hero chip and sentence end within the first screen, and the
  strip and its chips have no ``nowrap`` and no fixed width, so they wrap
  instead of running off screen.

It is an estimate. The manual release gate (task 22) is the real check.

**Validates: scorecard Requirements 3.1, 12.6; design "Visual standards"**
"""

from __future__ import annotations

import math
import re
from functools import lru_cache

import pytest
from _scorecard_html import parse
from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings

from hauntlet.scorecard.build import build
from hauntlet.scorecard.render import CSS, render

SANS, SERIF, MONO = 0.55, 0.52, 0.6
LIMIT_1280 = 900
SCREEN_375 = 667


# --------------------------------------------------------------------------- #
# stylesheet numbers
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=None)
def _rules(narrow: bool) -> dict[str, dict[str, str]]:
    css = CSS
    base = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*\s*\}", "", css)
    out: dict[str, dict[str, str]] = {}

    def add(text: str) -> None:
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            for one in sel.split(","):
                d = out.setdefault(one.strip(), {})
                for decl in body.split(";"):
                    if ":" in decl:
                        k, v = decl.split(":", 1)
                        d[k.strip()] = v.strip()

    add(base)
    if narrow:
        m = re.search(r"@media \(max-width:480px\)\{((?:[^{}]*\{[^{}]*\})*)\}", css)
        assert m, "narrow-screen block"
        add(m.group(1))
    return out


def px(sel: str, prop: str, narrow: bool = False) -> float:
    v = _rules(narrow)[sel][prop]
    m = re.match(r"(-?\d+(?:\.\d+)?)px", v)
    assert m, (sel, prop, v)
    return float(m.group(1))


def box(sel: str, prop: str, narrow: bool = False) -> tuple[float, float]:
    """(vertical, horizontal) total of a padding/margin shorthand, in px."""
    parts = [float(x[:-2]) for x in _rules(narrow)[sel][prop].split()]
    if len(parts) == 1:
        return 2 * parts[0], 2 * parts[0]
    if len(parts) == 2:
        return 2 * parts[0], 2 * parts[1]
    if len(parts) == 3:
        return parts[0] + parts[2], 2 * parts[1]
    return parts[0] + parts[2], parts[1] + parts[3]


def line_height(sel: str, size: float, narrow: bool = False) -> float:
    d = _rules(narrow).get(sel, {})
    lh = d.get("line-height")
    if lh is None and "font" in d:
        lh = re.search(r"/(\d+(?:\.\d+)?)", d["font"]).group(1)
    return size * float(lh or 1.5)


def lines(text: str, size: float, width: float, k: float) -> int:
    """Greedy word wrap with an average character width of ``k`` em."""
    cpl = max(1, int(width / (size * k)))
    n, cur = 1, 0
    for w in text.split():
        w_len = len(w)
        while w_len > cpl:  # overflow-wrap:anywhere breaks long IDs
            n += 1 if cur else 0
            w_len -= cpl
            cur = 0
        if cur and cur + 1 + w_len > cpl:
            n += 1
            cur = w_len
        else:
            cur = cur + (1 if cur else 0) + w_len
    return n


# --------------------------------------------------------------------------- #
# the model
# --------------------------------------------------------------------------- #


def _texts(doc, **where) -> list[str]:
    return [n.text for n in doc.nodes if n.inside(**where)]


def estimate(html: str, vw: int, view: str) -> dict[str, float]:
    """Bottom y of the hero chip, sentence and strip in ``view`` ("before"/"after")."""
    narrow = vw <= 480
    doc = parse(html)
    inner = vw - 32  # header and main side padding (16 px each)

    # Header: padding, the badge (bordered, padded, wrapped), the brand line(s).
    y = box("header.frame", "padding")[0] / 2
    badge = " ".join(_texts(doc, tag="p", class_="badge"))
    b_size = px(".badge", "font-size")
    b_pad = box(".badge", "padding")
    y += 2 + b_pad[0] + lines(badge, b_size, inner - b_pad[1] - 2, SANS) * line_height(".badge", b_size)
    y += float(_rules(False)[".badge"]["margin"].split()[2][:-2])  # margin-bottom
    brand = " ".join(n.text for n in doc.nodes if n.inside("div", class_="brand"))
    meta = px(".meta", "font-size")
    y += max(26.0, lines(brand, meta, inner - 60, SANS) * line_height(".brand", meta))
    y += box("header.frame", "padding")[0] / 2 + 1

    # Main, the section label, the hero card.
    y += float(_rules(False)["main"]["padding"].split()[0][:-2])
    y += line_height("h2.label", px("h2.label", "font-size")) + float(_rules(False)["h2"]["margin"].split()[2][:-2])
    hero_v, hero_h = box(".hero", "padding", narrow)
    y += 1 + hero_v / 2
    card_w = min(inner, 1120 - 32) - 2 - hero_h
    if any(n.inside("section", id="verdict") and n.inside(role="group") for n in doc.nodes):
        y += 44 + float(_rules(False)[".toggle"]["margin"].split()[2][:-2])  # the Before/After toggle

    out: dict[str, float] = {}
    if view == "before":
        lvl = px(".level-block .lvl", "font-size", narrow)
        word = px(".level-block .word", "font-size")
        block_h = box(".level-block", "padding")[0] + lvl * 1.0 + word * 1.3
        sentence = " ".join(_texts(doc, tag="p", class_="verdict-sentence")) if "v-before" not in html else " ".join(
            n.text for n in doc.nodes if n.inside(class_="v v-before") and n.inside(data_sentence=True)
        )
        s_size = px(".verdict-sentence", "font-size", narrow)
        s_lh = line_height(".verdict-sentence", s_size)
        block_w = 140 + box(".level-block", "padding")[1]
        side = card_w >= block_w + 24 + 260
        s_width = min(card_w - block_w - 24, 30 * s_size * SERIF) if side else min(card_w, 30 * s_size * SERIF)
        s_h = lines(sentence, s_size, s_width, SERIF) * s_lh
        out["chip"] = y + block_h
        out["sentence"] = y + (s_h if side else block_h + 16 + s_h)
    else:
        sv, sh = box(".strip", "padding")
        w = card_w - sh
        chip_big = px(".chip.big", "font-size")
        states = " ".join(n.text for n in doc.nodes if n.inside(data_strip=True) and n.inside(class_="strip-states"))
        h = sv + lines(states, chip_big, w, SANS) * (chip_big * 1.4 + 12 + 2) + 6
        h += line_height("body", 15) + 6
        note = " ".join(n.text for n in doc.nodes if n.inside(data_strip=True) and n.inside(class_="strip-note"))
        if note:
            h += lines(note, 13, w, SANS) * 13 * 1.5 + 6
        caused = " ".join(n.text for n in doc.nodes if n.inside(data_strip=True) and n.inside(class_="strip-caused"))
        if caused:
            h += lines(caused, 13, w, MONO) * 13 * 1.5
        out["strip"] = y + h
    return out


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def demo_pages(tmp_path_factory) -> dict[str, str]:
    from hauntlet.core.service import RangeService
    from hauntlet.core.store import Store
    from hauntlet.exorcist.service import ExorcistService
    from hauntlet.rooms import default_rooms
    from hauntlet.scorecard import render_exorcism

    svc = RangeService(Store(":memory:"), default_rooms())
    ex = ExorcistService(svc, tmp_path_factory.mktemp("ex"))
    return {room: render_exorcism(ex, ex.demo(room).bundle_dir) for room in ("cursed-repo", "poltergeist")}


@pytest.mark.parametrize("room", ["cursed-repo", "poltergeist"])
def test_demo_pages_put_the_verdict_on_the_first_screen(demo_pages, room) -> None:
    html = demo_pages[room]
    wide_b, wide_a = estimate(html, 1280, "before"), estimate(html, 1280, "after")
    assert wide_b["chip"] < LIMIT_1280 and wide_b["sentence"] < LIMIT_1280, wide_b
    assert wide_a["strip"] < LIMIT_1280, wide_a
    narrow = estimate(html, 375, "before")
    assert narrow["chip"] < SCREEN_375 and narrow["sentence"] < SCREEN_375, narrow


@settings(max_examples=60, deadline=None)
@given(case=scorecard_inputs())
def test_any_page_puts_the_verdict_on_the_first_screen(case) -> None:
    vm = build(case.inp)
    html = render(vm)
    b = estimate(html, 1280, "before")
    assert b["chip"] < LIMIT_1280 and b["sentence"] < LIMIT_1280, b
    n = estimate(html, 375, "before")
    assert n["chip"] < SCREEN_375 and n["sentence"] < SCREEN_375, n
    if vm.hero.strip is not None:
        assert estimate(html, 1280, "after")["strip"] < LIMIT_1280


def test_strip_and_chips_wrap_at_narrow_widths() -> None:
    rules = _rules(False)
    for sel, d in rules.items():
        if any(k in sel for k in (".strip", ".chip", ".level-block", ".hero", ".verdict-sentence")):
            assert d.get("white-space") != "nowrap", sel
            w = d.get("width", "")
            assert not re.match(r"\d+px", w) or float(w[:-2]) <= 320, sel
            mw = d.get("min-width", "0px")
            assert float(mw[:-2] or 0) <= 200, sel


def test_estimate_moves_with_the_stylesheet() -> None:
    """Sanity: a much larger hero sentence pushes the estimate down."""
    html = '<header class="frame"><p class="badge">x</p><div class="brand">y</div></header><p class="verdict-sentence" data-sentence>' + "word " * 200 + "</p>"
    short = '<header class="frame"><p class="badge">x</p><div class="brand">y</div></header><p class="verdict-sentence" data-sentence>word</p>'
    assert estimate(html, 1280, "before")["sentence"] > estimate(short, 1280, "before")["sentence"] + 100
    assert math.isfinite(estimate(short, 375, "before")["chip"])
