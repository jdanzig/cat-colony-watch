"""Committed AI-result cache used to rebuild the demo without API calls."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BudgetExceeded(RuntimeError):
    pass


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


class AICache:
    def __init__(
        self,
        path: str | Path,
        model: str,
        max_spend_usd: float | None = 3.0,
    ):
        self.path = Path(path)
        self.model = model
        self.max_spend_usd = max_spend_usd
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            cached_model = self.data.get("model")
            if cached_model != model:
                raise ValueError(
                    f"AI cache was built with {cached_model!r}, not requested model {model!r}"
                )
        else:
            self.data = {
                "version": 1,
                "model": model,
                "prompt_versions": {},
                "build_cost_usd": 0.0,
                "descriptions": {},
                "matches": {},
                "messages": {},
            }

    @property
    def spend(self) -> float:
        return float(self.data.get("build_cost_usd", 0.0))

    def check_budget(self, reserve_usd: float = 0.10) -> None:
        if self.max_spend_usd is None:
            return
        if self.spend >= self.max_spend_usd - reserve_usd:
            raise BudgetExceeded(
                f"AI cache build has spent ${self.spend:.4f}; another call could exceed "
                f"the ${self.max_spend_usd:.2f} limit"
            )

    def get(self, section: str, key: str) -> dict[str, Any] | None:
        return self.data[section].get(key)

    def put(self, section: str, key: str, value: dict[str, Any]) -> None:
        self.data[section][key] = value
        run_cost = value.get("_meta", {}).get("run_cost_usd")
        if run_cost:
            self.data["build_cost_usd"] = round(self.spend + float(run_cost), 8)
        self.save()

    def add_agent_result(
        self,
        key: str,
        *,
        mutations: list[dict[str, Any]],
        final_output: str,
        usage: dict[str, Any],
        run_cost_usd: float,
    ) -> None:
        self.data["messages"][key] = {
            "mutations": mutations,
            "final_output": final_output,
            "usage": usage,
            "_meta": {"run_cost_usd": run_cost_usd},
        }
        self.save()

    def record_call_cost(self, run_cost_usd: float) -> None:
        self.data["build_cost_usd"] = round(self.spend + run_cost_usd, 8)
        self.save()

    def save(self) -> None:
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
        temporary.replace(self.path)

    def stats(self) -> dict[str, Any]:
        return {
            "descriptions": len(self.data["descriptions"]),
            "matches": len(self.data["matches"]),
            "messages": len(self.data["messages"]),
            "build_cost_usd": self.spend,
        }
