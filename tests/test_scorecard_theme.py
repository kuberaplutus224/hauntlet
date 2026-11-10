"""Colour tokens and contrast (scorecard SP13, example; task 12.4).

- colour literals appear only in the ``:root`` token block, with the values of
  Requirement 11.3;
- every (foreground, background) pair the stylesheet uses is in ``theme.PAIRS``
  and meets 4.5:1 for text or 3:1 for a focus ring or sole boundary, computed
  with the WCAG relative-luminance formula;
- ``--accent`` is never a text colour; ``--border`` is never a control's only
  boundary; red (``--l4``) is used only by the L4 chip.

How pairs are derived from a rule: a ``color`` with a ``background`` in the same
rule is one pair; a ``color`` with no ``background`` is checked on every
surface; a ``background`` with no ``color`` is checked with ``--text``; an
``outline`` or ``border`` colour is a UI pair on every surface and against the
rule's own fill (unless it is the fill); a filled control's fill is a UI pair on
every surface; everything that sits on the green strip is checked on its tint.

**Validates: scorecard Requirements 11.3, 11.4, 12.1, SP13**
"""

from __future__ import annotations

import re

from hauntlet.scorecard import theme
from hauntlet.scorecard.render import CSS

RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
VAR = re.compile(r"var\(--([a-z0-9-]+)\)")


def _rules() -> list[tuple[str, dict[str, str]]]:
    out = []
    flat = re.sub(r"@media[^{]*\{((?:[^{}]*\{[^{}]*\})*)\s*\}", r"\1", CSS)
    for sel, body in RULE.findall(flat):
        decls = {}
        for d in body.split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls[k.strip()] = v.strip()
        out.append((sel.strip(), decls))
    return out


def _var(value: str | None) -> str | None:
    if not value:
        return None
    m = VAR.search(value)
    return m.group(1) if m else None


def test_tokens_and_literals() -> None:
    root = CSS.split(":root{", 1)[1].split("}", 1)[0]
    declared = dict(re.findall(r"--([a-z0-9-]+):(#[0-9A-Fa-f]{6})", root))
    assert declared == theme.TOKENS
    rest = CSS.replace(":root{" + root + "}", "")
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", rest), "colour literal outside :root"
    assert not re.search(r"\b(rgb|rgba|hsl|hsla)\(", rest)
    for name in ("white", "black", "red", "green", "gray", "grey", "purple"):
        assert not re.search(rf":\s*{name}\b", rest), name


def test_every_used_pair_is_allowed_and_passes() -> None:
    used: set[tuple[str, str, str]] = set()
    for sel, d in _rules():
        if sel == ":root":
            continue
        fg = _var(d.get("color"))
        bg = _var(d.get("background") or d.get("background-color"))
        if fg and bg:
            used.add((fg, bg, "text"))
        elif fg:
            used |= {(fg, s, "text") for s in theme.SURFACES}
        elif bg and bg not in theme.SURFACES:
            used.add(("text", bg, "text"))
        for prop in ("outline", "border", "border-color"):
            c = _var(d.get(prop))
            if c and c != "border":
                used |= {(c, s, "ui") for s in theme.SURFACES}
                if bg and bg not in theme.SURFACES and c != bg:
                    used.add((c, bg, "ui"))  # a border against its own fill (the green strip)
        if bg and bg not in theme.SURFACES and any(k in sel for k in ("button", ".btn", "summary")):
            used |= {(bg, s_, "ui") for s_ in theme.SURFACES}  # a filled control's edge is its fill
        if bg == theme.STRIP_TINT:
            # Everything that sits on the green strip: chip fills and outlines, and the arrow.
            used |= {(c, bg, "ui") for c in theme.STRIP_CONTENT_UI} | {(theme.STRIP_ARROW, bg, "text")}
    assert used
    for fg, bg, kind in sorted(used):
        assert (fg, bg, kind) in theme.PAIRS, (fg, bg, kind)
    for fg, bg, kind in theme.PAIRS:
        ratio = theme.contrast(theme.TOKENS[fg], theme.TOKENS[bg])
        assert ratio >= theme.minimum(kind), (fg, bg, kind, round(ratio, 2))


def test_accent_border_and_red_rules() -> None:
    for sel, d in _rules():
        assert _var(d.get("color")) != "accent", sel
        if "--l4" in "".join(d.values()) and sel != ":root":
            assert sel == ".lv4", sel
        # ".room-card.off" is a not-run room: a <div>, not a control, so its border is decorative.
        if any(k in sel for k in ("button", ".btn", "summary", ".room-card")) and ".off" not in sel:
            for prop in ("border", "border-color"):
                assert _var(d.get(prop)) != "border", sel


def test_known_ratios() -> None:
    assert round(theme.contrast("#FFFFFF", "#9046FF"), 2) == 4.66
    assert round(theme.contrast("#FAFAFA", "#9046FF"), 2) == 4.47  # why on-accent is pure white
    assert theme.contrast("#352F3D", "#19161D") < 3  # why --border is decorative only
