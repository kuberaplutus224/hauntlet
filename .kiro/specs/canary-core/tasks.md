# Implementation Plan — canary-core

- [x] 1. Levels, signals and data models
  - `core/levels.py`: `Level` (L0–L4), `Signal`, `Channel`, `level_of()`
  - `core/models.py`: manifests, `Run`, `Canary`, `Event`, score types, JSON helpers
  - _Requirements: 2.1–2.5_

- [x] 2. Canary minting
  - `core/canary.py`: url / secret / marker canaries per trap; controls get url only
  - Dummy secret format `HAUNTLET-DUMMY-<run8>-<trap>-<nonce>`
  - _Requirements: 1.1, 5.1_

- [x] 3. SQLite store
  - `core/store.py`: runs, canaries, events tables; append-only events
  - _Requirements: 1.1, 1.2_

- [x] 4. Pure scorer with golden tests
  - `core/scorer.py`: `score_run(events, manifest)`
  - `tests/test_scorer_golden.py` + fixtures
  - _Requirements: 1.3, 1.4, 2.1–2.9, 3.2, 3.3_

- [x] 5. Property-based tests for the scorer
  - P1–P5 from design.md in `tests/test_scorer_properties.py`
  - _Requirements: 2.6, 2.9, 3.3, 1.3_

- [x] 6. pass^k aggregation
  - `core/aggregate.py`: compromise rate, clean rate, pass^k, worst run; P6
  - _Requirements: 4.1, 4.2_

- [x] 7. Range service
  - `core/service.py`: `start_run`, `record_hit` (reached / exposed / expired), `finalize`, `score`
  - _Requirements: 1.1–1.4, 2.1, 2.4_

- [x] 8. Room protocol, sandboxed toolbox and stub room
  - `core/room.py`, `core/toolbox.py`, `rooms/threshold/`
  - _Requirements: 3.1, 5.2, 5.5_

- [x] 9. Payload safety checker
  - `scripts/check_payload_safety.py` + test over all templates; wired to the `payload-guard` hook
  - _Requirements: 5.3_

- [x] 10. Reference agents and local runner
  - `agents/naive.py`, `agents/hardened.py`, `core/runner.py`
  - _Requirements: regression anchors_

- [x] 11. Autopsy report renderer
  - `core/report.py`: self-contained HTML + JSON
  - _Requirements: 6.1–6.3_

- [x] 12. HTTP server and CLI
  - `server.py` (`/health`, `/runs`, `/c/{token}`, `/runs/{id}/finalize`, `/score`, `/report`), `noindex` on every response
  - `cli.py`: `run`, `selftest`, `serve`, `sample-report`
  - _Requirements: 5.4, 6.3_

- [x] 13. Timestamp-derived run window
  - [x] 13.1 Update `Run` model and `Event` model in `core/models.py`
    - Remove `status: str` field; add `finalized_at: float | None = None` and `grace_window_secs: float = 30`
    - Add `window_close(self) -> float` property: `(min(self.finalized_at, self.expires_at) if self.finalized_at is not None else self.expires_at) + self.grace_window_secs`
    - Add derived `is_active(now)`: `finalized_at is None and now < expires_at`
    - Add derived `is_provisional(now)`: `now < self.window_close()`
    - Add `late_by_secs: float = 0.0` field to `Event`
    - _Requirements: 1.3_
  - [x] 13.2 Migrate `core/store.py` schema and accessors
    - Replace `status TEXT` column with `finalized_at REAL` (nullable) and `grace_window_secs REAL NOT NULL DEFAULT 30`
    - Add `late_by_secs REAL NOT NULL DEFAULT 0` to events table
    - Update `add_run`, `get_run`, `update_run`, `append_events`, `events_for_run` to reflect new schema
    - _Requirements: 1.3_
  - [x] 13.3 Update `core/service.py` expiry stamping
    - In `record_hit`, replace `run.is_active(now)` with `run.window_close()` arithmetic; stamp `expired = (now >= run.window_close())` and `late_by_secs = max(0.0, now - run.window_close())`
    - In `start_run`, remove `status="active"` from `Run` construction; accept optional `grace_window_secs` kwarg (default 30) and pass it through
    - _Requirements: 1.3_
  - [x] 13.4 Write tests in `tests/test_run_window.py`
    - Verify `window_close` formula for finalized and unfinalized runs
    - Verify events recorded before `window_close` get `expired=False, late_by_secs=0`
    - Verify events recorded at or after `window_close` get `expired=True` and correct `late_by_secs`
    - _Requirements: 1.3_
  - [x] 13.5 Set grace_window_secs=0 in the local runner and CLI
    - In `core/runner.py`, pass `grace_window_secs=0` when calling `service.start_run`; in-process canary fetches complete before `finalize` is called, so local scores are always final immediately
    - In `cli.py`, pass `grace_window_secs=0` for any `start_run` calls it makes directly
    - _Requirements: 1.3_

- [ ] 14. RunScore.provisional and late_events
  - [ ] 14.1 Add `LateEvent` and update `RunScore` in `core/models.py`
    - Add new frozen dataclass `LateEvent(trap_id: str, signal: str, late_by_secs: float)`
    - Add `provisional: bool = False` and `late_events: tuple[LateEvent, ...] = ()` to `RunScore`
    - _Requirements: 1.3, 7.1_
  - [ ] 14.2 Update `core/scorer.py` to populate `late_events`
    - Keep `score_run`'s signature unchanged: `score_run(events, manifest) -> RunScore`
    - Collect expired admissible-by-manifest events into `late_events` as `LateEvent` instances; expired events still increment `ignored_events` AND are also listed in `late_events`
    - The returned `RunScore` always has `provisional=False`; the service sets the correct value with `dataclasses.replace(score, provisional=run.is_provisional(now))` after calling `score_run`
    - _Requirements: 1.3, 7.1_
  - [ ] 14.3 Thread `provisional` and `finalized_at` through `core/service.py`
    - In `finalize`, set `run.finalized_at = now` via `store.update_run`; derive `provisional = run.is_provisional(now)` and pass it to `score_run`
    - In `score` (re-score path), also derive and pass `provisional`
    - _Requirements: 1.3, 7.1_
  - [ ] 14.4 Write tests in `tests/test_scorer_provisional.py`
    - Verify `RunScore.provisional=True` when scored before `window_close`
    - Verify `RunScore.provisional=False` after `window_close`
    - Verify `late_events` contains correct `LateEvent` entries for expired events
    - _Requirements: 1.3, 7.1_

- [ ] 15. Manifest validation at construction and finalize rejections
  - [ ] 15.1 Add `InvalidRoom` exception and `_validate_manifest` helper; wire into `RangeService.__init__`
    - Define `class InvalidRoom(ValueError)` in `core/service.py`
    - `_validate_manifest(room_name: str, manifest: RoomManifest)` raises `InvalidRoom` naming the room and the failed rule for each invalid variant: (a) no `is_control=True` trap; (b) no `is_control=False` trap; (c) duplicate trap IDs; (d) any trap ID equals `"__task__"`; (e) any non-control trap has an empty `source`
    - In `RangeService.__init__`, call `_validate_manifest(name, room.manifest())` for every room passed in
    - _Requirements: 3.1_
  - [ ] 15.2 Replace status-based guard in `finalize` with timestamp checks
    - If `run.finalized_at is not None`, raise `InvalidObservation("already finalized")`
    - If `now >= run.window_close()`, raise `InvalidObservation("run closed")`
    - _Requirements: 1.3_
  - [ ] 15.3 Write tests in `tests/test_service_validation.py`
    - One test per invalid manifest variant (a)–(e) asserting `InvalidRoom` is raised at construction
    - One test that a fully valid manifest is accepted
    - One test that re-finalizing a finalized run raises
    - One test that finalizing after `window_close` raises with "run closed"
    - _Requirements: 3.1, 1.3_
  - [ ] 15.4 Update existing tests and server responses broken by the status-to-timestamps migration
    - In `tests/test_service.py` (or equivalent), update any tests that assert behaviour for hits after `finalize` or after TTL expiry to use timestamp comparisons instead of checking `run.status`
    - In `server.py`, replace any `run.status` field in `/runs` and `/runs/{id}` JSON responses with `finalized_at` and a computed `window_close` value
    - _Requirements: 1.3_

- [ ] 16. Report: provisional banner, late-arrivals section, Detected-not-assessed tag
  - [ ] 16.1 Add provisional banner to `core/report.py`
    - `render_report` reads `score.provisional` from the `RunScore` it already receives; no new kwargs needed
    - When `score.provisional` is `True`, render a styled `<div>` banner "Score provisional — grace window still open" between the verdict panel and room panels
    - _Requirements: 1.3, 7.1_
  - [ ] 16.2 Add late-arrivals section to `core/report.py`
    - `render_report` reads `score.late_events` from the `RunScore` it already receives; no new kwargs needed
    - When `score.late_events` is non-empty, render a "Late arrivals (not scored)" section listing each entry's trap ID, signal, and `late_by_secs` formatted as e.g. "12.3 s after grace window closed"
    - _Requirements: 7.1_
  - [ ] 16.3 Fix "not assessed" tags and update callers
    - Change the per-room L2 tag text from `"L2 not assessed (no transcript)"` to `"L2 and Detected not assessed (partial or absent transcript)"`
    - The Detected tag follows three cases based on `room.detected` and `room.l2_assessed`:
      - `room.detected=True` (any `l2_assessed`): show `"detected the attempt"` — findings in a partial transcript always count (Req 2.7)
      - `room.detected=False` and `room.l2_assessed=False`: show `"Detected: not assessed"` — no transcript, cannot determine
      - `room.detected=False` and `room.l2_assessed=True`: show `"did not report the attempt"` — full transcript assessed, nothing flagged
    - `render_report` callers are `cli.py` and `server.py`; no changes needed in `service.py`
    - _Requirements: 2.7, 7.1_
  - [ ] 16.4 Write tests in `tests/test_report_provisional.py`
    - Verify the provisional banner appears when `provisional=True` and is absent when `False`
    - Verify the late-arrivals section lists entries correctly
    - Verify the three Detected tag cases:
      - `room.detected=True, l2_assessed=False`: tag reads `"detected the attempt"`
      - `room.detected=False, l2_assessed=False`: tag reads `"Detected: not assessed"`
      - `room.detected=False, l2_assessed=True`: tag reads `"did not report the attempt"`
    - _Requirements: 1.3, 2.7, 7.1_

- [ ] 17. Payload guard literal-assignment rule
  - [ ] 17.1 Add literal-assignment rule to `scripts/check_payload_safety.py`
    - Add a new entry to `RULES` matching bare literal assignments of `password`, `secret`, `token`, or `api_key` (case-insensitive), e.g. `password=foo`, `"secret": "abc"`, `api_key = xyz`
    - Must NOT match when the value starts with `{` or `<` (placeholder references)
    - _Requirements: 5.3_
  - [ ] 17.2 Write tests in `tests/test_payload_guard.py`
    - Assert the new rule fires on `password=hunter2`, `"secret": "abc"`, `api_key=sk-real`
    - Assert it does NOT fire on `password={marker}`, `token=<placeholder>`, `secret={trap_url}`
    - _Requirements: 5.3_

- [ ] 18. Property-based tests P7, P8, P9
  - [ ] 18.1 Write P7 — Expiry boundary in `tests/test_scorer_properties.py`
    - **Property 7: Expiry boundary**
    - Generate a valid event and a `window_close` timestamp; assert that when `event.timestamp < window_close` the event scores normally; when `event.timestamp >= window_close` the event is excluded and appears in `RunScore.late_events`
    - **Validates: Requirements 1.3**
  - [ ] 18.2 Write P8 — Manifest validation in `tests/test_scorer_properties.py`
    - **Property 8: Manifest validation**
    - For each invalid manifest variant (missing control, missing non-control, duplicate IDs, reserved `__task__` ID, empty `source` on non-control), assert `RangeService.__init__` raises; assert a fully valid manifest is accepted without error
    - **Validates: Requirements 3.1**
  - [ ] 18.3 Write P9 — Partial transcript in `tests/test_scorer_properties.py`
    - **Property 9: Partial transcript**
    - Generate a run with an L2-triggering event and `transcript_provided=False`; assert findings count (level is L2), `l2_assessed=False`, and `RunScore` does not claim Detected is assessed
    - **Validates: Requirements 2.7**

## Notes

- Each task references specific requirements for traceability
- Tasks 13–14 must be completed in order (14 depends on 13's model changes)
- Task 15.2 depends on Task 13's removal of the `status` field
- Task 16 depends on Task 14's `LateEvent` and `provisional` types

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["13.1"] },
    { "id": 1, "tasks": ["13.2", "13.3", "13.5"] },
    { "id": 2, "tasks": ["13.4", "14.1"] },
    { "id": 3, "tasks": ["14.2", "14.3", "15.1", "15.2"] },
    { "id": 4, "tasks": ["14.4", "15.3", "15.4", "16.1", "16.2", "17.1"] },
    { "id": 5, "tasks": ["16.3", "16.4", "17.2"] },
    { "id": 6, "tasks": ["18.1", "18.2", "18.3"] }
  ]
}
```
