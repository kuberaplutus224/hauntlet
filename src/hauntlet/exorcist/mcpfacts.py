"""Read an MCP room's fact log for the "steered tool called, canary not reached" signal.

Requirement 10.9: a trap whose steered relay tool was called, but whose after
signals carry no ``reached``, is reported with its own after-signal and never
as clean or improved. The fact log is read where it lives:

- on the demo path, the run's workspace (``<scratch>/<room>-<run_id>``);
- on the real-client path, the copy ``hauntlet mcp finalize`` keeps
  (``<reports>/mcp-facts-<run>-<room>.jsonl``, approved change D19).

``factlog.read`` skips malformed and foreign-run records, so a tampered or
truncated log degrades to "fact log not available" rather than a wrong signal.
"""

from __future__ import annotations

from pathlib import Path

from hauntlet.exorcist.model import McpTools
from hauntlet.rooms.poltergeist import factlog

STEERED_CALL_NO_CANARY = "steered-call-no-canary"


def steered_relay_calls(facts: list, mcp: McpTools) -> set[str]:
    """Owning trap IDs of every logged call to one of the room's relay tools."""
    owners: set[str] = set()
    for fact in facts:
        if isinstance(fact, factlog.CallFact) and fact.tool in mcp.relay_tools:
            trap = mcp.steered_tools.get(fact.tool)
            if trap is not None:
                owners.add(trap)
    return owners


def demo_facts_path(scratch_root: Path, room: str, run_id: str) -> Path:
    """Where the demo run's fact log lives (matches ``PoltergeistRoom`` and ``cli.mcp_workspace``)."""
    return factlog.facts_path(Path(scratch_root) / f"{room}-{run_id}")


def reports_facts_path(reports_dir: Path, room: str, run_id: str) -> Path:
    """Where ``hauntlet mcp finalize`` keeps the fact-log copy (D19)."""
    return Path(reports_dir) / f"mcp-facts-{run_id}-{room}.jsonl"


def read_facts(path: Path, run_id: str) -> list | None:
    """Facts for ``run_id`` at ``path``, or ``None`` when no readable log exists."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        return None
    return factlog.read(path, run_id)
