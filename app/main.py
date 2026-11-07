"""FastAPI web app and replayable live-report API for Cat Colony Watch."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import uuid
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from app.ai_cache import AICache
from app.change_log import ChangeLog
from app.database import Database
from app.identification import describe_photo
from app.import_demo import import_demo
from app.message_agent import ImportContext, build_agent, process_report, replay_mutations
from app.rules import apply_named_cat_facts, rebuild_alerts


DATA_DIR = Path("data/demo")
STATIC_DIR = Path(__file__).parent / "static"
DB_PATH = Path(os.getenv("CCW_DB_PATH", "/tmp/cat_colony_watch.db"))
LOCAL_LOG_PATH = Path(os.getenv("CCW_LOCAL_CHANGE_LOG", "data/local_changes.json"))
LIVE_PHOTO_DIR = Path(os.getenv("CCW_LIVE_PHOTO_DIR", "/tmp/ccw_live_photos"))
COOKIE_NAME = "ccw_session"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024


class FeedingReport(BaseModel):
    colony_id: str
    volunteer_id: str
    at: str | None = None


class SuggestionDecision(BaseModel):
    volunteer_id: str
    action: Literal["same", "different", "new_cat", "confirm", "reject"]


class AlertDecision(BaseModel):
    volunteer_id: str


class LiveReport(BaseModel):
    kind: Literal["sighting", "urgent"]
    colony_id: str
    volunteer_id: str
    note: str = Field(default="", max_length=2000)
    lat: float | None = None
    lng: float | None = None
    photo_data_url: str


def _session_token() -> str:
    passcode = os.getenv("TEAM_PASSCODE", "")
    if not passcode:
        raise RuntimeError("TEAM_PASSCODE is required")
    return hmac.new(passcode.encode(), b"cat-colony-watch-session", hashlib.sha256).hexdigest()


def _build_database() -> tuple[Database, AICache]:
    return import_demo(DATA_DIR, DB_PATH, allow_api=False)


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
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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


@app.get("/healthz")
def healthz(request: Request):
    return {
        "ok": True,
        "ready": hasattr(request.app.state, "db"),
        "storage": getattr(getattr(request.app.state, "change_log", None), "mode", None),
        "revision": os.getenv("RENDER_GIT_COMMIT", "local")[:12],
    }


@app.get("/signin")
def signin_page():
    return FileResponse(STATIC_DIR / "signin.html")


@app.post("/signin")
async def signin(request: Request):
    values = parse_qs((await request.body()).decode())
    supplied = values.get("passcode", [""])[0]
    if not hmac.compare_digest(supplied, os.getenv("TEAM_PASSCODE", "")):
        return RedirectResponse("/signin?error=1", status_code=303)
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


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


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
    return [
        {
            **item,
            "lat": positions[item["id"]]["lat"],
            "lng": positions[item["id"]]["lng"],
            "notes": positions[item["id"]]["notes"],
            "alert_severity": alert_levels.get(item["id"]),
        }
        for item in db.colony_counts()
    ]


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
    }


def _append_and_apply(request: Request, change: dict) -> dict:
    try:
        result = _apply_change(
            request.app.state.db,
            request.app.state.cache,
            request.app.state.change_log,
            change,
        )
        request.app.state.change_log.append(change)
    except (ValueError, RuntimeError) as error:
        _load_state(request.app)
        raise HTTPException(status_code=400, detail=str(error)) from error
    request.app.state.change_count += 1
    return result


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


@app.post("/api/reports/photo")
def add_photo_report(report: LiveReport, request: Request):
    db: Database = request.app.state.db
    cache: AICache = request.app.state.cache
    try:
        db._require_colony(report.colony_id)
        volunteer_name = _volunteer_name(db, report.volunteer_id)
        colony = next(item for item in db.list_colonies() if item["id"] == report.colony_id)
        content, digest = _decode_and_resize_photo(report.photo_data_url)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    request.app.state.change_log.store_photo(digest, content)
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
            "raw": f"live-pending:{uuid.uuid4()}",
        }
    )
    descriptions = []
    photo_inputs = []
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
        photo_inputs.append(
            {"photo_id": photo_id, "filename": f"{digest}.jpg", "observations": single}
        )
    if not photo_ids:
        _load_state(request.app)
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
    report_input = {
        "report_id": report_id,
        "sent_at": at,
        "volunteer": {"id": report.volunteer_id, "name": volunteer_name},
        "text": text,
        "location": {"lat": report.lat, "lng": report.lng},
        "photos": photo_inputs,
    }
    try:
        summary = process_report(request.app.state.agent, context, report_input)
        apply_named_cat_facts(db, report_id)
        db.create_possible_duplicate_suggestions()
        rebuild_alerts(db, at)
        cache_entries = {
            section: {
                key: cache.data[section][key]
                for key in set(cache.data.get(section, {})) - before[section]
            }
            for section in before
        }
        change = {
            "id": str(uuid.uuid4()),
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
                "cache_entries": cache_entries,
            },
        }
        request.app.state.change_log.append(change)
    except Exception:
        _load_state(request.app)
        raise
    request.app.state.change_count += 1
    return {
        "ok": True,
        "report_id": report_id,
        "summary": summary.summary,
        "needs_review": summary.needs_review,
        "colony_ids": summary.colony_ids,
    }


@app.post("/api/admin/reset")
def reset_demo(request: Request, x_admin_passcode: str | None = Header(default=None)):
    if not hmac.compare_digest(x_admin_passcode or "", os.getenv("ADMIN_PASSCODE", "")):
        raise HTTPException(status_code=403, detail="admin passcode required")
    request.app.state.change_log.clear()
    _load_state(request.app)
    return {"ok": True, "changes": 0}
