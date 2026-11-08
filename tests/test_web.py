"""Assert the authenticated Step 6 APIs and durable human decisions."""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["OPENAI_MODEL"] = "gpt-6.1-terra"
os.environ["TEAM_PASSCODE"] = "test-team"
os.environ["ADMIN_PASSCODE"] = "test-admin"
os.environ["RENDER_GIT_COMMIT"] = "0123456789abcdef"
os.environ["SPONSOR_REPORT_TOKEN"] = "test-sponsor-link"
os.environ["UPSTASH_REDIS_REST_URL"] = ""
os.environ["UPSTASH_REDIS_REST_TOKEN"] = ""

import app.main as web


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    web.DB_PATH = root / "web.db"
    web.LOCAL_LOG_PATH = root / "changes.json"
    web.LIVE_PHOTO_DIR = root / "live_photos"

    with TestClient(web.app) as client:
        assert client.get("/api/bootstrap").status_code == 401
        assert client.get("/api/sponsor-link").status_code == 401
        signin_page = client.get("/signin")
        assert signin_page.status_code == 200
        assert "__DEPLOY_REVISION__" not in signin_page.text
        assert signin_page.text.count("?v=0123456789ab") == 4
        assert 'id="locale-select"' in signin_page.text
        assert client.get("/report/not-the-token").status_code == 404
        sponsor_report = client.get("/report/test-sponsor-link")
        assert sponsor_report.status_code == 200
        assert sponsor_report.headers["cache-control"] == "private, no-store"
        assert sponsor_report.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
        assert "__SPONSOR_DATA__" not in sponsor_report.text
        assert "__DEPLOY_REVISION__" not in sponsor_report.text
        assert sponsor_report.text.count("?v=0123456789ab") == 4
        assert "<img" not in sponsor_report.text
        assert "/api/" not in sponsor_report.text
        assert "305-555" not in sponsor_report.text
        assert 'id="locale-select"' in sponsor_report.text
        for private_value in ("Marta", "Beatriz", "Mango", "Laundromat", "25.", "-80."):
            assert private_value not in sponsor_report.text

        signed_in = client.post(
            "/signin", data={"passcode": "test-team"}, follow_redirects=False
        )
        assert signed_in.status_code == 303
        cookies = signed_in.cookies
        assert client.get("/api/sponsor-link", cookies=cookies).status_code == 405
        assert client.post(
            "/api/sponsor-link",
            cookies=cookies,
            json={"admin_passcode": "wrong"},
        ).status_code == 403
        assert client.post(
            "/api/sponsor-link",
            cookies=cookies,
            json={"admin_passcode": "test-admin"},
        ).json() == {
            "path": "/report/test-sponsor-link"
        }

        bootstrap = client.get("/api/bootstrap", cookies=cookies).json()
        assert len(bootstrap["colonies"]) == 18
        assert bootstrap["alerts"] and bootstrap["suggestions"]
        assert len(bootstrap["volunteers"]) == 8
        clinic_cats = web.app.state.db.connection.execute(
            """
            SELECT reported_name, tnr_status FROM cats
            WHERE reported_name IN ('Pebble', 'Cinder', 'Sombra', 'Misty', 'Chispa')
              AND merged_into_cat_id IS NULL
            ORDER BY reported_name
            """
        ).fetchall()
        assert len(clinic_cats) == 5
        assert all(row["tnr_status"] == "fixed" for row in clinic_cats)
        assert web.app.state.db.sponsor_counts()["fixed"] == 6
        assert web.app.state.db.connection.execute(
            "SELECT COUNT(*) FROM reports"
        ).fetchone()[0] == 89
        newest_report = web.app.state.db.connection.execute(
            "SELECT MAX(sent_at) FROM reports"
        ).fetchone()[0]
        assert datetime.fromisoformat(newest_report).date() == datetime.now(
            ZoneInfo("America/New_York")
        ).date()

        severity = {"urgent": 0, "high": 1, "normal": 2, None: 3}
        colony_order = [
            (severity[item["alert_severity"]], -item["cats"], item["name"])
            for item in bootstrap["colonies"]
        ]
        assert colony_order == sorted(colony_order)
        same_cat_strengths = [
            item["strength"]
            for item in bootstrap["suggestions"]
            if item["kind"] == "same_cat"
        ]
        assert same_cat_strengths == sorted(
            same_cat_strengths, key=lambda strength: 0 if strength == "strong" else 1
        )
        assert all(
            item["photo_id"] is None
            for item in bootstrap["alerts"]
            if item["kind"] == "kittens"
        )
        assert all(
            "needs a vet: Mosaic needs a vet" not in item["text"]
            for item in bootstrap["alerts"]
        )

        detailed = next(item for item in bootstrap["colonies"] if item["cats"])
        colony = client.get(f"/api/colonies/{detailed['id']}", cookies=cookies).json()
        assert {"cats", "fixed", "needs_tnr", "needs_vet", "feeding_log", "feeders", "cats_list"} <= colony.keys()
        cat = client.get(f"/api/cats/{colony['cats_list'][0]['id']}", cookies=cookies).json()
        assert cat["photos"] and "history" in cat and "description" in cat
        assert client.get(f"/api/photos/{cat['photos'][0]['id']}", cookies=cookies).status_code == 200

        fed_at = "2026-11-07T15:30:00+00:00"
        fed = client.post(
            "/api/reports/fed",
            cookies=cookies,
            json={
                "colony_id": "westchester-market",
                "volunteer_id": "beatriz-cruz",
                "at": fed_at,
            },
        )
        assert fed.status_code == 200

        suggestion = next(item for item in bootstrap["suggestions"] if item["kind"] == "same_cat")
        decision = client.post(
            f"/api/suggestions/{suggestion['id']}/decision",
            cookies=cookies,
            json={"volunteer_id": "beatriz-cruz", "action": "different"},
        )
        assert decision.status_code == 200

        alert = bootstrap["alerts"][0]
        done = client.post(
            f"/api/alerts/{alert['id']}/done",
            cookies=cookies,
            json={"volunteer_id": "beatriz-cruz"},
        )
        assert done.status_code == 200

        changes = json.loads(web.LOCAL_LOG_PATH.read_text())
        assert [item["type"] for item in changes] == [
            "feeding_report",
            "suggestion_decision",
            "alert_resolution",
        ]

        web._load_state(web.app)
        rebuilt = client.get("/api/colonies/westchester-market", cookies=cookies).json()
        assert rebuilt["last_fed_at"] == fed_at
        remaining = client.get("/api/suggestions", cookies=cookies).json()
        assert all(item["id"] != suggestion["id"] for item in remaining)
        alerts = client.get("/api/alerts", cookies=cookies).json()
        assert all(item["id"] != alert["id"] for item in alerts)

        index = client.get("/", cookies=cookies)
        assert index.status_code == 200
        assert "__DEPLOY_REVISION__" not in index.text
        assert index.text.count("?v=0123456789ab") == 7
        assert "/static/favicon.svg?v=0123456789ab" in index.text
        assert 'id="locale-select"' in index.text
        assert client.get("/static/ui_text.js").status_code == 200
        assert "¿Es el mismo gato?" in client.get("/static/ui_text.js").text

        confirm_js = client.get("/static/confirm.js").text
        assert "T.featureMatches" not in confirm_js

print("authenticated UI API and replay checks passed")
