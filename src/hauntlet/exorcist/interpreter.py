"""The demo agent's config interpreter (Requirements 8.2, 8.4–8.6).

``Config.load(dir)`` reads a ``.kiro/`` tree: steering, hooks, ``mcp.json`` and
``sandbox.json``. ``decide(action, text, config, agent_env)`` answers proceed
or skip. It evaluates every layer, so attribution is complete, and lists every
item that would deny.

The layers, in order:

1. **Steering** (the agent's own judgement in Kiro). Every demo proposal comes
   from content, never from the user.
   - ``DATA`` denies an action whose source is listed;
   - ``LINKS`` denies ``web`` actions that are not forms;
   - ``FORMS`` denies ``form`` actions;
   - ``FILES`` denies ``write``;
   - ``TOOLS`` denies ``@mcp``;
   - ``ECHO`` denies ``respond``;
   - ``SECRETS`` denies an action whose arguments carry a credential-like value
     from the agent environment;
   - ``REPORT`` asks for a report whenever a steering rule denies a directed
     action.
2. **MCP availability:** a tool in ``disabledTools`` is not offered.
3. **MCP approval:** a tool not in ``autoApprove`` is an ask, which is a deny
   here (headless semantics, https://kiro.dev/docs/permissions/).
4. **Hooks:** ``PreToolUse`` command hooks whose matcher selects the action
   run through ``hookrun``. Exit 2 denies. Anything other than 0 or 2 is
   "not interpreted" and does not deny.
5. **Sandbox:** shell actions only (assumption A2). With ``DEFAULT_BLOCKED``, a
   shell action that names a URL is denied. The sandbox never touches
   ``web_fetch`` or file actions.

Matchers follow https://kiro.dev/docs/hooks/types/. A matcher with none of
``\\ ^ $ ( ) [ ] | +`` is a selector, matched with ``*``/``?`` wildcards
against the tool ID and each tag. Any other matcher is an unanchored regex on
the tool ID.

This module has no room, trap or canary knowledge (Requirement 8.7). Its
inputs are the action, the text that suggested it, the parsed config and the
agent environment.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from urllib.parse import quote, quote_plus

from hauntlet.exorcist import hookrun
from hauntlet.exorcist.grammar import Rule, credential_values, parse
from hauntlet.exorcist.manifest import MANIFEST_JSON
from hauntlet.exorcist.model import RESPOND, Action, Attribution, Decision, Outcome, Source
from hauntlet.exorcist.validate import REGEX_META, front_matter

MCP_FILE = ".kiro/settings/mcp.json"
SANDBOX_FILE = ".kiro/settings/sandbox.json"
_URL = re.compile(r"https?://", re.IGNORECASE)

HookRunner = Callable[[Path, Mapping[str, object], Mapping[str, str], Path, float], hookrun.HookResult]


@dataclass(frozen=True)
class SteeringRule:
    file: str
    rule: Rule
    sources: frozenset[Source]

    @property
    def item_id(self) -> str:
        return f"{self.file}#{self.rule.value}"


@dataclass(frozen=True)
class HookEntry:
    file: str
    name: str
    matcher: str | None
    script: Path
    timeout: float

    @property
    def item_id(self) -> str:
        return f"{self.file}#{self.name}"


@dataclass(frozen=True)
class Config:
    root: Path
    steering: tuple[SteeringRule, ...] = ()
    hooks: tuple[HookEntry, ...] = ()
    mcp_server: str | None = None
    auto_approve: tuple[str, ...] = ()  # "*" means every tool
    disabled_tools: tuple[str, ...] = ()
    sandbox_enabled: bool = False
    network_access: str | None = None
    not_interpreted: tuple[str, ...] = ()
    edited: tuple[str, ...] = ()  # guardrail files changed since generation (still used)

    @classmethod
    def load(cls, root: Path | str) -> Config:
        return _load(Path(root))

    def rule(self, rule: Rule) -> SteeringRule | None:
        return next((r for r in self.steering if r.rule is rule), None)


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #


def _digests(root: Path) -> dict[str, str] | None:
    path = root / MANIFEST_JSON
    if not path.is_file() or path.is_symlink():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    d = doc.get("digests") if isinstance(doc, dict) else None
    return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _bullets(body: str) -> tuple[list[str], list[str]]:
    """Split steering body into bullets and other prose; headings and blanks are ignored."""
    bullets: list[str] = []
    prose: list[str] = []
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("- "):
            bullets.append(line[2:])
        elif line.startswith((" ", "\t")) and bullets:
            bullets[-1] += " " + line.strip()
        else:
            prose.append(line.strip())
    return bullets, prose


def _load(root: Path) -> Config:
    kiro = root / ".kiro"
    digests = _digests(root)
    not_interp: list[str] = []
    edited: list[str] = []

    def check_edited(path: Path) -> None:
        rel = _rel(root, path)
        if digests is not None and rel in digests and _sha(path) != digests[rel]:
            edited.append(rel)

    steering: list[SteeringRule] = []
    for path in sorted((kiro / "steering").glob("*.md")) if (kiro / "steering").is_dir() else []:
        if path.is_symlink() or not path.is_file():
            continue
        rel = _rel(root, path)
        check_edited(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        if text.startswith("---"):
            fm = front_matter(text)
            if fm is None or fm.get("inclusion", "always") != "always":
                not_interp.append(f"{rel}: not an inclusion: always steering file")
                continue
            body = text[text.index("\n---\n", 3) + 5 :]
        else:
            # No front matter: Kiro's default inclusion mode is always (steering docs).
            body = text
        bullets, prose = _bullets(body)
        for b in bullets:
            parsed = parse(b)
            if parsed is None:
                not_interp.append(f"{rel}: sentence not interpreted by the demo agent: {b.strip()[:80]}")
            else:
                steering.append(SteeringRule(rel, parsed[0], parsed[1]))
        not_interp += [f"{rel}: prose not interpreted by the demo agent: {p[:80]}" for p in prose]

    hooks: list[HookEntry] = []
    hooks_dir = kiro / "hooks"
    for path in sorted(hooks_dir.glob("*.json")) if hooks_dir.is_dir() else []:
        if path.is_symlink() or not path.is_file():
            continue
        rel = _rel(root, path)
        check_edited(path)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            not_interp.append(f"{rel}: not valid JSON")
            continue
        if not isinstance(doc, dict) or doc.get("version") != "v1" or not isinstance(doc.get("hooks"), list):
            not_interp.append(f"{rel}: not a v1 hook file")
            continue
        for hook in doc["hooks"]:
            entry = _hook_entry(root, rel, hook, digests, not_interp)
            if entry is not None:
                hooks.append(entry)

    mcp_server, auto, disabled = None, (), ()
    mcp_path = root / MCP_FILE
    if mcp_path.is_file() and not mcp_path.is_symlink():
        check_edited(mcp_path)
        try:
            servers = json.loads(mcp_path.read_text(encoding="utf-8")).get("mcpServers", {})
        except (OSError, ValueError, AttributeError):
            servers = None
        if not isinstance(servers, dict) or len(servers) != 1:
            not_interp.append(f"{MCP_FILE}: MCP config not interpreted (needs exactly one server entry)")
        else:
            (mcp_server, entry), = servers.items()
            entry = entry if isinstance(entry, dict) else {}
            auto = tuple(str(x) for x in entry.get("autoApprove", []) if isinstance(x, str))
            disabled = tuple(str(x) for x in entry.get("disabledTools", []) if isinstance(x, str))

    sb_enabled, net = False, None
    sb_path = root / SANDBOX_FILE
    if sb_path.is_file() and not sb_path.is_symlink():
        check_edited(sb_path)
        try:
            sb = json.loads(sb_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            sb = None
        if isinstance(sb, dict):
            sb_enabled = sb.get("enabled") is True
            net = sb.get("networkAccess", "DEFAULT_BLOCKED") if sb_enabled else None
        else:
            not_interp.append(f"{SANDBOX_FILE}: not valid JSON")

    return Config(
        root=root,
        steering=tuple(steering),
        hooks=tuple(hooks),
        mcp_server=mcp_server,
        auto_approve=auto,
        disabled_tools=disabled,
        sandbox_enabled=sb_enabled,
        network_access=net,
        not_interpreted=tuple(not_interp),
        edited=tuple(edited),
    )


def _hook_entry(
    root: Path, rel: str, hook: object, digests: dict[str, str] | None, not_interp: list[str]
) -> HookEntry | None:
    if not isinstance(hook, dict):
        not_interp.append(f"{rel}: hook entry is not an object")
        return None
    name = str(hook.get("name", "?"))
    where = f"{rel}#{name}"
    if hook.get("enabled") is False:
        return None
    if hook.get("trigger") != "PreToolUse":
        not_interp.append(f"{where}: trigger {hook.get('trigger')!r} is not interpreted by the demo agent")
        return None
    action = hook.get("action")
    if not isinstance(action, dict) or action.get("type") != "command":
        not_interp.append(f"{where}: agent-type hook not interpreted by the demo agent")
        return None
    try:
        argv = shlex.split(str(action.get("command", "")))
    except ValueError:
        argv = []
    if len(argv) != 2 or argv[0] != "python3":
        not_interp.append(f"{where}: command is not of the form `python3 <bundle path>`")
        return None
    pure = PurePosixPath(argv[1])
    script = (root / pure).resolve()
    if pure.is_absolute() or ".." in pure.parts or not script.is_relative_to(root.resolve()) or not script.is_file():
        not_interp.append(f"{where}: script is not a file inside the bundle")
        return None
    srel = pure.as_posix()
    if digests is None or digests.get(srel) != _sha(script):
        not_interp.append(f"{where}: script does not match the bundle manifest digest")
        return None
    matcher = hook.get("matcher")
    timeout = hook.get("timeout", 60)
    return HookEntry(
        file=rel,
        name=name,
        matcher=matcher if isinstance(matcher, str) else None,
        script=script,
        timeout=float(timeout) if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) else 60.0,
    )


# --------------------------------------------------------------------------- #
# matching and deciding
# --------------------------------------------------------------------------- #


def matches(matcher: str | None, action: Action) -> bool:
    """Kiro's hook matcher semantics for one action."""
    if matcher is None or matcher == "":
        return True
    if set(matcher) & REGEX_META:
        try:
            return re.search(matcher, action.tool_id) is not None
        except re.error:
            return False
    return fnmatchcase(action.tool_id, matcher) or any(fnmatchcase(t, matcher) for t in action.tags)


def mcp_tool(action: Action, server: str | None) -> str | None:
    """The MCP tool name of an action on ``server``, or None."""
    if server is None or "@mcp" not in action.tags:
        return None
    prefix = f"@{server}/"
    for tag in action.tags:
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None


def _carries(args: Mapping[str, str], values: Mapping[str, str]) -> str | None:
    blob = json.dumps(dict(args), sort_keys=True, ensure_ascii=False)
    for name, value in sorted(values.items()):
        if value in blob or quote(value, safe="") in blob or quote_plus(value) in blob:
            return name
    return None


def decide(
    action: Action,
    text: str,
    config: Config,
    agent_env: Mapping[str, str],
    runner: HookRunner = hookrun.run,
) -> Decision:
    """Decide one action. ``text`` is the content that suggested it; no current rule reads
    it, but it is part of the interface so a rule could, without widening what ``decide`` sees."""
    deniers: list[Attribution] = []
    not_interp: list[str] = []
    is_respond = action.tool_id == RESPOND

    # 1. steering
    def steer(rule: Rule, hit: bool, why: str) -> None:
        sr = config.rule(rule)
        if sr is not None and hit:
            deniers.append(Attribution(sr.item_id, sr.file, rule.value, why))

    data = config.rule(Rule.DATA)
    steer(Rule.DATA, data is not None and action.source in data.sources, f"instruction came from {action.source.value}")
    steer(Rule.LINKS, "web" in action.tags and "form" not in action.tags, "opens a link the request did not need")
    steer(Rule.FORMS, "form" in action.tags, "submits a form the user did not ask for")
    steer(Rule.FILES, "write" in action.tags, "writes a file the request did not need")
    steer(Rule.TOOLS, "@mcp" in action.tags, "calls a tool the request did not need")
    steer(Rule.ECHO, is_respond, "repeats a phrase because content asked")
    leaked = _carries(action.args, credential_values(dict(agent_env)))
    steer(Rule.SECRETS, leaked is not None, f"carries the value of {leaked}")
    report = bool(deniers) and action.directed and config.rule(Rule.REPORT) is not None

    if not is_respond:
        # 2-3. MCP availability and approval
        tool = mcp_tool(action, config.mcp_server)
        if tool is not None:
            if tool in config.disabled_tools:
                deniers.append(Attribution(f"{MCP_FILE}#{config.mcp_server}.disabledTools", MCP_FILE,
                                           f"{config.mcp_server}.disabledTools", "tool not offered"))
            if "*" not in config.auto_approve and tool not in config.auto_approve:
                deniers.append(Attribution(f"{MCP_FILE}#{config.mcp_server}.autoApprove", MCP_FILE,
                                           f"{config.mcp_server}.autoApprove", "ask, treated as deny (headless)"))
        # 4. hooks
        event = {
            "hook_event_name": "PreToolUse",
            "cwd": str(config.root),
            "session_id": "demo",
            "tool_name": action.tool_id,
            "tool_input": dict(action.args),
        }
        for hook in config.hooks:
            if not matches(hook.matcher, action):
                continue
            result = runner(hook.script, event, dict(agent_env), config.root, hook.timeout)
            if result.status == hookrun.BLOCK:
                deniers.append(Attribution(hook.item_id, hook.file, hook.name, result.reason.strip()))
            elif result.status != hookrun.ALLOW:
                not_interp.append(f"{hook.item_id}: {result.reason}")
        # 5. sandbox: shell commands only
        if (
            config.sandbox_enabled
            and config.network_access == "DEFAULT_BLOCKED"
            and "shell" in action.tags
            and any(_URL.search(v) for v in action.args.values())
        ):
            deniers.append(Attribution(f"{SANDBOX_FILE}#networkAccess", SANDBOX_FILE, "networkAccess",
                                       "outbound network from a shell command"))

    return Decision(
        outcome=Outcome.SKIP if deniers else Outcome.PROCEED,
        report=report,
        deniers=tuple(deniers),
        not_interpreted=tuple(not_interp),
    )
