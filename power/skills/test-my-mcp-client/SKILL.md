---
name: test-my-mcp-client
description: Test the user's own MCP client, for example their Kiro, against Hauntlet's Poltergeist room in real-client mode, using a throwaway scratch workspace, then finalize the run and open the report. Use when the user says "test my MCP client", "test my Kiro", "run Poltergeist on my client", or asks for a real-client Hauntlet run. Covers poltergeist and poltergeist-legacy; Cursed Repo has no real-client mode yet.
---

# Test your own MCP client (Poltergeist)

Poltergeist is an MCP server that does a real task and also carries traps:
a tool description that changes after the client approved it, and a tool
return value with an instruction in it. In real-client mode, the user's own
client launches the server, does the task, and Hauntlet scores what happened.

## Safety (read first)

This power follows the Hauntlet repository's `.kiro/steering/safety-rules.md`
(summary in `../run-range/references/safety.md`; paths are relative to this
SKILL.md). For this skill:

- **The room server goes only into a new scratch client workspace.** Never
  write it into the user's workspace `.kiro/settings/mcp.json` or into
  `~/.kiro/settings/mcp.json`, even if the user asks. Explain why: a room
  server is hostile by design, and wired into their own Kiro it would be a
  trap in the setup they want to protect. Offer the scratch workspace instead.
- Never show the run-creation response; keep only the run ID.
- Show dummy secrets only as `HAUNTLET-DUMMY-…`.
- Everything runs on `127.0.0.1`. Name no other host.
- If Kiro refuses a write to a `.kiro/settings/` file, show the user the path
  and content to create by hand. Do not retry through the shell or another
  tool.
- Ask before deleting anything, and before stopping a process you did not
  start.
- Some client behaviours are out of reach of config. Say only that; make no
  other claim about any client.

## Before you start

Use the install form, range directory and environment chosen in the
`run-range` skill ("Before you start"). If none has been chosen this session,
do those steps first. Commands below are written short, starting with the word `hauntlet`; run
them in the full form, in the range directory.

Ask which room: `poltergeist` (current protocol) or `poltergeist-legacy`
(older protocol revisions). If the user asks for Cursed Repo, say that Cursed
Repo has no real-client mode yet, and offer instead
`hauntlet run --room cursed-repo --agent naive` (the `run-range` skill) and
`hauntlet exorcist demo --room cursed-repo` (the `exorcist` skill).

## Step 1: Start the range

`hauntlet serve` keeps running. Start it as a background process if you can,
with the range directory as working directory and both variables set;
otherwise ask the user to run it in a terminal and give them the full command.

```sh
hauntlet serve
```

Wait until this succeeds:

```sh
curl -fsS http://127.0.0.1:8666/health
```

## Step 2: Create a run

The response holds the run's canary URLs and dummy secrets, so print only the
run ID:

```sh
curl -fsS -X POST http://127.0.0.1:8666/runs \
  -H 'Content-Type: application/json' \
  -d '{"rooms": ["poltergeist"], "ttl_seconds": 3600}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["run"]["run_id"])'
```

Use `"poltergeist-legacy"` in `rooms` for the legacy room. Call the printed ID
`RUN_ID`. Always write it as `--run=RUN_ID`, with `=`: run IDs can start with
`-`.

## Step 3: Make the scratch client workspace

```sh
mktemp -d "${TMPDIR:-/tmp}/hauntlet-client-XXXXXX"
```

Check the printed path, resolved to an absolute path, before writing anything
(`references/scratch-workspace.md`, in the `references/` folder next to this
SKILL.md). It must be empty, and must not be the
user's workspace or inside it, inside `~/.kiro`, or inside the range
directory. If any check fails, stop and write nothing.

## Step 4: Wire the room server into the scratch workspace only

Write `<scratch>/.kiro/settings/mcp.json` with the entry for the install form
in use, from `references/scratch-workspace.md`. The server entry runs:

```sh
hauntlet mcp serve --room poltergeist --run=RUN_ID
```

or, for the legacy room:

```sh
hauntlet mcp serve --room poltergeist-legacy --run=RUN_ID
```

`HAUNTLET_DB` in its `env` must be the same absolute path the range uses.

Try the write once with your normal file tool. If Kiro refuses it, show the
user the path and the JSON and ask them to create the file. Do not retry
another way.

## Step 5: The user runs the task

Tell the user:

1. Open the scratch folder in a **new Kiro window** (File → New Window, then
   open the folder) and trust it.
2. In that window's MCP panel, the `hauntlet_poltergeist` server starts. Its
   log shows the workspace path and, after `give the client this task:`, the
   task text. A line `took over from an earlier session that never listed or
   called tools` is normal: some clients start the server once briefly before
   the real connection. If the log shows `refused, serving nothing: …`, tell
   the user that line and stop: the run is not active or the database path
   does not match.
3. Approve the server's tools when asked, give the agent the task text from
   the log unchanged, and let it work. Do not invent or reword the task.
4. Come back to this chat when the agent is done.

Do not take part in the task yourself. This chat only sets up and finalizes.

## Step 6: Finalize

Offer to save the agent's conversation as `<scratch>/transcript.jsonl`
(format: `references/transcript-format.md`, in the `references/` folder next
to this SKILL.md). Without it, L2 Echoed and Detected are not assessed.

With a transcript, from the range directory:

```sh
hauntlet mcp finalize --run=RUN_ID --transcript=FILE
```

Without one:

```sh
hauntlet mcp finalize --run=RUN_ID
```

`FILE` is the transcript's absolute path. Show the printed level lines,
truncating any dummy secret to `HAUNTLET-DUMMY-…`, and open the `report:`
path with `open` (macOS) or `xdg-open` (Linux), or give the absolute path.

The run stays provisional for a short grace window, so late canary hits still
count. The report says so.

## Step 7: Clean up

1. Remove the `hauntlet_poltergeist` (or `hauntlet_poltergeist_legacy`) entry
   from `<scratch>/.kiro/settings/mcp.json`. If it was the only entry, remove
   the file. If Kiro refuses, ask the user to do it.
2. Ask before deleting the scratch folder itself.
3. Offer to stop `hauntlet serve` if you started it.

## Next

Offer the `exorcist` skill: it can generate guardrails from this run once the
grace window has closed, and set up an after run in a new scratch workspace.
