"""The literal-credential-assignment payload-guard rule (Requirement 5.3)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_payload_safety import check_text  # noqa: E402

RULE = "literal credential assignment"


def _rule_names(text: str) -> set[str]:
    return {name for _, name, _ in check_text(text)}


@pytest.mark.parametrize(
    "text",
    [
        "password=hunter2",
        '"secret": "abc"',
        "api_key=sk-real",
        'password = "hunter2"',  # `=` with a quoted value and surrounding spaces
        'password: "x"',         # `:` with a quoted value is still a literal
    ],
)
def test_literal_credential_assignment_fires(text: str) -> None:
    assert RULE in _rule_names(text)


@pytest.mark.parametrize(
    "text",
    [
        "password={marker}",
        "token=<placeholder>",
        "secret={trap_url}",
        "access_token=abc",            # word boundary: `token` must not match inside `access_token`
        "Keep the secret: do not share",  # `:` with an unquoted prose value does not fire
    ],
)
def test_placeholder_credential_assignment_does_not_fire(text: str) -> None:
    assert RULE not in _rule_names(text)
