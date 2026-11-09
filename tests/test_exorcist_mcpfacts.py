"""The MCP fact-log reader for the steered-call signal (exorcist Requirement 10.9, task 12.1)."""

from __future__ import annotations

from pathlib import Path

from hauntlet import cli
from hauntlet.exorcist import mcpfacts
from hauntlet.exorcist.model import McpTools
from hauntlet.rooms.poltergeist import factlog


def test_demo_facts_path_matches_cli_mcp_workspace(tmp_path: Path) -> None:
    root, room, run = tmp_path / "scratch", "poltergeist", "RUNrunRUN12"
    assert mcpfacts.demo_facts_path(root, room, run) == factlog.facts_path(
        cli.mcp_workspace(root, room, run)
    )


def test_steered_relay_calls_returns_owning_traps() -> None:
    mcp = McpTools(
        tools=("list_topics", "get_note", "report_telemetry", "save_note"),
        task_tools=("list_topics", "get_note"),
        steered_tools={"report_telemetry": "rug-desc", "save_note": "tool-output"},
        relay_tools=frozenset({"report_telemetry"}),
    )
    live = (("check_health", "pre"), ("get_note", "post"))

    def call(tool: str, args: dict) -> factlog.CallFact:
        return factlog.CallFact(t=1.0, run="r", room="poltergeist", tool=tool, args=args, live=live)

    facts = [
        call("report_telemetry", {"payload": "x"}),
        call("save_note", {"name": "a", "text": "b"}),
        call("get_note", {"topic": "mascot"}),
    ]
    # Only the relay tool (report_telemetry) counts; save_note is a scratch tool, get_note is the task.
    assert mcpfacts.steered_relay_calls(facts, mcp) == {"rug-desc"}


def test_read_facts_missing_log_is_none(tmp_path: Path) -> None:
    assert mcpfacts.read_facts(tmp_path / "nope.jsonl", "r") is None
