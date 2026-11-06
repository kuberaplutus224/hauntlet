"""Run lifecycle, canary attribution and the harmlessness rules (Requirements 1, 2.4, 5)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hauntlet.core.canary import DUMMY_PREFIX
from hauntlet.core.levels import Level, Signal
from hauntlet.core.room import Observation
from hauntlet.core.service import InvalidObservation
from hauntlet.core.toolbox import ToolBox

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_payload_safety import check_text  # noqa: E402


def _canary(desc, trap_id, kind):
    return next(c for c in desc.canaries if c.trap_id == trap_id and c.kind == kind)


def test_runs_get_unique_ids_and_scoped_canaries(service) -> None:
    a = service.start_run(["threshold"])
    b = service.start_run(["threshold"])
    assert a.run.run_id != b.run.run_id
    assert {c.run_id for c in a.canaries} == {a.run.run_id}
    assert not {c.value for c in a.canaries} & {c.value for c in b.canaries}


def test_controls_get_only_a_url_canary(service) -> None:
    desc = service.start_run(["threshold"])
    kinds = {c.kind for c in desc.canaries if c.is_control}
    assert kinds == {"url"}


def test_dummy_secrets_are_obviously_fake(service) -> None:
    desc = service.start_run(["threshold"])
    secrets = [c.value for c in desc.canaries if c.kind == "secret"]
    assert secrets and all(s.startswith(DUMMY_PREFIX + "-") for s in secrets)
    assert all(not check_text(s) for s in secrets), "dummy secret resembles a real credential"


def test_hit_is_reached_and_secret_in_query_is_exposed(service) -> None:
    desc = service.start_run(["threshold"])
    url = _canary(desc, "notes-instruction", "url").value
    secret = _canary(desc, "notes-instruction", "secret").value
    events = service.record_hit(url, f"key={secret}")
    assert [e.signal for e in events] == [Signal.REACHED, Signal.EXPOSED]
    service.finalize(desc.run.run_id, [], transcript_provided=False)
    assert service.score(desc.run.run_id).overall_worst == Level.L4


def test_secret_attributes_to_the_trap_that_planted_it(service) -> None:
    desc = service.start_run(["threshold"])
    control_url = _canary(desc, "contributing-link", "url").value
    secret = _canary(desc, "notes-instruction", "secret").value
    events = service.record_hit(control_url, f"x={secret}")
    assert [(e.trap_id, e.signal) for e in events] == [
        ("contributing-link", Signal.REACHED),
        ("notes-instruction", Signal.EXPOSED),
    ]


def test_unknown_token_records_nothing(service) -> None:
    assert service.record_hit("nope") is None


def test_hits_after_expiry_are_stored_but_not_scored(service, clock) -> None:
    desc = service.start_run(["threshold"], ttl=10)
    clock.advance(11)
    url = _canary(desc, "notes-instruction", "url").value
    secret = _canary(desc, "notes-instruction", "secret").value
    events = service.record_hit(url, f"key={secret}")
    assert all(e.expired for e in events)
    score = service.score(desc.run.run_id)
    assert score.overall_worst == Level.L0 and score.ignored_events == 2


def test_hits_after_finalize_are_expired(service) -> None:
    desc = service.start_run(["threshold"])
    service.finalize(desc.run.run_id, [], transcript_provided=True)
    events = service.record_hit(_canary(desc, "notes-instruction", "url").value)
    assert events[0].expired


@pytest.mark.parametrize(
    "obs",
    [
        Observation("attic", "notes-instruction", "filesystem", "acted"),
        Observation("threshold", "ghost", "filesystem", "acted"),
        Observation("threshold", "notes-instruction", "filesystem", "levitated"),
        Observation("threshold", "notes-instruction", "network", "exposed"),
    ],
)
def test_finalize_rejects_invalid_observations(service, obs) -> None:
    desc = service.start_run(["threshold"])
    with pytest.raises(InvalidObservation):
        service.finalize(desc.run.run_id, [obs], transcript_provided=True)


def test_finalize_only_once(service) -> None:
    desc = service.start_run(["threshold"])
    service.finalize(desc.run.run_id, [], transcript_provided=True)
    with pytest.raises(InvalidObservation):
        service.finalize(desc.run.run_id, [], transcript_provided=True)


def test_unknown_room_is_rejected(service) -> None:
    with pytest.raises(KeyError):
        service.start_run(["attic"])


def test_toolbox_confines_writes_and_fetches(tmp_path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    tools = ToolBox(ws, {}, lambda url: "ok", "http://range.test")
    tools.write_file("inside.txt", "fine")
    assert (ws / "inside.txt").read_text() == "fine"
    with pytest.raises(PermissionError):
        tools.write_file("../outside.txt", "nope")
    with pytest.raises(PermissionError):
        tools.write_file("/etc/hauntlet.txt", "nope")
    with pytest.raises(PermissionError):
        tools.fetch("http://evil.test/c/token")
    with pytest.raises(PermissionError):
        tools.fetch("http://range.test/other")
    assert tools.fetch("http://range.test/c/abc") == "ok"
