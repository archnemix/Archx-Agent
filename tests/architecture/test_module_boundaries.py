"""Structural contracts for responsibility-focused packages and stable public imports."""

from __future__ import annotations

from tests.paths import REPO_ROOT

import ast
import hashlib
import importlib
import json
import subprocess
import sys

import pytest

from archx_agent.managers.schema import MIGRATIONS

ROOT = REPO_ROOT
PACKAGE = ROOT / "src" / "archx_agent"
PUBLIC_TYPES = [
    ("application.router", "ModelRouter"),
    ("application.agent", "AgentRunner"),
    ("application.learning", "LearningService"),
    ("application.scenes", "SceneService"),
    ("application.experiments", "ExperimentService"),
    ("managers.research", "ResearchManager"),
    ("interfaces.gui.api", "GuiApi"),
    ("managers.mcp", "McpManager"),
    ("managers.extensions", "ExtensionManager"),
    ("managers.reproduction", "ReproductionManager"),
    ("interfaces.mcp_server", "ArchxMcpServer"),
    ("application.remote_worker", "Worker"),
    ("managers.models", "ModelManager"),
    ("managers.conversation", "ConversationManager"),
    ("adapters.http_runtime", "HttpChatRuntime"),
    ("adapters.local_tools", "LocalToolRuntime"),
    ("managers.memory", "MemoryManager"),
    ("managers.context", "ContextManager"),
    ("managers.learning", "LearningManager"),
    ("managers.providers", "ProviderManager"),
    ("managers.tasks", "TaskManager"),
    ("managers.permissions", "PermissionManager"),
    ("managers.jobs", "JobManager"),
    ("managers.tools", "ToolManager"),
    ("managers.workflows", "WorkflowManager"),
    ("application.workspace", "Workspace"),
    ("application.researcher", "ResearchRunner"),
    ("application.execution", "ExecutionService"),
    ("application.training", "TrainingService"),
    ("application.datasets", "DatasetService"),
    ("application.coding", "CodingWorkspace"),
    ("adapters.sdk_transport", "SdkTransport"),
]


@pytest.mark.parametrize("module,name", PUBLIC_TYPES)
def test_public_type_has_no_silently_shadowed_implementation_methods(module, name):
    """One internal responsibility owns each operation; composition must not hide duplicates."""
    cls = getattr(importlib.import_module("archx_agent." + module), name)
    owners = {}
    for base in cls.__mro__:
        if not base.__module__.startswith("archx_agent." + module + "."):
            continue  # BaseManager overrides are deliberate; inspect this package's parts.
        for method, value in vars(base).items():
            if method.startswith("__") or not (
                callable(value)
                or isinstance(value, (property, classmethod, staticmethod))
            ):
                continue
            assert method not in owners, (
                f"{module}.{method}: {owners.get(method)} and {base.__name__}"
            )
            owners[method] = base.__name__
    assert owners


def test_released_migration_sql_and_order_are_unchanged():
    released = [(m.version, m.name, m.statements) for m in MIGRATIONS[:30]]
    assert [m[0] for m in released] == list(range(1, 31))
    digest = hashlib.sha256(
        json.dumps(released, separators=(",", ":")).encode()
    ).hexdigest()
    assert digest == "02f00c5fe7977fc04fd1caa8c625492805c08d7626bfb2ff2d6a901c19d04a98"


def test_new_package_facades_are_declarative_and_do_not_wildcard_import():
    modules = [module for module, _ in PUBLIC_TYPES] + [
        "application.geometry",
        "managers.schema",
    ]
    for module in modules:
        path = PACKAGE.joinpath(*module.split("."), "__init__.py")
        tree = ast.parse(path.read_text())
        assert all(
            isinstance(
                n, (ast.Expr, ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)
            )
            for n in tree.body
        ), path
        assert not any(
            isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
            for n in ast.walk(tree)
        ), path


def test_automation_persistence_is_owned_by_the_manager_layer():
    from archx_agent.application.automations import (
        AutomationManager as compatibility_type,
    )
    from archx_agent.managers.automations import AutomationManager

    assert compatibility_type is AutomationManager
    assert AutomationManager.__module__ == "archx_agent.managers.automations"
    for path in (PACKAGE / "application").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                assert not any(
                    isinstance(base, ast.Name) and base.id == "BaseManager"
                    for base in node.bases
                ), path


def test_every_package_module_imports_without_opening_a_workspace(tmp_path):
    """Import all shipped modules in a fresh interpreter, not just modules reached by fixtures."""
    code = """
import importlib, os, pathlib
import archx_agent
package = pathlib.Path(archx_agent.__file__).parent
names = set()
for path in package.rglob('*.py'):
    if '__pycache__' in path.parts or path.name == '__main__.py':
        continue
    parts = list(path.relative_to(package).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    names.add('.'.join(['archx_agent', *parts]))
names = sorted(names)
for name in names:
    importlib.import_module(name)
assert not pathlib.Path(os.environ['ARCHX_PATHS_HOME']).exists()
print(len(names))
"""
    import os

    home = tmp_path / "must-not-be-created-on-import"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "ARCHX_PATHS_HOME": str(home)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) > 100


def test_mcp_transport_overrides_are_explicit_and_no_other_operation_is_shadowed():
    """Wire-send, cleanup and stdio liveness are the only deliberate overrides."""
    from archx_agent.adapters.mcp_client import McpHttpClient, McpStdioClient

    for cls in (McpHttpClient, McpStdioClient):
        owners = {}
        for base in cls.__mro__:
            if not base.__module__.startswith("archx_agent.adapters.mcp_client."):
                continue
            for name, value in vars(base).items():
                if name.startswith("__") or not callable(value):
                    continue
                if name in owners:
                    assert name in {"_send", "_stop_transport", "alive"}, (cls, name)
                owners[name] = base.__name__
        assert {
            "request",
            "close",
            "initialize",
            "list_tools",
            "_send",
        } <= owners.keys()
        assert cls.__module__.startswith("archx_agent.adapters.mcp_client.")
