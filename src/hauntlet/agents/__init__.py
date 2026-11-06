"""Reference agents: regression anchors for the range.

``naive`` follows any instruction it reads and should score high. ``hardened``
treats file content as data, does only the task, and reports the attempt; it
should score L0 with Detected. Neither calls a model: they are deterministic so
scoring regressions are unambiguous.
"""

from __future__ import annotations

from typing import Protocol

from hauntlet.core.room import RoomMaterials, Transcript
from hauntlet.core.toolbox import ToolBox


class Agent(Protocol):
    name: str

    def run(self, materials: RoomMaterials, tools: ToolBox) -> Transcript: ...


def get_agent(name: str) -> Agent:
    from hauntlet.agents.hardened import HardenedAgent
    from hauntlet.agents.naive import NaiveAgent

    agents: dict[str, Agent] = {"naive": NaiveAgent(), "hardened": HardenedAgent()}
    try:
        return agents[name]
    except KeyError:
        raise KeyError(f"unknown agent {name!r}; choose from {sorted(agents)}") from None
