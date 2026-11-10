"""Colour tokens (Requirement 11.3) and the token pairs the stylesheet may use (Requirement 12.1).

``PAIRS`` lists every (foreground, background, kind) combination the stylesheet
uses. ``kind`` is ``"text"`` (needs 4.5:1) or ``"ui"`` (a focus ring or a
component's only boundary: needs 3:1). The theme test derives the pairs the CSS
actually uses and checks each is listed here and passes.
"""

from __future__ import annotations

TOKENS: dict[str, str] = {
    "page": "#000000",
    "surface-1": "#19161D",
    "surface-2": "#28242E",
    "border": "#352F3D",
    "text": "#FAFAFA",
    "muted": "#A39FAB",
    "accent": "#9046FF",
    "on-accent": "#FFFFFF",
    "accent-text": "#C59EFF",
    "l0": "#33D480",
    "l1": "#EFE08A",
    "l2": "#FFC857",
    "l3": "#FF9F5A",
    "l4": "#FF7A88",
    "on-level": "#000000",
    "info": "#69A0F6",
}

SURFACES = ("page", "surface-1", "surface-2")
LEVELS = ("l0", "l1", "l2", "l3", "l4")
#: Foregrounds allowed as text on any surface.
TEXT_ON_SURFACES = ("text", "muted", "accent-text", "info", *LEVELS)

TEXT_MIN = 4.5
UI_MIN = 3.0

PAIRS: frozenset[tuple[str, str, str]] = frozenset(
    {(fg, bg, "text") for fg in TEXT_ON_SURFACES for bg in SURFACES}
    | {("on-level", lv, "text") for lv in LEVELS}
    | {("on-accent", "accent", "text")}
    # Focus ring and outlined controls on every surface.
    | {("accent-text", bg, "ui") for bg in SURFACES}
    # Outlined grey and info chips: the outline is their only boundary.
    | {("muted", bg, "ui") for bg in SURFACES}
    | {("info", bg, "ui") for bg in SURFACES}
)


def _channel(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG 2.x contrast ratio between two ``#RRGGBB`` colours."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def minimum(kind: str) -> float:
    return TEXT_MIN if kind == "text" else UI_MIN
