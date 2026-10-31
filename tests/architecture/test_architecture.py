"""Collected dependency-boundary and storage-driver guards.

These must live in a test module, not conftest.py: pytest does not collect tests
from conftest. Interface imports of adapter protocol values/metadata are reviewed
and allowed; orchestration still belongs in the application layer.
"""

from __future__ import annotations

from tests.paths import SRC as SOURCE_ROOT

import ast
import sys
from importlib.util import resolve_name
from pathlib import Path

import pytest

SRC = SOURCE_ROOT

PACKAGE_ROOT = SRC / "archx_agent"

LAYER_IMPORTS = {
    "interfaces": {"interfaces", "application", "managers", "adapters", "helpers"},
    "application": {"application", "managers", "adapters", "helpers"},
    "managers": {"managers", "adapters", "helpers"},
    "helpers": {"helpers"},
    "adapters": {"adapters", "helpers"},
}


def iter_package_modules() -> list[Path]:
    return sorted(p for p in PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def module_layer(path: Path) -> str:
    rel = path.relative_to(PACKAGE_ROOT).parts
    return rel[0] if len(rel) > 1 else "root"


def imported_layers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    layers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "archx_agent" and len(parts) > 1:
                    layers.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                package = ".".join(
                    ("archx_agent", *path.relative_to(PACKAGE_ROOT).parts[:-1])
                )
                module = resolve_name("." * node.level + module, package)
            parts = module.split(".")
            if parts[0] == "archx_agent" and len(parts) > 1:
                layers.add(parts[1])
            elif module == "archx_agent":
                layers.update(
                    alias.name for alias in node.names if alias.name in LAYER_IMPORTS
                )
    return layers


def test_import_matrix_is_respected():
    violations = []
    for path in iter_package_modules():
        layer = module_layer(path)
        allowed = LAYER_IMPORTS.get(layer)
        if allowed is None:
            continue
        for imported in imported_layers(path):
            if imported == "root":
                continue
            if imported not in allowed:
                violations.append(
                    f"{path.relative_to(PACKAGE_ROOT)}: layer {layer} imports {imported}"
                )
    assert not violations, "import matrix violated:\n" + "\n".join(violations)


def test_only_sqlite_store_imports_sqlite3():
    offenders = []
    for path in iter_package_modules():
        if path.name == "sqlite_store.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                a.name == "sqlite3" for a in node.names
            ):
                offenders.append(str(path.relative_to(PACKAGE_ROOT)))
            if isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                offenders.append(str(path.relative_to(PACKAGE_ROOT)))
    assert not offenders, (
        f"sqlite3 imported outside helpers/sqlite_store.py: {sorted(set(offenders))}"
    )


def test_relative_imports_resolve_to_layers_not_module_names(tmp_path, monkeypatch):
    root = tmp_path / "archx_agent"
    path = root / "managers" / "sample.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "from .base import Manager\nfrom ..helpers import jsonio\nfrom . import context\n"
    )
    monkeypatch.setattr(sys.modules[__name__], "PACKAGE_ROOT", root)
    assert imported_layers(path) == {"managers", "helpers"}


@pytest.mark.parametrize(
    "statement",
    [
        "from ..application import chat",
        "from .. import application",
        "from archx_agent import application",
    ],
)
def test_guard_rejects_an_upward_relative_import(tmp_path, monkeypatch, statement):
    root = tmp_path / "archx_agent"
    path = root / "helpers" / "bad.py"
    path.parent.mkdir(parents=True)
    path.write_text(statement + "\n")
    monkeypatch.setattr(sys.modules[__name__], "PACKAGE_ROOT", root)
    with pytest.raises(AssertionError, match="layer helpers imports application"):
        test_import_matrix_is_respected()
