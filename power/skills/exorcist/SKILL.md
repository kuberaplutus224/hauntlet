---
name: exorcist
description: Generate the Kiro guardrails (steering files, a credential-egress hook, an MCP allow-list with disabled tools, and a sandbox config) that close the gaps a Hauntlet run found, and show the before/after delta. Use when the user asks how to fix what Hauntlet found, wants to see the Exorcist demo, or wants guardrails for a finalized real-client run. Never applies anything to the user's workspace without asking.
---

# The Exorcist

The Exorcist turns a Hauntlet run into Kiro guardrails that would have stopped
each trap that fired, re-runs the room, and shows the before/after delta per
trap. There are two paths. Always say which one produced a result.

## Safety (read first)

This power follows the Hauntlet repository's `.kiro/steering/safety-rules.md`
(summary in `skills/run-range/references/safety.md`). For this skill:

- Show dummy secrets only as `HAUNTLET-DUMMY-…`.
- Everything runs on `127.0.0.1`. Name no other host.
- Never copy, merge or write a bundle file into the user's workspace or
  `~/.kiro` unless the user asks for it in this session. Then show the target
  paths and contents first, never overwrite an existing file, and show a merge
  instead.
- An after run with the user's own client uses a new scratch client workspace,
  never the user's workspace (see the `test-my-mcp-client` skill).
- Ask before deleting anything.
- Some client behaviours are out of reach of config. Say only that; make no
  other claim about any client.

## Before you start

Use the install form, range directory and environment chosen in the
`run-range` skill ("Before you start"). If none has been chosen this session,
do those steps first. Commands below are written short, starting with the word `hauntlet`; run
them in the full form, in the range directory.

## Path 1: the demo agent (no setup)

Ask for a room. Every room except `parlor` is supported: `threshold`,
`cursed-repo`, `cursed-repo-tests`, `poltergeist`, `poltergeist-legacy`.

```sh
hauntlet exorcist demo --room cursed-repo
```

For Poltergeist:

```sh
hauntlet exorcist demo --room poltergeist
```

The command prints `bundle:`, `delta:`, `report:` and a line like
`poltergeist: before worst=L4 … -> after worst=L0 detected=True …`.

Show the user:

1. the before → after line, as "before L4 Exposed, after L0 Clean, Detected";
2. this sentence, every time: **"The demo agent is scripted and uses no
   model. It is not Kiro, and it says nothing about any model."**;
3. the guardrails (see "Show the guardrails");
4. the report: open the `report:` path with `open` (macOS) or `xdg-open`
   (Linux), or give the absolute path.

## Path 2: the user's own client (real-client run)

This needs a finalized real-client run, made with the `test-my-mcp-client`
skill (Poltergeist rooms) or the `test-my-browser-agent` skill (Parlor). Then:

1. Generate the bundle:

   ```sh
   hauntlet exorcist generate --run=RUN_ID
   ```

   It prints `bundle:`, `manual steps:` (the bundle's `EXORCISM.md`) and the
   `delta` command to run later, with the bundle ID. If it refuses because the
   run is still provisional, show the refusal and say to retry once the
   grace window has closed. If it refuses for another reason, show the
   reason and stop.

2. Show the guardrails (below).

3. Ask the user whether to do an after run. If yes, follow the same skill as
   the before run with a **new** run and a **new** scratch client workspace,
   and apply the bundle there, as its `EXORCISM.md` "Manual steps" say:
   - copy the bundle's `.kiro/steering/` and `.kiro/hooks/` into the scratch
     client workspace;
   - build its `.kiro/settings/mcp.json` from the bundle's entry, as in
     `references/reading-a-bundle.md` ("Filling in the bundle's MCP entry");
   - copy `.kiro/settings/sandbox.json` if the bundle has one;
   - tell the user the remaining manual steps in `EXORCISM.md` (approvals,
     saved permission rules, trusting the workspace). They are the user's to
     do, in their Kiro window.

4. After the after run is finalized, attach it:

   ```sh
   hauntlet exorcist delta --bundle BUNDLE_ID --after AFTER_RUN_ID
   ```

   Show the printed `path:` line (it says the after result came from a real
   client, declared by the tester) and open the `report:` path.

## Show the guardrails

Read the bundle directory printed as `bundle:` and show, in this order, with
each file's content (details in `references/reading-a-bundle.md`):

1. steering files: `.kiro/steering/*.md` (advisory: the model reads them);
2. hooks: `.kiro/hooks/*.json` and the guard script they run (enforced);
3. the MCP allow-list: `.kiro/settings/mcp.json`, its `disabledTools` and its
   empty `autoApprove` (enforced);
4. `.kiro/settings/sandbox.json`, if present (enforced, for shell commands and
   stdio MCP servers);
5. the "What configuration cannot fix" section of `EXORCISM.md`.

Label each file Advisory or Enforced, as above. Do not claim a steering file
enforces anything.

## Applying to the user's own workspace

Only if the user asks for it in this session:

1. List each target path in the user's workspace and show the content.
2. For any file that already exists, show the merge you propose. Never
   overwrite it.
3. Kiro may refuse an agent write to `.kiro/settings/` files. If it does, show
   the path and content for the user to create by hand. Do not retry through
   the shell or another tool.
4. Never include a Hauntlet room server entry in the user's own `mcp.json`.
   Only the guardrails (steering, hooks, sandbox, and `disabledTools` /
   `autoApprove` settings for servers the user already has) belong there.
