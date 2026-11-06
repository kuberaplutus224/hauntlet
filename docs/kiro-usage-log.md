# Kiro usage log

A dated, factual record of how the project was built, for the Kiroween write-up.
The `kiro-usage-log` Stop hook appends to this file from Kiro sessions.

- 2026-11-05 — Repo scaffold created **outside Kiro** (Claude Code): MIT license,
  `.kiro/steering` (product, tech, safety-rules), `.kiro/specs/canary-core`
  (requirements, design, tasks), five hooks in `.kiro/hooks`, and a first
  implementation of canary-core tasks 1–12 with golden and Hypothesis
  property-based tests. Planning inputs came from `hauntlet-plan/`. Next step:
  open the repo in Kiro, run Analyze Requirements and Correctness (PBT) on the
  canary-core spec, and drive the remaining specs through Kiro.
- 2026-11-05 — Implemented canary-core task 13 (timestamp-derived run window): updated `Run`/`Event` models, migrated SQLite schema, updated `RangeService` expiry stamping, set `grace_window_secs=0` in local runner, wrote 10 tests in `test_run_window.py` — spec / task execution (Kiro spec task agent) / hooks
- 2026-11-05 — Implemented canary-core task 14 (RunScore.provisional and late_events): added `LateEvent` dataclass and `provisional`/`late_events` fields to `RunScore` in models.py, updated scorer.py to collect expired events into late_events, threaded provisional flag through service.py finalize and score paths, wrote 6 tests in test_scorer_provisional.py — spec / task / hook
- 2026-11-05 — Fixed order-invariance bug in scorer.py (sorted late_events by trap_id/signal/late_by_secs, refactored _admissible to delegate to _admissible_ignoring_expiry); simplified service.py finalize to drop redundant provisional calc; extended P3 property test to cover expired events — hook / PBT
- 2026-11-06 — Implemented canary-core task 15 (manifest validation and finalize rejections): added `InvalidRoom` exception and `_validate_manifest` helper wired into `RangeService.__init__`, replaced status-based finalize guard with timestamp checks, wrote 8 tests in `test_service_validation.py`, updated server.py to return `finalized_at`/`window_close` instead of legacy status field — spec / task
- 2026-11-06 — Added grace_window_secs field to POST /runs, added RunClosed(InvalidObservation) exception, mapped finalize rejections to HTTP 409, added three server tests — steering / hook
