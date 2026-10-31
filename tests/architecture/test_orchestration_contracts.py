"""Preserved AST contracts and explicit exceptions for the nine-owner cleanup batch."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from tests.paths import REPO_ROOT

CONTRACTS = json.loads((REPO_ROOT / "docs/audit/orchestration-contracts.json").read_text())
ROOT = REPO_ROOT / "src/archx_agent"


def current_node(contract):
    original = Path(contract["original"])
    if original.as_posix() == "interfaces/gui/server.py":
        folder = ROOT / "interfaces/gui"
        files = [*folder.joinpath("api").glob("*.py"), folder / "http.py", folder / "lifecycle.py", folder / "transport_helpers.py"]
    else:
        files = list((ROOT / original.with_suffix("")).glob("*.py"))
    owner, _, method = contract["name"].rpartition(".")
    for file in files:
        tree = ast.parse(file.read_text())
        for node in tree.body:
            if contract["kind"] in {"method", "class_attribute"} and isinstance(node, ast.ClassDef):
                matches = node.name == owner or node.name.startswith(owner) and node.name.endswith("Mixin")
                if owner == "GuiApi" and file.parent.name == "api":
                    matches = True
                if matches:
                    for child in node.body:
                        if isinstance(child, ast.FunctionDef) and child.name == method:
                            return child
                        if contract["kind"] == "class_attribute" and isinstance(child, ast.Assign) and any(isinstance(n, ast.Name) and n.id == method for n in child.targets):
                            return child
            elif contract["kind"] == "branch" and isinstance(node, ast.FunctionDef) and node.name == contract["name"]:
                return ast.Module(body=node.body, type_ignores=[])
            elif contract["kind"] == "parser" and isinstance(node, ast.FunctionDef) and node.name == contract["name"]:
                return node
            elif contract["kind"] == "global":
                names = [node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else [n.id for n in getattr(node, "targets", []) if isinstance(n, ast.Name)]
                if contract["name"] in names:
                    return node
    raise AssertionError("Missing contract owner: " + contract["name"])


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda c: c["original"] + ":" + c["name"])
def test_preserved_or_explicitly_changed_ast(contract):
    node = current_node(contract)
    if contract["name"] == "AgentRunner.run":
        # Preserve the existing public Budget override hook after moving the run loop.
        node.body = [n for n in node.body if not (isinstance(n, ast.ImportFrom) and n.module == "archx_agent.application.agent")]
    digest = hashlib.sha256(ast.dump(node).encode()).hexdigest()
    assert digest == contract.get("current_sha256", contract["sha256"])


def test_all_nine_fixed_targets_have_contracts():
    assert len({c["original"] for c in CONTRACTS}) == 9
    # Recovered copies are useful regression contracts, not independent before/after proof.
    recovered = {c["original"] for c in CONTRACTS if c["baseline"] != "pre-change source snapshot"}
    assert recovered == {"application/router.py", "application/agent.py"}
