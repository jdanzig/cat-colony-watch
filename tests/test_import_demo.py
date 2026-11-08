"""Assert that demo-day shifting preserves the imported timeline."""

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.import_demo import shift_demo_reports_to_today


reports = [
    {"sent_at": "2026-10-25T07:06:00", "text": "first"},
    {"sent_at": "2026-11-07T09:44:00", "text": "newest"},
]
original_interval = datetime.fromisoformat(reports[1]["sent_at"]) - datetime.fromisoformat(
    reports[0]["sent_at"]
)
shifted = shift_demo_reports_to_today(reports, date(2030, 4, 12))

assert reports[0]["sent_at"] == "2026-10-25T07:06:00"
assert shifted[0]["cache_sent_at"] == reports[0]["sent_at"]
assert shifted[1]["cache_sent_at"] == reports[1]["sent_at"]
assert datetime.fromisoformat(shifted[1]["sent_at"]).date() == date(2030, 4, 12)
assert datetime.fromisoformat(shifted[1]["sent_at"]) - datetime.fromisoformat(
    shifted[0]["sent_at"]
) == original_interval

print("demo timestamp shifting checks passed")
