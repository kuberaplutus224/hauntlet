"""Nothing invented (scorecard SP1, task 12.4).

Two halves:

1. **Renderer:** every visible text node of the page is a view-model string,
   a fixed copy string, an imported text, or glue ("→", ",", ":").
2. **Builder:** every text-bearing view-model string is derivable from the
   sources: an input value (score, manifest, bundle, delta, facts), an imported
   text, a fixed copy string, a copy template filled with anything, or a join of
   those with the separators the builder uses.

**Validates: scorecard Requirements 1.1–1.3, SP1**
"""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from functools import lru_cache

from _scorecard_html import parse
from _scorecard_strategies import REGISTERED, scorecard_inputs
from hypothesis import given, settings

from hauntlet.core.levels import Level
from hauntlet.core.models import to_dict
from hauntlet.exorcist import CLASS_TEXT
from hauntlet.exorcist import texts
from hauntlet.exorcist.report import DEMO_NOTES
from hauntlet.scorecard import copy
from hauntlet.scorecard.build import build
from hauntlet.scorecard.render import render
from hauntlet.scorecard.rooms import ROOM_CARDS

GLUE = {"→", ",", ":", "·", "(", ")"}
SEPS = (" · ", " → ", "; ", ", ", " and ")
#: View-model keys that are identifiers or CSS, not displayed text.
NOT_TEXT = {"fact_id", "ids", "token", "kind", "run_role", "source", "next_step", "toggle", "stream_url", "path", "ref"}


def _strings(obj, out: set[str]) -> None:
    if isinstance(obj, str):
        out.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _strings(v, out)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for v in obj:
            _strings(v, out)
    elif is_dataclass(obj):
        _strings(asdict(obj), out)


@lru_cache(maxsize=1)
def _fixed() -> tuple[frozenset[str], tuple[re.Pattern[str], ...]]:
    lits: set[str] = set()
    for name, v in vars(copy).items():
        if name.isupper():
            _strings(v, lits)
    for name in dir(texts):
        if name.isupper():
            _strings(getattr(texts, name), lits)
    _strings(list(texts.ASSUMPTIONS), lits)
    _strings(DEMO_NOTES, lits)
    _strings(CLASS_TEXT, lits)
    _strings(ROOM_CARDS, lits)
    lits |= {f"{lv.name} {lv.label}" for lv in Level}  # core's level names (levels.py)
    lits |= set(REGISTERED)  # the room registry
    templates = []
    for s in list(lits):
        if re.search(r"\{[a-z_]+\}", s):
            parts = re.split(r"\{[a-z_]+\}", s)
            pat = "(.+)".join(re.escape(p.strip(" ·")) for p in parts)
            templates.append(re.compile("^" + pat.strip() + "$", re.DOTALL))
    return frozenset(x.strip() for x in lits if "{" not in x), tuple(templates)


def _inputs(case) -> set[str]:
    out: set[str] = set()
    _strings(to_dict(case.before.score), out)
    _strings(to_dict(case.before.manifest), out)
    _strings(case.delta or {}, out)
    _strings(case.bundle or {}, out)
    for f in case.inp.before.facts:
        _strings(dict(f.fields), out)
    ex = case.inp.exorcism
    if ex is not None and ex.after is not None:
        for f in ex.after.facts:
            _strings(dict(f.fields), out)
    out.add(case.inp.agent_name)
    return {s.strip() for s in out if s.strip()}


def _derivable(s: str, allowed: frozenset[str], templates, depth: int = 0) -> bool:
    s = s.strip()
    if not s or s in allowed or re.fullmatch(r"[\d\s.,%+→·:()^-]*", s):
        return True
    if any(p.match(s) for p in templates):
        return True
    if depth > 3:
        return False
    for sep in SEPS:
        if sep in s and all(_derivable(p, allowed, templates, depth + 1) for p in s.split(sep)):
            return True
    for lit in allowed:
        if len(lit) > 3 and s.startswith(lit + " ") and _derivable(s[len(lit) + 1 :], allowed, templates, depth + 1):
            return True
    return False


def _vm_texts(obj, out: list[str], key: str = "") -> None:
    if is_dataclass(obj):
        obj = asdict(obj)
    if isinstance(obj, dict):
        pill = "cost" in obj
        for k, v in obj.items():
            if k in NOT_TEXT or (pill and k == "name"):
                continue
            _vm_texts(v, out, k)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _vm_texts(v, out, key)
    elif isinstance(obj, str):
        out.append(obj)


@settings(max_examples=80, deadline=None)
@given(case=scorecard_inputs())
def test_sp1_builder_strings_come_from_the_sources(case) -> None:
    vm = build(case.inp)
    lits, templates = _fixed()
    allowed = lits | frozenset(_inputs(case))
    texts_: list[str] = []
    _vm_texts(vm, texts_)
    bad = sorted({s for s in texts_ if not _derivable(s, allowed, templates)})
    assert not bad, bad[:5]


@settings(max_examples=60, deadline=None)
@given(case=scorecard_inputs())
def test_sp1_renderer_text_nodes_are_known(case) -> None:
    vm = build(case.inp)
    doc = parse(render(vm))
    lits, templates = _fixed()
    vm_strings: set[str] = set()
    _strings(vm, vm_strings)
    allowed = lits | frozenset(s.strip() for s in vm_strings)
    bad = sorted({n.text for n in doc.nodes if n.text not in allowed and n.text not in GLUE
                  and not any(p.match(n.text) for p in templates)})
    assert not bad, bad[:5]
    assert doc.title == copy.TITLE
