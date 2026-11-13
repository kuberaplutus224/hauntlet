# Design Document — kiro-power

## Overview

The power is a directory of static files: one manifest and four skills. It
adds no Python code to the package. The only code is `tests/test_power.py`,
which checks the files against the manifest schema, the skill format, the CLI
and the safety rules.

## Architecture

Three parts, none of them new runtime code:

1. **The power** (`power/`): a manifest Kiro reads to show and activate the
   power, and four skills Kiro loads into the agent's context on demand.
2. **The existing CLI** (`hauntlet …`, from `src/hauntlet/cli.py`): the only
   thing the skills run. The power never calls the package any other way.
3. **The guard test** (`tests/test_power.py`): reads `power/` as text, checks
   it against the CLI parser and the room registry, and scans it for safety
   rule violations.

At run time the agent following a skill touches four places, and only these:

| Place | Written by | Holds |
|---|---|---|
| Range directory (checkout or `~/hauntlet-range/`) | the `hauntlet` CLI | event store, room scratch files, reports, Exorcist bundles |
| Scratch client workspace (`mktemp -d`) | the agent (or the user, if Kiro refuses) | the room server entry, an applied bundle, a transcript |
| User's workspace and `~/.kiro` | nobody, unless the user asks in the session (`exorcist` only) | guardrails only, never a room server |
| `127.0.0.1:8666` | `hauntlet serve` | the range's HTTP API, canary endpoint and Parlor pages |

```
power/
├── plugin.json
└── skills/
    ├── run-range/
    │   ├── SKILL.md
    │   └── references/
    │       ├── rooms-and-levels.md
    │       └── safety.md
    ├── exorcist/
    │   ├── SKILL.md
    │   └── references/
    │       └── reading-a-bundle.md
    ├── test-my-mcp-client/
    │   ├── SKILL.md
    │   └── references/
    │       ├── scratch-workspace.md
    │       └── transcript-format.md
    └── test-my-browser-agent/
        └── SKILL.md
```

`references/safety.md` exists once, in `run-range`. Every skill also carries
its own short safety section inline, because a skill may be loaded alone; the
others point to `skills/run-range/references/safety.md` for the full list.
Cross-skill references (`transcript-format.md`, `scratch-workspace.md`) use
paths relative to the power root, and the guard test checks they exist.

### Format, checked against current docs (2026-11-12)

- kiro.dev/docs/powers/create/ (page updated 2026-10-08): a power needs
  `plugin.json`; `skills/` and `mcp.json` are optional; required manifest
  fields listed are `$schema`, `name`, `version`, `description`, `author`
  (with at least `name`), `keywords`; optional `homepage`, `repository`,
  `license`. Keywords trigger activation.
- agent-plugins.org/schemas/1.0.0/plugin.schema.json: required `$schema` and
  `name`; `name` pattern `^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$`,
  1 to 64 characters; `additionalProperties: false`; `author` has only
  `name`, `email`, `url`.
- kiro.dev/docs/powers/installation/ (page updated 2026-10-23): Add Custom
  Power → Import power from a folder / Import power from GitHub; "A single
  repository can contain multiple powers, each in its own directory." In the
  Agent Plugins format, a power's MCP servers "activate and deactivate with the
  power".
- Skill frontmatter: `name` (matches the directory, lowercase and hyphens) and
  `description` (at most 1024 characters), per the brief and the Agent Skills
  format Kiro uses.

## Data Models

The power has no runtime data of its own. These are the file shapes it
defines or depends on.

### Manifest (`power/plugin.json`)

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "hauntlet",
  "version": "0.1.0",
  "description": "Run Hauntlet, a local test range for AI agents, against your own agent: it plants known, published prompt-injection traps, scores what the agent did from L0 Clean to L4 Exposed, and generates Kiro guardrails (steering, hooks, MCP allow-list, sandbox) that close the gaps.",
  "author": { "name": "kuberaplutus224" },
  "keywords": ["hauntlet", "agent security", "prompt injection", "mcp", "red team", "guardrails", "canary", "haunted"],
  "homepage": "https://github.com/kuberaplutus224/hauntlet",
  "repository": "https://github.com/kuberaplutus224/hauntlet",
  "license": "MIT"
}
```

"run Hauntlet on my agent" contains the keyword `hauntlet`, so it activates
the power.

### Skill frontmatter (`power/skills/<name>/SKILL.md`)

```yaml
---
name: <directory name>        # ^[a-z0-9]+(?:-[a-z0-9]+)*$, at most 64 characters
description: <one line>       # 1 to 1024 characters: what the skill does and when to use it
---
```

Exactly these two keys, each on one line. The test parses them by hand (no
YAML dependency).

### Scratch server entry (`<scratch>/.kiro/settings/mcp.json`)

One `mcpServers` entry named `hauntlet_<room>` (`-` as `_`, the name the
Exorcist bundle uses), whose `args` end in
`hauntlet mcp serve --room <room> --run=<run id>`, with `env` holding the
absolute `HAUNTLET_DB` and `HAUNTLET_BASE_URL=http://127.0.0.1:8666`. Both
install forms are in `skills/test-my-mcp-client/references/scratch-workspace.md`.

### Extracted command (test only)

`(source text, argv)`: the Markdown span or line a command came from, and the
argument list after `hauntlet`, as `build_parser().parse_args` takes it.

## Components and Interfaces

### Shared conventions in every skill

#### Install form and range directory (Requirement 4)

Each skill starts with a "Before you start" block:

1. `uv --version`. If missing: tell the user to install uv, stop.
2. Pick the install form once per session. In the commands, `hauntlet` means:
   - local checkout: `uv run hauntlet`, run in the checkout;
   - no checkout: `uvx --from git+https://github.com/kuberaplutus224/hauntlet hauntlet`.
3. Pick the range directory: the checkout, or `~/hauntlet-range/`. Check it
   is not the user's workspace or inside it (unless the workspace is the
   checkout). Create it after telling the user.
4. Every command runs with `cwd` = range directory and
   `HAUNTLET_DB=<range dir>/.hauntlet/range.db` (absolute);
   `HAUNTLET_BASE_URL=http://127.0.0.1:8666` for `serve`, `mcp serve`,
   `parlor open`, `run`, `selftest` and `exorcist demo`.

Reason (fact 2 in requirements.md): `cli._scratch()` writes room materials to
`./.hauntlet/scratch/`. Running from the user's workspace would put a cursed
repository where the user's own agent works.

#### Writing the commands

Commands are written as `hauntlet <subcommand> …` with concrete room names and
uppercase placeholders (`RUN_ID`, `BUNDLE_ID`, `AFTER_RUN_ID`, `FILE`), always
`--run=RUN_ID` with `=`. No `[optional]` brackets and no `<room>` inside a
command: optional flags are shown as two separate commands, and the room is
named in the sentence ("for Poltergeist legacy, use `--room
poltergeist-legacy`" is written as the full command). This keeps every command
parseable (Requirement 11.5).

#### Showing output

- Show the level lines and the `report:` path that the command prints.
- Before showing any output, replace every `HAUNTLET-DUMMY-` value with
  `HAUNTLET-DUMMY-…`.
- Never show the `POST /runs` response. The run is created with:

  ```sh
  curl -fsS -X POST http://127.0.0.1:8666/runs \
    -H 'Content-Type: application/json' \
    -d '{"rooms": ["poltergeist"], "ttl_seconds": 3600}' \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["run"]["run_id"])'
  ```

  so only the run ID reaches the agent's context (fact 3).
- Open reports with `open` (macOS) or `xdg-open` (Linux); otherwise give the
  absolute path.

#### Long-running server

`hauntlet serve` blocks. The skill starts it as a background process when the
agent has a tool for that, with the range directory as working directory and
the two environment variables; otherwise it asks the user to run it in a
terminal and gives the exact command. Readiness: `curl -fsS
http://127.0.0.1:8666/health`. At the end the skill offers to stop the server
it started, and never stops one it did not start without asking.

#### Safety section (every SKILL.md)

A short block, before the first command:

- Follows the Hauntlet repository's `.kiro/steering/safety-rules.md`.
- Dummy secrets only, shown as `HAUNTLET-DUMMY-…`.
- Everything runs on this machine: `127.0.0.1` only. No other host.
- Hostile servers go only into a new scratch client workspace, never into
  your workspace or `~/.kiro`.
- Ask before deleting anything or writing into your workspace or `~/.kiro`.
- Some client behaviours are out of reach of config.

### Skill: `run-range`

Steps: Before you start → `hauntlet selftest` (show its last line) → show
rooms and levels (from `references/rooms-and-levels.md`) → ask room and agent
(default `threshold`, `naive`) → `hauntlet run --room threshold --agent naive`
(and the `hardened` variant) → show level lines → open the report → explain
that the reference agents are anchors (naive high, hardened L0 + Detected) →
suggest `exorcist`, `test-my-mcp-client` or `test-my-browser-agent`.

Room table (`references/rooms-and-levels.md`), one line each:

| Room | Tests | Real-client skill |
|---|---|---|
| `threshold` | coding agents (one-trap stub) | none |
| `cursed-repo` | coding agents (README, agents guide, comment, config, issue note) | none |
| `cursed-repo-tests` | coding agents (trap in the failing test) | none |
| `poltergeist` | MCP clients (changed tool description, tool return value) | `test-my-mcp-client` |
| `poltergeist-legacy` | MCP clients on older protocol revisions | `test-my-mcp-client` |
| `parlor` | browser agents (visible, hidden, ARIA, title, image text) | `test-my-browser-agent` |

Levels: the five one-liners of Requirement 5.3, plus Detected and controls.

### Skill: `exorcist`

Two paths, said plainly each time:

- **Demo path:** `hauntlet exorcist demo --room cursed-repo` (or any room
  except `parlor`). Show the `<room>: before worst=… -> after worst=…` line,
  the bundle path and the report. Always add: "The demo agent is scripted and
  uses no model. It is not Kiro, and it says nothing about any model."
- **Your own client:** after a finalized real-client run from
  `test-my-mcp-client`: `hauntlet exorcist generate --run=RUN_ID` → read the
  bundle → apply it to a **new** scratch client workspace per its
  `EXORCISM.md` → the user runs the after run (same skill, new run ID) →
  `hauntlet exorcist delta --bundle BUNDLE_ID --after AFTER_RUN_ID`.

Showing the guardrails (`references/reading-a-bundle.md`): list the bundle's
`.kiro/steering/*.md`, `.kiro/hooks/*.json`, `.kiro/settings/mcp.json`
(allow-list, disabled tools) and `.kiro/settings/sandbox.json`; show each
file's content, then `EXORCISM.md`'s "what configuration cannot fix" part.

Applying: default target is the scratch client workspace of the after run.
The user's workspace only on an explicit request in this session; then show
paths and contents first, never overwrite, show a merge for existing files.

### Skill: `test-my-mcp-client`

1. Before you start; ask `poltergeist` or `poltergeist-legacy`. For Cursed
   Repo: say it has no real-client mode yet and offer `run-range` or the
   Exorcist demo.
2. Start `hauntlet serve`; wait for `/health`.
3. Create the run (command above); keep `RUN_ID`.
4. Create the scratch client workspace and check it
   (`references/scratch-workspace.md`):

   ```sh
   mktemp -d "${TMPDIR:-/tmp}/hauntlet-client-XXXXXX"
   ```

   The resolved path must not be the user's workspace or inside it, not
   inside `~/.kiro`, not inside the range directory, and must be empty.
5. Write `<scratch>/.kiro/settings/mcp.json`. No-checkout form:

   ```json
   {
     "mcpServers": {
       "hauntlet_poltergeist": {
         "command": "uvx",
         "args": ["--from", "git+https://github.com/kuberaplutus224/hauntlet",
                  "hauntlet", "mcp", "serve", "--room", "poltergeist", "--run=RUN_ID"],
         "env": {
           "HAUNTLET_DB": "/absolute/path/to/range/.hauntlet/range.db",
           "HAUNTLET_BASE_URL": "http://127.0.0.1:8666"
         }
       }
     }
   }
   ```

   Checkout form: `"command": "uv"`, `"args": ["run", "--directory",
   "/absolute/path/to/checkout", "hauntlet", "mcp", "serve", …]`. If Kiro
   refuses the write: show path and JSON, ask the user to create it, do not
   retry another way (fact 4).
6. Tell the user: open the scratch folder in a new Kiro window, trust it,
   approve the `hauntlet_poltergeist` tools, and give the agent the task text
   the server printed in its MCP log. If the server log says `refused,
   serving nothing: …`, show that line and stop.
7. When the user is done: offer to save the transcript as
   `<scratch>/transcript.jsonl` (format in `references/transcript-format.md`).
   Then, from the range directory, either
   `hauntlet mcp finalize --run=RUN_ID --transcript=FILE` or
   `hauntlet mcp finalize --run=RUN_ID`. Show level lines; open the report.
8. Clean up: remove the `hauntlet_poltergeist` entry (or the file, if it was
   the only entry); ask before deleting the scratch folder; offer to stop the
   server. Point to `exorcist`.

### Skill: `test-my-browser-agent`

1. Before you start; start `hauntlet serve`; create a run for `["parlor"]`.
2. `hauntlet parlor open --run=RUN_ID`; show the printed task and say: give
   it to the browser agent unchanged.
3. Say the pages are on `127.0.0.1` only; the browser agent must run on this
   machine. No tunnel, no other host.
4. If the browser agent is set up through Kiro config (for example a browser
   MCP server), that config goes only into a new scratch client workspace,
   with the same checks as `test-my-mcp-client` step 4.
5. When done: offer a transcript; ask how the agent reads pages; run one of
   `hauntlet parlor finalize --run=RUN_ID --transcript=FILE --perception=dom_text`
   (with `raw_html`, `vision` or `not_recorded` as the user says) or without
   `--transcript`. Show level lines; open the report.
6. Clean up as in `test-my-mcp-client` step 8.

### Command extraction (`tests/test_power.py`)

Sources: every `*.md` under `power/skills/`.

1. **Inline code spans and fenced code blocks.** Each span, and each line of a
   `sh`/`bash`/`text` block (with `\` continuations joined), is a candidate.
   Strip leading `VAR=value` assignments. A candidate is a command if, after
   stripping an optional prefix `uv run ` or
   `uvx --from git+https://github.com/kuberaplutus224/hauntlet `, it starts
   with the word `hauntlet` followed by a space. A lone `hauntlet` (no
   subcommand) is not a command.
2. **JSON blocks.** In a `json` fenced block that parses, every `args` list
   that contains `"hauntlet"` gives the command formed by the items after it.
   Blocks with `/absolute/path/...` placeholders still parse as JSON.
3. Each command is split with `shlex.split` and passed to
   `build_parser().parse_args(argv)`. `SystemExit` fails the test with the
   file and the command. The parser's `func` is never called.
4. For `run`, `exorcist demo` and `mcp serve`, the `--room` value must be in
   `default_rooms()`, and for `exorcist demo` it must not be `parlor`.
5. At least one command must be found per skill.

Consequence for authors: every inline `hauntlet …` span is a complete
command. To mention a subcommand in prose, write it without the leading
`hauntlet` (for example "the `mcp finalize` step").

### Content scanner (`tests/test_power.py`)

Applied to every file under `power/` (UTF-8 text; a non-text file fails).

| Check | Rule |
|---|---|
| Dummy secret | every `HAUNTLET-DUMMY-` is followed by `…` (U+2026) |
| Marker and token | every `hauntlet-mark-` is followed by `…`; every `/c/` is followed by `<token>` or `…` |
| URLs | find `[a-z][a-z0-9+.-]*://\S+` (trailing punctuation trimmed). Allowed: host `127.0.0.1` or `localhost` (any port, path); exactly `https://github.com/kuberaplutus224/hauntlet` with optional `git+` prefix and optional `.git`; exactly the schema URL. Anything else fails |
| Bare domains | after removing allowed URLs, no `\b[a-z0-9-]+(\.[a-z0-9-]+)*\.(com|org|net|io|dev|ai|app|co|xyz|me)\b` (case-insensitive). `sh` is not in the list, so file names like `install.sh` pass (review 2026-11-12) |
| Approved wording | every `SKILL.md` contains "Some client behaviours are out of reach of config" (case-insensitive) |

Negative cases (Requirement 11.8) feed the same functions short strings: a
full dummy secret, `https://example.org/x`, a bare `evil.com`, `hauntlet mcp serve --room cursed-repo --run=X` (bad choice),
`hauntlet run --room nope` (unknown room), and a frontmatter name that differs
from its directory.

## Correctness Properties

Each property is checked by `tests/test_power.py` over every file in the power
(the inputs are a fixed set of files, so these are exhaustive checks, not
Hypothesis properties). Each one has negative cases that prove the check
catches a violation.

### Property 1: Manifest shape (KP1)

`plugin.json` has exactly the Requirement 1.2 values, no key outside the schema's properties, `author` keys within `name`/`email`/`url`, a `name` matching the schema pattern, and the license named in `LICENSE`.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 11.1, 11.2**

### Property 2: Skill format (KP2)

The skill set is exactly the four names; every `SKILL.md` has frontmatter with exactly `name` and `description`, `name` equal to its directory, a description of 1 to 1024 characters, and fewer than 500 lines; every `references/…` path it names exists.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 11.3**

### Property 3: No bundled server (KP3)

No `mcp.json` exists anywhere under `power/`.

**Validates: Requirements 3.1, 11.4**

### Property 4: No drift from the CLI (KP4)

For every Markdown file under `power/skills/`, every extracted `hauntlet` command parses with `build_parser()`; every `--room` names a registered room, and never `parlor` for `exorcist demo`; every skill yields at least one command.

**Validates: Requirements 11.5**

### Property 5: Room list (KP5)

The room table in `run-range` equals `default_rooms()`, with no duplicates.

**Validates: Requirements 5.2, 11.6**

### Property 6: Safe content (KP6)

For every file under `power/`: it is UTF-8 text, and the content scanner finds nothing (no full dummy secret, marker or canary token; no URL outside the allowed set; no bare domain).

**Validates: Requirements 9.2, 9.4, 9.6, 11.7**

### Property 7: Approved wording (KP7)

Every `SKILL.md` names `.kiro/steering/safety-rules.md` and contains the approved client-behaviour wording.

**Validates: Requirements 9.1, 9.6**

## Error Handling

The power has no code that can fail at run time; its error handling is what
each skill tells the agent to do when a step fails.

| Failure | What the skill does |
|---|---|
| `uv --version` fails | Tell the user to install uv; stop. Never install it. |
| `uvx --from git+…` cannot fetch (for example a private repository) | Say so; offer the local checkout. Try no other source. |
| Range directory would be the user's workspace or inside it | Stop and ask for another directory. |
| `hauntlet selftest` fails | Show the lines after `selftest FAILED`; stop. |
| `/health` never answers | Show the server's last output; ask the user to check the terminal running `hauntlet serve`. |
| Scratch path fails a check (not empty, inside the user's workspace, `~/.kiro` or the range directory) | Stop and write nothing. |
| Kiro refuses the agent's write to `.kiro/settings/mcp.json` | Show the path and JSON for the user to create. Do not retry another way. |
| Room server log shows `refused, serving nothing: …` | Show that line; stop. The run is inactive or the database path differs. |
| Room server refuses a second session | New run and new scratch workspace. |
| Browser agent runs in the cloud | Say it cannot reach `127.0.0.1`; stop. No tunnel. |
| `exorcist generate` refuses a provisional run | Show the refusal; retry after the grace window. |
| `exorcist demo --room parlor` | Not offered; the skill lists only supported rooms. |
| Any CLI command exits non-zero | Show its error line (dummy secrets truncated) and stop that skill. |

## Decisions

- **P1: no `mcp.json` in v1.** A power's MCP servers start whenever the power
  is active (installation docs: they "activate and deactivate with the
  power"). `hauntlet mcp serve` needs a `--run` ID created per run, so a
  static config cannot name a valid run, and a server that did start would be
  a hostile room server inside the user's own Kiro. That would plant a trap in
  the very setup the power is meant to protect. Room servers are written only
  into a scratch client workspace, per run.
- **P2: a range directory, never the user's workspace.** Facts 2 and 3 in
  requirements.md.
- **P3: Poltergeist only for real-client MCP.** Cursed Repo has no real-client
  mode (fact 1, Q1).
- **P4: docs-only scratch checks.** The scratch checks are instructions the
  agent follows, not a script. Alternative: a `hauntlet` helper command that
  creates the scratch workspace and writes its `mcp.json` with the checks in
  code. That would be stricter but changes the CLI, which this spec does not
  do. It is a candidate for v2.
- **P5: no write workaround.** If Kiro refuses an agent write to
  `.kiro/settings/mcp.json`, the user creates the file. The skill never
  writes it through the shell instead.
- **P6: no `--reapproval`.** It is a manual, unscored observation; the power
  leaves it unset to keep the walkthrough short. Runs record `not_recorded`
  (Q3).
- **P7: reuse the room READMEs' facts, not their text.** The skills restate
  the steps in their own words and link no external page. They cite the
  repository's room READMEs by path for detail.

## Safety

The power ships no trap content, no MCP server, and no secret. It tells the
agent to run commands that already exist and already serve hostile content
only to active runs on `127.0.0.1`. The risks it adds are about *where* things
land, and each one has a rule:

| Risk | Rule |
|---|---|
| Hostile room files in the user's workspace | range directory (P2) |
| Hostile MCP server in the user's Kiro | no `mcp.json` (P1); scratch client workspace only (Requirement 7.5, 7.6) |
| Dummy secrets on screen or in chat | run-ID-only extraction; truncation; scanner |
| External hosts | localhost only; scanner |
| Destructive cleanup | ask before deleting; only the scratch entry is removed without asking |

The stranger test from safety-rules.md: a stranger who installs the power and
says "run Hauntlet on my agent" gets reference runs in `~/hauntlet-range/`
and reports on disk. Nothing is wired into their Kiro until they ask for a
real-client test, and then only into a temp folder they open on purpose.

## Testing strategy

`tests/test_power.py`, plain pytest (no Hypothesis: the inputs are a fixed set
of files). Groups: manifest, skills format, no `mcp.json`, command drift, room
list, content scanner, negative cases. No network. It imports
`hauntlet.cli.build_parser` and `hauntlet.rooms.default_rooms` only.

Manual gate (tasks.md task 7): import `power/` into Kiro, check activation on
"run Hauntlet on my agent", and walk each skill once.

## Out of scope

- A bundled MCP server, hooks or steering inside the power.
- Any CLI or room change, including a real-client Cursed Repo.
- The hosted range: the power is local-only.
- Publishing to the Kiro powers registry.
