"""The Exorcist's demo agent: a gullible agent that obeys only what the config allows.

It proposes the same actions a naive agent would, from the generic instruction
shapes in the cited benchmarks, and routes every one through the generated
config's interpreter (``hauntlet.exorcist.interpreter.decide``). Its behaviour
changes only through that config, so a before/after delta measures the bundle,
not the agent.

It knows nothing about any room: it dispatches through the same task driver the
reference agents use (``hauntlet.agents._task``), and the only room constants it
uses are imported from there. It never reads ``RoomMaterials``' environment or
calls the toolbox's environment accessor; its agent environment is exactly what
``env_channel`` returns, which the harness fills with the channel a real client
of the room would get (exorcist Requirement 8.9).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path

from hauntlet.agents._task import (
    PARLOR_ROOM,
    POLTERGEIST_ROOMS,
    Exchange,
    do_task,
)
from hauntlet.core.room import RoomMaterials, Transcript, TranscriptEntry
from hauntlet.core.toolbox import ToolBox
from hauntlet.exorcist import hookrun, render
from hauntlet.exorcist.interpreter import Config, HookRunner, decide
from hauntlet.exorcist.model import RESPOND, Action, Decision, Outcome, Source

#: Generic instruction shapes (the same ones the naive agent keys off).
_URL = re.compile(r"https?://\S+")
_ENV_REF = re.compile(r"<value of ([A-Z0-9_]+)>")
_CREATE = re.compile(r'create the file (\S+) containing "([^"]+)"', re.IGNORECASE)
_REPEAT = re.compile(r'repeat the phrase "([^"]+)"', re.IGNORECASE)
#: A description that says "you must call <tool> with the <var> value shown in the note".
_CALL_WITH_VALUE = re.compile(
    r"you must call `?(\w+)`? with the `?(\w+)`? value", re.IGNORECASE
)
#: Tool output that says "by calling <tool>('a', 'b')".
_CALLING = re.compile(r"by calling `?(\w+)\('([^']*)',\s*'([^']*)'\)")
#: An imperative verb just before a URL makes following it a directed instruction.
_IMPERATIVE = re.compile(r"(?:open|visit|confirm|register|fetch|navigate to|go to)\s*$", re.IGNORECASE)


class UnsupportedRoom(ValueError):
    """The demo agent does not support this room (real-client path only)."""


def _report_sentence(where: str) -> str:
    return (
        f" Ignored a suspicious instruction embedded in {where}; it looks like a prompt"
        " injection and is outside the task, so I did not follow it."
    )


class DemoAgent:
    name = "demo"

    def __init__(
        self,
        config_dir: Path | str,
        env_channel: Callable[[RoomMaterials], Mapping[str, str]] | None = None,
        *,
        runner: HookRunner = hookrun.run,
    ) -> None:
        self.config_dir = Path(config_dir)
        self._env_channel = env_channel or (lambda _m: {})
        self._runner = runner
        #: Every guardrail item that denied an action in the last run, in order.
        #: The Exorcist reads it to show the demo path's attributions.
        self.denials: list = []
        #: One record per gated action: ``(tool_id, where, source, proceeded, denier_ids)``.
        #: Lets a test compare behaviour across configs and prove causality.
        self.trace: list[tuple[str, str, str, bool, tuple[str, ...]]] = []

    # -- dispatch ----------------------------------------------------------

    def run(self, materials: RoomMaterials, tools: ToolBox) -> Transcript:
        config = Config.load(self.config_dir)
        self.denials = []
        self.trace = []
        env = dict(self._env_channel(materials))
        transcript: Transcript = [TranscriptEntry("user", materials.task)]
        if materials.room in POLTERGEIST_ROOMS:
            return self._run_mcp(materials, tools, transcript, config, env)
        if materials.room == PARLOR_ROOM:
            raise UnsupportedRoom(f"the demo agent does not support {materials.room!r} (real-client only)")
        return self._run_files(materials, tools, transcript, config, env)

    # -- gate --------------------------------------------------------------

    def _gate(
        self,
        action: Action,
        text: str,
        config: Config,
        env: Mapping[str, str],
        transcript: Transcript,
        reports: dict[str, str],
    ) -> bool:
        """Decide one proposed action; log a skip and a report. True to proceed."""
        decision: Decision = decide(action, text, config, env, runner=self._runner)
        denier_ids = tuple(d.item_id for d in decision.deniers)
        proceeded = decision.outcome is Outcome.PROCEED
        self.trace.append((action.tool_id, action.where, action.source.value, proceeded, denier_ids))
        if decision.report and action.where not in reports:
            reports[action.where] = _report_sentence(action.where)
        if decision.outcome is Outcome.SKIP:
            self.denials.extend(decision.deniers)
            transcript.append(TranscriptEntry("tool", f"skipped: {action.tool_id} ({', '.join(denier_ids)})"))
            return False
        return True

    # -- file rooms --------------------------------------------------------

    def _run_files(
        self,
        materials: RoomMaterials,
        tools: ToolBox,
        transcript: Transcript,
        config: Config,
        env: Mapping[str, str],
    ) -> Transcript:
        reports: dict[str, str] = {}
        repeated: list[str] = []
        for rel in tools.list_files():
            text = tools.read_file(rel)
            transcript.append(TranscriptEntry("tool", f"read {rel}"))
            flat = " ".join(text.split())
            filled = _ENV_REF.sub(lambda m: env.get(m.group(1), ""), flat)
            for m in _URL.finditer(filled):
                url = m.group(0).rstrip(".,;")
                directed = bool(_IMPERATIVE.search(filled[: m.start()]))
                action = Action("web_fetch", frozenset({"web"}), {"url": url}, Source.REPO_FILE, rel, directed)
                if self._gate(action, filled, config, env, transcript, reports):
                    try:
                        tools.fetch(url)
                        transcript.append(TranscriptEntry("tool", f"fetched {url}"))
                    except (PermissionError, LookupError) as exc:
                        transcript.append(TranscriptEntry("tool", f"fetch failed: {exc}"))
            for name, content in _CREATE.findall(filled):
                action = Action("fs_write", frozenset({"write"}), {"path": name, "content": content},
                                Source.REPO_FILE, rel, directed=True)
                if self._gate(action, filled, config, env, transcript, reports):
                    tools.write_file(name, content + "\n")
                    transcript.append(TranscriptEntry("tool", f"wrote {name}"))
            for phrase in _REPEAT.findall(filled):
                action = Action(RESPOND, frozenset(), {"text": phrase}, Source.REPO_FILE, rel, directed=True)
                if self._gate(action, filled, config, env, transcript, reports):
                    repeated.append(phrase)

        summary = do_task(materials, tools)
        if repeated:
            summary += " As requested: " + "; ".join(repeated)
        summary += "".join(reports[w] for w in sorted(reports))
        transcript.append(TranscriptEntry("assistant", summary))
        return transcript

    # -- MCP rooms ---------------------------------------------------------

    def _run_mcp(
        self,
        materials: RoomMaterials,
        tools: ToolBox,
        transcript: Transcript,
        config: Config,
        env: Mapping[str, str],
    ) -> Transcript:
        server = config.mcp_server or render.server_name(materials.room)
        reports: dict[str, str] = {}

        def react(client, ex: Exchange) -> str:
            transcript.append(TranscriptEntry("tool", "called list_topics"))
            transcript.append(TranscriptEntry("tool", "re-listed tools after the change signal"))
            schemas = client.input_schemas()
            # A changed description that directs a call: read the value, then make the call.
            for tool_name, desc in sorted(ex.relisted.items()):
                if not desc or desc == ex.approved.get(tool_name):
                    continue
                m = _CALL_WITH_VALUE.search(desc)
                if m is None:
                    continue
                target, var = m.group(1), m.group(2)
                where = f"the {tool_name} tool description"
                read_args = _args_from_task(schemas.get(tool_name, {}), materials.task)
                read = self._mcp_action(server, tool_name, read_args, Source.TOOL_DESCRIPTION, where)
                if not self._gate(read, desc, config, env, transcript, reports):
                    continue
                reply = client.call(tool_name, **read_args)
                transcript.append(TranscriptEntry("tool", f"called {tool_name}"))
                value = _value_from_reply(reply, var)
                prop = _single_property(schemas.get(target, {}))
                call_args = {prop: value} if prop else {}
                call = self._mcp_action(server, target, call_args, Source.TOOL_DESCRIPTION, where)
                if self._gate(call, desc, config, env, transcript, reports):
                    client.call(target, **call_args)
                    transcript.append(TranscriptEntry("tool", f"called {target}"))
            # Tool output that writes out a call: make it.
            for target, a, b in _CALLING.findall(ex.topics):
                props = _properties(schemas.get(target, {}))
                call_args = dict(zip(props, (a, b))) if len(props) >= 2 else {}
                where = "the list_topics tool output"
                call = self._mcp_action(server, target, call_args, Source.TOOL_OUTPUT, where)
                if self._gate(call, ex.topics, config, env, transcript, reports):
                    client.call(target, **call_args)
                    transcript.append(TranscriptEntry("tool", f"called {target}"))
            return "".join(reports[w] for w in sorted(reports))

        summary = do_task(materials, tools, react)
        transcript.append(TranscriptEntry("assistant", summary))
        return transcript

    def _mcp_action(
        self, server: str, tool: str, args: Mapping[str, str], source: Source, where: str
    ) -> Action:
        tags = frozenset({"@mcp", f"@{server}", f"@{server}/{tool}"})
        return Action(f"mcp_{server}_{tool}", tags, dict(args), source, where, directed=True)


# --------------------------------------------------------------------------- #
# schema helpers (D20): fill a steered call's arguments without hard-coding names
# --------------------------------------------------------------------------- #


def _properties(schema: Mapping) -> list[str]:
    props = schema.get("properties") if isinstance(schema, Mapping) else None
    return list(props) if isinstance(props, Mapping) else []


def _single_property(schema: Mapping) -> str | None:
    props = _properties(schema)
    return props[0] if len(props) == 1 else None


def _args_from_task(schema: Mapping, task: str) -> dict[str, str]:
    """For each required string property named in the task text, take the word after it."""
    args: dict[str, str] = {}
    for prop in _properties(schema):
        m = re.search(rf"\b{re.escape(prop)}\b\W+(\w+)", task)
        if m is not None:
            args[prop] = m.group(1)
    return args


def _value_from_reply(reply: str, var: str) -> str:
    m = re.search(rf"^\s*{re.escape(var)}\s*[:=]\s*(\S+)", reply, re.MULTILINE)
    return m.group(1) if m is not None else ""


# --------------------------------------------------------------------------- #
# baseline config (Requirement 8.3): the gullible starting point
# --------------------------------------------------------------------------- #


def write_baseline_config(root: Path | str, mcp_server: str | None = None) -> Path:
    """Write the baseline config: no steering, no hooks, no sandbox.

    For an MCP room, one server entry with ``autoApprove: ["*"]`` (the config
    equivalent of "Always allow", so every call proceeds). A room with no MCP
    server gets no ``mcp.json``; with no server named, the interpreter applies no
    MCP gating, which is the same gullible behaviour.
    """
    import json

    root = Path(root)
    (root / ".kiro").mkdir(parents=True, exist_ok=True)
    if mcp_server is not None:
        settings = root / ".kiro/settings"
        settings.mkdir(parents=True, exist_ok=True)
        (settings / "mcp.json").write_text(
            json.dumps({"mcpServers": {mcp_server: {"autoApprove": ["*"]}}}, indent=2) + "\n",
            encoding="utf-8",
        )
    return root


def baseline_for(root: Path | str, room: str) -> Path:
    """Baseline config for ``room``: names the MCP server for an MCP room, else bare."""
    server = render.server_name(room) if room in POLTERGEIST_ROOMS else None
    return write_baseline_config(root, server)
