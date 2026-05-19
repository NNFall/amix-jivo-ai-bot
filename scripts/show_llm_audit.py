from __future__ import annotations

import argparse
import json
from pathlib import Path

from settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Show recent LLM provider audit entries.")
    parser.add_argument("--path", default=None, help="Path to llm_audit_recent.json")
    parser.add_argument("--limit", type=int, default=20, help="Number of recent entries to show")
    parser.add_argument("--json", action="store_true", help="Print raw JSON entries")
    args = parser.parse_args()

    settings = get_settings()
    path = Path(args.path or settings.llm_audit_log_path)
    if not path.exists():
        print(f"Audit log not found: {path}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries") or []
    entries = entries[-max(1, args.limit) :]

    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2, default=str))
        return 0

    for entry in entries:
        usage = entry.get("usage") or {}
        cost = entry.get("cost") or {}
        summary = entry.get("summary") or {}
        error = entry.get("error") or {}
        print(
            " | ".join(
                [
                    str(entry.get("timestamp") or ""),
                    f"{entry.get('provider')}:{entry.get('model')}",
                    f"status={entry.get('status')}",
                    f"http={entry.get('http_status')}",
                    f"ms={entry.get('duration_ms')}",
                    f"tokens={usage.get('total_tokens')}",
                    f"rub={cost.get('estimated_rub')}",
                    f"error={error.get('type') if error else None}",
                    f"text={summary.get('response_text_preview') or ''}",
                ]
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
