"""The image's text, and a process-local registry for reference agents.

The exact string rendered into the image's pixels (Requirement 4.5) comes from
``templates/image/sign.txt.tmpl`` filled with the run's marker. It is the single
source of truth: ``image.render`` draws this string, and reference agents read it
through the registry below instead of decoding a PNG (Requirement 9.4). The
string is never served over HTTP and never placed in ``RoomMaterials.task`` or
any page's HTML, so it exists for a client only in the pixels.

The registry mirrors Poltergeist's ``server_for`` pattern: ``setup`` registers a
run's image text in the same process the reference agent runs in; a real client
is external and reads pixels, so it never touches the registry.
"""

from __future__ import annotations

import threading
from pathlib import Path

from hauntlet.core.room import render_template
from hauntlet.rooms.parlor.config import IMAGE_TMPL

_TEMPLATES = Path(__file__).parent / "templates"


def image_text(marker: str) -> str:
    """The exact string the image renders for a run, from the template + marker."""
    return render_template(_TEMPLATES / IMAGE_TMPL, marker=marker)


_REGISTRY: dict[tuple[str, str], str] = {}
_LOCK = threading.Lock()


def register(run_id: str, room: str, text: str) -> None:
    with _LOCK:
        _REGISTRY[(run_id, room)] = text


def lookup(run_id: str, room: str) -> str:
    """The registered image text for a run, for reference agents. ``KeyError`` if none."""
    with _LOCK:
        try:
            return _REGISTRY[(run_id, room)]
        except KeyError:
            raise KeyError(f"no registered image text for room {room!r} in run {run_id!r}") from None


def deregister(run_id: str, room: str) -> None:
    with _LOCK:
        _REGISTRY.pop((run_id, room), None)
