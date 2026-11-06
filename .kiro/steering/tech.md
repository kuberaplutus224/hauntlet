---
inclusion: always
---

# Tech

Stack is decided: **Python 3.12 end-to-end**, managed with `uv`. Keep it boring
and demo-friendly.

- **Core + rooms:** Python. FastAPI + uvicorn (server), stdlib `sqlite3` (event
  store), pytest + Hypothesis (golden and property-based tests), the official
  `mcp` SDK (Poltergeist). The scorer is a pure, I/O-free module.
- **Scorecard UI:** static HTML + Alpine.js, live updates over SSE. No build step.
- **Layout:** `src/hauntlet/core/` owns runs, canaries, events, scoring and the
  report. Rooms live in `src/hauntlet/rooms/<name>/` and only produce materials
  and events; they never decide a score.
- **Canary endpoint:** `GET /c/{token}` keyed by an unguessable token; serve
  hostile content only for active runs; every response carries
  `X-Robots-Tag: noindex, nofollow`.
- **Dummy secrets:** format `HAUNTLET-DUMMY-<run>-<trap>-<nonce>`. Never a
  realistic credential shape (secret scanners will flag it).
- **Trap templates** use `{placeholder}` fields only. A literal URL, host, or
  credential in a template is a bug; `scripts/check_payload_safety.py` rejects it.
- **Local run:** one command — `uv run hauntlet run --room threshold --agent naive`.
- **Reference agents:** `naive` (expected to score high) and `hardened`
  (expected to score L0 with Detected) are regression anchors; `hauntlet selftest`
  asserts both.
- **Kiro config the Exorcist writes:** `.kiro/settings/mcp.json`,
  `.kiro/settings/sandbox.json` (`{"enabled": true, "networkAccess": ...}`),
  steering files and hook JSON.
- **Commands:** `uv run pytest` · `uv run hauntlet selftest` ·
  `uv run hauntlet serve`.
- **License:** MIT, committed in the first commit.

Keep secrets out of the repo. There are none to keep — all planted secrets are
dummies by rule (`safety-rules.md`).
