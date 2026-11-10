"""The shared redactor (scorecard D31, redactor half of SP10; task 4.2).

**Validates: scorecard Requirements 10.1–10.3, SP10**
"""

from __future__ import annotations

from urllib.parse import quote

from _exorcist_strategies import runs
from hypothesis import given, settings
from hypothesis import strategies as st

from hauntlet.core.canary import DUMMY_PREFIX, MARKER_PREFIX
from hauntlet.redact import MARKER_SHOWN, SECRET_SHOWN, TOKEN_SHOWN, redact_patterns, redactor

filler = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=20)


def _wrap(value: str, how: str, before: str, after: str) -> str:
    if how == "raw":
        return f"{before}{value}{after}"
    if how == "encoded":
        return f"{before}{quote(value, safe='')}{after}"
    if how == "double":
        return f"{before}{quote(quote(value, safe=''), safe='')}{after}"
    if how == "url":
        return f"{before}http://127.0.0.1:8666/c/{value}?k=1{after}"
    if how == "quoted":
        return f'{before}"{value}"<{after}'
    return f"{before} {value} {after}"  # bare


def _leaks(out: str, canaries) -> list[str]:
    bad = []
    for c in canaries:
        if c.kind == "secret":
            tail = c.value[len(DUMMY_PREFIX) + 1 :]
            if c.value.lower() in out.lower() or tail.lower() in out.lower():
                bad.append(c.value)
        elif c.kind == "marker":
            tail = c.value[len(MARKER_PREFIX) + 1 :]
            if tail.lower() in out.lower():
                bad.append(c.value)
        elif c.value in out:
            bad.append(c.value)
    return bad


@settings(max_examples=60, deadline=None)
@given(
    run=runs(),
    picks=st.lists(st.tuples(st.integers(0, 10_000), st.sampled_from(["raw", "encoded", "double", "url", "quoted", "bare"])), min_size=1, max_size=6),
    before=filler,
    after=filler,
)
def test_no_canary_value_survives(run, picks, before, after) -> None:
    canaries = list(run.canaries)
    text = "".join(_wrap(canaries[i % len(canaries)].value, how, before, after) for i, how in picks)
    out = redactor(canaries)(text)
    assert not _leaks(out, canaries), out


@settings(max_examples=60, deadline=None)
@given(run=runs(), how=st.sampled_from(["raw", "encoded", "url", "quoted"]), before=filler, after=filler)
def test_pattern_only_mode_removes_secrets_markers_and_canary_paths(run, how, before, after) -> None:
    for c in run.canaries:
        if c.kind == "url" and how != "url":
            continue  # a bare token has no pattern; exact values (D30) cover it
        out = redact_patterns(_wrap(c.value, how, before, after))
        assert not _leaks(out, [c]), out


@settings(max_examples=100, deadline=None)
@given(run=runs(), text=st.text(max_size=80), i=st.integers(0, 10_000))
def test_idempotent(run, text, i) -> None:
    canaries = list(run.canaries)
    r = redactor(canaries)
    once = r(text + canaries[i % len(canaries)].value + text)
    assert r(once) == once
    assert redact_patterns(redact_patterns(text)) == redact_patterns(text)


def test_shown_forms() -> None:
    assert redact_patterns(f"key={DUMMY_PREFIX}-abc12345-trap-0a1b2c3d4e5f.") == f"key={SECRET_SHOWN}"
    assert redact_patterns(f"say {MARKER_PREFIX}-0a1b2c3d4e now") == f"say {MARKER_SHOWN} now"
    assert redact_patterns("GET /c/AbC_-123?x=1") == f"GET /c/{TOKEN_SHOWN}?x=1"
    assert redact_patterns("nothing to see") == "nothing to see"
