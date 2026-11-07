"""Deployable FastAPI shell for Cat Colony Watch."""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.change_log import ChangeLog
from app.database import Database
from app.import_demo import import_demo


DATA_DIR = Path("data/demo")
DB_PATH = Path(os.getenv("CCW_DB_PATH", "/tmp/cat_colony_watch.db"))
LOCAL_LOG_PATH = Path(os.getenv("CCW_LOCAL_CHANGE_LOG", "data/local_changes.json"))
COOKIE_NAME = "ccw_session"


class FeedingReport(BaseModel):
    colony_id: str
    volunteer_id: str
    at: str | None = None


def _session_token() -> str:
    passcode = os.getenv("TEAM_PASSCODE", "")
    if not passcode:
        raise RuntimeError("TEAM_PASSCODE is required")
    return hmac.new(passcode.encode(), b"cat-colony-watch-session", hashlib.sha256).hexdigest()


def _build_database() -> Database:
    db, _ = import_demo(DATA_DIR, DB_PATH, allow_api=False)
    return db


def _apply_change(db: Database, change: dict) -> int | None:
    if change.get("type") != "feeding_report":
        raise ValueError(f"unsupported change type: {change.get('type')}")
    payload = change["data"]
    volunteer = db.connection.execute(
        "SELECT name FROM volunteers WHERE id = ?", (payload["volunteer_id"],)
    ).fetchone()
    if volunteer is None:
        raise ValueError(f"unknown volunteer: {payload['volunteer_id']}")
    db._require_colony(payload["colony_id"])
    report_id = db.add_report(
        {
            "sent_at": payload["at"],
            "sender": volunteer["name"],
            "kind": "fed",
            "text": f"Fed {payload['colony_id']}",
            "lat": None,
            "lng": None,
            "source": "app",
            "raw": f"live:{change['id']}",
        }
    )
    db.log_feeding(
        payload["colony_id"], payload["volunteer_id"], payload["at"], report_id
    )
    return report_id


def _load_state(app: FastAPI) -> None:
    previous = getattr(app.state, "db", None)
    if previous is not None:
        previous.close()
    app.state.db = _build_database()
    app.state.change_log = ChangeLog(local_path=LOCAL_LOG_PATH)
    changes = app.state.change_log.load()
    for change in changes:
        _apply_change(app.state.db, change)
    app.state.change_count = len(changes)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    for key in ("OPENAI_MODEL", "TEAM_PASSCODE", "ADMIN_PASSCODE"):
        if not os.getenv(key):
            raise RuntimeError(f"{key} is required")
    _load_state(app)
    yield
    app.state.db.close()


app = FastAPI(title="Cat Colony Watch", lifespan=lifespan)


@app.middleware("http")
async def require_team_passcode(request: Request, call_next):
    path = request.url.path
    if path == "/healthz" or path.startswith("/signin") or path.startswith("/report/"):
        return await call_next(request)
    if hmac.compare_digest(request.cookies.get(COOKIE_NAME, ""), _session_token()):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "team sign-in required"}, status_code=401)
    return RedirectResponse("/signin", status_code=303)


@app.get("/healthz")
def healthz(request: Request):
    return {
        "ok": True,
        "ready": hasattr(request.app.state, "db"),
        "storage": getattr(getattr(request.app.state, "change_log", None), "mode", None),
    }


@app.get("/signin", response_class=HTMLResponse)
def signin_page():
    return """<!doctype html><html><meta name="viewport" content="width=device-width">
    <title>Sign in · Cat Colony Watch</title><body><main><h1>Cat Colony Watch</h1>
    <form method="post"><label>Team passcode <input type="password" name="passcode"
    autocomplete="current-password" required></label><button>Sign in</button></form></main></body></html>"""


@app.post("/signin")
async def signin(request: Request):
    values = parse_qs((await request.body()).decode())
    supplied = values.get("passcode", [""])[0]
    if not hmac.compare_digest(supplied, os.getenv("TEAM_PASSCODE", "")):
        return HTMLResponse("Incorrect passcode", status_code=401)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        _session_token(),
        max_age=60 * 60 * 24 * 180,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    counts = request.app.state.db.colony_counts()
    alerts = request.app.state.db.open_alerts()
    rows = "".join(
        f"<li><b>{html.escape(item['name'])}</b>: {item['cats']} cats · "
        f"{item['fixed']} fixed · {item['needs_tnr']} need TNR</li>"
        for item in counts
        if item["cats"]
    )
    alert_rows = "".join(
        f"<li><b>{html.escape(item['severity'])}</b> {html.escape(item['text'])}</li>"
        for item in alerts
    )
    return f"""<!doctype html><html><meta name="viewport" content="width=device-width">
    <title>Cat Colony Watch</title><body><main><h1>Cat Colony Watch</h1>
    <p>Step 5 deployment shell. The phone-first interface comes next.</p>
    <h2>Open alerts</h2><ul>{alert_rows}</ul><h2>Colonies</h2><ul>{rows}</ul>
    </main></body></html>"""


@app.get("/api/colonies")
def colonies(request: Request):
    return request.app.state.db.colony_counts()


@app.get("/api/alerts")
def alerts(request: Request):
    return request.app.state.db.open_alerts()


@app.get("/api/suggestions")
def suggestions(request: Request):
    return request.app.state.db.open_suggestions()


@app.get("/api/storage")
def storage(request: Request):
    return {
        "mode": request.app.state.change_log.mode,
        "changes": request.app.state.change_count,
    }


@app.post("/api/reports/fed")
def add_feeding(report: FeedingReport, request: Request):
    at = report.at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    change = {
        "id": str(uuid.uuid4()),
        "type": "feeding_report",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "colony_id": report.colony_id,
            "volunteer_id": report.volunteer_id,
            "at": at,
        },
    }
    try:
        # Validate against the current database before persisting the event.
        request.app.state.db._require_colony(report.colony_id)
        request.app.state.db._require_volunteer(report.volunteer_id)
        request.app.state.change_log.append(change)
        report_id = _apply_change(request.app.state.db, change)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    request.app.state.change_count += 1
    return {"ok": True, "report_id": report_id, "change_id": change["id"], "at": at}


@app.post("/api/admin/reset")
def reset_demo(request: Request, x_admin_passcode: str | None = Header(default=None)):
    if not hmac.compare_digest(x_admin_passcode or "", os.getenv("ADMIN_PASSCODE", "")):
        raise HTTPException(status_code=403, detail="admin passcode required")
    request.app.state.change_log.clear()
    _load_state(request.app)
    return {"ok": True, "changes": 0}
