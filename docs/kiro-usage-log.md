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
