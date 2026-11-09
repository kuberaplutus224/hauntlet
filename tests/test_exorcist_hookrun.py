"""The confined hook runner (exorcist Requirements 6.1, 6.2, 8.5, 9.8; property EP13, task 9.3).

- **EP13:** the shipped guard, fed arbitrary JSON, exits 0 or 2. It blocks
  exactly when the tool input carries a credential-like environment value, raw
  or percent-encoded, and its message names the variable, never the value.
- **Confinement:** canary scripts that try a socket, a ``subprocess`` call, a
  file write, ``os.system``, ``ctypes`` or ``os.remove`` are each refused, are
  reported as not interpreted, and leave no side effect.
- **Timeout:** a sleeping script is killed and reported as not interpreted.
- **Working directory and environment:** cwd is the bundle directory, and the
  environment is the one passed in, plus only the variables the platform adds
  itself.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hauntlet.exorcist import hookrun
from hauntlet.exorcist.hookrun import ALLOW, BLOCK, NOT_INTERPRETED, run

GUARD = Path(__file__).resolve().parent.parent / "src/hauntlet/exorcist/guards/credential_egress.py"
SECRET = "HAUNTLET-DUMMY-abcd1234-trap-0123456789"
#: Variables the OS/interpreter add to a child's environment on their own (PEP 538 locale
#: coercion; CoreFoundation on macOS). They never come from the parent's environment.
PLATFORM_VARS = {"LC_CTYPE", "__CF_USER_TEXT_ENCODING"}

json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=30),
    lambda kids: st.lists(kids, max_size=4) | st.dictionaries(st.text(max_size=8), kids, max_size=4),
    max_leaves=12,
)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(event=json_values, carry=st.booleans(), encoded=st.booleans())
def test_ep13_guard_exits_only_0_or_2(tmp_path: Path, event, carry: bool, encoded: bool) -> None:
    env = {"RANGEKIT_PUBLISH_KEY": SECRET, "PLAIN": "not-a-credential-value"}
    if carry:
        value = SECRET.replace("-", "%2D") if encoded else SECRET
        event = {"tool_name": "web_fetch", "tool_input": {"url": f"x?k={value}", "other": event}}
    result = run(GUARD, event if isinstance(event, dict) else {"tool_input": event}, env, tmp_path, 5)
    assert result.status in (ALLOW, BLOCK), result
    if carry and not encoded:
        assert result.status == BLOCK
        assert "RANGEKIT_PUBLISH_KEY" in result.reason and SECRET not in result.reason


def test_guard_blocks_percent_encoded_and_allows_clean_input(tmp_path: Path) -> None:
    env = {"POLTERGEIST_SESSION": "sess-value-1234567890/+=", "SHORT_KEY": "abc"}
    from urllib.parse import quote, quote_plus

    for carried in (env["POLTERGEIST_SESSION"], quote(env["POLTERGEIST_SESSION"], safe=""),
                    quote_plus(env["POLTERGEIST_SESSION"])):
        r = run(GUARD, {"tool_input": {"payload": carried}}, env, tmp_path, 5)
        assert r.status == BLOCK, carried
    assert run(GUARD, {"tool_input": {"payload": "abc"}}, env, tmp_path, 5).status == ALLOW
    assert run(GUARD, {"tool_input": {"url": "plain"}}, {}, tmp_path, 5).status == ALLOW
    # Not a JSON object on stdin: allowed rather than silently blocked.
    assert run(GUARD, {"tool_input": None}, env, tmp_path, 5).status == ALLOW


@pytest.fixture
def listener():
    """A local TCP listener that records whether anything connected."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(0.2)
    hits: list[bool] = []
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            hits.append(True)
            conn.close()

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    yield srv.getsockname()[1], hits
    stop.set()
    t.join(1)
    srv.close()


def _script(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / f"{name}.py"
    p.write_text(body)
    return p


def test_confinement_refuses_network_processes_and_writes(tmp_path: Path, listener) -> None:
    port, hits = listener
    marker = tmp_path / "PWNED"
    cases = {
        "socket": f"import socket\ns = socket.create_connection(('127.0.0.1', {port}))\n",
        "socket_late": "import _socket\n",
        "subprocess": f"import subprocess\nsubprocess.run(['touch', {str(marker)!r}])\n",
        "write": f"open({str(marker)!r}, 'w').write('x')\n",
        "osopen": f"import os\nos.open({str(marker)!r}, os.O_WRONLY | os.O_CREAT)\n",
        "system": f"import os\nos.system('touch {marker}')\n",
        "ctypes": "import ctypes\n",
        "remove": f"import os\nos.remove({str(tmp_path / 'keep.txt')!r})\n",
        "urllib": f"import urllib.request\nurllib.request.urlopen('http://127.0.0.1:{port}/')\n",
    }
    (tmp_path / "keep.txt").write_text("keep")
    for name, body in cases.items():
        result = run(_script(tmp_path, name, body + "import sys\nsys.exit(2)\n"), {}, {}, tmp_path, 5)
        assert result.status == NOT_INTERPRETED, (name, result)
        assert "confinement" in result.reason, (name, result.reason)
    assert not marker.exists()
    assert (tmp_path / "keep.txt").read_text() == "keep"
    time.sleep(0.3)
    assert hits == [], "a confined hook reached the network"


def test_reading_is_allowed(tmp_path: Path) -> None:
    data = tmp_path / "data.txt"
    data.write_text("hello")
    body = f"import sys\nsys.exit(2 if open({str(data)!r}).read() == 'hello' else 0)\n"
    assert run(_script(tmp_path, "reader", body), {}, {}, tmp_path, 5).status == BLOCK


def test_timeout_kills_and_is_not_interpreted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(hookrun, "HOOK_TIMEOUT_CAP", 1.0)
    start = time.monotonic()
    result = run(_script(tmp_path, "slow", "import time\ntime.sleep(30)\n"), {}, {}, tmp_path, 60)
    assert result.status == NOT_INTERPRETED and "timed out" in result.reason
    assert time.monotonic() - start < 5


@pytest.mark.parametrize("code", [0, 2, 1, 3, 255])
def test_exit_codes_map_to_the_protocol(tmp_path: Path, code: int) -> None:
    result = run(_script(tmp_path, f"exit{code}", f"import sys\nsys.exit({code})\n"), {}, {}, tmp_path, 5)
    assert result.status == {0: ALLOW, 2: BLOCK}.get(code, NOT_INTERPRETED)


def test_cwd_and_environment_are_exactly_as_passed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PARENT_ONLY_SECRET_KEY", "must-not-leak-1234567890")
    body = (
        "import json, os, sys\n"
        "sys.stderr.write(json.dumps({'cwd': os.getcwd(), 'env': dict(os.environ)}))\n"
        "sys.exit(2)\n"
    )
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    result = run(_script(tmp_path, "probe", body), {}, {"AGENT_KEY": "v"}, bundle, 5)
    seen = json.loads(result.reason)
    assert Path(seen["cwd"]).resolve() == bundle.resolve()
    assert seen["env"].get("AGENT_KEY") == "v"
    assert set(seen["env"]) - {"AGENT_KEY"} <= PLATFORM_VARS
    assert "PARENT_ONLY_SECRET_KEY" not in seen["env"]
    assert os.environ["PARENT_ONLY_SECRET_KEY"] not in result.reason
