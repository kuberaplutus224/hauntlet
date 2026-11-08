"""Citation gate for the Parlor room (requirements 12.1-12.4).

Two parts:

* Rule 4 (active now). Every source the Parlor spec relies on is listed in rule 4
  of ``.kiro/steering/safety-rules.md``: injkt plus the four arXiv sources the
  maintainer confirmed on 2026-11-08 (WASP, EIA, VPI-Bench, pop-up attacks).
* Room and README (active once ``parlor`` is registered). The manifest and the
  room README cite only those sources, nothing is left unverified, and every
  cited arXiv ID is in rule 4. These tests skip while the room does not exist,
  and switch on by themselves when ``rooms/__init__.py`` registers it.

The README is parsed by Markdown headings, never by line numbers, the same way
as the Cursed Repo and Poltergeist gates.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _retired import RETIRED_SOURCES

from hauntlet.core.models import TrapSpec
from hauntlet.rooms import default_rooms

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "src" / "hauntlet" / "rooms" / "parlor" / "README.md"
SAFETY_RULES = ROOT / ".kiro" / "steering" / "safety-rules.md"

ROOM_NAME = "parlor"
UNVERIFIED_MARKERS = ("to verify", "unconfirmed")

#: arXiv sources confirmed for Parlor on 2026-11-08.
PARLOR_ARXIV_IDS = {
    "2504.18575": "WASP",
    "2409.11295": "EIA",
    "2506.02456": "VPI-Bench",
    "2411.02391": "pop-up attacks",
}
#: Named sources without an arXiv ID.
PARLOR_NAMED = ("injkt",)

_ROOMS = default_rooms()
REGISTERED = ROOM_NAME in _ROOMS
NON_CONTROL: tuple[TrapSpec, ...] = (
    tuple(t for t in _ROOMS[ROOM_NAME].manifest().traps if not t.is_control) if REGISTERED else ()
)
TRAP_IDS = [t.trap_id for t in NON_CONTROL]

needs_room = pytest.mark.skipif(not REGISTERED, reason="parlor room not registered yet")

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FIELD = re.compile(r"^-\s+([A-Za-z][A-Za-z /]*?):\s*(.*)$")
_ARXIV_ID = re.compile(r"(?:arXiv\s+|arxiv\.org/(?:abs|html|pdf)/)(\d{4}\.\d{4,5})", re.IGNORECASE)


def _arxiv_ids(text: str) -> set[str]:
    return set(_ARXIV_ID.findall(text))


def _rule4_text() -> str:
    text = SAFETY_RULES.read_text(encoding="utf-8")
    match = re.search(r"^4\.\s.*?(?=^\d+\.\s|^#)", text, re.MULTILINE | re.DOTALL)
    assert match is not None, f"{SAFETY_RULES.name}: rule 4 not found"
    return match.group(0)


def _headed_blocks(lines: list[str], level: int) -> list[tuple[str, list[str]]]:
    """Split ``lines`` into (heading text, body lines) at headings of ``level``."""
    blocks: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match is not None and len(match.group(1)) <= level:
            if current is not None:
                blocks.append(current)
            current = (match.group(2), []) if len(match.group(1)) == level else None
            continue
        if current is not None:
            current[1].append(line)
    if current is not None:
        blocks.append(current)
    return blocks


def _readme_text() -> str:
    assert README.is_file(), f"{README} is missing; the registered parlor room needs its README"
    return README.read_text(encoding="utf-8")


def _citation_entries() -> dict[str, dict[str, list[str]]]:
    sections = [body for title, body in _headed_blocks(_readme_text().splitlines(), 2)
                if title.strip().lower() == "citations"]
    assert len(sections) == 1, f"{README.name}: expected exactly one '## Citations' section"
    entries: dict[str, dict[str, list[str]]] = {}
    for title, body in _headed_blocks(sections[0], 3):
        fields: dict[str, list[str]] = {}
        for line in body:
            match = _FIELD.match(line.strip())
            if match is not None:
                fields.setdefault(match.group(1).strip(), []).append(match.group(2).strip())
        entries[title.strip().strip("`")] = fields
    return entries


def _names_allowed_source(text: str) -> bool:
    return bool(_arxiv_ids(text) & PARLOR_ARXIV_IDS.keys()) or any(
        n.lower() in text.lower() for n in PARLOR_NAMED
    )


# (a) rule 4: active now ----------------------------------------------------


@pytest.mark.parametrize("arxiv_id", sorted(PARLOR_ARXIV_IDS), ids=lambda i: PARLOR_ARXIV_IDS[i])
def test_parlor_arxiv_source_is_in_rule_4(arxiv_id: str) -> None:
    assert arxiv_id in _arxiv_ids(_rule4_text()), (
        f"arXiv {arxiv_id} ({PARLOR_ARXIV_IDS[arxiv_id]}) is not listed in safety-rules rule 4"
    )


@pytest.mark.parametrize("name", PARLOR_NAMED)
def test_parlor_named_source_is_in_rule_4(name: str) -> None:
    assert name in _rule4_text(), f"{name} is not listed in safety-rules rule 4"


# (b) manifest: once registered ---------------------------------------------


@needs_room
def test_no_manifest_source_is_unverified() -> None:
    for spec in _ROOMS[ROOM_NAME].manifest().traps:
        for marker in UNVERIFIED_MARKERS:
            assert marker not in spec.source.lower(), f"{spec.trap_id}: source marked {marker!r}"


@needs_room
@pytest.mark.parametrize("spec", NON_CONTROL, ids=TRAP_IDS)
def test_source_names_a_confirmed_parlor_source(spec: TrapSpec) -> None:
    assert _names_allowed_source(spec.source), (
        f"{spec.trap_id}: source {spec.source!r} names none of injkt or arXiv "
        f"{', '.join(sorted(PARLOR_ARXIV_IDS))}"
    )
    stray = sorted(_arxiv_ids(spec.source) - PARLOR_ARXIV_IDS.keys())
    assert not stray, f"{spec.trap_id}: source cites arXiv IDs not confirmed for Parlor: {stray}"


# (c) README: once registered -----------------------------------------------


@needs_room
@pytest.mark.parametrize("marker", UNVERIFIED_MARKERS)
def test_readme_has_no_unverified_marker(marker: str) -> None:
    offenders = [n for n, line in enumerate(_readme_text().splitlines(), 1) if marker in line.lower()]
    assert not offenders, f"{README.name} contains {marker!r} on lines {offenders}"


@needs_room
@pytest.mark.parametrize("spec", NON_CONTROL, ids=TRAP_IDS)
def test_trap_has_a_citation_entry(spec: TrapSpec) -> None:
    entries = _citation_entries()
    assert spec.trap_id in entries, f"{spec.trap_id}: no '### {spec.trap_id}' citation entry"
    fields = entries[spec.trap_id]
    benchmarks = fields.get("Benchmark", [])
    assert benchmarks and all(_names_allowed_source(b) for b in benchmarks), (
        f"{spec.trap_id}: every 'Benchmark:' line must name injkt or a confirmed arXiv source"
    )
    urls = fields.get("URL", [])
    assert urls and all("https://" in u for u in urls), f"{spec.trap_id}: needs 'URL:' lines with https://"
    assert _arxiv_ids(" ".join(benchmarks)) == _arxiv_ids(" ".join(urls)), (
        f"{spec.trap_id}: Benchmark arXiv IDs do not match URL references"
    )
    assert _arxiv_ids(spec.source) == _arxiv_ids(" ".join(benchmarks)), (
        f"{spec.trap_id}: manifest source and README citation name different arXiv IDs"
    )


@needs_room
def test_every_readme_arxiv_id_is_in_rule_4() -> None:
    missing = sorted(_arxiv_ids(_readme_text()) - _arxiv_ids(_rule4_text()))
    assert not missing, f"arXiv IDs cited in {README.name} but absent from rule 4: {missing}"


@needs_room
@pytest.mark.parametrize("name", RETIRED_SOURCES)
def test_no_citation_names_a_retired_source(name: str) -> None:
    assert name.lower() not in _readme_text().lower(), f"{README.name} names retired source {name!r}"
    for spec in NON_CONTROL:
        assert name.lower() not in spec.source.lower(), f"{spec.trap_id}: source names {name!r}"
