"""The scorecard on the existing routes and writers (scorecard D23, task 17.3).

- ``/runs/{id}/report``: the scorecard with badge C4; an active run's page links
  the live stream; 404 for unknown and hostile IDs;
- ``/exorcisms/{id}/report``: the exorcism's scorecard, with the demo badge and
  path label, the download link and no bundle path; 404 for unknown IDs;
- ``/exorcist``: the launcher; the demo round trip lands on a scorecard;
- every response carries ``X-Robots-Tag`` and the robots meta;
- the delta HTML files and the CLI's HTML reports are scorecard pages, with the
  path set by the command.

**Validates: scorecard Requirements 2.3, 13.1–13.4, D23**
"""

from __future__ import annotations

import json
import re
from html import unescape

import pytest
from _scorecard_html import parse
from fastapi.testclient import TestClient

from hauntlet.agents import get_agent
from hauntlet.cli import main
from hauntlet.core.runner import run_once
from hauntlet.core.service import RangeService
from hauntlet.core.store import Store
from hauntlet.exorcist.texts import DEMO_LABEL, REAL_CLIENT_LABEL
from hauntlet.rooms import default_rooms
from hauntlet.scorecard import copy
from hauntlet.server import create_app

ROBOTS = '<meta name="robots" content="noindex, nofollow">'


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "range" / "range.db"
    monkeypatch.setenv("HAUNTLET_DB", str(db))
    svc = RangeService(Store(db), default_rooms())
    return svc, TestClient(create_app(svc)), db


def _ok(r) -> str:
    assert r.status_code == 200, r.text[:200]
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert ROBOTS in r.text
    return r.text


def _badge(html: str) -> str:
    return re.search(r'<p class="badge" role="note">([^<]*)</p>', html).group(1).replace("&#x27;", "'")


def test_run_report_is_the_scorecard(env, tmp_path) -> None:
    svc, c, _ = env
    r = run_once(svc, "threshold", get_agent("naive"), tmp_path / "s")
    html = _ok(c.get(f"/runs/{r.score.run_id}/report"))
    assert _badge(html) == copy.C4
    assert "L4 Exposed" in html and f"<code>{r.score.run_id}</code>" in html
    data = json.loads(parse(html).scripts["sc-data"])
    assert data["streamUrl"] is None
    assert copy.C22 in html and copy.C23 not in html
    secrets = [x.value for x in svc.canaries(r.score.run_id) if x.kind == "secret"]
    assert all(s not in html for s in secrets)


def test_active_run_links_the_live_stream(env) -> None:
    svc, c, _ = env
    run_id = svc.start_run(["poltergeist"]).run.run_id
    html = _ok(c.get(f"/runs/{run_id}/report"))
    data = json.loads(parse(html).scripts["sc-data"])
    assert data["streamUrl"] == f"/runs/{run_id}/facts/stream"
    assert copy.C23 in html and copy.C19 in html


@pytest.mark.parametrize("bad", ["no-such-run-0001", "short", "a" * 65])
def test_run_report_404(env, bad) -> None:
    _, c, _ = env
    r = c.get(f"/runs/{bad}/report")
    assert r.status_code == 404 and r.headers["x-robots-tag"] == "noindex, nofollow"


def test_launcher_and_demo_round_trip(env) -> None:
    _, c, db = env
    html = _ok(c.get("/exorcist"))
    assert _badge(html) == copy.C1
    assert 'data-room="cursed-repo"' in html and 'data-room="poltergeist"' in html
    body = c.post("/exorcist/demo", json={"room": "poltergeist"}).json()
    page = _ok(c.get(body["report_url"]))
    assert _badge(page) == copy.C1 and DEMO_LABEL in unescape(page) and REAL_CLIENT_LABEL not in unescape(page)
    assert f'href="{body["bundle_url"]}"' in page
    assert str(db.parent) not in page, "a served page never shows the bundle path"
    assert "fact log not available" not in page  # D26 evidence is read
    assert c.get("/exorcisms/deadbeefdead99/report").status_code == 404


def test_written_delta_html_is_the_scorecard(env) -> None:
    _, c, db = env
    body = c.post("/exorcist/demo", json={"room": "cursed-repo"}).json()
    bundle_dir = next(db.parent.glob(f"**/{body['bundle_id']}"))
    (html_file,) = (bundle_dir / "deltas").glob("*.html")
    html = html_file.read_text(encoding="utf-8")
    assert _badge(html) == copy.C1 and DEMO_LABEL in unescape(html) and ROBOTS in html


def test_cli_reports_are_scorecards_with_the_commands_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HAUNTLET_DB", str(tmp_path / "db" / "range.db"))
    out = tmp_path / "reports"
    assert main(["run", "--room", "threshold", "--agent", "hardened", "--out", str(out)]) == 0
    (page,) = out.glob("autopsy-threshold-hardened-*.html")
    assert _badge(page.read_text()) == copy.C3.format(name="hardened")
    assert main(["run", "--room", "threshold", "--agent", "naive", "--repeat", "2", "--out", str(out)]) == 0
    (page,) = out.glob("autopsy-threshold-naive-*.html")
    assert copy.SECTION_AGGREGATES in page.read_text()
    assert main(["exorcist", "demo", "--room", "cursed-repo", "--out", str(out)]) == 0
    (page,) = out.glob("exorcist-delta-*.html")
    assert _badge(page.read_text()) == copy.C1
