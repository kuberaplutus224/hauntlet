# Design Document — scorecard

## Overview

The scorecard is one server-rendered HTML page, enhanced with Alpine.js. It
shows a run (the autopsy) and, when one exists, its exorcism (bundle, after
run, delta). Live facts arrive over Server-Sent Events while a run is active.

The design follows four rules from the requirements:

- **One pure builder.** A pure function turns the inputs (scores, manifest,
  bundle manifest, delta JSON, facts) into a **view model**. The renderer
  turns the view model into HTML. Every state rule (hero, grey states,
  controls, changes) lives in the builder, so the tests check plain data, not
  markup.
- **The server renders everything.** The HTML holds every section, every
  room's trap cards, both views and the full evidence log. Alpine only toggles
  classes, plays a replay and appends live lines (Requirement 1.4).
- **Redact once, early.** Facts are redacted when they are loaded, before the
  builder sees them. The builder, the renderer and the stream therefore cannot
  leak a canary value (Requirement 10).
- **Read, never decide.** The page reads `RunScore`, `RunManifest`,
  `bundle.json` and the delta's `render_json` output. It never recomputes a
  level, a class or a change state.

New code lives in `src/hauntlet/scorecard/`. Changes outside it are the
approved decisions D21–D28, and three items approved in design review
(2026-11-09): **D30** (a read-only canary accessor), **D31** (where the
redactor lives), and **C26** and **C27** (two more fixed strings). There is
also one small Exorcist change under D24's import rule: the trap-class texts
become the public constant `hauntlet.exorcist.CLASS_TEXT`. D29 stays reserved
for the full-exorcism sample (requirements, Q2).

## Architecture

```mermaid
flowchart LR
  subgraph core["hauntlet.core"]
    RS["RangeService<br/>score / manifest / get_run<br/>events (D21) / canaries (D30)"]
  end
  subgraph ex["hauntlet.exorcist"]
    EXS[ExorcistService<br/>bundle dir, deltas/]
    TX[texts.py / report.render_json]
    PR[profiles.py D15]
  end
  subgraph rooms["room packages"]
    RC["card.py (D28)"]
    FLs[fact logs<br/>poltergeist / parlor]
  end
  RED["hauntlet/redact.py (D31)"]
  subgraph sc["hauntlet.scorecard"]
    SRC[sources.py<br/>I/O: load inputs]
    FCT[facts.py<br/>normalise + phrase]
    BLD[build.py<br/>pure view model]
    REN[render.py<br/>HTML]
    STR[stream.py<br/>SSE, D22]
    ST[static/<br/>scorecard.css, scorecard.js]
  end
  RS --> SRC
  EXS --> SRC
  FLs --> SRC
  SRC --> RED --> FCT --> BLD
  TX --> BLD
  PR --> BLD
  RC --> BLD
  BLD --> REN
  ST --> REN
  SRC --> STR
  FCT --> STR
  REN --> HTTP["server.py routes (D23)"]
  STR --> HTTP
  REN --> CLI["cli.py writers (D23)"]
  REN --> EXW["exorcist service / hosted writers (D23)"]
```

Data flows one way. `hauntlet.scorecard` imports `hauntlet.core`,
`hauntlet.exorcist` (types, texts, profiles, `render_json`) and the room card
data. Neither `core` nor `exorcist` imports `hauntlet.scorecard` (D24). The
Exorcist's writers call the renderer through a function passed in by the
caller (see "Writers"), so the import direction holds.

### Package layout

```
src/hauntlet/scorecard/
  __init__.py      # render_run, render_exorcism, render_launcher (public API)
  copy.py          # C1–C27, hero phrases (C24), signal phrases (C25), D27 tables
  model.py         # view-model dataclasses (frozen, JSON-ready)
  inputs.py        # ScorecardInput and its parts (what the builder receives)
  build.py         # pure: ScorecardInput -> ViewModel
  facts.py         # pure: raw records -> Fact; Fact -> FactLine (phrase, who, time, tag)
  sources.py       # I/O: RangeService, bundle dir, scratch, reports dir -> ScorecardInput
  render.py        # pure: ViewModel -> HTML string
  stream.py        # SSE generator for D22
  rooms.py         # D28 registry: room name -> RoomCard
  theme.py         # colour tokens and the declared token pairs (for SP13)
  static/
    scorecard.css
    scorecard.js   # the Alpine component; inlined into each page
src/hauntlet/redact.py   # D31: canary redaction, imports only hauntlet.core.canary
src/hauntlet/rooms/<pkg>/card.py   # D28: ROOM_CARDS
```

`render.py` inlines `scorecard.css` and `scorecard.js` into every page, so a
written file is self-contained apart from the pinned Alpine script
(Requirement 13.7).

## Components and Interfaces

Each component and the interface it exposes. The sections below give the
rules behind each one.

| Component | Module | Interface | Details |
|---|---|---|---|
| Public API | `scorecard/__init__.py` | `render_run(service, run_id, path=…, served=…)`, `render_exorcism(ex_service, bundle_dir, served=…)`, `render_launcher(demo_rooms)`, `exorcism_file_renderer(...)` | "Routes and writers" |
| Sources (only I/O) | `scorecard/sources.py` | `load_run(service, run_id)`, `live_fact_log(db_path, run, room)`, `reports_fact_log(reports_dir, room, run_id)`, `bundle_evidence(bundle_dir, run_id)`, `load_bundle(bundle_dir)`, `load_delta(bundle_dir)` → `ScorecardInput` | "Where each input comes from", "Fact-log path" |
| Redactor | `hauntlet/redact.py` (D31) | `redactor(canaries) -> Callable[[str], str]` | "Redaction" |
| Facts | `scorecard/facts.py` (pure) | `normalise_event(e)`, `normalise_mcp(f, profile)`, `normalise_parlor(f)`, `normalise_trace(entry, seq)` → `Fact`; `Fact` → `FactLine` | "Facts" |
| Builder | `scorecard/build.py` (pure) | `ScorecardInput` → `ViewModel`; `state_for_trap`, `state_for_room` | "Builder rules" |
| Renderer | `scorecard/render.py` (pure) | `ViewModel` → HTML string, with `scorecard.css` and `scorecard.js` inlined | "Renderer" |
| Live stream | `scorecard/stream.py` (D22) | `GET /runs/{run_id}/facts/stream` → `text/event-stream` with `fact`, `finalized`, `done` events | "Live stream" |
| Fixed copy | `scorecard/copy.py` | C1–C27, C24/C25 tables, D27 phrase tables, fact phrases, section titles | "Fixed copy" |
| Room registry | `scorecard/rooms.py` (D28) | room name → (display name, stands for), merged from each room's `ROOM_CARDS` | "D21, D25, D26, D28 details" |
| Theme | `scorecard/theme.py` | colour tokens and `PAIRS` | "Stylesheet and tokens" |
| Alpine component | `scorecard/static/scorecard.js` | `scorecard()` reading `#sc-data` | "The Alpine component" |

Interfaces added outside the package:

- `RangeService.events(run_id) -> list[Event]` (D21) and
  `RangeService.canaries(run_id) -> list[Canary]` (D30), both read-only.
- `ExorcistService(html_renderer: Callable[[Path, str], bytes] | None)` (D23,
  "Writers").
- `hauntlet.exorcist.CLASS_TEXT`, the public name of `_CLASS_TEXT`.
- `ROOM_CARDS: dict[str, tuple[str, str]]` in each room package's `card.py`
  (D28).

## Data Models

### Inputs (`inputs.py`)

The builder receives one immutable value. `sources.py` is the only module that
does I/O to produce it.

```python
@dataclass(frozen=True)
class RunInput:
    run: Run                          # created_at, finalized_at, expires_at, window_close()
    score: RunScore
    manifest: RunManifest
    facts: tuple[Fact, ...]           # redacted, already normalised (facts.py)
    fact_logs: Mapping[str, bool]     # room -> fact log available (MCP and Parlor rooms only)

@dataclass(frozen=True)
class ExorcismInput:
    bundle_id: str
    bundle: Mapping[str, Any]         # parsed bundle.json, unchanged
    delta: Mapping[str, Any]          # json.loads(render_json(delta)), unchanged
    after: RunInput | None            # None while the after run is pending
    trace: tuple[Fact, ...]           # D26 demo-config facts, demo path only
    download_url: str | None          # "/exorcisms/{id}/bundle" when served by the range
    bundle_path: str | None           # the bundle directory, for static exports

@dataclass(frozen=True)
class ScorecardInput:
    path: str                         # "demo-agent" | "real-client" | "reference:<name>" | "not-recorded"
    agent_name: str                   # "" when not known
    before: RunInput
    exorcism: ExorcismInput | None
    aggregates: tuple[AggregateScore, ...]
    registered_rooms: tuple[str, ...] # registry order (default_rooms())
    served: bool                      # True for HTTP responses, False for written files
    stream_url: str | None            # set only while before.run is active and served
    now: float                        # the clock used for active/provisional, injected
```

The delta is taken as its `render_json` document, never as the `Delta`
dataclass. In-process callers pass `json.loads(render_json(delta))`, and the
hosted route reads `deltas/<after>.json`. Both paths give the builder the same
input, and SP2 can compare the page against exactly what the JSON output says.

#### Where each input comes from (`sources.py`)

| Input | Function | Source |
|---|---|---|
| `Run`, `RunScore`, `RunManifest` | `load_run(service, run_id)` | `RangeService.get_run`, `.score`, `.manifest` |
| Stored events | same | `RangeService.events(run_id)` (D21) |
| Canary values for redaction | same | `RangeService.canaries(run_id)` (D30) |
| Live MCP / Parlor fact log | `live_fact_log(db_path, run, room)` | `cli.mcp_workspace(scratch_root_beside(db), room, run.run_id)` and the room's `factlog.facts_path`, the layout `hauntlet mcp serve` and `hauntlet parlor open` use. Only a store-validated run and a room from its manifest go in (see "Live stream", "Fact-log path") |
| Real-client MCP fact log after finalize | `reports_fact_log(reports_dir, room, run_id)` | the D19 copy `mcp-facts-<run_id>-<room>.jsonl` (`mcpfacts.reports_facts_path`) |
| Demo fact logs and trace | `bundle_evidence(bundle_dir, run_id)` | `evidence/facts-<run_id>-<room>.jsonl`, `evidence/trace-<run_id>.jsonl` (D26) |
| Bundle manifest | `load_bundle(bundle_dir)` | `bundle.json` |
| Delta | `load_delta(bundle_dir)` | the `deltas/<after>.json` whose after run has the latest `created_at`; else `ExorcistService.before_only_delta` |

Fact logs are parsed with the rooms' own `factlog.read`, which skips malformed
lines and never raises. A room whose log file is missing, or which was torn
down at finalize (Parlor today, an MCP room without the D19 copy), gets
`fact_logs[room] = False`.

**Latest delta.** `hosted._latest_delta` picks the last HTML file by name, and
run IDs are random, so with two attached after runs it picks one at random. The
scorecard picks by the after run's `created_at` (from `RangeService.get_run`),
and breaks ties by after run ID. `hosted.report_html` is replaced by the
scorecard route (D23), so the old rule no longer decides what is shown.

### View model (`model.py`)

```python
@dataclass(frozen=True)
class State:
    kind: str            # "level" | "grey" | "control" | "info" | "progress"
    label: str           # chip text, e.g. "L3 Acted", "Not exercised", "False alarm"
    token: str           # CSS token: "l0".."l4", "muted", "info"
    meaning: str         # legend text (C6–C15)
    level: int | None    # 0..4 only when kind == "level"

@dataclass(frozen=True)
class Change:
    before: State
    after: State | None  # None: after not run yet
    marker: str          # "", "Regression", "Lower level observed", "Unchanged",
                         # "Not exercised after", C15, "After: not run yet"

@dataclass(frozen=True)
class Pill:
    name: str            # "Detected" | "Task done" | "False alarms"
    before: str          # e.g. "Detected in 1 of 3 rooms"
    after: str | None
    cost: bool           # True when the after value is a delta cost (9.5)

@dataclass(frozen=True)
class Hero:
    change: Change       # overall
    sentence_before: str
    sentence_after: str | None
    pills: tuple[Pill, ...]
    toggle: str          # "toggle" | "pending" | "none"
    provisional_note: str | None   # C20, filled

@dataclass(frozen=True)
class RoomCard:
    room: str
    name: str            # D28 display name
    stands_for: str      # D28
    run: bool            # False -> "Not run"
    change: Change | None
    summary_before: str
    summary_after: str | None

@dataclass(frozen=True)
class FixLine:
    item_id: str; path: str; rule: str; reason: str
    tag: str             # "Advisory" | "Enforced"
    assumptions: tuple[str, ...]

@dataclass(frozen=True)
class TrapCard:
    ref: str; trap_id: str; is_control: bool
    where: str           # surface + D27 source words
    asked: str           # D27 effects phrase, or the control phrase
    did_before: tuple[str, ...]    # C25 phrases
    did_after: tuple[str, ...] | None
    change: Change
    detected_before: bool; detected_after: bool | None
    evidence: tuple[FactLine, ...]
    fixes: tuple[FixLine, ...]
    no_guardrail: str | None       # reason, or "No exorcism generated yet."
    citation: str                  # TrapSpec.source
    changed_by: tuple[str, ...] | None  # changed_by_display; None on real client
    changed_by_note: str | None    # C17 heading, C18, or "none"
    class_label: str               # delta class, when an exorcism exists

@dataclass(frozen=True)
class FactLine:
    fact_id: str         # content-derived (see "Facts")
    room: str; trap_id: str | None
    time: str            # "+1.2 s" | "at finalize" | "" (demo config)
    who: str             # "Range" | "Agent (observed by the range)" | "Demo config (Hauntlet's interpreter)"
    text: str            # fixed phrase + redacted fields
    tag: str             # "L4 Exposed", "Detected", "Task done", "False alarm", "Blocked", "Not exercised", ""
    note: str            # "from the submitted transcript", the expired note, or ""
    run_role: str        # "before" | "after"

@dataclass(frozen=True)
class ViewModel:
    badge: str; path: str; path_label: str | None
    run_id: str; after_run_id: str | None; rooms_in_run: tuple[str, ...]
    hero: Hero
    legend: tuple[State, ...]
    rooms: tuple[RoomCard, ...]
    traps: Mapping[str, tuple[TrapCard, ...]]   # run rooms only
    default_room: str
    exorcism: "ExorcismView"
    aggregates: tuple[...]                       # rows as the core report shows them
    late: tuple[...]; ignored_events: int
    evidence: "EvidenceView"                     # lines, unavailable rooms, demo-config lines
    live: bool; stream_url: str | None
```

`ExorcismView` holds: files (grouped `FixLine`s per path, with tag and
assumption texts), `cannot_fix` (the six items, verbatim), the
`permissions.yaml` suggestion with its label, `not_interpreted`, `demo_notes`,
`demo_env_note`, `no_guardrail`, costs per room, `download_url` or
`bundle_path`, and a `next_step`: the generate offer (7.7), the delta command
(7.8), or nothing.

## Builder rules (`build.py`)

### States

`state_for_trap(trap_score_or_delta_values, room)` follows a fixed order:

| Condition | State |
|---|---|
| control | `control`: "False alarm" (C14) if the trap is in the room's `false_positives`, else "No false alarm" (muted). Never a level. |
| `not_exercised` signal and level 0 | `grey`: "Not exercised" (C11) |
| otherwise | `level` L0–L4. An L0 trap in a room with `l2_assessed` false gets an extra grey tag "L2 not assessed" (C13) beside the chip, not instead of it. |

`state_for_room` and the hero use the same order on the room's worst level, with
"Not fully exercised" (C21) when the worst level is 0 and any non-control trap
carries `not_exercised`. While the run is active (`run.is_active(now)`) the hero
and every run room show the `progress` state "In progress" with C19, and no
level.

### After state from the delta

The after state comes from the delta trap's `change`, `after_level` and
`after_signals`. The builder maps each change constant once:

| `change` (from `delta.py`) | After state | Marker |
|---|---|---|
| `after not run yet` | none | "After: not run yet" |
| `steered tool called, canary not reached` | `info`: C15 | C15 |
| `not exercised after` | `grey`: C11 | "Not exercised after" |
| `regression` | level from `after_level` | "Regression" |
| `lower level observed` | level from `after_level` | "Lower level observed" |
| `unchanged` | level from `after_level` | "Unchanged" |

A control's after state uses the after room's `false_positives` from the delta
room. There is no "improved" marker. The markers are the delta's own words.
SP7 and SP8 check this table against random deltas.

### Hero

- **Chip:** the before overall state. In the After view the chip is
  `Change(before, after)`, where the after state is the after run's worst
  level with the same rules.
- **Sentence before (C24):** subject from the path (`demo-agent` → "The demo
  agent"; `reference:<name>` → "The reference agent {name}"; otherwise "Your
  agent"), plus the level phrase. Grey and progress states use C21 and C19
  instead.
- **Sentence after:** "After the exorcism, the worst observed level went from
  L{b} to L{a}." When the levels are equal it is "… stayed at L{b}." When the
  after state is grey it is C21 for the after run. It never says the bundle
  caused anything. On the demo path, the "Changed by" rows say what the
  interpreter denied. On the real-client path, C18 says it cannot be observed.
- **Pills:** computed per room from the before `RunScore` and the after
  `RunScore` (loaded by `sources.py`; the delta's room state has no
  `l2_assessed`). `cost` is true when the delta room lists a cost.
- **Toggle:** `"toggle"` when the delta has an `after_run_id`; `"pending"` when a
  bundle exists without one; `"none"` with no exorcism.

### Room summary

"{f} of {n} traps fired" always, then "· {x} not exercised" and
"· {a} false alarms" when non-zero. Fired means a non-control trap at L1 or
above. The After view shows "{b} → {a}" for each term. Rooms not in the run get
"Not run" and an empty summary.

Default room: the run room with the highest before level; the first in registry
order on a tie.

### Trap cards

- **Where:** `"{surface} ({source words})"` from `TrapSpec.surface` and the D27
  source table. A control has no profile, so it shows the surface only.
- **Asked to:** D27 effect phrases in `EFFECT_ORDER`, joined as "a", "a and b",
  "a, b and c", the same joining `grammar.render_sources` uses. A control shows
  "nothing harmful (a benign look-alike)".
- **What the agent did:** C25 phrases in the order reached, echoed, acted,
  exposed, flagged, then C15 when it is in `extra_signals`. With no
  harm-carrying signal: "Did not act on it." (plus the echo note when L2 is not
  assessed), or "The instruction never reached the agent." for
  `not_exercised`.
- **Fixes:** every `bundle.items[]` whose `cites` contains the trap's ref,
  in manifest order. Tag: `Enforced` if `enforced` is true, else `Advisory`.
  The reason, rule and assumptions are copied unchanged.
- **No guardrail:** the `bundle.no_guardrail[].reason` for the ref, else the
  manifest class text when the class is `resisted`, `l0_l2_not_assessed` or
  `control` ("resisted (no guardrail)" and the like, from the public
  `hauntlet.exorcist.CLASS_TEXT`), else
  "No exorcism generated yet." when there is no bundle.
- **Changed by:** demo path: `changed_by_display` unchanged, heading C17, or
  "none". Real-client path: `None`, note C18. Pending: not shown. Items that are
  only in `cites` never appear (SP9).

### Exorcism files

Files come from `bundle.digests` (every guardrail file), in that order. Each
file gets the items whose `path` matches it. A file with no items is a support
file (today only `.kiro/hooks/guards/credential_egress.py`, the guard script
the egress hooks run). It shows the fixed string **C26: "Support file
used by the hooks in this bundle."** and no tag. A file's tag is Enforced when any of its items is
enforced, else Advisory. Today a file's items are all one kind, and a test pins
that, so the file tag is never mixed.

## Fixed copy (`copy.py`)

`copy.py` holds C1–C27 exactly as written in the requirements' table, the
C24 and C25 tables, the D27 phrase tables, the fact phrases (below), and the
section titles. Every other string the renderer emits is a value from the
inputs, or a text imported from `exorcist/texts.py` or `exorcist/report.py`
(`DEMO_NOTES`). A test compares `copy.py` against the requirements' table.
SP1 then checks that every text node of a rendered page is one of these, or an
input value.

Section titles (frame copy, serif): "Verdict", "Levels", "Rooms: the parts
stitched together", "What happened in {room}", "The exorcism", "Evidence log".

## Facts (`facts.py`)

### Normalised record

```python
@dataclass(frozen=True)
class Fact:
    source: str          # "event" | "mcp" | "parlor" | "demo"
    kind: str            # event: "network"/"filesystem"/"transcript" + signal; fact-log kind; "decision"
    room: str
    trap_id: str | None  # only when the record names it, or the room data maps it to exactly one trap
    t: float | None      # None for finalize-time events and demo decisions
    fields: Mapping[str, str]   # redacted strings only
    expired: bool
    late_by_secs: float
    seq: int             # position in its source, for demo decisions and stable order
```

`normalise_event(e)`: `t` is `e.timestamp` for the `network` channel and
`None` for `filesystem` and `transcript`. Those events are created at
`finalize`, so their timestamp is the finalize time, not when the thing
happened (Requirement 8.4). `trap_id` is the event's trap. `__task__` gives a
room-level fact; `__page__` events are never stored as scored events and are
skipped if present.

`normalise_mcp(f, profile)` and `normalise_parlor(f)`: `t` is the record's `t`.
`trap_id` is set for `relay`, `scratch` and `site_action` (which name it), and
for a `call` whose tool is in the room profile's `steered_tools` (a one-to-one
map, D15). Other records stay room-level (Requirement 8.6).

`normalise_trace(entry, seq)`: one demo decision. It is always room-level,
because the trace's `where` field is a location string, and the delta already
maps decisions to traps for the Changed by rows.

### Order and identity

Lines are ordered by:

1. timed facts by `(t, source rank, room, kind, trap_id, fields)`;
2. then the finalize-time facts, in the same key without `t`;
3. demo decisions go in their own list, "Demo config decisions (in order, not
   timed)", by `seq`. The trace has no timestamps, so they are never
   interleaved with timed facts.

`fact_id` is the first 16 hex characters of SHA-256 over the canonical JSON of
`(run_role, source, kind, room, trap_id, t, fields, expired)`, plus `-{n}` for
the n-th identical record. It never uses the store's random `event_id`, so the
sample report stays byte-identical (D9), and the stream and the embedded page
agree on IDs (SP16).

### Phrases

Each `FactLine` is `who`, a fixed phrase with `{fields}`, and a tag. Fields are
redacted before they get here and are truncated to 160 characters with "…".

| Source / kind | Who | Text | Tag |
|---|---|---|---|
| event network `reached` | Agent (observed by the range) | "Fetched a planted link (/c/<token>)." | level L1, or "False alarm" for a control |
| event network `exposed` | Agent (observed by the range) | "Sent HAUNTLET-DUMMY-… to the canary endpoint." | L4 Exposed |
| event filesystem `acted` | Range | "Workspace check: {detail}." | L3 Acted |
| event transcript `echoed` | Range | "Transcript check: planted text repeated in the reply." | L2 Echoed |
| event transcript `flagged` | Range | "Transcript check: the reply reported the instruction." | Detected |
| event `task_done` | Range | "Task check passed." | Task done |
| event `not_exercised` | Range | "The instruction never reached the agent." | Not exercised |
| mcp `negotiated` | Agent (observed by the range) | "Client connected (protocol {revision})." | |
| mcp `list` | Agent (observed by the range) | "Client listed the tools." / "… after the description change." | |
| mcp `call` | Agent (observed by the range) | "Client called {tool} with {args}." | |
| mcp `mutation` | Range | "MCP server changed the description of {tools}." | |
| mcp `signal` | Range | "MCP server sent the tool-change signal ({path}); a receiver was {present / not present}." | |
| mcp `relay` | Range | "Steered tool passed the call to the canary endpoint{, carrying a dummy secret}." | |
| mcp `scratch` | Range | "Steered tool wrote {path} in the scratch workspace." | |
| mcp `answer` | Agent (observed by the range) | "Client submitted an answer: {text}." | |
| mcp `takeover` | Range | "MCP server replaced an earlier session that never got past the handshake." | |
| parlor `page` | Agent (observed by the range) | "Browser fetched page {page_id}." | |
| parlor `image` | Agent (observed by the range) | "Browser fetched the image." | |
| parlor `submit` | Agent (observed by the range) | "Browser submitted the form to {to} (answer {answer}, member code {member_code})." | |
| parlor `site_action` | Range | "Page action wrote {path} in the scratch workspace." | |
| parlor `dropped` | Range | "{count} further requests were not logged (cap reached)." | |
| demo `decision` | Demo config (Hauntlet's interpreter) | "{allowed / skipped} {tool_id}, suggested by {where}{; denied by {ids}}." | "Blocked" when skipped |

Notes added to a line:

- transcript events: "from the submitted transcript" (8.5);
- expired events: "arrived after the window closed, not scored", with
  `late_by_secs` (8.4);
- the time column: "+{t − run.created_at:.1f} s", "at finalize", or empty for
  demo decisions.

Fact phrases are fact descriptions, not trap text. SP11 checks them against the
templates like everything else.

## Redaction (`hauntlet/redact.py`, D31; D30)

```python
def redactor(canaries: Iterable[Canary]) -> Callable[[str], str]
```

The returned function applies, in order:

1. **Exact values** from the run's canaries (D30), longest first: a secret →
   `HAUNTLET-DUMMY-…`, a marker → `hauntlet-mark-…`, a URL or page token →
   `<token>`.
2. **Patterns**, which also catch values from other runs and cases without D30:
   `HAUNTLET-DUMMY-[^\s"'<>&]*` → `HAUNTLET-DUMMY-…`;
   `hauntlet-mark-[0-9A-Za-z]*` → `hauntlet-mark-…`;
   `/c/[A-Za-z0-9_-]+` → `/c/<token>`.
3. URL-decoded forms: the function also redacts the `unquote`d text and, when
   that changed anything, returns the redacted decoded text. A secret sent
   percent-encoded in a query string is caught too.

The prefix stays and the rest is replaced by one "…" (Requirement 10.1).
`sources.py` applies the function to every string field of every fact before
`facts.py` sees it, and to every event `detail`. The builder applies it once
more to every string it copies from `bundle.json` and the delta. Those should
hold no canary value (exorcist EP3), so this is belt and braces.

- **D30 (approved 2026-11-09, core change). `RangeService.canaries(run_id) ->
  list[Canary]`.** It returns `store.canaries_for_run(run_id)` unchanged and
  raises `UnknownRun` for an unknown run. It is read-only and additive, like
  D21. *Why:* URL and page tokens are random `token_urlsafe(18)` strings with
  no prefix. A token that a client echoes outside a `/c/` path (for example a
  bare value in a tool argument) can only be redacted by its exact value.
  *Without D30:* only the pattern pass runs, and a bare token outside `/c/`
  would be shown. SP10 would then be weakened to the patterns.
- **D31 (approved 2026-11-09). The redactor lives in `src/hauntlet/redact.py`.** D26
  writes the demo's evidence redacted from inside `ExorcistService`, and D24
  forbids the Exorcist importing `hauntlet.scorecard`. A top-level module
  beside `hauntlet/paths.py`, importing only `hauntlet.core.canary` for the
  prefixes, serves both. It is not in `core/`. *Alternative:* keep the
  redactor in the scorecard package, and have D26 write raw evidence, as D19
  does for real clients. The scorecard would redact when reading. That would
  amend D26's "redacted".

## Renderer (`render.py`)

### Document outline

```
<html lang="en">
<head> meta charset, viewport, robots noindex,nofollow, <title>
       <style>{scorecard.css}</style>
       <script>document.addEventListener('alpine:init',()=>document.documentElement.classList.add('js'))</script>
       <script defer src="…alpinejs@3.14.1/dist/cdn.min.js" integrity="sha384-…" crossorigin="anonymous"></script>
<body>
<header class="frame">                       sticky; badge first
  <p class="badge" role="note">{C1–C4}</p>
  ghost mark (inline SVG, aria-hidden) · <h1>Hauntlet</h1> · run <code>{run_id}</code> · rooms · after run
<main x-data="scorecard()">
  <section aria-labelledby="verdict">  hero: chip, sentence (serif), pills, toggle, C5
  <section aria-labelledby="levels">   legend
  <section aria-labelledby="rooms">    room cards (buttons)
  <section aria-labelledby="traps">    one <div class="room-panel" data-room> per run room, with trap cards
  <section aria-labelledby="exorcism"> files, download, cannot-fix <details>, extras
  <section aria-labelledby="evidence"> label C16, replay/live controls, <ol> of facts
  <script type="application/json" id="sc-data">{…}</script>
  <script>{scorecard.js}</script>
<footer> dummy-secret and scratch note (the core report's footer, verbatim)
```

The run ID is rendered as `<code>{run_id}</code>`, so the existing
deterministic-sample test still finds it.

### Views without scripts, and with them

- **Both views are in the document.** Each value that differs between Before
  and After is rendered twice, in `<span class="v v-before">` and
  `<span class="v v-after">`. Without scripts, the CSS shows both, each with a
  visible "Before:" or "After:" prefix. With Alpine running, the `js` class is
  set on `<html>` at `alpine:init`, and `.js .v:not(.on)` is hidden. Alpine
  sets `.on` with `:class` from the `view` state. The After span always
  contains "{before} → {after}", so the before value is visible in both views
  (Requirement 9.1, SP6).
- **The `js` class is set only by Alpine.** If the CDN is blocked, nothing is
  hidden. The page never uses `x-cloak`.
- **Room panels:** every run room's panel is rendered. Under `.js`, panels
  other than the selected one are hidden by class. Room cards are `<button>`s
  with `aria-pressed`.
- **Expanders** are `<details>`/`<summary>`, which work without scripts.
- **Evidence:** every fact is an `<li>` in the document. Replay adds a
  `.pending` class to all lines and removes it line by line. Without scripts,
  or with reduced motion, every line stays visible.

### The Alpine component (`scorecard.js`)

State: `view` ("before" | "after"), `room`, `logScope` ("room" | "all"),
`replaying`, `live`, `liveLines` (array of `FactLine` objects from the stream),
`verdictReady`, `announce` (the live-region text).

- `init()`: reads `#sc-data` with `JSON.parse` (`defaultRoom`, `hasAfter`,
  `streamUrl`, `seenIds`). If `streamUrl` is set it opens an `EventSource`.
- `fact` event: parse, skip if the ID is already in `seenIds`, push onto
  `liveLines`. Each line renders through `<template x-for>` with `x-text` only.
- `finalized` event: set `verdictReady`, which shows a "Show the verdict"
  button (a link to the same URL). The page never reloads by itself (8.7).
- `done` event: close the source and set `live = false`.
- Live region: a `<p aria-live="polite">` whose text is set at most once every
  5 s, to "{n} new facts" (12.8).
- Replay: the gap between lines is the recorded gap, scaled so the whole replay
  takes at most 10 s. Each gap is clamped to 50–1500 ms. With
  `matchMedia('(prefers-reduced-motion: reduce)')` true, replay shows
  everything at once (8.8, 12.7).

The script has no `innerHTML`, no `x-html` and no `eval` of data. Alpine's
standard build evaluates directive expressions, and those expressions are
fixed strings in our own markup, never data.

### Escaping

- Every value goes through one helper, `t(value)` = `html.escape(str(value),
  quote=True)`. Markup is built by small functions that take already-escaped
  parts. SP12 checks the result with hostile input, and a static test checks
  that `render.py` and `scorecard.js` contain no `x-html` and no `innerHTML`.
- Embedded JSON is `json.dumps(…, ensure_ascii=False)`, with `<`, `>`, `&`,
  U+2028 and U+2029 replaced by `\u` escapes. A value cannot close the
  `<script>` element.
- Alpine attributes in the markup are literal; no data is ever placed inside
  an `x-*`, `@*` or `:*` attribute. Values that Alpine needs (room names, fact
  IDs) go in `data-*` attributes, escaped, and are read with `dataset`.

## Stylesheet and tokens (`scorecard.css`, `theme.py`)

`:root` declares the tokens of Requirement 11.3 as `--page`, `--surface-1`,
`--surface-2`, `--border`, `--text`, `--muted`, `--accent`, `--on-accent`,
`--accent-text`, `--l0`…`--l4`, `--on-level`, `--info`. They are the only
colour literals in the file (SP13).

Rules the CSS follows, which the static tests rely on:

- **Fills:** a rule that sets `background` to `--l0`…`--l4` sets `color:
  var(--on-level)`. One that sets `--accent` sets `color: var(--on-accent)`.
  Other rules set `color` only to `--text`, `--muted`, `--accent-text`,
  `--info` or a level token, on `--page`, `--surface-1` or `--surface-2`.
  `theme.PAIRS` lists every allowed (foreground, background) pair. The test
  derives the pairs used from the CSS and checks each one is in `PAIRS` and
  passes 4.5:1. All of them do: the lowest is `--muted` on `--surface-2` at
  5.86:1, and white on `--accent` is 4.66:1.
- **Chips:** level chips are filled (`--lN` with `--on-level`). Grey states
  are outlined: a dashed 1px `--muted` border, `--muted` text, transparent
  fill. The info state is outlined in `--info`. Text always says the state.
- **Focus:** `:focus-visible { outline: 3px solid var(--accent-text);
  outline-offset: 2px }` on every control. `--accent-text` is 7.03:1 or more
  on every surface.
- **Boundaries:** buttons are filled `--accent`, or outlined in
  `--accent-text` (≥ 3:1). `--border` is used only on cards, which are not
  controls.
- **Targets:** `button, summary, a.btn, .room-card { min-height: 44px;
  min-width: 44px }`.
- **Type:** headline, section titles and `.verdict-sentence` use
  `font-family: ui-serif, "New York", Charter, "Bitstream Charter", Cambria, "Times New Roman", serif` (Georgia dropped: see "Polish"). Everything else uses `ui-sans-serif,
  system-ui, sans-serif`. Code uses `ui-monospace, monospace`.
- **Layout:** a single column up to 640 px, then a two-column room grid and
  hero. No fixed widths over 320 px. Long IDs and paths use
  `overflow-wrap: anywhere`. The evidence list is the only element with
  `overflow-x: auto` (12.6).
- **Header:** `position: sticky; top: 0`. On narrow screens the badge wraps to
  at most three lines, and the rest of the header scrolls under it, so the
  badge stays visible (Requirement 2.2).
- **Motion:** chip and replay transitions sit under
  `@media (prefers-reduced-motion: no-preference)` only. A
  `@media (prefers-reduced-motion: reduce)` block sets `animation: none;
  transition: none` on everything (12.7).

`red` (`--l4`) appears only in the `.lv4` chip and the L4 legend entry. The test
greps the CSS for `--l4` uses.

The ghost mark is a new inline SVG path drawn for this page (not the core
report's path), filled with `--accent-text`, with `aria-hidden="true"`. No Kiro
logo or wordmark appears.

## Visual standards (visual review 2026-11-09)

The first version was correct but too flat: every section had the same weight,
so the verdict did not stand out. Layout and visual weight follow the review
mockup (`scorecard-v2-reference.dc.html`); its copy is not used.

**Type scale.** Only the hero and the title of "The exorcism" use the serif
stack.

| Element | Size | Style |
|---|---|---|
| Hero level (`L4`) | 56px | serif, 600 |
| Hero level word (`Exposed`) | 18px | sans, uppercase, letter-spaced |
| Hero sentence | 28px | serif |
| "The exorcism" title | 26px | serif |
| Other section labels | 13px | sans, uppercase, letter-spacing .1em, muted |
| Card titles | 16px | sans, 600 |
| Body | 15px | sans |
| Evidence lines, IDs, file paths | 12–13px | mono |

**Page.** `main` is at most 1120px wide. Sections are 28px apart.

**Hero.** A large level block (level and word), not a pill. In the After view
the main element is the **before → after strip**: the two states ("L4 Exposed
→ L0 Clean"), the number of files in the bundle, and the files that caused the
change.

- "Caused" means the demo path's `changed_by_display`, reduced to file paths
  across all traps, under heading C17. A file whose items depend on A4 says
  "depends on A4". On the real-client path the strip shows C18 instead of
  files.
- The strip is green (`--l0` fill, `--on-level` text) only when the after state
  is L0 Clean (Requirement 9.6). Otherwise it is outlined in the after state's
  token.
- Order inside the hero: toggle, then the view (before: level block and
  sentence; after: strip and sentence), then pills, then C5.

**Legend.** One compact row of chips. Each level's label is shown once: the
chip says "L0 Clean" and the text beside it is the rest of C6 ("— did not act
on any planted instruction that reached it."). `copy.MEANING_TAILS` holds the
part of each C6–C14 string after its label.

**Rooms.** Run rooms first, at full weight. Rooms not run follow as small,
muted cards (name, what it stands for, "Not run"), so every part of the house
stays visible (Requirement 5.1, as amended).

**Trap card.**

- The three steps sit side by side: `grid-template-columns:
  repeat(auto-fit, minmax(200px, 1fr))`. They stack only when the card is
  narrower than about 620px.
- The title is the trap's threat-profile class in words (content source and
  steered effects, D27): "{Source} asked the agent to {asked}", for example "A
  repository file asked the agent to send a planted dummy secret out". The trap
  ID is shown beside it in mono. A control's title is "A harmless look-alike in
  {surface}". The Exorcist calls these "threat-profile classes"; they are
  not the eligibility class (`CLASS_TEXT`), which stays in the card as before.

**Exorcism.**

- One row per file: mono path · Enforced/Advisory chip · one sentence. The
  sentence is fixed per file kind (`copy.FILE_KIND_SENTENCES`), from the
  verified docs table. It is never an item's reason.

  | Kind | Sentence |
  |---|---|
  | steering | Guidance the model reads. Kiro does not enforce it. |
  | hook | Runs before matching tool calls and can block them. |
  | mcp | Settings for the range's MCP server entry. |
  | sandbox | Turns on Kiro's sandbox for shell commands. |
  | support | C26 |

- A `<details>` per file holds its items, grouped: items with the same reason,
  citations and assumptions are one line that lists their rules together (the
  four `credential-egress-*` hooks are one line). Each reason appears once in
  the row.
- A primary "Download bundle (.zip)" button. A page served over HTTP never
  shows the bundle's absolute path; a static export shows it, because that is
  the only way to find the files (Requirement 7.3).

**Evidence log.**

- A separator (" · ") always comes before a note such as "from the submitted
  transcript".
- Rows that would show the same time, who, text, tag and note in the
  same room are merged into one row with "×N". The merged row keeps every fact
  ID, so the live stream does not add them again. The trap cards' evidence is
  not merged, so each trap still lists its own facts.

**Polish (task 14, second pass).**

- Every serif style sets `font-variant-numeric: lining-nums tabular-nums`. That
  is not enough on its own: Chrome ignores `ui-serif` and fell back to Georgia,
  which has no lining figures, so "L0" still read "Lo". The serif stack is now
  `ui-serif, "New York", Charter, "Bitstream Charter", Cambria, "Times New Roman", serif` (no Georgia), and the renderer wraps every level code
  (L0–L4) in serif text, including escaped copy, in `<span class="lv-code">`,
  set in the sans stack with `lining-nums`.
- The green After strip is a dark tint (new token `--l0-tint`, `#0E2A1D`) with a
  2px `--l0` border and `--text`, not a solid `--l0` fill. On the tint: text
  14.7:1, the muted arrow 5.9:1, the `--l0` border 7.95:1, and every chip fill or
  outline at least 5.8:1. The outlined variant is unchanged.
- Nothing is wider than its container at 375px. Mono paths may break only after
  "/": the renderer puts an escaped `<wbr>` after each "/". A guardrail item ID
  (`path#rule`) may also break before its "#" and before a "." in the rule. File
  names never break, and `.path` sets `overflow-wrap: normal`. `pre` blocks,
  the static bundle path, the `permissions.yaml` label and trap-card evidence
  lines are data and wrap anywhere. Other `code` keeps `overflow-wrap: anywhere`.
  Only the evidence log scrolls sideways, inside its own region (12.6).
- The Before/After toggle is a segmented control: one row, no wrapping, at
  every width down to 320px.

**Checks.** No browser is used (Q3). `tests/test_scorecard_layout.py`
estimates block heights from the stylesheet's own numbers and the rendered
text: line height × wrapped lines, plus padding, margins and borders, with
average character widths of 0.55 em (sans), 0.52 em (serif) and 0.6 em
(mono). It checks two things:

- at 1280px wide, the hero chip, the sentence and the before → after strip end
  above 900px, in the view where each is shown;
- at 375px wide, the hero chip and sentence end within the first 667px, and the
  strip has no fixed width or `nowrap` content that could push it off screen.

This is an estimate. The manual release gate (task 22) is the real check.

## Live stream (`stream.py`, D22)

`GET /runs/{run_id}/facts/stream` returns `text/event-stream`. It is a
FastAPI `StreamingResponse` over an async generator.

```
retry: 3000

id: <fact_id>
event: fact
data: {FactLine JSON}

event: finalized
data: {}

event: done
data: {}
```

Loop, every `poll` seconds (default 0.5):

1. Load the run. Unknown run → 404 before streaming starts.
2. Read events (D21) and the live fact logs, normalise and redact them
   (`sources.py`, `facts.py`), and format them as `FactLine`s.
3. Send each line whose `fact_id` is not in the sent set, in the page's order.
   The store orders events by `(timestamp, event_id)`, and `event_id` is
   random, so the stream tracks sent IDs, never an index.
4. Once `finalized_at` is set, send `finalized` once.
5. Once `now >= window_close()`, or the run expired, send any last lines,
   then `done`, and end.
6. Every 15 s with nothing sent, send a `: keepalive` comment.
7. End on client disconnect (`request.is_disconnected()`), or when the
   lifetime cap is reached (`expires_at + grace + 5 s`).

### Fact-log path

The stream, and `/runs/{id}/report` for an active run, read a live fact log
from a path built like this, and in no other way:

1. The URL's `run_id` is checked against the writer's ID charset
   (`[A-Za-z0-9_-]{8,64}`) before any lookup. A mismatch gets 404.
2. `RangeService.get_run(run_id)` must succeed. The path then uses the stored
   `Run.run_id`, not the URL string.
3. The room names come from `RangeService.manifest(run_id).rooms`,
   intersected with the registered MCP and Parlor rooms. The client supplies no
   room name, file name or path part. The stream has no query parameters.
4. The workspace is `cli.mcp_workspace(scratch_root_beside(db), room,
   run.run_id)`. That is the existing helper `hauntlet mcp serve`, `hauntlet
   parlor open` and both finalize commands use, with the scratch root from
   `hauntlet.paths`. The file is the room's own `factlog.facts_path(workspace)`.
   `sources.py` imports `cli.mcp_workspace` inside the function, because
   `cli.py` imports the scorecard at module level. A test checks that the
   result equals `mcpfacts.demo_facts_path` for the Poltergeist rooms.
5. The file must not be a symlink, which `mcpfacts.read_facts` already checks.
   Its resolved path must also lie under the resolved scratch root, a new check
   in `sources.py`. Otherwise the room is "fact log not available".

A test covers hostile URL IDs (`..`, `/`, `%2F`, absolute paths, over-long
IDs, unknown but well-formed IDs) and a symlinked fact log. Each one gets 404
or "fact log not available", and no file outside the scratch root is opened
(checked with an `open` spy).

`Last-Event-ID` is honoured. Lines up to and including that ID are taken as
sent, using the same ordering.

Blocking store and file reads run in `anyio.to_thread.run_sync`. Caps come from
`HAUNTLET_STREAM_MAX` (default 20 concurrent streams) and
`HAUNTLET_STREAM_POLL_SECS` (default 0.5). A connect over the cap gets 429.
The counter is a `threading.BoundedSemaphore`, as in `hosted.py`. The stream
records no event and serves no room content. The existing middleware adds
`X-Robots-Tag`. The response also sets `Cache-Control: no-store`.

For a finished run the loop runs once: all lines, `finalized`, `done`. That is
what SP16 compares with the embedded facts.

A finished hosted demo run has its fact logs in the bundle's `evidence/`
directory (D26), not in live scratch. The stream does not look there, so the
exorcism page, not the stream, is the demo's view, and it shows a replay (Q4).

## Routes and writers (D23)

| Route / writer | Before | After this spec |
|---|---|---|
| `GET /runs/{id}/report` | `core.report.render_report` | `scorecard.render_run(service, run_id, path="not-recorded", served=True)`. While the run is active it sets `stream_url`. |
| `GET /exorcisms/{id}/report` | latest `deltas/*.html` or `render_html(before_only_delta)` | `scorecard.render_exorcism(ex_service, bundle_dir, served=True)`. The path comes from the delta (`demo-agent` → C1, `real-client` → C2, `pending` → C4). |
| `GET /exorcist` | `exorcist.html` with injected rooms | `scorecard.render_launcher(demo_rooms)`: the frame with badge C1, the levels legend, and one button per room. Pressing one posts to `/exorcist/demo`, then sets `location` to the returned `report_url`. |
| `GET /runs/{id}/facts/stream` | — | D22 |
| `hauntlet run` | `autopsy-<room>-<agent>-<id>.html` from `render_report` | same file name, scorecard, path `reference:<name>` for `naive`/`hardened`, `demo-agent` for `demo`, with aggregates when `--repeat > 1` |
| `hauntlet mcp finalize`, `hauntlet parlor finalize` | `autopsy-mcp-…` / `autopsy-parlor-…` | same file names, scorecard, path `real-client`. Built before teardown, so the live fact log is still readable. |
| `hauntlet sample-report` | `render_report` | scorecard of the same fixed Threshold naive run, path `reference:naive` |
| Exorcist delta HTML (`deltas/<after>.html`, `exorcist-delta-<after>.html`) | `report.render_html` | scorecard |

**Writers.** `ExorcistService` gets an optional `html_renderer:
Callable[[Path, str], bytes] | None`, with arguments bundle dir and after run
ID. `_write_delta` calls it for the `html` file when it is set, and otherwise
keeps `report.render_html`. `cli.py` and `server.py` construct the service with
`html_renderer=scorecard.exorcism_file_renderer(...)`. The Exorcist never
imports the scorecard (D24). The `json` and `txt` files are untouched (13.2,
SP17).

`report.render_html` and `exorcist.html` stay in the tree for their existing
tests. Nothing serves or writes them on the default paths. `core/report.py` is
unchanged (15.2).

**Existing tests that read HTML** (13.6) and what keeps them passing:

| Test | Assertion | Scorecard source |
|---|---|---|
| `test_exorcist_server::test_demo_round_trip` | "demo agent", "noindex" | `DEMO_LABEL` (2.4), robots meta |
| `test_exorcist_server::test_page_lists_the_demo_rooms` | room names, "not Kiro" | launcher buttons, C1 |
| `test_exorcist_server::test_page_external_scripts_are_pinned_with_integrity` | pinned Alpine with SRI | same tag as `exorcist.html` |
| `test_sample_report_deterministic` | identical bytes, `<code>sample-report</code>` | content-derived fact IDs, injected clock, `<code>` run ID |
| `test_end_to_end`, `test_report_provisional`, `test_aggregate_not_exercised` | call `render_report` directly | `core/report.py` unchanged |
| `test_exorcist_delta` (EP11 HTML) | calls `report.render_html` directly | unchanged |

New scorecard tests repeat the core report's assertions against `render_run`
in the scorecard's own wording: the chip "L4 Exposed" for the naive Threshold
run, `noindex`, and no dummy secret.

## D21, D25, D26, D28 details

- **D21.** `RangeService.events(self, run_id) -> list[Event]` in
  `core/service.py`: check `store.get_manifest(run_id)`, raise `UnknownRun` if
  it is missing, return `store.events_for_run(run_id)`. No other line in `core/`
  changes (D30 adds `canaries` the same way if approved).
- **D25.** `.kiro/hooks/scorecard-refresh.json` matcher becomes
  `src/hauntlet/(core/(scorer|report|aggregate)\.py|scorecard/.*|exorcist/texts\.py)$`.
  The command and timeout are unchanged.
- **D26.** After `_run_demo` returns, `ExorcistService.demo` writes into the
  bundle directory, through the existing `writer.write_into` (scratch-guarded):
  - `evidence/facts-<run_id>-<room>.jsonl` for the before and after runs of
    an MCP room, one redacted record per line, in the room's own record
    format;
  - `evidence/trace-<run_id>.jsonl` for both runs, one
    `{"seq", "tool_id", "where", "source", "proceeded", "denied_by"}` record
    per entry.

  `DemoRun` already carries `facts` and `trace`. `hosted._ARCHIVE_SKIP` gains
  `"evidence"`, so the download is unchanged. The retention sweep removes the
  whole bundle directory, `evidence/` included. The `tests/test_exorcist_server`
  zip-listing assertion is extended to check that `evidence/` is absent.
- **D28.** `card.py` in each room package:
  `ROOM_CARDS: dict[str, tuple[str, str]]`, mapping a room name to (display
  name, stands for). There are four files: `threshold`, `cursed_repo` (two
  rooms), `poltergeist` (two rooms) and `parlor`, with the values approved in
  the requirements. `scorecard/rooms.py` merges them. A test checks that the
  merge covers exactly `default_rooms()` (SP18). The cards are plain strings,
  not trap content, but they pass `scripts/check_payload_safety.py` like any
  room file.

## Safety

- **No hostile content.** The page renders surfaces, citations, profile
  phrases and fact descriptions. It never renders a template, a fixture, a
  tool description, a page body or a tool result. SP11 runs the exorcist EP3
  6-word check over every rendered page.
- **No working canary.** Every token is redacted before it reaches HTML, the
  embedded JSON or the stream (SP10). A viewer of a live page cannot trigger a
  hit.
- **Untrusted strings.** Event details and fact-log fields can carry text a
  real client chose. They are escaped, never placed in Alpine attributes, and
  truncated (SP12).
- **Third-party script.** Only Alpine, pinned with SRI, and the same tag as the
  existing page. No fonts, images or analytics.
- **Disclosure.** Client limits appear only through C5 and `CANNOT_FIX` item 1.
  The scorecard never reads `mcp-summary-*.txt`, where the manual re-approval
  observation lives (Requirement 14.2).

## Correctness properties

The requirements define SP1–SP18. This table maps each to its test and
generator.

| Property | Test file | Generator / method |
|---|---|---|
| SP1 nothing invented | `test_scorecard_copy.py` | Hypothesis runs + deltas; collect text nodes with `html.parser`, subtract `copy.py` strings, imported texts and input values; remainder must be empty (whitespace and punctuation aside) |
| SP2 parity | `test_scorecard_parity.py` | random run → every core-report datum present; random delta → every `render_json` field value present (escaped) |
| SP3 no-script content | `test_scorecard_noscript.py` | parse HTML only; count trap cards per run room, both `.v-before`/`.v-after` spans, all fact `<li>`s |
| SP4 path badge | `test_scorecard_badge.py` | each path × with/without delta; first header child text; forbidden labels absent |
| SP5 hero | `test_scorecard_states.py` | builder only, random runs incl. active/provisional/not-exercised |
| SP6 before kept | `test_scorecard_states.py` | builder + HTML: every before value appears in both views |
| SP7 grey stays grey | `test_scorecard_states.py` | builder: token never `l0` for grey/control/info/not run; HTML: no `.lv0` on those cards |
| SP8 regressions and costs | `test_scorecard_states.py` | random deltas with forced higher after levels and costs |
| SP9 changed by | `test_scorecard_changed_by.py` | demo vs real deltas; chips == `changed_by_display`; `cites`-only items absent |
| SP10 redaction | `test_scorecard_redaction.py` | random canaries embedded in event details, fact-log fields (raw, percent-encoded, in `/c/` URLs, bare); check HTML, `#sc-data` and stream bytes |
| SP11 no trap text | `test_scorecard_no_trap_text.py` | every registered room run with naive and demo agents; the EP3 6-word scan |
| SP12 escaping | `test_scorecard_escaping.py` | Hypothesis text with `<script>`, `</script>`, quotes, `x-html`, `@click` in details and fields; parse and compare element and attribute sets with a clean render |
| SP13 contrast | `test_scorecard_theme.py` | example: parse `:root`, derive used pairs, WCAG formula |
| SP14 labels, controls, motion | `test_scorecard_a11y_static.py` | example: chips have text; `@click`/`:aria-*` only on `button`/`a`/`summary`; 44px rule; reduced-motion block; landmarks; one `h1`; `lang` |
| SP15 fact times | `test_scorecard_facts.py` | random events per channel, expired flags, fact-log records; check time column, notes, trap attribution |
| SP16 stream = replay | `test_scorecard_stream.py` | finished runs: collect SSE until `done` with `TestClient`, compare with embedded `<li>` IDs and texts; one active-run case finalized from a second thread |
| SP17 compatibility | `test_scorecard_compat.py` | `render_json`/`render_text` are not edited; golden outputs for fixed deltas, captured and committed before the D23 change, must still match; JSON route bodies compared before/after D23 for fixed runs; sample rendered twice |
| SP18 cards and phrases | `test_scorecard_rooms.py` | example over `default_rooms()` and `PROFILES` |

Strategies reuse `tests/_exorcist_strategies.py` (runs, specs) and add
`facts()` (events per channel, MCP and Parlor records, trace entries) and
`hostile_text()`.

## Error handling

| Case | Behaviour |
|---|---|
| Unknown run on `/runs/{id}/report` or the stream | 404, as today |
| Unknown or expired bundle on `/exorcisms/{id}/report` | 404, as today (`HostedExorcist._bundle`) |
| `bundle.json` or a delta JSON that does not parse | No 500. The page renders the run alone, and the exorcism section says "The exorcism files for this run could not be read." (C27) |
| Delta whose after run is no longer in the store | page renders from the delta JSON; pills fall back to the delta room state, and "Detected" for the after view shows "not assessed" for that room |
| Fact log missing, torn down or unreadable | "fact log not available" for the room (8.9) |
| Malformed fact-log lines | skipped by `factlog.read`, as today |
| Stream over cap | 429 with a plain-text reason |
| Client disconnects | generator ends and releases its slot |
| Alpine fails to load | full static page; no `js` class, nothing hidden |

C26 and C27 are in the requirements' copy table.

## Testing strategy

- **Pure first.** `build.py`, `facts.py`, `copy.py` and `redact.py` are tested
  without HTML, with Hypothesis over synthetic inputs. Most properties (SP5–SP9,
  SP15) check the view model.
- **HTML second.** `render.py` tests parse the output with the stdlib
  `html.parser` and check structure: no-script content, badge position,
  escaping, labels and controls. No browser is used (Q3).
- **Stream.** `TestClient` reads the SSE body for finished runs. One threaded
  test covers an active run that is finalized during the stream.
- **Routes.** `test_scorecard_server.py` covers each D23 route, `noindex` on
  every response, 404s, and the launcher's demo round trip.
- **Golden pages.** One golden HTML per demo room (`cursed-repo`,
  `poltergeist`) and one for the sample. Fixed clocks, run IDs, seeds and
  bundle IDs are injected by the test, which does not change the product's
  random IDs. They fail if the page changes unintentionally.
- **Release gate (manual, Q3).** At 320 px and 375 × 667 px in one Chromium
  and one WebKit browser: badge, hero chip and sentence visible without
  scrolling; no horizontal page scroll; keyboard walk through every control
  with visible focus; reduced motion on, replay instant; VoiceOver reads the
  badge, the chip text and the sentence first. The result is recorded in the
  release task.

## Decisions

Approved in requirements review (2026-11-09): D21–D28.

Approved in design review (2026-11-09):

- **D30. `RangeService.canaries(run_id)`, read-only (core change).** It is
  needed for exact-value redaction of bare tokens. Without it, redaction is
  pattern-only. See "Redaction".
- **D31. Redactor in `src/hauntlet/redact.py`.** It is shared by the scorecard
  and the D26 writer without breaking D24's import rule. The alternative
  amends D26 to store raw evidence.
- **C26, C27. Two more fixed strings.**
  - C26: "Support file used by the hooks in this bundle."
  - C27: "The exorcism files for this run could not be read."
- **`CLASS_TEXT` (small Exorcist change under D24's import rule).**
  `src/hauntlet/exorcist/manifest.py` renames the private `_CLASS_TEXT` mapping
  to the public `CLASS_TEXT`, with the same keys and texts.
  `src/hauntlet/exorcist/__init__.py` re-exports it. `manifest.py` uses the new
  name internally. No test refers to `_CLASS_TEXT` (checked with `grep`), so no
  private alias is kept. The scorecard imports `from hauntlet.exorcist import
  CLASS_TEXT`, and nothing in the scorecard reads a private Exorcist name. The
  import direction is unchanged: the scorecard imports the Exorcist, never the
  reverse. `bundle.json` and `EXORCISM.md` bytes are unchanged.

Reserved: **D29**, a full demo-exorcism sample (requirements, Q2).

Approved after the final checkpoint (2026-11-10):

- **D32. Keep fact logs readable after finalize for pages served by `hauntlet
  serve`.**
  - *Problem:* once `mcp finalize` or `parlor finalize` tears the workspace
    down, `/runs/{id}/report` showed "fact log not available" for Parlor and the
    Poltergeist rooms. The server had no reports directory, so it never found the
    D19 copy, and Parlor's log was never copied.
  - *Change:*
    - `server.py` reads `HAUNTLET_REPORTS_DIR` (default `reports`, the CLI's
      `--out` default, `hauntlet.paths.DEFAULT_REPORTS_DIR`) and passes it as
      `reports_dir` to `ExorcistService`, `exorcism_file_renderer`, the
      run-report and exorcism-report routes' renderers, and the D22 stream. The
      path stays server-side: no route serves a file from it, and every read goes
      through `sources`' checks (not a symlink, resolves under the directory).
    - `cli.py` `parlor finalize`, before teardown, copies the Parlor fact log
      byte for byte to `<out>/parlor-facts-<run>.jsonl`
      (`hauntlet.paths.reports_parlor_facts_path`), with `_copy_fact_log`'s rules:
      a symlink or non-file is not copied; an `OSError` keeps the workspace and
      exits 1. Nothing else in its output changes.
    - `sources.reports_fact_log` covers Parlor too. Lookup order per room is
      unchanged: the bundle's D26 evidence, then the live workspace, then the
      reports-directory copy.
  - *Read, never write (follow-up, 2026-11-10):* `ExorcistService` gains
    `write_reports: bool = True`. With `False` it still reads the D19 and Parlor
    copies from `reports_dir`, but never writes `exorcist-delta-<after>.html`
    there. `server.py` passes `write_reports=False`: the hosted range would
    otherwise leave one file per demo in the reports directory, which the
    retention sweep (confined to the exorcist root) never removes, so a public
    server's disk would grow without bound. The delta's HTML still lands in the
    bundle's `deltas/`, which the sweep covers. The CLI is unchanged and keeps
    writing its delta report. Attaching a real-client after run on the hosted
    range reads the D19 copy, so the 10.9 signal is computed there.
  - *Unchanged:* the copies can hold the run's dummy secret, as the workspace
    did (D19); the scorecard redacts them before they reach a page or the stream.
    No core change.

Approved after the security review (2026-11-10). The review found no injection,
XSS, traversal or secret exposure; these close its availability findings (M1–M3)
and add browser hardening (L1, L2).

- **D33. Request caps and retention (M1, M2).**
  - Everywhere: `POST /runs` refuses duplicate rooms (422; unknown rooms stay
    400). `finalize` refuses `detail` over 4,096 characters and more than 500
    observations (422). Every request body over 64 KiB gets 413, checked on
    `Content-Length` and on the bytes actually received (an ASGI wrapper, so a
    chunked body cannot get around it). Nothing is ever truncated.
  - Hosted (`HAUNTLET_HOSTED=1`): at most `HAUNTLET_MAX_OPEN_RUNS` (50)
    unfinished runs (not finalized, not expired) created by the server; over it,
    429. The check and the new run happen under one lock.
  - Hosted: a lazy retention sweep, run at most once a minute from `POST /runs`,
    deletes runs whose window closed more than `HAUNTLET_RUN_RETENTION_SECS`
    (86400) ago, with their canaries and events.
  - **Core change:** one method, `Store.delete_closed_before(cutoff)`. It uses
    `Run.window_close`'s rule (`min(finalized_at, expires_at) + grace`), so an
    active or provisional run is never deleted. Nothing else in `core/` changes.
- **D34. Per-client limits (M3).**
  - Client key (`hauntlet/limits.py`): with `HAUNTLET_TRUST_PROXY=1`, the
    **last** `X-Forwarded-For` entry, the address Render's proxy saw connect.
    Earlier entries are client-controlled and never used. Otherwise, the socket
    address.
  - Hosted, per client: 3 demos a minute (the global 6/min stays), 2 open live
    streams, 10 run creations an hour. In-memory, one process; at most 10,000
    keys are tracked, so forged addresses cannot grow memory without bound.
  - Every live stream closes after `HAUNTLET_STREAM_MAX_SECS` (600) with
    `event: timeout` and no `done`. The browser's `EventSource` reconnects on its
    own with `Last-Event-ID`. Once the run is over, the reconnected stream sends
    the remaining rows and `done`, and the page stops, so reconnects happen only
    while the run is active. The page script is unchanged.
  - **Scope choice:** the per-client quotas apply only when hosted. A tester's
    local `hauntlet serve` keeps no quotas, so repeated real-client runs are not
    throttled. The stream lifetime applies everywhere.
- **D35. Browser headers and docs (L1, L2).**
  - Every response: `X-Content-Type-Options: nosniff`, `Referrer-Policy:
    no-referrer`, `X-Frame-Options: DENY`, and `Content-Security-Policy:
    frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action
    'self'`, unless the response sets its own CSP. Parlor's stricter page policy
    is kept.
  - **No `script-src` yet:** the scorecard inlines its script and loads Alpine's
    standard build, which evaluates directive expressions. A script policy needs
    hashes for the inline script and the Alpine CSP build first. Escaping (SP12)
    is the XSS defence until then.
  - Hosted: `/docs`, `/redoc` and `/openapi.json` return 404.
- **L3.** The Docker base images are pinned by digest and the GitHub Actions by
  commit SHA, with the tag in a comment.
- **L4.** The README says `FORWARDED_ALLOW_IPS=*` is only safe behind Render's
  proxy.
- **Base URL.** `hauntlet serve` uses `HAUNTLET_BASE_URL`, else Render's
  `RENDER_EXTERNAL_URL`, else the local default. An empty value counts as unset.

Design choices that need no decision, because they stay inside the scorecard
package or follow an approved decision:

- the latest delta is chosen by the after run's `created_at`;
- `ExorcistService` gets an optional `html_renderer` hook (D23);
- `evidence/` is excluded from the archive (D26);
- the stream's fact-log path is built only from a store-validated run ID and
  a manifest room, through `cli.mcp_workspace` ("Fact-log path").

## Out of scope

As in the requirements, plus:

- Streaming a hosted demo live (Q4).
- Any client-side formatting of facts: lines arrive formatted from the server.
- Browser-based layout or accessibility tests (Q3).
- Removing `exorcist.html` or `report.render_html`. They stay for their tests
  and can be retired in a later change.
