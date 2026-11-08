# Findings from real-client testing

## 2026-11-08: Kiro against the Poltergeist rooms

Testing Kiro as a real MCP client against `hauntlet mcp serve` found two
problems. Neither is a security issue: both stopped the connection from being
set up, and no trap, tool call or secret was involved.

| # | Finding | Whose | Status | Report upstream |
|---|---|---|---|---|
| 1 | The `mcp` SDK locks a connection's protocol era on the first request, so a client's fallback `initialize` is refused | upstream (`mcp` 2.3.0) | worked around in room code | yes, not yet reported |
| 2 | Hauntlet refused Kiro's second server process for the same run | ours | fixed | no |

Versions: `mcp` 2.3.0 (Python SDK). Kiro identified itself as
`{"name": "kiro", "version": "0.0.0"}` in `clientInfo`. Hauntlet's server
reported `hauntlet-poltergeist` 0.1.0.

The raw captures are in [`findings/2026-11-08/`](findings/2026-11-08/), copied
unchanged; see "How the captures were made" for how to read them.

---

### 1. Upstream: the SDK locks the protocol era on the first request

**Where:** `serve_dual_era_loop` in `mcp/server/runner.py`, `mcp` 2.3.0.

**What happens.** `serve_dual_era_loop` reads the client's first request and
fixes the connection's era from it, once: a request carrying the 2026-07-28
`_meta` envelope makes the connection modern, and anything else makes it
legacy. It never changes after that.

Kiro opens every stdio connection with a 2026-07-28 probe:

```json
{"jsonrpc":"2.0","id":"server-discover-probe-1","method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"kiro","version":"0.0.0"},"io.modelcontextprotocol/clientCapabilities":{"elicitation":{"form":{},"url":{}}}}}}
```

`poltergeist-legacy` speaks only 2025-11-25 and 2025-06-18, so its version gate
refused the probe:

```json
{"jsonrpc":"2.0","id":"server-discover-probe-1","error":{"code":-32022,"message":"Unsupported protocol version","data":{"supported":["2025-11-25","2025-06-18"],"requested":"2026-07-28"}}}
```

Kiro then fell back to the handshake, on a version the error listed as
supported:

```json
{"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{"elicitation":{"form":{},"url":{}}},"clientInfo":{"name":"kiro","version":"0.0.0"}},"jsonrpc":"2.0","id":0}
```

By then the probe had already locked the connection to 2026-07-28, so the SDK
refused the `initialize`:

```json
{"jsonrpc":"2.0","id":0,"error":{"code":-32022,"message":"connection is serving the 2026-07-28 protocol; the initialize handshake is not accepted","data":{"supported":["2026-07-28"],"requested":"2025-11-25"}}}
```

The two error replies contradict each other. The first says the server supports
only `2025-11-25` and `2025-06-18`. The second, on the same connection, says it
supports only `2026-07-28`.

**What the captures show, and what they don't.** The captures contain the
probe, our `-32022` reply and Kiro's `initialize`, in `attempt-legacy-1/` to
`attempt-legacy-3/`. They contain no reply to that `initialize`. Finding 2 was
masking it, and the capture script appends every server process's input and
output to the same files, so the captures can't show which process received
the `initialize`. The SDK's refusal above was reproduced by sending the two
captured Kiro messages, unchanged, to one `hauntlet mcp serve --room
poltergeist-legacy` process before the workaround. That is the
`test_kiro_discover_probe_then_initialize_succeeds_on_legacy` test in
`tests/test_mcp_legacy_discover_probe.py`, which failed with exactly that
error.

**Why we think this is an SDK issue.** This is our reading of the 2026-07-28
[Versioning and Compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)
page; the report should check it with the SDK maintainers.

- A server may decline a version it knows but has chosen not to support, and
  must then answer with `UnsupportedProtocolVersionError` listing what it does
  support. The client should pick a mutually supported version from that list
  and retry.
- A dual-era server picks its behaviour from how the client opens, and an
  `initialize` request selects legacy semantics for the stdio process.
- The SDK has no setting to serve only legacy revisions. A server built on it
  can decline 2026-07-28 only by refusing modern requests itself, as
  `poltergeist-legacy` does with middleware. Once it has, the client's
  spec-sanctioned retry (an `initialize` on a listed legacy version) can no
  longer be served, because the refused request already locked the era.

A fix upstream could leave the era undecided until a request is actually
served, so a refused modern request doesn't lock it. Another option is a
supported-versions setting on the server, so the SDK itself answers the probe
the way the server wants. Either is for the maintainers to choose.

**Our workaround** (room code only; the SDK is not patched).
`answer_pre_handshake_probes` in `src/hauntlet/rooms/poltergeist/server.py`
sits between stdin and the SDK, for rooms that speak handshake revisions only
(`poltergeist-legacy`):

- Until the first `initialize`, it answers any request carrying the 2026-07-28
  `_meta` envelope itself, with the same `-32022` error and supported list as
  the version gate, and does not pass it to the SDK. The first request the SDK
  sees is then the `initialize`, so it picks the legacy era.
- From the first `initialize` on, it passes every message through unchanged.
- Each answered probe is recorded in the fact log as a refused revision, and
  the run summary shows it as `refused protocol revision '2026-07-28'`.
- The `poltergeist` room (2026-07-28) does not use it.

`tests/test_mcp_legacy_discover_probe.py` replays Kiro's two messages byte for
byte against a real `hauntlet mcp serve` process. The `initialize` now succeeds
on 2025-11-25, and `tools/list` works.

**Not yet re-tested with Kiro.** Both fixes are in place, but `poltergeist-legacy`
has not been run against Kiro since. The fix is verified against the captured
messages only.

---

### 2. Hauntlet: Kiro's second server process was refused

**What happens.** Kiro starts an MCP server twice per connect. The first
process gets a short probe and is closed; the second is the real connection.
The current captures (`in.log`, `out.log` and `err.log`, from the modern
`poltergeist` room) show the pattern:

- first process: `server/discover`, then `subscriptions/listen`;
- second process: `server/discover` and `subscriptions/listen` again, then
  `tools/list`.

`hauntlet mcp serve` allowed one session per run and room, so that the fact log
had a single writer and a single rug pull. The first process created the
workspace, and the second was refused:

```text
hauntlet mcp: refused, serving nothing: run 'MlNZk-cdymGy55ai' already has a poltergeist workspace at …/mcp-scratch/poltergeist-MlNZk-cdymGy55ai; each run serves one MCP session per room (start a new run to retry)
```

Kiro waited on the refused process and gave up after 60 seconds. In `err.log`
that refused process starts at 13:30:30 and its capture pipeline ends at
13:31:30. The same happened on `poltergeist-legacy` (`attempt-legacy-1/` to
`attempt-legacy-3/`) and on `poltergeist` (`attempt-modern/`).

**Initially misread.** `err.log` shows `client disconnected` for the first
process, so this first looked like Kiro dropping its connection. It isn't.
Closing the probe process is Kiro's normal behaviour; the bug was our refusal of
the process that followed it.

**The fix** (`prepare_mcp_serve` in `src/hauntlet/cli.py`):

- The serving process holds an exclusive lock (`flock`) on `.serve.lock` in
  the workspace for as long as it runs. The OS releases it when the process
  exits, however it exits.
- A later `hauntlet mcp serve` for the same run and room may take over the
  workspace only if it gets the lock within about 3 seconds, so the earlier
  process has exited, and the earlier fact log has no `list` or `call` fact, so
  that session never got past the handshake and the rug pull can't have fired.
  Otherwise it is refused as before, with the reason.
- On takeover the earlier fact log moves to
  `poltergeist-facts.prev-N.jsonl` and is kept. The new log starts with a
  `takeover` fact naming that file and its fact count. Scoring reads only the
  new log, so the score reflects the real session alone, and the run summary
  notes the takeover.

Tests: `tests/test_poltergeist_real_client_e2e.py` runs a probe-only process
and then a full session on the same run, against both rooms, and gets the
normal scores (`rug-desc` L4, `tool-output` L3, control L0). A second test
checks that a session that already listed tools is never taken over.

**Re-tested with Kiro.** The current captures include a run after the fix, at
15:12:48, on `poltergeist`. Both of Kiro's processes started in the same second.
Each took over the previous one, the second served `tools/list`, and Kiro closed
the connection cleanly at 15:13:03 (`exit=0`). The first process took over a
workspace left behind by the failed 13:30 attempt, so that run's workspace
holds `prev-1` (from 13:30) and `prev-2` (the 15:12 probe). The `listen:0`
`Connection closed` error at the end of `out.log` is the SDK closing the open
subscription when Kiro closed stdin. The session did not go on to call any
tool, so this re-test shows the connection is set up, not a scored run.

---

### How the captures were made

Kiro launched the server through a wrapper script (`capture.sh`, kept outside
this repo) that reads the run ID and room from files and runs:

```sh
tee -a in.log | uv run hauntlet mcp serve --room "$ROOM" --run="$RUN" 2>>err.log | tee -a out.log
```

It writes `--- start <time> run=<id> pid=<pid>` and `--- exit=<status> <time>`
lines to `err.log` around each process. Every process appends to the same
three files, so lines from Kiro's two processes interleave in each file. The
`--- exit` time is when the whole pipeline ended, which for a refused process is
when Kiro closed its input.

| Path | Room | What it shows |
|---|---|---|
| `attempt-modern/` | `poltergeist` | finding 2: the probe served, the second process refused |
| `attempt-legacy-1/` | `poltergeist-legacy` | findings 1 and 2, over two connect attempts |
| `attempt-legacy-2/` | `poltergeist-legacy` | findings 1 and 2, one connect attempt |
| `attempt-legacy-3/` | `poltergeist-legacy` | the same; it also has one `invalid choice: ''` line from a moment when the wrapper's room file was empty, a test-setup slip and not a finding |
| `in.log`, `out.log`, `err.log` | `poltergeist` | the 13:30 refusal and the 15:12 run after the takeover fix |

The captures contain no dummy secret and no URL. The `err.log` files contain
absolute paths on the tester's machine, left as they were.
