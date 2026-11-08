"""FastAPI web app and replayable live-report API for Cat Colony Watch."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from app.ai_cache import AICache
from app.change_log import ChangeLog
from app.database import Database
from app.identification import describe_photo
from app.import_demo import import_demo
from app.message_agent import (
    AgentSummary,
    ImportContext,
    build_agent,
    match_report_photo,
    replay_mutations,
)
from app.rules import NEEDS_VET_WORDS, PREGNANCY_WORDS, apply_named_cat_facts, rebuild_alerts


DATA_DIR = Path("data/demo")
STATIC_DIR = Path(__file__).parent / "static"
SIGNIN_TEMPLATE = STATIC_DIR / "signin.html"
SPONSOR_TEMPLATE = Path(__file__).parent / "sponsor.html"
DB_PATH = Path(os.getenv("CCW_DB_PATH", "/tmp/cat_colony_watch.db"))
LOCAL_LOG_PATH = Path(os.getenv("CCW_LOCAL_CHANGE_LOG", "data/local_changes.json"))
LIVE_PHOTO_DIR = Path(os.getenv("CCW_LIVE_PHOTO_DIR", "/tmp/ccw_live_photos"))
RUNTIME_CACHE_PATH = Path(
    os.getenv("CCW_AI_CACHE_PATH", "/tmp/cat_colony_watch_ai_cache.json")
)
COOKIE_NAME = "ccw_session"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_PHOTO_BODY_BYTES = 17 * 1024 * 1024
RATE_WINDOW_SECONDS = 10 * 60
PHOTO_RATE_LIMIT = 5
SIGNIN_FAILURE_LIMIT = 10
MIAMI_TIME = ZoneInfo("America/New_York")
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def _deploy_revision() -> str:
    return os.getenv("RENDER_GIT_COMMIT", "local")[:12] or "local"


def _log_event(event: str, **fields: object) -> None:
    """Write one privacy-safe operational event to the platform log."""
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True), file=sys.stdout, flush=True)


def _client_key(request: Request) -> str:
    if os.getenv("RENDER"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


def _safe_log_path(path: str) -> str:
    return "/report/[redacted]" if path.startswith("/report/") else path


def _rate_limited(app: FastAPI, bucket: str, key: str, limit: int) -> bool:
    now = time.monotonic()
    cutoff = now - RATE_WINDOW_SECONDS
    with app.state.rate_lock:
        window = app.state.rate_windows.setdefault((bucket, key), [])
        window[:] = [seen for seen in window if seen > cutoff]
        if len(window) >= limit:
            return True
        window.append(now)
        return False


def _clear_rate_limit(app: FastAPI, bucket: str, key: str) -> None:
    with app.state.rate_lock:
        app.state.rate_windows.pop((bucket, key), None)


def _index_html() -> str:
    return (STATIC_DIR / "index.html").read_text().replace(
        "__DEPLOY_REVISION__", _deploy_revision()
    )


def _signin_html(*, rate_limited: bool = False) -> str:
    html = SIGNIN_TEMPLATE.read_text().replace(
        "__DEPLOY_REVISION__", _deploy_revision()
    )
    if rate_limited:
        html = html.replace(
            '<body class="signin-page">',
            '<body class="signin-page" data-rate-limited="true">',
        )
    return html


def _sponsor_report_token() -> str:
    configured = os.getenv("SPONSOR_REPORT_TOKEN", "").strip()
    if configured:
        return configured
    return hmac.new(
        os.environ["ADMIN_PASSCODE"].encode(),
        b"cat-colony-watch-sponsor-report",
        hashlib.sha256,
    ).hexdigest()[:32]


def _sponsor_html(db: Database) -> str:
    return (
        SPONSOR_TEMPLATE.read_text()
        .replace("__DEPLOY_REVISION__", _deploy_revision())
        .replace("__SPONSOR_DATA__", json.dumps(db.sponsor_counts(), separators=(",", ":")))
    )


class FeedingReport(BaseModel):
    colony_id: str
    volunteer_id: str
    at: str | None = None
    client_request_id: str | None = Field(
        default=None, min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._-]+$"
    )


class SuggestionDecision(BaseModel):
    volunteer_id: str
    action: Literal["same", "different", "new_cat", "confirm", "reject"]


class AlertDecision(BaseModel):
    volunteer_id: str


class AdminPasscode(BaseModel):
    admin_passcode: str = Field(min_length=1, max_length=200)


class LiveReport(BaseModel):
    kind: Literal["sighting", "urgent"]
    colony_id: str
    volunteer_id: str
    note: str = Field(default="", max_length=2000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    photo_data_url: str
    client_request_id: str | None = Field(
        default=None, min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._-]+$"
    )


def _session_token() -> str:
    passcode = os.getenv("TEAM_PASSCODE", "")
    if not passcode:
        raise RuntimeError("TEAM_PASSCODE is required")
    return hmac.new(passcode.encode(), b"cat-colony-watch-session", hashlib.sha256).hexdigest()


def _build_database() -> tuple[Database, AICache]:
    RUNTIME_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DATA_DIR / "ai_cache.json", RUNTIME_CACHE_PATH)
    db, cache = import_demo(
        DATA_DIR,
        DB_PATH,
        cache_path=RUNTIME_CACHE_PATH,
        allow_api=False,
        verbose=False,
    )
    # Live reports retain cost accounting, but are not blocked by the demo-import
    # budget. Import and evaluation commands still use their explicit safeguards.
    cache.max_spend_usd = None
    return db, cache


def _api_spend_today(changes: list[dict], now: datetime | None = None) -> float:
    today = (now or datetime.now(timezone.utc)).astimezone(MIAMI_TIME).date()
    total = 0.0
    for change in changes:
        if change.get("type") != "live_report":
            continue
        try:
            created = datetime.fromisoformat(change["created_at"]).astimezone(MIAMI_TIME)
        except (KeyError, TypeError, ValueError):
            continue
        if created.date() == today:
            total += float(change.get("data", {}).get("api_cost_usd", 0.0) or 0.0)
    return round(total, 8)


def _api_day(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(MIAMI_TIME).date().isoformat()


def _volunteer_name(db: Database, volunteer_id: str) -> str:
    row = db.connection.execute(
        "SELECT name FROM volunteers WHERE id = ?", (volunteer_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown volunteer: {volunteer_id}")
    return str(row["name"])


def _restore_live_photo(change_log: ChangeLog, digest: str) -> Path:
    path = LIVE_PHOTO_DIR / f"{digest}.jpg"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(change_log.load_photo(digest))
    return path


def _apply_change(
    db: Database,
    cache: AICache,
    change_log: ChangeLog,
    change: dict,
) -> dict:
    """Apply one durable live change while rebuilding SQLite."""
    kind = change.get("type")
    payload = change["data"]
    if kind == "feeding_report":
        volunteer_name = _volunteer_name(db, payload["volunteer_id"])
        db._require_colony(payload["colony_id"])
        report_id = db.add_report(
            {
                "sent_at": payload["at"],
                "sender": volunteer_name,
                "kind": "fed",
                "text": f"Fed {payload['colony_id']}",
                "lat": payload.get("lat"),
                "lng": payload.get("lng"),
                "source": "app",
                "raw": f"live:{change['id']}",
            }
        )
        db.log_feeding(payload["colony_id"], payload["volunteer_id"], payload["at"], report_id)
        rebuild_alerts(db, payload["at"])
        return {"report_id": report_id}

    if kind == "suggestion_decision":
        suggestion = db.connection.execute(
            "SELECT * FROM suggestions WHERE id = ?", (payload["suggestion_id"],)
        ).fetchone()
        if suggestion is None:
            raise ValueError(f"unknown suggestion: {payload['suggestion_id']}")
        valid_actions = {
            "same_cat": {"same", "different", "new_cat"},
            "possible_duplicate": {"confirm", "reject"},
            "status_change": {"confirm", "reject"},
        }
        if payload["action"] not in valid_actions[suggestion["kind"]]:
            raise ValueError(
                f"action {payload['action']} is not valid for {suggestion['kind']}"
            )
        decision = "confirmed" if payload["action"] in {"same", "confirm"} else "rejected"
        db.confirm_suggestion(
            payload["suggestion_id"],
            payload["volunteer_id"],
            decision,
            decided_at=payload["at"],
        )
        cat_id = None
        if payload["action"] == "new_cat":
            if suggestion["kind"] != "same_cat":
                raise ValueError("new cat is only valid for a photo match")
            candidate = db.connection.execute(
                "SELECT colony_id FROM cats WHERE id = ?", (suggestion["candidate_cat_id"],)
            ).fetchone()
            result = db.create_cat_for_photo(int(suggestion["photo_id"]), candidate["colony_id"])
            cat_id = result.get("cat_id")
        rebuild_alerts(db, payload["at"])
        return {"suggestion_id": payload["suggestion_id"], "cat_id": cat_id}

    if kind == "alert_resolution":
        db._require_volunteer(payload["volunteer_id"])
        db.resolve_alert(payload["alert_id"], payload["at"])
        return {"alert_id": payload["alert_id"]}

    if kind == "live_report":
        for section, entries in payload.get("cache_entries", {}).items():
            cache.data.setdefault(section, {}).update(entries)
        photo_path = _restore_live_photo(change_log, payload["photo_hash"])
        volunteer_name = _volunteer_name(db, payload["volunteer_id"])
        report_id = db.add_report(
            {
                "sent_at": payload["at"],
                "sender": volunteer_name,
                "kind": payload["kind"],
                "text": payload["text"],
                "lat": payload.get("lat"),
                "lng": payload.get("lng"),
                "source": "app",
                "raw": f"live:{change['id']}",
            }
        )
        photo_ids = []
        for cat_index, description in enumerate(payload["descriptions"]):
            photo_ids.append(db.add_photo(report_id, photo_path, cat_index, description))
        old_ids = payload.get("original_photo_ids", photo_ids)
        id_map = dict(zip(old_ids, photo_ids, strict=True))
        mutations = deepcopy(payload["mutations"])
        for mutation in mutations:
            if mutation["tool"] == "match_photo":
                mutation["args"]["photo_id"] = id_map[mutation["args"]["photo_id"]]
        context = ImportContext(
            db=db,
            cache=cache,
            model=cache.model,
            report_id=report_id,
            volunteer_id=payload["volunteer_id"],
            sent_at=payload["at"],
            photo_ids=set(photo_ids),
            allow_api=False,
        )
        replay_mutations(context, mutations)
        apply_named_cat_facts(db, report_id)
        db.create_possible_duplicate_suggestions()
        rebuild_alerts(db, payload["at"])
        return {"report_id": report_id, "summary": payload["summary"]}

    raise ValueError(f"unsupported change type: {kind}")


def _load_state(app: FastAPI) -> None:
    previous = getattr(app.state, "db", None)
    if previous is not None:
        previous.close()
    db, cache = _build_database()
    change_log = ChangeLog(local_path=LOCAL_LOG_PATH)
    changes = change_log.load()
    for change in changes:
        _apply_change(db, cache, change_log, change)
    app.state.db = db
    app.state.cache = cache
    app.state.agent = build_agent(cache.model)
    app.state.change_log = change_log
    app.state.change_count = len(changes)
    app.state.changes_by_id = {
        change["id"]: change for change in changes if change.get("id")
    }
    derived_spend = _api_spend_today(changes)
    recorded_spend = change_log.api_spend(_api_day())
    if derived_spend > recorded_spend:
        recorded_spend = change_log.add_api_spend(
            _api_day(), derived_spend - recorded_spend
        )
    app.state.api_spend_today_usd = round(max(derived_spend, recorded_spend), 8)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    for key in ("OPENAI_MODEL", "TEAM_PASSCODE", "ADMIN_PASSCODE"):
        if not os.getenv(key):
            raise RuntimeError(f"{key} is required")
    app.state.mutation_lock = threading.RLock()
    app.state.rate_lock = threading.Lock()
    app.state.rate_windows = {}
    app.state.started_at = datetime.now(timezone.utc)
    app.state.photo_operations = {
        "succeeded": 0,
        "failed": 0,
        "total_duration_ms": 0,
        "last_error": None,
    }
    _load_state(app)
    yield
    app.state.db.close()


app = FastAPI(title="Cat Colony Watch", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def request_operations(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "")
    if not SAFE_REQUEST_ID.fullmatch(request_id):
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.monotonic()
    status = 500
    try:
        if request.url.path == "/api/reports/photo":
            try:
                content_length = int(request.headers.get("content-length", "0"))
            except ValueError:
                content_length = 0
            if content_length > MAX_PHOTO_BODY_BYTES:
                status = 413
                return JSONResponse(
                    {"detail": "photo report is too large"},
                    status_code=status,
                    headers={"X-Request-ID": request_id},
                )
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        _log_event(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=_safe_log_path(request.url.path),
            status=status,
            duration_ms=round((time.monotonic() - started) * 1000),
        )


@app.middleware("http")
async def require_team_passcode(request: Request, call_next):
    path = request.url.path
    public = (
        path == "/healthz"
        or path.startswith("/signin")
        or path.startswith("/static/")
        or path.startswith("/report/")
    )
    if public:
        return await call_next(request)
    if hmac.compare_digest(request.cookies.get(COOKIE_NAME, ""), _session_token()):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "team sign-in required"}, status_code=401)
    return RedirectResponse("/signin", status_code=303)


@app.middleware("http")
async def private_response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(self), geolocation=(self), microphone=()"
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://unpkg.com; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    if not request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "private, no-store")
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0]
    if request.url.scheme == "https" or forwarded_proto == "https" or os.getenv("RENDER"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


@app.get("/healthz")
def healthz(request: Request):
    ready = hasattr(request.app.state, "db")
    if ready:
        try:
            request.app.state.db.connection.execute("SELECT 1").fetchone()
        except Exception:
            ready = False
    return JSONResponse({
        "ok": ready,
        "ready": ready,
        "storage": getattr(getattr(request.app.state, "change_log", None), "mode", None),
        "revision": _deploy_revision(),
    }, status_code=200 if ready else 503)


@app.get("/signin")
def signin_page():
    return HTMLResponse(_signin_html())


@app.post("/signin")
async def signin(request: Request):
    values = parse_qs((await request.body()).decode())
    supplied = values.get("passcode", [""])[0]
    client_key = _client_key(request)
    if not hmac.compare_digest(supplied, os.getenv("TEAM_PASSCODE", "")):
        if _rate_limited(request.app, "signin", client_key, SIGNIN_FAILURE_LIMIT):
            return HTMLResponse(
                _signin_html(rate_limited=True),
                status_code=429,
                headers={"Retry-After": str(RATE_WINDOW_SECONDS)},
            )
        return RedirectResponse("/signin?error=1", status_code=303)
    _clear_rate_limit(request.app, "signin", client_key)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        _session_token(),
        max_age=60 * 60 * 24 * 180,
        httponly=True,
        secure=(
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").split(",", 1)[0] == "https"
            or bool(os.getenv("RENDER"))
        ),
        samesite="lax",
    )
    return response


@app.get("/")
def home():
    return HTMLResponse(_index_html())


@app.get("/report/{token}")
def sponsor_report(token: str, request: Request):
    if not hmac.compare_digest(token, _sponsor_report_token()):
        raise HTTPException(status_code=404, detail="Not Found")
    return HTMLResponse(
        _sponsor_html(request.app.state.db),
        headers={
            "Cache-Control": "private, no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "Referrer-Policy": "no-referrer",
        },
    )


@app.post("/api/sponsor-link")
def sponsor_link(access: AdminPasscode):
    if not hmac.compare_digest(
        access.admin_passcode, os.getenv("ADMIN_PASSCODE", "")
    ):
        raise HTTPException(status_code=403, detail="admin passcode required")
    return {"path": f"/report/{_sponsor_report_token()}"}


def _colony_rows(db: Database) -> list[dict]:
    positions = {item["id"]: item for item in db.list_colonies()}
    severity_rank = {"urgent": 3, "high": 2, "normal": 1}
    alert_levels: dict[str, str] = {}
    for alert in db.open_alerts():
        colony_id = alert["colony_id"]
        if not colony_id:
            continue
        current = alert_levels.get(colony_id)
        if current is None or severity_rank[alert["severity"]] > severity_rank[current]:
            alert_levels[colony_id] = alert["severity"]
    rows = [
        {
            **item,
            "lat": positions[item["id"]]["lat"],
            "lng": positions[item["id"]]["lng"],
            "notes": positions[item["id"]]["notes"],
            "alert_severity": alert_levels.get(item["id"]),
        }
        for item in db.colony_counts()
    ]
    return sorted(
        rows,
        key=lambda item: (
            -severity_rank.get(item["alert_severity"], 0),
            -item["cats"],
            item["name"],
        ),
    )


@app.get("/api/bootstrap")
def bootstrap(request: Request):
    db = request.app.state.db
    return {
        "colonies": _colony_rows(db),
        "alerts": db.open_alerts(),
        "suggestions": db.open_suggestions(),
        "volunteers": db.list_volunteers(),
    }


@app.get("/api/colonies")
def colonies(request: Request):
    return _colony_rows(request.app.state.db)


@app.get("/api/colonies/{colony_id}")
def colony_detail(colony_id: str, request: Request):
    try:
        return request.app.state.db.colony_detail(colony_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/cats/{cat_id}")
def cat_detail(cat_id: int, request: Request):
    try:
        return request.app.state.db.cat_detail(cat_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/volunteers")
def volunteers(request: Request):
    return request.app.state.db.list_volunteers()


@app.get("/api/alerts")
def alerts(request: Request):
    return request.app.state.db.open_alerts()


@app.get("/api/suggestions")
def suggestions(request: Request):
    return request.app.state.db.open_suggestions()


@app.get("/api/photos/{photo_id}")
def photo(photo_id: int, request: Request):
    try:
        record = request.app.state.db.photo(photo_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    path = Path(record["path"]).resolve()
    allowed = [
        (DATA_DIR / "photos").resolve(),
        LIVE_PHOTO_DIR.resolve(),
        (LOCAL_LOG_PATH.parent / "live_photos").resolve(),
    ]
    if not any(path.is_relative_to(root) for root in allowed) or not path.is_file():
        raise HTTPException(status_code=404, detail="photo is unavailable")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/storage")
def storage(request: Request):
    return {
        "mode": request.app.state.change_log.mode,
        "changes": request.app.state.change_count,
        "api_spend_today_usd": request.app.state.api_spend_today_usd,
    }


@app.get("/api/operations")
def operations(request: Request, x_admin_passcode: str | None = Header(default=None)):
    if not hmac.compare_digest(x_admin_passcode or "", os.getenv("ADMIN_PASSCODE", "")):
        raise HTTPException(status_code=403, detail="admin passcode required")
    photo_operations = dict(request.app.state.photo_operations)
    succeeded = int(photo_operations["succeeded"])
    photo_operations["average_duration_ms"] = (
        round(int(photo_operations["total_duration_ms"]) / succeeded) if succeeded else None
    )
    return {
        "revision": _deploy_revision(),
        "uptime_seconds": round(
            (datetime.now(timezone.utc) - request.app.state.started_at).total_seconds()
        ),
        "storage": request.app.state.change_log.mode,
        "changes": request.app.state.change_count,
        "api_spend_today_usd": request.app.state.api_spend_today_usd,
        "photo_reports": photo_operations,
    }


def _append_and_apply(request: Request, change: dict) -> dict:
    with request.app.state.mutation_lock:
        existing = request.app.state.changes_by_id.get(change["id"])
        if existing is not None:
            if existing.get("type") != change.get("type"):
                raise HTTPException(status_code=409, detail="request id was already used")
            return {
                "duplicate": True,
                "change_id": existing["id"],
                "at": existing.get("data", {}).get("at"),
                **existing.get("data", {}).get("response", {}),
            }
        try:
            result = _apply_change(
                request.app.state.db,
                request.app.state.cache,
                request.app.state.change_log,
                change,
            )
            change["data"]["response"] = result
            request.app.state.change_log.append(change)
        except (ValueError, RuntimeError) as error:
            _load_state(request.app)
            raise HTTPException(status_code=400, detail=str(error)) from error
        request.app.state.change_count += 1
        request.app.state.changes_by_id[change["id"]] = change
        return result


@app.post("/api/reports/fed")
def add_feeding(report: FeedingReport, request: Request):
    at = report.at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    change = {
        "id": report.client_request_id or str(uuid.uuid4()),
        "type": "feeding_report",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": {
            "colony_id": report.colony_id,
            "volunteer_id": report.volunteer_id,
            "at": at,
        },
    }
    result = _append_and_apply(request, change)
    return {"ok": True, "change_id": change["id"], "at": at, **result}


@app.post("/api/suggestions/{suggestion_id}/decision")
def decide_suggestion(suggestion_id: int, decision: SuggestionDecision, request: Request):
    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    change = {
        "id": str(uuid.uuid4()),
        "type": "suggestion_decision",
        "created_at": at,
        "data": {
            "suggestion_id": suggestion_id,
            "volunteer_id": decision.volunteer_id,
            "action": decision.action,
            "at": at,
        },
    }
    return {"ok": True, **_append_and_apply(request, change)}


@app.post("/api/alerts/{alert_id}/done")
def resolve_alert(alert_id: int, decision: AlertDecision, request: Request):
    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    change = {
        "id": str(uuid.uuid4()),
        "type": "alert_resolution",
        "created_at": at,
        "data": {"alert_id": alert_id, "volunteer_id": decision.volunteer_id, "at": at},
    }
    return {"ok": True, **_append_and_apply(request, change)}


def _decode_and_resize_photo(data_url: str) -> tuple[bytes, str]:
    try:
        header, encoded = data_url.split(",", 1)
        if not header.startswith("data:image/") or ";base64" not in header:
            raise ValueError
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("photo must be a base64 image data URL") from error
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("photo is larger than 12 MB")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((768, 768), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=86, optimize=True)
    except OSError as error:
        raise ValueError("photo could not be read") from error
    content = output.getvalue()
    return content, hashlib.sha256(content).hexdigest()


def _photo_report_outcomes(db: Database, photo_ids: list[int]) -> dict:
    placeholders = ",".join("?" for _ in photo_ids)
    matches = db.connection.execute(
        f"""
        SELECT s.photo_id, s.candidate_cat_id, s.strength,
               COALESCE(c.reported_name, c.display_name) AS candidate
        FROM suggestions s JOIN cats c ON c.id = s.candidate_cat_id
        WHERE s.kind = 'same_cat' AND s.decided IS NULL
          AND s.photo_id IN ({placeholders})
        ORDER BY s.photo_id
        """,
        photo_ids,
    ).fetchall()
    new_cats = db.connection.execute(
        f"""
        SELECT COUNT(DISTINCT p.cat_id)
        FROM photos p
        WHERE p.id IN ({placeholders}) AND p.cat_id IS NOT NULL
        """,
        photo_ids,
    ).fetchone()[0]
    return {
        "match_suggestions": [dict(row) for row in matches],
        "new_cat_count": int(new_cats),
    }


@app.post("/api/reports/photo")
def add_photo_report(report: LiveReport, request: Request):
    change_id = report.client_request_id or str(uuid.uuid4())
    with request.app.state.mutation_lock:
        existing = request.app.state.changes_by_id.get(change_id)
        if existing is not None:
            if existing.get("type") != "live_report":
                raise HTTPException(status_code=409, detail="request id was already used")
            return {
                "ok": True,
                "duplicate": True,
                **existing.get("data", {}).get("response", {}),
                "api_spend_today_usd": request.app.state.api_spend_today_usd,
            }
        client_key = _client_key(request)
        if _rate_limited(request.app, "photo", client_key, PHOTO_RATE_LIMIT):
            raise HTTPException(
                status_code=429,
                detail="too many photo reports; wait a few minutes and try again",
                headers={"Retry-After": str(RATE_WINDOW_SECONDS)},
            )
        started = time.monotonic()
        spend_before = request.app.state.cache.spend
        request.state.photo_change_appended = False
        request.state.photo_digest = None
        try:
            result = _add_photo_report_locked(report, request, change_id)
            elapsed = round((time.monotonic() - started) * 1000)
            request.app.state.photo_operations["succeeded"] += 1
            request.app.state.photo_operations["total_duration_ms"] += elapsed
            _log_event(
                "photo_report",
                request_id=request.state.request_id,
                outcome="succeeded",
                kind=report.kind,
                colony_id=report.colony_id,
                duration_ms=elapsed,
                api_cost_usd=result["api_cost_usd"],
                match_suggestions=len(result["match_suggestions"]),
                new_cat_count=result["new_cat_count"],
            )
            return result
        except HTTPException:
            if request.state.photo_digest and not request.state.photo_change_appended:
                _record_failed_api_spend(request, spend_before)
                _load_state(request.app)
                _discard_uncommitted_photo(request)
            raise
        except Exception as error:
            if not request.state.photo_change_appended:
                _record_failed_api_spend(request, spend_before)
            _load_state(request.app)
            _discard_uncommitted_photo(request)
            elapsed = round((time.monotonic() - started) * 1000)
            request.app.state.photo_operations["failed"] += 1
            request.app.state.photo_operations["last_error"] = type(error).__name__
            _log_event(
                "photo_report",
                request_id=request.state.request_id,
                outcome="failed",
                kind=report.kind,
                colony_id=report.colony_id,
                duration_ms=elapsed,
                error_type=type(error).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="photo analysis is temporarily unavailable; your form was not recorded",
                headers={"Retry-After": "30"},
            ) from error


def _record_failed_api_spend(request: Request, spend_before: float) -> None:
    spent = round(max(0.0, request.app.state.cache.spend - spend_before), 8)
    if spent:
        request.app.state.change_log.add_api_spend(_api_day(), spent)


def _discard_uncommitted_photo(request: Request) -> None:
    digest = request.state.photo_digest
    if digest and not any(
        item.get("data", {}).get("photo_hash") == digest
        for item in request.app.state.change_log.load()
    ):
        request.app.state.change_log.delete_photo(digest)
        (LIVE_PHOTO_DIR / f"{digest}.jpg").unlink(missing_ok=True)


def _add_photo_report_locked(report: LiveReport, request: Request, change_id: str):
    db: Database = request.app.state.db
    cache: AICache = request.app.state.cache
    spend_before = cache.spend
    try:
        db._require_colony(report.colony_id)
        volunteer_name = _volunteer_name(db, report.volunteer_id)
        colony = next(item for item in db.list_colonies() if item["id"] == report.colony_id)
        content, digest = _decode_and_resize_photo(report.photo_data_url)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    request.state.photo_digest = digest
    photo_path = LIVE_PHOTO_DIR / f"{digest}.jpg"
    photo_path.parent.mkdir(parents=True, exist_ok=True)
    photo_path.write_bytes(content)
    description = cache.get("descriptions", digest)
    if description is None:
        cache.check_budget()
        description = describe_photo(
            photo_path,
            model=cache.model,
            cache_dir="/tmp/ccw_eval_cache",
            cost_log="costs.log",
        )
        cache.put("descriptions", digest, description)

    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    note = report.note.strip()
    text = f"Colony: {colony['name']}. {note or report.kind.title() + ' report with photo.'}"
    report_id = db.add_report(
        {
            "sent_at": at,
            "sender": volunteer_name,
            "kind": report.kind,
            "text": text,
            "lat": report.lat,
            "lng": report.lng,
            "source": "app",
            "raw": f"live:{change_id}",
        }
    )
    descriptions = []
    photo_ids = []
    for cat_index, cat in enumerate(description.get("cats", [])):
        single = {
            "cat_count": 1,
            "cats": [cat],
            "kittens_present": description.get("kittens_present", False),
            "photo_quality": description.get("photo_quality", "poor"),
        }
        descriptions.append(single)
        photo_id = db.add_photo(report_id, photo_path, cat_index, single)
        photo_ids.append(photo_id)
    if not photo_ids:
        raise HTTPException(status_code=400, detail="no cat was visible in the photo")

    before = {
        section: set(cache.data.get(section, {})) for section in ("matches", "messages")
    }
    context = ImportContext(
        db=db,
        cache=cache,
        model=cache.model,
        report_id=report_id,
        volunteer_id=report.volunteer_id,
        sent_at=at,
        photo_ids=set(photo_ids),
    )
    if report.kind in {"sighting", "urgent"}:
        # The app form has already supplied the colony, volunteer, timestamp and
        # report kind. Only visual identity needs AI here; deterministic routing
        # avoids several redundant agent turns on the phone's critical path.
        for photo_id in photo_ids:
            match_report_photo(context, photo_id, report.colony_id)
        direct_outcomes = _photo_report_outcomes(db, photo_ids)
        report_label = "sighting" if report.kind == "sighting" else "urgent report"
        if direct_outcomes["match_suggestions"]:
            match = direct_outcomes["match_suggestions"][0]
            summary_text = (
                f"Recorded a {colony['name']} {report_label}; a {match['strength']} "
                f"{match['candidate']} match needs review."
            )
            needs_review = True
        elif direct_outcomes["new_cat_count"]:
            summary_text = (
                f"Recorded a {colony['name']} {report_label} and created "
                f"{direct_outcomes['new_cat_count']} new cat record"
                f"{'s' if direct_outcomes['new_cat_count'] != 1 else ''}."
            )
            needs_review = False
        else:
            summary_text = f"Recorded a {colony['name']} {report_label}."
            needs_review = False
        if report.kind == "urgent":
            normalized_note = note.casefold()
            if NEEDS_VET_WORDS.search(note) or PREGNANCY_WORDS.search(note):
                event_kind = "health"
            elif any(word in normalized_note for word in ("kitten", "gatito", "ti chat")):
                event_kind = "kittens"
            else:
                event_kind = "need"
            detail = note or "Urgent photo report"
            db.record_event(
                event_kind,
                report.colony_id,
                None,
                detail,
                report_id,
                at,
                report.volunteer_id,
            )
            context.mutations.append({
                "tool": "record_event",
                "args": {
                    "kind": event_kind,
                    "colony_id": report.colony_id,
                    "detail": detail,
                    "cat_id": None,
                },
            })
            needs_review = True
        summary = AgentSummary(
            summary=summary_text,
            colony_ids=[report.colony_id],
            needs_review=needs_review,
        )
    apply_named_cat_facts(db, report_id)
    db.create_possible_duplicate_suggestions()
    rebuild_alerts(db, at)
    api_cost_usd = round(cache.spend - spend_before, 8)
    outcomes = _photo_report_outcomes(db, photo_ids)
    cache_entries = {
        section: {
            key: cache.data[section][key]
            for key in set(cache.data.get(section, {})) - before[section]
        }
        for section in before
    }
    change = {
        "id": change_id,
        "type": "live_report",
        "created_at": at,
        "data": {
            "kind": report.kind,
            "colony_id": report.colony_id,
            "volunteer_id": report.volunteer_id,
            "text": text,
            "lat": report.lat,
            "lng": report.lng,
            "at": at,
            "photo_hash": digest,
            "descriptions": descriptions,
            "original_photo_ids": photo_ids,
            "mutations": context.mutations,
            "summary": summary.summary,
            "api_cost_usd": api_cost_usd,
            "cache_entries": cache_entries,
        },
    }
    response = {
        "ok": True,
        "report_id": report_id,
        "summary": summary.summary,
        "needs_review": summary.needs_review,
        "colony_ids": summary.colony_ids,
        "api_cost_usd": api_cost_usd,
        **outcomes,
    }
    change["data"]["response"] = response
    request.app.state.change_log.store_photo(digest, content)
    request.app.state.change_log.append(change)
    request.state.photo_change_appended = True
    recorded_spend = request.app.state.change_log.add_api_spend(
        _api_day(), api_cost_usd
    )
    request.app.state.change_count += 1
    request.app.state.changes_by_id[change_id] = change
    request.app.state.api_spend_today_usd = round(recorded_spend, 8)
    return {
        **response,
        "api_spend_today_usd": request.app.state.api_spend_today_usd,
    }


@app.post("/api/admin/reset")
def reset_demo(request: Request, x_admin_passcode: str | None = Header(default=None)):
    if not hmac.compare_digest(x_admin_passcode or "", os.getenv("ADMIN_PASSCODE", "")):
        raise HTTPException(status_code=403, detail="admin passcode required")
    with request.app.state.mutation_lock:
        request.app.state.change_log.clear()
        _load_state(request.app)
        return {
            "ok": True,
            "changes": 0,
            "api_spend_today_usd": request.app.state.api_spend_today_usd,
        }
