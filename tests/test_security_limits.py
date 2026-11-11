"""Request caps, retention, per-client limits and headers (approved changes D33, D34, D35).

Each cap is tested just under (accepted) and just over (refused, never truncated).

**Validates: D33 (request caps, open-run cap, retention sweep), D34 (client key,
per-client quotas, stream lifetime), D35 (security headers, docs off when hosted)**
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.limits import Slots, Window, client_key
from hauntlet.rooms import default_rooms
from hauntlet.server import BASE_CSP, MAX_BODY_BYTES, MAX_DETAIL_CHARS, MAX_OBSERVATIONS, create_app


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HAUNTLET_DB", str(tmp_path / "range.db"))
    monkeypatch.setenv("HAUNTLET_REPORTS_DIR", str(tmp_path / "reports"))
    for k in ("HAUNTLET_HOSTED", "HAUNTLET_TRUST_PROXY", "HAUNTLET_BASE_URL", "RENDER_EXTERNAL_URL",
              "HAUNTLET_CLIENT_IP_HEADER", "HAUNTLET_LOG_CLIENT_KEY"):
        monkeypatch.delenv(k, raising=False)
    clock = Clock()

    def make(**env_vars):
        for k, v in env_vars.items():
            monkeypatch.setenv(k, v)
        svc = RangeService(Store(tmp_path / "range.db"), default_rooms(), clock=clock)
        return svc, TestClient(create_app(svc))

    return make, clock


def _ip(addr: str) -> dict:
    return {"X-Forwarded-For": addr}


# --------------------------------------------------------------------------- #
# D33: request caps
# --------------------------------------------------------------------------- #


def test_duplicate_rooms_are_refused(env) -> None:
    _, c = env[0]()
    assert c.post("/runs", json={"rooms": sorted(default_rooms())}).status_code == 201  # one of each
    r = c.post("/runs", json={"rooms": ["threshold", "threshold"]})
    assert r.status_code == 422 and "at most once" in r.text
    assert c.post("/runs", json={"rooms": ["attic"]}).status_code == 400  # unknown: as before


def _finalize(c, observations):
    rid = c.post("/runs", json={"rooms": ["threshold"]}).json()["run"]["run_id"]
    return c.post(f"/runs/{rid}/finalize", json={"observations": observations}), rid


def _obs(detail: str = "") -> dict:
    return {"room": "threshold", "trap_id": "notes-instruction", "channel": "filesystem", "signal": "acted", "detail": detail}


def test_detail_cap(env) -> None:
    svc, c = env[0]()
    r, rid = _finalize(c, [_obs("d" * MAX_DETAIL_CHARS)])
    assert r.status_code == 200
    assert [e.detail for e in svc.events(rid)] == ["d" * MAX_DETAIL_CHARS]  # stored whole
    r, rid = _finalize(c, [_obs("d" * (MAX_DETAIL_CHARS + 1))])
    assert r.status_code == 422
    assert svc.events(rid) == [] and svc.get_run(rid).finalized_at is None  # nothing stored


def test_observation_count_cap(env) -> None:
    _, c = env[0]()
    small = {"room": "threshold", "trap_id": "__task__", "channel": "filesystem", "signal": "task_done"}
    assert _finalize(c, [small] * MAX_OBSERVATIONS)[0].status_code == 200
    assert _finalize(c, [small] * (MAX_OBSERVATIONS + 1))[0].status_code == 422


def _padded(size: int) -> bytes:
    body = json.dumps({"observations": []}).encode()
    return body[:-1] + b" " * (size - len(body)) + b"}"


def test_body_cap_by_length_and_by_stream(env) -> None:
    _, c = env[0]()
    rid = c.post("/runs", json={"rooms": ["threshold"]}).json()["run"]["run_id"]
    rid2 = c.post("/runs", json={"rooms": ["threshold"]}).json()["run"]["run_id"]
    hdr = {"Content-Type": "application/json"}
    assert c.post(f"/runs/{rid}/finalize", content=_padded(MAX_BODY_BYTES + 1), headers=hdr).status_code == 413
    assert c.post(f"/runs/{rid}/finalize", content=_padded(MAX_BODY_BYTES), headers=hdr).status_code == 200

    def chunks():  # no Content-Length: chunked transfer
        data = _padded(MAX_BODY_BYTES + 1)
        for i in range(0, len(data), 4096):
            yield data[i : i + 4096]

    assert c.post(f"/runs/{rid2}/finalize", content=chunks(), headers=hdr).status_code == 413
    assert c.get(f"/runs/{rid2}").json()["finalized_at"] is None
    # The cap covers every request body, not only finalize.
    assert c.post("/runs", content=b'{"rooms":["threshold"]' + b" " * MAX_BODY_BYTES + b"}", headers=hdr).status_code == 413


# --------------------------------------------------------------------------- #
# D33 (hosted): open-run cap and retention sweep
# --------------------------------------------------------------------------- #


def test_open_run_cap(env) -> None:
    svc, c = env[0](HAUNTLET_HOSTED="1", HAUNTLET_TRUST_PROXY="1", HAUNTLET_MAX_OPEN_RUNS="50")
    ids = []
    for i in range(50):  # 5 clients x 10, under their per-hour quota
        r = c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip(f"10.0.0.{i // 10}"))
        assert r.status_code == 201, (i, r.text)
        ids.append(r.json()["run"]["run_id"])
    r = c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip("10.0.1.1"))
    assert r.status_code == 429 and "unfinished runs" in r.text
    c.post(f"/runs/{ids[0]}/finalize", json={"observations": []})  # one finishes
    assert c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip("10.0.1.1")).status_code == 201


def test_open_run_cap_counts_expiry(env) -> None:
    svc, c = env[0](HAUNTLET_HOSTED="1", HAUNTLET_TRUST_PROXY="1", HAUNTLET_MAX_OPEN_RUNS="2")
    clock = env[1]
    for i in range(2):
        assert c.post("/runs", json={"rooms": ["threshold"], "ttl_seconds": 60}, headers=_ip(f"10.1.0.{i}")).status_code == 201
    assert c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip("10.1.0.9")).status_code == 429
    clock.now += 61  # both expired: no longer unfinished
    assert c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip("10.1.0.9")).status_code == 201


def test_retention_sweep(env) -> None:
    svc, c = env[0](HAUNTLET_HOSTED="1", HAUNTLET_TRUST_PROXY="1", HAUNTLET_RUN_RETENTION_SECS="3600")
    clock = env[1]
    old = c.post("/runs", json={"rooms": ["threshold"], "grace_window_secs": 0}, headers=_ip("10.2.0.1")).json()
    old_id = old["run"]["run_id"]
    token = next(x["url"] for x in old["canaries"] if x["url"]).rsplit("/c/", 1)[1]
    c.get(f"/c/{token}")
    c.post(f"/runs/{old_id}/finalize", json={"observations": [_obs("x")]})
    assert svc.events(old_id)
    clock.now += 3600 - 1  # just under retention after its window closed
    live = c.post("/runs", json={"rooms": ["threshold"], "ttl_seconds": 86400}, headers=_ip("10.2.0.2")).json()["run"]["run_id"]
    assert svc.store.get_run(old_id) is not None
    clock.now += 61  # over retention, and the once-a-minute sweep may run again
    c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip("10.2.0.3"))
    assert svc.store.get_run(old_id) is None
    assert svc.store.events_for_run(old_id) == [] and svc.store.canaries_for_run(old_id) == []
    assert c.get(f"/runs/{old_id}/report").status_code == 404
    assert c.get(f"/c/{token}").status_code == 404  # its canary is gone too
    assert svc.store.get_run(live) is not None  # an active run is never swept


def test_store_never_deletes_active_or_provisional_runs(tmp_path) -> None:
    store = Store(tmp_path / "s.db")
    clock = Clock()
    svc = RangeService(store, default_rooms(), clock=clock)
    active = svc.start_run(["threshold"], ttl=100).run.run_id
    prov = svc.start_run(["threshold"], ttl=100, grace_window_secs=50).run.run_id
    svc.finalize(prov, [], transcript_provided=False)
    assert store.delete_closed_before(clock.now + 49) == 0  # prov's window closes at now + 50
    assert store.delete_closed_before(clock.now + 51) == 1 and store.get_run(prov) is None
    assert store.get_run(active) is not None
    assert store.delete_closed_before(clock.now + 100 + 30 + 1) == 1  # active expired + default grace


# --------------------------------------------------------------------------- #
# D34: client key and per-client limits
# --------------------------------------------------------------------------- #


def test_client_key_uses_the_last_forwarded_entry() -> None:
    real = {"x-forwarded-for": "203.0.113.9"}
    forged = {"x-forwarded-for": "1.1.1.1, 6.6.6.6, 203.0.113.9"}
    assert client_key(real, "10.0.0.5", True) == client_key(forged, "10.0.0.5", True) == "203.0.113.9"
    assert client_key({"x-forwarded-for": "1.1.1.1"}, "10.0.0.5", False) == "10.0.0.5"  # untrusted: socket
    assert client_key({}, "10.0.0.5", True) == "10.0.0.5"
    assert client_key({"x-forwarded-for": " , "}, None, True) == "unknown"


def test_forged_first_entry_does_not_dodge_the_run_quota(env) -> None:
    _, c = env[0](HAUNTLET_HOSTED="1", HAUNTLET_TRUST_PROXY="1", HAUNTLET_RUNS_PER_HOUR="10")
    for i in range(10):
        assert c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip(f"9.9.9.{i}, 203.0.113.7")).status_code == 201
    r = c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip("8.8.8.8, 203.0.113.7"))
    assert r.status_code == 429 and "this client" in r.text
    assert c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip("203.0.113.8")).status_code == 201


def test_run_quota_resets_after_an_hour(env) -> None:
    _, c = env[0](HAUNTLET_HOSTED="1", HAUNTLET_TRUST_PROXY="1", HAUNTLET_RUNS_PER_HOUR="2", HAUNTLET_MAX_OPEN_RUNS="100")
    clock = env[1]
    for _ in range(2):
        assert c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip("7.7.7.7")).status_code == 201
    assert c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip("7.7.7.7")).status_code == 429
    clock.now += 3601
    assert c.post("/runs", json={"rooms": ["threshold"]}, headers=_ip("7.7.7.7")).status_code == 201


def test_demo_quota_per_client(env) -> None:
    _, c = env[0](HAUNTLET_HOSTED="1", HAUNTLET_TRUST_PROXY="1")
    a, b = _ip("198.51.100.1"), _ip("198.51.100.2")
    for _ in range(3):
        assert c.post("/exorcist/demo", json={"room": "cursed-repo"}, headers=a).status_code == 200
    r = c.post("/exorcist/demo", json={"room": "cursed-repo"}, headers=a)
    assert r.status_code == 429 and "this client" in r.text
    assert c.post("/exorcist/demo", json={"room": "cursed-repo"}, headers=b).status_code == 200  # others unaffected


def test_streams_per_client(env) -> None:
    svc, c = env[0](HAUNTLET_HOSTED="1", HAUNTLET_TRUST_PROXY="1")
    rid = c.post("/runs", json={"rooms": ["threshold"], "grace_window_secs": 0}, headers=_ip("10.3.0.1")).json()["run"]["run_id"]
    c.post(f"/runs/{rid}/finalize", json={"observations": []})
    slots = c.app.state.stream_per_client
    key = "192.0.2.4"
    assert slots.take(key) and slots.take(key)  # this client already holds 2
    r = c.get(f"/runs/{rid}/facts/stream", headers=_ip(key))
    assert r.status_code == 429 and "this client" in r.text
    assert c.get(f"/runs/{rid}/facts/stream", headers=_ip("192.0.2.5")).status_code == 200
    slots.give(key)
    assert c.get(f"/runs/{rid}/facts/stream", headers=_ip(key)).status_code == 200  # 1 + this one = 2
    # The finished stream gave its slot back: the client holds 1, so exactly one more fits.
    assert slots.take(key) and not slots.take(key)


def test_stream_closes_after_max_secs(env, monkeypatch) -> None:
    import time

    monkeypatch.setenv("HAUNTLET_STREAM_POLL_SECS", "0.05")
    svc = RangeService(Store(":memory:"), default_rooms())  # real clock: the run stays active
    monkeypatch.setenv("HAUNTLET_STREAM_MAX_SECS", "0.4")
    c = TestClient(create_app(svc))
    rid = svc.start_run(["threshold"], ttl=86400).run.run_id
    import threading

    out: dict = {}

    def read() -> None:
        t = time.monotonic()
        out["body"] = c.get(f"/runs/{rid}/facts/stream").text
        out["took"] = time.monotonic() - t

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(5)  # a stream without the limit would stay open for the run's 24 h
    assert not reader.is_alive(), "the stream did not close within 5 s"
    assert "event: timeout" in out["body"] and "event: done" not in out["body"]
    assert out["took"] >= 0.35, out["took"]


def test_limiter_memory_is_bounded(monkeypatch) -> None:
    from hauntlet import limits

    monkeypatch.setattr(limits, "MAX_KEYS", 100)
    w = Window(1, 60.0, lambda: 0.0)
    for i in range(1000):
        w.hit(f"k{i}")
    assert len(w._seen) == 100
    s = Slots(1)
    assert all(s.take(f"k{i}") for i in range(100)) and not s.take("one-more")


# --------------------------------------------------------------------------- #
# D35: headers and docs
# --------------------------------------------------------------------------- #

HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "x-robots-tag": "noindex, nofollow",
}


def test_security_headers_on_every_kind_of_response(env) -> None:
    svc, c = env[0]()
    rid = c.post("/runs", json={"rooms": ["threshold"]}).json()["run"]["run_id"]
    for method, path in [("GET", "/exorcist"), ("GET", f"/runs/{rid}/report"), ("GET", "/health"),
                         ("GET", f"/runs/{rid}"), ("GET", "/robots.txt"), ("GET", "/no-such-route"),
                         ("POST", "/runs")]:
        r = c.request(method, path, json={"rooms": ["threshold"]} if method == "POST" else None)
        for k, v in HEADERS.items():
            assert r.headers.get(k) == v, (path, k)
        assert r.headers.get("content-security-policy") == BASE_CSP, path
    too_big = c.post("/runs", content=b" " * (MAX_BODY_BYTES + 1), headers={"Content-Type": "application/json"})
    assert too_big.status_code == 413 and too_big.headers["x-frame-options"] == "DENY"


def test_parlor_page_keeps_its_stricter_csp(env, tmp_path, capsys) -> None:
    from hauntlet import cli
    from hauntlet.paths import scratch_root_beside

    svc = RangeService(Store(tmp_path / "range.db"), default_rooms(), page_scratch_root=scratch_root_beside(tmp_path / "range.db"))
    c = TestClient(create_app(svc))
    run = c.post("/runs", json={"rooms": ["parlor"]}).json()
    assert cli.main(["parlor", "open", f"--run={run['run']['run_id']}"]) == 0
    capsys.readouterr()
    token = next(x["url"] for x in run["canaries"] if x["kind"] == "page").rsplit("/c/", 1)[1]
    r = c.get(f"/c/{token}", params={"page": "lobby"})
    assert r.status_code == 200 and "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_docs_off_only_when_hosted(env) -> None:
    _, local = env[0]()
    assert [local.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")] == [200, 200, 200]
    _, hosted = env[0](HAUNTLET_HOSTED="1")
    assert [hosted.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")] == [404, 404, 404]
    assert hosted.get("/health").status_code == 200


def test_base_url_falls_back_to_render_external_url(env, monkeypatch) -> None:
    from hauntlet.server import _base_url

    assert _base_url() == "http://127.0.0.1:8666"
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://hauntlet.onrender.com/")
    assert _base_url() == "https://hauntlet.onrender.com"
    monkeypatch.setenv("HAUNTLET_BASE_URL", "")  # Blueprint left it empty
    assert _base_url() == "https://hauntlet.onrender.com"
    monkeypatch.setenv("HAUNTLET_BASE_URL", "https://range.example")
    assert _base_url() == "https://range.example"
    c = TestClient(create_app())  # the service built from the environment, as `hauntlet serve` does
    url = next(x["url"] for x in c.post("/runs", json={"rooms": ["threshold"]}).json()["canaries"] if x["url"])
    assert url.startswith("https://range.example/c/")


# --------------------------------------------------------------------------- #
# D34 addition: a configured client-IP header, and the opt-in key log
# --------------------------------------------------------------------------- #


def test_client_ip_header_is_used_only_behind_a_trusted_proxy() -> None:
    h = {"cf-connecting-ip": "198.51.100.20", "x-forwarded-for": "1.1.1.1, 203.0.113.9"}
    assert client_key(h, "10.0.0.5", True, "CF-Connecting-IP") == "198.51.100.20"
    assert client_key(h, "10.0.0.5", True) == "203.0.113.9"  # not configured: last XFF entry
    assert client_key(h, "10.0.0.5", False, "CF-Connecting-IP") == "10.0.0.5"  # untrusted: socket
    missing = {"x-forwarded-for": "1.1.1.1, 203.0.113.9"}
    assert client_key(missing, "10.0.0.5", True, "CF-Connecting-IP") == "203.0.113.9"  # absent: fall back
    assert client_key({"cf-connecting-ip": "  "}, "10.0.0.5", True, "CF-Connecting-IP") == "10.0.0.5"
    assert len(client_key({"cf-connecting-ip": "x" * 500}, None, True, "CF-Connecting-IP")) == 64


def test_client_ip_header_keys_the_quota(env) -> None:
    _, c = env[0](HAUNTLET_HOSTED="1", HAUNTLET_TRUST_PROXY="1", HAUNTLET_CLIENT_IP_HEADER="CF-Connecting-IP",
                  HAUNTLET_RUNS_PER_HOUR="2", HAUNTLET_MAX_OPEN_RUNS="100")
    same = lambda xff: {"CF-Connecting-IP": "198.51.100.30", "X-Forwarded-For": xff}  # noqa: E731
    assert c.post("/runs", json={"rooms": ["threshold"]}, headers=same("10.0.0.1")).status_code == 201
    assert c.post("/runs", json={"rooms": ["threshold"]}, headers=same("10.0.0.2")).status_code == 201
    # A different last XFF entry does not help: the configured header is the key.
    assert c.post("/runs", json={"rooms": ["threshold"]}, headers=same("10.0.0.3")).status_code == 429
    other = {"CF-Connecting-IP": "198.51.100.31", "X-Forwarded-For": "10.0.0.1"}
    assert c.post("/runs", json={"rooms": ["threshold"]}, headers=other).status_code == 201


def test_client_key_log_is_off_by_default(env, caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="hauntlet.client_key")
    _, c = env[0](HAUNTLET_TRUST_PROXY="1")
    c.get("/health", headers={"X-Forwarded-For": "203.0.113.50"})
    assert not [r for r in caplog.records if r.name == "hauntlet.client_key"]


def test_client_key_log_line(env, caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="hauntlet.client_key")
    _, c = env[0](HAUNTLET_TRUST_PROXY="1", HAUNTLET_LOG_CLIENT_KEY="1")
    c.get("/health", headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.50", "CF-Connecting-IP": "198.51.100.77",
                              "True-Client-IP": "198.51.100.78"})
    c.get("/robots.txt")
    lines = [r.getMessage() for r in caplog.records if r.name == "hauntlet.client_key"]
    assert len(lines) == 2  # one per request
    first, second = lines
    assert first == "key=203.0.113.50 xff_entries=2 cf_connecting_ip=present true_client_ip=present GET /health"
    assert "198.51.100.77" not in first and "198.51.100.78" not in first and "6.6.6.6" not in first
    assert second == "key=testclient xff_entries=0 cf_connecting_ip=absent true_client_ip=absent GET /robots.txt"


def test_client_key_log_shows_the_configured_header_value_only_as_the_key(env, caplog) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="hauntlet.client_key")
    _, c = env[0](HAUNTLET_TRUST_PROXY="1", HAUNTLET_LOG_CLIENT_KEY="1", HAUNTLET_CLIENT_IP_HEADER="CF-Connecting-IP")
    c.get("/health", headers={"X-Forwarded-For": "203.0.113.50", "CF-Connecting-IP": "198.51.100.77",
                              "True-Client-IP": "198.51.100.78"})
    (line,) = [r.getMessage() for r in caplog.records if r.name == "hauntlet.client_key"]
    assert line.startswith("key=198.51.100.77 xff_entries=1 cf_connecting_ip=present true_client_ip=present")
    assert "198.51.100.78" not in line and "203.0.113.50" not in line
