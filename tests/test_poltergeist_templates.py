"""PP7 Safety at rest for the Poltergeist rooms' templates.

Every template passes the payload guard, carries no literal URL, host, IP,
credential or dummy secret, takes exactly the placeholders the server fills, and
the two trap texts (and only those) match the hardened agent's flag pattern.

**Validates: Requirements 7.3, 7.5**
"""
from __future__ import annotations

import re
import string
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hauntlet.agents.hardened import _DIRECTED
from hauntlet.core.canary import DUMMY_PREFIX, DUMMY_SECRET_RE, MARKER_PREFIX, dummy_secret
from hauntlet.core.room import render_template
from hauntlet.rooms.poltergeist import server
from hauntlet.rooms.poltergeist.config import (
    LIST_TOPICS_OUTPUT_TMPL,
    NOTE_TMPL,
    NOTE_TOPICS,
    TOOLS,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_payload_safety import check_file, check_text  # noqa: E402

TEMPLATES = ROOT / "src" / "hauntlet" / "rooms" / "poltergeist" / "templates"
ALL_FILES = sorted(p for p in TEMPLATES.rglob("*") if p.is_file())

NOTE_TEMPLATES = tuple(NOTE_TMPL.format(topic=t) for t in NOTE_TOPICS)

#: Exact placeholder set per template, as the server fills them.
EXPECTED_FIELDS: dict[str, set[str]] = {
    **{t.desc_tmpl: set() for t in TOOLS},
    **{t.desc_post_tmpl: set() for t in TOOLS if t.desc_post_tmpl},
    LIST_TOPICS_OUTPUT_TMPL: {"marker"},
    **{rel: {"secret"} for rel in NOTE_TEMPLATES},
}

#: Payload-guard rules that cover "no literal URL, host or IP".
_ADDRESS_RULES = {"literal URL", "literal host", "literal IP address"}
#: Bare hostnames the guard's `www.` rule would miss.
_BARE_HOST = re.compile(r"\blocalhost\b|\b[a-z0-9-]+\.(?:com|net|org|io|dev|app|local)\b", re.I)

_TOOL = {t.name: t for t in TOOLS}


def _rel(path: Path) -> str:
    return path.relative_to(TEMPLATES).as_posix()


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def _flat(text: str) -> str:
    """Collapse whitespace the way the hardened agent does before matching."""
    return " ".join(text.split())


def _render(rel: str, **fields: str) -> str:
    return render_template(TEMPLATES / rel, **fields)


def _marker() -> str:
    return f"{MARKER_PREFIX}-0123456789"


def _secret() -> str:
    return dummy_secret("run-abc123", "rug-desc")


# --- payload guard ---------------------------------------------------------


def test_template_tree_is_populated() -> None:
    # Guards every other test here against passing vacuously on a wrong path.
    assert server.TEMPLATES.resolve() == TEMPLATES.resolve()
    assert len(ALL_FILES) == len(EXPECTED_FIELDS) == 12


@pytest.mark.parametrize("path", ALL_FILES, ids=_rel)
def test_payload_guard_reports_nothing(path: Path) -> None:
    assert check_file(path) == []


def test_payload_guard_script_passes_on_templates_dir() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_payload_safety.py", str(TEMPLATES)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# --- literal content and placeholders --------------------------------------


@pytest.mark.parametrize("path", ALL_FILES, ids=_rel)
def test_no_literal_address_credential_or_dummy(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert _BARE_HOST.search(text) is None
    assert DUMMY_PREFIX not in text
    assert DUMMY_SECRET_RE.search(text) is None


@pytest.mark.parametrize("path", ALL_FILES, ids=_rel)
def test_exact_placeholder_set(path: Path) -> None:
    assert _fields(path.read_text(encoding="utf-8")) == EXPECTED_FIELDS[_rel(path)]


def test_referenced_templates_match_files_on_disk() -> None:
    on_disk = {_rel(p) for p in ALL_FILES}
    assert set(EXPECTED_FIELDS) == on_disk


# --- rendering with real-shaped values (property) --------------------------

_hex = st.text(alphabet="0123456789abcdef", min_size=10, max_size=10)
_ident = st.text(alphabet=string.ascii_letters + string.digits + "-_", min_size=1, max_size=30)


@settings(max_examples=100)
@given(marker_hex=_hex, run_id=_ident, trap_id=_ident)
def test_rendering_introduces_no_address_and_fills_every_placeholder(
    marker_hex: str, run_id: str, trap_id: str
) -> None:
    """**Validates: Requirements 7.3, 7.5**"""
    values = {"marker": f"{MARKER_PREFIX}-{marker_hex}", "secret": dummy_secret(run_id, trap_id)}
    assert DUMMY_SECRET_RE.fullmatch(values["secret"])
    for rel, needed in EXPECTED_FIELDS.items():
        text = _render(rel, **{k: values[k] for k in needed})
        assert not {name for _, name, _ in check_text(text)} & _ADDRESS_RULES, rel
        assert _BARE_HOST.search(text) is None, rel
        assert _fields(text) == set(), rel
        for k in needed:
            assert values[k] in text, rel


# --- hardened agent's flag pattern -----------------------------------------


def test_post_mutation_get_note_description_matches_hardened_pattern() -> None:
    assert _DIRECTED.search(_flat(_render(_TOOL["get_note"].desc_post_tmpl))) is not None


def test_list_topics_output_matches_hardened_pattern() -> None:
    assert _DIRECTED.search(_flat(_render(LIST_TOPICS_OUTPUT_TMPL, marker=_marker()))) is not None


def test_control_descriptions_do_not_match_hardened_pattern() -> None:
    control = _TOOL["check_health"]
    for rel in (control.desc_tmpl, control.desc_post_tmpl):
        assert _DIRECTED.search(_flat(_render(rel))) is None, rel


_BENIGN = sorted({t.desc_tmpl for t in TOOLS} - {_TOOL["check_health"].desc_tmpl}) + list(
    NOTE_TEMPLATES
)


@pytest.mark.parametrize("rel", _BENIGN)
def test_benign_template_does_not_match_hardened_pattern(rel: str) -> None:
    fields = {"secret": _secret()} if rel in NOTE_TEMPLATES else {}
    assert _DIRECTED.search(_flat(_render(rel, **fields))) is None


def test_benign_topic_list_part_does_not_match_hardened_pattern() -> None:
    text = _render(LIST_TOPICS_OUTPUT_TMPL, marker=_marker())
    benign = "\n".join(line for line in text.splitlines() if not line.startswith("SYSTEM"))
    assert all(f"- {t}" in benign for t in NOTE_TOPICS)
    assert _DIRECTED.search(_flat(benign)) is None
