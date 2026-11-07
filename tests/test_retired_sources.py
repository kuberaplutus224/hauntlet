"""Repo-wide guard: retired benchmark names never come back (cursed-repo task 14).

Requirements 8.1 and 8.3: every trap source is a benchmark that was checked.
The retired names live only in ``tests/_retired.py``. Every other text file the
repository would commit is scanned, case-insensitively.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from _retired import RETIRED_SOURCES

ROOT = Path(__file__).resolve().parent.parent

#: Repo-relative POSIX paths that may contain retired names.
ALLOWED = frozenset({
    "tests/_retired.py",  # the single definition
    "tests/test_retired_sources.py",  # this file
    "docs/kiro-usage-log.md",  # append-only history written by a hook
})

#: Directories skipped by the fallback walk when git is unavailable.
SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".hypothesis",
    ".hauntlet", ".mypy_cache", ".ruff_cache", "reports", "dist", "build",
    "node_modules",
})


def _git_files() -> list[str] | None:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT, capture_output=True, check=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return sorted({p for p in out.decode("utf-8", errors="surrogateescape").split("\0") if p})


def _walked_files() -> list[str]:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for name in filenames:
            files.append(Path(dirpath, name).relative_to(ROOT).as_posix())
    return sorted(files)


def repo_files() -> list[str]:
    """Repo-relative paths of every file the repository would commit."""
    files = _git_files()
    return _walked_files() if files is None else files


def scan(needles: tuple[str, ...], allowed: frozenset[str] = ALLOWED) -> list[str]:
    """``path:line: text`` for every line of a UTF-8 file containing a needle."""
    lowered = tuple(n.lower() for n in needles)
    hits: list[str] = []
    for rel in repo_files():
        if rel in allowed:
            continue
        path = ROOT / rel
        if not path.is_file() or path.is_symlink():  # tracked but deleted, or a link
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            if any(needle in line.lower() for needle in lowered):
                hits.append(f"{rel}:{n}: {line.strip()[:160]}")
    return hits


def test_no_retired_source_name_in_repo() -> None:
    hits = scan(RETIRED_SOURCES)
    assert not hits, "retired benchmark names found:\n" + "\n".join(hits)


def test_scanner_reads_files() -> None:
    """A broken file listing must not pass the guard vacuously."""
    hits = scan(("a haunted house for ai agents",))
    assert any(h.startswith("README.md:") for h in hits), hits
