"""Agents SDK message processor and its SQLite-backed tools."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from agents import Agent, ModelSettings, RunContextWrapper, RunHooks, Runner, function_tool
from agents.items import ModelResponse
from pydantic import BaseModel

from app.ai_cache import AICache, file_hash, value_hash
from app.database import Database
from app.identification import MATCH_PROMPT_VERSION, MODEL_PRICES, match_cat


AGENT_PROMPT_VERSION = "message-agent-v1"
EventKind = Literal["fed", "sighting", "tnr_done", "health", "kittens", "need", "status"]
TNRStatus = Literal["fixed", "needs_tnr", "unknown"]
Health = Literal["ok", "needs_vet"]
NewStatus = Literal["adopted", "missing", "deceased"]
Severity = Literal["urgent", "high", "normal"]


class AgentSummary(BaseModel):
    summary: str
    colony_ids: list[str]
    needs_review: bool


@dataclass
class ImportContext:
    db: Database
    cache: AICache
    model: str
    report_id: int
    volunteer_id: str
    sent_at: str
    photo_ids: set[int]
    cache_dir: Path = Path("eval/cache")
    cost_log: Path = Path("costs.log")
    mutations: list[dict[str, Any]] = field(default_factory=list)
    agent_run_cost_usd: float = 0.0


def _record(context: ImportContext, tool: str, args: dict[str, Any]) -> None:
    context.mutations.append({"tool": tool, "args": args})


@function_tool(failure_error_function=None)
def list_colonies(wrapper: RunContextWrapper[ImportContext]) -> list[dict[str, Any]]:
    """List the rescue's colony IDs, nicknames, approximate coordinates, and notes."""
    return wrapper.context.db.list_colonies()


@function_tool(failure_error_function=None)
def find_colony(
    wrapper: RunContextWrapper[ImportContext],
    text_hint: str,
    lat: float | None = None,
    lng: float | None = None,
) -> dict[str, Any]:
    """Find a colony by a message's nickname hint or coordinates; coordinates must be within 300 m."""
    colonies = wrapper.context.db.list_colonies()
    hint = text_hint.casefold()
    named = [item for item in colonies if item["name"].casefold() in hint]
    if len(named) == 1:
        return {**named[0], "matched_by": "name"}
    if lat is None or lng is None:
        return {"id": None, "reason": "no unique nickname and no coordinates"}

    nearest = min(
        colonies,
        key=lambda item: _distance_m(lat, lng, float(item["lat"]), float(item["lng"])),
    )
    distance = _distance_m(lat, lng, float(nearest["lat"]), float(nearest["lng"]))
    if distance > 300:
        return {"id": None, "reason": "none within 300 m", "distance_m": round(distance)}
    return {**nearest, "matched_by": "location", "distance_m": round(distance)}


@function_tool(failure_error_function=None)
def log_feeding(
    wrapper: RunContextWrapper[ImportContext],
    colony_id: str,
    volunteer_id: str,
    at: str,
) -> dict[str, Any]:
    """Log an explicit feeding report for a colony, volunteer, and timestamp."""
    context = wrapper.context
    if volunteer_id != context.volunteer_id or at != context.sent_at:
        raise ValueError("feeding volunteer and time must match the current report")
    event_id = context.db.log_feeding(colony_id, volunteer_id, at, context.report_id)
    args = {"colony_id": colony_id, "volunteer_id": volunteer_id, "at": at}
    _record(context, "log_feeding", args)
    return {"event_id": event_id, **args}


@function_tool(failure_error_function=None)
def list_cats(
    wrapper: RunContextWrapper[ImportContext], colony_id: str
) -> list[dict[str, Any]]:
    """List active cats at one colony; names from a message are hints, not identity proof."""
    cats = wrapper.context.db.list_cats(colony_id)
    for cat in cats:
        cat["description"] = json.loads(cat.pop("description_json"))
    return cats


@function_tool(failure_error_function=None)
def match_photo(
    wrapper: RunContextWrapper[ImportContext], photo_id: int, colony_id: str
) -> dict[str, Any]:
    """Compare one current-report photo within a colony and create a suggestion or a new cat; never merge."""
    return _match_photo(wrapper.context, photo_id, colony_id, record=True)


@function_tool(failure_error_function=None)
def record_event(
    wrapper: RunContextWrapper[ImportContext],
    kind: EventKind,
    colony_id: str,
    detail: str,
    cat_id: int | None = None,
) -> dict[str, Any]:
    """Record a fed, sighting, TNR, health, kittens, need, or status event supported by this message."""
    context = wrapper.context
    event_id = context.db.record_event(
        kind,
        colony_id,
        cat_id,
        detail,
        context.report_id,
        context.sent_at,
        context.volunteer_id,
    )
    args = {"kind": kind, "colony_id": colony_id, "detail": detail, "cat_id": cat_id}
    _record(context, "record_event", args)
    return {"event_id": event_id, **args}


@function_tool(failure_error_function=None)
def update_cat(
    wrapper: RunContextWrapper[ImportContext],
    cat_id: int,
    tnr_status: TNRStatus | None = None,
    health: Health | None = None,
    health_note: str | None = None,
    pregnant: bool | None = None,
) -> dict[str, Any]:
    """Update only TNR, health, health note, or pregnancy; this tool cannot change status."""
    context = wrapper.context
    result = context.db.update_cat(
        cat_id,
        tnr_status=tnr_status,
        health=health,
        health_note=health_note,
        pregnant=pregnant,
    )
    args = {
        "cat_id": cat_id,
        "tnr_status": tnr_status,
        "health": health,
        "health_note": health_note,
        "pregnant": pregnant,
    }
    _record(context, "update_cat", args)
    return result


@function_tool(failure_error_function=None)
def suggest_status(
    wrapper: RunContextWrapper[ImportContext], cat_id: int, new_status: NewStatus, reason: str
) -> dict[str, Any]:
    """Suggest adopted, missing, or deceased for human review; never change status directly."""
    context = wrapper.context
    result = context.db.suggest_status(cat_id, new_status, reason)
    args = {"cat_id": cat_id, "new_status": new_status, "reason": reason}
    _record(context, "suggest_status", args)
    return result


@function_tool(failure_error_function=None)
def raise_alert(
    wrapper: RunContextWrapper[ImportContext],
    kind: str,
    severity: Severity,
    colony_id: str,
    text: str,
    cat_id: int | None = None,
) -> dict[str, Any]:
    """Raise a message-supported urgent, high, or normal colony alert."""
    context = wrapper.context
    alert_id = context.db.raise_alert(
        kind, severity, colony_id, cat_id, text, context.sent_at
    )
    args = {
        "kind": kind,
        "severity": severity,
        "colony_id": colony_id,
        "text": text,
        "cat_id": cat_id,
    }
    _record(context, "raise_alert", args)
    return {"alert_id": alert_id, **args}


def build_agent(model: str) -> Agent[ImportContext]:
    return Agent[ImportContext](
        name="Cat colony report recorder",
        model=model,
        model_settings=ModelSettings(
            reasoning={"effort": "none"},
            verbosity="low",
            max_tokens=800,
            parallel_tool_calls=False,
        ),
        instructions=(
            "Process exactly one rescue report. Use only facts in the supplied report and photo "
            "observations; never invent a cat, colony, condition, feeding, or outcome. Resolve a "
            "colony with find_colony or list_colonies. Log feeding only when the text explicitly "
            "says feeding happened. For EVERY supplied photo_id, call match_photo exactly once, "
            "even when the message names a cat: a name is only a hint and visual matching is still "
            "required. match_photo creates a pending same-cat suggestion or a new cat and never "
            "merges. Never claim a pending match is confirmed. Use update_cat only for TNR, health, "
            "or pregnancy supported by the report; it cannot change status. Adopted, missing, and "
            "deceased are always suggest_status calls requiring later human confirmation. Record "
            "message-supported kittens, health, tnr_done, or supply events and raise same-day alerts "
            "when appropriate. A feeder saying they cannot continue is urgent. Finish with a short "
            "structured summary of what was recorded and what still needs human review."
        ),
        tools=[
            list_colonies,
            find_colony,
            log_feeding,
            list_cats,
            match_photo,
            record_event,
            update_cat,
            suggest_status,
            raise_alert,
        ],
        output_type=AgentSummary,
    )


def process_report(
    agent: Agent[ImportContext], context: ImportContext, report_input: dict[str, Any]
) -> AgentSummary:
    cache_key = value_hash(
        {
            "prompt": AGENT_PROMPT_VERSION,
            "model": context.model,
            "report": report_input,
        }
    )
    cached = context.cache.get("messages", cache_key)
    if cached is not None:
        replay_mutations(context, cached["mutations"])
        return AgentSummary.model_validate_json(cached["final_output"])

    context.cache.check_budget()
    result = Runner.run_sync(
        agent,
        json.dumps(report_input, ensure_ascii=False, sort_keys=True),
        context=context,
        max_turns=10,
        hooks=UsageLoggingHooks(),
    )
    summary = result.final_output_as(AgentSummary)
    usage = result.context_wrapper.usage
    usage_data = {
        "requests": usage.requests,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }
    context.cache.add_agent_result(
        cache_key,
        mutations=context.mutations,
        final_output=summary.model_dump_json(),
        usage=usage_data,
        run_cost_usd=context.agent_run_cost_usd,
    )
    return summary


class UsageLoggingHooks(RunHooks[ImportContext]):
    async def on_llm_end(
        self,
        context: RunContextWrapper[ImportContext],
        agent: Agent[ImportContext],
        response: ModelResponse,
    ) -> None:
        usage = response.usage
        usage_data = {
            "requests": usage.requests,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        }
        run_cost = _estimated_cost(
            context.context.model, usage.input_tokens, usage.output_tokens
        )
        _log_agent_cost(
            context.context.cost_log,
            context.context.model,
            usage_data,
            run_cost,
        )
        context.context.agent_run_cost_usd = round(
            context.context.agent_run_cost_usd + run_cost, 8
        )
        context.context.cache.record_call_cost(run_cost)


def replay_mutations(context: ImportContext, mutations: list[dict[str, Any]]) -> None:
    for mutation in mutations:
        args = mutation["args"]
        tool = mutation["tool"]
        if tool == "match_photo":
            _match_photo(context, record=False, **args)
        elif tool == "log_feeding":
            context.db.log_feeding(
                args["colony_id"], args["volunteer_id"], args["at"], context.report_id
            )
        elif tool == "record_event":
            context.db.record_event(
                args["kind"],
                args["colony_id"],
                args["cat_id"],
                args["detail"],
                context.report_id,
                context.sent_at,
                context.volunteer_id,
            )
        elif tool == "update_cat":
            context.db.update_cat(**args)
        elif tool == "suggest_status":
            context.db.suggest_status(**args)
        elif tool == "raise_alert":
            context.db.raise_alert(
                args["kind"],
                args["severity"],
                args["colony_id"],
                args["cat_id"],
                args["text"],
                context.sent_at,
            )
        else:
            raise ValueError(f"unknown cached mutation tool: {tool}")


def _match_photo(
    context: ImportContext, photo_id: int, colony_id: str, *, record: bool
) -> dict[str, Any]:
    if photo_id not in context.photo_ids:
        raise ValueError(f"photo {photo_id} is not attached to the current report")
    photo = context.db.photo(photo_id)
    candidates = context.db.matching_candidates(colony_id)
    query_description = json.loads(photo["description_json"])
    match_key = value_hash(
        {
            "prompt": MATCH_PROMPT_VERSION,
            "model": context.model,
            "query_hash": file_hash(photo["path"]),
            "query_box": query_description["cats"][0]["box"],
            "candidates": [
                {
                    "id": candidate["id"],
                    "references": [file_hash(path) for path in candidate["reference_photos"]],
                }
                for candidate in candidates
            ],
        }
    )
    result = context.cache.get("matches", match_key)
    if result is None:
        context.cache.check_budget()
        result = match_cat(
            photo["path"],
            candidates,
            query_description=query_description,
            model=context.model,
            cache_dir=context.cache_dir,
            cost_log=context.cost_log,
        )
        context.cache.put("matches", match_key, result)

    if result["suggestion"] == "new":
        action = context.db.create_cat_for_photo(photo_id, colony_id)
    else:
        action = context.db.create_same_cat_suggestion(
            photo_id,
            int(result["candidate_id"]),
            result["suggestion"],
            result.get("comparisons", []),
            result["reason"],
        )
    if record:
        _record(context, "match_photo", {"photo_id": photo_id, "colony_id": colony_id})
    return {"match": result["suggestion"], **action}


def _distance_m(first_lat: float, first_lng: float, second_lat: float, second_lng: float) -> float:
    radius = 6_371_000
    phi1 = math.radians(first_lat)
    phi2 = math.radians(second_lat)
    delta_phi = math.radians(second_lat - first_lat)
    delta_lambda = math.radians(second_lng - first_lng)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _estimated_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = MODEL_PRICES.get(model)
    if prices is None:
        for name, candidate_prices in MODEL_PRICES.items():
            if model.startswith(name + "-"):
                prices = candidate_prices
                break
    if prices is None:
        raise ValueError(f"no cost table entry for model {model}; cannot enforce the budget")
    return round(
        input_tokens * prices[0] / 1_000_000 + output_tokens * prices[1] / 1_000_000,
        8,
    )


def _log_agent_cost(
    path: Path,
    model: str,
    usage: dict[str, int],
    run_cost_usd: float,
) -> None:
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": "message_agent",
        "cache_hit": False,
        "model": model,
        **usage,
        "estimated_cost_usd": run_cost_usd,
        "run_cost_usd": run_cost_usd,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as output:
        output.write(json.dumps(entry, sort_keys=True) + "\n")
