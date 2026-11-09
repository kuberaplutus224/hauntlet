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


def _demo_agent() -> Agent:
    """The Exorcist demo agent on a bare baseline (D17 (h)).

    The baseline names no MCP server, so the interpreter applies no MCP gating
    and the agent obeys every instruction it reads, like ``naive``. A per-room
    baseline with ``autoApprove: ["*"]`` is written by the Exorcist's demo flow;
    both are gullible, so the behaviour is the same.
    """
    import tempfile

    from hauntlet.agents.demo import DemoAgent, write_baseline_config
    from hauntlet.exorcist.profiles import real_client_env

    baseline = write_baseline_config(tempfile.mkdtemp(prefix="hauntlet-demo-baseline-"))
    return DemoAgent(baseline, real_client_env)


def get_agent(name: str) -> Agent:
    from hauntlet.agents.hardened import HardenedAgent
    from hauntlet.agents.naive import NaiveAgent

    agents: dict[str, Agent] = {"naive": NaiveAgent(), "hardened": HardenedAgent()}
    if name == "demo":
        return _demo_agent()
    try:
        return agents[name]
    except KeyError:
        raise KeyError(f"unknown agent {name!r}; choose from {sorted(agents)}") from None
