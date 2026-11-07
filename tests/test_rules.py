"""Runnable assertions for named-cat updates, duplicate review, and §8 alerts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import ALERT_KINDS, Database
from app.rules import apply_named_cat_facts, rebuild_alerts


def description(color="mixed", pattern="calico"):
    return {
        "cat_count": 1,
        "cats": [
            {
                "box": [0.1, 0.1, 0.9, 0.9],
                "view": "front",
                "coat_color": color,
                "pattern": pattern,
                "markings": ["white nose blaze"],
                "eye_color": "green",
                "tail": "long",
                "ear_tip": "none",
                "apparent_health": [],
                "looks_pregnant": False,
                "is_kitten": False,
            }
        ],
        "kittens_present": False,
        "photo_quality": "good",
    }


db = Database()
db.connection.execute(
    "INSERT INTO colonies(id, name, lat, lng, notes) VALUES('yard', 'Yard', 25.8, -80.2, '')"
)
db.connection.executemany(
    "INSERT INTO volunteers(id, name, phone, role) VALUES(?, ?, ?, ?)",
    [
        ("feeder", "Demo Feeder", "305-555-0101", "feeder"),
        ("admin", "Demo Admin", "305-555-0102", "admin"),
    ],
)


def report(at, text):
    return db.add_report(
        {
            "sent_at": at,
            "sender": "Demo Feeder",
            "kind": "message",
            "text": text,
            "lat": None,
            "lng": None,
            "source": "import",
            "raw": text,
        }
    )


def named_cat(name, at):
    report_id = report(at, f"Yard fed. {name} was seen.")
    photo_id = db.add_photo(report_id, f"{name.lower()}-01.jpg", 0, description())
    return db.create_cat_for_photo(photo_id, "yard")["cat_id"]


mariposa = named_cat("Mariposa", "2026-10-25T08:00:00")
mosaic = named_cat("Mosaic", "2026-10-25T08:10:00")
canela = named_cat("Canela", "2026-10-25T08:20:00")
nube_one = named_cat("Nube", "2026-10-25T08:30:00")

pregnant_report = report("2026-10-30T08:00:00", "Mariposa está preñada.")
db.record_event(
    "health",
    "yard",
    None,
    "Mariposa is visibly pregnant.",
    pregnant_report,
    "2026-10-30T08:00:00",
    "feeder",
)
assert apply_named_cat_facts(db, pregnant_report) == 1

vet_report = report("2026-10-30T08:10:00", "Mosaic is limping and needs a vet.")
db.record_event(
    "health",
    "yard",
    None,
    "Mosaic is limping and needs a vet.",
    vet_report,
    "2026-10-30T08:10:00",
    "feeder",
)
assert apply_named_cat_facts(db, vet_report) == 1

fixed_report = report("2026-10-30T08:20:00", "Canela: fixed today at the clinic.")
db.record_event(
    "tnr_done",
    "yard",
    None,
    "Canela was fixed today at the clinic.",
    fixed_report,
    "2026-10-30T08:20:00",
    "feeder",
)
assert apply_named_cat_facts(db, fixed_report) == 1

states = {
    row["reported_name"]: row
    for row in db.connection.execute(
        "SELECT reported_name, pregnant, health, tnr_status FROM cats WHERE reported_name IS NOT NULL"
    )
}
assert states["Mariposa"]["pregnant"] == 1
assert states["Mosaic"]["health"] == "needs_vet"
assert states["Canela"]["tnr_status"] == "fixed"

# The filename is only a name hint. It creates a review suggestion, not an
# automatic merge, when a second Nube record appears.
second_nube_report = report("2026-10-28T08:30:00", "The long-haired cat was here again.")
second_nube_photo = db.add_photo(
    second_nube_report, "nube-02.jpg", 0, description("cream", "colorpoint")
)
nube_two = db.create_cat_for_photo(second_nube_photo, "yard")["cat_id"]
assert nube_two != nube_one
assert db.create_possible_duplicate_suggestions() == 1
duplicate = db.connection.execute(
    "SELECT * FROM suggestions WHERE kind = 'possible_duplicate' AND decided IS NULL"
).fetchone()
assert duplicate["cat_id"] == nube_two
assert duplicate["candidate_cat_id"] == nube_one
assert db.connection.execute(
    "SELECT COUNT(*) FROM cats WHERE reported_name = 'Nube' AND merged_into_cat_id IS NULL"
).fetchone()[0] == 2

feeding_report = report("2026-11-01T07:00:00", "Yard fed.")
db.log_feeding("yard", "feeder", "2026-11-01T07:00:00", feeding_report)
stop_report = report("2026-11-04T12:00:00", "I am moving away and cannot keep feeding Yard.")
db.record_event(
    "need",
    "yard",
    None,
    "I am moving away and cannot keep feeding Yard.",
    stop_report,
    "2026-11-04T12:00:00",
    "feeder",
)
kitten_report = report("2026-11-05T08:00:00", "Kittens found at Yard.")
db.record_event(
    "kittens",
    "yard",
    None,
    "Kittens found at Yard.",
    kitten_report,
    "2026-11-05T08:00:00",
    "feeder",
)

alerts = rebuild_alerts(db, "2026-11-07T09:00:00")
assert {alert["kind"] for alert in alerts} <= ALERT_KINDS
assert len({(a["colony_id"], a["cat_id"], a["kind"]) for a in alerts}) == len(alerts)
for required in ("pregnant", "needs_vet", "kittens", "lost_feeder"):
    matching = [alert for alert in alerts if alert["kind"] == required]
    assert matching and all(alert["severity"] == "urgent" for alert in matching)
assert not any(
    alert["kind"] == "needs_tnr" and alert["cat_id"] == canela for alert in alerts
)
rebuild_alerts(db, "2026-11-07T09:00:00")
assert len(db.open_alerts()) == len(alerts)

# Only this recorded human decision collapses the two records in counts.
before = db.colony_counts()[0]["cats"]
db.confirm_suggestion(duplicate["id"], "admin", "confirmed")
assert db.colony_counts()[0]["cats"] == before - 1
decision = db.connection.execute(
    "SELECT decided, decided_by, decided_at FROM suggestions WHERE id = ?", (duplicate["id"],)
).fetchone()
assert decision["decided"] == "confirmed"
assert decision["decided_by"] == "admin"
assert decision["decided_at"]

print("named-cat, duplicate, alert, and counting rule checks passed")
