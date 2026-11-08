"""Example tests for the Poltergeist task check (Requirements 1.3, 1.4)."""

from __future__ import annotations

import pytest

from hauntlet.rooms.poltergeist.taskcheck import EXPECTED, check_answer

ACCEPTED = ["Boo", "boo", "boo.", "The mascot is Boo!", "  boo  ", "boo\n"]
REJECTED = ["taboo", "boost", "booo", "b o o", "", None]


def test_expected_answer_is_boo() -> None:
    assert EXPECTED == "boo"


@pytest.mark.parametrize("answer", ACCEPTED, ids=repr)
def test_accepted_answers_complete_the_task(answer: str) -> None:
    assert check_answer(answer) is True


@pytest.mark.parametrize("answer", REJECTED, ids=repr)
def test_rejected_answers_do_not_complete_the_task(answer: str | None) -> None:
    assert check_answer(answer) is False


def test_taboo_is_rejected_regression_guard() -> None:
    """Guard against a substring check: "taboo" contains "boo" but is not the word "boo".

    A naive ``EXPECTED in answer.lower()`` would accept it; the check must match
    whole words only.
    """
    assert "boo" in "taboo"
    assert check_answer("taboo") is False


@pytest.mark.parametrize("answer", [123, b"boo", ["boo"]], ids=repr)
def test_non_str_answers_return_false_without_raising(answer: object) -> None:
    assert check_answer(answer) is False  # type: ignore[arg-type]
