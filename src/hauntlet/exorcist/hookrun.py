"""Run a bundled hook command under Kiro's protocol, confined (Requirement 8.5, Q4).

The protocol (https://kiro.dev/docs/hooks/actions/): the event JSON goes in on
stdin, exit 0 allows, exit 2 blocks. A timeout, any other exit code, or the
guard tripping a confinement rule gives ``not_interpreted``, which never
counts as a block.

How the runner confines the guard:

- **No shell.** It runs ``sys.executable -I -B -S -c BOOT <script>``. ``-I``
  ignores ``PYTHON*`` variables and the user site, ``-B`` writes no bytecode,
  and ``-S`` skips ``site``.
- **No network, no processes, no writes.** ``BOOT`` installs an audit hook
  before the script runs, and an audit hook cannot be removed. It refuses:
  - sockets;
  - imports of network, process and FFI modules;
  - process creation;
  - opening a file for anything but reading;
  - filesystem mutation;
  - ``ctypes``.
- **Working directory** is the bundle directory.
- **Environment** is exactly the agent environment passed in. ``PATH`` is not
  needed. The platform adds two variables itself, which is expected and
  tested: ``LC_CTYPE`` (Python's locale coercion, PEP 538) and, on macOS,
  ``__CF_USER_TEXT_ENCODING``. Neither carries anything from the parent's
  environment.
- **Timeout** is ``min(timeout, HOOK_TIMEOUT_CAP)``; the child is killed when
  it expires.
- **Output** is capped.

The audit hook is the second layer. The first is that the interpreter runs
only digest-verified scripts from bundles the Exorcist generated.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

HOOK_TIMEOUT_CAP = 5.0
OUTPUT_CAP = 4096

ALLOW = "allow"
BLOCK = "block"
NOT_INTERPRETED = "not_interpreted"

#: Runs inside the child before the guard. Kept dependency-free on purpose.
BOOT = r"""
import os, sys

_PREFIXES = (
    "socket.", "subprocess.", "os.system", "os.exec", "os.spawn", "os.posix_spawn",
    "os.fork", "os.forkpty", "os.kill", "os.killpg", "pty.spawn", "os.remove", "os.unlink",
    "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.chflags", "os.truncate",
    "os.symlink", "os.link", "os.utime", "os.putenv", "os.unsetenv", "shutil.", "ctypes.",
    "webbrowser.open", "urllib.Request", "http.client.", "ftplib.", "smtplib.", "imaplib.",
    "poplib.", "nntplib.", "telnetlib.", "sqlite3.connect",
)
_IMPORTS = {
    "socket", "_socket", "ssl", "_ssl", "ctypes", "_ctypes", "subprocess", "_posixsubprocess",
    "multiprocessing", "_multiprocessing", "asyncio", "select", "selectors", "http", "ftplib",
    "smtplib", "urllib.request", "webbrowser", "pty", "sqlite3", "_sqlite3",
}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

def _confine(event, args):
    if event == "open":
        mode, flags = args[1], args[2]
        if isinstance(mode, str) and any(c in mode for c in "wax+"):
            raise PermissionError("hauntlet hook confinement: write access refused")
        if isinstance(flags, int) and flags & _WRITE_FLAGS:
            raise PermissionError("hauntlet hook confinement: write access refused")
        return
    if event == "import":
        name = args[0] or ""
        if name in _IMPORTS or name.split(".")[0] in _IMPORTS:
            raise PermissionError(f"hauntlet hook confinement: import of {name} refused")
        return
    if event.startswith(_PREFIXES):
        raise PermissionError(f"hauntlet hook confinement: {event} refused")

sys.addaudithook(_confine)
_script = sys.argv[1]
sys.argv = [_script]
import runpy
runpy.run_path(_script, run_name="__main__")
"""


@dataclass(frozen=True)
class HookResult:
    status: str  # ALLOW | BLOCK | NOT_INTERPRETED
    exit_code: int | None
    reason: str  # stderr (capped) or why it was not interpreted


def _cap(data: bytes | str | None) -> str:
    if data is None:
        return ""
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    return text[:OUTPUT_CAP]


def run(
    script: Path,
    event: Mapping[str, object],
    env: Mapping[str, str],
    cwd: Path,
    timeout: float,
) -> HookResult:
    """Run ``script`` once with ``event`` on stdin; map its exit code to allow/block."""
    limit = min(float(timeout) if timeout and timeout > 0 else HOOK_TIMEOUT_CAP, HOOK_TIMEOUT_CAP)
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-B", "-S", "-c", BOOT, str(script)],
            input=json.dumps(dict(event)).encode("utf-8"),
            cwd=str(cwd),
            env=dict(env),
            capture_output=True,
            timeout=limit,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return HookResult(NOT_INTERPRETED, None, f"timed out after {limit:g}s and was killed")
    except OSError as exc:
        return HookResult(NOT_INTERPRETED, None, f"could not start: {exc}")
    stderr = _cap(proc.stderr)
    if proc.returncode == 0:
        return HookResult(ALLOW, 0, stderr)
    if proc.returncode == 2:
        return HookResult(BLOCK, 2, stderr)
    return HookResult(NOT_INTERPRETED, proc.returncode, f"exit code {proc.returncode}: {stderr}".strip())
