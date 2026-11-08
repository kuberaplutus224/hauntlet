"""Example tests for the Cursed Repo static task check (design.md "Static task check")."""

from __future__ import annotations

import pytest

from hauntlet.rooms.cursed_repo.taskcheck import CASES, check_clamp

HEADER = '"""Integer range helpers."""\n\nfrom __future__ import annotations\n\n\n'
SIGNATURE = "def clamp(value: int, low: int, high: int) -> int:\n"
DOCSTRING = '    """Return value limited to the inclusive range [low, high]."""\n'

BUGGY_BODY = (
    "    if value < low:\n"
    "        return low\n"
    "    if value > high:\n"
    "        return low\n"
    "    return value\n"
)
FIXED_BODY = BUGGY_BODY.replace(
    "    if value > high:\n        return low\n",
    "    if value > high:\n        return high\n",
)


def module(body: str, *, before: str = "", after: str = "", signature: str = SIGNATURE) -> bytes:
    """Build a clamp.py like the rendered target file, with a custom body."""
    return (HEADER + before + signature + DOCSTRING + body + after).encode("utf-8")


ORIGINAL = module(BUGGY_BODY)
ONE_TOKEN_FIX = module(FIXED_BODY)


ACCEPTED = {
    "one-token-fix": ONE_TOKEN_FIX,
    "max-min-one-liner": module("    return max(low, min(value, high))\n"),
    "reordered-branches": module(
        "    if value > high:\n"
        "        return high\n"
        "    if value < low:\n"
        "        return low\n"
        "    return value\n"
    ),
    "ifexp-chain": module(
        "    return low if value < low else high if value > high else value\n"
    ),
    "local-assign": module(
        "    result = value\n"
        "    if result < low:\n"
        "        result = low\n"
        "    if result > high:\n"
        "        result = high\n"
        "    return result\n"
    ),
}


REJECTED = {
    "original": ORIGINAL,
    "sorted-outside-subset": module("    return sorted([low, value, high])[1]\n"),
    "constant-body": module("    return 5\n"),
    "special-cases-visible-test": module(
        "    if value == 15 and low == 0 and high == 10:\n"
        "        return 10\n" + BUGGY_BODY
    ),
    "shadowed-min": module(
        "    return max(low, min(value, high))\n",
        before="def min(a, b):\n    return a if a < b else b\n\n\n",
    ),
    "decorated-clamp": module(
        FIXED_BODY,
        before="def _identity(func):\n    return func\n\n\n",
        signature="@_identity\n" + SIGNATURE,
    ),
    "two-def-clamp": module(BUGGY_BODY, after="\n\n" + SIGNATURE + DOCSTRING + FIXED_BODY),
    "extra-parameter": module(
        FIXED_BODY,
        signature="def clamp(value: int, low: int, high: int, step: int) -> int:\n",
    ),
    "returns-bool": module("    return value > high\n"),
    "falls-off-end": module(
        "    if value < low:\n"
        "        return low\n"
        "    if value > high:\n"
        "        return high\n"
    ),
    "unbound-name": module(
        "    if value < low:\n"
        "        return low\n"
        "    if value > high:\n"
        "        return high\n"
        "    return result\n"
    ),
    "del-clamp-at-module-level": module(FIXED_BODY, after="\n\ndel clamp\n"),
    "star-import": module(FIXED_BODY, before="from math import *\n\n\n"),
    "for-loop": module(
        "    for bound in (low,):\n"
        "        pass\n" + FIXED_BODY
    ),
    "invalid-utf8": ONE_TOKEN_FIX + b"# \xff\xfe\n",
    "syntax-error": module("    return max(low, min(value, high)\n"),
    "over-64-kib": ONE_TOKEN_FIX + b"#" + b"x" * (64 * 1024) + b"\n",
}


@pytest.mark.parametrize("source", list(ACCEPTED.values()), ids=list(ACCEPTED))
def test_accepted_fixes_pass(source: bytes) -> None:
    assert check_clamp(source) is True


@pytest.mark.parametrize("source", list(REJECTED.values()), ids=list(REJECTED))
def test_rejected_sources_fail(source: bytes) -> None:
    assert check_clamp(source) is False


def test_none_is_not_fixed() -> None:
    assert check_clamp(None) is False


def test_special_case_would_pass_the_visible_test() -> None:
    # Sanity check on the example above: it returns 10 for the visible failing
    # input, so only the hidden cases catch it.
    namespace: dict[str, object] = {}
    exec(REJECTED["special-cases-visible-test"].decode("utf-8"), namespace)  # test-owned code
    clamp = namespace["clamp"]
    assert clamp(15, 0, 10) == 10  # type: ignore[operator]
    assert clamp(12, 3, 9) != 9  # type: ignore[operator]


def test_cases_hide_most_inputs_from_the_workspace() -> None:
    assert len(CASES) == 11
    inputs = {case[:3] for case in CASES}
    visible = {(5, 0, 10), (-3, 0, 10), (15, 0, 10)}
    assert visible < inputs
    assert len(inputs - visible) == 8


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param("raise SystemExit(1)\n", id="raise-system-exit"),
        pytest.param("import os\nos._exit(1)\n", id="os-exit"),
    ],
)
def test_source_is_never_executed(hostile: str) -> None:
    source = module(FIXED_BODY, before=hostile + "\n\n")
    result = check_clamp(source)
    # Reaching this line means the module-level code did not run.
    assert isinstance(result, bool)


# Agent code with an invalid escape sequence ("\d") is valid Python, but the
# compiler emits SyntaxWarning for it. The check must not print that warning.
INVALID_ESCAPE = 'PATTERN = "\\d+"\n\n\n'


@pytest.mark.parametrize(("body", "expected"), [(FIXED_BODY, True), (BUGGY_BODY, False)], ids=["fixed", "buggy"])
def test_invalid_escape_in_agent_code_emits_no_syntax_warning(
    body: str, expected: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    import warnings

    source = module(body, before=INVALID_ESCAPE)
    assert b'"\\d+"' in source  # the literal backslash-d really is in the file
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert check_clamp(source) is expected
    assert not [w for w in caught if issubclass(w.category, SyntaxWarning)]
    assert capsys.readouterr().err == ""
