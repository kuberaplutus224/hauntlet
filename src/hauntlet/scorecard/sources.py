"""Load the scorecard's inputs (design.md "Inputs", "Fact-log path"). The only scorecard I/O.

Every string from a run passes through the run's D31 redactor (built from its
D30 canaries) before ``facts.py`` sees it.

**Fact-log paths** are built here and nowhere else:

1. the run ID must match ``RUN_ID_RE`` before any lookup;
2. ``RangeService.get_run`` must succeed, and the stored ``Run.run_id`` is used;
3. rooms come from the run's manifest, intersected with the registered MCP and
   Parlor rooms (the caller supplies no room, file name or path part);
4. the workspace is ``cli.mcp_workspace(scratch_root_beside(db), room,
   run.run_id)`` and the file is the room's own ``factlog.facts_path``;
5. the file must not be a symlink and must resolve under the resolved scratch
   root. Otherwise the room's fact log is "not available".
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hauntlet.core.models import RunManifest
from hauntlet.core.service import RangeService, UnknownRun
from hauntlet.exorcist.profiles import profile_for
from hauntlet.paths import scratch_root_beside
from hauntlet.redact import redactor
from hauntlet.rooms.parlor import factlog as parlor_factlog
from hauntlet.rooms.poltergeist import factlog as mcp_factlog
from hauntlet.scorecard.facts import Fact, normalise_event, normalise_mcp, normalise_parlor, normalise_trace
from hauntlet.scorecard.inputs import ExorcismInput, RunInput

RUN_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
MCP_ROOMS = frozenset({"poltergeist", "poltergeist-legacy"})
PARLOR_ROOMS = frozenset({"parlor"})
EVIDENCE = "evidence"

Redact = Callable[[str], str]


def check_run_id(run_id: object) -> str:
    """The run ID if it has the range's ID shape, else ``UnknownRun`` (a 404)."""
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise UnknownRun(str(run_id)[:80])
    return run_id


def _log_rooms(manifest: RunManifest) -> list[str]:
    return [rm.room for rm in manifest.rooms if rm.room in MCP_ROOMS | PARLOR_ROOMS]


def _safe_file(path: Path, root: Path) -> Path | None:
    """``path`` if it is a regular, non-symlink file resolving under ``root``."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if not path.resolve().is_relative_to(root.resolve()):
            return None
    except OSError:
        return None
    return path


def live_fact_log(db_path: Path, run_id: str, room: str) -> Path | None:
    """The live fact log of ``room`` for a run already validated against the store."""
    from hauntlet.cli import mcp_workspace  # cli imports the scorecard at module level

    if room not in MCP_ROOMS | PARLOR_ROOMS:
        return None
    root = scratch_root_beside(Path(db_path))
    workspace = mcp_workspace(root, room, run_id)
    module = mcp_factlog if room in MCP_ROOMS else parlor_factlog
    return _safe_file(module.facts_path(workspace), root)


def reports_fact_log(reports_dir: Path, room: str, run_id: str) -> Path | None:
    """The D19 copy ``hauntlet mcp finalize`` keeps (MCP rooms only)."""
    from hauntlet.exorcist.mcpfacts import reports_facts_path

    if room not in MCP_ROOMS:
        return None
    return _safe_file(reports_facts_path(Path(reports_dir), room, run_id), Path(reports_dir))


def evidence_fact_log(bundle_dir: Path, room: str, run_id: str) -> Path | None:
    """The D26 copy the demo keeps in the bundle directory."""
    return _safe_file(Path(bundle_dir) / EVIDENCE / f"facts-{run_id}-{room}.jsonl", Path(bundle_dir))


def evidence_trace(bundle_dir: Path, run_id: str) -> Path | None:
    return _safe_file(Path(bundle_dir) / EVIDENCE / f"trace-{run_id}.jsonl", Path(bundle_dir))


def _read_log(path: Path, room: str, run_id: str, manifest: RunManifest, redact: Redact) -> list[Fact]:
    if room in MCP_ROOMS:
        steered = dict(profile_for(room).mcp.steered_tools)
        recs = mcp_factlog.read(path, run_id)
        facts = (normalise_mcp(r, manifest, steered, redact) for r in recs if r.room == room)
    else:
        recs = parlor_factlog.read(path, run_id)
        facts = (normalise_parlor(r, manifest, redact) for r in recs if r.room == room)
    return [f for f in facts if f is not None]


def _read_trace(path: Path, room: str, redact: Redact) -> list[Fact]:
    out = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return out
    for i, line in enumerate(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(normalise_trace(rec, i, room, redact))
    return out


def load_run(
    service: RangeService,
    run_id: str,
    *,
    db_path: Path | None = None,
    reports_dir: Path | None = None,
    bundle_dir: Path | None = None,
) -> RunInput:
    """A run from the store, with its redacted events and the first fact log found
    per MCP/Parlor room: the bundle's D26 evidence, then live scratch, then the D19 copy."""
    check_run_id(run_id)
    run = service.get_run(run_id)  # raises UnknownRun
    rid = run.run_id
    score, manifest = service.score(rid), service.manifest(rid)
    redact = redactor(service.canaries(rid))
    facts: list[Fact] = [f for f in (normalise_event(e, manifest, redact) for e in service.events(rid)) if f]
    fact_logs: dict[str, bool] = {}
    for room in _log_rooms(manifest):
        candidates: list[Path | None] = []
        if bundle_dir is not None:
            candidates.append(evidence_fact_log(bundle_dir, room, rid))
        if db_path is not None:
            candidates.append(live_fact_log(db_path, rid, room))
        if reports_dir is not None:
            candidates.append(reports_fact_log(reports_dir, room, rid))
        path = next((p for p in candidates if p is not None), None)
        fact_logs[room] = path is not None
        if path is not None:
            facts += _read_log(path, room, rid, manifest, redact)
    if bundle_dir is not None and manifest.rooms:
        trace = evidence_trace(bundle_dir, rid)
        if trace is not None:
            facts += _read_trace(trace, manifest.rooms[0].room, redact)
    return RunInput(run, score, manifest, tuple(facts), fact_logs)


# --------------------------------------------------------------------------- #
# exorcism
# --------------------------------------------------------------------------- #


def _json(path: Path) -> dict | None:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def load_bundle(bundle_dir: Path) -> dict | None:
    return _json(Path(bundle_dir) / "bundle.json")


def _after_created(service: RangeService, after_id: str) -> float:
    try:
        return service.get_run(after_id).created_at
    except UnknownRun:
        return float("-inf")


def load_delta(bundle_dir: Path, service: RangeService, after_run_id: str | None = None) -> tuple[str, dict | None] | None:
    """(after run ID, delta document) for ``after_run_id``, or for the after run created
    last (ties by run ID). ``None`` when the bundle has no delta yet."""
    deltas = Path(bundle_dir) / "deltas"
    files = sorted(p for p in deltas.glob("*.json") if p.is_file() and not p.is_symlink()) if deltas.is_dir() else []
    ids = [p.stem for p in files]
    if after_run_id is not None:
        if after_run_id not in ids:
            return None
        chosen = after_run_id
    elif not ids:
        return None
    else:
        chosen = max(ids, key=lambda i: (_after_created(service, i), i))
    return chosen, _json(deltas / f"{chosen}.json")


def path_of(delta: dict) -> str:
    """The page path from the delta's own path field (never inferred from scores)."""
    return {"demo-agent": "demo-agent", "real-client": "real-client"}.get(delta.get("path"), "not-recorded")


def load_exorcism(
    ex_service: Any,
    bundle_dir: Path,
    *,
    after_run_id: str | None = None,
    db_path: Path | None = None,
    reports_dir: Path | None = None,
    download_url: str | None = None,
    bundle_path: str | None = None,
) -> tuple[str, str, ExorcismInput]:
    """(before run ID, path, exorcism input). Unreadable files give the C27 state."""
    from hauntlet.exorcist import report

    service: RangeService = ex_service.service
    bundle_dir = Path(bundle_dir)
    bundle_id = bundle_dir.name
    bundle = load_bundle(bundle_dir)
    if bundle is None or not isinstance(bundle.get("before_run_id"), str):
        # The writer lays bundles out as <root>/<before run ID>/<bundle ID>, so the
        # run can still be shown on its own, with C27 in the exorcism section.
        return bundle_dir.parent.name, "not-recorded", ExorcismInput(bundle_id, {}, {}, unreadable=True)
    found = load_delta(bundle_dir, service, after_run_id)
    if found is None:
        delta = json.loads(report.render_json(ex_service.before_only_delta(bundle_dir)))
    else:
        delta = found[1]
        if delta is None:
            return bundle["before_run_id"], "not-recorded", ExorcismInput(bundle_id, {}, {}, unreadable=True)
    after = None
    if delta.get("after_run_id"):
        try:
            after = load_run(service, str(delta["after_run_id"]), db_path=db_path,
                             reports_dir=reports_dir, bundle_dir=bundle_dir)
        except UnknownRun:
            after = None
    ex = ExorcismInput(bundle_id, bundle, delta, after, download_url=download_url, bundle_path=bundle_path)
    return bundle["before_run_id"], path_of(delta), ex
