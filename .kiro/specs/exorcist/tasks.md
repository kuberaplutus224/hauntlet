# Implementation Plan — exorcist

## Overview

Build the Exorcist from design.md in the order below.

1. **Small changes outside the package.** The approved changes that sit outside
   `src/hauntlet/exorcist/` come first: D20 (client schema accessor), D19 (fact
   log copy at `mcp finalize`) and D18 (wording). A checkpoint follows that
   requires every existing test and an unchanged `hauntlet selftest`.
2. **Threat profiles.** The D15 profiles for every registered room.
3. **Generator.** The pure modules (eligibility, grammar, catalogue,
   generate/render, validate) with their properties, then the writer and the
   bundle manifest (checkpoint).
4. **Interpreter and hook runner** (checkpoint).
5. **Demo agent.** Its tests include the empty-environment rule from the design
   review.
6. **Demo flow, delta and goldens.** The goldens are pinned only after the
   actual results are compared with design.md's prediction table (checkpoint).
7. **CLI**, then the **hosted routes** (checkpoint each).
8. **Room READMEs and the final checkpoint.**

The permitted changes outside `src/hauntlet/exorcist/` and
`src/hauntlet/agents/demo.py` are exactly those in requirements 14.1 (a)–(h).
**No module in `src/hauntlet/core/` changes.** Any other change found while
building is a new numbered proposal (D21+) and stops the task.

**Do-not-tune rule.** The goldens pin what the code produces. If a demo result
differs from design.md's "Expected demo results", stop at task 13.4 and report
the difference before pinning. Do not change the interpreter, the grammar or the
obedience parser to restore a predicted value.

## Tasks

- [x] 1. Approved change D20: schema accessor on the in-process client
  - [x] 1.1 Add `PoltergeistClient.input_schemas() -> dict[str, dict]`
    - `src/hauntlet/rooms/poltergeist/client.py`: `_list` also stores each listed tool's `inputSchema` (as a plain dict); `input_schemas()` returns a deep copy from the latest listing, `{}` before `approve()`
    - Nothing else in the client changes; `call`, `approve`, `relist` and `descriptions` behave as today
    - _Requirements: 14.1 (g), D20_
  - [x] 1.2 Write `tests/test_poltergeist_client_schemas.py`
    - The result equals the server's `INPUT_SCHEMAS` after `approve()` and after the post-mutation `relist()`, on `poltergeist` and `poltergeist-legacy` (both legacy revisions)
    - The result is a copy: mutating it does not change a later call
    - The naive and hardened Poltergeist goldens are unchanged
    - _Requirements: D20_

- [x] 2. Approved change D19: fact-log copy at `hauntlet mcp finalize`
  - [x] 2.1 Write the copy before teardown
    - `src/hauntlet/cli.py` `cmd_mcp_finalize`: for each Poltergeist room, after the summary and report are written and before `room.teardown`, copy `factlog.facts_path(workspace)` byte for byte to `<reports>/mcp-facts-<run_id>-<room>.jsonl`. If the copy fails, keep the workspace (same rule as other write failures) and exit non-zero
    - No other output, message or exit code changes
    - _Requirements: 10.9, 14.1 (f), D19_
  - [x] 2.2 Extend the real-client end-to-end tests
    - In `tests/test_poltergeist_real_client_e2e.py` (or a new `tests/test_mcp_finalize_facts_copy.py`): after a full session and `mcp finalize`, the copy exists and is byte-identical to the workspace log as it was at finalize time. The summary and report files are unchanged versus a run without the copy step. The workspace is still removed
    - _Requirements: D19_

- [x] 3. Approved change D18: correct the three defence claims
  - `src/hauntlet/rooms/parlor/config.py` `TrapPlacement.defence` for `sign-image` and `hidden-css`, and the matching rows in `src/hauntlet/rooms/parlor/README.md` "Defences", get the exact wording in design.md "D18 wording"
  - `src/hauntlet/rooms/poltergeist/README.md`, the fact-log tampering note: replace the sandbox sentence with the design's wording
  - Text only: no test asserts on the old wording (`grep` the tests first and stop if one does)
  - _Requirements: 14.1 (d), D18_

- [x] 4. Checkpoint: outside changes green
  - `uv run pytest` passes; `uv run hauntlet selftest` passes with output unchanged; `uv run python scripts/check_payload_safety.py` is clean; `git diff --stat src/hauntlet/core` is empty

- [x] 5. Approved change D15: threat profiles
  - [x] 5.1 Shared profile types
    - `src/hauntlet/exorcist/model.py`: `Source`, `Effect`, `TrapThreat`, `McpTools`, `RoomThreats` exactly as design.md "Data models" (frozen; `effects` non-empty, checked in `__post_init__`)
    - _Requirements: 13.1_
  - [x] 5.2 `threats.py` in each room package
    - `rooms/threshold/threats.py`, `rooms/cursed_repo/threats.py` (both configs), `rooms/poltergeist/threats.py` (both revisions), `rooms/parlor/threats.py`, with the values in design.md's D15 table
    - Poltergeist `McpTools`: `task_tools = ("list_topics", "get_note", "submit_answer")`; derive `steered_tools` and `relay_tools` from `config.TOOLS` kinds `relay`/`scratch` at import
    - `real_client_env` per design "Environment (8.9)": threshold `{"HAUNTLET_DEMO_KEY"}`; cursed-repo / cursed-repo-tests derived from `config.traps` `env_var`; Poltergeist and Parlor empty
    - Profiles import only `hauntlet.exorcist.model` and their own room's config; rooms import nothing else new
    - _Requirements: 13.1, D15_
  - [x] 5.3 Registry
    - `src/hauntlet/exorcist/profiles.py`: `profile_for(room_name) -> RoomThreats`, raising `KeyError` with the known names; the only Exorcist module that names rooms
    - _Requirements: 13.1_
  - [x] 5.4 Write `tests/test_threat_profiles.py`
    - For every room in `default_rooms()`: each non-control trap has a profile, no profile names an unknown trap or a control, and every effect set is non-empty
    - MCP rooms: `task_tools` and `steered_tools` are advertised tool names; the two sets are disjoint; `relay_tools ⊆ steered_tools`
    - _Requirements: 13.2_

- [x] 6. Generator: pure modules
  - [x] 6.1 Eligibility
    - `exorcist/eligibility.py`: `classify(score, manifest)` with the ordered rules in design.md "Eligibility"; `require_final(run, score)` raises for unknown, unfinalized or provisional runs
    - _Requirements: 1.1–1.6_
  - [x] 6.2 Property EP1
    - `tests/test_exorcist_eligibility.py`: the `runs()` strategy (design "Correctness properties") plus an independent oracle written from Requirement 1.3; classification matches; cited traps ∪ no-guardrail equals fired ∪ not-exercised; `__task__` never appears
    - _Requirements: 1.3–1.5, 4.2_
  - [x] 6.3 Grammar
    - `exorcist/grammar.py`: the eight sentence templates verbatim from design.md; source display names in enum order; `render(rule, sources)` and `parse(bullet) -> (rule, sources) | None` (whitespace-normalised); `CREDENTIAL_NAME` regex and `MIN_SECRET_LEN = 12` defined once here
    - Unit tests: `parse(render(r, s)) == (r, s)` for every rule and every non-empty source subset; near-miss sentences give `None`
    - _Requirements: 5.3, 8.4_
  - [x] 6.4 Catalogue, generate and render
    - `exorcist/catalogue.py`: the selection table in design.md "Catalogue and grammar"
    - `exorcist/generate.py`: `generate(score, manifest, profiles) -> BundleSpec`, with items and citations recorded per design. Guardrail content is computed only from eligible `(source, effects)`, MCP tool lists and server names
    - `exorcist/render.py`: steering files, `credential-egress.json`, `mcp.json` (placeholders `<after-run-id>`, `<hauntlet-checkout>`, `<path-to-range-db>`, `<range-base-url>`), `sandbox.json`, and the guard copied from `exorcist/guards/credential_egress.py`. Output is deterministic: sorted keys and lists, `\n` line ends, no timestamps
    - `exorcist/guards/credential_egress.py`: as design.md "Hooks and the guard script" (stdlib only; exits 0 or 2; names the variable, never the value)
    - _Requirements: 2.1–2.5, 5.1–5.3, 6.1, 6.4_
  - [x] 6.5 Permissions suggestion
    - In `generate`: the YAML text from design.md's rules table, with the user-level label and the "Always allow" review note; `deny` or `ask` only; each rule commented with its citations
    - _Requirements: 4.5, 7.2_
  - [x] 6.6 Validate
    - `exorcist/validate.py`: the checks in design.md "Bundle layout and writer". Raises `BundleInvalid(path, rule)`
    - _Requirements: 2.7_
  - [x] 6.7 Generator properties
    - `tests/test_exorcist_generate.py`:
      - **EP2:** steering and hook bytes are equal for runs with permuted trap IDs, fresh canaries and the same class multiset
      - **EP3:** no canary value, no `hauntlet-mark-`/`HAUNTLET-DUMMY-`, and no shared 6-gram with any file under `src/hauntlet/rooms/*/templates` or `fixtures`; steering and hooks also contain no trap ID or room name
      - **EP4:** `validate` accepts every generated bundle
      - **EP5:** a superset run keeps every item, and no loosening value appears (`"*"`, any `networkAccess` but `DEFAULT_BLOCKED`, any `allow`)
      - **EP16:** no `permissions.yaml` in the file map; suggestion only `deny`/`ask`; label present
    - Example test: `scripts/check_payload_safety.py` passes on `exorcist/guards/` and on rendered files written to a temp dir
    - _Requirements: 2.5, 2.7, 4.4, 4.5, 5.1–5.4, 6.3, 6.4_

- [x] 7. Writer and bundle manifest
  - [x] 7.1 Paths and writer
    - `exorcist/paths.py` `exorcist_root(db)`; `exorcist/writer.py` `write_bundle(root, before_run_id, spec, created_at) -> Path` with every check in design.md (ID charset, `.kiro` refusals, `mkdir(exist_ok=False)`, `O_CREAT|O_EXCL|O_NOFOLLOW`, containment after resolve); `write_delta(bundle_dir, after_run_id, files)` under the same checks
    - _Requirements: 3.1–3.4_
  - [x] 7.2 Bundle manifest
    - `bundle.json`: items, cites, classes, no-guardrail list, assumptions, SHA-256 of each `.kiro/` file, `created_at`, before run ID, schema version
    - `EXORCISM.md`: the same content for people, plus:
      - the cannot-fix list verbatim from the requirements;
      - A1–A5 next to the items that depend on them;
      - the permissions suggestion;
      - the Requirement 4.6 statement (per room: empty demo environment in Poltergeist, so the guard and `SECRETS` change nothing there; any file-room change by either cites A4) whenever either item is present;
      - the manual steps per real-client room from design.md "Manual steps for real Kiro", each citing its doc URL
    - No private-finding detail: client limits use only the approved general wording (Requirement 15)
    - _Requirements: 4.1–4.6, 7.1–7.3, 15.1, 15.2_
  - [x] 7.3 Property EP6 and manifest tests
    - `tests/test_exorcist_paths.py`, **EP6:** hostile IDs, `..`, absolute paths, pre-placed symlinks at each level, a root under a `.kiro` directory, an existing bundle directory; each is written inside the root or refused
    - Manifest tests: every guardrail file's digest matches; `EXORCISM.md` contains every cited trap, each cannot-fix item and each manual step's URL; the 4.6 statement is present exactly when the guard or `SECRETS` is
    - _Requirements: 3.1–3.3, 4.1–4.3, 4.6, 7.1_

- [x] 8. Checkpoint: generator green
  - `uv run pytest` passes (EP1–EP6, EP16 included); payload safety clean; core unchanged

- [x] 9. Interpreter and hook runner
  - [x] 9.1 Hook runner
    - `exorcist/hookrun.py`: `run(script, event, env, cwd, timeout)` exactly as design.md "Hook runner" (`sys.executable -I -B -S -c BOOT`, audit hook, cwd, env, `min(timeout, HOOK_TIMEOUT_CAP=5)`, kill on timeout, 4 KiB output cap). Returns `allow | block | not_interpreted(reason)`
    - _Requirements: 8.5_
  - [x] 9.2 Interpreter
    - `exorcist/interpreter.py`: `Config.load(dir)` and `decide(action, text, config, agent_env)` with the five layers, matcher semantics and attribution in design.md "Config interpreter". `not_interpreted` collects unparsed bullets, non-`always` steering, non-`PreToolUse` or agent-type hooks, commands not of the form `python3 <bundle path>`, guard digest mismatches, ambiguous `mcp.json`, and hook runner `not_interpreted` results
    - Edited steering and JSON files are marked "edited since generation" by digest; they are not refused
    - _Requirements: 8.2, 8.4–8.6_
  - [x] 9.3 Interpreter and hook runner tests
    - `tests/test_exorcist_hookrun.py`, **EP13:**
      - the shipped guard fed arbitrary JSON exits 0 or 2;
      - canary scripts placed in a temp bundle (and added to its digest list) that try a socket, a `subprocess` call, a file write, `os.system` and `ctypes` are each refused by the audit hook;
      - a sleeping script is killed and reported not interpreted;
      - cwd is the bundle directory, and the environment is exactly the one passed
    - `tests/test_exorcist_interpreter.py`:
      - **EP7:** random `Action`s and texts with identifier tokens substituted give the same `Decision`;
      - **EP9:** bundles of only unparseable bullets or agent-type hooks deny nothing;
      - matcher semantics: the doc's examples (`shell`, `@mcp`, `@git/git_status`, `mcp_git_*`, the anchored write regex);
      - 9.6: `sandbox.json` `DEFAULT_BLOCKED` changes no `web_fetch` or `fs_write` decision;
      - `SECRETS` with an empty agent env never denies
    - _Requirements: 6.1, 6.2, 8.2, 8.4, 8.5, 9.5, 9.6, 9.8_

- [x] 10. Checkpoint: interpreter green
  - `uv run pytest` passes; core unchanged

- [x] 11. Demo agent
  - [x] 11.1 `src/hauntlet/agents/demo.py`
    - `DemoAgent(config_dir, env_channel)`, `name = "demo"`; agent environment = `env_channel(materials)` (design "Environment (8.9)"); never calls `tools.getenv` and never reads `materials.env` itself (passes `materials` to the driver unchanged)
    - Obedience parser with the shapes in design.md's table; `directed` set only by an imperative addressed to the agent; sources set from where content was read
    - "Learning a value from content": pre-read through the instructing tool, argument from the task text by schema property name (D20 `input_schemas()`), value by `^\s*<V>\s*[:=]\s*(\S+)`
    - Every proposal goes through `interpreter.decide`; `PROCEED` executes through the same `ToolBox` or client the driver handed over; `SKIP` writes a `tool` transcript line naming the attribution; `report` decisions add the hardened-style sentence naming `action.where`
    - File rooms through `do_task(materials, tools)`; MCP rooms through `do_task(materials, tools, react)`. Any other room raises `UnsupportedRoom`, named by the room the materials carry, with no room-name literal in code
    - `_task.py` does not change
    - _Requirements: 8.1–8.4, 8.6, 8.7, 8.9_
  - [x] 11.2 Baseline config and registration (`env_channel=exorcist.profiles.real_client_env`)
    - Built-in baseline under a scratch dir: empty steering and hooks, `mcp.json` with one `hauntlet` server entry and `autoApprove: ["*"]` (only when materials name an MCP connection), no sandbox. `get_agent("demo")` returns `DemoAgent(baseline)` (`src/hauntlet/agents/__init__.py`, D17 (h))
    - _Requirements: 8.3, 8.8, 14.1 (h)_
  - [x] 11.3 Demo-agent rule tests
    - `tests/test_demo_agent_static.py` (9.1): scans `agents/demo.py`, `exorcist/interpreter.py`, `exorcist/hookrun.py`, `exorcist/grammar.py` and the guard. It fails on any registered room name, any trap ID from `default_rooms()`, `hauntlet-mark-`, `HAUNTLET-DUMMY-`, `getenv`, `.env` in `demo.py`, or an import of `hauntlet.rooms.*` (the demo agent may import `hauntlet.agents._task` only)
    - `tests/test_demo_agent_env.py` (9.9, **EP17**): every demo room × several seeds; the agent environment and every hook-runner `env` argument (captured with a stub) equal `{k: materials.env[k] for k in real_client_env}`, which is `{}` with no canary value for the Poltergeist rooms; each file room's `real_client_env` equals the env names its `setup` plants (from config); a `ToolBox` subclass records `getenv` calls (must be zero)
    - `tests/test_demo_agent_driver.py` (9.7, **EP14**): two seeds per demo room; driver writes and calls recorded through a `ToolBox` subclass and a client proxy carry no canary value and are equal once task data is masked
    - _Requirements: 8.1, 8.7, 8.9, 9.1, 9.7, 9.9_

- [x] 12. Demo flow, fact-log signal and delta
  - [x] 12.1 Fact-log reader
    - `exorcist/mcpfacts.py`: `steered_relay_calls(facts, mcp)`. Loaders: the demo workspace (`<scratch>/<room>-<run_id>`, with a test that this matches `cli.mcp_workspace`), and `<reports>/mcp-facts-<run>-<room>.jsonl` (D19). Uses `factlog.read`, so malformed and foreign-run records are skipped
    - _Requirements: 1.2, 10.9_
  - [x] 12.2 Delta model and report
    - `exorcist/delta.py`: `admit` (the four 10.6 checks, first failure named) and `classify_change` with the ordered rules in design.md; `steered-call-no-canary` from 12.1; "fact log not available" when no source exists
    - `exorcist/report.py`: `.json`, `.html` (own template, `html.escape` on every value) and `.txt` in the design's section order. The first line is the path label; the Costs section lists task regressions and new false positives. Demo-path notes cover the inert sandbox, ungated task tools and the 4.6 statement. Before and after autopsy reports are linked through the existing `render_report`. The word "fixed" never appears
    - _Requirements: 7.5, 10.1–10.9, 4.6_
  - [x] 12.3 Delta properties
    - `tests/test_exorcist_delta.py`:
      - **EP10:** every format holds every before trap's level and signals, with or without an after run; "not exercised after" is never improved; a higher level is always marked a regression;
      - **EP11:** first line by path;
      - **EP12:** admission holds iff all four checks hold;
      - **EP15:** synthetic fact logs × after scores
    - _Requirements: 10.1–10.6, 10.9_
  - [x] 12.4 `ExorcistService.demo`
    - `exorcist/service.py`: the four steps in design.md "Demo flow" (`run_once(..., keep_workspace=True)`, fact-log read, teardown through `service.context` + `room.teardown`, generate → validate → write, after run, admit, delta). Refuses unsupported rooms. `generate(run_id)` and `attach(bundle_id, after_run_id)` share the same pieces
    - _Requirements: 8.3, 10.6, 11.1, 12.1–12.3_

- [x] 13. Goldens and causality (demo rooms: threshold, cursed-repo, cursed-repo-tests, poltergeist, poltergeist-legacy)
  - [x] 13.1 Run each demo room once and record the actual results
    - Before and after: worst level, Detected, task, false positives, per-trap levels, attributions
  - [x] 13.2 Check Requirement 8.3
    - Before is L3 or above in every hosted demo room (`cursed-repo`, `poltergeist`). If not, stop and report; do not tune
  - [x] 13.3 Write `tests/test_demo_agent_causality.py`
    - **EP8:** every outcome that differs from the baseline has an attribution. For each attributed item, a bundle with only that item removed restores the baseline outcome of the actions attributed to it alone. Removed means: a hook entry or steering bullet deleted; for an MCP key (`disabledTools`, `autoApprove`), the key reverted to its baseline value (`autoApprove: ["*"]`), because an absent `autoApprove` still makes every call ask. Digests are updated. Check 9.3 alongside
    - Assert that no Poltergeist after-change is attributed to `credential-egress` or `SECRETS`, and that every file-room attribution to either cites A4 in the report and manifest (4.6)
    - _Requirements: 4.6, 8.6, 9.3, 9.4_
  - [x] 13.4 Compare with design.md "Expected demo results"
    - If any value differs, **stop and report** the table of predicted vs actual to the user before writing goldens. Do not change code to match
  - [x] 13.5 Pin the goldens
    - `tests/test_demo_agent_golden.py` (9.2): per demo room, the action trace and per-trap levels under the baseline and under the generated bundle
    - `tests/test_exorcist_repo_kiro_untouched.py` (3.5): hash the repository's `.kiro/` tree, run `ExorcistService.demo` for one file room and one MCP room, and hash again; the hashes are equal
    - _Requirements: 3.5, 9.2_

- [x] 14. Checkpoint: demo loop green
  - `uv run pytest` passes; `uv run hauntlet selftest` unchanged; core unchanged; actual demo results reported (task 13.4)

- [x] 15. Approved change D17: CLI
  - [x] 15.1 Subcommands
    - `src/hauntlet/cli.py`: `hauntlet exorcist demo --room R [--out DIR]`, `generate --run ID`, `delta --bundle ID --after ID` per design.md "CLI". All three share `HAUNTLET_DB` and `HAUNTLET_BASE_URL`; refusals exit 2 with the reason. `demo` is added to `hauntlet run --agent` through `get_agent`
    - _Requirements: 12.1–12.4, 8.8, D17_
  - [x] 15.2 Write `tests/test_exorcist_cli.py`
    - `demo` for one file room and one MCP room writes a bundle and a delta and prints their paths; `demo --room parlor` refuses and names the supported rooms; `generate` refuses an unfinalized run
    - Real-client simulation: `hauntlet serve` app + `mcp serve` subprocess driven by a scripted MCP client as the after run, then `mcp finalize` (D19 copy present), then `exorcist delta`. The report is labelled "real client, declared by the tester" and the fact-log signal is computed. The test does not claim the client is Kiro
    - _Requirements: 7.4, 7.5, 10.6, 10.9, 12.1–12.4_

- [x] 16. Checkpoint: CLI green
  - `uv run pytest` passes; core unchanged

- [x] 17. Approved change D16 and its amendment: hosted routes
  - [x] 17.1 Routes and service wiring
    - `src/hauntlet/server.py` `create_app`: build an `ExorcistService` beside `RangeService` with the env-configured caps, and add the six routes in design.md "Hosted service". Existing routes and the `noindex` middleware are unchanged. IDs are checked against `[A-Za-z0-9_-]` before any filesystem lookup. The retention sweeper is confined to `exorcist_root`
    - `src/hauntlet/exorcist/static/exorcist.html`: demo button per configured demo room, links to report and bundle; Alpine.js, no build step, no inline secrets, and `meta robots noindex`
    - _Requirements: 11.1–11.6, D16_
  - [x] 17.2 Write `tests/test_exorcist_server.py`
    - The demo round trip for `cursed-repo` and `poltergeist`; 429 over the concurrency and per-minute caps (fake clock); 400 for an unsupported room; 409 when exorcising an unfinalized run
    - The bundle zip is deterministic (the same bytes twice) and extracts to the bundle tree
    - Attaching an after run: success, and each admission failure
    - 404 for unknown, expired (after the sweeper) and malformed IDs; `X-Robots-Tag` on every exorcist response; no route accepts a body containing a bundle or config
    - _Requirements: 11.1–11.6_

- [x] 18. Checkpoint: hosted green
  - `uv run pytest` passes; core unchanged; `uv run hauntlet serve` started by hand serves `/exorcist`

- [x] 19. Room READMEs and release gate
  - Add an "Exorcist" section to `src/hauntlet/rooms/poltergeist/README.md` and `src/hauntlet/rooms/parlor/README.md`: how to generate, apply by hand and attach, with a pointer to `EXORCISM.md` for the cited steps
  - Add a short note to the Cursed Repo and Threshold READMEs: demo path only
  - Top-level `README.md`: one paragraph on the Exorcist and the two re-run paths, with the demo-agent caveat ("not Kiro, says nothing about any model")
  - Disclosure checklist (Requirement 15, manual review): no repository file, generated bundle or report describes a privately disclosed finding beyond the approved general wording
  - _Requirements: 7.1, 15.1, 15.2_

- [x] 20. Final checkpoint
  - `uv run pytest`, `uv run hauntlet selftest` (unchanged), `uv run python scripts/check_payload_safety.py`, `uv run hauntlet sample-report` (no diff in `docs/sample-report.html`), `git diff --stat src/hauntlet/core` empty
  - Report the final demo results table (before/after per demo room) and any not-interpreted items or open assumptions (A1–A5) that remain

## Notes

- Every test task is required; none is optional.
- **Every checkpoint is a stop.** Report the test count, the selftest result
  and the payload-guard result, so the maintainer can commit before the next
  task.
- **Task 13.4 is a hard stop.** If the demo results differ from design.md
  "Expected demo results", report the predicted vs actual table before pinning
  any golden. Do not tune the interpreter, grammar or obedience parser.
- `src/hauntlet/core/` stays unchanged throughout. Each checkpoint checks
  `git diff --stat src/hauntlet/core`. Anything that needs a core change is a
  new numbered proposal (D21+) and stops the task.
- Tasks 1–14 were done on 2026-11-08. The demo agent records a per-action
  `trace` and a `denials` list used by the delta and the causality tests. Task 3 also corrected Parlor README
  limitation 7, which made the same wrong sandbox claim as the three D18 texts
  (text only).
- Tasks that write the same file run in separate waves: `exorcist/generate.py`
  (6.4, 6.5); `tests/test_exorcist_generate.py` (6.7 only); `agents/demo.py`
  (11.1, 11.2); `exorcist/delta.py` and `report.py` (12.2 after 12.1's signal);
  `cli.py` (2.1, 15.1); `server.py` (17.1 only).
- The D15 profiles (task 5) come before the generator, because guardrail
  selection reads them. Their `real_client_env` field must exist before the
  demo agent (task 11) is built.
- The goldens (13.5) come after the causality test (13.3) and the comparison
  with the prediction (13.4), so a pinned golden never hides an unexplained
  result.
- The room READMEs (task 19) are written last, after behaviour is final, so
  the manual steps match the shipped CLI and bundle layout.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "3"] },
    { "id": 1, "tasks": ["1.2", "2.2"] },
    { "id": 2, "tasks": ["4"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.2"] },
    { "id": 5, "tasks": ["5.3", "6.1", "6.3"] },
    { "id": 6, "tasks": ["5.4", "6.2", "6.4"] },
    { "id": 7, "tasks": ["6.5", "6.6"] },
    { "id": 8, "tasks": ["6.7"] },
    { "id": 9, "tasks": ["7.1"] },
    { "id": 10, "tasks": ["7.2"] },
    { "id": 11, "tasks": ["7.3"] },
    { "id": 12, "tasks": ["8"] },
    { "id": 13, "tasks": ["9.1"] },
    { "id": 14, "tasks": ["9.2"] },
    { "id": 15, "tasks": ["9.3"] },
    { "id": 16, "tasks": ["10"] },
    { "id": 17, "tasks": ["11.1"] },
    { "id": 18, "tasks": ["11.2"] },
    { "id": 19, "tasks": ["11.3"] },
    { "id": 20, "tasks": ["12.1"] },
    { "id": 21, "tasks": ["12.2"] },
    { "id": 22, "tasks": ["12.3"] },
    { "id": 23, "tasks": ["12.4"] },
    { "id": 24, "tasks": ["13.1"] },
    { "id": 25, "tasks": ["13.2"] },
    { "id": 26, "tasks": ["13.3"] },
    { "id": 27, "tasks": ["13.4"] },
    { "id": 28, "tasks": ["13.5"] },
    { "id": 29, "tasks": ["14"] },
    { "id": 30, "tasks": ["15.1"] },
    { "id": 31, "tasks": ["15.2"] },
    { "id": 32, "tasks": ["16"] },
    { "id": 33, "tasks": ["17.1"] },
    { "id": 34, "tasks": ["17.2"] },
    { "id": 35, "tasks": ["18"] },
    { "id": 36, "tasks": ["19"] },
    { "id": 37, "tasks": ["20"] }
  ]
}
```
