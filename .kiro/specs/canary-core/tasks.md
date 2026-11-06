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
