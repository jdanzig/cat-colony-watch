"""Deterministic cat updates, alerts, and duplicate suggestions.

The agent records observations and events. These rules make the decisions that
must be stable and testable: named-cat facts, alert kinds/severity, and whether
two existing records should be offered to a person as a possible duplicate.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.database import Database


PREGNANCY_WORDS = re.compile(r"\b(pregnan\w*|preñad\w*)\b", re.IGNORECASE)
NEEDS_VET_WORDS = re.compile(
    r"\b(limp\w*|injur\w*|sick\w*|wound\w*|coje\w*)\b|needs? (?:a )?vet|vet appointment",
    re.IGNORECASE,
)
STOPPING_WORDS = re.compile(
    r"cannot (?:keep|continue) feeding|can['’]t (?:keep|continue) feeding|moving away|"
    r"no feeder|need(?:s|ed)? (?:another|a replacement) feeder",
    re.IGNORECASE,
)
FOOD_SHORTAGE_WORDS = re.compile(
    r"almost out of food|out of food|bowls? (?:are )?empty|did not have food|"
    r"need\w* (?:a feeder with )?food|food (?:is )?needed",
    re.IGNORECASE,
)
FOOD_RESTORED_WORDS = re.compile(
    r"food delivery arrived|\bstocked\b|sufficient food|suficiente comida",
    re.IGNORECASE,
)


def apply_named_cat_facts(db: Database, report_id: int) -> int:
    """Apply health/TNR/pregnancy facts to one uniquely named known cat.

    A reported name is enough to update these reversible care fields. It is
    never used here to merge photos or to change adopted/missing/deceased.
    """
    report = db.connection.execute(
        "SELECT text FROM reports WHERE id = ?", (report_id,)
    ).fetchone()
    if report is None:
        raise ValueError(f"unknown report: {report_id}")
    events = db.connection.execute(
        "SELECT id, colony_id, kind, detail FROM events WHERE report_id = ? ORDER BY id",
        (report_id,),
    ).fetchall()
    updated = 0
    for event in events:
        if event["kind"] not in {"tnr_done", "health"}:
            continue
        cats = db.connection.execute(
            """
            SELECT id, reported_name FROM cats
            WHERE colony_id = ? AND status = 'active' AND merged_into_cat_id IS NULL
              AND reported_name IS NOT NULL
            ORDER BY id
            """,
            (event["colony_id"],),
        ).fetchall()
        evidence = f"{report['text']} {event['detail']}"
        named = [
            cat
            for cat in cats
            if re.search(
                rf"(?<!\w){re.escape(cat['reported_name'])}(?!\w)",
                evidence,
                re.IGNORECASE,
            )
        ]
        unique_ids = {int(cat["id"]) for cat in named}
        if len(unique_ids) != 1:
            continue
        cat_id = unique_ids.pop()
        changes: dict[str, object] = {}
        if event["kind"] == "tnr_done":
            changes["tnr_status"] = "fixed"
        if event["kind"] == "health" and PREGNANCY_WORDS.search(evidence):
            changes["pregnant"] = True
        if event["kind"] == "health" and NEEDS_VET_WORDS.search(evidence):
            changes["health"] = "needs_vet"
            changes["health_note"] = _clean_health_note(event["detail"])
        if not changes:
            continue
        db.update_cat(cat_id, **changes)
        with db.connection:
            db.connection.execute(
                "UPDATE events SET cat_id = ? WHERE id = ?", (cat_id, event["id"])
            )
        updated += 1
    return updated


def rebuild_alerts(db: Database, as_of: str | None = None) -> list[dict]:
    """Recompute the exact PLAN §8 alert set from database state and events."""
    if as_of is None:
        row = db.connection.execute("SELECT MAX(sent_at) AS at FROM reports").fetchone()
        if row is None or row["at"] is None:
            return []
        as_of = str(row["at"])
    now = datetime.fromisoformat(as_of)
    stale_at = now - timedelta(days=1)
    unfed_at = now - timedelta(days=2)
    colonies = {
        row["id"]: row["name"]
        for row in db.connection.execute("SELECT id, name FROM colonies").fetchall()
    }
    desired: dict[tuple[str, int | None, str], dict] = {}

    def add(
        kind: str,
        severity: str,
        colony_id: str,
        text: str,
        *,
        cat_id: int | None = None,
        created_at: str | None = None,
    ) -> None:
        key = (colony_id, cat_id, kind)
        item = {
            "kind": kind,
            "severity": severity,
            "colony_id": colony_id,
            "cat_id": cat_id,
            "text": text,
            "created_at": created_at or as_of,
        }
        current = desired.get(key)
        if current is None or item["created_at"] < current["created_at"]:
            desired[key] = item

    cats = db.connection.execute(
        """
        SELECT id, colony_id, display_name, tnr_status, health, health_note,
               pregnant, first_seen
        FROM cats
        WHERE status = 'active' AND merged_into_cat_id IS NULL
        ORDER BY id
        """
    ).fetchall()
    pregnancy_at: dict[int, str] = {}
    needs_vet_at: dict[int, str] = {}
    for event in db.connection.execute(
        "SELECT cat_id, detail, at FROM events WHERE kind = 'health' AND cat_id IS NOT NULL ORDER BY at"
    ).fetchall():
        cat_id = int(event["cat_id"])
        if PREGNANCY_WORDS.search(event["detail"]):
            pregnancy_at.setdefault(cat_id, event["at"])
        if NEEDS_VET_WORDS.search(event["detail"]):
            needs_vet_at.setdefault(cat_id, event["at"])
    for cat in cats:
        colony_name = colonies[cat["colony_id"]]
        if cat["pregnant"] and cat["tnr_status"] != "fixed":
            add(
                "pregnant",
                "urgent",
                cat["colony_id"],
                f"Pregnant cat at {colony_name}: trap within days",
                cat_id=int(cat["id"]),
                created_at=pregnancy_at.get(int(cat["id"]), cat["first_seen"]),
            )
        if cat["health"] == "needs_vet":
            note = f": {cat['health_note']}" if cat["health_note"] else ""
            add(
                "needs_vet",
                "urgent",
                cat["colony_id"],
                f"{cat['display_name']} needs a vet{note}",
                cat_id=int(cat["id"]),
                created_at=needs_vet_at.get(int(cat["id"]), cat["first_seen"]),
            )
        if cat["tnr_status"] == "needs_tnr":
            add(
                "needs_tnr",
                "normal",
                cat["colony_id"],
                f"New unfixed cat at {colony_name}: add to the TNR list",
                cat_id=int(cat["id"]),
                created_at=cat["first_seen"],
            )

    kitten_events = db.connection.execute(
        """
        SELECT colony_id, cat_id, MIN(at) AS first_at
        FROM events WHERE kind = 'kittens'
        GROUP BY colony_id, cat_id
        """
    ).fetchall()
    for event in kitten_events:
        colony_name = colonies[event["colony_id"]]
        add(
            "kittens",
            "urgent",
            event["colony_id"],
            f"New kittens at {colony_name}: check for the mother",
            cat_id=event["cat_id"],
            created_at=event["first_at"],
        )

    feeding_rows = db.connection.execute(
        """
        SELECT colony_id, MAX(at) AS last_fed_at
        FROM events WHERE kind = 'fed' GROUP BY colony_id
        """
    ).fetchall()
    stopping_rows = db.connection.execute(
        "SELECT colony_id, detail, at FROM events WHERE kind = 'need' ORDER BY at"
    ).fetchall()
    stopping: dict[str, tuple[str, str]] = {}
    for event in stopping_rows:
        if STOPPING_WORDS.search(event["detail"]):
            stopping.setdefault(event["colony_id"], (event["detail"], event["at"]))
    for feeding in feeding_rows:
        colony_id = feeding["colony_id"]
        last_fed = datetime.fromisoformat(feeding["last_fed_at"])
        stopped = stopping.get(colony_id)
        if stopped:
            add(
                "lost_feeder",
                "urgent",
                colony_id,
                f"{colonies[colony_id]} has lost its feeder: arrange coverage today",
                created_at=stopped[1],
            )
        elif last_fed <= unfed_at:
            add(
                "lost_feeder",
                "urgent",
                colony_id,
                f"{colonies[colony_id]} hasn't been fed since {feeding['last_fed_at']}",
                created_at=feeding["last_fed_at"],
            )

    supply_rows = db.connection.execute(
        """
        SELECT colony_id, detail, at FROM events
        WHERE kind IN ('need', 'status') ORDER BY at
        """
    ).fetchall()
    latest_supply: dict[str, tuple[bool, str]] = {}
    for event in supply_rows:
        if FOOD_RESTORED_WORDS.search(event["detail"]):
            latest_supply[event["colony_id"]] = (False, event["at"])
        elif FOOD_SHORTAGE_WORDS.search(event["detail"]):
            latest_supply[event["colony_id"]] = (True, event["at"])
    for colony_id, (shortage, at) in latest_supply.items():
        if shortage:
            add(
                "out_of_food",
                "high",
                colony_id,
                f"{colonies[colony_id]} is out of food",
                created_at=at,
            )

    waiting = db.connection.execute(
        """
        SELECT colony_id, COUNT(*) AS count, MIN(waiting_since) AS first_waiting
        FROM (
            SELECT candidate.colony_id AS colony_id, r.sent_at AS waiting_since
            FROM suggestions s
            JOIN photos p ON p.id = s.photo_id
            JOIN reports r ON r.id = p.report_id
            JOIN cats candidate ON candidate.id = s.candidate_cat_id
            WHERE s.kind = 'same_cat' AND s.decided IS NULL
            UNION ALL
            SELECT target.colony_id, target.first_seen
            FROM suggestions s
            JOIN cats target ON target.id = s.cat_id
            WHERE s.kind = 'possible_duplicate' AND s.decided IS NULL
        ) pending
        WHERE waiting_since <= ?
        GROUP BY colony_id
        """,
        (stale_at.isoformat(),),
    ).fetchall()
    for row in waiting:
        add(
            "stale_suggestions",
            "normal",
            row["colony_id"],
            f"{row['count']} matches waiting to be confirmed",
            created_at=row["first_waiting"],
        )

    db.sync_alerts(list(desired.values()), as_of)
    return db.open_alerts()


def _clean_health_note(detail: str) -> str:
    note = re.sub(
        r"[.;]?\s*(?:photo match|identity)\b.*$", "", detail, flags=re.IGNORECASE
    ).strip()
    return note.rstrip(".;")
