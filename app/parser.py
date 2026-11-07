"""Parse an iOS WhatsApp text export into import-ready reports."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit


MESSAGE_RE = re.compile(
    r"^\[(?P<timestamp>[^]]+)]\s(?P<sender>[^:]+):\s?(?P<text>.*)$"
)
TIMESTAMPED_LINE_RE = re.compile(r"^\[[^]]+]\s")
ATTACHMENT_RE = re.compile(r"<attached:\s*([^>]+)>", re.IGNORECASE)
GOOGLE_MAPS_URL_RE = re.compile(
    r"https?://(?:"
    r"(?:www\.)?google\.com/maps|"
    r"maps\.google\.com|"
    r"maps\.app\.goo\.gl|"
    r"goo\.gl/maps"
    r")[^\s<>]*",
    re.IGNORECASE,
)
COORDINATES_RE = re.compile(r"(-?\d{1,2}(?:\.\d+)?),\s*(-?\d{1,3}(?:\.\d+)?)")
TIMESTAMP_FORMATS = (
    "%m/%d/%y, %I:%M:%S %p",
    "%m/%d/%y, %I:%M %p",
    "%m/%d/%Y, %I:%M:%S %p",
    "%m/%d/%Y, %I:%M %p",
)


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("\u202f", " ").replace("\u00a0", " ").replace("\u200e", "")
    for timestamp_format in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(normalized, timestamp_format)
        except ValueError:
            continue
    raise ValueError(f"unsupported WhatsApp timestamp: {value!r}")


def _coordinates(value: str) -> tuple[float | None, float | None]:
    match = COORDINATES_RE.search(unquote(value))
    if not match:
        return None, None
    lat, lng = (float(part) for part in match.groups())
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None
    return lat, lng


def _location(text: str) -> tuple[str | None, float | None, float | None]:
    match = GOOGLE_MAPS_URL_RE.search(text)
    if not match:
        return None, None, None

    url = match.group(0)
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    for key in ("q", "query", "ll", "destination"):
        for value in query.get(key, []):
            lat, lng = _coordinates(value)
            if lat is not None:
                return url, lat, lng

    lat, lng = _coordinates(parsed.path)
    return url, lat, lng


def parse_chat(text: str) -> list[dict[str, Any]]:
    """Return reports from an iOS WhatsApp export's `_chat.txt` contents."""
    reports: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def finish_current() -> None:
        nonlocal current
        if current is None:
            return
        message_text = "\n".join(current.pop("text_lines")).strip()
        raw = "\n".join(current.pop("raw_lines"))
        location_url, lat, lng = _location(message_text)
        reports.append(
            {
                **current,
                "text": message_text,
                "lat": lat,
                "lng": lng,
                "location_url": location_url,
                "raw": raw,
            }
        )
        current = None

    for raw_line in text.splitlines():
        line = raw_line.lstrip("\ufeff\u200e")
        message = MESSAGE_RE.match(line)
        if message:
            finish_current()
            body = message.group("text")
            attachments = ATTACHMENT_RE.findall(body)
            body = ATTACHMENT_RE.sub("", body).strip()
            current = {
                "sent_at": _parse_timestamp(message.group("timestamp")).isoformat(),
                "sender": message.group("sender").strip(),
                "kind": "message",
                "source": "import",
                "attachments": attachments,
                "text_lines": [body] if body else [],
                "raw_lines": [raw_line],
            }
            continue

        if TIMESTAMPED_LINE_RE.match(line):
            # WhatsApp system messages have timestamps but no sender. They are
            # not volunteer reports and must not become part of the prior text.
            finish_current()
            continue

        if current is None:
            continue
        current["raw_lines"].append(raw_line)
        attachments = ATTACHMENT_RE.findall(line)
        if attachments:
            current["attachments"].extend(attachments)
            line = ATTACHMENT_RE.sub("", line).strip()
        if line:
            current["text_lines"].append(line)

    finish_current()
    return reports


def parse_chat_file(path: str | Path) -> list[dict[str, Any]]:
    """Read and parse a WhatsApp `_chat.txt` file."""
    return parse_chat(Path(path).read_text(encoding="utf-8-sig"))
