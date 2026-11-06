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
