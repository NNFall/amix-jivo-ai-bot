from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.run_history_order_eval import run_evaluation


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run deterministic wiring checks through the real two-tool assistant pipeline."
    )
    parser.add_argument(
        "--scenarios",
        default=str(ROOT_DIR / "tests" / "history_order_eval_scenarios.json"),
    )
    parser.add_argument("--output", default="DIALOG_EVALS.md")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--seed", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-isolated", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    markdown_path = Path(args.output)
    evidence_path = markdown_path.with_suffix(".json")
    if args.append and markdown_path.exists():
        raise SystemExit("Append mode is not supported for reproducible evidence; choose a new output file.")

    evidence = run_evaluation(
        scenarios_path=Path(args.scenarios),
        output_path=evidence_path,
        markdown_output_path=markdown_path,
        fake=True,
        repeat=args.repeat,
    )
    summary = evidence["summary"]
    print(f"Dialog regression eval saved to: {markdown_path}")
    print(
        f"PASS={summary['passed_scenarios']} "
        f"FAIL={summary['scenarios'] - summary['passed_scenarios']}"
    )
    raise SystemExit(0 if summary["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
