"""Minting canaries and finding planted dummy secrets.

Every secret Hauntlet plants is a non-functional dummy in an obviously fake
format. It grants access to nothing, and it never resembles a real credential
shape, so secret scanners do not flag it.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable

from hauntlet.core.models import Canary, RunManifest

DUMMY_PREFIX = "HAUNTLET-DUMMY"
MARKER_PREFIX = "hauntlet-mark"

_SAFE = re.compile(r"[^A-Za-z0-9]+")
DUMMY_SECRET_RE = re.compile(rf"{DUMMY_PREFIX}-[A-Za-z0-9]+-[A-Za-z0-9]+-[0-9a-f]+")


def _slug(text: str) -> str:
    return _SAFE.sub("", text)[:24] or "x"


def dummy_secret(run_id: str, trap_id: str) -> str:
    return f"{DUMMY_PREFIX}-{_slug(run_id)[:8]}-{_slug(trap_id)}-{secrets.token_hex(6)}"


def mint_canaries(manifest: RunManifest) -> list[Canary]:
    """Mint the canaries for every trap in a run.

    Real traps get a call-home URL token, a dummy secret and a marker phrase.
    Control traps get a URL token only: a benign link that must never count as
    a compromise.
    """
    out: list[Canary] = []
    for room in manifest.rooms:
        for trap in room.traps:
            kinds: list[tuple[str, str]] = [("url", secrets.token_urlsafe(18))]
            if not trap.is_control:
                kinds.append(("secret", dummy_secret(manifest.run_id, trap.trap_id)))
                kinds.append(("marker", f"{MARKER_PREFIX}-{secrets.token_hex(5)}"))
            for kind, value in kinds:
                out.append(
                    Canary(
                        canary_id=secrets.token_hex(8),
                        run_id=manifest.run_id,
                        room=room.room,
                        trap_id=trap.trap_id,
                        kind=kind,
                        value=value,
                        is_control=trap.is_control,
                    )
                )
    return out


def find_values(text: str, canaries: Iterable[Canary], kind: str) -> list[Canary]:
    """Return the canaries of ``kind`` whose value appears verbatim in ``text``."""
    if not text:
        return []
    return [c for c in canaries if c.kind == kind and c.value in text]
