"""Validate guardrail files before anything is written (Requirement 2.7).

Checks each file against the formats verified in the Kiro docs, plus the
bundle's own limits:

- only the file kinds Requirement 2.1 allows;
- no key outside those named in Requirements 2.3 and 2.4;
- no loosening value (Requirement 6.4).

A failure raises ``BundleInvalid(path, rule)``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

#: Documented PascalCase hook triggers (https://kiro.dev/docs/hooks/types/).
HOOK_TRIGGERS = frozenset(
    {
        "UserPromptSubmit", "Stop", "SessionStart", "SessionEnd", "PreCompact",
        "PostCompact", "PreToolUse", "PostToolUse", "PostFileCreate", "PostFileSave",
        "PostFileDelete", "PreTaskExec", "PostTaskExec",
    }
)
HOOK_KEYS = frozenset({"name", "description", "trigger", "matcher", "action", "timeout", "enabled", "confirm"})
MCP_ENTRY_KEYS = frozenset({"command", "args", "env", "disabled", "autoApprove", "disabledTools"})
SANDBOX_KEYS = frozenset({"enabled", "networkAccess", "mcpSandboxing"})
#: Characters that make a matcher a regex rather than a selector (hook triggers page).
REGEX_META = set("\\^$()[]|+")

_ALLOWED = (
    re.compile(r"^\.kiro/steering/[a-z0-9-]+\.md$"),
    re.compile(r"^\.kiro/hooks/[a-z0-9-]+\.json$"),
    re.compile(r"^\.kiro/hooks/guards/[a-z0-9_]+\.py$"),
    re.compile(r"^\.kiro/settings/mcp\.json$"),
    re.compile(r"^\.kiro/settings/sandbox\.json$"),
)
_SERVER_NAME = re.compile(r"^[a-z0-9_]+$")


class BundleInvalid(ValueError):
    def __init__(self, path: str, rule: str) -> None:
        super().__init__(f"{path}: {rule}")
        self.path = path
        self.rule = rule


def validate(files: Mapping[str, bytes]) -> None:
    for path in sorted(files):
        if not any(rx.match(path) for rx in _ALLOWED):
            raise BundleInvalid(path, "not a file kind the bundle may contain (Requirement 2.1)")
        data = files[path]
        if path.startswith(".kiro/steering/"):
            _steering(path, data)
        elif path.startswith(".kiro/hooks/guards/"):
            _guard(path, data)
        elif path.startswith(".kiro/hooks/"):
            _hooks(path, data)
        elif path.endswith("mcp.json"):
            _mcp(path, data)
        else:
            _sandbox(path, data)


def _text(path: str, data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise BundleInvalid(path, "not UTF-8") from None


def _json(path: str, data: bytes) -> object:
    try:
        return json.loads(_text(path, data))
    except ValueError:
        raise BundleInvalid(path, "not valid JSON") from None


def front_matter(text: str) -> dict[str, str] | None:
    """The leading ``---`` block as key/value pairs, or ``None`` if it is not first."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 3)
    if end < 0:
        return None
    out: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            return None
        out[key.strip()] = value.strip()
    return out


def _steering(path: str, data: bytes) -> None:
    fm = front_matter(_text(path, data))
    if fm is None:
        raise BundleInvalid(path, "front matter must be the very first content")
    if fm.get("inclusion") != "always":
        raise BundleInvalid(path, "front matter must say inclusion: always")


def _guard(path: str, data: bytes) -> None:
    try:
        compile(_text(path, data), path, "exec")
    except SyntaxError as exc:
        raise BundleInvalid(path, f"guard script does not compile: {exc.msg}") from None


def matcher_ok(matcher: str) -> bool:
    if not (set(matcher) & REGEX_META):
        return bool(matcher.strip())
    try:
        re.compile(matcher)
    except re.error:
        return False
    return True


def _hooks(path: str, data: bytes) -> None:
    doc = _json(path, data)
    if not isinstance(doc, dict) or set(doc) != {"version", "hooks"}:
        raise BundleInvalid(path, "a hook file has exactly version and hooks")
    if doc["version"] != "v1" or not isinstance(doc["hooks"], list) or not doc["hooks"]:
        raise BundleInvalid(path, 'version must be "v1" and hooks a non-empty array')
    for hook in doc["hooks"]:
        if not isinstance(hook, dict) or not set(hook) <= HOOK_KEYS:
            raise BundleInvalid(path, "hook has an undocumented key")
        if not isinstance(hook.get("name"), str) or not hook["name"]:
            raise BundleInvalid(path, "hook needs a name")
        if hook.get("trigger") not in HOOK_TRIGGERS:
            raise BundleInvalid(path, f"unknown trigger {hook.get('trigger')!r}")
        if "matcher" in hook and not (isinstance(hook["matcher"], str) and matcher_ok(hook["matcher"])):
            raise BundleInvalid(path, f"matcher {hook.get('matcher')!r} is neither a selector nor a regex")
        action = hook.get("action")
        if not isinstance(action, dict) or action.get("type") not in ("command", "agent"):
            raise BundleInvalid(path, "action.type must be command or agent")
        field = "command" if action["type"] == "command" else "prompt"
        if not isinstance(action.get(field), str) or not action[field] or set(action) != {"type", field}:
            raise BundleInvalid(path, f"a {action['type']} action needs exactly type and {field}")
        timeout = hook.get("timeout", 60)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 0:
            raise BundleInvalid(path, "timeout must be a whole number of seconds, 0 or more")


def _mcp(path: str, data: bytes) -> None:
    doc = _json(path, data)
    if not isinstance(doc, dict) or set(doc) != {"mcpServers"} or not isinstance(doc["mcpServers"], dict):
        raise BundleInvalid(path, "mcp.json has exactly mcpServers")
    for name, entry in doc["mcpServers"].items():
        if not _SERVER_NAME.match(name):
            raise BundleInvalid(path, f"server name {name!r} must use only [a-z0-9_]")
        if not isinstance(entry, dict) or not set(entry) <= MCP_ENTRY_KEYS:
            raise BundleInvalid(path, f"{name}: only {sorted(MCP_ENTRY_KEYS)} are allowed")
        if entry.get("disabled") is True:
            raise BundleInvalid(path, f"{name}: the room server must not be disabled")
        for key in ("autoApprove", "disabledTools"):
            value = entry.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                raise BundleInvalid(path, f"{name}.{key} must be a list of tool names")
        if entry.get("autoApprove", []) != []:
            raise BundleInvalid(
                path,
                f"{name}.autoApprove must be empty: a tool's description can change after approval",
            )


def _sandbox(path: str, data: bytes) -> None:
    doc = _json(path, data)
    if not isinstance(doc, dict) or not set(doc) <= SANDBOX_KEYS:
        raise BundleInvalid(path, f"sandbox.json may contain only {sorted(SANDBOX_KEYS)}")
    if doc.get("enabled") is not True:
        raise BundleInvalid(path, "enabled must be true")
    if doc.get("networkAccess") != "DEFAULT_BLOCKED":
        raise BundleInvalid(path, "networkAccess must be DEFAULT_BLOCKED")
    if "mcpSandboxing" in doc and not isinstance(doc["mcpSandboxing"], bool):
        raise BundleInvalid(path, "mcpSandboxing must be true or false")
