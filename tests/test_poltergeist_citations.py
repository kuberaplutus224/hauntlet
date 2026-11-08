"""Citation gate for the Poltergeist rooms (release gate, task 14.3).

Requirements 11.2 (no invented technique: every trap is anchored to a published
source), 11.3 (each non-control trap's source names its benchmark; the full
citation lives in the room README) and 11.4 (every source is in safety-rules
rule 4, and nothing is left UNCONFIRMED).

Both manifests come from the registered rooms, not from a hardcoded trap list.
The README is parsed by Markdown headings, never by line numbers: the
``## Citations`` section runs to the next level-2 heading, and each trap's entry
is a ``### <trap_id>`` subsection holding ``- Key: value`` lines (possibly
nested under a sub-item, so one trap may carry several ``Benchmark:`` lines).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _retired import RETIRED_SOURCES

from hauntlet.core.models import RoomManifest, TrapSpec
from hauntlet.rooms import default_rooms

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "src" / "hauntlet" / "rooms" / "poltergeist" / "README.md"
SAFETY_RULES = ROOT / ".kiro" / "steering" / "safety-rules.md"

ROOM_NAMES = ("poltergeist", "poltergeist-legacy")
UNVERIFIED_MARKERS = ("to verify", "unconfirmed")

#: Named benchmarks a Poltergeist citation may use besides a bare arXiv ID.
NAMED_BENCHMARKS = ("MCPTox",)

_ROOMS = default_rooms()
MANIFESTS: tuple[RoomManifest, ...] = tuple(_ROOMS[name].manifest() for name in ROOM_NAMES)
NON_CONTROL: tuple[TrapSpec, ...] = tuple(
    {t.trap_id: t for m in MANIFESTS for t in m.traps if not t.is_control}.values()
)
TRAP_IDS = [t.trap_id for t in NON_CONTROL]

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FIELD = re.compile(r"^-\s+([A-Za-z][A-Za-z /]*?):\s*(.*)$")
_ARXIV_ID = re.compile(r"(?:arXiv\s+|arxiv\.org/(?:abs|html|pdf)/)(\d{4}\.\d{4,5})", re.IGNORECASE)


def _headed_blocks(lines: list[str], level: int) -> list[tuple[str, list[str]]]:
    """Split ``lines`` into (heading text, body lines) at headings of ``level``.

    A heading of a higher level (fewer ``#``) ends the current block. Lines
    inside fenced code blocks are never treated as headings.
    """
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
    return README.read_text(encoding="utf-8")


def _citations_section() -> list[str]:
    sections = [body for title, body in _headed_blocks(_readme_text().splitlines(), 2)
                if title.strip().lower() == "citations"]
    assert len(sections) == 1, f"{README.name}: expected exactly one '## Citations' section"
    return sections[0]


def _citation_entries() -> dict[str, dict[str, list[str]]]:
    """``trap_id -> {field name: [values]}`` for every ``### <trap_id>`` entry."""
    entries: dict[str, dict[str, list[str]]] = {}
    for title, body in _headed_blocks(_citations_section(), 3):
        key = title.strip().strip("`")
        fields: dict[str, list[str]] = {}
        for line in body:
            match = _FIELD.match(line.strip())
            if match is not None:
                fields.setdefault(match.group(1).strip(), []).append(match.group(2).strip())
        entries[key] = fields
    return entries


def _arxiv_ids(text: str) -> set[str]:
    return set(_ARXIV_ID.findall(text))


def _rule4_text() -> str:
    text = SAFETY_RULES.read_text(encoding="utf-8")
    match = re.search(r"^4\.\s.*?(?=^\d+\.\s|^#)", text, re.MULTILINE | re.DOTALL)
    assert match is not None, f"{SAFETY_RULES.name}: rule 4 not found"
    return match.group(0)


# (a) manifests -------------------------------------------------------------


def test_both_rooms_are_registered() -> None:
    assert set(ROOM_NAMES) <= set(_ROOMS)
    assert NON_CONTROL, "no non-control traps in the Poltergeist manifests"


@pytest.mark.parametrize("manifest", MANIFESTS, ids=lambda m: m.room)
def test_no_manifest_source_is_unverified(manifest: RoomManifest) -> None:
    for spec in manifest.traps:
        for marker in UNVERIFIED_MARKERS:
            assert marker not in spec.source.lower(), (
                f"{manifest.room}/{spec.trap_id}: source still marked {marker!r}: {spec.source!r}"
            )


@pytest.mark.parametrize("spec", NON_CONTROL, ids=TRAP_IDS)
def test_non_control_source_names_a_published_source(spec: TrapSpec) -> None:
    assert spec.source.strip(), f"{spec.trap_id}: source is empty"
    assert _arxiv_ids(spec.source), f"{spec.trap_id}: source {spec.source!r} names no arXiv ID"


# (b) README ----------------------------------------------------------------


@pytest.mark.parametrize("marker", UNVERIFIED_MARKERS)
def test_readme_has_no_unverified_marker(marker: str) -> None:
    offenders = [
        f"line {n}: {line.strip()}"
        for n, line in enumerate(_readme_text().splitlines(), start=1)
        if marker in line.lower()
    ]
    assert not offenders, f"{README.name} still contains {marker!r}:\n" + "\n".join(offenders)


# (c) one citation entry per non-control trap --------------------------------


@pytest.mark.parametrize("spec", NON_CONTROL, ids=TRAP_IDS)
def test_trap_has_a_citation_entry(spec: TrapSpec) -> None:
    entries = _citation_entries()
    assert spec.trap_id in entries, (
        f"{spec.trap_id}: no '### {spec.trap_id}' entry in the README's Citations section"
    )
    fields = entries[spec.trap_id]

    benchmarks = fields.get("Benchmark", [])
    assert benchmarks, f"{spec.trap_id}: citation entry has no 'Benchmark:' line"
    for line in benchmarks:
        assert _arxiv_ids(line) or any(b in line for b in NAMED_BENCHMARKS), (
            f"{spec.trap_id}: 'Benchmark: {line}' names no benchmark or arXiv ID"
        )

    urls = fields.get("URL", [])
    assert urls and all("https://" in u for u in urls), (
        f"{spec.trap_id}: every citation needs a 'URL:' line with an https:// reference"
    )

    cited = _arxiv_ids(" ".join(benchmarks))
    referenced = _arxiv_ids(" ".join(urls))
    assert cited == referenced, (
        f"{spec.trap_id}: Benchmark arXiv IDs {sorted(cited)} do not match URL references "
        f"{sorted(referenced)}"
    )
    assert _arxiv_ids(spec.source) == cited, (
        f"{spec.trap_id}: source names {sorted(_arxiv_ids(spec.source))} but the README "
        f"cites {sorted(cited)}"
    )


# (d) safety-rules rule 4 ----------------------------------------------------


def test_every_readme_arxiv_id_is_in_rule_4() -> None:
    cited = _arxiv_ids(_readme_text())
    assert cited, f"{README.name} cites no arXiv ID"
    missing = sorted(cited - _arxiv_ids(_rule4_text()))
    assert not missing, f"arXiv IDs cited in {README.name} but absent from safety-rules rule 4: {missing}"


# (e) retired sources --------------------------------------------------------


@pytest.mark.parametrize("name", RETIRED_SOURCES)
def test_no_citation_names_a_retired_source(name: str) -> None:
    section = "\n".join(_citations_section()).lower()
    assert name.lower() not in section, f"README Citations section names {name!r}"
    for spec in NON_CONTROL:
        assert name.lower() not in spec.source.lower(), (
            f"{spec.trap_id}: source {spec.source!r} names {name!r}"
        )
