"""Guardrail catalogue: which threat classes select which items (design "Catalogue and grammar").

The selection uses only the eligible traps' (content source, steered effects)
and, for MCP rooms, the room's tool lists. It never uses trap IDs or trap text
(Requirement 5.1).
"""

from __future__ import annotations

from dataclasses import dataclass

from hauntlet.exorcist.grammar import Rule
from hauntlet.exorcist.model import Effect, TrapThreat

STEERING_DIR = ".kiro/steering"
HOOKS_DIR = ".kiro/hooks"
SETTINGS_DIR = ".kiro/settings"
GUARD_PATH = f"{HOOKS_DIR}/guards/credential_egress.py"
HOOK_FILE = f"{HOOKS_DIR}/credential-egress.json"
MCP_FILE = f"{SETTINGS_DIR}/mcp.json"
SANDBOX_FILE = f"{SETTINGS_DIR}/sandbox.json"

#: Which Kiro surfaces honour each kind, from the verified table in requirements.md.
SURFACES = {
    "steering": "IDE, CLI and Web read workspace steering; CLI V1/V2 load only inclusion: always files",
    "hook": "IDE and CLI (PreToolUse); Web sessions do not run hooks",
    "mcp": "IDE and CLI: workspace .kiro/settings/mcp.json, merged over the user file",
    "sandbox": (
        "IDE 1.3+ and CLI 2.31+ local V3 sessions; covers shell commands and, with mcpSandboxing, "
        "stdio MCP servers; not built-in file tools or web fetch"
    ),
}

#: The steering file each rule goes in, with that file's title. Rules render in this order.
STEERING_FILES: tuple[tuple[str, str, tuple[Rule, ...]], ...] = (
    ("untrusted-content.md", "Untrusted content", (Rule.DATA, Rule.REPORT)),
    ("credentials.md", "Credentials", (Rule.SECRETS,)),
    (
        "unrequested-actions.md",
        "Unrequested actions",
        (Rule.LINKS, Rule.FILES, Rule.TOOLS, Rule.ECHO, Rule.FORMS),
    ),
)


@dataclass(frozen=True)
class SteeringSelect:
    """A steering rule and the effects that select it (``None``: any eligible trap)."""

    rule: Rule
    effects: frozenset[Effect] | None
    reason: str
    assumptions: tuple[str, ...] = ()

    def selects(self, threat: TrapThreat) -> bool:
        return self.effects is None or bool(threat.effects & self.effects)


def selects(effects: frozenset[Effect], threat: TrapThreat) -> bool:
    return bool(threat.effects & effects)


_E = Effect

STEERING: tuple[SteeringSelect, ...] = (
    SteeringSelect(
        Rule.DATA,
        None,
        "Instructions arrived inside content the agent read; that content should be treated as data.",
    ),
    SteeringSelect(
        Rule.REPORT,
        None,
        "The agent should tell the user where an injected instruction was instead of quietly following it.",
    ),
    SteeringSelect(
        Rule.SECRETS,
        frozenset({_E.SECRET_SEND}),
        "A planted credential was, or could have been, sent out; credential values should not leave the session.",
        ("A4",),
    ),
    SteeringSelect(
        Rule.LINKS,
        frozenset({_E.NETWORK_FETCH, _E.SECRET_SEND}),
        "Content asked the agent to open a link the user's request did not need.",
    ),
    SteeringSelect(
        Rule.FILES,
        frozenset({_E.FILE_WRITE}),
        "Content asked the agent to create or change a file the user's request did not need.",
    ),
    SteeringSelect(
        Rule.TOOLS,
        frozenset({_E.TOOL_CALL}),
        "Content asked the agent to call a tool the user's request did not need.",
    ),
    SteeringSelect(
        Rule.ECHO,
        frozenset({_E.ECHO}),
        "Content asked the agent to repeat a phrase back to the user.",
    ),
    SteeringSelect(
        Rule.FORMS,
        frozenset({_E.FORM_SUBMIT}),
        "Content asked the agent to submit a web form the user did not ask for.",
    ),
)

#: The credential-egress hook is selected by these effects (design "Catalogue").
EGRESS_EFFECTS = frozenset({_E.SECRET_SEND, _E.FILE_WRITE})
EGRESS_REASON = (
    "A planted credential could leave through a web fetch, an MCP call, a shell command or a file "
    "write; this guard blocks any such call whose input carries a credential-like environment value."
)
#: (hook name, matcher) per entry, in file order. Matchers are documented selectors (tags).
EGRESS_HOOKS: tuple[tuple[str, str], ...] = (
    ("credential-egress-web", "web"),
    ("credential-egress-mcp", "@mcp"),
    ("credential-egress-shell", "shell"),
    ("credential-egress-write", "write"),
)
EGRESS_TIMEOUT_SECS = 5

#: The sandbox is selected by these effects.
SANDBOX_EFFECTS = frozenset({_E.NETWORK_FETCH, _E.SECRET_SEND})
SANDBOX_REASON = (
    "Content asked for an outbound request; the sandbox blocks outbound network from shell commands "
    "(and stdio MCP servers when mcpSandboxing is on). It does not cover web fetch or file tools."
)

MCP_AUTOAPPROVE_REASON = (
    "No tool skips approval: a tool's description can change after it was approved, so every call asks."
)
MCP_DISABLED_REASON = "Tools the task does not need are hidden from the agent, so content cannot steer a call to them."

#: Permission-suggestion selection.
PERMS_FETCH_EFFECTS = frozenset({_E.NETWORK_FETCH, _E.SECRET_SEND})
PERMS_WRITE_EFFECTS = frozenset({_E.FILE_WRITE})
PERMS_TOOL_EFFECTS = frozenset({_E.TOOL_CALL})
