"""Run an agent through a room locally, once or N times."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hauntlet.core.aggregate import aggregate
from hauntlet.core.models import AggregateScore, RunManifest, RunScore
from hauntlet.core.room import Observation, Transcript
from hauntlet.core.service import RangeService
from hauntlet.core.toolbox import ToolBox


@dataclass(frozen=True)
class RunResult:
    score: RunScore
    manifest: RunManifest
    transcript: Transcript
    observations: tuple[Observation, ...]
    tool_calls: tuple[str, ...]


def run_once(
    service: RangeService,
    room_name: str,
    agent,
    scratch_root: Path,
    keep_workspace: bool = False,
) -> RunResult:
    desc = service.start_run([room_name], grace_window_secs=0)
    room = service.rooms[room_name]
    ctx = service.context(desc.run.run_id, room_name, scratch_root)
    materials = room.setup(ctx)
    tools = ToolBox(materials.workspace, materials.env, service.fetch_local, service.base_url)
    try:
        transcript = agent.run(materials, tools)
        observations = room.collect(ctx, materials, transcript)
        score = service.finalize(desc.run.run_id, observations, transcript_provided=True)
    finally:
        if not keep_workspace:
            room.teardown(ctx)
    return RunResult(
        score=score,
        manifest=service.manifest(desc.run.run_id),
        transcript=transcript,
        observations=tuple(observations),
        tool_calls=tuple(tools.calls),
    )


def run_repeated(
    service: RangeService, room_name: str, agent, n: int, scratch_root: Path
) -> tuple[list[RunResult], tuple[AggregateScore, ...]]:
    if n < 1:
        raise ValueError("n must be at least 1")
    results = [run_once(service, room_name, agent, scratch_root) for _ in range(n)]
    return results, aggregate([r.score for r in results])
