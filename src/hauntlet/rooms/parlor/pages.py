"""Render the run's pages and the guestbook acknowledgement. Pure, no I/O beyond
reading the committed templates.

Every page carries the ``noindex`` meta (in the template) and a response header
set that forbids script and confines every fetch and form to the run's own
origin (Requirement 2.4, 8.4). Canary URLs appear only as link targets and form
actions, never as subresources (Requirement 8.5): ``img-src 'self'`` is the
page token's own image, not a trap canary.
"""

from __future__ import annotations

from pathlib import Path

from hauntlet.core.room import render_template
from hauntlet.rooms.parlor.config import ACK_TMPL, LEDGER, LEDGER_TMPL, LOBBY, LOBBY_TMPL

_TEMPLATES = Path(__file__).parent / "templates"

HTML_CONTENT_TYPE = "text/html; charset=utf-8"
IMAGE_CONTENT_TYPE = "image/png"

#: Response headers on every page (and the ack). The core middleware adds
#: ``X-Robots-Tag`` separately.
PAGE_HEADERS: tuple[tuple[str, str], ...] = (
    (
        "Content-Security-Policy",
        "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    ),
    ("Cache-Control", "no-store"),
    ("Referrer-Policy", "no-referrer"),
)

_TEMPLATE_BY_PAGE = {LOBBY: LOBBY_TMPL, LEDGER: LEDGER_TMPL}


def render_page(page_id: str, fields: dict[str, str]) -> str:
    """Render ``page_id``'s HTML with ``fields`` filling its placeholders."""
    template = _TEMPLATE_BY_PAGE.get(page_id)
    if template is None:
        raise KeyError(f"no template for page {page_id!r}")
    return render_template(_TEMPLATES / template, **fields)


def render_ack() -> str:
    """The guestbook / notice acknowledgement page (no agent input reflected)."""
    return render_template(_TEMPLATES / ACK_TMPL)
