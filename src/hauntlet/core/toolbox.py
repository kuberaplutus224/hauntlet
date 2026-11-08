"""The only tools the reference agents get.

Writes are confined to the run's scratch workspace, and fetches may reach only
the run's own canary endpoint. Nothing else is reachable, by construction.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

_TOKEN = re.compile(r"[A-Za-z0-9_-]+")


def _is_canary_url(url: str, prefix: str) -> bool:
    """True iff ``url`` is ``<prefix><token>`` or ``<prefix><token>?<query>``.

    ``<token>`` is one ``[A-Za-z0-9_-]+`` segment (never decoded), and the whole
    URL has no fragment, backslash, whitespace or control character (C0, DEL, C1),
    so percent-encoding can appear only in the query.
    """
    if not isinstance(url, str) or not url.startswith(prefix):
        return False
    if any(ch in "#\\" or ch.isspace() or unicodedata.category(ch) == "Cc" for ch in url):
        return False
    token, _, _query = url[len(prefix) :].partition("?")
    return _TOKEN.fullmatch(token) is not None


class ToolBox:
    def __init__(
        self,
        workspace: Path,
        env: dict[str, str],
        fetcher: Callable[[str], str],
        canary_prefix: str,
    ) -> None:
        self.workspace = workspace.resolve()
        self._env = dict(env)
        self._fetcher = fetcher
        self._prefix = canary_prefix.rstrip("/") + "/c/"
        self.calls: list[str] = []

    def _resolve(self, rel: str) -> Path:
        p = (self.workspace / rel).resolve()
        if p != self.workspace and self.workspace not in p.parents:
            raise PermissionError(f"path escapes the scratch workspace: {rel}")
        return p

    def list_files(self) -> list[str]:
        self.calls.append("list_files")
        return sorted(
            str(p.relative_to(self.workspace)) for p in self.workspace.rglob("*") if p.is_file()
        )

    def read_file(self, rel: str) -> str:
        self.calls.append(f"read_file {rel}")
        return self._resolve(rel).read_text(encoding="utf-8")

    def write_file(self, rel: str, content: str) -> None:
        self.calls.append(f"write_file {rel}")
        p = self._resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def getenv(self, name: str) -> str | None:
        self.calls.append(f"getenv {name}")
        return self._env.get(name)

    def fetch(self, url: str) -> str:
        self.calls.append(f"fetch {url}")
        if not _is_canary_url(url, self._prefix):
            raise PermissionError(f"fetch blocked: only the run's canary endpoint is reachable ({url})")
        return self._fetcher(url)
