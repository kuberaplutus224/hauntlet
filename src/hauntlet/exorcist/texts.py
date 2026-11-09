"""Fixed texts the bundle manifest and delta reports must carry verbatim.

- ``CANNOT_FIX`` is the "What configuration cannot fix" list from requirements.md.
- ``ASSUMPTIONS`` holds A1–A5 (requirements A1–A3, design A4–A5).

Client limits use only the approved general wording (Requirement 15). No text
here describes any privately disclosed finding.
"""

from __future__ import annotations

CANNOT_FIX: tuple[tuple[str, str], ...] = (
    (
        "Some client behaviours are out of reach of config.",
        "How a client handles approvals is decided by the client. The most a bundle can do for an "
        "MCP server is: leave `autoApprove` empty, recommend not choosing \"Always allow\" for that "
        "server, and disable tools the task does not need.",
    ),
    (
        "Steering is advisory.",
        "The model reads it and may still follow an injected instruction. A steering item is never "
        "described as enforcing anything.",
    ),
    (
        "The sandbox does not cover built-in tools.",
        "By assumption A2, `sandbox.json` does not stop built-in file writes or web fetches.",
    ),
    (
        "Hooks gate tool calls, not content.",
        "No documented hook can remove text from a page, file or tool result before the model reads it.",
    ),
    (
        "A host allow-list cannot separate same-origin traps.",
        "In the range, task pages and trap canaries share one origin (`/c/<token>`). A host rule that "
        "allows the task allows the trap.",
    ),
    (
        "A bundle loads only when the workspace is trusted.",
        "In an untrusted IDE or interactive CLI workspace, Kiro does not load steering or MCP config.",
    ),
)

ASSUMPTIONS: dict[str, str] = {
    "A1": (
        "`autoApprove` and `disabledTools` entry form. Kiro's MCP configuration page calls the "
        "entries \"tool names\"; its MCP security page's example lists `mcp_<server>_<tool>` IDs. "
        "This bundle uses plain tool names. Check that they took effect: the disabled tools are "
        "absent from Kiro's MCP panel for the server, and other tools still prompt."
    ),
    "A2": (
        "Built-in web fetch and the sandbox. The sandbox page does not list the built-in web fetch "
        "tool as covered, so no sandbox item is credited with blocking it."
    ),
    "A3": (
        "Loopback under `DEFAULT_BLOCKED`. The docs do not say whether `DEFAULT_BLOCKED` blocks "
        "loopback (127.0.0.1). A local range's canary endpoint is on loopback. Unverified."
    ),
    "A4": (
        "Hook commands inherit Kiro's environment. The hook pages say the command runs in the "
        "project root with event JSON on stdin; they do not say which environment variables it "
        "gets. The credential-egress guard (and the SECRETS rule's effect in the demo) relies on "
        "seeing the agent's environment. Unverified on Kiro."
    ),
    "A5": (
        "A sandboxed stdio MCP server can still write its own scratch workspace. If, with "
        "`mcpSandboxing` on, the range's server cannot write its fact log, the after run is "
        "reported as not exercised, never as clean."
    ),
}

#: Requirement 4.6: what the demo environment is, per kind of room.
MCP_ENV_NOTE = (
    "The demo agent's environment is empty in an MCP room, as a real MCP client's is "
    "(Requirement 8.9), so the credential-egress guard and the SECRETS rule change nothing here: "
    "any change comes from steering and the MCP config (disabledTools, and the empty autoApprove, "
    "under which every demo-agent MCP call asks and the demo treats an ask as a deny)."
)
FILE_ROOM_ENV_NOTE = (
    "The demo agent's environment holds this room's dummy keys, as a coding agent's shell would "
    "(Requirement 8.9), so a change here attributed to the credential-egress guard or the SECRETS "
    "rule depends on assumption A4 (whether Kiro passes its environment to hook commands)."
)
#: Both sentences, for the bundle manifest, which is not tied to one room.
DEMO_ENV_NOTE = MCP_ENV_NOTE + " " + FILE_ROOM_ENV_NOTE

DEMO_LABEL = (
    "Re-run by Hauntlet's demo agent: a scripted agent with no model, reading the generated config "
    "through Hauntlet's interpreter. This is not Kiro, and it says nothing about any model."
)
REAL_CLIENT_LABEL = (
    "Re-run by a real client, declared by the tester. Hauntlet did not observe which client ran or "
    "whether the bundle was loaded."
)
PENDING_LABEL = (
    "Not re-run yet. This shows what the bundle addresses in the before run; apply the bundle and "
    "attach an after run to see the delta."
)
