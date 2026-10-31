#!/usr/bin/env python3
"""Export per-source-file evidence from a coverage.py JSON report (standard library only)."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def export(report: Path, output: Path) -> None:
    data = json.loads(report.read_text())
    rows = []
    for name, measured in sorted(data["files"].items()):
        summary = measured["summary"]
        statements = int(summary["num_statements"])
        covered = int(summary["covered_lines"])
        rows.append(
            [
                name,
                statements,
                covered,
                summary["missing_lines"],
                summary.get("num_branches", 0),
                summary.get("covered_branches", 0),
                ",".join(map(str, measured.get("missing_lines", []))),
                "no executable statements"
                if not statements
                else "not exercised in measured processes"
                if not covered
                else "partly exercised"
                if covered < statements
                else "all statements exercised",
            ]
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as target:
        writer = csv.writer(target, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "file",
                "statements",
                "covered_statements",
                "missing_statements",
                "branches",
                "covered_branches",
                "missing_lines",
                "measurement",
            ]
        )
        writer.writerows(rows)
    print(
        f"Exported {len(rows)} source-file measurements. Coverage is evidence, not correctness certification."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="coverage.py JSON report"
    )
    parser.add_argument("--out", type=Path, required=True, help="per-file TSV output")
    args = parser.parse_args()
    export(args.input, args.out)
