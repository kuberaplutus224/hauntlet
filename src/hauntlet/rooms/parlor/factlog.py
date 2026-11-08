"""Parlor fact log: append-only JSONL of what the page handler served and received.

The page handler appends one JSON object per fact to
``<workspace>/parlor-facts.jsonl`` and fsyncs it before replying to the request
that produced it, so a separate finalize process reads complete records
(Requirement 11.4). Every record shares an envelope::

    {"t": <ts>, "run": "<run_id>", "room": "<name>", "kind": "...", ...}

with the per-kind fields:

========== ==========================================================
kind       fields
========== ==========================================================
page       ``page_id`` (str)
image      (envelope only)
submit     ``answer`` (str), ``member_code`` (str), ``to`` (str)
site_action ``trap_id`` (str), ``path`` (str)
dropped    ``count`` (int) — appended once when the per-run cap is hit
========== ==========================================================

``read`` parses with ``json.loads`` only, caps line length, and silently skips
malformed lines, unknown kinds, records with missing or wrongly typed fields,
and records naming another run. It never raises for bad content and never
executes anything. This module has no clock: ``t`` comes from the caller.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

#: File name of the fact log inside the run's workspace.
FACTS_FILENAME = "parlor-facts.jsonl"
#: Lines longer than this (bytes, excluding the newline) are skipped unread.
MAX_LINE_BYTES = 1 << 16  # 64 KiB
#: At most this many records are kept per run; further appends are dropped.
MAX_FACTS = 512
#: Every string field is truncated to this many bytes (UTF-8) before writing.
MAX_FIELD = 4096


def facts_path(workspace: str | os.PathLike[str]) -> Path:
    return Path(workspace) / FACTS_FILENAME


def _clip(value: object) -> str:
    """Coerce to str and truncate to MAX_FIELD bytes without splitting a char."""
    s = value if isinstance(value, str) else str(value)
    raw = s.encode("utf-8")[:MAX_FIELD]
    return raw.decode("utf-8", errors="ignore")


# --------------------------------------------------------------------------- #
# Fact record types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Fact:
    t: float
    run: str
    room: str


@dataclass(frozen=True)
class PageFact(Fact):
    page_id: str
    kind = "page"


@dataclass(frozen=True)
class ImageFact(Fact):
    kind = "image"


@dataclass(frozen=True)
class SubmitFact(Fact):
    answer: str
    member_code: str
    to: str
    kind = "submit"


@dataclass(frozen=True)
class SiteActionFact(Fact):
    trap_id: str
    path: str
    kind = "site_action"


@dataclass(frozen=True)
class DroppedFact(Fact):
    count: int
    kind = "dropped"


def _record(fact: Fact) -> dict:
    base = {"t": fact.t, "run": fact.run, "room": fact.room, "kind": fact.kind}
    if isinstance(fact, PageFact):
        base["page_id"] = _clip(fact.page_id)
    elif isinstance(fact, SubmitFact):
        base["answer"] = _clip(fact.answer)
        base["member_code"] = _clip(fact.member_code)
        base["to"] = _clip(fact.to)
    elif isinstance(fact, SiteActionFact):
        base["trap_id"] = _clip(fact.trap_id)
        base["path"] = _clip(fact.path)
    elif isinstance(fact, DroppedFact):
        base["count"] = int(fact.count)
    return base


def to_line(fact: Fact) -> str:
    return json.dumps(_record(fact), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def append(path: str | os.PathLike[str], fact: Fact) -> bool:
    """Append ``fact`` as one JSON line, flushed and fsynced. Returns False (and
    writes nothing but a single ``dropped`` marker) once the per-run cap is hit."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = _count_lines(p)
    if existing >= MAX_FACTS:
        if existing == MAX_FACTS:  # write the marker exactly once
            _write(p, to_line(DroppedFact(fact.t, fact.run, fact.room, count=1)))
        return False
    _write(p, to_line(fact))
    return True


def _write(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def _from_record(obj: object, run_id: str) -> Fact | None:
    if not isinstance(obj, dict):
        return None
    t, run, room, kind = obj.get("t"), obj.get("run"), obj.get("room"), obj.get("kind")
    if not isinstance(t, (int, float)) or isinstance(t, bool):
        return None
    if not isinstance(run, str) or run != run_id or not isinstance(room, str):
        return None
    try:
        if kind == "page":
            return PageFact(t, run, room, page_id=_req_str(obj, "page_id"))
        if kind == "image":
            return ImageFact(t, run, room)
        if kind == "submit":
            return SubmitFact(
                t, run, room,
                answer=_req_str(obj, "answer"),
                member_code=_req_str(obj, "member_code"),
                to=_req_str(obj, "to"),
            )
        if kind == "site_action":
            return SiteActionFact(t, run, room, trap_id=_req_str(obj, "trap_id"), path=_req_str(obj, "path"))
        if kind == "dropped":
            count = obj.get("count")
            return DroppedFact(t, run, room, count=count) if isinstance(count, int) else None
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _req_str(obj: dict, name: str) -> str:
    value = obj[name]
    if not isinstance(value, str):
        raise TypeError(name)
    return value


def read(path: str | os.PathLike[str], run_id: str) -> list[Fact]:
    """Read every well-formed fact for ``run_id``. Never raises on bad content."""
    p = Path(path)
    facts: list[Fact] = []
    try:
        with p.open("rb") as f:
            for raw in f:
                if len(raw) > MAX_LINE_BYTES + 1:
                    continue
                try:
                    obj = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                fact = _from_record(obj, run_id)
                if fact is not None:
                    facts.append(fact)
    except OSError:
        return []
    return facts
