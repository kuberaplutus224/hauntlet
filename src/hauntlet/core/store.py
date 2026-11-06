"""SQLite persistence for runs, canaries and the append-only event log."""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from pathlib import Path

from hauntlet.core.models import (
    Canary,
    Event,
    Run,
    RunManifest,
    manifest_from_dict,
    to_dict,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    created_at    REAL NOT NULL,
    expires_at    REAL NOT NULL,
    status        TEXT NOT NULL,
    seed          INTEGER NOT NULL,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS canaries (
    canary_id  TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES runs(run_id),
    room       TEXT NOT NULL,
    trap_id    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    value      TEXT NOT NULL UNIQUE,
    is_control INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS canaries_run ON canaries(run_id);
CREATE TABLE IF NOT EXISTS events (
    event_id  TEXT PRIMARY KEY,
    run_id    TEXT NOT NULL,
    room      TEXT NOT NULL,
    trap_id   TEXT NOT NULL,
    channel   TEXT NOT NULL,
    signal    TEXT NOT NULL,
    timestamp REAL NOT NULL,
    detail    TEXT NOT NULL,
    expired   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id);
"""


class Store:
    """Thread-safe SQLite store. Use ``":memory:"`` for tests."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)

    # -- runs ---------------------------------------------------------------

    def add_run(self, run: Run, manifest: RunManifest, canaries: list[Canary]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?)",
                (
                    run.run_id,
                    run.created_at,
                    run.expires_at,
                    run.status,
                    run.seed,
                    json.dumps(to_dict(manifest)),
                ),
            )
            self._db.executemany(
                "INSERT INTO canaries VALUES (?,?,?,?,?,?,?)",
                [
                    (c.canary_id, c.run_id, c.room, c.trap_id, c.kind, c.value, int(c.is_control))
                    for c in canaries
                ],
            )

    def get_run(self, run_id: str) -> Run | None:
        with self._lock:
            row = self._db.execute(
                "SELECT run_id, created_at, expires_at, status, seed FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        return Run(**dict(row)) if row else None

    def get_manifest(self, run_id: str) -> RunManifest | None:
        with self._lock:
            row = self._db.execute(
                "SELECT manifest_json FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return manifest_from_dict(json.loads(row["manifest_json"])) if row else None

    def update_run(self, run_id: str, *, status: str | None = None, manifest: RunManifest | None = None) -> None:
        with self._lock, self._db:
            if status is not None:
                self._db.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run_id))
            if manifest is not None:
                self._db.execute(
                    "UPDATE runs SET manifest_json=? WHERE run_id=?",
                    (json.dumps(to_dict(manifest)), run_id),
                )

    # -- canaries -----------------------------------------------------------

    def canaries_for_run(self, run_id: str) -> list[Canary]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM canaries WHERE run_id=? ORDER BY room, trap_id, kind", (run_id,)
            ).fetchall()
        return [_canary(r) for r in rows]

    def canary_by_value(self, value: str, kind: str) -> Canary | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM canaries WHERE value=? AND kind=?", (value, kind)
            ).fetchone()
        return _canary(row) if row else None

    # -- events -------------------------------------------------------------

    def append_events(self, events: list[Event]) -> list[Event]:
        stored = [
            e if e.event_id else Event(**{**e.__dict__, "event_id": secrets.token_hex(8)})
            for e in events
        ]
        with self._lock, self._db:
            self._db.executemany(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        e.event_id,
                        e.run_id,
                        e.room,
                        e.trap_id,
                        e.channel,
                        e.signal,
                        e.timestamp,
                        e.detail,
                        int(e.expired),
                    )
                    for e in stored
                ],
            )
        return stored

    def events_for_run(self, run_id: str) -> list[Event]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY timestamp, event_id", (run_id,)
            ).fetchall()
        return [
            Event(**{**dict(r), "expired": bool(r["expired"])})
            for r in rows
        ]


def _canary(row: sqlite3.Row) -> Canary:
    d = dict(row)
    d["is_control"] = bool(d["is_control"])
    return Canary(**d)
