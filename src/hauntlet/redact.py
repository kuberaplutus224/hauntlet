"""Canary redaction shared by the scorecard and the Exorcist's demo evidence (approved D31).

A canary value is a run's URL token, page token, marker or dummy secret. Before
any text from a run is shown or kept as evidence, every canary value in it is
replaced:

- a dummy secret by ``HAUNTLET-DUMMY-…``;
- a marker by ``hauntlet-mark-…``;
- a URL or page token by ``<token>`` (so ``/c/<token>``).

``redactor(canaries)`` applies, in order:

1. the run's exact values (approved D30 gives them), longest first;
2. patterns that also catch values from other runs, or when no canary list is
   given: the two prefixes, and any ``/c/<path segment>``;
3. the same two steps on the URL-decoded text. When decoding reveals anything to
   redact, the decoded, redacted text is returned, so a percent-encoded secret
   is caught too.

The result is idempotent: redacting redacted text changes nothing. This module
lives outside ``hauntlet.core`` and imports only core constants and types.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from urllib.parse import unquote

from hauntlet.core.canary import DUMMY_PREFIX, MARKER_PREFIX
from hauntlet.core.models import Canary

ELLIPSIS = "…"
SECRET_SHOWN = f"{DUMMY_PREFIX}-{ELLIPSIS}"
MARKER_SHOWN = f"{MARKER_PREFIX}-{ELLIPSIS}"
TOKEN_SHOWN = "<token>"

#: A prefixed value runs until whitespace, a quote, an angle bracket or ``&``.
#: The ellipsis is part of the run, so a redacted value matches itself.
_TAIL = r"""[^\s"'<>&]*"""
_SECRET_RE = re.compile(re.escape(DUMMY_PREFIX) + "-" + _TAIL, re.IGNORECASE)
_MARKER_RE = re.compile(re.escape(MARKER_PREFIX) + "-" + _TAIL, re.IGNORECASE)
_CANARY_PATH_RE = re.compile(r"/c/[A-Za-z0-9_-]+")
#: How many times percent-decoding is repeated (double-encoded input).
_MAX_DECODE = 4


def _exact_pass(canaries: Iterable[Canary]) -> Callable[[str], str]:
    pairs: list[tuple[re.Pattern[str], str]] = []
    for c in sorted({(c.kind, c.value) for c in canaries if c.value}, key=lambda kv: -len(kv[1])):
        kind, value = c
        if kind == "secret":
            pairs.append((re.compile(re.escape(value), re.IGNORECASE), SECRET_SHOWN))
        elif kind == "marker":
            pairs.append((re.compile(re.escape(value), re.IGNORECASE), MARKER_SHOWN))
        else:  # "url", "page", and any future kind: a token, case-sensitive
            pairs.append((re.compile(re.escape(value)), TOKEN_SHOWN))

    def apply(text: str) -> str:
        for pattern, shown in pairs:
            text = pattern.sub(shown, text)
        return text

    return apply


def _pattern_pass(text: str) -> str:
    text = _SECRET_RE.sub(SECRET_SHOWN, text)
    text = _MARKER_RE.sub(MARKER_SHOWN, text)
    return _CANARY_PATH_RE.sub("/c/" + TOKEN_SHOWN, text)


def _decoded(text: str) -> str:
    for _ in range(_MAX_DECODE):
        nxt = unquote(text)
        if nxt == text:
            break
        text = nxt
    return text


def redactor(canaries: Iterable[Canary] = ()) -> Callable[[str], str]:
    """A function that redacts every canary value (the given ones and any pattern match)."""
    exact = _exact_pass(canaries)

    def plain(text: str) -> str:
        return _pattern_pass(exact(text))

    def redact(text: str) -> str:
        if not isinstance(text, str):
            text = str(text)
        decoded = _decoded(text)
        if decoded != text:
            red = plain(decoded)
            if red != decoded:
                return red
        return plain(text)

    return redact


#: Pattern-only redaction, for text that has no run (or no canary list).
redact_patterns = redactor(())
