"""Citation gate for the Cursed Repo rooms (release gate, task 13.3).

Requirements 8.2 (every "to verify" resolved before release) and 8.3 (full
citations live in the room README, keyed by trap ID).

The README is parsed by Markdown headings, never by line numbers: the
``## Citations`` section runs to the next level-2 heading, and each trap's entry
is a ``### <trap_id>`` subsection holding ``- Key: value`` lines.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from _retired import RETIRED_SOURCES

from hauntlet.core.models import TrapSpec
from hauntlet.rooms.cursed_repo.config import CURSED_REPO, CURSED_REPO_TESTS

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "src" / "hauntlet" / "rooms" / "cursed_repo" / "README.md"

ALLOWED_BENCHMARKS = ("RepoGuardBench", "CodeIPI", "CIPR")

MANIFESTS = (CURSED_REPO.manifest(), CURSED_REPO_TESTS.manifest())
NON_CONTROL: tuple[TrapSpec, ...] = tuple(
    t for m in MANIFESTS for t in m.traps if not t.is_control
)
TRAP_IDS = [t.trap_id for t in NON_CONTROL]

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FIELD = re.compile(r"^-\s+([A-Za-z][A-Za-z /]*?):\s*(.*)$")


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


def _citation_entries() -> dict[str, dict[str, str]]:
    """``trap_id -> {field name: value}`` for every ``### <trap_id>`` entry."""
    entries: dict[str, dict[str, str]] = {}
    for title, body in _headed_blocks(_citations_section(), 3):
        key = title.strip().strip("`")
        fields: dict[str, str] = {}
        for line in body:
            match = _FIELD.match(line.strip())
            if match is not None:
                fields.setdefault(match.group(1).strip(), match.group(2).strip())
        entries[key] = fields
    return entries


def _source_benchmark(spec: TrapSpec) -> str:
    """The benchmark a source names: its first comma-separated field."""
    return spec.source.split(",", 1)[0].strip()


def _benchmarks_named(text: str) -> set[str]:
    return {b for b in ALLOWED_BENCHMARKS if re.search(rf"\b{re.escape(b)}\b", text)}


# (a) manifests -------------------------------------------------------------


@pytest.mark.parametrize("manifest", MANIFESTS, ids=lambda m: m.room)
def test_no_manifest_source_is_unverified(manifest) -> None:
    for spec in manifest.traps:
        assert "to verify" not in spec.source.lower(), (
            f"{manifest.room}/{spec.trap_id}: source still marked 'to verify': {spec.source!r}"
        )


@pytest.mark.parametrize("spec", NON_CONTROL, ids=TRAP_IDS)
def test_non_control_source_names_an_allowed_benchmark(spec: TrapSpec) -> None:
    assert spec.source.strip(), f"{spec.trap_id}: source is empty"
    benchmark = _source_benchmark(spec)
    assert benchmark in ALLOWED_BENCHMARKS, (
        f"{spec.trap_id}: source {spec.source!r} names {benchmark!r}, "
        f"not one of {ALLOWED_BENCHMARKS}"
    )


# (b) README ----------------------------------------------------------------


def test_readme_has_no_to_verify() -> None:
    offenders = [
        f"line {n}: {line.strip()}"
        for n, line in enumerate(_readme_text().splitlines(), start=1)
        if "to verify" in line.lower()
    ]
    assert not offenders, f"{README.name} still contains 'to verify':\n" + "\n".join(offenders)


# (c) one citation entry per non-control trap --------------------------------


@pytest.mark.parametrize("spec", NON_CONTROL, ids=TRAP_IDS)
def test_trap_has_a_citation_entry(spec: TrapSpec) -> None:
    entries = _citation_entries()
    assert spec.trap_id in entries, (
        f"{spec.trap_id}: no '### {spec.trap_id}' entry in the README's Citations section"
    )
    fields = entries[spec.trap_id]

    benchmark_line = fields.get("Benchmark", "")
    assert benchmark_line, f"{spec.trap_id}: citation entry has no 'Benchmark:' line"
    expected = _source_benchmark(spec)
    assert _benchmarks_named(benchmark_line) == {expected}, (
        f"{spec.trap_id}: README 'Benchmark: {benchmark_line}' does not name exactly "
        f"the source's benchmark {expected!r}"
    )

    url_line = fields.get("URL", "")
    assert "https://" in url_line, (
        f"{spec.trap_id}: citation entry has no 'URL:' line with an https:// reference"
    )


# (d) excluded benchmarks ----------------------------------------------------


@pytest.mark.parametrize("name", RETIRED_SOURCES)
def test_no_citation_names_an_excluded_benchmark(name: str) -> None:
    section = "\n".join(_citations_section()).lower()
    assert name.lower() not in section, f"README Citations section names {name!r}"
    for spec in NON_CONTROL:
        assert name.lower() not in spec.source.lower(), (
            f"{spec.trap_id}: source {spec.source!r} names {name!r}"
        )
