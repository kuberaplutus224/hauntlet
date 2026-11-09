"""Helpers for the demo-agent tests: drive a room with a chosen ToolBox and build a bundle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hauntlet.core.models import Canary, RunManifest, RunScore
from hauntlet.core.room import RoomMaterials
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.core.toolbox import ToolBox
from hauntlet.rooms import default_rooms

BASE_URL = "http://range.test"
DEMO_ROOMS = ("threshold", "cursed-repo", "cursed-repo-tests", "poltergeist", "poltergeist-legacy")


@dataclass
class Driven:
    materials: RoomMaterials
    tools: ToolBox
    score: RunScore
    manifest: RunManifest
    canaries: tuple[Canary, ...]
    run_id: str


def drive(room: str, scratch: Path, agent, toolbox_cls=ToolBox) -> Driven:
    """Mirror ``runner.run_once`` but with a chosen ToolBox subclass; returns the pieces."""
    service = RangeService(Store(":memory:"), default_rooms(), base_url=BASE_URL)
    desc = service.start_run([room], grace_window_secs=0)
    run_id = desc.run.run_id
    rm = service.rooms[room]
    ctx, materials = service.setup_room(run_id, room, scratch)
    tools = toolbox_cls(materials.workspace, materials.env, service.fetch_local, service.base_url)
    try:
        transcript = agent.run(materials, tools)
        observations = rm.collect(ctx, materials, transcript)
        score = service.finalize(run_id, observations, transcript_provided=True)
    finally:
        rm.teardown(ctx)
    return Driven(materials, tools, score, service.manifest(run_id), desc.canaries, run_id)


def canary_values(canaries: tuple[Canary, ...]) -> list[str]:
    return [c.value for c in canaries if c.value]
