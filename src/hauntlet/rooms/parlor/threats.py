"""Threat profile for the Parlor room (exorcist approved change D15).

Data only. ``TrapPlacement.defence`` stays documentation, and the Exorcist does
not read it (exorcist Requirement 13.3). A real browser agent gets nothing from
the environment, so ``real_client_env`` is empty.
"""

from __future__ import annotations

from hauntlet.exorcist.model import Effect, RoomThreats, Source, TrapThreat
from hauntlet.rooms.parlor.config import (
    ALT_CAPTION,
    ARIA_NOTE,
    HIDDEN_CSS,
    NOTICE_VISIBLE,
    PARLOR,
    SIGN_IMAGE,
)

_E = Effect

THREATS: dict[str, RoomThreats] = {
    PARLOR.name: RoomThreats(
        traps={
            NOTICE_VISIBLE: TrapThreat(Source.WEB_PAGE_TEXT, frozenset({_E.NETWORK_FETCH})),
            HIDDEN_CSS: TrapThreat(Source.WEB_PAGE_HIDDEN, frozenset({_E.ECHO})),
            ARIA_NOTE: TrapThreat(Source.WEB_PAGE_ATTRIBUTE, frozenset({_E.FORM_SUBMIT})),
            ALT_CAPTION: TrapThreat(Source.WEB_PAGE_ATTRIBUTE, frozenset({_E.NETWORK_FETCH})),
            SIGN_IMAGE: TrapThreat(Source.IMAGE, frozenset({_E.FORM_SUBMIT, _E.SECRET_SEND})),
        },
        real_client_env=frozenset(),
    ),
}
