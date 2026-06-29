"""
Inspect SVIS JSON output and print a compact summary.

Usage:
  python inspect_output.py output/your_file_svis.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def summarize(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    variables = data.get("variables", [])

    type_counts = Counter(v.get("data_type", "unknown") for v in variables)
    review_count = sum(1 for v in variables if v.get("needs_review"))
    modules = Counter(v.get("module") or "(none)" for v in variables)

    print("=" * 60)
    print(f"File: {path}")
    print("=" * 60)
    print(f"survey_id      : {data.get('survey_id')}")
    print(f"survey_name    : {data.get('survey_name')}")
    print(f"country_code   : {data.get('country_code')}")
    print(f"year           : {data.get('year')}")
    print(f"study_type     : {data.get('study_type')}")
    print(f"source_file    : {data.get('source_file')}")
    print(f"extraction_date: {data.get('extraction_date')}")
    print(f"notes          : {data.get('extraction_notes')}")

    print("\nVariables")
    print(f"total          : {len(variables)}")
    print(f"needs_review   : {review_count}")

    print("\nBy data_type")
    for k, v in sorted(type_counts.items()):
        print(f"- {k}: {v}")

    print("\nTop modules")
    for module, count in modules.most_common(10):
        print(f"- {module}: {count}")

    if variables:
        print("\nSample variables")
        for v in variables[:10]:
            print(
                f"- {v.get('raw_name')} | {v.get('data_type')} | "
                f"review={v.get('needs_review')} | module={v.get('module')}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect SVIS JSON output.")
    parser.add_argument("json_path", type=Path, help="Path to *_svis.json file")
    args = parser.parse_args()

    if not args.json_path.exists():
        raise SystemExit(f"File not found: {args.json_path}")

    summarize(args.json_path)
