"""Scratch-only writes (Requirement 3).

Every bundle goes to ``<root>/<before_run_id>/<bundle_id>/``. The writer
refuses:

- a root inside any ``.kiro`` directory, including this repository's own and
  ``~/.kiro``;
- an ID outside ``[A-Za-z0-9_-]{8,64}``;
- an existing bundle directory;
- a symlink at any component it creates;
- any file that would resolve outside the bundle directory.

Files are created with ``O_CREAT | O_EXCL | O_NOFOLLOW``.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from hauntlet.exorcist import manifest
from hauntlet.exorcist.model import BundleSpec
from hauntlet.exorcist.validate import validate

ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
DELTAS = "deltas"
#: The demo's kept evidence (approved change D26): redacted fact logs and traces.
EVIDENCE = "evidence"


class WriteRefused(PermissionError):
    pass


def new_bundle_id() -> str:
    return secrets.token_urlsafe(12)


def _check_id(what: str, value: str) -> None:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise WriteRefused(f"invalid {what} {value!r}")


def _refuse_kiro(path: Path) -> None:
    if ".kiro" in path.parts:
        raise WriteRefused(f"refusing to write inside a .kiro directory: {path}")


def _contained(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _mkdir_strict(path: Path, *, exist_ok: bool) -> None:
    if path.is_symlink():
        raise WriteRefused(f"refusing a symlink at {path}")
    try:
        path.mkdir(exist_ok=exist_ok)
    except FileExistsError:
        raise WriteRefused(f"{path} already exists") from None
    if path.is_symlink() or not path.is_dir():
        raise WriteRefused(f"{path} is not a real directory")


def _write_rel(base: Path, rel: str, data: bytes) -> Path:
    pure = PurePosixPath(rel)
    if (
        pure.is_absolute()
        or "\\" in rel
        or str(pure) != rel  # non-canonical: "a//b", "a/./b", trailing "/"
        or not pure.parts
        or any(p in ("", ".", "..") for p in pure.parts)
    ):
        raise WriteRefused(f"invalid relative path {rel!r}")
    cur = base
    for part in pure.parts[:-1]:
        cur = cur / part
        _mkdir_strict(cur, exist_ok=True)
    target = cur / pure.parts[-1]
    if not _contained(target.parent.resolve(), base.resolve()):
        raise WriteRefused(f"{rel!r} escapes the bundle directory")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except FileExistsError:
        raise WriteRefused(f"{target} already exists") from None
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return target


def prepare_root(root: Path) -> Path:
    """Resolve and create the scratch root, refusing any ``.kiro`` location."""
    resolved = Path(root).expanduser().resolve()
    _refuse_kiro(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    if Path(root).expanduser().is_symlink():
        raise WriteRefused(f"refusing a symlinked scratch root {root}")
    return resolved


def write_bundle(
    root: Path, spec: BundleSpec, created_at: float, bundle_id: str | None = None
) -> tuple[str, Path]:
    """Validate, then write the guardrail files and the manifest. Returns ``(bundle_id, dir)``."""
    bundle_id = bundle_id or new_bundle_id()
    _check_id("run ID", spec.before_run_id)
    _check_id("bundle ID", bundle_id)
    validate(spec.files)  # Requirement 2.7: nothing is written for an invalid bundle
    base_root = prepare_root(root)
    run_dir = base_root / spec.before_run_id
    _mkdir_strict(run_dir, exist_ok=True)
    bundle_dir = run_dir / bundle_id
    _mkdir_strict(bundle_dir, exist_ok=False)
    if not _contained(bundle_dir.resolve(), base_root):
        raise WriteRefused(f"{bundle_dir} escapes the scratch root")
    for rel in sorted(spec.files):
        _write_rel(bundle_dir, rel, spec.files[rel])
    _write_rel(bundle_dir, manifest.MANIFEST_JSON, manifest.bundle_json(spec, bundle_id, created_at))
    _write_rel(bundle_dir, manifest.MANIFEST_MD, manifest.exorcism_md(spec, bundle_id))
    return bundle_id, bundle_dir


def write_into(bundle_dir: Path, rel: str, data: bytes) -> Path:
    """Write one more file into an existing bundle (``deltas/``, ``baseline/``, ``evidence/``), same checks."""
    bundle_dir = Path(bundle_dir)
    resolved = bundle_dir.resolve()
    _refuse_kiro(resolved)
    if bundle_dir.is_symlink() or not resolved.is_dir():
        raise WriteRefused(f"{bundle_dir} is not a bundle directory")
    first = PurePosixPath(rel).parts[:1]
    if first not in ((DELTAS,), ("baseline",), (EVIDENCE,)):
        raise WriteRefused(f"only deltas/, baseline/ and evidence/ may be added to a bundle, not {rel!r}")
    return _write_rel(resolved, rel, data)


def write_delta(bundle_dir: Path, after_run_id: str, files: Mapping[str, bytes]) -> list[Path]:
    """Write ``deltas/<after_run_id>.<ext>`` for each extension in ``files``."""
    _check_id("run ID", after_run_id)
    out = []
    for ext in sorted(files):
        if ext not in ("json", "html", "txt"):
            raise WriteRefused(f"unknown delta format {ext!r}")
        out.append(write_into(bundle_dir, f"{DELTAS}/{after_run_id}.{ext}", files[ext]))
    return out
