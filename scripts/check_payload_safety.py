#!/usr/bin/env python3
"""Mechanical enforcement of .kiro/steering/safety-rules.md for trap content.

Rejects, in any trap template or fixture:
  * destructive commands (rm -rf, mkfs, dd of=, curl | sh, fork bombs, ...)
  * anything shaped like a real credential (cloud keys, tokens, private keys)
  * literal URLs or hostnames: the only reachable host is the run's own canary
    endpoint, which templates must reference through a {placeholder}

Usage:
  check_payload_safety.py PATH [PATH ...]   check files or directories
  check_payload_safety.py --stdin           read a Kiro hook event (JSON) on STDIN
  check_payload_safety.py                   check every room template and fixture

Exit code 0 when clean, 1 with a report on stderr when anything is found.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GLOBS = ("src/hauntlet/rooms/*/templates/**/*", "src/hauntlet/rooms/*/fixtures/**/*")

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("destructive command", re.compile(r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", re.I)),
    ("destructive command", re.compile(r"\bmkfs(\.\w+)?\b|\bdd\s+[^\n]*\bof=|\bshred\b|>\s*/dev/sd", re.I)),
    ("destructive command", re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:")),
    ("remote code execution", re.compile(r"\b(curl|wget)\b[^\n|]*\|\s*(ba|z)?sh\b", re.I)),
    ("privilege change", re.compile(r"\bchmod\s+(-R\s+)?777\s+/|\bsudo\b", re.I)),
    ("git history rewrite", re.compile(r"\bgit\s+push\s+[^\n]*--force|\bgit\s+reset\s+--hard", re.I)),
    ("realistic credential", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("realistic credential", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("realistic credential", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("realistic credential", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b")),
    ("realistic credential", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("literal URL", re.compile(r"\b(?:https?|ftp|wss?)://", re.I)),
    ("literal host", re.compile(r"\bwww\.[a-z0-9-]+\.[a-z]{2,}\b", re.I)),
    ("literal IP address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def check_text(text: str) -> list[tuple[int, str, str]]:
    found = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, rx in RULES:
            m = rx.search(line)
            if m:
                found.append((lineno, name, m.group(0)))
    return found


def check_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    return [f"{path}:{ln}: {name}: {snippet!r}" for ln, name, snippet in check_text(text)]


def _expand(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out += [f for f in sorted(p.rglob("*")) if f.is_file()]
        elif p.is_file():
            out.append(p)
    return out


def _paths_from_hook_event(raw: str) -> list[Path]:
    """Pull file paths out of a Kiro hook event, whatever its exact shape."""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return [Path(raw.strip())] if raw.strip() else []
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and ("path" in k.lower() or "file" in k.lower()):
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return [Path(p) if Path(p).is_absolute() else ROOT / p for p in found]


def main(argv: list[str]) -> int:
    if argv[:1] == ["--stdin"]:
        paths = _paths_from_hook_event(sys.stdin.read())
    elif argv:
        paths = [Path(a) for a in argv]
    else:
        paths = [p for g in DEFAULT_GLOBS for p in ROOT.glob(g)]
    problems = [msg for f in _expand(paths) for msg in check_file(f)]
    if problems:
        print("payload-guard: unsafe trap content (see .kiro/steering/safety-rules.md)", file=sys.stderr)
        for msg in problems:
            print("  " + msg, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
