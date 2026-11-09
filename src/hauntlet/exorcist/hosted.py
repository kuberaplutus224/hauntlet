"""The hosted Exorcist: self-serve demo, bundle download, attach, report (Requirement 11, D16).

Wraps ``ExorcistService`` with the caps and the retention sweeper the hosted
range needs, and serves only bundles the server generated. It accepts no
uploaded bundle, config or hook (11.5). Demo runs are in-process and make no
outbound network call.
"""

from __future__ import annotations

import io
import threading
import time
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from hauntlet.exorcist import report as report_mod
from hauntlet.exorcist.service import DemoUnsupported, ExorcistService

#: Files in a bundle that make up the applyable archive (not deltas or baseline).
_ARCHIVE_SKIP = ("deltas", "baseline")
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)  # fixed, so the archive is byte-deterministic


class Overloaded(Exception):
    """A cap was exceeded (maps to HTTP 429)."""


class NotFound(Exception):
    """An unknown, expired or malformed ID (maps to HTTP 404)."""


@dataclass(frozen=True)
class HostedCaps:
    max_concurrent: int = 1
    per_minute: int = 6
    retention_secs: float = 3600.0
    demo_rooms: tuple[str, ...] = ("cursed-repo", "poltergeist")


class HostedExorcist:
    def __init__(self, service: ExorcistService, caps: HostedCaps, clock=time.time) -> None:
        self.service = service
        self.caps = caps
        self.clock = clock
        self._sema = threading.BoundedSemaphore(max(1, caps.max_concurrent))
        self._recent: deque[float] = deque()
        self._rate_lock = threading.Lock()

    # -- caps and sweeper --------------------------------------------------

    def _rate_check(self) -> None:
        now = self.clock()
        with self._rate_lock:
            while self._recent and now - self._recent[0] >= 60.0:
                self._recent.popleft()
            if len(self._recent) >= self.caps.per_minute:
                raise Overloaded("too many demos this minute; try again shortly")
            self._recent.append(now)

    def _acquire(self) -> None:
        if not self._sema.acquire(blocking=False):
            raise Overloaded("another demo is already running; try again shortly")

    def sweep(self) -> None:
        """Delete bundle directories older than the retention window, under the root only.

        Age is the bundle's recorded ``created_at`` (same clock as the caps), so
        it is consistent whatever the filesystem mtimes are.
        """
        import json

        root = self.service.root.resolve()
        if not root.is_dir():
            return
        cutoff = self.clock() - self.caps.retention_secs
        for before_dir in list(root.iterdir()):
            if not before_dir.is_dir() or before_dir.is_symlink():
                continue
            for bundle in list(before_dir.iterdir()):
                if not bundle.is_dir() or bundle.is_symlink() or not bundle.resolve().is_relative_to(root):
                    continue
                manifest = bundle / "bundle.json"
                if not manifest.is_file():
                    continue
                try:
                    created = float(json.loads(manifest.read_text(encoding="utf-8"))["created_at"])
                except (OSError, ValueError, KeyError):
                    continue
                if created < cutoff:
                    _rmtree_under(bundle, root)
            if before_dir.is_dir() and not any(before_dir.iterdir()):
                before_dir.rmdir()

    # -- routes ------------------------------------------------------------

    def demo(self, room: str) -> dict:
        self.sweep()
        if room not in self.caps.demo_rooms or not self.service.supports(room):
            raise DemoUnsupported(
                f"the hosted demo does not offer {room!r}; offered: {sorted(self.caps.demo_rooms)}"
            )
        self._rate_check()
        self._acquire()
        try:
            result = self.service.demo(room)
        finally:
            self._sema.release()
        return {
            "bundle_id": result.bundle_id,
            "report_url": f"/exorcisms/{result.bundle_id}/report",
            "bundle_url": f"/exorcisms/{result.bundle_id}/bundle",
        }

    def exorcise(self, run_id: str) -> dict:
        from hauntlet.core.service import UnknownRun
        from hauntlet.exorcist.eligibility import NotFinal

        self.sweep()
        self._rate_check()
        self._acquire()
        try:
            bundle_id, _dir = self.service.generate_bundle(run_id)
        except UnknownRun as exc:
            raise NotFound(str(exc)) from None
        finally:
            self._sema.release()
        return {
            "bundle_id": bundle_id,
            "report_url": f"/exorcisms/{bundle_id}/report",
            "bundle_url": f"/exorcisms/{bundle_id}/bundle",
        }

    def bundle_zip(self, bundle_id: str) -> bytes:
        bundle_dir = self._bundle(bundle_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
            for path in _archive_files(bundle_dir):
                info = zipfile.ZipInfo(str(path.relative_to(bundle_dir).as_posix()), date_time=_ZIP_EPOCH)
                info.external_attr = 0o644 << 16
                zf.writestr(info, path.read_bytes())
        return buf.getvalue()

    def attach(self, bundle_id: str, run_id: str):
        bundle_dir = self._bundle(bundle_id)
        return self.service.attach_to_bundle(bundle_dir, run_id)

    def report_html(self, bundle_id: str) -> str:
        bundle_dir = self._bundle(bundle_id)
        latest = _latest_delta(bundle_dir)
        if latest is not None:
            return latest.read_text(encoding="utf-8")
        return report_mod.render_html(self.service.before_only_delta(bundle_dir))

    def _bundle(self, bundle_id: str) -> Path:
        try:
            return self.service.find_bundle(bundle_id)
        except FileNotFoundError as exc:
            raise NotFound(str(exc)) from None


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _archive_files(bundle_dir: Path) -> list[Path]:
    out = []
    for p in sorted(bundle_dir.rglob("*")):
        if p.is_file() and not p.is_symlink() and p.relative_to(bundle_dir).parts[0] not in _ARCHIVE_SKIP:
            out.append(p)
    return out


def _latest_delta(bundle_dir: Path) -> Path | None:
    htmls = sorted((bundle_dir / "deltas").glob("*.html")) if (bundle_dir / "deltas").is_dir() else []
    return htmls[-1] if htmls else None


def _rmtree_under(target: Path, root: Path) -> None:
    import shutil

    if target.resolve().is_relative_to(root) and target.is_dir() and not target.is_symlink():
        shutil.rmtree(target, ignore_errors=True)
