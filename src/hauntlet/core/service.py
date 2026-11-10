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
from hauntlet.core.levels import KNOWN_SIGNALS, PAGE_TRAP_ID, TASK_TRAP_ID, Channel, Signal
from hauntlet.core.models import Canary, Event, RoomManifest, Run, RunManifest, RunScore
from hauntlet.core.room import (
    Observation,
    PageResponse,
    PageRoom,
    Room,
    RoomContext,
    RoomMaterials,
)
from hauntlet.core.scorer import score_run
from hauntlet.core.store import Store

DEFAULT_TTL_SECONDS = 15 * 60

#: What ``fetch_local`` returns for a non-text page response (``ToolBox.fetch``
#: returns ``str``; reference agents never need image bytes).
NON_TEXT_PLACEHOLDER = "[non-text resource]"


class UnknownRun(KeyError):
    pass


class InvalidObservation(ValueError):
    pass


class RunClosed(InvalidObservation):
    """Raised when finalize is rejected because the run is already finalized or closed."""
    pass


class InvalidRoom(ValueError):
    pass


def _validate_manifest(room_name: str, manifest: RoomManifest) -> None:
    """Raise InvalidRoom with a descriptive message for any invalid manifest variant.

    Checks in order:
    (a) At least one control trap (is_control=True)
    (b) At least one non-control trap (is_control=False)
    (c) No duplicate trap IDs
    (d) No trap uses a reserved ID ("__task__" or "__page__")
    (e) Every non-control trap has a non-empty source citation
    """
    traps = manifest.traps

    # (a) must have at least one control trap
    if not any(t.is_control for t in traps):
        raise InvalidRoom(
            f"Room {room_name!r}: manifest has no control trap (is_control=True). "
            "At least one control trap is required."
        )

    # (b) must have at least one non-control trap
    if not any(not t.is_control for t in traps):
        raise InvalidRoom(
            f"Room {room_name!r}: manifest has no non-control trap (is_control=False). "
            "At least one non-control trap is required."
        )

    # (c) no duplicate trap IDs
    seen: set[str] = set()
    duplicates: list[str] = []
    for t in traps:
        if t.trap_id in seen:
            duplicates.append(t.trap_id)
        seen.add(t.trap_id)
    if duplicates:
        raise InvalidRoom(
            f"Room {room_name!r}: duplicate trap IDs: {sorted(set(duplicates))}."
        )

    # (d) no trap uses a reserved pseudo-trap ID ("__task__", or "__page__" from D11)
    for reserved_id in (TASK_TRAP_ID, PAGE_TRAP_ID):
        if any(t.trap_id == reserved_id for t in traps):
            raise InvalidRoom(
                f"Room {room_name!r}: trap ID {reserved_id!r} is reserved and cannot be used."
            )

    # (e) every non-control trap must have a non-empty source citation
    missing_source = [t.trap_id for t in traps if not t.is_control and not t.source.strip()]
    if missing_source:
        raise InvalidRoom(
            f"Room {room_name!r}: non-control traps missing a source citation: {missing_source}."
        )


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
        *,
        run_id_factory: Callable[[], str] = lambda: secrets.token_urlsafe(12),
        seed_factory: Callable[[], int] = lambda: secrets.randbelow(2**31),
        page_scratch_root: Path | None = None,
    ) -> None:
        for name, room in rooms.items():
            _validate_manifest(name, room.manifest())
        self.store = store
        self.rooms = dict(rooms)
        self.base_url = base_url.rstrip("/")
        self.clock = clock
        self.default_ttl = default_ttl
        self.run_id_factory = run_id_factory
        self.seed_factory = seed_factory
        #: Scratch root for page rooms this process did not set up itself, e.g.
        #: ``hauntlet serve`` serving a run that ``hauntlet parlor open`` set up (D11).
        self.page_scratch_root = page_scratch_root
        #: (run_id, room) -> the scratch root ``setup_room`` used in this process.
        self._page_roots: dict[tuple[str, str], Path] = {}

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
        run_id = self.run_id_factory()
        run = Run(
            run_id=run_id,
            created_at=now,
            expires_at=now + (ttl if ttl is not None else self.default_ttl),
            seed=self.seed_factory(),
            grace_window_secs=grace_window_secs,
        )
        manifest = RunManifest(
            run_id=run_id, rooms=tuple(self.rooms[n].manifest() for n in names)
        )
        canaries = mint_canaries(manifest)
        # D11: one page-serving canary per page room, owned by the reserved
        # ``__page__`` pseudo-trap. Other rooms get nothing extra.
        for name in names:
            if isinstance(self.rooms[name], PageRoom):
                canaries.append(
                    Canary(
                        canary_id=secrets.token_hex(8),
                        run_id=run_id,
                        room=name,
                        trap_id=PAGE_TRAP_ID,
                        kind="page",
                        value=secrets.token_urlsafe(18),
                    )
                )
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

    def setup_room(
        self, run_id: str, room_name: str, scratch_root: Path
    ) -> tuple[RoomContext, RoomMaterials]:
        """Build the room's context and run its ``setup`` under ``scratch_root``.

        For a page room, remember ``scratch_root`` for this run so ``serve_page``
        in this process finds the workspace ``setup`` just created (D11).
        """
        ctx = self.context(run_id, room_name, scratch_root)
        room = self.rooms[room_name]
        materials = room.setup(ctx)
        if isinstance(room, PageRoom):
            self._page_roots[(run_id, room_name)] = scratch_root
        return ctx, materials

    def _page_root(self, run_id: str, room_name: str) -> Path | None:
        """The scratch root a page room's workspace lives under, or None."""
        return self._page_roots.get((run_id, room_name), self.page_scratch_root)

    # -- pages (D11) --------------------------------------------------------

    def serve_page(self, token: str, query: str = "") -> PageResponse | None:
        """Serve a page room's response for a ``page`` token. Records no event.

        Returns None (the caller answers 404) unless the token is a known page
        canary, its run exists and is active (not finalized, not past
        ``expires_at``; the grace window does not extend serving), the room is a
        page room, and a scratch root is known for the run.
        """
        canary = self.store.canary_by_value(token, "page")
        if canary is None:
            return None
        run = self.store.get_run(canary.run_id)
        if run is None or not run.is_active(self.clock()):
            return None
        room = self.rooms.get(canary.room)
        if not isinstance(room, PageRoom):
            return None
        root = self._page_root(canary.run_id, canary.room)
        if root is None:
            return None
        return room.serve_page(self.context(canary.run_id, canary.room, root), query)

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
        if self.record_hit(token, parts.query) is not None:
            return "ok"
        page = self.serve_page(token, parts.query)  # D11: page tokens, never scored
        if page is None:
            raise LookupError("unknown canary")
        if page.content_type.startswith("text/"):
            return page.body.decode("utf-8", errors="replace")
        return NON_TEXT_PLACEHOLDER

    # -- finalize and score -------------------------------------------------

    def finalize(
        self, run_id: str, observations: Iterable[Observation], transcript_provided: bool
    ) -> RunScore:
        run = self.get_run(run_id)
        if run.finalized_at is not None:
            raise RunClosed("already finalized")
        now = self.clock()
        if now >= run.window_close():
            raise RunClosed("run closed")
        manifest = self.manifest(run_id)
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
        return self.score(run_id)

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

    # -- read-only accessors (approved changes D21, D30) ---------------------

    def events(self, run_id: str) -> list[Event]:
        """The run's stored events, unchanged (D21). Read-only; scores nothing."""
        if self.store.get_manifest(run_id) is None:
            raise UnknownRun(run_id)
        return self.store.events_for_run(run_id)

    def canaries(self, run_id: str) -> list[Canary]:
        """The run's canaries, unchanged (D30), for redaction. Read-only."""
        if self.store.get_manifest(run_id) is None:
            raise UnknownRun(run_id)
        return self.store.canaries_for_run(run_id)
