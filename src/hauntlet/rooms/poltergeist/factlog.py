"""Poltergeist fact log: append-only JSONL of server-observed facts.

The MCP server appends one JSON object per fact to
``<scratch>/poltergeist-facts.jsonl`` and fsyncs it before replying to the
request that produced it, so a separate finalize process reads complete records
(Requirement 8.5). Every record shares an envelope::

    {"t": <ts>, "run": "<run_id>", "room": "<name>", "kind": "...", ...}

with the per-kind fields from design.md "Fact log":

========== ==========================================================
kind       fields
========== ==========================================================
negotiated ``revision`` (str), ``subscribed`` (bool)
list       ``after_mutation`` (bool), ``desc_versions`` {tool: pre|post}
call       ``tool`` (str), ``args`` (object), ``live`` {get_note, check_health}
mutation   ``tools`` (list of str)
answer     ``text`` (str)
relay      ``trap_id`` (str), ``had_secret`` (bool)
scratch    ``trap_id`` (str), ``path`` (str)
========== ==========================================================

Facts are frozen, hashable dataclasses so they compare with ``==`` and can be
put in sets. Mapping fields are stored in canonical immutable form:

* ``desc_versions`` and ``live``: tuples of ``(tool, version)`` pairs sorted by
  tool (use ``.version(tool)`` / ``.live_version(tool)`` to look one up).
* ``args``: canonical JSON text of the arguments object (nested values stay
  exact and hashable); ``.arguments()`` returns a fresh ``dict``.

The fact log lives in scratch, which a client with filesystem access could edit
(design "Known limitations"). ``read`` therefore parses with ``json.loads`` only,
caps line length, and silently skips malformed lines, unknown kinds, records
with missing or wrongly typed fields, and records naming another run. It never
raises for bad content. Path containment of ``ScratchFact.path`` is checked by
``collect``, not here. This module has no clock: ``t`` comes from the caller.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

#: File name of the fact log inside the run's scratch workspace.
FACTS_FILENAME = "poltergeist-facts.jsonl"

#: Lines longer than this (bytes, excluding the newline) are skipped unread.
MAX_LINE_BYTES = 1 << 20  # 1 MiB

#: Description versions a changed tool can carry.
VERSIONS: frozenset[str] = frozenset({"pre", "post"})

#: Tools whose live description versions every ``call`` fact records.
LIVE_TOOLS: tuple[str, ...] = ("check_health", "get_note")  # sorted

#: All record kinds.
KINDS: frozenset[str] = frozenset(
    {"negotiated", "list", "call", "mutation", "answer", "relay", "scratch"}
)

_ENVELOPE = ("t", "run", "room", "kind")


# --------------------------------------------------------------------------- #
# validation helpers (raise ValueError; callers turn that into "skip")
# --------------------------------------------------------------------------- #


def _req_str(name: str, value: object, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ValueError(f"{name} must be a{' non-empty' if nonempty else ''} string")
    return value


def _req_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a bool")
    return value


def _req_ts(value: object) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("t must be a number")
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("t must be finite")
    return value


def _versions(name: str, value: object) -> tuple[tuple[str, str], ...]:
    """Normalize a {tool: pre|post} mapping (or pair sequence) to sorted pairs."""
    if isinstance(value, Mapping):
        items = list(value.items())
    elif isinstance(value, tuple):
        items = list(value)
        if not all(isinstance(p, tuple) and len(p) == 2 for p in items):
            raise ValueError(f"{name} must be pairs")
        if len({k for k, _ in items}) != len(items):
            raise ValueError(f"{name} has duplicate tools")
    else:
        raise ValueError(f"{name} must be a mapping")
    out = []
    for tool, ver in items:
        _req_str(f"{name} key", tool)
        if ver not in VERSIONS:
            raise ValueError(f"{name}[{tool}] must be 'pre' or 'post'")
        out.append((tool, ver))
    return tuple(sorted(out))


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def _set(obj: object, name: str, value: object) -> None:
    object.__setattr__(obj, name, value)


# --------------------------------------------------------------------------- #
# Fact record types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Envelope:
    t: float | int
    run: str
    room: str

    def _check_envelope(self) -> None:
        _req_ts(self.t)
        _req_str("run", self.run)
        _req_str("room", self.room)


@dataclass(frozen=True)
class NegotiatedFact(_Envelope):
    revision: str
    subscribed: bool
    kind = "negotiated"

    def __post_init__(self) -> None:
        self._check_envelope()
        _req_str("revision", self.revision)
        _req_bool("subscribed", self.subscribed)

    def _fields(self) -> dict[str, Any]:
        return {"revision": self.revision, "subscribed": self.subscribed}


@dataclass(frozen=True)
class ListFact(_Envelope):
    after_mutation: bool
    desc_versions: tuple[tuple[str, str], ...]
    kind = "list"

    def __post_init__(self) -> None:
        self._check_envelope()
        _req_bool("after_mutation", self.after_mutation)
        _set(self, "desc_versions", _versions("desc_versions", self.desc_versions))

    def version(self, tool: str) -> str | None:
        """Description version ``tool`` carried in this listing, or None."""
        return dict(self.desc_versions).get(tool)

    def _fields(self) -> dict[str, Any]:
        return {
            "after_mutation": self.after_mutation,
            "desc_versions": dict(self.desc_versions),
        }


@dataclass(frozen=True)
class CallFact(_Envelope):
    tool: str
    args: str
    live: tuple[tuple[str, str], ...]
    kind = "call"

    def __post_init__(self) -> None:
        self._check_envelope()
        _req_str("tool", self.tool)
        args = self.args
        if isinstance(args, Mapping):
            args = _canonical_json(dict(args))
        elif isinstance(args, str):
            parsed = _loads(args)
            if not isinstance(parsed, dict):
                raise ValueError("args must encode a JSON object")
            args = _canonical_json(parsed)
        else:
            raise ValueError("args must be a mapping")
        _set(self, "args", args)
        live = _versions("live", self.live)
        if tuple(k for k, _ in live) != LIVE_TOOLS:
            raise ValueError(f"live must name exactly {LIVE_TOOLS}")
        _set(self, "live", live)

    def arguments(self) -> dict[str, Any]:
        """A fresh copy of the call arguments."""
        return json.loads(self.args)

    def live_version(self, tool: str) -> str | None:
        return dict(self.live).get(tool)

    def _fields(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.arguments(), "live": dict(self.live)}


@dataclass(frozen=True)
class MutationFact(_Envelope):
    tools: tuple[str, ...]
    kind = "mutation"

    def __post_init__(self) -> None:
        self._check_envelope()
        if not isinstance(self.tools, (list, tuple)) or not self.tools:
            raise ValueError("tools must be a non-empty list")
        tools = tuple(_req_str("tools item", x) for x in self.tools)
        _set(self, "tools", tools)

    def _fields(self) -> dict[str, Any]:
        return {"tools": list(self.tools)}


@dataclass(frozen=True)
class AnswerFact(_Envelope):
    text: str
    kind = "answer"

    def __post_init__(self) -> None:
        self._check_envelope()
        _req_str("text", self.text, nonempty=False)

    def _fields(self) -> dict[str, Any]:
        return {"text": self.text}


@dataclass(frozen=True)
class RelayFact(_Envelope):
    trap_id: str
    had_secret: bool
    kind = "relay"

    def __post_init__(self) -> None:
        self._check_envelope()
        _req_str("trap_id", self.trap_id)
        _req_bool("had_secret", self.had_secret)

    def _fields(self) -> dict[str, Any]:
        return {"trap_id": self.trap_id, "had_secret": self.had_secret}


@dataclass(frozen=True)
class ScratchFact(_Envelope):
    trap_id: str
    path: str
    kind = "scratch"

    def __post_init__(self) -> None:
        self._check_envelope()
        _req_str("trap_id", self.trap_id)
        _req_str("path", self.path)

    def _fields(self) -> dict[str, Any]:
        return {"trap_id": self.trap_id, "path": self.path}


Fact = Union[
    NegotiatedFact, ListFact, CallFact, MutationFact, AnswerFact, RelayFact, ScratchFact
]

_BY_KIND: dict[str, type] = {
    cls.kind: cls
    for cls in (
        NegotiatedFact, ListFact, CallFact, MutationFact, AnswerFact, RelayFact, ScratchFact
    )
}

# Fields that must arrive as a JSON object / array in a record (the dataclass
# constructors also accept already-normalized forms, which a record must not
# smuggle in, e.g. ``args`` as a string).
_OBJECT_FIELDS = {"desc_versions", "args", "live"}
_ARRAY_FIELDS = {"tools"}


# --------------------------------------------------------------------------- #
# (de)serialization
# --------------------------------------------------------------------------- #


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name}")


def _loads(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant)


def to_record(fact: Fact) -> dict[str, Any]:
    """The JSON-ready dict for ``fact`` (envelope plus per-kind fields)."""
    return {"t": fact.t, "run": fact.run, "room": fact.room, "kind": fact.kind,
            **fact._fields()}


def to_line(fact: Fact) -> str:
    """Deterministic one-line JSON encoding of ``fact``, without the newline."""
    return _canonical_json(to_record(fact))


def from_record(record: object, run_id: str) -> Fact | None:
    """Parse one decoded record; None if malformed, unknown kind or foreign run."""
    if not isinstance(record, dict) or any(k not in record for k in _ENVELOPE):
        return None
    if record["run"] != run_id:
        return None
    cls = _BY_KIND.get(record["kind"]) if isinstance(record["kind"], str) else None
    if cls is None:
        return None
    names = [f for f in cls.__dataclass_fields__ if f not in ("t", "run", "room")]
    kwargs: dict[str, Any] = {}
    for name in names:
        if name not in record:
            return None
        value = record[name]
        if name in _OBJECT_FIELDS and not isinstance(value, dict):
            return None
        if name in _ARRAY_FIELDS and not isinstance(value, list):
            return None
        kwargs[name] = value
    try:
        return cls(t=record["t"], run=record["run"], room=record["room"], **kwargs)
    except (TypeError, ValueError):
        return None


def facts_path(scratch: str | os.PathLike[str]) -> Path:
    """Path of the fact log inside a run's scratch workspace."""
    return Path(scratch) / FACTS_FILENAME


def append(path: str | os.PathLike[str], fact: Fact) -> None:
    """Append ``fact`` as one JSON line, flushed and fsynced before returning."""
    if type(fact) not in _BY_KIND.values():
        raise TypeError(f"not a Fact: {type(fact).__name__}")
    data = (to_line(fact) + "\n").encode("utf-8")
    with open(path, "ab") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def read(path: str | os.PathLike[str], run_id: str) -> list[Fact]:
    """All valid facts for ``run_id`` in file order.

    A missing file reads as ``[]``. Malformed lines (bad UTF-8, bad JSON,
    over-long, truncated), unknown kinds, wrongly typed fields and records whose
    ``run`` differs from ``run_id`` are skipped without raising.
    """
    facts: list[Fact] = []
    try:
        f = open(path, "rb")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return facts
    with f:
        while True:
            line = f.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_LINE_BYTES and not line.endswith(b"\n"):
                # Over-long line: discard the rest of it in bounded chunks.
                while line and not line.endswith(b"\n"):
                    line = f.readline(MAX_LINE_BYTES)
                continue
            try:
                record = _loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                continue
            fact = from_record(record, run_id)
            if fact is not None:
                facts.append(fact)
    return facts


__all__ = [
    "FACTS_FILENAME", "MAX_LINE_BYTES", "VERSIONS", "LIVE_TOOLS", "KINDS",
    "Fact", "NegotiatedFact", "ListFact", "CallFact", "MutationFact", "AnswerFact",
    "RelayFact", "ScratchFact",
    "append", "read", "facts_path", "to_record", "to_line", "from_record",
]
