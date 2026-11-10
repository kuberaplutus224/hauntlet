# Implementation Plan — scorecard

## Overview

Build the scorecard from design.md in the order below.

1. **Compatibility goldens first.** Capture today's delta JSON and text output
   and today's JSON route bodies before anything changes (SP17).
2. **Small changes outside the package.** These are D21 and D30 (read-only
   `RangeService` accessors), `CLASS_TEXT` (Exorcist, D24 note), D31 (the
   redactor) and D28 (room cards). A checkpoint follows that requires every
   existing test and an unchanged `hauntlet selftest`.
3. **Pure scorecard modules.** In order: copy, theme, model, facts, then the
   builder with its properties (checkpoint).
4. **I/O and HTML.** `sources.py` with the fact-log path rules, then the
   renderer and static assets with their properties (checkpoint).
5. **D26 demo evidence, the D22 stream, the D23 switch of routes and writers,
   and D25** (checkpoint).
6. **Golden pages.** They are pinned only after the maintainer has looked at
   the rendered pages (hard stop).
7. **Docs, the manual release gate and the final checkpoint.**

The permitted changes outside `src/hauntlet/scorecard/` are exactly those in
requirements 15.1 (a)–(k). **In `src/hauntlet/core/`, only `service.py`
changes, and only by the two read-only methods of D21 and D30.** Any other
change found while building is a new numbered proposal (D32+; D29 is
reserved) and stops the task.

**Do-not-tune rule.** The scorecard renders what the data says. If a rendered
page shows a state that looks wrong (for example a demo room that is not L3 or
above before), stop and report it. Do not change the builder's state rules,
the copy or the data to make a page look as expected.

## Tasks

- [x] 1. Capture compatibility goldens (before any other change)
  - `tests/fixtures/scorecard_compat/`: for three fixed deltas (demo path with an after run, real-client path, pending), built from fixed-seed synthetic runs in `tests/_exorcist_strategies.py`, write today's `render_json` and `render_text` bytes
  - For one fixed run on an in-memory `RangeService`, write today's JSON bodies of `GET /runs/{id}`, `/runs/{id}/score`, `/health`, `POST /runs/{id}/finalize`
  - `tests/test_scorecard_compat.py` (first half of **SP17**): the current code reproduces every file byte for byte
  - _Requirements: 13.1, 13.2, SP17_

- [x] 2. Approved changes D21 and D30: read-only accessors
  - [x] 2.1 `src/hauntlet/core/service.py`
    - `RangeService.events(run_id) -> list[Event]` and `RangeService.canaries(run_id) -> list[Canary]`. Each checks `store.get_manifest(run_id)`, raises `UnknownRun` if it is missing, and returns `store.events_for_run` / `store.canaries_for_run` unchanged
    - No other line in `core/` changes
    - _Requirements: 15.1 (a), (i), D21, D30_
  - [x] 2.2 Write `tests/test_service_read_accessors.py`
    - After a naive Threshold run: `events` equals `store.events_for_run`, and `canaries` equals `store.canaries_for_run`; both raise `UnknownRun` for an unknown ID; calling them changes no score (`score` before == after)
    - _Requirements: D21, D30_

- [x] 3. `CLASS_TEXT` public constant (D24 note)
  - `src/hauntlet/exorcist/manifest.py`: rename `_CLASS_TEXT` to `CLASS_TEXT` (same keys and texts) and use the new name internally; re-export from `src/hauntlet/exorcist/__init__.py`
  - First `grep -rn _CLASS_TEXT tests src`: if any test uses the private name, keep `_CLASS_TEXT = CLASS_TEXT`; otherwise no alias
  - `tests/test_exorcist_manifest.py` still passes, and `bundle.json` and `EXORCISM.md` for a fixed spec are byte-identical before and after (compare against a capture made at the start of this task)
  - _Requirements: 15.1 (k)_

- [x] 4. Approved change D31: the redactor
  - [x] 4.1 `src/hauntlet/redact.py`
    - `redactor(canaries) -> Callable[[str], str]`, exactly as design.md "Redaction": exact values longest first, then the three patterns, then the URL-decoded pass. It imports only `hauntlet.core.canary` (for `DUMMY_PREFIX` and `MARKER_PREFIX`) and `hauntlet.core.models`
    - _Requirements: 10.1–10.3, 15.1 (j), D31_
  - [x] 4.2 Write `tests/test_redact.py` (redactor half of **SP10**)
    - Hypothesis: random canary sets embedded raw, percent-encoded, inside `/c/` URLs, bare, and next to quotes and `<`; the output holds no full value, nothing after `HAUNTLET-DUMMY-` or `hauntlet-mark-`, and no token
    - Pattern-only mode (empty canary list) still removes secrets, markers and `/c/` tokens
    - Idempotent: `r(r(x)) == r(x)`
    - _Requirements: 10.1–10.3, SP10_

- [x] 5. Approved change D28: room cards
  - `card.py` with `ROOM_CARDS: dict[str, tuple[str, str]]` in `rooms/threshold/`, `rooms/cursed_repo/` (both rooms), `rooms/poltergeist/` (both rooms) and `rooms/parlor/`, with the values from requirements D28, verbatim
  - Plain strings; no imports
  - `uv run python scripts/check_payload_safety.py` stays clean
  - _Requirements: 5.1, 15.1 (g), D28_

- [x] 6. Checkpoint: outside changes green
  - `uv run pytest` passes (task 1's compat tests included); `uv run hauntlet selftest` passes with output unchanged; payload safety clean; `git diff --stat src/hauntlet/core` shows only `service.py`, and the diff is the two methods

- [x] 7. Pure modules: copy, theme, model, inputs
  - [x] 7.1 `scorecard/copy.py`
    - C1–C27 verbatim from the requirements' table; the C24 hero phrases and C25 signal phrases from Requirements 3.3 and 6.4; the D27 effect and source tables; the fact phrases from design.md "Facts"; the section titles
    - _Requirements: 1.1, 1.2, 3.3, 6.4, D27_
  - [x] 7.2 `scorecard/theme.py`
    - The tokens of Requirement 11.3 and `PAIRS`, the allowed (foreground, background, kind) pairs from design.md "Stylesheet and tokens"; `contrast(a, b)` with the WCAG relative-luminance formula
    - _Requirements: 11.3, 12.1_
  - [x] 7.3 `scorecard/model.py`, `scorecard/inputs.py`, `scorecard/rooms.py`
    - The frozen dataclasses from design.md "Inputs" and "View model"; `rooms.py` merges the four `ROOM_CARDS`
    - _Requirements: 1.1, 5.1_
  - [x] 7.4 Write `tests/test_scorecard_copy_table.py` and `tests/test_scorecard_rooms.py`
    - Every C-row in `.kiro/specs/scorecard/requirements.md` (parsed from the markdown table) equals the `copy.py` constant
    - **SP18:** `rooms.py` covers exactly `default_rooms()`; every non-control trap in every profile yields a D27 "where" and "asked to" line; every `Effect` and `Source` has a phrase
    - _Requirements: 1.1, 5.1, 6.3, SP18_

- [x] 8. Facts
  - [x] 8.1 `scorecard/facts.py`
    - `Fact` and the normalisers `normalise_event`, `normalise_mcp`, `normalise_parlor` and `normalise_trace` from design.md "Facts", with the trap-attribution rule (8.6), the order, the content-derived `fact_id`, and `to_line(fact, run) -> FactLine` with the phrase table, the who column, the notes and the time column
    - Inputs are already redacted; `facts.py` does no I/O
    - _Requirements: 8.2–8.6_
  - [x] 8.2 Write `tests/test_scorecard_facts.py` (**SP15**)
    - Strategy `facts()`: events on every channel and signal, expired and late, every MCP and Parlor record kind, and trace entries
    - Filesystem and transcript events show "at finalize"; transcript lines carry "from the submitted transcript"; expired events carry the not-scored note; only records that name a trap, or a `call` to a steered tool, get a `trap_id`; demo decisions never do
    - `fact_id` is stable across two orderings of the same events with different random `event_id`s
    - Every phrase is in `copy.py`
    - _Requirements: 8.4–8.6, SP15_

- [x] 9. Builder
  - [x] 9.1 `scorecard/build.py`
    - `build(inp: ScorecardInput) -> ViewModel`, with the rules in design.md "Builder rules": states, the after state from the delta (the change table), hero (chip, sentences, pills, toggle, provisional note), room cards and summaries, default room, trap cards (where, asked, did, fixes, no-guardrail, changed by), exorcism view (files from `digests`, C26 support files, tags, assumptions, cannot-fix, permissions, not interpreted, demo notes, env note, costs, next step), the evidence view, aggregates, late arrivals and ignored events
    - Strings copied from `bundle.json` and the delta pass through the redactor once more
    - Class texts from `hauntlet.exorcist.CLASS_TEXT`
    - _Requirements: 1.1–1.3, 1.5, 2.3, 2.4, 3.1–3.6, 4.1–4.3, 5.1–5.5, 6.1–6.7, 7.1–7.8, 9.1–9.7_
  - [x] 9.2 Write `tests/test_scorecard_states.py` (**SP5–SP8**)
    - **SP5:** hero chip and sentence per 3.2 and 3.3, over random runs including active, provisional, all-`not_exercised` and L2-not-assessed rooms; an active run never has a level
    - **SP6:** every before level, signal and pill value appears in the view model's After view values
    - **SP7:** no grey, control, info or not-run state has token `l0`; controls never have a level
    - **SP8:** forced higher after levels are marked "Regression"; delta costs appear as costs and never on an improved state
    - _Requirements: 3.1–3.4, 5.2, 5.3, 9.1–9.6, SP5–SP8_
  - [x] 9.3 Write `tests/test_scorecard_changed_by.py` (**SP9**)
    - Demo deltas: chips equal `changed_by_display`; A4 items carry "depends on A4"; items only in `cites` are absent; an empty list shows "none". Real-client deltas: C18, no chips
    - _Requirements: 6.7, SP9_
  - [x] 9.4 Write `tests/test_scorecard_badge.py`, builder half (**SP4**)
    - Each path maps to its exact C1–C4 string; demo view models never carry C2 or `REAL_CLIENT_LABEL`, and real-client ones never carry C1 or `DEMO_LABEL`
    - _Requirements: 2.3–2.5, SP4_

- [x] 10. Checkpoint: pure modules green
  - `uv run pytest` passes (SP4 builder half, SP5–SP9, SP15, SP18); core unchanged since task 6

- [x] 11. Sources (I/O)
  - [x] 11.1 `scorecard/sources.py`
    - `load_run`, `live_fact_log`, `reports_fact_log`, `bundle_evidence`, `load_bundle`, `load_delta` from design.md "Inputs". Every string goes through the D31 redactor with the run's D30 canaries before `facts.py`
    - Fact-log path rules exactly as design.md "Fact-log path": the ID charset check first; `get_run` must succeed; the stored `Run.run_id` is used; rooms come from the manifest ∩ registered MCP/Parlor rooms; `cli.mcp_workspace` (imported inside the function) plus the room's `factlog.facts_path`; not a symlink; resolved under the scratch root
    - Latest delta by the after run's `created_at`, ties broken by run ID; unreadable `bundle.json` or delta gives the C27 state, never an exception
    - _Requirements: 1.1, 7.3, 8.3, 8.9, 10.3_
  - [x] 11.2 Write `tests/test_scorecard_sources.py`
    - The live path equals `mcpfacts.demo_facts_path` for both Poltergeist rooms and the `hauntlet parlor open` workspace for Parlor
    - Hostile IDs (`..`, `/`, `%2F`, absolute, over-long, well-formed but unknown) and a symlinked fact log give `UnknownRun`/404 or "fact log not available". An `open` spy shows that no file outside the scratch root is opened
    - Two attached after runs: the one created later is shown
    - A corrupt `bundle.json` and a corrupt delta JSON each give the C27 state
    - _Requirements: 8.9, design "Fact-log path"_

- [x] 12. Renderer and static assets
  - [x] 12.1 `scorecard/static/scorecard.css`
    - The token block and the rules in design.md "Stylesheet and tokens": fills with on-tokens, outlined grey and info chips, `:focus-visible`, 44 px targets, the serif stack `ui-serif, Georgia, serif` for headline, section titles and `.verdict-sentence`, the system sans body stack, sticky header, single column below 640 px, `overflow-x` only on the evidence list, and both motion blocks
    - _Requirements: 11.1, 11.3, 11.4, 12.1, 12.4–12.7, 2.2_
  - [x] 12.2 `scorecard/static/scorecard.js`
    - The Alpine component in design.md "The Alpine component": `js` class at `alpine:init`; view, room and log-scope state with `:class`; `EventSource` with ID dedupe, `finalized` shows the "Show the verdict" link, `done` closes; a throttled live region; replay with clamped gaps and an instant reduced-motion path; launcher buttons post to `/exorcist/demo` and follow `report_url`
    - No `innerHTML`, no `x-html`, no `eval` of data
    - _Requirements: 1.4, 3.5, 5.5, 8.7, 8.8, 12.7, 12.8, 7.9_
  - [x] 12.3 `scorecard/render.py`
    - The document outline in design.md "Renderer", with the badge as the header's first child, `<code>{run_id}</code>`, both views as `.v-before`/`.v-after` spans, every run room's panel, `<details>` expanders, every fact `<li>` with `data-fact-id`, `#sc-data` JSON escaped for `<script>`, the pinned Alpine tag copied from `exorcist.html`, and CSS and JS inlined
    - `render_launcher(demo_rooms)`: header with C1, legend, one button per room
    - The only escaping path is `t()`
    - `scorecard/__init__.py`: `render_run`, `render_exorcism`, `render_launcher` and `exorcism_file_renderer`, each `sources` → `build` → `render`
    - _Requirements: 1.4, 2.1, 2.2, 7.9, 10.5–10.7, 12.3, 12.9, 13.7_
  - [x] 12.4 Write the HTML property tests
    - `tests/test_scorecard_copy.py`, **SP1:** text nodes minus copy, imported texts and input values is empty
    - `tests/test_scorecard_parity.py`, **SP2:** every core-report datum, and every `render_json` field value, is present
    - `tests/test_scorecard_noscript.py`, **SP3:** with no script run, every section, the trap cards of every run room, both views and every fact are present
    - `tests/test_scorecard_badge.py`, HTML half of **SP4**: the header's first child is the badge
    - `tests/test_scorecard_redaction.py`, page half of **SP10**: no canary value in the HTML or `#sc-data`
    - `tests/test_scorecard_no_trap_text.py`, **SP11:** every registered room × naive and demo agents; the 6-word scan against templates and fixtures
    - `tests/test_scorecard_escaping.py`, **SP12:** hostile details and fields add no element or attribute; there is no `x-html` and no `innerHTML` in `render.py` or `scorecard.js`
    - `tests/test_scorecard_theme.py`, **SP13** (example): colour literals only in `:root`; every used pair is in `PAIRS` and passes; `--l4` only on L4 selectors
    - `tests/test_scorecard_a11y_static.py`, **SP14** (example): chip, pill and tag text present; click bindings only on `button`/`a`/`summary`; the 44 px rule; the reduced-motion block; `header`/`main`, one `h1`, ordered headings, `lang="en"`; theme words absent from `[data-finding]` regions (11.2)
    - _Requirements: 1.1, 1.4, 1.5, 2.2, 10.1–10.5, 11.2–11.4, 12.1–12.5, 12.7, 12.9, SP1–SP4, SP10–SP14_

- [x] 13. Checkpoint: renderer green
  - `uv run pytest` passes (SP1–SP15, SP18); payload safety clean; core unchanged since task 6
  - Write one page per path (demo, real client, reference, not recorded) to a temp dir and report the paths, so the maintainer can open them

- [x] 14. Visual standards (visual review 2026-11-09)
  - Implement design.md "Visual standards": type scale, 1120px page and 28px section gap, hero level block and before → after strip, one-row legend, run rooms first and muted small cards for rooms not run, trap steps as an auto-fit grid with the threat-profile title and mono ID, one row per exorcism file with grouped items in `<details>` and a primary download button, the evidence separator and "×N" merging
  - Requirements 5.1 and 11.1 are amended as recorded in requirements.md
  - Served pages never show the bundle's absolute path
  - `exorcist/texts.py`: replace "(Requirement 8.9)" in `MCP_ENV_NOTE` and `FILE_ROOM_ENV_NOTE` with plain words. This deliberately changes the delta JSON and text, so the task 1 compatibility goldens are re-captured once for this change, and the diff is shown in the report
  - Tests: `tests/test_scorecard_layout.py` (the height estimates above), a file-row test (no sentence repeats within a row; identical items grouped), a served-path test, an evidence test (separator before every note; merged rows keep every ID); the existing token, contrast and no-literal checks stay
  - Regenerate the six review pages in `/tmp/hauntlet-scorecard-pages` and stop
  - _Requirements: 3.1, 5.1, 6.2, 7.1–7.3, 8.2, 11.1, 11.3, 12.1, 12.6_

- [x] 15. Approved change D26: keep the demo's evidence
  - `src/hauntlet/exorcist/service.py` `demo`: after the after run, write `evidence/facts-<run_id>-<room>.jsonl` (MCP rooms, before and after; records redacted with the D31 redactor and the run's D30 canaries) and `evidence/trace-<run_id>.jsonl` (both runs) through `writer.write_into`
  - `src/hauntlet/exorcist/hosted.py`: `_ARCHIVE_SKIP` gains `"evidence"`
  - Tests: `tests/test_exorcist_server.py` zip listing has no `evidence/`; a new `tests/test_exorcist_demo_evidence.py` checks that the files exist for `cursed-repo` (trace only) and `poltergeist` (facts and trace), contain no canary value, and are removed by the retention sweep with their bundle
  - _Requirements: 8.3, D26_

- [x] 16. Approved change D22: the live stream
  - [x] 16.1 `scorecard/stream.py` and the route
    - `GET /runs/{run_id}/facts/stream` in `src/hauntlet/server.py`, with the loop, events, keepalive, `Last-Event-ID`, `Cache-Control: no-store`, the caps `HAUNTLET_STREAM_MAX` and `HAUNTLET_STREAM_POLL_SECS`, thread offload and disconnect handling from design.md "Live stream". Paths only through `sources.live_fact_log`
    - _Requirements: 8.7, 10.3, 10.7, D22_
  - [x] 16.2 Write `tests/test_scorecard_stream.py` (**SP16**, stream half of **SP10**)
    - Finished runs (random rooms): the `fact` events up to `done` equal the embedded `<li>` IDs and texts, in order; no canary value appears in the stream bytes
    - Active run: a second thread records a canary hit and then finalizes; the client sees the hit, then `finalized`, then `done`
    - `Last-Event-ID` resumes without duplicates; 404 for unknown and hostile IDs; 429 over the cap (cap 1); `X-Robots-Tag` present
    - _Requirements: 8.7, 8.8, 10.3, SP10, SP16_

- [x] 17. Approved change D23: switch routes and writers
  - [x] 17.1 Routes
    - `src/hauntlet/server.py`: `/runs/{id}/report` → `render_run(path="not-recorded", served=True)`, with `stream_url` while the run is active; `/exorcisms/{id}/report` → `render_exorcism`; `/exorcist` → `render_launcher`. JSON routes are untouched
    - _Requirements: 13.1, D23_
  - [x] 17.2 Writers
    - `ExorcistService(…, html_renderer=None)`: `_write_delta` uses it for `html` when set. `cli.py` and `server.py` pass `scorecard.exorcism_file_renderer`
    - `cli.py`: `hauntlet run` (path per agent, aggregates when `--repeat > 1`), `mcp finalize` and `parlor finalize` (path `real-client`, rendered before teardown), and `sample-report` (`reference:naive`) write scorecard HTML under the same file names
    - `core/report.py`, `exorcist/report.render_html` and `exorcist.html` stay; nothing on the default paths uses them
    - _Requirements: 13.3, 13.4, D23_
  - [x] 17.3 Write `tests/test_scorecard_server.py` and finish **SP17**
    - Each route: 200 and `noindex` (header and meta), 404s; the launcher demo round trip shows C1 and `DEMO_LABEL`; an active run's report carries `stream_url`
    - `tests/test_scorecard_compat.py` (second half of **SP17**): task 1's goldens still match after the switch; `sample-report` is identical twice and contains `<code>sample-report</code>`
    - The existing HTML tests listed in design.md "Routes and writers" pass unchanged
    - _Requirements: 13.1–13.6, SP17_

- [x] 18. Approved change D25: the hook
  - `.kiro/hooks/scorecard-refresh.json`: set the matcher to the design's regex; the command and timeout are unchanged
  - Regenerate `docs/sample-report.html` with `uv run hauntlet sample-report --out docs/sample-report.html`; the run again produces no diff
  - A test checks the matcher against `src/hauntlet/scorecard/render.py`, `src/hauntlet/exorcist/texts.py`, `src/hauntlet/core/report.py` (match) and `src/hauntlet/rooms/parlor/room.py` (no match)
  - _Requirements: 13.4, 13.5, D25_

- [x] 19. Checkpoint: wired up
  - `uv run pytest` passes; `uv run hauntlet selftest` unchanged; payload safety clean; core diff still only the two methods
  - `uv run hauntlet serve` started by hand: `/exorcist` → demo for `cursed-repo` and `poltergeist` → scorecard with the replay; a Poltergeist run started through `hauntlet mcp serve` shows live facts on `/runs/{id}/report`

- [x] 20. Golden pages (hard stop before pinning)
  - [x] 20.1 Render and report
    - With injected fixed clocks, seeds, run IDs and bundle IDs (test-only factories), render the demo scorecard for `cursed-repo` and `poltergeist` and the sample. Report the file paths and, per room, the hero, room cards and trap states as text
  - [x] 20.2 **Stop for the maintainer's review.** Do not pin until the maintainer has looked at the three pages. If a state looks wrong, report it; do not tune (Overview)
  - [x] 20.3 Pin
    - `tests/test_scorecard_golden.py`: byte comparison against `tests/fixtures/scorecard_golden/*.html`
    - _Requirements: 13.4, 13.6_

- [x] 21. Docs and steering
  - `.kiro/steering/tech.md`: replace the layout line with the D24 wording ("… scoring and the core report; the scorecard page lives in `src/hauntlet/scorecard/`")
  - `README.md`: a short "Scorecard" section (what each section shows, the path badge, "Facts the range observed"), with `GET /runs/{id}/facts/stream` added to the route list
  - Disclosure checklist (Requirement 14, manual): no scorecard file, copy, test or sample describes a privately disclosed finding beyond the approved general wording; `mcp-summary-*.txt` is never read by `sources.py`
  - _Requirements: 14.1, 14.2, D24_

- [x] 22. Manual release gate (Q3)
  - At 320 px and 375 × 667 px in one Chromium-based and one WebKit-based browser, on a demo exorcism page and a live run page:
    - the badge, hero chip and verdict sentence are visible without scrolling;
    - no horizontal page scroll (the evidence list may scroll inside itself);
    - a keyboard walk reaches every control in visual order with a visible focus ring;
    - with reduced motion on, replay is instant and nothing animates;
    - with scripts disabled, the whole page is readable;
    - VoiceOver reads the badge, the chip text and the sentence first
  - Record the results (browser versions, pass or fail per item) in the task's completion note
  - _Requirements: 2.2, 12.3–12.7, Q3_
  - **Completion note (2026-11-10):** passed, as reported by the maintainer. Chromium-based browser checked by Claude; Safari (WebKit) and VoiceOver checked by the maintainer. Every item passed in both browsers. Browser versions were not recorded.

- [x] 23. Final checkpoint
  - `uv run pytest`, `uv run hauntlet selftest` (unchanged), `uv run python scripts/check_payload_safety.py`, `uv run hauntlet sample-report` (no diff), and `git diff --stat src/hauntlet/core` (only the two `service.py` methods)
  - Report the test count, the release-gate results, and anything shown as "fact log not available" on the default paths (expected: Parlor after finalize, and real-client MCP runs on the hosted range without the D19 copy)

## Notes

- Every test task is required; none is optional.
- **Every checkpoint is a stop.** Report the test count, the selftest result
  and the payload-guard result, so the maintainer can commit before the next
  task.
- **Task 1 runs before any other change**, so the compatibility goldens record
  today's behaviour, not the new one.
- **Task 20.2 is a hard stop.** Golden pages are pinned only after the
  maintainer has seen them.
- In `src/hauntlet/core/`, only `service.py` changes, and only by `events` and
  `canaries`. Each checkpoint checks this. Anything else in core is a new
  numbered proposal (D32+) and stops the task.
- The scorecard never reads a private Exorcist name. Class texts come from
  `hauntlet.exorcist.CLASS_TEXT` (task 3). The Exorcist never imports
  `hauntlet.scorecard`. Its writers get the renderer through the
  `html_renderer` argument (task 17.2).
- Fact-log paths are built only in `sources.live_fact_log`, from a
  store-validated run and a manifest room, through `cli.mcp_workspace`. The
  stream and the routes never build a path themselves (tasks 11, 16).
- Tasks that write the same file run in separate waves:
  `src/hauntlet/server.py` (16.1, 17.1); `src/hauntlet/exorcist/service.py`
  (15, 17.2); `tests/test_scorecard_badge.py` (9.4, 12.4);
  `tests/test_scorecard_redaction.py` (12.4 only; 4.2 and 16.2 use their own
  files); `tests/test_scorecard_compat.py` (1, 17.3).
- The redactor (task 4) and D30 (task 2) come before `sources.py` (task 11) and
  D26 (task 15), which both redact with a run's canaries.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "3", "4.1", "5"] },
    { "id": 2, "tasks": ["2.2", "4.2"] },
    { "id": 3, "tasks": ["6"] },
    { "id": 4, "tasks": ["7.1", "7.2", "7.3"] },
    { "id": 5, "tasks": ["7.4", "8.1"] },
    { "id": 6, "tasks": ["8.2", "9.1"] },
    { "id": 7, "tasks": ["9.2", "9.3", "9.4"] },
    { "id": 8, "tasks": ["10"] },
    { "id": 9, "tasks": ["11.1", "12.1", "12.2"] },
    { "id": 10, "tasks": ["11.2", "12.3"] },
    { "id": 11, "tasks": ["12.4"] },
    { "id": 12, "tasks": ["13"] },
    { "id": 13, "tasks": ["14"] },
    { "id": 14, "tasks": ["15", "16.1"] },
    { "id": 15, "tasks": ["16.2", "17.1"] },
    { "id": 16, "tasks": ["17.2"] },
    { "id": 17, "tasks": ["17.3", "18"] },
    { "id": 18, "tasks": ["19"] },
    { "id": 19, "tasks": ["20.1"] },
    { "id": 20, "tasks": ["20.2"] },
    { "id": 21, "tasks": ["20.3", "21"] },
    { "id": 22, "tasks": ["22"] },
    { "id": 23, "tasks": ["23"] }
  ]
}
```
