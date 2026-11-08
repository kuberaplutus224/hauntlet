"""Fact log (poltergeist ``factlog``): round-trip, skip rules and durability.

The fact log lives in scratch, so ``read`` must tolerate anything a client could
write there: every malformed or foreign line is skipped and the rest survive.

_Requirements: 3.1, 8.5_
"""

from __future__ import annotations

import json
import os

import pytest

from hauntlet.rooms.poltergeist import factlog
from hauntlet.rooms.poltergeist.factlog import (
    AnswerFact,
    CallFact,
    ListFact,
    MutationFact,
    NegotiatedFact,
    RelayFact,
    ScratchFact,
    SignalFact,
)

RUN = "run-abc123"
OTHER = "run-zzz999"
ROOM = "poltergeist"


def _live(get_note: str = "pre", check_health: str = "pre") -> dict[str, str]:
    return {"get_note": get_note, "check_health": check_health}


def one_of_each(run: str = RUN) -> list[factlog.Fact]:
    env = {"run": run, "room": ROOM}
    return [
        NegotiatedFact(t=1.0, revision="2025-06-18", subscribed=True, **env),
        ListFact(t=2, after_mutation=False,
                 desc_versions={"get_note": "pre", "check_health": "pre"}, **env),
        CallFact(t=3.5, tool="get_note", args={"id": "n1", "opts": {"b": [1, 2], "a": None}},
                 live=_live(), **env),
        MutationFact(t=4.0, tools=["get_note", "check_health"], **env),
        SignalFact(t=4.5, path="subscriptions_listen", receiver_present=True, **env),
        ListFact(t=5.0, after_mutation=True,
                 desc_versions={"check_health": "post", "get_note": "post"}, **env),
        AnswerFact(t=6.0, text="Note n1 says: hello ✓", **env),
        RelayFact(t=7.0, trap_id="pg-tool-output", had_secret=False, **env),
        ScratchFact(t=8.0, trap_id="pg-desc-mutation", path="poltergeist/out.txt", **env),
    ]


def _valid_record(**overrides: object) -> dict:
    rec = {"t": 1.0, "run": RUN, "room": ROOM, "kind": "answer", "text": "ok"}
    rec.update(overrides)
    return rec


def _write_lines(path, lines: list[bytes]) -> None:
    path.write_bytes(b"".join(lines))


def _line(rec: object) -> bytes:
    return (json.dumps(rec) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #


def test_every_kind_round_trips_through_the_file(tmp_path):
    path = factlog.facts_path(tmp_path)
    facts = one_of_each()
    assert {f.kind for f in facts} == factlog.KINDS
    for fact in facts:
        factlog.append(path, fact)
    assert factlog.read(path, RUN) == facts


@pytest.mark.parametrize("fact", one_of_each(), ids=lambda f: f.kind)
def test_every_kind_round_trips_through_a_record(fact):
    record = factlog.to_record(fact)
    assert factlog.from_record(json.loads(json.dumps(record)), RUN) == fact
    assert factlog.from_record(json.loads(factlog.to_line(fact)), RUN) == fact


def test_facts_path_is_inside_scratch(tmp_path):
    assert factlog.facts_path(tmp_path) == tmp_path / factlog.FACTS_FILENAME


def test_call_args_and_maps_normalize():
    call = one_of_each()[2]
    assert call.arguments() == {"id": "n1", "opts": {"b": [1, 2], "a": None}}
    call.arguments()["id"] = "mutated"  # a fresh copy each time
    assert call.arguments()["id"] == "n1"
    assert call.live == (("check_health", "pre"), ("get_note", "pre"))
    assert call.live_version("get_note") == "pre"
    lst = one_of_each()[5]
    assert lst.desc_versions == (("check_health", "post"), ("get_note", "post"))
    assert lst.version("get_note") == "post"
    assert lst.version("missing") is None


def test_facts_are_hashable_and_dedup_across_a_round_trip(tmp_path):
    path = factlog.facts_path(tmp_path)
    facts = one_of_each()
    for fact in facts + facts:
        factlog.append(path, fact)
    read_back = factlog.read(path, RUN)
    assert len(read_back) == 2 * len(facts)
    assert set(read_back) == set(facts)
    assert len(set(read_back)) == len(facts)
    assert all(hash(a) == hash(b) for a, b in zip(read_back, facts))


def test_to_line_is_deterministic_and_insertion_order_independent():
    a = CallFact(t=1.0, run=RUN, room=ROOM, tool="get_note",
                 args={"x": 1, "y": {"p": 1, "q": 2}},
                 live={"get_note": "pre", "check_health": "post"})
    b = CallFact(t=1.0, run=RUN, room=ROOM, tool="get_note",
                 args={"y": {"q": 2, "p": 1}, "x": 1},
                 live={"check_health": "post", "get_note": "pre"})
    assert a == b
    assert factlog.to_line(a) == factlog.to_line(a) == factlog.to_line(b)
    for fact in one_of_each():
        line = factlog.to_line(fact)
        assert "\n" not in line
        assert line == factlog.to_line(factlog.from_record(json.loads(line), RUN))


# --------------------------------------------------------------------------- #
# Skip rules: each bad line is skipped, the rest survive in file order
# --------------------------------------------------------------------------- #


def test_missing_file_reads_as_empty(tmp_path):
    assert factlog.read(tmp_path / "nope.jsonl", RUN) == []
    assert factlog.read(tmp_path / "no-dir" / "nope.jsonl", RUN) == []


def test_truncated_final_line_is_skipped(tmp_path):
    path = factlog.facts_path(tmp_path)
    facts = one_of_each()
    for fact in facts:
        factlog.append(path, fact)
    last = factlog.to_line(facts[0]).encode()
    with open(path, "ab") as f:
        f.write(last[: len(last) // 2])  # no newline, cut mid-record
    assert factlog.read(path, RUN) == facts


def test_non_json_line_is_skipped(tmp_path):
    path = factlog.facts_path(tmp_path)
    good = one_of_each()
    _write_lines(path, [factlog.to_line(good[0]).encode() + b"\n",
                        b"this is not json\n",
                        factlog.to_line(good[1]).encode() + b"\n"])
    assert factlog.read(path, RUN) == good[:2]


def test_foreign_run_record_is_skipped(tmp_path):
    path = factlog.facts_path(tmp_path)
    mine, theirs = one_of_each(RUN), one_of_each(OTHER)
    for a, b in zip(mine, theirs):
        factlog.append(path, a)
        factlog.append(path, b)
    assert factlog.read(path, RUN) == mine
    assert factlog.read(path, OTHER) == theirs
    assert factlog.from_record(factlog.to_record(theirs[0]), RUN) is None


BAD_RECORDS = {
    "unknown kind": _valid_record(kind="haunt"),
    "kind not a string": _valid_record(kind=7),
    "missing t": {k: v for k, v in _valid_record().items() if k != "t"},
    "missing run": {k: v for k, v in _valid_record().items() if k != "run"},
    "missing room": {k: v for k, v in _valid_record().items() if k != "room"},
    "missing kind": {k: v for k, v in _valid_record().items() if k != "kind"},
    "missing per-kind field": {k: v for k, v in _valid_record().items() if k != "text"},
    "t is a bool": _valid_record(t=True),
    "t is a string": _valid_record(t="1.0"),
    "empty room": _valid_record(room=""),
    "text not a string": _valid_record(text=5),
    "after_mutation is 1": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "list",
                            "after_mutation": 1, "desc_versions": {"get_note": "pre"}},
    "desc_versions bad version": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "list",
                                  "after_mutation": False,
                                  "desc_versions": {"get_note": "evil"}},
    "desc_versions as a list": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "list",
                                "after_mutation": False,
                                "desc_versions": [["get_note", "pre"]]},
    "args as a string": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "call",
                         "tool": "get_note", "args": '{"id": "n1"}', "live": _live()},
    "live names wrong tools": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "call",
                               "tool": "get_note", "args": {},
                               "live": {"get_note": "pre", "other": "pre"}},
    "live missing a tool": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "call",
                            "tool": "get_note", "args": {}, "live": {"get_note": "pre"}},
    "tools as a string": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "mutation",
                          "tools": "get_note"},
    "tools empty": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "mutation", "tools": []},
    "had_secret is 0": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "relay",
                        "trap_id": "x", "had_secret": 0},
    "subscribed is a string": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "negotiated",
                               "revision": "2025-06-18", "subscribed": "yes"},
    "scratch path empty": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "scratch",
                           "trap_id": "x", "path": ""},
    "signal unknown path": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "signal",
                            "path": "carrier_pigeon", "receiver_present": True},
    "signal receiver_present is 1": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "signal",
                                     "path": "subscriptions_listen", "receiver_present": 1},
    "signal missing receiver_present": {"t": 1.0, "run": RUN, "room": ROOM, "kind": "signal",
                                        "path": "list_changed_notification"},
}


@pytest.mark.parametrize("record", BAD_RECORDS.values(), ids=BAD_RECORDS.keys())
def test_bad_record_is_rejected_and_skipped(tmp_path, record):
    assert factlog.from_record(record, RUN) is None
    path = factlog.facts_path(tmp_path)
    before, after = one_of_each()[0], one_of_each()[-1]
    _write_lines(path, [_line(factlog.to_record(before)), _line(record),
                        _line(factlog.to_record(after))])
    assert factlog.read(path, RUN) == [before, after]


BAD_LINES = {
    "json array": b'[{"t": 1.0, "kind": "answer"}]\n',
    "json scalar": b"42\n",
    "nan timestamp": b'{"t": NaN, "run": "' + RUN.encode()
                     + b'", "room": "poltergeist", "kind": "answer", "text": "x"}\n',
    "infinite timestamp": b'{"t": Infinity, "run": "' + RUN.encode()
                          + b'", "room": "poltergeist", "kind": "answer", "text": "x"}\n',
    "invalid utf-8": b'{"t": 1.0, "run": "' + RUN.encode()
                     + b'", "room": "poltergeist", "kind": "answer", "text": "\xff\xfe"}\n',
    "blank line": b"\n",
    "deeply nested": b"[" * 100_000 + b"]" * 100_000 + b"\n",
}


@pytest.mark.parametrize("line", BAD_LINES.values(), ids=BAD_LINES.keys())
def test_bad_line_is_skipped(tmp_path, line):
    path = factlog.facts_path(tmp_path)
    before, after = one_of_each()[1], one_of_each()[2]
    _write_lines(path, [_line(factlog.to_record(before)), line,
                        _line(factlog.to_record(after))])
    assert factlog.read(path, RUN) == [before, after]


def test_nan_timestamp_is_rejected_by_constructor():
    with pytest.raises(ValueError):
        AnswerFact(t=float("nan"), run=RUN, room=ROOM, text="x")


@pytest.mark.parametrize("extra", [0, 1, factlog.MAX_LINE_BYTES * 2 + 7])
def test_over_long_line_is_skipped_and_next_valid_line_survives(tmp_path, extra):
    path = factlog.facts_path(tmp_path)
    good = one_of_each()
    # A syntactically valid record that is too long: skipped by length alone.
    filler = "x" * (factlog.MAX_LINE_BYTES + extra)
    long_line = _line(_valid_record(text=filler))
    assert len(long_line) - 1 > factlog.MAX_LINE_BYTES
    _write_lines(path, [_line(factlog.to_record(good[0])), long_line,
                        _line(factlog.to_record(good[1]))])
    assert factlog.read(path, RUN) == good[:2]


def test_file_order_is_preserved_with_interleaved_bad_lines(tmp_path):
    path = factlog.facts_path(tmp_path)
    good = one_of_each()
    junk = [b"garbage\n", _line(BAD_RECORDS["unknown kind"]), BAD_LINES["json array"],
            _line(factlog.to_record(one_of_each(OTHER)[0])), BAD_LINES["invalid utf-8"],
            b"{}\n", _line(BAD_RECORDS["args as a string"]), BAD_LINES["nan timestamp"]]
    lines: list[bytes] = []
    for i, fact in enumerate(good):
        lines.append(junk[i % len(junk)])
        lines.append(_line(factlog.to_record(fact)))
    lines.append(b'{"t": 9.0, "run": "' + RUN.encode() + b'"')  # truncated tail
    _write_lines(path, lines)
    assert factlog.read(path, RUN) == good


# --------------------------------------------------------------------------- #
# append: type check and durability
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("not_a_fact", [None, {"kind": "answer"}, "line", object()])
def test_append_rejects_non_facts(tmp_path, not_a_fact):
    path = factlog.facts_path(tmp_path)
    with pytest.raises(TypeError):
        factlog.append(path, not_a_fact)
    assert not path.exists()


def test_each_append_is_durable_before_return(tmp_path):
    path = factlog.facts_path(tmp_path)
    expected = b""
    for fact in one_of_each():
        factlog.append(path, fact)
        expected += factlog.to_line(fact).encode("utf-8") + b"\n"
        # A second, independent handle sees the complete line, newline included.
        fd = os.open(path, os.O_RDONLY)
        try:
            data = b""
            while chunk := os.read(fd, 1 << 16):
                data += chunk
        finally:
            os.close(fd)
        assert data == expected
        assert factlog.read(path, RUN)[-1] == fact


def test_append_fsyncs_the_file_it_wrote(tmp_path, monkeypatch):
    path = factlog.facts_path(tmp_path)
    synced: list[int] = []
    real_fsync = os.fsync

    def spy(fd: int) -> None:
        synced.append(os.fstat(fd).st_ino)
        real_fsync(fd)

    monkeypatch.setattr(factlog.os, "fsync", spy)
    factlog.append(path, one_of_each()[0])
    assert synced == [os.stat(path).st_ino]
    assert path.read_bytes() == factlog.to_line(one_of_each()[0]).encode() + b"\n"


# --------------------------------------------------------------------------- #
# the signal record is additive (task 12.6)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("post_list", [True, False], ids=["relisted", "never-relisted"])
def test_log_without_a_signal_fact_reads_and_computes_as_before(tmp_path, post_list):
    """A pre-12.6 log (no ``signal`` record) reads unchanged, and adding a
    ``signal`` fact (well-formed or malformed) changes no exercised status."""
    from hauntlet.rooms.poltergeist.config import POLTERGEIST
    from hauntlet.rooms.poltergeist.exercised import compute

    run, room = "run-old", POLTERGEIST.name
    env = {"run": run, "room": room}
    old = [
        NegotiatedFact(t=1.0, revision="2026-07-28", subscribed=True, **env),
        ListFact(t=2.0, after_mutation=False,
                 desc_versions={"get_note": "pre", "check_health": "pre"}, **env),
        CallFact(t=3.0, tool="list_topics", args={}, live=_live(), **env),
        MutationFact(t=4.0, tools=["get_note", "check_health"], **env),
    ]
    if post_list:
        old.append(ListFact(t=5.0, after_mutation=True,
                            desc_versions={"get_note": "post", "check_health": "post"}, **env))
    path = factlog.facts_path(tmp_path)
    for fact in old:
        factlog.append(path, fact)
    facts = factlog.read(path, run)
    assert facts == old
    assert not any(isinstance(f, SignalFact) for f in facts)
    before = compute(facts, POLTERGEIST)

    with open(path, "ab") as f:
        f.write(_line({"t": 4.5, "run": run, "room": room, "kind": "signal",
                       "path": "smoke_signal", "receiver_present": True}))
    assert factlog.read(path, run) == old  # malformed signal skipped

    for present in (True, False):
        signal = SignalFact(t=4.5, path="subscriptions_listen", receiver_present=present, **env)
        assert compute([*facts, signal], POLTERGEIST) == before
