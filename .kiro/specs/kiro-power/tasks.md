# Implementation Plan — kiro-power

## Overview

Build the power from design.md: tests first (they define the format), then the
manifest, the four skills, the README section, and a manual import check.

Nothing under `src/`, `scripts/`, `.kiro/steering/`, `.kiro/hooks/` or
`.kiro/settings/` changes (Requirement 12.1). Nothing is committed.

## Tasks

- [x] 1. Write `tests/test_power.py` (fails until tasks 2 to 4 land)
  - [x] 1.1 Manifest checks
    - Parse `power/plugin.json`; exact keys and values of Requirement 1.2; no key outside the schema's properties; `author` keys ⊆ `name`, `email`, `url`; `version`, `description`, `author`, `keywords` present; `license` equals the license named on `LICENSE`'s first line ("MIT License" → `MIT`); `name` matches the schema pattern and is 1 to 64 characters; no `POWER.md`
    - _Requirements: 1.1–1.5, 11.1, 11.2_
  - [x] 1.2 Skill format checks
    - The set of `power/skills/*/` equals the four names; each `SKILL.md` has frontmatter with exactly `name` and `description` (parsed by hand between the first two `---` lines, no new dependency); `name` equals the directory and matches `^[a-z0-9]+(?:-[a-z0-9]+)*$`, ≤ 64; `description` 1 to 1024 characters; under 500 lines; every `references/…` path named in a `SKILL.md` exists
    - No file named `mcp.json` anywhere under `power/`
    - _Requirements: 2.1–2.5, 3.1, 11.3, 11.4_
  - [x] 1.3 Command drift
    - The extractor of design.md "Command extraction" (code spans, shell blocks with continuations, JSON `args`); each command parses with `build_parser()`; `--room` values in `default_rooms()`, and not `parlor` for `exorcist demo`; at least one command per skill
    - The `run-range` room list (the table in `references/rooms-and-levels.md`) equals `default_rooms()`
    - _Requirements: 5.2, 11.5, 11.6_
  - [x] 1.4 Content scanner
    - The table in design.md "Content scanner" over every file under `power/`
    - _Requirements: 9.2, 9.4, 9.6, 11.7_
  - [x] 1.5 Negative cases
    - The bad inputs listed in design.md, each caught by the same function the real check uses
    - _Requirements: 11.8_

- [x] 2. `power/plugin.json`
  - Exactly the manifest in design.md "Manifest"
  - _Requirements: 1.1–1.5_

- [x] 3. Skills
  - [x] 3.1 `power/skills/run-range/` — `SKILL.md`, `references/rooms-and-levels.md`, `references/safety.md`
    - Before you start (uv check, install form, range directory, env), selftest, rooms and levels, `run`, open the report, anchors note
    - _Requirements: 2, 4, 5, 9_
  - [x] 3.2 `power/skills/exorcist/` — `SKILL.md`, `references/reading-a-bundle.md`
    - Demo path with the demo-agent sentence; real-client `generate` / `delta`; showing the bundle; ask-before-apply; scratch-only for after runs
    - _Requirements: 2, 6, 9_
  - [x] 3.3 `power/skills/test-my-mcp-client/` — `SKILL.md`, `references/scratch-workspace.md`, `references/transcript-format.md`
    - Poltergeist rooms; Cursed Repo redirect; serve, run ID only, scratch checks, `mcp.json` (both install forms), refusal fallback, user steps, finalize, cleanup
    - _Requirements: 2, 3.3, 7, 9_
  - [x] 3.4 `power/skills/test-my-browser-agent/` — `SKILL.md`
    - Parlor run, `parlor open`, localhost only, scratch-only config, finalize with perception, cleanup
    - _Requirements: 2, 8, 9_

- [x] 4. README "Kiro Power" section
  - Install (folder import of `power/`; GitHub import once public, saying the power is in `power/`), one line per skill, the no-MCP-server line. No other section changes
  - _Requirements: 10.1, 10.2_

- [x] 5. Checkpoint
  - `uv run pytest` (report the count, and that `tests/test_power.py` passes), `uv run hauntlet selftest`, `uv run python scripts/check_payload_safety.py`
  - `git status --short` shows only `power/`, `tests/test_power.py`, `README.md` and `.kiro/specs/kiro-power/`
  - Stop and report

- [ ] 6. Manual dry run of the commands (no Kiro import yet)
  - In a temp range directory, run each skill's commands by hand with the local form: `selftest`, one `run`, one `exorcist demo`, and the real-client steps up to writing the scratch `mcp.json` (no client session). Confirm the scratch checks reject the user's workspace and `~/.kiro`, and that no file appears in the repository working tree outside `reports/` and `.hauntlet/`
  - Report anything a skill says that the CLI does not do

- [ ] 7. Manual gate: import into Kiro (maintainer)
  - Powers panel → Add Custom Power → Import power from a folder → `power/`; check that the details view shows the manifest's description, author, keywords and repository link
  - In a fresh chat, "run Hauntlet on my agent" activates the power and starts `run-range`
  - Walk `test-my-mcp-client` once with Poltergeist in a scratch window; confirm nothing was written to the user's workspace `.kiro/` or `~/.kiro/`
  - Record whether Kiro allowed the agent to write the scratch `mcp.json` (fact 4)
  - Folder import only: the repository stays private until 2026-12-04. The GitHub-import URL form that selects `power/` (Q4) is checked after it is public, and the README line updated then
  - _Requirements: 12.4_

## Notes

- Every test task is required.
- Task 5 is a stop. Tasks 6 and 7 come after the maintainer's go-ahead.
- If a skill needs a command the CLI lacks, stop and raise it. Do not add it
  (Requirement 12.1, decision P4).

## Task Dependency Graph

Tasks 1.1 to 1.5 all write `tests/test_power.py`, so they run in separate
waves. Tasks 2, 3.x and 4 write separate files and can run alongside 1.1.
Task 5 needs every earlier task; tasks 6 and 7 wait for the maintainer's
go-ahead after task 5.

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2", "3.1", "3.2", "3.3", "3.4", "4"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["1.4"] },
    { "id": 4, "tasks": ["1.5"] },
    { "id": 5, "tasks": ["5"] },
    { "id": 6, "tasks": ["6"] },
    { "id": 7, "tasks": ["7"] }
  ]
}
```
