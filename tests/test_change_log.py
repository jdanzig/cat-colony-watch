"""Assert local change-log persistence and replay into a rebuilt database."""

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.change_log import ChangeLog
from app.ai_cache import AICache
from app.database import Database
from app.main import _apply_change


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "changes.json"
    log = ChangeLog(url="", token="", local_path=path)
    change = {
        "id": "test-change",
        "type": "feeding_report",
        "created_at": "2026-11-07T12:00:00+00:00",
        "data": {
            "colony_id": "yard",
            "volunteer_id": "feeder",
            "at": "2026-11-07T12:00:00+00:00",
        },
    }
    log.append(change)
    assert ChangeLog(url="", token="", local_path=path).load() == [change]
    log.store_photo("abc123", b"photo bytes")
    assert log.load_photo("abc123") == b"photo bytes"
    assert log.add_api_spend("2026-11-07", 0.0123) == 0.0123
    assert log.api_spend("2026-11-07") == 0.0123

    photo_change = {
        "id": "photo-change",
        "type": "live_report",
        "created_at": "2026-11-07T13:00:00+00:00",
        "data": {"photo_hash": "abc123"},
    }
    log.append(photo_change)
    bundle = log.export_bundle()
    assert bundle["format"] == "cat-colony-watch-backup-v1"
    assert bundle["photos"] and len(bundle["changes"]) == 2
    restore_path = Path(directory) / "restored.json"
    restored = ChangeLog(url="", token="", local_path=restore_path)
    restored.restore_bundle(bundle)
    assert restored.load() == [change, photo_change]
    assert restored.load_photo("abc123") == b"photo bytes"
    try:
        restored.restore_bundle(bundle)
        raise AssertionError("restore should refuse a non-empty log")
    except ValueError as error:
        assert "not empty" in str(error)
    restored.delete_photo("abc123")
    assert not (restore_path.parent / "live_photos" / "abc123.jpg").exists()

    db = Database()
    db.connection.execute(
        "INSERT INTO colonies(id, name, lat, lng, notes) VALUES('yard', 'Yard', 25.8, -80.2, '')"
    )
    db.connection.execute(
        """
        INSERT INTO volunteers(id, name, phone, role)
        VALUES('feeder', 'Demo Feeder', '305-555-0101', 'feeder')
        """
    )
    cache = AICache(Path(directory) / "cache.json", "test-model")
    for item in [change]:
        _apply_change(db, cache, log, item)
    last_fed = db.colony_counts()[0]
    assert last_fed["last_fed_at"] == "2026-11-07T12:00:00+00:00"
    assert last_fed["last_fed_by"] == "Demo Feeder"

    log.clear()
    assert log.load() == []
    assert not (path.parent / "live_photos" / "abc123.jpg").exists()
    assert log.api_spend("2026-11-07") == 0.0123

print("change-log persistence and replay checks passed")
