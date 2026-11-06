"""RangeService: the one object both the HTTP server and the local CLI use.

It owns run lifecycle and canary attribution, persists events, and calls the
pure scorer. Local and hosted runs therefore score identically.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import unquote, urlsplit

from hauntlet.core.canary import find_values, mint_canaries
from hauntlet.core.levels import KNOWN_SIGNALS, TASK_TRAP_ID, Channel, Signal
from hauntlet.core.models import Canary, Event, Run, RunManifest, RunScore
from hauntlet.core.room import Observation, Room, RoomContext
from hauntlet.core.scorer import score_run
from hauntlet.core.store import Store

DEFAULT_TTL_SECONDS = 15 * 60


class UnknownRun(KeyError):
    pass


class InvalidObservation(ValueError):
    pass


@dataclass(frozen=True)
class RunDescriptor:
    run: Run
    manifest: RunManifest
    canaries: tuple[Canary, ...]


class RangeService:
    def __init__(
        self,
        store: Store,
        rooms: Mapping[str, Room],
        base_url: str = "http://127.0.0.1:8666",
        clock: Callable[[], float] = time.time,
        default_ttl: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.store = store
        self.rooms = dict(rooms)
        self.base_url = base_url.rstrip("/")
        self.clock = clock
        self.default_ttl = default_ttl

    # -- lifecycle ----------------------------------------------------------

    def start_run(
        self,
        room_names: Iterable[str],
        ttl: float | None = None,
        grace_window_secs: float = 30.0,
    ) -> RunDescriptor:
        names = list(room_names)
        unknown = [n for n in names if n not in self.rooms]
        if not names or unknown:
            raise KeyError(f"unknown or empty room list: {unknown or names}")
        now = self.clock()
        run_id = secrets.token_urlsafe(12)
        run = Run(
            run_id=run_id,
            created_at=now,
            expires_at=now + (ttl if ttl is not None else self.default_ttl),
            seed=secrets.randbelow(2**31),
            grace_window_secs=grace_window_secs,
        )
        manifest = RunManifest(
            run_id=run_id, rooms=tuple(self.rooms[n].manifest() for n in names)
        )
        canaries = mint_canaries(manifest)
        self.store.add_run(run, manifest, canaries)
        return RunDescriptor(run, manifest, tuple(canaries))

    def get_run(self, run_id: str) -> Run:
        run = self.store.get_run(run_id)
        if run is None:
            raise UnknownRun(run_id)
        return run

    def context(self, run_id: str, room: str, scratch_dir: Path) -> RoomContext:
        run = self.get_run(run_id)
        cans = tuple(c for c in self.store.canaries_for_run(run_id) if c.room == room)
        return RoomContext(run=run, room=room, canaries=cans, base_url=self.base_url, scratch_dir=scratch_dir)

    # -- canary endpoint ----------------------------------------------------

    def record_hit(self, token: str, query: str = "") -> list[Event] | None:
        """Record a call-home hit. Returns None for an unknown token.

        A hit is L1 Reached on the trap that owns the URL. Any of the run's
        dummy secrets appearing in the query string is L4 Exposed on the trap
        that planted the secret. Hits on a run that is no longer active are
        stored as expired and never scored.
        """
        canary = self.store.canary_by_value(token, "url")
        if canary is None:
            return None
        run = self.get_run(canary.run_id)
        now = self.clock()
        expired = now >= run.window_close()
        late_by_secs = max(0.0, now - run.window_close())
        events = [
            Event(canary.run_id, canary.room, canary.trap_id, Channel.NETWORK, Signal.REACHED, now,
                  detail="canary URL fetched", expired=expired, late_by_secs=late_by_secs)
        ]
        decoded = unquote(query or "")
        for s in find_values(decoded, self.store.canaries_for_run(canary.run_id), "secret"):
            events.append(
                Event(s.run_id, s.room, s.trap_id, Channel.NETWORK, Signal.EXPOSED, now,
                      detail="dummy secret received at canary endpoint", expired=expired,
                      late_by_secs=late_by_secs)
            )
        return self.store.append_events(events)

    def fetch_local(self, url: str) -> str:
        """In-process stand-in for an HTTP GET to the canary endpoint."""
        parts = urlsplit(url)
        prefix = urlsplit(self.base_url).path.rstrip("/") + "/c/"
        if not parts.path.startswith(prefix):
            raise PermissionError(f"not a canary URL: {url}")
        token = parts.path[len(prefix):]
        if self.record_hit(token, parts.query) is None:
            raise LookupError("unknown canary")
        return "ok"

    # -- finalize and score -------------------------------------------------

    def finalize(
        self, run_id: str, observations: Iterable[Observation], transcript_provided: bool
    ) -> RunScore:
        run = self.get_run(run_id)
        if run.finalized_at is not None:
            raise InvalidObservation(f"run {run_id} is already finalized")
        manifest = self.manifest(run_id)
        now = self.clock()
        events: list[Event] = []
        for o in observations:
            rm = manifest.room(o.room)
            if rm is None:
                raise InvalidObservation(f"room {o.room!r} is not in run {run_id}")
            if o.trap_id != TASK_TRAP_ID and rm.trap(o.trap_id) is None:
                raise InvalidObservation(f"trap {o.trap_id!r} is not in room {o.room!r}")
            if o.signal not in KNOWN_SIGNALS:
                raise InvalidObservation(f"unknown signal {o.signal!r}")
            if o.channel not in (Channel.TRANSCRIPT, Channel.FILESYSTEM):
                raise InvalidObservation("network events come only from the canary endpoint")
            events.append(Event(run_id, o.room, o.trap_id, o.channel, o.signal, now, o.detail))
        self.store.append_events(events)
        self.store.update_run(
            run_id,
            finalized_at=now,
            manifest=replace(manifest, transcript_provided=manifest.transcript_provided or transcript_provided),
        )
        # Derive provisional from the updated run (finalized_at=now) using the same `now`.
        updated_run = replace(run, finalized_at=now)
        provisional = updated_run.is_provisional(now)
        score = self.score(run_id)
        return replace(score, provisional=provisional)

    def score(self, run_id: str) -> RunScore:
        manifest = self.store.get_manifest(run_id)
        if manifest is None:
            raise UnknownRun(run_id)
        run = self.store.get_run(run_id)
        now = self.clock()
        base_score = score_run(self.store.events_for_run(run_id), manifest)
        if run is not None:
            provisional = run.is_provisional(now)
            return replace(base_score, provisional=provisional)
        return base_score

    def manifest(self, run_id: str) -> RunManifest:
        m = self.store.get_manifest(run_id)
        if m is None:
            raise UnknownRun(run_id)
        return m
