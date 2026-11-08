"""Unit tests for Poltergeist ``exercised.compute`` (task 5.7).

_Requirements: 4.1, 4.3_
"""

from __future__ import annotations

import random

import pytest

from hauntlet.rooms.poltergeist.config import (
    CONTROL,
    POLTERGEIST,
    POLTERGEIST_LEGACY,
    RUG_DESC,
    TOOL_OUTPUT,
)
from hauntlet.rooms.poltergeist.exercised import (
    EXERCISED,
    NO_LIST_AFTER_MUTATION,
    NOT_SUBSCRIBED,
    POISONED_TOOL_NEVER_CALLED,
    Exercised,
    compute,
)
from hauntlet.rooms.poltergeist.factlog import (
    CallFact,
    ListFact,
    MutationFact,
    NegotiatedFact,
)

RUN = "run-test"
CONFIGS = [POLTERGEIST, POLTERGEIST_LEGACY]
IDS = ["poltergeist", "poltergeist-legacy"]
DESC_TOOLS = ("get_note", "check_health")


def _room(config) -> str:
    return config.revision.name


def _neg(config, subscribed: bool, t: float = 0) -> NegotiatedFact:
    rev = (config.revision.modern_versions or config.revision.handshake_versions)[0]
    return NegotiatedFact(t, RUN, _room(config), rev, subscribed)


def _list(config, after: bool, t: float, **versions: str) -> ListFact:
    dv = versions or {tool: ("post" if after else "pre") for tool in DESC_TOOLS}
    return ListFact(t, RUN, _room(config), after, desc_versions=dv)


def _call(config, tool: str, t: float, live: str = "pre") -> CallFact:
    return CallFact(
        t, RUN, _room(config), tool, args={},
        live={"get_note": live, "check_health": live},
    )


def _mut(config, t: float) -> MutationFact:
    return MutationFact(t, RUN, _room(config), tools=list(DESC_TOOLS))


def _ok() -> Exercised:
    return Exercised(True, EXERCISED)


def _baseline(config, subscribed: bool = True) -> list:
    """Negotiate, list pre, call get_note (mutation fires)."""
    return [
        _neg(config, subscribed, 0),
        _list(config, False, 1),
        _call(config, "get_note", 2),
        _mut(config, 3),
    ]


# --------------------------------------------------------------------------- #
# the four cases of task 5.7's first bullet
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
def test_post_mutation_list_serving_post_exercises_description_traps(config):
    facts = _baseline(config) + [_list(config, True, 4)]
    out = compute(facts, config)
    assert out[RUG_DESC] == _ok()
    assert out[CONTROL] == _ok()


@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
def test_only_pre_mutation_list_is_not_exercised(config):
    out = compute(_baseline(config), config)
    assert out[RUG_DESC] == Exercised(False, NO_LIST_AFTER_MUTATION)
    assert out[CONTROL] == Exercised(False, NO_LIST_AFTER_MUTATION)


@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
def test_post_mutation_list_still_serving_pre_is_not_exercised(config):
    stale = _list(config, True, 4, get_note="pre", check_health="pre")
    out = compute(_baseline(config) + [stale], config)
    assert out[RUG_DESC] == Exercised(False, NO_LIST_AFTER_MUTATION)
    assert out[CONTROL] == Exercised(False, NO_LIST_AFTER_MUTATION)


def test_unsubscribed_never_refetched_gives_not_subscribed_on_2026_07_28():
    out = compute(_baseline(POLTERGEIST, subscribed=False), POLTERGEIST)
    assert out[RUG_DESC] == Exercised(False, NOT_SUBSCRIBED)
    assert out[CONTROL] == Exercised(False, NOT_SUBSCRIBED)


def test_subscription_reason_does_not_apply_on_legacy():
    out = compute(_baseline(POLTERGEIST_LEGACY, subscribed=False), POLTERGEIST_LEGACY)
    assert out[RUG_DESC] == Exercised(False, NO_LIST_AFTER_MUTATION)
    assert out[CONTROL] == Exercised(False, NO_LIST_AFTER_MUTATION)


def test_subscribed_but_never_refetched_gives_no_list_on_2026_07_28():
    out = compute(_baseline(POLTERGEIST, subscribed=True), POLTERGEIST)
    assert out[RUG_DESC] == Exercised(False, NO_LIST_AFTER_MUTATION)
    assert out[CONTROL] == Exercised(False, NO_LIST_AFTER_MUTATION)


def test_unsubscribed_but_refetched_post_is_exercised():
    facts = _baseline(POLTERGEIST, subscribed=False) + [_list(POLTERGEIST, True, 4)]
    out = compute(facts, POLTERGEIST)
    assert out[RUG_DESC] == _ok()
    assert out[CONTROL] == _ok()


# --------------------------------------------------------------------------- #
# no tool called / tool-output
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("subscribed", [True, False])
@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
def test_no_tool_called_no_mutation(config, subscribed):
    facts = [_neg(config, subscribed, 0), _list(config, False, 1)]
    out = compute(facts, config)
    assert out[RUG_DESC] == Exercised(False, NO_LIST_AFTER_MUTATION)
    assert out[CONTROL] == Exercised(False, NO_LIST_AFTER_MUTATION)
    assert out[TOOL_OUTPUT] == Exercised(False, POISONED_TOOL_NEVER_CALLED)


@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
def test_tool_output_exercised_only_when_list_topics_called(config):
    assert compute(_baseline(config), config)[TOOL_OUTPUT] == Exercised(
        False, POISONED_TOOL_NEVER_CALLED
    )
    facts = _baseline(config) + [_call(config, "list_topics", 4, live="post")]
    assert compute(facts, config)[TOOL_OUTPUT] == _ok()


@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
def test_save_note_alone_does_not_exercise_tool_output(config):
    facts = _baseline(config) + [_call(config, "save_note", 4, live="post")]
    assert compute(facts, config)[TOOL_OUTPUT] == Exercised(
        False, POISONED_TOOL_NEVER_CALLED
    )


# --------------------------------------------------------------------------- #
# independence of control and rug-desc
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
def test_post_for_get_note_only_exercises_rug_desc_only(config):
    lst = _list(config, True, 4, get_note="post", check_health="pre")
    out = compute(_baseline(config) + [lst], config)
    assert out[RUG_DESC] == _ok()
    assert out[CONTROL] == Exercised(False, NO_LIST_AFTER_MUTATION)


@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
def test_post_for_check_health_only_exercises_control_only(config):
    lst = _list(config, True, 4, get_note="pre", check_health="post")
    out = compute(_baseline(config) + [lst], config)
    assert out[RUG_DESC] == Exercised(False, NO_LIST_AFTER_MUTATION)
    assert out[CONTROL] == _ok()


# --------------------------------------------------------------------------- #
# empty, order independence, completeness
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
def test_empty_fact_list(config):
    assert compute([], config) == {
        RUG_DESC: Exercised(False, NO_LIST_AFTER_MUTATION),
        TOOL_OUTPUT: Exercised(False, POISONED_TOOL_NEVER_CALLED),
        CONTROL: Exercised(False, NO_LIST_AFTER_MUTATION),
    }


@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
@pytest.mark.parametrize("subscribed", [True, False])
def test_order_independence(config, subscribed):
    cases = [
        _baseline(config, subscribed),
        _baseline(config, subscribed)
        + [_list(config, True, 4, get_note="post", check_health="pre"),
           _call(config, "list_topics", 5, live="post")],
    ]
    for facts in cases:
        expected = compute(facts, config)
        assert compute(list(reversed(facts)), config) == expected
        shuffled = list(facts)
        random.Random(7).shuffle(shuffled)
        assert compute(shuffled, config) == expected


@pytest.mark.parametrize("config", CONFIGS, ids=IDS)
@pytest.mark.parametrize("with_facts", [False, True])
def test_every_config_trap_appears(config, with_facts):
    facts = _baseline(config) + [_list(config, True, 4)] if with_facts else []
    out = compute(facts, config)
    assert set(out) == {t.trap_id for t in config.traps}
    assert CONTROL in out
