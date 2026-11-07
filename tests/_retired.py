"""Benchmark names retired as trap sources (task 14 of the cursed-repo spec).

Defined once here and imported by ``test_retired_sources.py`` (repo-wide scan)
and ``test_cursed_repo_citations.py`` (citation gate). This file is the only
tracked file, besides the append-only ``docs/kiro-usage-log.md``, allowed to
contain them.
"""

from __future__ import annotations

RETIRED_SOURCES: tuple[str, ...] = ("Meta SWE-PI", "SWE-PI", "Meta SWE-bench", "Prompt Siren")
