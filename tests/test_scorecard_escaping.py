"""Escaping (scorecard SP12, task 12.4).

Hostile text in event details and bundle reasons (tags, ``</script>``, quotes,
Alpine directives) adds no element and no attribute: the page's tag/attribute
shape equals the shape of the same page rendered with harmless text. The
renderer and the component script contain no ``x-html`` and no ``innerHTML``.

**Validates: scorecard Requirements 10.5, SP12**
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from _scorecard_html import parse
from _scorecard_strategies import scorecard_inputs
from hypothesis import given, settings
from hypothesis import strategies as st

from hauntlet.scorecard.build import build
from hauntlet.scorecard.facts import Fact
from hauntlet.scorecard.render import render

PKG = Path(__file__).resolve().parents[1] / "src" / "hauntlet" / "scorecard"

hostile = st.one_of(
    st.sampled_from([
        "<script>alert(1)</script>", "</script><img src=x onerror=alert(1)>", '"><b x-html="1">',
        "' @click='steal()'", "<template x-if=1>", "{{ 7*7 }}", "&lt;b&gt;", "\u2028</script>",
        "<!-- x -->", "<style>*{}</style>",
    ]),
    st.text(alphabet="<>\"'&/=@:x- ", max_size=40),
)


def _swap_facts(ri, value):
    return replace(ri, facts=tuple(replace(f, fields={k: value for k in f.fields}) for f in ri.facts))


def _with(inp, value):
    inp = replace(inp, before=_swap_facts(inp.before, value))
    ex = inp.exorcism
    if ex is not None and ex.bundle:
        bundle = json.loads(json.dumps(ex.bundle))
        for it in bundle.get("items", ()):
            it["reason"] = value
        after = _swap_facts(ex.after, value) if ex.after is not None else None
        inp = replace(inp, exorcism=replace(ex, bundle=bundle, after=after))
    return inp


@settings(max_examples=100, deadline=None)
@given(case=scorecard_inputs(), bad=hostile)
def test_sp12_hostile_text_adds_no_markup(case, bad) -> None:
    inp = replace(case.inp, before=replace(case.inp.before, facts=case.inp.before.facts + (
        Fact("event", "filesystem:acted", case.before.manifest.rooms[0].room, None, None, {"detail": "x"}),)))
    clean = parse(render(build(_with(inp, "x"))))
    dirty_html = render(build(_with(inp, bad)))
    dirty = parse(dirty_html)
    assert dirty.tag_shape() == clean.tag_shape()
    assert set(dirty.scripts) == set(clean.scripts)
    json.loads(dirty.scripts["sc-data"])  # the embedded data still parses


def test_no_html_injection_sinks_in_the_source() -> None:
    for name in ("render.py", "static/scorecard.js", "build.py"):
        src = (PKG / name).read_text(encoding="utf-8")
        assert "x-html" not in src and "innerHTML" not in src and "outerHTML" not in src, name
        assert "eval(" not in src and "new Function" not in src, name
