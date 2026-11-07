"""SQLite storage and human-confirmation invariants for Cat Colony Watch."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TABLES = (
    "alerts",
    "suggestions",
    "events",
    "photos",
    "reports",
    "cats",
    "colony_feeders",
    "volunteers",
    "colonies",
)

ALERT_KINDS = {
    "pregnant",
    "kittens",
    "needs_vet",
    "lost_feeder",
    "out_of_food",
    "needs_tnr",
    "stale_suggestions",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS colonies (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS volunteers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('feeder', 'volunteer', 'admin'))
);

CREATE TABLE IF NOT EXISTS colony_feeders (
    colony_id TEXT NOT NULL REFERENCES colonies(id) ON DELETE CASCADE,
    volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
    PRIMARY KEY (colony_id, volunteer_id)
);

CREATE TABLE IF NOT EXISTS cats (
    id INTEGER PRIMARY KEY,
    colony_id TEXT NOT NULL REFERENCES colonies(id),
    display_name TEXT NOT NULL,
    reported_name TEXT,
    description_json TEXT NOT NULL,
    tnr_status TEXT NOT NULL CHECK (tnr_status IN ('fixed', 'needs_tnr', 'unknown')),
    health TEXT NOT NULL CHECK (health IN ('ok', 'needs_vet')),
    health_note TEXT,
    pregnant INTEGER NOT NULL DEFAULT 0 CHECK (pregnant IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'adopted', 'missing', 'deceased')),
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    reference_photo TEXT NOT NULL,
    merged_into_cat_id INTEGER REFERENCES cats(id)
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    sent_at TEXT NOT NULL,
    volunteer_id TEXT NOT NULL REFERENCES volunteers(id),
    kind TEXT NOT NULL CHECK (kind IN ('message', 'fed', 'sighting', 'urgent')),
    text TEXT NOT NULL,
    lat REAL,
    lng REAL,
    source TEXT NOT NULL CHECK (source IN ('import', 'app')),
    raw TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    cat_index INTEGER NOT NULL DEFAULT 0,
    description_json TEXT NOT NULL,
    crop_box TEXT NOT NULL,
    cat_id INTEGER REFERENCES cats(id),
    UNIQUE (report_id, path, cat_index)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    colony_id TEXT NOT NULL REFERENCES colonies(id),
    cat_id INTEGER REFERENCES cats(id),
    report_id INTEGER REFERENCES reports(id),
    kind TEXT NOT NULL CHECK (
        kind IN ('fed', 'sighting', 'tnr_done', 'health', 'kittens', 'need', 'status')
    ),
    detail TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL,
    volunteer_id TEXT NOT NULL REFERENCES volunteers(id)
);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('same_cat', 'possible_duplicate', 'status_change')),
    photo_id INTEGER REFERENCES photos(id),
    cat_id INTEGER REFERENCES cats(id),
    candidate_cat_id INTEGER REFERENCES cats(id),
    new_status TEXT CHECK (new_status IN ('adopted', 'missing', 'deceased')),
    strength TEXT CHECK (strength IN ('strong', 'weak')),
    feature_verdicts_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided TEXT CHECK (decided IN ('confirmed', 'rejected')),
    decided_by TEXT REFERENCES volunteers(id),
    decided_at TEXT,
    CHECK (
        (kind = 'same_cat' AND photo_id IS NOT NULL AND candidate_cat_id IS NOT NULL
            AND cat_id IS NULL AND new_status IS NULL AND strength IS NOT NULL)
        OR
        (kind = 'possible_duplicate' AND photo_id IS NULL AND candidate_cat_id IS NOT NULL
            AND cat_id IS NOT NULL AND new_status IS NULL AND strength = 'weak'
            AND cat_id != candidate_cat_id)
        OR
        (kind = 'status_change' AND cat_id IS NOT NULL AND new_status IS NOT NULL
            AND photo_id IS NULL AND candidate_cat_id IS NULL)
    ),
    CHECK (
        (decided IS NULL AND decided_by IS NULL AND decided_at IS NULL)
        OR
        (decided IS NOT NULL AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS one_open_photo_match
ON suggestions(photo_id) WHERE kind = 'same_cat' AND decided IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS one_open_status_change
ON suggestions(cat_id, new_status) WHERE kind = 'status_change' AND decided IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS one_open_possible_duplicate
ON suggestions(MIN(cat_id, candidate_cat_id), MAX(cat_id, candidate_cat_id))
WHERE kind = 'possible_duplicate' AND decided IS NULL;

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    colony_id TEXT REFERENCES colonies(id),
    cat_id INTEGER REFERENCES cats(id),
    kind TEXT NOT NULL CHECK (
        kind IN (
            'pregnant', 'kittens', 'needs_vet', 'lost_feeder',
            'out_of_food', 'needs_tnr', 'stale_suggestions'
        )
    ),
    severity TEXT NOT NULL CHECK (severity IN ('urgent', 'high', 'normal')),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS cats_by_colony ON cats(colony_id, status);
CREATE INDEX IF NOT EXISTS events_by_colony_time ON events(colony_id, at);
CREATE INDEX IF NOT EXISTS suggestions_open ON suggestions(decided, kind);

CREATE UNIQUE INDEX IF NOT EXISTS one_open_alert
ON alerts(IFNULL(colony_id, '__all__'), IFNULL(cat_id, -1), kind)
WHERE resolved_at IS NULL;
"""


class Database:
    """Small SQLite wrapper that keeps identity and status decisions explicit."""

    def __init__(self, path: str | Path = ":memory:", *, reset: bool = False):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # Agents SDK executes synchronous function tools in a worker thread.
        # Imports are sequential, so one connection is safe to share here.
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if reset:
            self.reset()
        else:
            self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def reset(self) -> None:
        self.connection.execute("PRAGMA foreign_keys = OFF")
        for table in TABLES:
            self.connection.execute(f"DROP TABLE IF EXISTS {table}")
        self.connection.commit()
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)

    def seed_demo(self, data_dir: str | Path) -> None:
        data_dir = Path(data_dir)
        colonies = json.loads((data_dir / "colonies.json").read_text())
        volunteers = json.loads((data_dir / "volunteers.json").read_text())
        with self.connection:
            self.connection.executemany(
                "INSERT OR REPLACE INTO colonies(id, name, lat, lng, notes) VALUES(?, ?, ?, ?, ?)",
                [
                    (item["id"], item["name"], item["lat"], item["lng"], item["notes"])
                    for item in colonies
                ],
            )
            for volunteer in volunteers:
                self.connection.execute(
                    "INSERT OR REPLACE INTO volunteers(id, name, phone, role) VALUES(?, ?, ?, ?)",
                    (
                        volunteer["id"],
                        volunteer["name"],
                        volunteer["phone"],
                        volunteer["role"],
                    ),
                )
                self.connection.executemany(
                    "INSERT OR IGNORE INTO colony_feeders(colony_id, volunteer_id) VALUES(?, ?)",
                    [(colony_id, volunteer["id"]) for colony_id in volunteer["colony_ids"]],
                )

    def volunteer_id_for_name(self, name: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM volunteers WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown volunteer: {name}")
        return str(row["id"])

    def add_report(self, report: dict[str, Any]) -> int:
        volunteer_id = self.volunteer_id_for_name(report["sender"])
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO reports(sent_at, volunteer_id, kind, text, lat, lng, source, raw)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report["sent_at"],
                    volunteer_id,
                    report["kind"],
                    report["text"],
                    report["lat"],
                    report["lng"],
                    report["source"],
                    report["raw"],
                ),
            )
        return int(cursor.lastrowid)

    def add_photo(
        self,
        report_id: int,
        path: str | Path,
        cat_index: int,
        description: dict[str, Any],
    ) -> int:
        cat = description["cats"][0]
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO photos(path, report_id, cat_index, description_json, crop_box)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    str(path),
                    report_id,
                    cat_index,
                    json.dumps(description, sort_keys=True),
                    json.dumps(cat["box"]),
                ),
            )
        return int(cursor.lastrowid)

    def list_colonies(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, name, lat, lng, notes FROM colonies ORDER BY name"
        ).fetchall()
        return [dict(row) for row in rows]

    def list_cats(self, colony_id: str) -> list[dict[str, Any]]:
        self._require_colony(colony_id)
        rows = self.connection.execute(
            """
            SELECT id, display_name, reported_name, description_json, tnr_status, health,
                   health_note, pregnant, status, first_seen, last_seen, reference_photo
            FROM cats
            WHERE colony_id = ? AND status = 'active' AND merged_into_cat_id IS NULL
            ORDER BY id
            """,
            (colony_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def photo(self, photo_id: int) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT p.*, r.sent_at, r.volunteer_id
            FROM photos p JOIN reports r ON r.id = p.report_id WHERE p.id = ?
            """,
            (photo_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown photo: {photo_id}")
        return dict(row)

    def matching_candidates(self, colony_id: str) -> list[dict[str, Any]]:
        cats = self.list_cats(colony_id)
        candidates = []
        for cat in cats:
            references = self.connection.execute(
                """
                SELECT path, description_json FROM photos
                WHERE cat_id = ? ORDER BY id LIMIT 2
                """,
                (cat["id"],),
            ).fetchall()
            if not references:
                continue
            candidates.append(
                {
                    "id": str(cat["id"]),
                    "reference_photos": [row["path"] for row in references],
                    "reference_descriptions": [
                        json.loads(row["description_json"]) for row in references
                    ],
                }
            )
        return candidates

    def create_cat_for_photo(self, photo_id: int, colony_id: str) -> dict[str, Any]:
        self._require_colony(colony_id)
        photo = self.photo(photo_id)
        if photo["cat_id"] is not None:
            return {"action": "existing", "cat_id": int(photo["cat_id"])}
        pending = self.connection.execute(
            "SELECT id FROM suggestions WHERE photo_id = ? AND decided IS NULL", (photo_id,)
        ).fetchone()
        if pending:
            return {"action": "pending", "suggestion_id": int(pending["id"])}

        description = json.loads(photo["description_json"])
        cat = description["cats"][0]
        ear_tip = cat.get("ear_tip", "unclear")
        tnr_status = "fixed" if ear_tip in {"left", "right"} else "needs_tnr" if ear_tip == "none" else "unknown"
        health_signs = cat.get("apparent_health", [])
        health = "needs_vet" if health_signs else "ok"
        health_note = "; ".join(health_signs) or None
        reported_name = self._reported_name_hint(photo, colony_id)
        display_name = reported_name or self._display_name(cat)
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO cats(
                    colony_id, display_name, reported_name, description_json, tnr_status,
                    health, health_note, pregnant, status, first_seen, last_seen, reference_photo
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    colony_id,
                    display_name,
                    reported_name,
                    photo["description_json"],
                    tnr_status,
                    health,
                    health_note,
                    int(bool(cat.get("looks_pregnant"))),
                    photo["sent_at"],
                    photo["sent_at"],
                    photo["path"],
                ),
            )
            cat_id = int(cursor.lastrowid)
            self.connection.execute("UPDATE photos SET cat_id = ? WHERE id = ?", (cat_id, photo_id))
            self._insert_event(
                colony_id,
                cat_id,
                photo["report_id"],
                "sighting",
                "New cat from photo",
                photo["sent_at"],
                photo["volunteer_id"],
            )
        return {"action": "new", "cat_id": cat_id, "display_name": display_name}

    def create_possible_duplicate_suggestions(self) -> int:
        """Suggest record-level duplicates from reported-name hints; never merge them."""
        groups = self.connection.execute(
            """
            SELECT colony_id, LOWER(reported_name) AS normalized_name,
                   MIN(reported_name) AS reported_name
            FROM cats
            WHERE status = 'active' AND merged_into_cat_id IS NULL AND reported_name IS NOT NULL
            GROUP BY colony_id, LOWER(reported_name)
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        created = 0
        with self.connection:
            for group in groups:
                cats = self.connection.execute(
                    """
                    SELECT id, first_seen FROM cats
                    WHERE colony_id = ? AND LOWER(reported_name) = ?
                      AND status = 'active' AND merged_into_cat_id IS NULL
                    ORDER BY first_seen, id
                    """,
                    (group["colony_id"], group["normalized_name"]),
                ).fetchall()
                survivor = int(cats[0]["id"])
                for duplicate in cats[1:]:
                    duplicate_id = int(duplicate["id"])
                    existing = self.connection.execute(
                        """
                        SELECT id FROM suggestions
                        WHERE kind = 'possible_duplicate' AND decided IS NULL
                          AND MIN(cat_id, candidate_cat_id) = MIN(?, ?)
                          AND MAX(cat_id, candidate_cat_id) = MAX(?, ?)
                        """,
                        (duplicate_id, survivor, duplicate_id, survivor),
                    ).fetchone()
                    if existing:
                        continue
                    self.connection.execute(
                        """
                        INSERT INTO suggestions(
                            kind, cat_id, candidate_cat_id, strength,
                            feature_verdicts_json, reason, created_at
                        ) VALUES('possible_duplicate', ?, ?, 'weak', '{}', ?, ?)
                        """,
                        (
                            duplicate_id,
                            survivor,
                            f"Two records share the reported name {group['reported_name']}; "
                            "a person must compare them before merging.",
                            duplicate["first_seen"],
                        ),
                    )
                    created += 1
        return created

    def create_same_cat_suggestion(
        self,
        photo_id: int,
        candidate_cat_id: int,
        strength: str,
        comparisons: list[dict[str, Any]],
        reason: str,
    ) -> dict[str, Any]:
        if strength not in {"strong", "weak"}:
            raise ValueError("same-cat suggestion strength must be strong or weak")
        photo = self.photo(photo_id)
        candidate = self.connection.execute(
            "SELECT id, colony_id FROM cats WHERE id = ? AND status = 'active'",
            (candidate_cat_id,),
        ).fetchone()
        if candidate is None:
            raise ValueError(f"unknown active candidate cat: {candidate_cat_id}")
        existing = self.connection.execute(
            "SELECT id, strength, candidate_cat_id FROM suggestions WHERE photo_id = ? AND decided IS NULL",
            (photo_id,),
        ).fetchone()
        if existing:
            return {"action": "pending", **dict(existing)}
        if photo["cat_id"] is not None:
            return {"action": "existing", "cat_id": int(photo["cat_id"])}
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO suggestions(
                    kind, photo_id, candidate_cat_id, strength,
                    feature_verdicts_json, reason, created_at
                ) VALUES('same_cat', ?, ?, ?, ?, ?, ?)
                """,
                (
                    photo_id,
                    candidate_cat_id,
                    strength,
                    json.dumps(comparisons, sort_keys=True),
                    reason,
                    photo["sent_at"],
                ),
            )
        return {
            "action": "suggestion",
            "suggestion_id": int(cursor.lastrowid),
            "candidate_cat_id": candidate_cat_id,
            "strength": strength,
        }

    def log_feeding(self, colony_id: str, volunteer_id: str, at: str, report_id: int) -> int:
        self._require_colony(colony_id)
        self._require_volunteer(volunteer_id)
        with self.connection:
            return self._insert_event(
                colony_id, None, report_id, "fed", "Fed colony", at, volunteer_id
            )

    def record_event(
        self,
        kind: str,
        colony_id: str,
        cat_id: int | None,
        detail: str,
        report_id: int,
        at: str,
        volunteer_id: str,
    ) -> int:
        if kind not in {"fed", "sighting", "tnr_done", "health", "kittens", "need", "status"}:
            raise ValueError(f"unsupported event kind: {kind}")
        self._require_colony(colony_id)
        self._require_volunteer(volunteer_id)
        if cat_id is not None:
            self._require_cat_at_colony(cat_id, colony_id)
        with self.connection:
            return self._insert_event(
                colony_id, cat_id, report_id, kind, detail, at, volunteer_id
            )

    def update_cat(
        self,
        cat_id: int,
        *,
        tnr_status: str | None = None,
        health: str | None = None,
        health_note: str | None = None,
        pregnant: bool | None = None,
    ) -> dict[str, Any]:
        if tnr_status is not None and tnr_status not in {"fixed", "needs_tnr", "unknown"}:
            raise ValueError(f"unsupported TNR status: {tnr_status}")
        if health is not None and health not in {"ok", "needs_vet"}:
            raise ValueError(f"unsupported health value: {health}")
        row = self.connection.execute("SELECT id FROM cats WHERE id = ?", (cat_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown cat: {cat_id}")
        changes = {
            "tnr_status": tnr_status,
            "health": health,
            "health_note": health_note,
            "pregnant": None if pregnant is None else int(pregnant),
        }
        selected = {key: value for key, value in changes.items() if value is not None}
        if selected:
            assignments = ", ".join(f"{key} = ?" for key in selected)
            with self.connection:
                self.connection.execute(
                    f"UPDATE cats SET {assignments} WHERE id = ?",
                    (*selected.values(), cat_id),
                )
        return dict(
            self.connection.execute(
                "SELECT id, tnr_status, health, health_note, pregnant, status FROM cats WHERE id = ?",
                (cat_id,),
            ).fetchone()
        )

    def suggest_status(
        self,
        cat_id: int,
        new_status: str,
        reason: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if new_status not in {"adopted", "missing", "deceased"}:
            raise ValueError(f"unsupported status suggestion: {new_status}")
        row = self.connection.execute(
            "SELECT id FROM cats WHERE id = ? AND status = 'active'", (cat_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown active cat: {cat_id}")
        existing = self.connection.execute(
            """
            SELECT id FROM suggestions
            WHERE kind = 'status_change' AND cat_id = ? AND new_status = ? AND decided IS NULL
            """,
            (cat_id, new_status),
        ).fetchone()
        if existing:
            return {"action": "pending", "suggestion_id": int(existing["id"])}
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO suggestions(
                    kind, cat_id, new_status, feature_verdicts_json, reason, created_at
                ) VALUES('status_change', ?, ?, '{}', ?, ?)
                """,
                (
                    cat_id,
                    new_status,
                    reason,
                    created_at or datetime.now(timezone.utc).isoformat(),
                ),
            )
        return {"action": "suggestion", "suggestion_id": int(cursor.lastrowid)}

    def confirm_suggestion(
        self,
        suggestion_id: int,
        decided_by: str,
        decision: str,
        *,
        decided_at: str | None = None,
    ) -> None:
        if decision not in {"confirmed", "rejected"}:
            raise ValueError("decision must be confirmed or rejected")
        self._require_volunteer(decided_by)
        suggestion = self.connection.execute(
            "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()
        if suggestion is None:
            raise ValueError(f"unknown suggestion: {suggestion_id}")
        if suggestion["decided"] is not None:
            raise ValueError(f"suggestion {suggestion_id} is already decided")
        decided_at = decided_at or datetime.now(timezone.utc).isoformat()
        with self.connection:
            self.connection.execute(
                """
                UPDATE suggestions SET decided = ?, decided_by = ?, decided_at = ? WHERE id = ?
                """,
                (decision, decided_by, decided_at, suggestion_id),
            )
            if decision == "confirmed" and suggestion["kind"] == "same_cat":
                photo = self.photo(int(suggestion["photo_id"]))
                cat_id = int(suggestion["candidate_cat_id"])
                self.connection.execute(
                    "UPDATE photos SET cat_id = ? WHERE id = ? AND cat_id IS NULL",
                    (cat_id, suggestion["photo_id"]),
                )
                cat = self.connection.execute(
                    "SELECT colony_id FROM cats WHERE id = ?", (cat_id,)
                ).fetchone()
                self.connection.execute(
                    "UPDATE cats SET last_seen = MAX(last_seen, ?) WHERE id = ?",
                    (photo["sent_at"], cat_id),
                )
                self._insert_event(
                    cat["colony_id"],
                    cat_id,
                    photo["report_id"],
                    "sighting",
                    "Human-confirmed same-cat photo",
                    photo["sent_at"],
                    photo["volunteer_id"],
                )
            elif decision == "confirmed" and suggestion["kind"] == "status_change":
                self.connection.execute(
                    "UPDATE cats SET status = ? WHERE id = ?",
                    (suggestion["new_status"], suggestion["cat_id"]),
                )

            elif decision == "confirmed" and suggestion["kind"] == "possible_duplicate":
                duplicate_id = int(suggestion["cat_id"])
                survivor_id = int(suggestion["candidate_cat_id"])
                duplicate = self.connection.execute(
                    "SELECT colony_id FROM cats WHERE id = ? AND merged_into_cat_id IS NULL",
                    (duplicate_id,),
                ).fetchone()
                survivor = self.connection.execute(
                    "SELECT colony_id FROM cats WHERE id = ? AND merged_into_cat_id IS NULL",
                    (survivor_id,),
                ).fetchone()
                if duplicate is None or survivor is None:
                    raise ValueError("possible-duplicate cat was already merged")
                if duplicate["colony_id"] != survivor["colony_id"]:
                    raise ValueError("possible-duplicate cats must belong to the same colony")
                self.connection.execute(
                    "UPDATE photos SET cat_id = ? WHERE cat_id = ?", (survivor_id, duplicate_id)
                )
                self.connection.execute(
                    "UPDATE events SET cat_id = ? WHERE cat_id = ?", (survivor_id, duplicate_id)
                )
                self.connection.execute(
                    """
                    UPDATE cats
                    SET last_seen = MAX(last_seen, (SELECT last_seen FROM cats WHERE id = ?))
                    WHERE id = ?
                    """,
                    (duplicate_id, survivor_id),
                )
                self.connection.execute(
                    "UPDATE cats SET merged_into_cat_id = ? WHERE id = ?",
                    (survivor_id, duplicate_id),
                )

    def sync_alerts(self, desired: list[dict[str, Any]], resolved_at: str) -> None:
        """Make open alerts equal a fixed-rule result, with one row per rule key."""
        wanted: dict[tuple[str | None, int | None, str], dict[str, Any]] = {}
        for item in desired:
            if item["kind"] not in ALERT_KINDS:
                raise ValueError(f"unsupported alert kind: {item['kind']}")
            if item["severity"] not in {"urgent", "high", "normal"}:
                raise ValueError(f"unsupported alert severity: {item['severity']}")
            if item.get("colony_id") is not None:
                self._require_colony(item["colony_id"])
            if item.get("cat_id") is not None:
                if item.get("colony_id") is None:
                    raise ValueError("cat-specific alerts require a colony")
                self._require_cat_at_colony(item["cat_id"], item["colony_id"])
            key = (item.get("colony_id"), item.get("cat_id"), item["kind"])
            wanted[key] = item

        open_rows = self.connection.execute(
            "SELECT id, colony_id, cat_id, kind FROM alerts WHERE resolved_at IS NULL"
        ).fetchall()
        with self.connection:
            for row in open_rows:
                key = (row["colony_id"], row["cat_id"], row["kind"])
                if key not in wanted:
                    self.connection.execute(
                        "UPDATE alerts SET resolved_at = ? WHERE id = ?", (resolved_at, row["id"])
                    )
            for key, item in wanted.items():
                existing = self.connection.execute(
                    """
                    SELECT id FROM alerts
                    WHERE colony_id IS ? AND cat_id IS ? AND kind = ? AND resolved_at IS NULL
                    """,
                    key,
                ).fetchone()
                if existing:
                    self.connection.execute(
                        "UPDATE alerts SET severity = ?, text = ? WHERE id = ?",
                        (item["severity"], item["text"], existing["id"]),
                    )
                else:
                    acknowledged = self.connection.execute(
                        """
                        SELECT 1 FROM alerts
                        WHERE colony_id IS ? AND cat_id IS ? AND kind = ?
                          AND resolved_at IS NOT NULL AND resolved_at >= ?
                        LIMIT 1
                        """,
                        (*key, item.get("created_at", resolved_at)),
                    ).fetchone()
                    if acknowledged:
                        continue
                    self.connection.execute(
                        """
                        INSERT INTO alerts(colony_id, cat_id, kind, severity, text, created_at)
                        VALUES(?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.get("colony_id"),
                            item.get("cat_id"),
                            item["kind"],
                            item["severity"],
                            item["text"],
                            item.get("created_at", resolved_at),
                        ),
                    )

    def open_alerts(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT a.id, a.colony_id, COALESCE(c.name, 'All colonies') AS colony, a.cat_id,
                   cat.display_name AS cat, a.kind, a.severity, a.text, a.created_at,
                   COALESCE(
                       (SELECT p.id FROM photos p WHERE p.cat_id = a.cat_id ORDER BY p.id LIMIT 1),
                       (SELECT p.id FROM photos p JOIN cats pc ON pc.id = p.cat_id
                        WHERE pc.colony_id = a.colony_id AND pc.merged_into_cat_id IS NULL
                        ORDER BY p.id LIMIT 1)
                   ) AS photo_id
            FROM alerts a
            LEFT JOIN colonies c ON c.id = a.colony_id
            LEFT JOIN cats cat ON cat.id = a.cat_id
            WHERE a.resolved_at IS NULL
            ORDER BY CASE a.severity WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                     a.created_at, c.name, a.kind
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def colony_counts(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT c.id, c.name,
                   COUNT(cat.id) AS cats,
                   COALESCE(SUM(cat.tnr_status = 'fixed'), 0) AS fixed,
                   COALESCE(SUM(cat.tnr_status = 'needs_tnr'), 0) AS needs_tnr,
                   COALESCE(SUM(cat.health = 'needs_vet'), 0) AS needs_vet,
                   (SELECT e.at FROM events e
                    WHERE e.colony_id = c.id AND e.kind = 'fed'
                    ORDER BY e.at DESC LIMIT 1) AS last_fed_at,
                   (SELECT v.name FROM events e JOIN volunteers v ON v.id = e.volunteer_id
                    WHERE e.colony_id = c.id AND e.kind = 'fed'
                    ORDER BY e.at DESC LIMIT 1) AS last_fed_by
            FROM colonies c
            LEFT JOIN cats cat ON cat.colony_id = c.id AND cat.status = 'active'
                              AND cat.merged_into_cat_id IS NULL
            GROUP BY c.id, c.name
            ORDER BY c.name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def open_suggestions(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT s.id, s.kind, s.strength, s.reason, s.new_status, s.created_at,
                   s.photo_id, s.cat_id, s.candidate_cat_id, s.feature_verdicts_json,
                   candidate.display_name AS candidate, target.display_name AS target,
                   COALESCE(candidate.colony_id, target.colony_id) AS colony_id,
                   c.name AS colony,
                   (SELECT rp.id FROM photos rp WHERE rp.cat_id = s.candidate_cat_id
                    ORDER BY rp.id LIMIT 1) AS candidate_photo_id,
                   (SELECT tp.id FROM photos tp WHERE tp.cat_id = s.cat_id
                    ORDER BY tp.id LIMIT 1) AS target_photo_id
            FROM suggestions s
            LEFT JOIN cats candidate ON candidate.id = s.candidate_cat_id
            LEFT JOIN cats target ON target.id = s.cat_id
            LEFT JOIN colonies c ON c.id = COALESCE(candidate.colony_id, target.colony_id)
            WHERE s.decided IS NULL
            ORDER BY s.id
            """
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["feature_verdicts"] = json.loads(item.pop("feature_verdicts_json"))
            result.append(item)
        return result

    def list_volunteers(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, name, phone, role FROM volunteers ORDER BY name"
        ).fetchall()
        return [dict(row) for row in rows]

    def colony_detail(self, colony_id: str) -> dict[str, Any]:
        self._require_colony(colony_id)
        colony = self.connection.execute(
            "SELECT id, name, lat, lng, notes FROM colonies WHERE id = ?", (colony_id,)
        ).fetchone()
        counts = next(item for item in self.colony_counts() if item["id"] == colony_id)
        feeders = self.connection.execute(
            """
            SELECT v.id, v.name, v.phone, v.role
            FROM colony_feeders cf JOIN volunteers v ON v.id = cf.volunteer_id
            WHERE cf.colony_id = ? ORDER BY v.name
            """,
            (colony_id,),
        ).fetchall()
        feedings = self.connection.execute(
            """
            SELECT e.id, e.at, e.detail, v.id AS volunteer_id, v.name AS volunteer
            FROM events e JOIN volunteers v ON v.id = e.volunteer_id
            WHERE e.colony_id = ? AND e.kind = 'fed'
            ORDER BY e.at DESC LIMIT 20
            """,
            (colony_id,),
        ).fetchall()
        cats = self.connection.execute(
            """
            SELECT cat.id, cat.display_name, cat.reported_name, cat.tnr_status, cat.health,
                   cat.health_note, cat.pregnant, cat.status, cat.first_seen, cat.last_seen,
                   (SELECT p.id FROM photos p WHERE p.cat_id = cat.id ORDER BY p.id LIMIT 1)
                       AS photo_id,
                   (SELECT COUNT(*) FROM suggestions s
                    WHERE s.kind = 'same_cat' AND s.candidate_cat_id = cat.id
                      AND s.decided IS NULL) AS unconfirmed_sightings
            FROM cats cat
            WHERE cat.colony_id = ? AND cat.status = 'active'
              AND cat.merged_into_cat_id IS NULL
            ORDER BY COALESCE(cat.reported_name, cat.display_name), cat.id
            """,
            (colony_id,),
        ).fetchall()
        return {
            **dict(colony),
            **counts,
            "feeders": [dict(row) for row in feeders],
            "feeding_log": [dict(row) for row in feedings],
            "cats_list": [dict(row) for row in cats],
        }

    def cat_detail(self, cat_id: int) -> dict[str, Any]:
        cat = self.connection.execute(
            """
            SELECT cat.*, c.name AS colony
            FROM cats cat JOIN colonies c ON c.id = cat.colony_id
            WHERE cat.id = ? AND cat.merged_into_cat_id IS NULL
            """,
            (cat_id,),
        ).fetchone()
        if cat is None:
            raise ValueError(f"unknown cat: {cat_id}")
        photos = self.connection.execute(
            """
            SELECT p.id, r.sent_at, v.name AS volunteer, 1 AS confirmed
            FROM photos p JOIN reports r ON r.id = p.report_id
            JOIN volunteers v ON v.id = r.volunteer_id
            WHERE p.cat_id = ?
            UNION ALL
            SELECT p.id, r.sent_at, v.name AS volunteer, 0 AS confirmed
            FROM suggestions s JOIN photos p ON p.id = s.photo_id
            JOIN reports r ON r.id = p.report_id JOIN volunteers v ON v.id = r.volunteer_id
            WHERE s.kind = 'same_cat' AND s.candidate_cat_id = ? AND s.decided IS NULL
            ORDER BY sent_at DESC
            """,
            (cat_id, cat_id),
        ).fetchall()
        history = self.connection.execute(
            """
            SELECT e.id, e.kind, e.detail, e.at, v.name AS volunteer
            FROM events e JOIN volunteers v ON v.id = e.volunteer_id
            WHERE e.cat_id = ? ORDER BY e.at DESC, e.id DESC LIMIT 50
            """,
            (cat_id,),
        ).fetchall()
        item = dict(cat)
        item["description"] = json.loads(item.pop("description_json"))
        item["photos"] = [dict(row) for row in photos]
        item["history"] = [dict(row) for row in history]
        return item

    def resolve_alert(self, alert_id: int, resolved_at: str) -> None:
        row = self.connection.execute(
            "SELECT id FROM alerts WHERE id = ? AND resolved_at IS NULL", (alert_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown open alert: {alert_id}")
        with self.connection:
            self.connection.execute(
                "UPDATE alerts SET resolved_at = ? WHERE id = ?", (resolved_at, alert_id)
            )

    def _insert_event(
        self,
        colony_id: str,
        cat_id: int | None,
        report_id: int | None,
        kind: str,
        detail: str,
        at: str,
        volunteer_id: str,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO events(colony_id, cat_id, report_id, kind, detail, at, volunteer_id)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (colony_id, cat_id, report_id, kind, detail, at, volunteer_id),
        )
        return int(cursor.lastrowid)

    def _require_colony(self, colony_id: str) -> None:
        if self.connection.execute(
            "SELECT 1 FROM colonies WHERE id = ?", (colony_id,)
        ).fetchone() is None:
            raise ValueError(f"unknown colony: {colony_id}")

    def _require_volunteer(self, volunteer_id: str) -> None:
        if self.connection.execute(
            "SELECT 1 FROM volunteers WHERE id = ?", (volunteer_id,)
        ).fetchone() is None:
            raise ValueError(f"unknown volunteer: {volunteer_id}")

    def _require_cat_at_colony(self, cat_id: int, colony_id: str) -> None:
        if self.connection.execute(
            """
            SELECT 1 FROM cats
            WHERE id = ? AND colony_id = ? AND merged_into_cat_id IS NULL
            """,
            (cat_id, colony_id),
        ).fetchone() is None:
            raise ValueError(f"cat {cat_id} does not belong to colony {colony_id}")

    @staticmethod
    def _display_name(cat: dict[str, Any]) -> str:
        coat = str(cat.get("coat_color", "unclear")).replace("_", " ")
        pattern = str(cat.get("pattern", "unclear")).replace("_", " ")
        base = f"{coat} {pattern}" if pattern not in {"unclear", "other"} else f"{coat} cat"
        marking = next(iter(cat.get("markings", [])), "")
        return f"{base}, {marking}".capitalize() if marking else base.capitalize()

    def _reported_name_hint(self, photo: dict[str, Any], colony_id: str) -> str | None:
        stem = Path(photo["path"]).stem
        filename_hint = re.sub(r"[-_]\d+$", "", stem).replace("_", " ").strip()
        if not filename_hint or filename_hint.casefold().startswith("img "):
            return None
        known = self.connection.execute(
            """
            SELECT reported_name FROM cats
            WHERE colony_id = ? AND LOWER(reported_name) = LOWER(?)
              AND status = 'active' AND merged_into_cat_id IS NULL
            ORDER BY id LIMIT 1
            """,
            (colony_id, filename_hint),
        ).fetchone()
        if known:
            return str(known["reported_name"])
        report = self.connection.execute(
            "SELECT text FROM reports WHERE id = ?", (photo["report_id"],)
        ).fetchone()
        if report and re.search(
            rf"(?<!\w){re.escape(filename_hint)}(?!\w)", str(report["text"]), re.IGNORECASE
        ):
            return filename_hint.title()
        return None
