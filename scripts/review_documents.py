#!/usr/bin/env python3
"""Read/classify every Markdown document and check current source references.

This is repeatable document-inventory evidence, not automated semantic certification.
Historical transcripts retain their old paths/counts. Local link checks ignore remote
URLs and anchors; explicit source references are checked only in current prose.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import re

from audit_repository import ROOT, document_links, repository_files

SOURCE_REFERENCE = re.compile(
    r"(?:src/archx_agent/|tests/|scripts/|managers/|adapters/|application/|interfaces/|helpers/)"
    r"[\w/.-]+\.(?:py|sh|mjs|js|css)(?:::[\w.]+)?"
)


def classification(path: Path) -> str:
    if "reports" in path.parts or "verification" in path.parts:
        return "historical checkpoint"
    if "ci" in path.parts:
        return "historical CI evidence"
    if path.name in {"CHANGELOG.md", "THINKING.md", "VERIFICATION.md"}:
        return "mixed decision/change/evidence log"
    return "current guide/status"


def review_text(path: Path, root: Path = ROOT) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    kind = classification(path)
    issues = document_links(text, path)
    if not text.startswith("# "):
        issues.append("missing top-level plain-English title")
    if kind.startswith("historical"):
        if not re.search(
            r"historical|recorded run|GitHub Actions run", text[:1000], re.I
        ):
            issues.append("missing historical-evidence context")
    elif kind == "current guide/status":
        # Only exact inline references; examples/placeholders/fenced transcripts are
        # not asserted executable. A removed file becoming a package is still stale.
        fenced = False
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if fenced:
                continue
            for token in re.findall(r"`([^`\n]+)`", line):
                if not SOURCE_REFERENCE.fullmatch(token):
                    continue
                name = token.split("::", 1)[0]
                target = root / name
                if name.startswith(
                    (
                        "managers/",
                        "adapters/",
                        "application/",
                        "interfaces/",
                        "helpers/",
                    )
                ):
                    target = root / "src" / "archx_agent" / name
                if not target.is_file():
                    issues.append(f"line {number}: stale source reference {token}")
    return kind, issues


def review(output: Path) -> int:
    rows = []
    failures = []
    for path in repository_files():
        if path.suffix != ".md":
            continue
        kind, issues = review_text(path)
        text = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(ROOT))
        title = next(
            (line[2:] for line in text.splitlines() if line.startswith("# ")),
            "Untitled",
        )
        rows.append(
            [
                relative,
                title,
                kind,
                hashlib.sha256(path.read_bytes()).hexdigest(),
                "full UTF-8 read; title; local file links; current exact inline source paths; history labels",
                "; ".join(issues) or "pass",
            ]
        )
        failures.extend(f"{relative}: {issue}" for issue in issues)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, delimiter="\t", lineterminator="\n")
        writer.writerow(
            ["document", "plain_english_name", "kind", "sha256", "checks", "result"]
        )
        writer.writerows(rows)
    for issue in failures:
        print(issue)
    print(
        f"Read {len(rows)} Markdown documents; {len(failures)} document-reference issues. "
        "Prose and executable examples still require implementation review."
    )
    return int(bool(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/audit/documents.tsv")
    raise SystemExit(review(parser.parse_args().out))
