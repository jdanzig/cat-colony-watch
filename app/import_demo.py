"""Build a SQLite demo database from the committed chat and AI cache."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from app.ai_cache import AICache, file_hash
from app.database import Database
from app.identification import DESCRIPTION_PROMPT_VERSION, MATCH_PROMPT_VERSION, describe_photo
from app.message_agent import (
    AGENT_PROMPT_VERSION,
    LEGACY_AGENT_PROMPT_VERSION,
    ImportContext,
    build_agent,
    process_report,
)
from app.parser import parse_chat_file
from app.rules import apply_named_cat_facts, rebuild_alerts


def shift_demo_reports_to_today(
    reports: list[dict[str, Any]], today: date | None = None
) -> list[dict[str, Any]]:
    """Move the whole demo timeline so its newest message falls on demo day."""
    if not reports:
        return reports
    demo_day = today or datetime.now(ZoneInfo("America/New_York")).date()
    newest = max(datetime.fromisoformat(report["sent_at"]) for report in reports)
    offset = demo_day - newest.date()
    shifted = []
    for report in reports:
        item = dict(report)
        item["cache_sent_at"] = report["sent_at"]
        item["sent_at"] = (
            datetime.fromisoformat(report["sent_at"]) + timedelta(days=offset.days)
        ).isoformat()
        shifted.append(item)
    return shifted


def import_demo(
    data_dir: str | Path,
    db_path: str | Path,
    *,
    limit: int | None = None,
    model: str | None = None,
    max_spend_usd: float = 3.0,
    allow_api: bool = True,
) -> tuple[Database, AICache]:
    data_dir = Path(data_dir)
    load_dotenv(Path(".env"))
    selected_model = model or os.getenv("OPENAI_MODEL")
    if not selected_model:
        raise RuntimeError("OPENAI_MODEL is required")
    if allow_api and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required")

    cache = AICache(data_dir / "ai_cache.json", selected_model, max_spend_usd)
    prompt_versions = {
        "description": DESCRIPTION_PROMPT_VERSION,
        "match": MATCH_PROMPT_VERSION,
        "message_agent": AGENT_PROMPT_VERSION,
        "message_agent_cache_compat": LEGACY_AGENT_PROMPT_VERSION,
    }
    if cache.data.get("prompt_versions") != prompt_versions:
        cache.data["prompt_versions"] = prompt_versions
        cache.save()

    db = Database(db_path, reset=True)
    db.seed_demo(data_dir)
    reports = shift_demo_reports_to_today(parse_chat_file(data_dir / "_chat.txt"))
    if limit is not None:
        reports = reports[:limit]
    agent = build_agent(selected_model)

    for number, report in enumerate(reports, 1):
        report_id = db.add_report(report)
        photo_inputs = []
        photo_ids: set[int] = set()
        for attachment in report["attachments"]:
            photo_path = data_dir / "photos" / Path(attachment).name
            if not photo_path.is_file():
                raise FileNotFoundError(f"chat attachment is missing: {photo_path}")
            digest = file_hash(photo_path)
            description = cache.get("descriptions", digest)
            if description is None:
                if not allow_api:
                    raise RuntimeError(
                        f"photo description missing from cache while API calls are disabled: {photo_path}"
                    )
                cache.check_budget()
                description = describe_photo(
                    photo_path,
                    model=selected_model,
                    cache_dir="eval/cache",
                    cost_log="costs.log",
                )
                cache.put("descriptions", digest, description)
            for cat_index, cat in enumerate(description.get("cats", [])):
                single_description = {
                    "cat_count": 1,
                    "cats": [cat],
                    "kittens_present": description.get("kittens_present", False),
                    "photo_quality": description.get("photo_quality", "poor"),
                }
                photo_id = db.add_photo(
                    report_id, photo_path, cat_index, single_description
                )
                photo_ids.add(photo_id)
                photo_inputs.append(
                    {
                        "photo_id": photo_id,
                        "filename": attachment,
                        "observations": single_description,
                    }
                )

        volunteer_id = db.volunteer_id_for_name(report["sender"])
        report_input: dict[str, Any] = {
            "report_id": report_id,
            "sent_at": report["sent_at"],
            "volunteer": {"id": volunteer_id, "name": report["sender"]},
            "text": report["text"],
            "location": {"lat": report["lat"], "lng": report["lng"]},
            "photos": photo_inputs,
        }
        cache_report_input = {**report_input, "sent_at": report["cache_sent_at"]}
        context = ImportContext(
            db=db,
            cache=cache,
            model=selected_model,
            report_id=report_id,
            volunteer_id=volunteer_id,
            sent_at=report["sent_at"],
            photo_ids=photo_ids,
            allow_api=allow_api,
        )
        summary = process_report(
            agent, context, report_input, cache_report_input=cache_report_input
        )
        apply_named_cat_facts(db, report_id)
        unmatched = db.connection.execute(
            """
            SELECT p.id FROM photos p
            LEFT JOIN suggestions s
              ON s.photo_id = p.id AND s.kind = 'same_cat' AND s.decided IS NULL
            WHERE p.report_id = ? AND p.cat_id IS NULL AND s.id IS NULL
            """,
            (report_id,),
        ).fetchall()
        if unmatched:
            raise RuntimeError(
                f"agent did not call match_photo for report {report_id}, photo IDs "
                f"{[row['id'] for row in unmatched]}"
            )
        print(
            f"{number:>3}/{len(reports)} report {report_id}: {summary.summary} "
            f"(cache spend ${cache.spend:.4f})"
        )

    db.create_possible_duplicate_suggestions()
    rebuild_alerts(db)
    return db, cache


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/demo")
    parser.add_argument("--db", default="data/demo/cat_colony_watch.db")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-spend", type=float, default=3.0)
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()
    db, cache = import_demo(
        args.data_dir,
        args.db,
        limit=args.limit,
        max_spend_usd=args.max_spend,
        allow_api=not args.cache_only,
    )
    print(
        json.dumps(
            {
                "cache": cache.stats(),
                "colonies": db.colony_counts(),
                "alerts": db.open_alerts(),
            },
            indent=2,
        )
    )
    db.close()


if __name__ == "__main__":
    main()
