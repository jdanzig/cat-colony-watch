"""Append-only live change log in Upstash Redis, with a local JSON fallback."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx


REDIS_CHANGES_KEY = "ccw:changes"


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
        if self.url:
            self._redis(["DEL", REDIS_CHANGES_KEY])
            return
        self._write_local([])

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
