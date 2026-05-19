from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import json
import os
import tempfile
import threading
from typing import Any


_AUDIT_LOCK = threading.Lock()

GOOGLE_MODEL_PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    # Official Google Gemini API pricing is USD per 1M tokens.
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
}


@dataclass(slots=True)
class LLMUsageStats:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(slots=True)
class LLMCostEstimate:
    input_usd_per_1m: float | None = None
    output_usd_per_1m: float | None = None
    estimated_usd: float | None = None
    estimated_rub: float | None = None
    usd_to_rub: float | None = None
    note: str | None = None


class LLMAuditLogger:
    def __init__(
        self,
        *,
        enabled: bool,
        path: str,
        max_entries: int,
        usd_to_rub: float,
    ) -> None:
        self.enabled = enabled
        self.path = Path(path)
        self.max_entries = max(1, int(max_entries or 1))
        self.usd_to_rub = float(usd_to_rub or 0)

    def write(self, entry: dict[str, Any]) -> None:
        if not self.enabled:
            return

        now = datetime.now(UTC).isoformat()
        entry.setdefault("timestamp", now)

        with _AUDIT_LOCK:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                existing = self._read_existing()
                entries = existing.get("entries", [])
                if not isinstance(entries, list):
                    entries = []
                entries.append(entry)
                entries = entries[-self.max_entries :]

                payload = {
                    "schema_version": 1,
                    "updated_at": now,
                    "max_entries": self.max_entries,
                    "entries_count": len(entries),
                    "entries": entries,
                }
                self._atomic_write(payload)
            except Exception:
                # Audit logging must never break customer replies.
                return

    def _read_existing(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=self.path.name, suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2, default=str)
                file.write("\n")
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


def extract_usage_stats(response_json: dict[str, Any] | None) -> LLMUsageStats:
    usage = (response_json or {}).get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    return LLMUsageStats(
        prompt_tokens=_to_int(usage.get("prompt_tokens") or usage.get("input_tokens")),
        completion_tokens=_to_int(usage.get("completion_tokens") or usage.get("output_tokens")),
        total_tokens=_to_int(usage.get("total_tokens")),
    )


def estimate_cost(
    *,
    provider: str,
    model: str | None,
    usage: LLMUsageStats,
    usd_to_rub: float,
) -> LLMCostEstimate:
    if provider not in {"google", "google_ai", "google_ai_studio", "gemini"}:
        return LLMCostEstimate(note="No built-in pricing table for this provider.")
    if not model:
        return LLMCostEstimate(note="Model is missing; cost cannot be estimated.")

    pricing = GOOGLE_MODEL_PRICING_USD_PER_1M.get(model)
    if pricing is None:
        return LLMCostEstimate(note=f"No built-in pricing table for model {model}.")

    prompt_tokens = usage.prompt_tokens or 0
    completion_tokens = usage.completion_tokens or 0
    estimated_usd = (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000
    estimated_rub = estimated_usd * usd_to_rub if usd_to_rub else None

    return LLMCostEstimate(
        input_usd_per_1m=pricing["input"],
        output_usd_per_1m=pricing["output"],
        estimated_usd=round(estimated_usd, 8),
        estimated_rub=round(estimated_rub, 4) if estimated_rub is not None else None,
        usd_to_rub=usd_to_rub,
        note="Paid-tier estimate. Free-tier requests may bill as 0 until free limits are exhausted.",
    )


def usage_to_dict(usage: LLMUsageStats) -> dict[str, int | None]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def cost_to_dict(cost: LLMCostEstimate) -> dict[str, float | str | None]:
    return {
        "input_usd_per_1m": cost.input_usd_per_1m,
        "output_usd_per_1m": cost.output_usd_per_1m,
        "estimated_usd": cost.estimated_usd,
        "estimated_rub": cost.estimated_rub,
        "usd_to_rub": cost.usd_to_rub,
        "note": cost.note,
    }


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
