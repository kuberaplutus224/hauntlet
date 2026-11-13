# Safety rules for the Hauntlet power

The power follows the Hauntlet repository's `.kiro/steering/safety-rules.md`.
These are the rules every Hauntlet skill applies.

1. **Dummy secrets only, shown truncated.** Every planted credential is a
   non-functional dummy. Show it only as `HAUNTLET-DUMMY-…`. Cut any longer
   value in command output to that before showing it. Canary links show as
   `/c/<token>` in prose.
2. **Never show the run-creation response.** `POST /runs` returns the run's
   canary URLs and dummy secrets. Pipe it through the run-ID filter in the
   skills, so only the run ID reaches the chat.
3. **This machine only.** Every URL is on `127.0.0.1` or `localhost`. Do not
   name, fetch or suggest any other host, and do not suggest a tunnel.
4. **Range directory, not the user's workspace.** Commands run in the range
   directory (a Hauntlet checkout or `~/hauntlet-range/`), because they write
   hostile room files under the directory they run in.
5. **Hostile servers only in a scratch client workspace.** A room's MCP
   server, or any config that points a client at a room, goes only into a new
   empty directory made for one run. Never into the user's workspace
   `.kiro/settings/mcp.json`, never into `~/.kiro`, even if asked. The power
   itself bundles no MCP server: a power's servers start whenever the power is
   active, and a room server there would plant a trap in the user's own Kiro.
6. **No workarounds.** If Kiro refuses a write to a `.kiro/settings/` file,
   show the user the path and content to create by hand. Do not retry through
   the shell or another tool.
7. **Ask first.** Ask before deleting a directory, writing into the user's
   workspace or `~/.kiro`, applying guardrails anywhere outside a scratch
   client workspace, or stopping a process you did not start.
8. **Client behaviour.** The only statement about any client's behaviour is:
   some client behaviours are out of reach of config. Make no other claim
   about any client.
