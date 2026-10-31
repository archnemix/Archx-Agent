#!/usr/bin/env python3
"""Read each repository file and check syntax, duplicate definitions and document links.

This is a structural audit, not a proof of every runtime path. It uses Git's file
list (including non-ignored new files), reads files sequentially, and never opens
ignored credentials, environments or caches. Node is needed to check browser JS.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    )
    return [ROOT / name for name in sorted(set(result.stdout.decode().split("\0"))) if name and (ROOT / name).is_file()]


def python_checks(text: str, filename: str) -> list[str]:
    tree = ast.parse(text, filename=filename)
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            seen = set()
            for key in node.keys:
                if not isinstance(key, ast.Constant):
                    continue
                if key.value in seen:
                    errors.append(f"line {key.lineno}: duplicate dictionary key {key.value!r}")
                seen.add(key.value)
        if isinstance(node, (ast.ClassDef, ast.Module)):
            seen_methods = set()
            for child in node.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                # A property setter legitimately reuses its property's name.
                setter = any(isinstance(d, ast.Attribute) and d.attr in {"setter", "deleter"}
                             for d in getattr(child, "decorator_list", []))
                if child.name in seen_methods and not setter:
                    errors.append(f"line {child.lineno}: duplicate definition {child.name}")
                seen_methods.add(child.name)
    return errors


def document_links(text: str, path: Path) -> list[str]:
    errors = []
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        for match in re.finditer(r"\[[^\]]*\]\(([^\s)]+)\)", line):
            target = unquote(match.group(1).split("#", 1)[0])
            if not target or re.match(r"[\w+.-]+:", target) or target.startswith("/"):
                continue
            if not (path.parent / target).exists():
                errors.append(f"line {number}: missing link target {target}")
    return errors


def responsibility(path: Path, text: str) -> str:
    relative = path.relative_to(ROOT)
    if path.suffix == ".py":
        doc = ast.get_docstring(ast.parse(text))
        if doc:
            return doc.splitlines()[0]
    if path.suffix == ".md":
        return next((line.removeprefix("# ") for line in text.splitlines() if line.startswith("# ")), "Documentation")
    if str(relative).startswith("tests/"):
        return "Regression tests for " + path.stem.removeprefix("test_").replace("_", " ")
    if path.name.startswith("view-"):
        return "Browser " + path.stem.removeprefix("view-") + " controls and rendering"
    if str(relative).startswith("docs/ci/"):
        return "Historical machine-readable CI evidence"
    if path.suffix in {".sh", ".mjs"}:
        return "Repeatable verification or maintenance command: " + path.stem.replace("_", " ")
    return str(relative)


def audit(output: Path | None = None) -> int:
    rows = []
    issues = []
    for path in repository_files():
        if output and path.resolve() == output.resolve():
            continue  # An inventory cannot include a stable hash of itself.
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        checks = ["read UTF-8", "SHA-256"]
        errors = []
        if path.suffix == ".py":
            try:
                errors += python_checks(text, str(path))
                checks += ["Python AST", "duplicate keys/definitions"]
            except SyntaxError as exc:
                errors.append(str(exc))
        if path.suffix == ".md":
            errors += document_links(text, path)
            checks += ["local document links (file targets only)"]
        command = None
        if path.suffix == ".sh":
            command = ["bash", "-n", str(path)]
        elif path.suffix in {".js", ".mjs"}:
            command = ["node", "--check", str(path)]
        if command:
            if not shutil.which(command[0]):
                errors.append(f"required checker unavailable: {command[0]}")
            else:
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                checks.append(" ".join(command[:2]))
                if result.returncode:
                    errors.append(result.stderr.strip())
        relative = str(path.relative_to(ROOT))
        issues.extend(relative + ": " + error for error in errors)
        rows.append([relative, len(raw), len(text.splitlines()), hashlib.sha256(raw).hexdigest(),
                     responsibility(path, text), "; ".join(checks), "; ".join(errors) or "pass"])
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
    writer.writerow(["file", "bytes", "lines", "sha256", "responsibility", "structural_checks", "result"])
    writer.writerows(rows)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(buffer.getvalue())
    for issue in issues:
        print(issue, file=sys.stderr)
    print(f"Read {len(rows)} files sequentially; {len(issues)} structural issues. "
          "Runtime correctness requires the test and acceptance suites.")
    return int(bool(issues))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write a per-file TSV inventory (excludes itself)")
    raise SystemExit(audit(parser.parse_args().out))
