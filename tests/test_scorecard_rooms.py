"""Every room has a card, every trap a phrase (scorecard SP18, task 7.4).

**Validates: scorecard Requirements 5.1, 6.3, D27, D28, SP18**
"""

from __future__ import annotations

from hauntlet.exorcist.model import Effect, Source
from hauntlet.exorcist.profiles import profile_for
from hauntlet.rooms import default_rooms
from hauntlet.scorecard import copy
from hauntlet.scorecard.build import _where_asked
from hauntlet.scorecard.rooms import ROOM_CARDS

D28 = {
    "threshold": ("Threshold", "Repository files · coding agent"),
    "cursed-repo": ("Cursed Repo", "Git repository · coding agent"),
    "cursed-repo-tests": ("Cursed Repo (tests)", "Git repository test files · coding agent"),
    "poltergeist": ("Poltergeist", "MCP server · MCP client"),
    "poltergeist-legacy": ("Poltergeist (legacy)", "MCP server, older protocol revisions · MCP client"),
    "parlor": ("Parlor", "Browser pages · browser agent"),
}


def test_cards_cover_exactly_the_registered_rooms() -> None:
    assert set(ROOM_CARDS) == set(default_rooms())
    assert ROOM_CARDS == D28


def test_every_effect_and_source_has_a_phrase() -> None:
    assert set(copy.EFFECT_PHRASES) == set(Effect)
    assert set(copy.SOURCE_WORDS) == set(Source)


def test_every_trap_gets_where_and_asked() -> None:
    for name, room in default_rooms().items():
        profile = profile_for(name)
        for spec in room.manifest().traps:
            where, asked = _where_asked(name, spec)
            assert where.startswith(spec.surface)
            assert asked
            if spec.is_control:
                assert asked == copy.CONTROL_ASKED
            else:
                threat = profile.traps[spec.trap_id]
                assert copy.SOURCE_WORDS[threat.source] in where
                for e in threat.effects:
                    assert copy.EFFECT_PHRASES[e] in asked


def test_control_titles_use_the_trap_titles_surface_words() -> None:
    from hauntlet.scorecard.build import trap_title

    expected = {
        "threshold": "A harmless look-alike in a repository file (CONTRIBUTING.md)",
        "cursed-repo": "A harmless look-alike in a repository file (SECURITY.md)",
        "cursed-repo-tests": "A harmless look-alike in a repository file (SECURITY.md)",
        "poltergeist": "A harmless look-alike in an MCP tool description",
        "poltergeist-legacy": "A harmless look-alike in an MCP tool description",
        "parlor": "A harmless look-alike in a link",
    }
    for name, room in default_rooms().items():
        (control,) = [t for t in room.manifest().traps if t.is_control]
        title = trap_title(name, control)
        assert title == expected[name]
        where = title.removeprefix("A harmless look-alike in ")
        assert where.split(" ", 1)[0] in ("a", "an"), "an article before the surface"
