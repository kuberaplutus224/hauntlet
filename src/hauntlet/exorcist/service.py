"""ExorcistService: run the demo loop, generate a bundle, attach a real-client after run.

The demo path runs the deterministic demo agent twice in-process, once on the
baseline config and once on the generated bundle, and builds the delta. It
never runs or imitates a real client; the real-client path only attaches a run
the tester finalized themselves.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from hauntlet.agents._task import PARLOR_ROOM
from hauntlet.agents.demo import DemoAgent, baseline_for
from hauntlet.core.levels import Signal
from hauntlet.core.models import RunManifest, RunScore
from hauntlet.core.room import RoomMaterials
from hauntlet.core.service import RangeService
from hauntlet.core.toolbox import ToolBox
from hauntlet.exorcist import mcpfacts, report
from hauntlet.exorcist.delta import DEMO, PENDING, REAL, Delta, admit, build_delta
from hauntlet.exorcist.generate import generate
from hauntlet.exorcist.manifest import needs_demo_env_note
from hauntlet.exorcist.model import BundleSpec
from hauntlet.exorcist.profiles import profile_for, real_client_env
from hauntlet.exorcist.texts import (
    DEMO_LABEL,
    FILE_ROOM_ENV_NOTE,
    MCP_ENV_NOTE,
    PENDING_LABEL,
    REAL_CLIENT_LABEL,
)
from hauntlet.exorcist.validate import validate
from hauntlet.exorcist.writer import EVIDENCE, write_bundle, write_delta, write_into
from hauntlet.redact import redactor


class DemoUnsupported(ValueError):
    pass


@dataclass(frozen=True)
class DemoRun:
    run_id: str
    score: RunScore
    manifest: RunManifest
    facts: list | None  # MCP fact log, read before teardown; None otherwise
    denials: tuple[str, ...]
    trace: list | None  # the demo agent's per-action trace; None on the real-client path


@dataclass(frozen=True)
class DemoResult:
    room: str
    bundle_id: str
    bundle_dir: Path
    before: DemoRun
    after: DemoRun
    delta: Delta


class ExorcistService:
    def __init__(
        self,
        service: RangeService,
        root: Path,
        reports_dir: Path | None = None,
        clock=time.time,
        html_renderer=None,
    ) -> None:
        self.service = service
        self.root = Path(root)
        self.reports_dir = Path(reports_dir) if reports_dir is not None else None
        self.clock = clock
        #: D23: ``(bundle_dir, after_run_id) -> bytes`` for the delta's HTML file. The
        #: caller passes the scorecard's renderer; the Exorcist never imports it (D24).
        #: ``None`` keeps ``report.render_html``.
        self.html_renderer = html_renderer

    # -- demo path ---------------------------------------------------------

    def supports(self, room: str) -> bool:
        return room in self.service.rooms and room != PARLOR_ROOM

    def demo(self, room: str) -> DemoResult:
        if room not in self.service.rooms:
            raise DemoUnsupported(f"unknown room {room!r}; known: {sorted(self.service.rooms)}")
        if not self.supports(room):
            supported = sorted(r for r in self.service.rooms if self.supports(r))
            raise DemoUnsupported(f"the demo agent does not support {room!r}; supported: {supported}")

        with tempfile.TemporaryDirectory(prefix="hauntlet-exorcist-demo-") as tmp:
            tmp = Path(tmp)
            baseline = baseline_for(tmp / "baseline", room)
            before = self._run_demo(room, baseline, tmp / "before")

            spec = generate(before.score, before.manifest)
            validate(spec.files)
            created_at = self.clock()
            bundle_id, bundle_dir = write_bundle(self.root, spec, created_at)

            after = self._run_demo(room, bundle_dir, tmp / "after")
            self._admit(before, after, created_at)
            # D26: keep the evidence the temporary directory would lose, redacted,
            # before the delta is written (its scorecard page reads it).
            for run in (before, after):
                self._write_evidence(bundle_dir, room, run)
            delta = self._delta(
                spec, before, after, path=DEMO, path_label=DEMO_LABEL,
                after_run_id=after.run_id, denials=after.denials,
                not_interpreted=_bundle_not_interpreted(bundle_dir),
            )
            self._write_delta(bundle_dir, after.run_id, delta)
            return DemoResult(room, bundle_id, bundle_dir, before, after, delta)

    # -- generate / find / attach by bundle (shared by the CLI and the hosted routes) --

    def generate_bundle(self, run_id: str) -> tuple[str, Path]:
        """Write a bundle for a finalized, non-provisional run. Returns ``(id, dir)``.

        Raises ``UnknownRun`` for an unknown run and ``NotFinal`` for one that is
        not finalized or still provisional (Requirement 1.1).
        """
        from hauntlet.exorcist.eligibility import require_final
        from hauntlet.exorcist.generate import generate
        from hauntlet.exorcist.validate import validate
        from hauntlet.exorcist.writer import write_bundle

        run = self.service.get_run(run_id)
        score = self.service.score(run_id)
        require_final(run, score, run_id)
        spec = generate(score, self.service.manifest(run_id))
        validate(spec.files)
        return write_bundle(self.root, spec, self.clock())

    def find_bundle(self, bundle_id: str) -> Path:
        """The bundle directory for ``bundle_id`` under the root, else ``FileNotFoundError``."""
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", bundle_id or ""):
            raise FileNotFoundError(f"invalid bundle ID {bundle_id!r}")
        if self.root.is_dir():
            for before_dir in sorted(self.root.iterdir()):
                cand = before_dir / bundle_id
                if (cand / "bundle.json").is_file():
                    return cand
        raise FileNotFoundError(f"no bundle {bundle_id!r}")

    def _before_of(self, bundle_dir: Path):
        import json

        before_run_id = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))["before_run_id"]
        return self.service.score(before_run_id), self.service.manifest(before_run_id)

    def attach_to_bundle(self, bundle_dir: Path, after_run_id: str) -> Delta:
        """Attach a real-client after run to an existing bundle (re-derives its spec)."""
        from hauntlet.exorcist.generate import generate

        before_score, before_manifest = self._before_of(bundle_dir)
        spec = generate(before_score, before_manifest)
        return self.attach((before_score, before_manifest), spec, bundle_dir, after_run_id)

    def before_only_delta(self, bundle_dir: Path) -> Delta:
        """A delta with no after run yet (Requirement 10.1), for a freshly generated bundle."""
        from hauntlet.exorcist.generate import generate

        before_score, before_manifest = self._before_of(bundle_dir)
        spec = generate(before_score, before_manifest)
        return build_delta(
            before_score, before_manifest, spec,
            path=PENDING, path_label=PENDING_LABEL,
            after=None, demo_env_note=None,
        )

    def _run_demo(self, room: str, config_dir: Path, scratch: Path) -> DemoRun:
        agent = DemoAgent(config_dir, real_client_env)
        rm = self.service.rooms[room]
        desc = self.service.start_run([room], grace_window_secs=0)
        run_id = desc.run.run_id
        ctx, materials = self.service.setup_room(run_id, room, scratch)
        tools = ToolBox(materials.workspace, materials.env, self.service.fetch_local, self.service.base_url)
        try:
            transcript = agent.run(materials, tools)
            observations = rm.collect(ctx, materials, transcript)
            score = self.service.finalize(run_id, observations, transcript_provided=True)
            facts = self._read_demo_facts(room, scratch, run_id)
        finally:
            rm.teardown(ctx)
        denials = tuple(d.item_id for d in agent.denials)
        return DemoRun(run_id, score, self.service.manifest(run_id), facts, denials, list(agent.trace))

    def _write_evidence(self, bundle_dir: Path, room: str, run: DemoRun) -> None:
        """D26: ``evidence/facts-<run>-<room>.jsonl`` (MCP rooms) and ``evidence/trace-<run>.jsonl``.

        Every string is redacted with the run's own canaries (D30, D31), so the
        files hold no canary value. They sit in the bundle directory, follow its
        retention, and are left out of the download archive.
        """
        import json

        from hauntlet.rooms.poltergeist import factlog

        redact = redactor(self.service.canaries(run.run_id))

        def clean(value):
            if isinstance(value, str):
                return redact(value)
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            if isinstance(value, list):
                return [clean(v) for v in value]
            return value

        def dumps(record: dict) -> str:
            return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

        if run.facts is not None:
            lines = [dumps(clean(factlog.to_record(f))) for f in run.facts]
            write_into(bundle_dir, f"{EVIDENCE}/facts-{run.run_id}-{room}.jsonl",
                       ("\n".join(lines) + "\n" if lines else "").encode("utf-8"))
        if run.trace is not None:
            lines = [
                dumps(clean({"seq": i, "tool_id": tool_id, "where": where, "source": source,
                             "proceeded": bool(proceeded), "denied_by": list(denied)}))
                for i, (tool_id, where, source, proceeded, denied) in enumerate(run.trace)
            ]
            write_into(bundle_dir, f"{EVIDENCE}/trace-{run.run_id}.jsonl",
                       ("\n".join(lines) + "\n" if lines else "").encode("utf-8"))

    def _read_demo_facts(self, room: str, scratch: Path, run_id: str) -> list | None:
        if profile_for(room).mcp is None:
            return None
        return mcpfacts.read_facts(mcpfacts.demo_facts_path(scratch, room, run_id), run_id)

    # -- real-client path --------------------------------------------------

    def attach(
        self, before: DemoRun | tuple[RunScore, RunManifest], spec: BundleSpec, bundle_dir: Path,
        after_run_id: str,
    ) -> Delta:
        """Attach a finalized real-client after run (Requirement 10.6) and write the delta."""
        before_score, before_manifest = (
            (before.score, before.manifest) if isinstance(before, DemoRun) else before
        )
        after_run = self.service.get_run(after_run_id)
        after_score = self.service.score(after_run_id)
        bundle_created = self._bundle_created_at(bundle_dir)
        admit(before_score, after_run, after_score, bundle_created)
        after = DemoRun(after_run_id, after_score, self.service.manifest(after_run_id),
                        self._read_reports_facts(after_score, after_run_id), (), None)
        delta = self._delta(
            spec, _AsRun(before_score, before_manifest), after,
            path=REAL, path_label=REAL_CLIENT_LABEL, after_run_id=after_run_id, denials=(),
            not_interpreted=_bundle_not_interpreted(bundle_dir),
        )
        self._write_delta(bundle_dir, after_run_id, delta)
        return delta

    def _read_reports_facts(self, score: RunScore, run_id: str) -> dict:
        """Per-MCP-room facts from the D19 copy in the reports directory."""
        out: dict[str, list | None] = {}
        for rs in score.rooms:
            if profile_for(rs.room).mcp is None:
                continue
            path = None
            if self.reports_dir is not None:
                path = mcpfacts.reports_facts_path(self.reports_dir, rs.room, run_id)
            out[rs.room] = mcpfacts.read_facts(path, run_id) if path is not None else None
        return out

    def _bundle_created_at(self, bundle_dir: Path) -> float:
        import json

        doc = json.loads((Path(bundle_dir) / "bundle.json").read_text(encoding="utf-8"))
        return float(doc["created_at"])

    # -- delta assembly ----------------------------------------------------

    def _admit(self, before: DemoRun, after: DemoRun, created_at: float) -> None:
        # The demo creates its own after run after the bundle, so the created-at
        # ordering is guaranteed; -inf skips that one check (it matters only for a
        # tester-attached run, which `attach` admits with the real bundle time).
        admit(before.score, self.service.get_run(after.run_id), after.score, float("-inf"))

    def _delta(
        self, spec: BundleSpec, before, after, *, path, path_label, after_run_id, denials, not_interpreted,
    ) -> Delta:
        extras, fact_logs = self._mcp_signals(after)
        note = self._env_note(before.manifest) if (path == DEMO and needs_demo_env_note(spec)) else None
        return build_delta(
            before.score, before.manifest, spec,
            path=path, path_label=path_label,
            after=after.score, after_run_id=after_run_id,
            extras=extras, fact_logs=fact_logs, denials=denials,
            not_interpreted=not_interpreted, demo_env_note=note,
            trace=after.trace,
        )

    def _env_note(self, manifest: RunManifest) -> str:
        """Only the environment sentence(s) that apply to this report's room(s) (Requirement 4.6)."""
        notes: list[str] = []
        has_mcp = any(profile_for(rm.room).mcp is not None for rm in manifest.rooms)
        has_file = any(profile_for(rm.room).mcp is None for rm in manifest.rooms)
        if has_mcp:
            notes.append(MCP_ENV_NOTE)
        if has_file:
            notes.append(FILE_ROOM_ENV_NOTE)
        return " ".join(notes)

    def _mcp_signals(self, after: DemoRun) -> tuple[dict, dict]:
        """(extras per (room,trap), fact_log_available per room) from the after fact log(s)."""
        extras: dict[tuple[str, str], set[str]] = {}
        available: dict[str, bool] = {}
        facts_by_room = after.facts if isinstance(after.facts, dict) else None
        for rs in after.score.rooms:
            mcp = profile_for(rs.room).mcp
            if mcp is None:
                available[rs.room] = True
                continue
            facts = facts_by_room.get(rs.room) if facts_by_room is not None else after.facts
            available[rs.room] = facts is not None
            if facts is None:
                continue
            owners = mcpfacts.steered_relay_calls(facts, mcp)
            by_id = {t.trap_id: t for t in rs.per_trap}
            for trap in owners:
                t = by_id.get(trap)
                if t is not None and Signal.REACHED not in t.signals:
                    extras[(rs.room, trap)] = {mcpfacts.STEERED_CALL_NO_CANARY}
        return extras, available

    def _write_delta(self, bundle_dir: Path, after_run_id: str, delta: Delta) -> list[Path]:
        files = report.render_all(delta)
        if self.html_renderer is None:
            paths = write_delta(bundle_dir, after_run_id, files)
            html = files["html"]
        else:
            # The JSON goes first: the renderer reads the delta back from it.
            paths = write_delta(bundle_dir, after_run_id, {k: files[k] for k in ("json", "txt")})
            html = self.html_renderer(bundle_dir, after_run_id)
            paths += write_delta(bundle_dir, after_run_id, {"html": html})
        if self.reports_dir is not None:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            (self.reports_dir / f"exorcist-delta-{after_run_id}.html").write_bytes(html)
        return paths


@dataclass(frozen=True)
class _AsRun:
    score: RunScore
    manifest: RunManifest


def _bundle_not_interpreted(bundle_dir: Path) -> tuple[str, ...]:
    """What the interpreter could not read in the written bundle (for the report)."""
    from hauntlet.exorcist.interpreter import Config

    return Config.load(bundle_dir).not_interpreted
