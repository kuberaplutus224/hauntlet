"""Two processes on one SQLite file (approved core change D8).

The real-client poltergeist path runs ``hauntlet mcp serve`` and
``hauntlet mcp finalize`` as separate processes against a single
``HAUNTLET_DB``, alongside the range server. These tests are the design's
spike promoted to a committed test: concurrent writers and a concurrent
reader on one store file, with no lock errors and nothing lost.

Child entry points are module-level so they pickle under the ``spawn``
start method (the macOS default), which the test selects explicitly rather
than inheriting from the platform.
"""

from __future__ import annotations

import multiprocessing
import queue
import sqlite3
import time
from pathlib import Path

from hauntlet.core.models import Canary, Event, Run, RoomManifest, RunManifest, TrapSpec
from hauntlet.core.store import Store

EVENTS_PER_WRITER = 50
ROOM = "threshold"
TRAP = "t1"
# Bounds every wait so a regression fails instead of hanging.
TIMEOUT_SECS = 30.0


def _manifest(run_id: str) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        rooms=(RoomManifest(room=ROOM, traps=(TrapSpec(TRAP, "NOTES.md", "test"),)),),
    )


def _seed_run(store: Store, run_id: str) -> None:
    store.add_run(
        Run(run_id=run_id, created_at=0.0, expires_at=1e12, seed=7),
        _manifest(run_id),
        [
            Canary(
                canary_id=f"{run_id}-c1",
                run_id=run_id,
                room=ROOM,
                trap_id=TRAP,
                kind="marker",
                value=f"marker-{run_id}",
            )
        ],
    )


def _event(run_id: str, tag: str, i: int) -> Event:
    return Event(
        run_id=run_id,
        room=ROOM,
        trap_id=TRAP,
        channel="filesystem",
        signal="acted",
        timestamp=float(i),
        detail=f"{tag}-{i}",
    )


def _append_events(store: Store, run_id: str, tag: str, n: int) -> None:
    for i in range(n):
        store.append_events([_event(run_id, tag, i)])


# --------------------------------------------------------------------------- #
# Child entry points (module-level: must be picklable under "spawn")
# --------------------------------------------------------------------------- #


def writer_child(db_path: str, run_id: str, n: int, results: object) -> None:
    """Append ``n`` events through a second connection to the same file."""
    errors: list[str] = []
    try:
        store = Store(db_path)
        _append_events(store, run_id, "child", n)
    except BaseException as exc:  # pragma: no cover - reported to the parent
        errors.append(f"{type(exc).__name__}: {exc}")
    results.put({"role": "writer", "errors": errors})  # type: ignore[attr-defined]


def reader_child(db_path: str, run_id: str, target: int, results: object) -> None:
    """Read runs, canaries and events while the writers are working."""
    errors: list[str] = []
    reads = 0
    max_seen = 0
    try:
        store = Store(db_path)
        deadline = time.monotonic() + TIMEOUT_SECS / 2
        while time.monotonic() < deadline:
            try:
                run = store.get_run(run_id)
                manifest = store.get_manifest(run_id)
                canaries = store.canaries_for_run(run_id)
                events = store.events_for_run(run_id)
            except sqlite3.Error as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                continue
            reads += 1
            if run is None or run.run_id != run_id:
                errors.append("run row missing or wrong")
            if manifest is None or manifest.run_id != run_id:
                errors.append("manifest missing or wrong")
            if len(canaries) != 1:
                errors.append(f"expected 1 canary, saw {len(canaries)}")
            if any(e.run_id != run_id for e in events):
                errors.append("event from a foreign run")
            max_seen = max(max_seen, len(events))
            if max_seen >= target:
                break
    except BaseException as exc:  # pragma: no cover - reported to the parent
        errors.append(f"{type(exc).__name__}: {exc}")
    results.put({"role": "reader", "errors": errors, "reads": reads, "max_seen": max_seen})  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_two_processes_share_one_store_file(tmp_path: Path) -> None:
    db_path = str(tmp_path / "hauntlet.db")
    run_id = "run-mp-1"
    parent = Store(db_path)
    _seed_run(parent, run_id)

    ctx = multiprocessing.get_context("spawn")
    results: multiprocessing.Queue = ctx.Queue()
    target = 2 * EVENTS_PER_WRITER

    writer = ctx.Process(
        target=writer_child, args=(db_path, run_id, EVENTS_PER_WRITER, results)
    )
    reader = ctx.Process(target=reader_child, args=(db_path, run_id, target, results))
    writer.start()
    reader.start()

    # The parent is the second writer, so 2N events are written concurrently.
    parent_error: str | None = None
    try:
        _append_events(parent, run_id, "parent", EVENTS_PER_WRITER)
    except BaseException as exc:  # pragma: no cover - surfaces as a failure below
        parent_error = f"{type(exc).__name__}: {exc}"

    # Drain the queue before joining: a full pipe would deadlock the children.
    reported: dict[str, dict] = {}
    deadline = time.monotonic() + TIMEOUT_SECS
    while len(reported) < 2 and time.monotonic() < deadline:
        try:
            payload = results.get(timeout=1.0)
        except queue.Empty:
            continue
        reported[payload["role"]] = payload

    for proc in (writer, reader):
        proc.join(timeout=max(1.0, deadline - time.monotonic()))
        if proc.is_alive():  # pragma: no cover - only on a regression
            proc.terminate()
            proc.join(timeout=5.0)

    assert parent_error is None, f"parent writer failed: {parent_error}"
    assert writer.exitcode == 0, f"writer exitcode {writer.exitcode}"
    assert reader.exitcode == 0, f"reader exitcode {reader.exitcode}"
    assert set(reported) == {"writer", "reader"}, f"missing reports: {reported}"
    assert reported["writer"]["errors"] == []
    assert reported["reader"]["errors"] == []
    assert reported["reader"]["reads"] > 0, "reader never completed a read"

    events = parent.events_for_run(run_id)
    assert len(events) == target
    assert sum(1 for e in events if e.detail.startswith("parent-")) == EVENTS_PER_WRITER
    assert sum(1 for e in events if e.detail.startswith("child-")) == EVENTS_PER_WRITER
    assert len({e.event_id for e in events}) == target

    # A fresh connection sees exactly the same log.
    assert len(Store(db_path).events_for_run(run_id)) == target


def test_file_store_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    store = Store(tmp_path / "wal.db")
    assert store._db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert store._db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_memory_store_still_works_without_wal() -> None:
    store = Store(":memory:")
    # An in-memory database silently ignores WAL; it must still open and work.
    assert store._db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "memory"
    assert store._db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000

    run_id = "run-mem"
    _seed_run(store, run_id)
    _append_events(store, run_id, "mem", 3)
    assert store.get_run(run_id) is not None
    assert len(store.canaries_for_run(run_id)) == 1
    assert len(store.events_for_run(run_id)) == 3
