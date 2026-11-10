"""Hypothesis strategies for the scorecard property tests (scorecard design "Correctness properties").

``scorecard_inputs()`` draws a ``ScorecardInput`` from a synthetic before run
(``_exorcist_strategies.runs``):

- the run is active, provisional or final;
- with no exorcism, a pending one (bundle, no after run), or one with an after
  run on the demo or real-client path;
- the after run is random per trap (levels, signals, false positives, task),
  with random "steered tool called, canary not reached" extras on MCP traps and,
  on the demo path, a trace whose denials come from the items citing each trap;
- the after ``RunInput`` is sometimes missing (an after run gone from the store).

It returns ``Case(inp, before, delta, bundle)`` so tests can compare against the
raw sources.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from _exorcist_strategies import ROOMS, SyntheticRun, runs
from hypothesis import strategies as st

from hauntlet.core.levels import Level, Signal
from hauntlet.core.models import Event, Run, RunScore, TrapScore
from hauntlet.exorcist import report
from hauntlet.exorcist.delta import DEMO, PENDING, REAL, build_delta
from hauntlet.exorcist.generate import generate
from hauntlet.exorcist.manifest import bundle_json
from hauntlet.exorcist.mcpfacts import STEERED_CALL_NO_CANARY
from hauntlet.exorcist.texts import DEMO_ENV_NOTE, DEMO_LABEL, PENDING_LABEL, REAL_CLIENT_LABEL
from hauntlet.redact import redactor
from hauntlet.rooms import default_rooms
from hauntlet.scorecard.facts import normalise_event
from hauntlet.scorecard.inputs import ExorcismInput, RunInput, ScorecardInput

REGISTERED = tuple(default_rooms())
CREATED = 1_700_000_000.0
MCP_ROOMS = ("poltergeist", "poltergeist-legacy")
TRAP_SIGNALS = ("reached", "echoed", "acted", "exposed", "flagged", "not_exercised")
BUNDLE_ID = "bundleSynth01"


@dataclass(frozen=True)
class Case:
    inp: ScorecardInput
    before: SyntheticRun
    delta: dict | None
    bundle: dict | None
    state: str  # "active" | "provisional" | "final"
    kind: str  # "none" | "pending" | "demo" | "real"
    events: tuple = ()  # the raw events behind the facts (details unredacted)


def _run(run_id: str, state: str) -> tuple[Run, float, bool]:
    if state == "active":
        return Run(run_id, CREATED, CREATED + 900, 0), CREATED + 10, True
    run = Run(run_id, CREATED, CREATED + 900, 0, finalized_at=CREATED + 60, grace_window_secs=30)
    if state == "provisional":
        return run, CREATED + 70, True
    return run, CREATED + 200, False


CHANNELS = ("network", "filesystem", "transcript")
EVENT_SIGNALS = ("reached", "echoed", "acted", "exposed", "flagged", "task_done", "not_exercised")


@st.composite
def run_events(draw, run: SyntheticRun, run_id: str, t0: float, details=None) -> tuple:
    """Stored events for random traps; details mix plain words with the run's canary values."""
    canaries = list(run.canaries)
    detail_text = details if details is not None else st.one_of(
        st.sampled_from(["canary URL fetched", "created a file", "marker repeated"]),
        st.builds(lambda i, how: (
            f"wrote {canaries[i % len(canaries)].value}" if how == 0
            else f"GET /c/{canaries[i % len(canaries)].value}?k={canaries[(i + 1) % len(canaries)].value}"
        ), st.integers(0, 1000), st.integers(0, 1)),
    )
    out = []
    for _ in range(draw(st.integers(0, 6))):
        rm = draw(st.sampled_from(run.manifest.rooms))
        trap = draw(st.sampled_from([t.trap_id for t in rm.traps] + ["__task__"]))
        out.append(Event(run_id, rm.room, trap, draw(st.sampled_from(CHANNELS)), draw(st.sampled_from(EVENT_SIGNALS)),
                         t0 + draw(st.floats(0, 50)), draw(detail_text), expired=draw(st.booleans())))
    red = redactor(canaries)
    return tuple(f for f in (normalise_event(e, run.manifest, red) for e in out) if f is not None), tuple(out)


@st.composite
def after_scores(draw, before: SyntheticRun) -> RunScore:
    rooms = []
    for rs in before.score.rooms:
        per = []
        for t in rs.per_trap:
            level = Level(draw(st.integers(0, 4)))
            sigs = tuple(sorted(draw(st.sets(st.sampled_from(TRAP_SIGNALS), max_size=3))))
            per.append(TrapScore(t.trap_id, t.is_control, level, Signal.FLAGGED in sigs, sigs))
        controls = [t.trap_id for t in rs.per_trap if t.is_control]
        fps = tuple(sorted(draw(st.sets(st.sampled_from(controls))))) if controls else ()
        worst = max((t.level for t in per if not t.is_control), default=Level.L0)
        rooms.append(replace(rs, per_trap=tuple(per), worst_level=worst, false_positives=fps,
                             task_completed=draw(st.booleans()), detected=draw(st.booleans()),
                             l2_assessed=draw(st.booleans())))
    overall = max((r.worst_level for r in rooms), default=Level.L0)
    return RunScore(before.score.run_id + "A", tuple(rooms), overall)


@st.composite
def scorecard_inputs(draw, kinds=("none", "pending", "demo", "real"), states=("active", "provisional", "final"), path=None, details=None):
    before = draw(runs())
    state = draw(st.sampled_from(states))
    kind = draw(st.sampled_from(kinds)) if state == "final" else "none"
    run, now, provisional = _run(before.score.run_id, state)
    score = replace(before.score, provisional=provisional)
    before = SyntheticRun(score, before.manifest, before.canaries)
    facts, events = draw(run_events(before, run.run_id, CREATED, details))
    before_ri = RunInput(run, score, before.manifest, facts)

    if kind == "none":
        p = path or draw(st.sampled_from(["demo-agent", "real-client", "reference:naive", "reference:hardened", "not-recorded"]))
        inp = ScorecardInput(p, before_ri, REGISTERED, now, served=draw(st.booleans()))
        return Case(inp, before, None, None, state, kind, events)

    spec = generate(before.score, before.manifest)
    bundle = json.loads(bundle_json(spec, BUNDLE_ID, 1.0))
    if kind == "pending":
        delta = build_delta(before.score, before.manifest, spec, path=PENDING, path_label=PENDING_LABEL)
        doc = json.loads(report.render_json(delta))
        inp = ScorecardInput("not-recorded", before_ri, REGISTERED, now,
                             exorcism=ExorcismInput(BUNDLE_ID, bundle, doc))
        return Case(inp, before, doc, bundle, state, kind, events)

    after = draw(after_scores(before))
    extras = {}
    for rm in before.manifest.rooms:
        if rm.room in MCP_ROOMS:
            for t in rm.traps:
                if not t.is_control and draw(st.booleans()):
                    extras[(rm.room, t.trap_id)] = {STEERED_CALL_NO_CANARY}
    trace = None
    if kind == "demo":
        trace = []
        for rm in before.manifest.rooms:
            for t in rm.traps:
                ref = f"{rm.room}/{t.trap_id}"
                deniers = tuple(i.item_id for i in spec.items if ref in i.cites)
                if deniers and draw(st.booleans()):
                    k = draw(st.integers(1, len(deniers)))
                    trace.append(("web_fetch", t.surface, "repo_file", False, deniers[:k]))
    delta = build_delta(
        before.score, before.manifest, spec,
        path=DEMO if kind == "demo" else REAL,
        path_label=DEMO_LABEL if kind == "demo" else REAL_CLIENT_LABEL,
        after=after, after_run_id=after.run_id, extras=extras,
        demo_env_note=DEMO_ENV_NOTE if kind == "demo" else None, trace=trace,
    )
    doc = json.loads(report.render_json(delta))
    after_run = Run(after.run_id, CREATED + 300, CREATED + 1200, 0, finalized_at=CREATED + 360)
    a_facts, a_events = draw(run_events(SyntheticRun(after, before.manifest, before.canaries), after.run_id, CREATED + 300, details))
    after_ri = RunInput(after_run, after, before.manifest, a_facts) if draw(st.booleans()) else None
    events = events + a_events
    inp = ScorecardInput(
        "demo-agent" if kind == "demo" else "real-client", before_ri, REGISTERED, CREATED + 2000,
        exorcism=ExorcismInput(BUNDLE_ID, bundle, doc, after_ri),
    )
    return Case(inp, before, doc, bundle, state, kind, events)
