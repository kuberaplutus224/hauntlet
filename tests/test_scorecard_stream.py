"""The live evidence stream (scorecard D22; SP16 and the stream half of SP10; task 16.2).

- **SP16:** for finished runs, the ``fact`` events up to ``done`` equal the rows
  the page embeds, IDs and texts, in order;
- **SP10:** no canary value in the stream bytes (the raw facts did carry some);
- an active run: a second thread records a canary hit and then finalizes; the
  client sees the hit, then ``finalized``, then ``done``;
- ``Last-Event-ID`` resumes without duplicates; 404 for unknown and hostile IDs;
  429 over the cap; ``X-Robots-Tag`` and ``Cache-Control: no-store`` present.

**Validates: scorecard Requirements 8.7, 8.8, 10.3, 10.7, SP10, SP16, D22**
"""

from __future__ import annotations

import json
import threading
import time
from urllib.parse import quote

import pytest
from _scorecard_html import parse
from fastapi.testclient import TestClient
from test_scorecard_redaction import leaks

from hauntlet.agents import get_agent
from hauntlet.core.runner import run_once
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.paths import scratch_root_beside
from hauntlet.rooms import default_rooms
from hauntlet.scorecard import render_run
from hauntlet.server import create_app


def _events(text: str) -> list[tuple[str, str | None, dict | None]]:
    out = []
    for block in text.split("\n\n"):
        name = eid = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("id: "):
                eid = line[4:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            out.append((name, eid, data))
    return out


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "range" / "range.db"
    monkeypatch.setenv("HAUNTLET_DB", str(db))
    monkeypatch.setenv("HAUNTLET_STREAM_POLL_SECS", "0.05")
    svc = RangeService(Store(db), default_rooms())
    return svc, db


def _get(client, url, **headers):
    r = client.get(url, headers=headers)
    return r, _events(r.text)


@pytest.mark.parametrize("room", sorted(default_rooms()))
def test_sp16_finished_run_stream_equals_the_page(env, room) -> None:
    svc, db = env
    r = run_once(svc, room, get_agent("naive"), scratch_root_beside(db), keep_workspace=True)
    run_id = r.score.run_id
    c = TestClient(create_app(svc))
    resp, events = _get(c, f"/runs/{run_id}/facts/stream")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-robots-tag"] == "noindex, nofollow" and resp.headers["cache-control"] == "no-store"
    names = [e[0] for e in events]
    assert names[-2:] == ["finalized", "done"] and names.count("done") == 1
    facts = [e for e in events if e[0] == "fact"]
    assert all(eid == data["fact_id"] for _, eid, data in facts)

    doc = parse(render_run(svc, run_id, path="reference:naive", db_path=db))
    embedded = [(a["data-fact-id"]) for t, a in doc.elements if t == "li" and "data-fact-id" in a]
    assert [d["fact_id"] for _, _, d in facts] == embedded
    row_text = {}
    for n in doc.nodes:
        fid = n.attr("data-fact-id")
        if fid:
            row_text.setdefault(fid, []).append(n.text)
    for _, _, d in facts:
        assert d["text"] in row_text[d["fact_id"]] and d["time"] in row_text[d["fact_id"]]
    assert not leaks(resp.text, svc.canaries(run_id))


def test_stream_redacts_what_the_raw_facts_carried(env) -> None:
    svc, db = env
    r = run_once(svc, "poltergeist", get_agent("naive"), scratch_root_beside(db), keep_workspace=True)
    raw = "".join(p.read_text() for p in scratch_root_beside(db).glob(f"poltergeist-{r.score.run_id}/*-facts.jsonl"))
    assert leaks(raw, svc.canaries(r.score.run_id))
    resp, _ = _get(TestClient(create_app(svc)), f"/runs/{r.score.run_id}/facts/stream")
    assert not leaks(resp.text, svc.canaries(r.score.run_id))


def test_active_run_sees_hit_then_finalized_then_done(env) -> None:
    svc, db = env
    desc = svc.start_run(["threshold"], grace_window_secs=0.3)
    run_id = desc.run.run_id
    url_token = next(cn.value for cn in desc.canaries if cn.kind == "url" and not cn.is_control)
    secret = next(cn.value for cn in desc.canaries if cn.kind == "secret")

    def agent():
        time.sleep(0.3)
        svc.record_hit(url_token, f"k={quote(secret)}")
        time.sleep(0.3)
        svc.finalize(run_id, [], transcript_provided=False)

    t = threading.Thread(target=agent)
    t.start()
    resp, events = _get(TestClient(create_app(svc)), f"/runs/{run_id}/facts/stream")
    t.join()
    names = [e[0] for e in events]
    first_fact = names.index("fact")
    assert first_fact < names.index("finalized") < names.index("done")
    texts = [d["text"] for n, _, d in events if n == "fact"]
    assert any("Fetched a planted link" in x for x in texts) and any("HAUNTLET-DUMMY-…" in x for x in texts)
    assert not leaks(resp.text, svc.canaries(run_id))


def test_last_event_id_resumes_without_duplicates(env) -> None:
    svc, db = env
    r = run_once(svc, "cursed-repo", get_agent("naive"), scratch_root_beside(db))
    c = TestClient(create_app(svc))
    _, events = _get(c, f"/runs/{r.score.run_id}/facts/stream")
    ids = [eid for n, eid, _ in events if n == "fact"]
    assert len(ids) >= 3
    _, again = _get(c, f"/runs/{r.score.run_id}/facts/stream", **{"Last-Event-ID": ids[1]})
    assert [eid for n, eid, _ in again if n == "fact"] == ids[2:]


@pytest.mark.parametrize("bad", ["no-such-run-0001", "short", "a" * 65, "..%2F..%2Fetc", "%2e%2e"])
def test_unknown_and_hostile_ids_are_404(env, bad) -> None:
    svc, _ = env
    r = TestClient(create_app(svc)).get(f"/runs/{bad}/facts/stream")
    assert r.status_code == 404 and r.headers["x-robots-tag"] == "noindex, nofollow"


def test_cap_gives_429_and_frees_its_slot(env, monkeypatch) -> None:
    svc, db = env
    monkeypatch.setenv("HAUNTLET_STREAM_MAX", "1")
    r = run_once(svc, "threshold", get_agent("naive"), scratch_root_beside(db))
    app = create_app(svc)
    c = TestClient(app)
    app.state.stream_slots.acquire()  # a stream already in flight
    try:
        assert c.get(f"/runs/{r.score.run_id}/facts/stream").status_code == 429
    finally:
        app.state.stream_slots.release()
    assert c.get(f"/runs/{r.score.run_id}/facts/stream").status_code == 200
    assert c.get(f"/runs/{r.score.run_id}/facts/stream").status_code == 200  # the slot came back
