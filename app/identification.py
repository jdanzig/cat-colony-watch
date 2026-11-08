"""Describe cat photos and suggest same-cat matches with the OpenAI API.

The model reports visible observations. Plain Python applies the matching rule,
and callers create suggestions for a person to confirm; this module never
merges cat records.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageOps
from pydantic import BaseModel, Field


DESCRIPTION_PROMPT_VERSION = "describe-cat-v1"
MATCH_PROMPT_VERSION = "match-cat-v1"
MAX_IMAGE_SIDE = 768
DEFAULT_CACHE_DIR = Path("eval/cache")
DEFAULT_COST_LOG = Path("costs.log")

# Standard API prices per million tokens on 2026-11-07. Unknown models are
# still logged with token counts, but their estimated cost is left unset.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-6.1-terra": (1.00, 5.00),
    "gpt-6-luna": (0.10, 0.50),
    "gpt-5.4-mini": (0.75, 4.50),
}

Verdict = Literal["same", "different", "not_visible", "unclear"]


class CatObservation(BaseModel):
    box: list[float] = Field(min_length=4, max_length=4)
    view: Literal["side", "front", "back", "face", "unclear"]
    coat_color: Literal[
        "black", "gray", "brown", "orange", "cream", "white", "mixed", "unclear"
    ]
    pattern: Literal[
        "solid", "tabby", "tortoiseshell", "calico", "bicolor", "colorpoint", "spotted", "other", "unclear"
    ]
    markings: list[str]
    eye_color: Literal["blue", "green", "yellow", "amber", "brown", "mixed", "unclear"]
    tail: str
    ear_tip: Literal["left", "right", "none", "unclear"]
    apparent_health: list[str]
    looks_pregnant: bool
    is_kitten: bool


class PhotoDescription(BaseModel):
    cat_count: int = Field(ge=0)
    cats: list[CatObservation]
    kittens_present: bool
    photo_quality: Literal["good", "poor"]


class FeatureVerdicts(BaseModel):
    coat_color: Verdict
    pattern: Verdict
    face_markings: Verdict
    body_markings: Verdict
    ear_shape_or_damage: Verdict
    ear_tip: Verdict
    eye_color: Verdict
    tail: Verdict


class CandidateComparison(BaseModel):
    candidate: str
    features: FeatureVerdicts
    matching_specific_markings: list[str]
    contradictions: list[str]


class MatchComparison(BaseModel):
    comparisons: list[CandidateComparison]


def _model_name(model: str | None) -> str:
    load_dotenv()
    selected = model or os.getenv("OPENAI_MODEL")
    if not selected:
        raise RuntimeError("OPENAI_MODEL is required; copy .env.example to .env and set it")
    return selected


def _file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_data_url(path: str | Path, box: list[float] | None = None) -> str:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        if box is not None:
            left, top, right, bottom = [max(0.0, min(1.0, float(v))) for v in box]
            if right > left and bottom > top:
                width, height = image.size
                image = image.crop(
                    (
                        round(left * width),
                        round(top * height),
                        round(right * width),
                        round(bottom * height),
                    )
                )
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _cache_key(kind: str, model: str, prompt_version: str, inputs: list[str]) -> str:
    payload = json.dumps(
        {"kind": kind, "model": model, "prompt_version": prompt_version, "inputs": inputs},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_cache(cache_dir: Path, key: str) -> dict[str, Any] | None:
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None
    result = json.loads(path.read_text())
    result["_meta"] = {
        **result.get("_meta", {}),
        "cache_hit": True,
        "run_cost_usd": 0.0,
    }
    return result


def _save_cache(cache_dir: Path, key: str, result: dict[str, Any]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _price_for_model(model: str) -> tuple[float, float] | None:
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    for name, prices in MODEL_PRICES.items():
        if model.startswith(name + "-"):
            return prices
    return None


def _usage_metadata(response: Any, model: str, kind: str, cost_log: Path) -> dict[str, Any]:
    usage = response.usage
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    prices = _price_for_model(model)
    estimated_cost = None
    if prices:
        estimated_cost = round(
            input_tokens * prices[0] / 1_000_000 + output_tokens * prices[1] / 1_000_000,
            8,
        )
    metadata = {
        "cache_hit": False,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": estimated_cost,
        "run_cost_usd": estimated_cost,
    }
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        **metadata,
    }
    cost_log.parent.mkdir(parents=True, exist_ok=True)
    with cost_log.open("a") as log:
        log.write(json.dumps(entry, sort_keys=True) + "\n")
    return metadata


def describe_photo(
    photo_path: str | Path,
    *,
    model: str | None = None,
    client: OpenAI | None = None,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    cost_log: str | Path = DEFAULT_COST_LOG,
) -> dict[str, Any]:
    """Return cached, structured visible observations for every cat in a photo."""
    photo_path = Path(photo_path)
    selected_model = _model_name(model)
    cache_dir = Path(cache_dir)
    key = _cache_key(
        "description", selected_model, DESCRIPTION_PROMPT_VERSION, [_file_hash(photo_path)]
    )
    cached = _load_cache(cache_dir, key)
    if cached is not None:
        return cached

    prompt = (
        "Describe only what is visibly supported in this cat-rescue photo. Find every real cat. "
        "For each cat, return a tight [left, top, right, bottom] bounding box using fractions from "
        "0 to 1. Markings must be short, concrete, persistent identity features such as a white "
        "nose blaze, asymmetrical socks, a chest patch, a facial stripe, or visible ear damage; "
        "do not include pose, background, collar, lighting, or guessed breed. Report uncertain or "
        "hidden details as unclear. Apparent health must contain only visible signs, never a diagnosis. "
        "cat_count must equal the number of entries in cats."
    )
    api = client or OpenAI(timeout=60.0, max_retries=0)
    response = api.responses.parse(
        model=selected_model,
        reasoning={"effort": "none"},
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": _image_data_url(photo_path), "detail": "high"},
                ],
            }
        ],
        text_format=PhotoDescription,
    )
    if response.output_parsed is None:
        raise RuntimeError("OpenAI returned no parsed photo description")
    result = response.output_parsed.model_dump()
    result["_meta"] = _usage_metadata(response, selected_model, "describe_photo", Path(cost_log))
    _save_cache(cache_dir, key, result)
    return result


def _first_cat(description: dict[str, Any]) -> dict[str, Any]:
    cats = description.get("cats", [])
    if not cats:
        raise ValueError("photo description contains no cat")
    return cats[0]


def _clearly_different_coat(first: str, second: str) -> bool:
    # White is commonly a marking rather than the whole coat, so the one-word
    # description is not safe enough to filter on. Black/gray and orange/cream
    # are grouped because lighting can shift those observations.
    if first in {"unclear", "mixed", "white"} or second in {"unclear", "mixed", "white"}:
        return False
    families = {
        "black": "dark",
        "gray": "dark",
        "orange": "warm",
        "cream": "warm",
        "brown": "brown",
        "white": "white",
    }
    return families.get(first) != families.get(second)


def decide_match(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the fixed suggestion rule to model-provided feature observations."""
    if not comparisons:
        return {"suggestion": "new", "candidate_id": None, "reason": "no candidates"}

    def has_any_contradiction(item: dict[str, Any]) -> bool:
        return bool(item.get("contradictions")) or any(
            value == "different" for value in item.get("features", {}).values()
        )

    # Eye color alone changes substantially with lighting and pupil dilation. It
    # blocks a strong match but cannot, by itself, prove that this is a new cat.
    persistent_features = {
        "coat_color",
        "pattern",
        "face_markings",
        "body_markings",
        "ear_shape_or_damage",
        "ear_tip",
        "tail",
    }

    def has_clear_contradiction(item: dict[str, Any]) -> bool:
        return any(
            name in persistent_features and value == "different"
            for name, value in item.get("features", {}).items()
        )

    viable = [item for item in comparisons if not has_clear_contradiction(item)]
    if not viable:
        return {
            "suggestion": "new",
            "candidate_id": None,
            "reason": "every candidate has a visible contradiction",
        }

    ranked = sorted(
        viable,
        key=lambda item: (
            len(set(item.get("matching_specific_markings", []))),
            sum(value == "same" for value in item.get("features", {}).values()),
            item.get("candidate", ""),
        ),
        reverse=True,
    )
    strong = [
        item
        for item in viable
        if len(set(item.get("matching_specific_markings", []))) >= 2
        and not has_any_contradiction(item)
    ]
    best = ranked[0]
    if len(strong) == 1:
        return {
            "suggestion": "strong",
            "candidate_id": strong[0]["candidate"],
            "reason": "; ".join(strong[0]["matching_specific_markings"]),
        }
    if len(strong) > 1:
        return {
            "suggestion": "weak",
            "candidate_id": best["candidate"],
            "reason": "multiple candidates have two or more matching specific markings",
        }
    return {
        "suggestion": "weak",
        "candidate_id": best["candidate"],
        "reason": "some agreement or an unclear view; human comparison required",
    }


def match_cat(
    query_photo: str | Path,
    candidates: list[dict[str, Any]],
    *,
    query_description: dict[str, Any] | None = None,
    model: str | None = None,
    client: OpenAI | None = None,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    cost_log: str | Path = DEFAULT_COST_LOG,
) -> dict[str, Any]:
    """Compare a cat crop with candidates and return a human-review suggestion.

    Each candidate is ``{"id", "reference_photos", "reference_descriptions"}``. This
    function only returns strong/weak/new; it never changes or merges records.
    """
    selected_model = _model_name(model)
    cache_dir = Path(cache_dir)
    query_description = query_description or describe_photo(
        query_photo,
        model=selected_model,
        client=client,
        cache_dir=cache_dir,
        cost_log=cost_log,
    )
    query_cat = _first_cat(query_description)

    narrowed = []
    for candidate in candidates:
        descriptions = candidate.get("reference_descriptions") or [candidate["description"]]
        candidate_cat = _first_cat(descriptions[0])
        if _clearly_different_coat(query_cat["coat_color"], candidate_cat["coat_color"]):
            continue
        narrowed.append(candidate)
    narrowed = narrowed[:5]
    if not narrowed:
        return {
            "suggestion": "new",
            "candidate_id": None,
            "comparisons": [],
            "reason": "no candidates after conservative coat-color filtering",
            "_meta": {"cache_hit": True, "run_cost_usd": 0.0},
        }

    hashes = [
        DESCRIPTION_PROMPT_VERSION,
        _file_hash(query_photo),
        json.dumps(query_cat["box"]),
    ]
    for candidate in narrowed:
        hashes.append(str(candidate["id"]))
        descriptions = candidate.get("reference_descriptions") or [candidate["description"]]
        for reference, description in zip(candidate["reference_photos"][:2], descriptions[:2]):
            hashes.extend([_file_hash(reference), json.dumps(_first_cat(description)["box"])])
    key = _cache_key("match", selected_model, MATCH_PROMPT_VERSION, hashes)
    cached = _load_cache(cache_dir, key)
    if cached is not None:
        return {**cached, **decide_match(cached.get("comparisons", []))}

    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "Compare the QUERY cat with each labeled CANDIDATE cat. Report visible feature "
                "verdicts; do not choose a winner and do not give a probability. A 'same' feature "
                "means it visibly agrees, not merely that it is common. matching_specific_markings "
                "must list only concrete, identity-level agreements (for example the same asymmetric "
                "nose blaze, sock boundary, chest patch shape, facial stripe, or ear damage). Generic "
                "coat color, tabby pattern, eye color, body size, pose, collars, and background are "
                "not specific markings. contradictions must list persistent visible conflicts, not "
                "viewpoint, lighting, pose, or a hidden feature. Return exactly one comparison for "
                "each candidate label."
            ),
        },
        {"type": "input_text", "text": "QUERY"},
        {
            "type": "input_image",
            "image_url": _image_data_url(query_photo, query_cat["box"]),
            "detail": "high",
        },
    ]
    for candidate in narrowed:
        descriptions = candidate.get("reference_descriptions") or [candidate["description"]]
        references = zip(candidate["reference_photos"][:2], descriptions[:2])
        for number, (reference, description) in enumerate(references, 1):
            candidate_cat = _first_cat(description)
            content.extend(
                [
                    {
                        "type": "input_text",
                        "text": f"CANDIDATE {candidate['id']} REFERENCE {number}",
                    },
                    {
                        "type": "input_image",
                        "image_url": _image_data_url(reference, candidate_cat["box"]),
                        "detail": "high",
                    },
                ]
            )

    api = client or OpenAI(timeout=60.0, max_retries=0)
    response = api.responses.parse(
        model=selected_model,
        reasoning={"effort": "none"},
        input=[{"role": "user", "content": content}],
        text_format=MatchComparison,
    )
    if response.output_parsed is None:
        raise RuntimeError("OpenAI returned no parsed cat comparison")
    metadata = _usage_metadata(response, selected_model, "match_cat", Path(cost_log))
    comparisons = [item.model_dump() for item in response.output_parsed.comparisons]
    for comparison in comparisons:
        comparison["candidate"] = normalize_candidate_label(comparison["candidate"])
    expected = {str(candidate["id"]) for candidate in narrowed}
    returned = {item["candidate"] for item in comparisons}
    if returned != expected:
        raise RuntimeError(f"comparison labels differ: expected {expected}, received {returned}")
    result = {**decide_match(comparisons), "comparisons": comparisons}
    result["_meta"] = metadata
    _save_cache(cache_dir, key, result)
    return result


def normalize_candidate_label(label: str) -> str:
    """Accept the model echoing a prompt label without changing candidate identity."""
    return re.sub(r"^candidate\s+", "", label.strip(), flags=re.IGNORECASE)
