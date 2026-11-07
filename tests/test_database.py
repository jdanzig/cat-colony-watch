"""Assert the counting rule and recorded-human-decision invariants."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Database


def description(color="orange", pattern="tabby"):
    return {
        "cat_count": 1,
        "cats": [
            {
                "box": [0.1, 0.1, 0.9, 0.9],
                "view": "front",
                "coat_color": color,
                "pattern": pattern,
                "markings": ["white chin"],
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
    "INSERT INTO colonies(id, name, lat, lng, notes) VALUES('laundromat', 'Laundromat', 25.8, -80.2, '')"
)
db.connection.executemany(
    "INSERT INTO volunteers(id, name, phone, role) VALUES(?, ?, ?, ?)",
    [
        ("marta", "Marta Ruiz", "305-555-0101", "feeder"),
        ("admin", "Beatriz Cruz", "305-555-0108", "admin"),
    ],
)

first_report = db.add_report(
    {
        "sent_at": "2026-11-01T07:00:00",
        "sender": "Marta Ruiz",
        "kind": "message",
        "text": "Orange cat",
        "lat": None,
        "lng": None,
        "source": "import",
        "raw": "first",
    }
)
first_photo = db.add_photo(first_report, "first.jpg", 0, description())
cat_id = db.create_cat_for_photo(first_photo, "laundromat")["cat_id"]
assert db.colony_counts()[0]["cats"] == 1

second_report = db.add_report(
    {
        "sent_at": "2026-11-02T07:00:00",
        "sender": "Marta Ruiz",
        "kind": "message",
        "text": "Orange cat again",
        "lat": None,
        "lng": None,
        "source": "import",
        "raw": "second",
    }
)
second_photo = db.add_photo(second_report, "second.jpg", 0, description())
match = db.create_same_cat_suggestion(
    second_photo,
    cat_id,
    "strong",
    [{"candidate": str(cat_id), "matching_specific_markings": ["white chin"]}],
    "same white chin",
)
assert db.colony_counts()[0]["cats"] == 1
assert db.photo(second_photo)["cat_id"] is None
assert db.open_suggestions()[0]["kind"] == "same_cat"

db.confirm_suggestion(match["suggestion_id"], "admin", "confirmed")
assert db.photo(second_photo)["cat_id"] == cat_id
decision = db.connection.execute(
    "SELECT decided, decided_by, decided_at FROM suggestions WHERE id = ?",
    (match["suggestion_id"],),
).fetchone()
assert decision["decided"] == "confirmed"
assert decision["decided_by"] == "admin"
assert decision["decided_at"]

status = db.suggest_status(cat_id, "adopted", "A family reported an adoption")
assert db.connection.execute("SELECT status FROM cats WHERE id = ?", (cat_id,)).fetchone()[0] == "active"
db.confirm_suggestion(status["suggestion_id"], "admin", "confirmed")
assert db.connection.execute("SELECT status FROM cats WHERE id = ?", (cat_id,)).fetchone()[0] == "adopted"
assert db.colony_counts()[0]["cats"] == 0

print("database counting and human-decision checks passed")
