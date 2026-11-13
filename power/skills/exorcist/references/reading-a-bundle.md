# Reading an Exorcist bundle

A bundle is a directory printed as `bundle:`, beside the range's event store
(`<range directory>/.hauntlet/exorcist/<before run>/<bundle id>/`). The last
path part is the bundle ID used by the `exorcist delta` step.

| Path in the bundle | Kind | What to tell the user |
|---|---|---|
| `.kiro/steering/*.md` | Advisory | Rules the model reads, for example to treat fetched and file content as data. The model may still follow an injected instruction. |
| `.kiro/hooks/*.json` | Enforced | A hook that checks tool calls for planted credentials before they run. |
| `.kiro/hooks/guards/*.py` | Enforced (support file) | The script the hook runs. It needs `python3` on `PATH`. |
| `.kiro/settings/mcp.json` (MCP rooms only) | Enforced | The room's server entry with `disabledTools` (tools the task does not need) and an empty `autoApprove`. |
| `.kiro/settings/sandbox.json` | Enforced | `{"enabled": true, "networkAccess": …}`. Covers shell commands and, with `mcpSandboxing`, stdio MCP servers. |
| `EXORCISM.md` | Manual | Which traps each item addresses, what configuration cannot fix, assumptions, and the manual steps for a real-client after run. |
| `bundle.json` | Data | Machine-readable manifest. Not for the user's workspace. |
| `deltas/`, `evidence/` | Data | Delta reports and redacted evidence. Not for the user's workspace. |

Only `.kiro/` content is ever copied anywhere, and only into a scratch client
workspace or, if the user asks, the user's workspace.

## Filling in the bundle's MCP entry

The bundle's `mcp.json` names the server `hauntlet_poltergeist` (or
`hauntlet_poltergeist_legacy`) and leaves four placeholders:
`<hauntlet-checkout>`, `<after-run-id>`, `<path-to-range-db>` and
`<range-base-url>`. For the after run's scratch client workspace:

- keep the server name, `disabledTools` and the empty `autoApprove` exactly;
- set `HAUNTLET_DB` to the absolute range database path and
  `HAUNTLET_BASE_URL` to `http://127.0.0.1:8666`;
- replace `"--run", "<after-run-id>"` with the single item
  `"--run=AFTER_RUN_ID"`, because run IDs can start with `-`;
- with a local checkout, keep `"command": "uv"` and put the checkout's
  absolute path in place of `<hauntlet-checkout>`;
- with no checkout, use the `command` and `args` from
  `../../test-my-mcp-client/references/scratch-workspace.md` (relative to
  this file) instead, with
  the after run's ID.

The resulting server command must still be the `mcp serve` subcommand for the
same room, for example:

```json
{"args": ["--directory", "/absolute/path/to/checkout", "run", "hauntlet", "mcp", "serve", "--room", "poltergeist", "--run=AFTER_RUN_ID"]}
```
