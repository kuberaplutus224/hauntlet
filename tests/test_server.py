"""HTTP surface (Requirements 5.4, 6.3)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from hauntlet.server import create_app


def _client(service) -> TestClient:
    return TestClient(create_app(service))


def test_health_and_noindex(service) -> None:
    res = _client(service).get("/health")
    assert res.status_code == 200 and res.json()["status"] == "ok"
    assert res.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_full_http_flow(service) -> None:
    c = _client(service)
    started = c.post("/runs", json={"rooms": ["threshold"]})
    assert started.status_code == 201
    body = started.json()
    run_id = body["run"]["run_id"]
    url = next(x for x in body["canaries"] if x["kind"] == "url" and not x["is_control"])["url"]
    secret = next(x for x in body["canaries"] if x["kind"] == "secret")["value"]

    hit = c.get(url.replace(service.base_url, ""), params={"key": secret})
    assert hit.status_code == 200 and hit.headers["X-Robots-Tag"] == "noindex, nofollow"

    fin = c.post(
        f"/runs/{run_id}/finalize",
        json={
            "transcript_provided": True,
            "observations": [
                {"room": "threshold", "trap_id": "__task__", "channel": "filesystem", "signal": "task_done"}
            ],
        },
    )
    assert fin.status_code == 200
    assert fin.json()["overall_worst"] == 4
    assert c.get(f"/runs/{run_id}/score").json()["rooms"][0]["task_completed"] is True
    report = c.get(f"/runs/{run_id}/report")
    assert report.status_code == 200 and "Exposed" in report.text


def test_run_response_has_window_close_not_status(service) -> None:
    """POST /runs and GET /runs/{id} expose finalized_at and window_close; no legacy status field."""
    c = _client(service)
    body = c.post("/runs", json={"rooms": ["threshold"]}).json()
    run = body["run"]

    # Must include the computed window_close timestamp
    assert "window_close" in run, "window_close missing from POST /runs response"
    assert isinstance(run["window_close"], float)

    # Must include finalized_at (nullable), not a legacy status string
    assert "finalized_at" in run
    assert run["finalized_at"] is None  # not yet finalized
    assert "status" not in run, "legacy status field must not appear in run response"

    # window_close = expires_at + grace_window_secs (not finalized yet)
    assert run["window_close"] == run["expires_at"] + run["grace_window_secs"]

    # GET /runs/{id} must return the same shape
    run_id = run["run_id"]
    fetched = c.get(f"/runs/{run_id}").json()
    assert "window_close" in fetched
    assert "finalized_at" in fetched
    assert "status" not in fetched


def test_errors(service) -> None:
    c = _client(service)
    assert c.get("/c/not-a-token").status_code == 404
    assert c.get("/runs/nope/score").status_code == 404
    assert c.post("/runs", json={"rooms": ["attic"]}).status_code == 400
    run_id = c.post("/runs", json={}).json()["run"]["run_id"]
    bad = c.post(
        f"/runs/{run_id}/finalize",
        json={"observations": [{"room": "threshold", "trap_id": "x", "channel": "network", "signal": "exposed"}]},
    )
    assert bad.status_code == 400


def test_grace_window_secs_accepted_and_reflected(service) -> None:
    """grace_window_secs is accepted and reflected in the window_close timestamp."""
    c = _client(service)
    body = c.post("/runs", json={"rooms": ["threshold"], "grace_window_secs": 60}).json()
    run = body["run"]
    assert run["grace_window_secs"] == 60.0
    assert run["window_close"] == run["expires_at"] + 60.0


def test_grace_window_secs_out_of_range_returns_422(service) -> None:
    """grace_window_secs outside [0, 300] returns HTTP 422."""
    c = _client(service)
    assert c.post("/runs", json={"rooms": ["threshold"], "grace_window_secs": -1}).status_code == 422
    assert c.post("/runs", json={"rooms": ["threshold"], "grace_window_secs": 301}).status_code == 422


def test_finalize_rejections_return_409(service, clock) -> None:
    """Already-finalized and closed-run finalize attempts return HTTP 409, not 400."""
    c = _client(service)

    # Finalizing twice: the second attempt is rejected as already finalized.
    run_id = c.post("/runs", json={"rooms": ["threshold"]}).json()["run"]["run_id"]
    assert c.post(f"/runs/{run_id}/finalize", json={}).status_code == 200
    second = c.post(f"/runs/{run_id}/finalize", json={})
    assert second.status_code == 409
    assert "already finalized" in second.json()["detail"]

    # Finalizing after the window closes (TTL 10s + zero grace) is rejected as run closed.
    closed_id = c.post(
        "/runs", json={"rooms": ["threshold"], "ttl_seconds": 10, "grace_window_secs": 0}
    ).json()["run"]["run_id"]
    clock.advance(11)
    closed = c.post(f"/runs/{closed_id}/finalize", json={})
    assert closed.status_code == 409
    assert "run closed" in closed.json()["detail"]
