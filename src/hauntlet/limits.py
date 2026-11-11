"""Request limits for the hosted range (approved changes D33, D34). In memory, one process.

- ``client_key``: who a request comes from. With ``HAUNTLET_TRUST_PROXY=1`` it is
  the **last** ``X-Forwarded-For`` entry, the address the trusted proxy (Render's)
  saw connect. Earlier entries are whatever the client sent, so they are never
  used. Without it, the socket address.
- ``Window``: at most ``limit`` events per key in a sliding ``period``.
- ``Slots``: at most ``limit`` things open at once per key (live streams).
- ``RunCap``: at most ``limit`` unfinished runs created by this server (D33).

Keys are pruned as they age, and at most ``MAX_KEYS`` are kept, so a flood of
forged addresses cannot grow memory without bound: the oldest key is dropped.
"""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping

MAX_KEYS = 10_000


#: Longest client key kept; a longer header value is cut, so keys stay small.
MAX_KEY_CHARS = 64


def forwarded_entries(headers: Mapping[str, str]) -> list[str]:
    return [e.strip() for e in headers.get("x-forwarded-for", "").split(",") if e.strip()]


def client_key(
    headers: Mapping[str, str], socket_host: str | None, trust_proxy: bool, ip_header: str | None = None,
) -> str:
    """Who a request comes from (D34).

    Behind a trusted proxy (``trust_proxy``): the value of ``ip_header`` when one is
    configured and present (for example ``CF-Connecting-IP``), else the last
    ``X-Forwarded-For`` entry. Never an earlier entry. Otherwise the socket address.
    """
    if trust_proxy:
        if ip_header:
            value = headers.get(ip_header.lower(), "").strip()
            if value:
                return value[:MAX_KEY_CHARS]
        entries = forwarded_entries(headers)
        if entries:
            return entries[-1][:MAX_KEY_CHARS]
    return socket_host or "unknown"


class Window:
    """Sliding-window counter: ``hit(key)`` is True when the event is allowed."""

    def __init__(self, limit: int, period: float, clock: Callable[[], float]) -> None:
        self.limit, self.period, self.clock = limit, period, clock
        self._seen: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            times = self._seen.pop(key, deque())
            while times and times[0] <= now - self.period:
                times.popleft()
            allowed = len(times) < self.limit
            if allowed:
                times.append(now)
            if times:
                self._seen[key] = times  # most recent last
            while len(self._seen) > MAX_KEYS:
                self._seen.popitem(last=False)
            return allowed


class Slots:
    """Per-key open counter: ``take`` is True when a slot was taken; ``give`` frees it."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._open: dict[str, int] = {}
        self._lock = threading.Lock()

    def take(self, key: str) -> bool:
        with self._lock:
            n = self._open.get(key, 0)
            if n >= self.limit:
                return False
            if key not in self._open and len(self._open) >= MAX_KEYS:
                return False  # every key is holding a slot: refuse rather than grow
            self._open[key] = n + 1
            return True

    def give(self, key: str) -> None:
        with self._lock:
            n = self._open.get(key, 0) - 1
            if n > 0:
                self._open[key] = n
            else:
                self._open.pop(key, None)


class RunCap:
    """Unfinished runs this server created (D33). ``is_open(run_id)`` asks the store.

    ``admit(create)`` checks the cap and records the new run under one lock, so two
    requests at once cannot both slip under it. ``create`` returns the run ID.
    """

    def __init__(self, limit: int, is_open: Callable[[str], bool]) -> None:
        self.limit, self.is_open = limit, is_open
        self._runs: list[str] = []
        self._lock = threading.Lock()

    def admit(self, create: Callable[[], str]) -> str | None:
        with self._lock:
            self._runs = [r for r in self._runs if self.is_open(r)]
            if len(self._runs) >= self.limit:
                return None
            run_id = create()
            self._runs.append(run_id)
            return run_id
