"""Kiro's connection to poltergeist-legacy over real stdio (bug from a real-client test).

Kiro opens with a 2026-07-28 ``server/discover`` probe carrying the per-request
``_meta`` envelope, gets ``-32022 Unsupported protocol version``, then falls back
to a 2025-11-25 ``initialize``. ``mcp`` 2.3.0 picks a connection's era from the
first request it sees, so the probe used to latch the connection to the modern
era and the fallback ``initialize`` was refused. ``hauntlet mcp serve`` now
answers enveloped requests that arrive before the first ``initialize`` itself,
for legacy rooms only, so the SDK first sees the ``initialize``.

These tests spawn ``hauntlet mcp serve`` as a real subprocess and replay Kiro's
two frames byte for byte.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hauntlet import cli
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.rooms import default_rooms
from hauntlet.rooms.poltergeist import factlog
from hauntlet.rooms.poltergeist.server import REFUSED_PREFIX

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8666"

#: Kiro's first frame, exactly as captured.
KIRO_DISCOVER = (
    '{"jsonrpc":"2.0","id":"server-discover-probe-1","method":"server/discover","params":'
    '{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",'
    '"io.modelcontextprotocol/clientInfo":{"name":"kiro","version":"0.0.0"},'
    '"io.modelcontextprotocol/clientCapabilities":{"elicitation":{"form":{},"url":{}}}}}}'
)
#: Kiro's fallback frame after the -32022 reply, exactly as captured.
KIRO_INITIALIZE = (
    '{"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":'
    '{"elicitation":{"form":{},"url":{}}},"clientInfo":{"name":"kiro","version":"0.0.0"}},'
    '"jsonrpc":"2.0","id":0}'
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "range.db"
    Store(path)
    monkeypatch.setenv("HAUNTLET_DB", str(path))
    monkeypatch.setenv("HAUNTLET_BASE_URL", BASE_URL)
    return path


def _spawn(db: Path, room: str, run_id: str) -> subprocess.Popen[str]:
    env = {**os.environ, "HAUNTLET_DB": str(db), "HAUNTLET_BASE_URL": BASE_URL}
    return subprocess.Popen(
        [sys.executable, "-m", "hauntlet.cli", "mcp", "serve", "--room", room, f"--run={run_id}"],
        cwd=ROOT, env=env, text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _send_raw(proc: subprocess.Popen[str], line: str) -> None:
    assert proc.stdin is not None
    proc.stdin.write(line + "\n")
    proc.stdin.flush()


def _read_until_id(proc: subprocess.Popen[str], msg_id: object) -> dict:
    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        assert line, "server closed stdout before answering"
        frame = json.loads(line)
        assert frame.get("jsonrpc") == "2.0"
        if "id" in frame and frame["id"] == msg_id:
            return frame


def _close(proc: subprocess.Popen[str]) -> str:
    assert proc.stdin is not None and proc.stderr is not None
    try:
        proc.stdin.close()
        proc.wait(timeout=30)
        return proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_kiro_discover_probe_then_initialize_succeeds_on_legacy(db: Path) -> None:
    run_id = RangeService(Store(db), default_rooms(), base_url=BASE_URL).start_run(
        ["poltergeist-legacy"]
    ).run.run_id
    proc = _spawn(db, "poltergeist-legacy", run_id)
    try:
        # 1. The discover probe gets the same -32022 the room has always sent.
        _send_raw(proc, KIRO_DISCOVER)
        probe = _read_until_id(proc, "server-discover-probe-1")
        assert "result" not in probe
        assert probe["error"]["code"] == -32022
        assert probe["error"]["message"] == "Unsupported protocol version"
        assert probe["error"]["data"] == {
            "supported": ["2025-11-25", "2025-06-18"],
            "requested": "2026-07-28",
        }

        # 2. The fallback initialize is accepted on 2025-11-25.
        _send_raw(proc, KIRO_INITIALIZE)
        init = _read_until_id(proc, 0)
        assert "error" not in init, init
        assert init["result"]["protocolVersion"] == "2025-11-25"
        assert init["result"]["capabilities"]["tools"]["listChanged"] is True

        # 3. tools/list works on the now-legacy connection.
        _send_raw(proc, json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        _send_raw(proc, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}))
        listed = _read_until_id(proc, 1)
        assert {t["name"] for t in listed["result"]["tools"]} >= {"list_topics", "get_note", "submit_answer"}
    finally:
        err = _close(proc)
    assert proc.returncode == 0, err

    # The probe is recorded as a refused attempt, then the real negotiation.
    ws = cli.mcp_workspace(cli.mcp_scratch_root(db), "poltergeist-legacy", run_id)
    negotiated = [f.revision for f in factlog.read(factlog.facts_path(ws), run_id) if f.kind == "negotiated"]
    assert negotiated == [REFUSED_PREFIX + "2026-07-28", "2025-11-25"]


def test_enveloped_request_after_initialize_is_still_refused_by_the_sdk(db: Path) -> None:
    """After the handshake the filter steps aside: the SDK's own legacy-era
    refusal of an enveloped request is unchanged."""
    run_id = RangeService(Store(db), default_rooms(), base_url=BASE_URL).start_run(
        ["poltergeist-legacy"]
    ).run.run_id
    proc = _spawn(db, "poltergeist-legacy", run_id)
    try:
        _send_raw(proc, KIRO_INITIALIZE)
        assert _read_until_id(proc, 0)["result"]["protocolVersion"] == "2025-11-25"
        _send_raw(proc, json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        _send_raw(proc, KIRO_DISCOVER)
        late = _read_until_id(proc, "server-discover-probe-1")
        assert "error" in late and late["error"]["code"] != -32022  # the SDK's INVALID_REQUEST
    finally:
        err = _close(proc)
    assert proc.returncode == 0, err


def test_modern_room_still_serves_the_discover_probe(db: Path) -> None:
    """The modern room is untouched: the SDK latches 2026-07-28 and answers it."""
    run_id = RangeService(Store(db), default_rooms(), base_url=BASE_URL).start_run(
        ["poltergeist"]
    ).run.run_id
    proc = _spawn(db, "poltergeist", run_id)
    try:
        _send_raw(proc, KIRO_DISCOVER)
        reply = _read_until_id(proc, "server-discover-probe-1")
        assert "result" in reply, reply
    finally:
        err = _close(proc)
    assert proc.returncode == 0, err
