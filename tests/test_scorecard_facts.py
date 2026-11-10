"""Facts for the evidence log (scorecard SP15, task 8.2).

- filesystem and transcript events show "at finalize"; network events and
  fact-log records keep their own time;
- transcript lines say they come from the submitted transcript; expired events
  say they were not scored;
- a fact names a trap only when the record names one in the room's manifest,
  or an MCP call's tool is a declared steered tool; demo decisions never do;
- IDs are content-derived: stable across orderings and random ``event_id``s;
- every phrase is fixed copy.

**Validates: scorecard Requirements 8.2–8.6, SP15**
"""

from __future__ import annotations

import random
import re
import string

from hypothesis import given, settings
from hypothesis import strategies as st

from hauntlet.core.levels import PAGE_TRAP_ID, TASK_TRAP_ID
from hauntlet.core.models import Event, Run, RunManifest
from hauntlet.exorcist.profiles import profile_for
from hauntlet.rooms import default_rooms
from hauntlet.rooms.parlor import factlog as pfl
from hauntlet.rooms.poltergeist import factlog as mfl
from hauntlet.scorecard import copy
from hauntlet.scorecard.facts import (
    lines,
    normalise_event,
    normalise_mcp,
    normalise_parlor,
    normalise_trace,
)

ROOMS = default_rooms()
RUN_ID = "factsRun0001"
MANIFEST = RunManifest(RUN_ID, tuple(ROOMS[n].manifest() for n in ("cursed-repo", "poltergeist", "parlor")))
RUN = Run(RUN_ID, 1000.0, 1900.0, 0, finalized_at=1060.0)
STEERED = dict(profile_for("poltergeist").mcp.steered_tools)
TRAPS = {rm.room: [t.trap_id for t in rm.traps] for rm in MANIFEST.rooms}

words = st.text(alphabet=string.ascii_letters + string.digits + " .{}<>&\"'", max_size=30)
room_names = st.sampled_from(sorted(TRAPS))


@st.composite
def events(draw) -> Event:
    room = draw(room_names)
    trap = draw(st.sampled_from(TRAPS[room] + [TASK_TRAP_ID, "unknown-trap"]))
    channel = draw(st.sampled_from(["network", "filesystem", "transcript"]))
    signal = draw(st.sampled_from(["reached", "echoed", "acted", "exposed", "flagged", "task_done", "not_exercised"]))
    return Event(RUN_ID, room, trap, channel, signal, 1000.0 + draw(st.floats(0, 100)), draw(words),
                 expired=draw(st.booleans()), late_by_secs=draw(st.floats(0, 50)),
                 event_id=draw(st.text(alphabet="0123456789abcdef", min_size=16, max_size=16)))


@st.composite
def mcp_records(draw):
    t = 1000.0 + draw(st.floats(0, 100))
    kind = draw(st.sampled_from(sorted(mfl.KINDS)))
    trap = draw(st.sampled_from(TRAPS["poltergeist"] + ["not-a-trap"]))
    env = (t, RUN_ID, "poltergeist")
    if kind == "negotiated":
        return mfl.NegotiatedFact(*env, revision="2026-07-28", subscribed=draw(st.booleans()))
    if kind == "list":
        return mfl.ListFact(*env, after_mutation=draw(st.booleans()), desc_versions={"get_note": "pre"})
    if kind == "call":
        tool = draw(st.sampled_from(["get_note", "list_topics", "save_note", "report_telemetry"]))
        return mfl.CallFact(*env, tool=tool, args={"q": draw(words)}, live={"get_note": "pre", "check_health": "pre"})
    if kind == "mutation":
        return mfl.MutationFact(*env, tools=("get_note",))
    if kind == "signal":
        return mfl.SignalFact(*env, path=mfl.SIGNAL_LISTEN, receiver_present=draw(st.booleans()))
    if kind == "answer":
        return mfl.AnswerFact(*env, text=draw(words))
    if kind == "relay":
        return mfl.RelayFact(*env, trap_id=trap, had_secret=draw(st.booleans()))
    if kind == "scratch":
        return mfl.ScratchFact(*env, trap_id=trap, path="sync-ack.txt")
    return mfl.TakeoverFact(*env, previous="", count=0)


@st.composite
def parlor_records(draw):
    t = 1000.0 + draw(st.floats(0, 100))
    env = (t, RUN_ID, "parlor")
    kind = draw(st.sampled_from(["page", "image", "submit", "site_action", "dropped"]))
    if kind == "page":
        return pfl.PageFact(*env, page_id=draw(words))
    if kind == "image":
        return pfl.ImageFact(*env)
    if kind == "submit":
        return pfl.SubmitFact(*env, answer=draw(words), member_code=draw(words), to=draw(words))
    if kind == "site_action":
        return pfl.SiteActionFact(*env, trap_id=draw(st.sampled_from(TRAPS["parlor"] + ["nope"])), path="x.txt")
    return pfl.DroppedFact(*env, count=3)


def _phrase_regex(template: str) -> re.Pattern[str]:
    parts = re.split(r"\{[a-z_]+\}", template)
    return re.compile("^" + "(.*)".join(re.escape(p) for p in parts) + "$", re.DOTALL)


PHRASES = [_phrase_regex(p) for p in copy.FACT_PHRASES.values()]


@settings(max_examples=150, deadline=None)
@given(evs=st.lists(events(), max_size=8), mcp=st.lists(mcp_records(), max_size=6),
       parlor=st.lists(parlor_records(), max_size=4), trace=st.lists(st.tuples(st.sampled_from(["web_fetch", "fs_write"]), words, st.booleans()), max_size=4))
def test_sp15_times_notes_attribution_and_phrases(evs, mcp, parlor, trace) -> None:
    facts = [f for f in (normalise_event(e, MANIFEST) for e in evs) if f is not None]
    facts += [f for f in (normalise_mcp(m, MANIFEST, STEERED) for m in mcp) if f is not None]
    facts += [f for f in (normalise_parlor(p, MANIFEST) for p in parlor) if f is not None]
    facts += [normalise_trace((tool, where, "repo_file", ok, () if ok else ("a#B",)), i, "cursed-repo")
              for i, (tool, where, ok) in enumerate(trace)]
    log, demo = lines(facts, RUN, MANIFEST, "before")
    assert len(log) + len(demo) == len(facts)
    by_id = {ln.fact_id for ln in log + demo}
    assert len(by_id) == len(facts), "fact IDs are unique"

    for ln in log:
        assert any(p.match(ln.text) for p in PHRASES), ln.text
    for ln in demo:
        assert ln.time == "" and ln.trap_id is None and ln.who == copy.WHO_DEMO
        assert ln.tag in ("", copy.TAG_BLOCKED)

    # Events, matched back by content.
    for e in evs:
        if e.trap_id == PAGE_TRAP_ID:
            continue
        cand = [ln for ln in log if ln.source == "event" and ln.room == e.room
                and ln.trap_id == (e.trap_id if e.trap_id in TRAPS[e.room] else None)]
        assert cand
        if e.channel == "network":
            assert any(ln.time.startswith("+") for ln in cand)
        else:
            assert any(ln.time == copy.TIME_AT_FINALIZE for ln in cand)
    transcript_lines = [ln for ln in log if ln.source == "event" and "Transcript check" in ln.text]
    for ln in transcript_lines:
        assert copy.NOTE_TRANSCRIPT in ln.note
    n_expired = sum(1 for e in evs if e.expired and e.trap_id != PAGE_TRAP_ID)
    assert sum(1 for ln in log if "not scored" in ln.note) == n_expired

    # Trap attribution (8.6).
    for ln in log:
        if ln.trap_id is not None:
            assert ln.trap_id in TRAPS[ln.room]
    for m in mcp:
        f = normalise_mcp(m, MANIFEST, STEERED)
        if m.kind in ("relay", "scratch"):
            assert f.trap_id == (m.trap_id if m.trap_id in TRAPS["poltergeist"] else None)
        elif m.kind == "call":
            assert f.trap_id == STEERED.get(m.tool)
        else:
            assert f.trap_id is None


@settings(max_examples=80, deadline=None)
@given(evs=st.lists(events(), min_size=1, max_size=8), seed=st.integers())
def test_ids_are_stable_across_orderings_and_event_ids(evs, seed) -> None:
    a = [f for f in (normalise_event(e, MANIFEST) for e in evs) if f]
    shuffled = list(evs)
    random.Random(seed).shuffle(shuffled)
    renamed = [Event(**{**e.__dict__, "event_id": f"{i:016x}"}) for i, e in enumerate(shuffled)]
    b = [f for f in (normalise_event(e, MANIFEST) for e in renamed) if f]
    la, _ = lines(a, RUN, MANIFEST, "before")
    lb, _ = lines(b, RUN, MANIFEST, "before")
    assert [(x.fact_id, x.text) for x in la] == [(x.fact_id, x.text) for x in lb]


def test_order_timed_then_finalize_and_redaction_applies() -> None:
    evs = [
        Event(RUN_ID, "cursed-repo", "readme-register", "filesystem", "acted", 1060.0, "wrote x"),
        Event(RUN_ID, "cursed-repo", "readme-register", "network", "reached", 1005.0, "canary URL fetched"),
    ]
    log, _ = lines([normalise_event(e, MANIFEST, str.upper) for e in evs], RUN, MANIFEST, "before")
    assert [ln.time for ln in log] == ["+5.0 s", copy.TIME_AT_FINALIZE]
    assert "WROTE X" in log[1].text, "fields pass through the given redactor"
    long = Event(RUN_ID, "cursed-repo", "readme-register", "filesystem", "acted", 1060.0, "y" * 500)
    (ln,), _ = lines([normalise_event(long, MANIFEST)], RUN, MANIFEST, "before")
    assert len(ln.text) < 200 and "…" in ln.text
