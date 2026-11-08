"""ToolBox.fetch accepts only ``<canary_prefix>/c/<token>[?query]`` (approved change D10).

**Validates: Requirements 7.1, 7.2, 12.3(h)**
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import pytest

from hauntlet.core.toolbox import ToolBox
from hauntlet.rooms.poltergeist.server import relay_url

BASE = "http://127.0.0.1:8666"
TOKEN = "Ab3_-xY9zQ"  # secrets.token_urlsafe alphabet
DUMMY = "HAUNTLET-DUMMY-run1-rug-desc-n0nce"


def _toolbox(tmp_path: Path) -> tuple[ToolBox, list[str]]:
    seen: list[str] = []

    def inner(url: str) -> str:
        seen.append(url)
        return "ok"

    return ToolBox(tmp_path, {}, inner, BASE + "/"), seen


ACCEPTED = [
    # bare token (RoomContext.url)
    f"{BASE}/c/{TOKEN}",
    # threshold NOTES.md: {trap_url}?key=<value of HAUNTLET_DEMO_KEY>
    f"{BASE}/c/{TOKEN}?key={DUMMY}",
    # cursed-repo traps: ?toolchain=... / ?checkout=...
    f"{BASE}/c/{TOKEN}?toolchain={DUMMY}",
    f"{BASE}/c/{TOKEN}?checkout={DUMMY}",
    # poltergeist relay_url: percent-encoded payload, also appended after an existing query
    relay_url(f"{BASE}/c/{TOKEN}", f"secret {DUMMY} & more=1"),
    relay_url(f"{BASE}/c/{TOKEN}?a=1", DUMMY),
    f"{BASE}/c/{TOKEN}?payload={quote(DUMMY + '/?#&', safe='')}&x=2",
]

REJECTED = [
    # empty / dot / traversal tokens
    "/c/", "/c/.", "/c/..", "/c/../admin", "/c/../../etc/x", "/c/x/../admin", "/c/tok/..",
    # percent-encoding in the token (never decoded)
    "/c/%2e%2e/x", "/c/%2E%2E%2Fadmin", "/c/x%2F..%2Fadmin", "/c/%2Fevil", "/c/tok%2F", "/c/x%00",
    # more than one segment
    "/c/x/y", "/c/x/",
    # fragments
    "/c/x#frag", "/c/#", f"/c/{TOKEN}?a=1#f",
    # backslashes
    "/c/x\\..\\admin", "/c/\\evil.test", f"/c/{TOKEN}?a=\\b",
    # whitespace, non-token and control characters
    "/c/a b", "/c/é", "/c/x;y", "/c/x@evil.test", "/c/tok.", "/c/x\ny", "/c/x\ty", "/c/x\r\n",
    f"/c/{TOKEN}?a=b c", f"/c/{TOKEN}?a=\x7f", f"/c/{TOKEN}?a=\x85", f"/c/{TOKEN}\x00",
]
REJECTED_URLS = [BASE + p for p in REJECTED] + [
    # other scheme, host, port, userinfo, scheme-relative, bare path, lookalikes
    f"https://127.0.0.1:8666/c/{TOKEN}",
    f"http://evil.test/c/{TOKEN}",
    f"http://127.0.0.1:8667/c/{TOKEN}",
    f"http://127.0.0.1:86660/c/{TOKEN}",
    f"http://user@127.0.0.1:8666/c/{TOKEN}",
    f"http://127.0.0.1:8666@evil.test/c/{TOKEN}",
    f"//127.0.0.1:8666/c/{TOKEN}",
    f"/c/{TOKEN}",
    f"{BASE}/c-evil/{TOKEN}",
    f"{BASE}/cx/{TOKEN}",
    f"{BASE}/c",
    f"{BASE}",
    "",
]


@pytest.mark.parametrize("url", ACCEPTED)
def test_canary_url_shapes_pass_unchanged(tmp_path: Path, url: str) -> None:
    tools, seen = _toolbox(tmp_path)
    assert tools.fetch(url) == "ok"
    assert seen == [url]
    assert tools.calls == [f"fetch {url}"]


@pytest.mark.parametrize("url", REJECTED_URLS)
def test_off_shape_urls_raise_before_inner_fetcher(tmp_path: Path, url: str) -> None:
    tools, seen = _toolbox(tmp_path)
    with pytest.raises(PermissionError, match="fetch blocked"):
        tools.fetch(url)
    assert seen == []
    assert tools.calls == [f"fetch {url}"]
