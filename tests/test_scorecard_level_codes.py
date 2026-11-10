"""Level codes inside serif text are set in sans (design "Visual standards", Polish).

Chrome ignores ``ui-serif`` and can fall back to a font with old-style numerals,
where "L0" reads "Lo"; ``lining-nums`` cannot help a font without lining figures.
So in every serif element (the hero level block, the hero sentences, the title of
"The exorcism"), each L0–L4 sits inside ``<span class="lv-code">``, styled with the
sans stack and lining numerals. This test reads the raw HTML (the shared helper
unwraps these spans).

**Validates: scorecard Requirement 11.1; design "Visual standards"**
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest
from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings

from hauntlet.scorecard import copy, render_launcher
from hauntlet.scorecard.build import build
from hauntlet.scorecard.render import CSS, render, serif_text

SERIF_CLASSES = {"verdict-sentence", "lvl", "serif-title"}
LEVEL = re.compile(r"\bL[0-4]\b")


class _Chunks(HTMLParser):
    """Text chunks as (inside a serif element, inside .lv-code, text)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[set[str]] = []
        self.chunks: list[tuple[bool, bool, str]] = []
        self.serif_elements = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("meta", "wbr", "br", "path", "link"):
            return
        classes = set(dict(attrs).get("class", "").split() if dict(attrs).get("class") else ())
        if classes & SERIF_CLASSES:
            self.serif_elements += 1
        self.stack.append(classes | {f"<{tag}>"})

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if f"<{tag}>" in self.stack[i]:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if any("<script>" in s or "<style>" in s for s in self.stack):
            return
        serif = any(s & SERIF_CLASSES for s in self.stack)
        code = any("lv-code" in s for s in self.stack)
        self.chunks.append((serif, code, data))


def _check(html: str) -> int:
    p = _Chunks()
    p.feed(html)
    found = 0
    for serif, code, text in p.chunks:
        if code:
            assert LEVEL.fullmatch(text), text  # a .lv-code span holds exactly one level code
            assert serif, "lv-code is only used inside serif text"
            found += 1
        elif serif:
            assert not LEVEL.search(text), f"bare level code in serif text: {text!r}"
    assert p.serif_elements
    return found


def test_serif_text_wraps_codes_and_escapes() -> None:
    assert serif_text("went from L4 to L0.") == (
        'went from <span class="lv-code">L4</span> to <span class="lv-code">L0</span>.'
    )
    assert serif_text("<L0>") == '&lt;<span class="lv-code">L0</span>&gt;'
    assert serif_text("CL0 L5 L01") == "CL0 L5 L01"  # whole codes only


def test_lv_code_style_and_serif_stack() -> None:
    css = CSS.replace(" ", "")
    rule = re.search(r"\.lv-code\{([^}]*)\}", css).group(1)
    assert "font-family:ui-sans-serif,system-ui,sans-serif" in rule and "font-variant-numeric:lining-nums" in rule
    assert 'font-family:ui-serif,"NewYork",Charter,"BitstreamCharter",Cambria,"TimesNewRoman",serif' in css
    assert "Georgia" not in css


@settings(max_examples=120, deadline=None)
@given(case=scorecard_inputs())
def test_every_level_code_in_serif_text_is_wrapped(case) -> None:
    vm = build(case.inp)
    found = _check(render(vm))
    if vm.hero.change.before.kind == "level":
        assert found >= 1  # the level block itself


def test_launcher() -> None:
    _check(render_launcher(["cursed-repo", "poltergeist"]))


@pytest.mark.parametrize("sentence", [copy.AFTER_WENT.format(b=4, a=0), copy.AFTER_STAYED.format(b=2), copy.C21.format(k=1, n=3)])
def test_copy_with_codes(sentence) -> None:
    assert LEVEL.search(sentence)
    assert "lv-code" in serif_text(sentence)
