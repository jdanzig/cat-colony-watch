"""Assert the authenticated Step 6 APIs and durable human decisions."""

import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["OPENAI_MODEL"] = "gpt-6.1-terra"
os.environ["TEAM_PASSCODE"] = "test-team"
os.environ["ADMIN_PASSCODE"] = "test-admin"
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
        signed_in = client.post(
            "/signin", data={"passcode": "test-team"}, follow_redirects=False
        )
        assert signed_in.status_code == 303
        cookies = signed_in.cookies

        bootstrap = client.get("/api/bootstrap", cookies=cookies).json()
        assert len(bootstrap["colonies"]) == 18
        assert bootstrap["alerts"] and bootstrap["suggestions"]
        assert len(bootstrap["volunteers"]) == 8

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

        assert client.get("/", cookies=cookies).status_code == 200
        assert client.get("/static/ui_text.js").status_code == 200

print("authenticated UI API and replay checks passed")
