"""Append-only live change log in Upstash Redis, with a local JSON fallback."""

from __future__ import annotations

import json
import os
import time
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


REDIS_CHANGES_KEY = "ccw:changes"
REDIS_PHOTO_PREFIX = "ccw:photo:"
REDIS_SPEND_PREFIX = "ccw:api-spend:"


class ChangeLog:
    def __init__(
        self,
        *,
        url: str | None = None,
        token: str | None = None,
        local_path: str | Path = "data/local_changes.json",
    ):
        self.url = url if url is not None else os.getenv("UPSTASH_REDIS_REST_URL")
        self.token = token if token is not None else os.getenv("UPSTASH_REDIS_REST_TOKEN")
        if bool(self.url) != bool(self.token):
            raise RuntimeError("both Upstash REST variables must be set together")
        self.local_path = Path(local_path)

    @property
    def mode(self) -> str:
        return "upstash" if self.url else "local"

    def load(self) -> list[dict[str, Any]]:
        if not self.url:
            if not self.local_path.exists():
                return []
            return json.loads(self.local_path.read_text())
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                rows = self._redis(["LRANGE", REDIS_CHANGES_KEY, 0, -1]) or []
                return [json.loads(row) for row in rows]
            except Exception as error:
                last_error = error
                time.sleep(attempt + 1)
        raise RuntimeError("Upstash change log is unreachable; refusing an empty rebuild") from last_error

    def append(self, change: dict[str, Any]) -> None:
        encoded = json.dumps(change, separators=(",", ":"), sort_keys=True)
        if self.url:
            self._redis(["RPUSH", REDIS_CHANGES_KEY, encoded])
            return
        changes = self.load()
        changes.append(change)
        self._write_local(changes)

    def clear(self) -> None:
        """Remove every live change and live photo, restoring the committed demo."""
        if self.url:
            cursor: str | int = 0
            photo_keys: list[str] = []
            while True:
                result = self._redis(
                    ["SCAN", cursor, "MATCH", f"{REDIS_PHOTO_PREFIX}*", "COUNT", 100]
                )
                cursor, keys = result
                photo_keys.extend(keys)
                if str(cursor) == "0":
                    break
            for start in range(0, len(photo_keys), 100):
                self._redis(["DEL", *photo_keys[start : start + 100]])
            self._redis(["DEL", REDIS_CHANGES_KEY])
            return
        self._write_local([])
        photo_dir = self.local_path.parent / "live_photos"
        if photo_dir.is_dir():
            for path in photo_dir.glob("*.jpg"):
                path.unlink()

    def api_spend(self, day: str) -> float:
        if self.url:
            return float(self._redis(["GET", f"{REDIS_SPEND_PREFIX}{day}"]) or 0.0)
        path = self._local_spend_path()
        values = json.loads(path.read_text()) if path.exists() else {}
        return float(values.get(day, 0.0))

    def add_api_spend(self, day: str, amount: float) -> float:
        amount = round(float(amount), 8)
        if amount < 0:
            raise ValueError("API spend cannot be negative")
        if self.url:
            return float(
                self._redis(["INCRBYFLOAT", f"{REDIS_SPEND_PREFIX}{day}", amount])
            )
        path = self._local_spend_path()
        values = json.loads(path.read_text()) if path.exists() else {}
        values[day] = round(float(values.get(day, 0.0)) + amount, 8)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(values, indent=2, sort_keys=True) + "\n")
        temporary.replace(path)
        return float(values[day])

    def store_photo(self, digest: str, content: bytes) -> None:
        """Persist one already-resized live photo by its content hash."""
        if self.url:
            self._redis(["SET", f"{REDIS_PHOTO_PREFIX}{digest}", b64encode(content).decode()])
            return
        path = self._local_photo_path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)

    def load_photo(self, digest: str) -> bytes:
        if self.url:
            encoded = self._redis(["GET", f"{REDIS_PHOTO_PREFIX}{digest}"])
            if not encoded:
                raise RuntimeError(f"live photo is missing from Upstash: {digest}")
            return b64decode(encoded)
        path = self._local_photo_path(digest)
        if not path.exists():
            raise RuntimeError(f"live photo is missing locally: {digest}")
        return path.read_bytes()

    def delete_photo(self, digest: str) -> None:
        """Remove one unreferenced live photo after a failed report."""
        if self.url:
            self._redis(["DEL", f"{REDIS_PHOTO_PREFIX}{digest}"])
            return
        self._local_photo_path(digest).unlink(missing_ok=True)

    def export_bundle(self) -> dict[str, Any]:
        """Export replay data and referenced photos into one private backup object."""
        changes = self.load()
        digests = sorted({
            change.get("data", {}).get("photo_hash")
            for change in changes
            if change.get("data", {}).get("photo_hash")
        })
        return {
            "format": "cat-colony-watch-backup-v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "changes": changes,
            "photos": {
                digest: b64encode(self.load_photo(digest)).decode()
                for digest in digests
            },
        }

    def restore_bundle(self, bundle: dict[str, Any], *, replace: bool = False) -> None:
        """Restore a validated backup; replacing existing state must be explicit."""
        if bundle.get("format") != "cat-colony-watch-backup-v1":
            raise ValueError("unsupported backup format")
        changes = bundle.get("changes")
        photos = bundle.get("photos")
        if not isinstance(changes, list) or not isinstance(photos, dict):
            raise ValueError("backup changes and photos are required")
        ids = [item.get("id") for item in changes if isinstance(item, dict)]
        if len(ids) != len(changes) or any(not item for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("backup has missing or duplicate change ids")
        digests = {
            change.get("data", {}).get("photo_hash")
            for change in changes
            if change.get("data", {}).get("photo_hash")
        }
        if not digests.issubset(photos):
            raise ValueError("backup is missing one or more live photos")
        if self.load() and not replace:
            raise ValueError("change log is not empty; pass replace=True to overwrite it")
        decoded = {}
        try:
            decoded = {digest: b64decode(photos[digest], validate=True) for digest in digests}
        except (ValueError, TypeError) as error:
            raise ValueError("backup contains an invalid photo") from error
        if replace:
            self.clear()
        for digest, content in decoded.items():
            self.store_photo(digest, content)
        for change in changes:
            self.append(change)

    def _redis(self, command: list[Any]) -> Any:
        response = httpx.post(
            str(self.url),
            headers={"Authorization": f"Bearer {self.token}"},
            json=command,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"Upstash error: {payload['error']}")
        return payload.get("result")

    def _write_local(self, changes: list[dict[str, Any]]) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.local_path.with_suffix(self.local_path.suffix + ".tmp")
        temporary.write_text(json.dumps(changes, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.local_path)

    def _local_photo_path(self, digest: str) -> Path:
        return self.local_path.parent / "live_photos" / f"{digest}.jpg"

    def _local_spend_path(self) -> Path:
        return self.local_path.with_name(f"{self.local_path.stem}_api_spend.json")
