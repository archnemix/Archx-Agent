"""Lifecycle operations for workspace composition."""

from __future__ import annotations

from typing import Self
import os
from pathlib import Path
from typing import Any, Mapping

from archx_agent import __version__
from archx_agent.adapters.extension_runtime import ExtensionRuntime
from archx_agent.adapters.scripted_runtime import ENV_FLAG
from archx_agent.helpers.backup_recovery import create_backup
from archx_agent.helpers.config import Config, load_config
from archx_agent.helpers.events import EventStore
from archx_agent.helpers.sqlite_store import SqliteStore
from archx_agent.helpers.write_coordinator import WriteCoordinator
from archx_agent.managers.coding import CodeManager
from archx_agent.managers.experiments import ExperimentManager
from archx_agent.managers.context import ContextManager
from archx_agent.managers.embeddings import EmbeddingManager
from archx_agent.managers.conversation import ConversationManager
from archx_agent.managers.extensions import ExtensionManager
from archx_agent.managers.jobs import JobManager
from archx_agent.managers.datasets import DatasetManager
from archx_agent.managers.learning import LearningManager
from archx_agent.managers.mcp import McpManager
from archx_agent.managers.media import MediaManager
from archx_agent.managers.memory import MemoryManager
from archx_agent.managers.models import ModelManager
from archx_agent.managers.permissions import PermissionManager
from archx_agent.managers.play import PlayManager
from archx_agent.managers.projects import ProjectManager
from archx_agent.managers.providers import ProviderManager
from archx_agent.managers.reproduction import ReproductionManager
from archx_agent.managers.research import ResearchManager
from archx_agent.managers.tasks import TaskManager
from archx_agent.managers.training import TrainingManager
from archx_agent.managers.remote import RemoteManager
from archx_agent.managers.execution import ExecutionManager
from archx_agent.managers.scenes import SceneManager
from archx_agent.managers.automations import AutomationManager
from archx_agent.managers.tools import ToolManager
from archx_agent.managers.versions import VersionManager
from archx_agent.managers.workflows import WorkflowManager
from archx_agent.application.router import ModelRouter
from archx_agent.application.scheduler import JobRunner
from archx_agent.application.search import SearchService
from archx_agent.application.simple import SimpleMode
from archx_agent.managers.schema import MIGRATIONS, SCHEMA_VERSION
from archx_agent.application.workspace.embeddings import _build_embedding_provider
from archx_agent.application.workspace.tools import _build_tool_runtime


class WorkspaceLifecycleMixin:
    """Lifecycle responsibility for Workspace."""

    @classmethod
    def open(
        cls,
        *,
        home: str | os.PathLike[str] | None = None,
        config_path: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        overrides: Mapping[str, Any] | None = None,
        create: bool = True,
        allow_test_double: bool | None = None,
    ) -> Self:
        config = load_config(
            home=home,
            config_path=config_path,
            env=env,
            overrides=overrides,
            create=create,
        )
        # The environment flag is a legitimate way to enable the test double (the CLI
        # passes it explicitly too); treat either as "the user asked for it".
        environ = os.environ if env is None else env
        enabled = (
            allow_test_double
            if allow_test_double is not None
            else (environ.get(ENV_FLAG) == "1")
        )
        return cls.from_config(config, allow_test_double=enabled)

    @classmethod
    def from_config(cls, config: Config, *, allow_test_double: bool = False) -> Self:
        warnings: list[str] = []
        config.ensure_dirs()
        db_path = config.path("storage.db_path")
        store = SqliteStore(db_path, wal=config.get("storage.journal_mode") == "wal")
        try:
            current_version = store.schema_version()
            target = SCHEMA_VERSION
            if (
                current_version
                and current_version < target
                and config.get("storage.auto_backup")
            ):
                try:
                    info = create_backup(
                        db_path, config.path("paths.backups"), label="pre-migration"
                    )
                    warnings.append(
                        f"backed up v{current_version} database before migration: {info.path.name}"
                    )
                except Exception as exc:  # noqa: BLE001 - backup failure must warn, not block
                    warnings.append(
                        f"pre-migration backup failed ({exc}); continuing without it"
                    )
            store.migrate(MIGRATIONS)
            coordinator = WriteCoordinator(
                store, name="main", max_queue=config.get("storage.write_queue_size")
            )
        except Exception:
            store.close()
            raise

        events_path = config.path("storage.events_path")
        try:
            events = EventStore(
                events_path, capture_level=config.get("trace.capture_level")
            )
        except Exception as exc:  # noqa: BLE001 - tracing must never block the app
            warnings.append(
                f"trace store unavailable ({exc}); continuing without tracing"
            )
            events = EventStore(
                Path(events_path).with_name("events-fallback.db"),
                capture_level="summary",
            )

        conversations = ConversationManager(store, coordinator, events=events)
        projects = ProjectManager(
            store,
            coordinator,
            events=events,
            projects_root=str(config.path("paths.projects")),
        )
        memory = MemoryManager(
            store,
            coordinator,
            events=events,
            artifacts_root=str(config.path("paths.artifacts")),
            duplicate_threshold=config.get("memory.duplicate_threshold"),
            active_ttl_minutes=config.get("memory.active_ttl_minutes"),
        )
        models = ModelManager(
            store,
            coordinator,
            events=events,
            models_root=str(config.path("paths.models")),
        )
        providers = ProviderManager(store, coordinator, events=events)
        embedding_provider, embedding_warning = _build_embedding_provider(config)
        if embedding_warning:
            warnings.append(embedding_warning)
        embeddings = EmbeddingManager(
            store,
            coordinator,
            events=events,
            conversations=conversations,
            memory=memory,
            provider=embedding_provider,
        )
        memory.embedding_index = embeddings if embedding_provider is not None else None
        permissions = PermissionManager(
            store, coordinator, events=events, config=config
        )
        tool_runtime, tool_warning = _build_tool_runtime(config)
        if tool_warning:
            warnings.append(tool_warning)
        context = ContextManager(
            store,
            coordinator,
            events=events,
            conversations=conversations,
            memory=memory,
            context_limit=config.get("model.context_limit"),
            output_budget=config.get("model.output_budget"),
            reserve_tokens=config.get("context.reserve_tokens"),
            memory_budget_ratio=config.get("context.memory_budget_ratio"),
            protect_pinned=config.get("context.protect_pinned"),
            default_strategy=config.get("context.strategy"),
        )
        ws = cls(
            config=config,
            store=store,
            coordinator=coordinator,
            events=events,
            conversations=conversations,
            projects=projects,
            memory=memory,
            models=models,
            providers=providers,
            permissions=permissions,
            tools=None,
            router=None,
            context=context,
            embeddings=embeddings,
            warnings=warnings,
            _runtimes={},
        )
        ws.tools = ToolManager(
            store,
            coordinator,
            permissions=permissions,
            events=events,
            config=config,
            runtime=tool_runtime,
            info_provider=ws.tool_info,
        )
        ws.mcp = McpManager(
            store, coordinator, events=events, config=config, tools=ws.tools
        )
        ws.extensions = ExtensionManager(
            store,
            coordinator,
            events=events,
            config=config,
            tools=ws.tools,
            runtime=ExtensionRuntime(
                max_output_bytes=int(config.get("tools.max_output_bytes")),
                timeout_seconds=int(config.get("tools.timeout_seconds")),
            ),
        )
        ws.versions = VersionManager(
            store,
            coordinator,
            events=events,
            max_bytes=int(config.get("tasks.max_version_bytes")),
        )
        ws.tasks = TaskManager(
            store,
            coordinator,
            events=events,
            versions=ws.versions,
            home=str(config.path("paths.home")),
            max_version_bytes=int(config.get("tasks.max_version_bytes")),
        )
        ws.tools.tasks = ws.tasks
        ws.jobs = JobManager(
            store,
            coordinator,
            events=events,
            config=config,
            tasks=ws.tasks,
        )
        ws.scheduler = JobRunner(ws, poll=float(config.get("scheduler.poll_seconds")))
        ws.workflows = WorkflowManager(
            store,
            coordinator,
            events=events,
            config=config,
            tools=ws.tools,
        )
        ws.reproduction = ReproductionManager(
            store,
            coordinator,
            tasks=ws.tasks,
            models=models,
            tools=ws.tools,
            conversations=conversations,
            mcp=ws.mcp,
            extensions=ws.extensions,
            config=config,
            events=events,
            home=str(config.path("paths.home")),
            app_version=__version__,
            schema_version=SCHEMA_VERSION,
        )
        ws.coding = CodeManager(store, coordinator, events=events)
        ws.experiments = ExperimentManager(store, coordinator, events=events)
        ws.play = PlayManager(store, coordinator, events=events)
        ws.media = MediaManager(store, coordinator, events=events)
        ws.datasets = DatasetManager(store, coordinator, events=events)
        ws.training = TrainingManager(store, coordinator, events=events)
        ws.remote = RemoteManager(store, coordinator, events=events)
        ws.execution = ExecutionManager(store, coordinator, events=events)
        ws.scenes = SceneManager(store, coordinator, events=events)
        ws.automations = AutomationManager(
            store, coordinator, jobs=ws.jobs, events=events
        )
        ws.research = ResearchManager(store, coordinator, events=events, config=config)
        ws.learning = LearningManager(store, coordinator, events=events, config=config)
        # Register every domain handler before replay, and replay before recovery
        # or plugin restoration consumes durable state. An empty registry skips intents.
        try:
            replayed = coordinator.replay()
        except Exception as exc:  # noqa: BLE001
            ws.warnings.append(f"journal replay failed: {exc}")
            replayed = 0

        if config.get("scheduler.reap_on_open"):
            try:
                reaped = ws.jobs.reap_expired()
                if reaped["expired"]:
                    ws.warnings.append(
                        f"failed {reaped['expired']} job(s) whose hard deadline had passed"
                    )
            except Exception as exc:  # noqa: BLE001 - a bad row must not block startup
                ws.warnings.append(f"could not reap expired jobs: {exc}")
        if config.get("scheduler.recover_on_open"):
            try:
                recovered = ws.jobs.recover()
                if recovered["requeued"] or recovered["interrupted"]:
                    ws.warnings.append(
                        f"recovered {recovered['requeued']} job(s) left behind by a dead worker "
                        f"({recovered['interrupted']} marked interrupted)"
                    )
            except Exception as exc:  # noqa: BLE001
                ws.warnings.append(f"could not recover orphaned jobs: {exc}")
        if config.get("tasks.interrupt_stale_on_open"):
            try:
                swept = ws.tasks.interrupt_stale(protect=ws.jobs.protected_task_ids())
                if swept["interrupted"]:
                    ws.warnings.append(
                        f"marked {swept['interrupted']} task(s) as interrupted: the process that "
                        "owned them is gone"
                    )
                if swept["skipped"]:
                    ws.warnings.append(
                        f"{len(swept['skipped'])} running task(s) belong to another live process "
                        "or are tracked manually; they were left alone"
                    )
            except Exception as exc:  # noqa: BLE001 - a stale row must not block startup
                ws.warnings.append(f"could not sweep interrupted tasks: {exc}")
        try:
            restored_mcp = ws.mcp.restore()
            restored_ext = ws.extensions.restore()
            if restored_mcp["tools"] or restored_ext["tools"]:
                ws.warnings.append(
                    f"restored {restored_mcp['tools']} MCP tool(s) from {restored_mcp['servers']} "
                    f"server(s) and {restored_ext['tools']} extension tool(s) from "
                    f"{restored_ext['extensions']} extension(s)"
                )
        except Exception as exc:  # noqa: BLE001 - a bad plugin must not stop the workspace
            ws.warnings.append(f"could not restore dynamic tools: {exc}")
        ws.search = SearchService(ws)
        ws.simple = SimpleMode(ws)
        ws.router = ModelRouter(
            models,
            config=config,
            runtime_for=ws.runtime_for,
            availability_check=ws.runtime_availability,
            remote_check=ws.assert_remote_allowed,
            events=events,
        )
        if replayed:
            ws.warnings.append(
                f"replayed {replayed} interrupted write(s) from the journal"
            )
        allow_double = allow_test_double or os.environ.get(ENV_FLAG) == "1"
        ws._allow_test_double = allow_double  # type: ignore[attr-defined]
        events.record(
            "system",
            "workspace.opened",
            level="summary",
            payload={
                "home": str(config.home),
                "schema_version": SCHEMA_VERSION,
                "replayed": replayed,
                "warnings": warnings,
            },
        )
        if config.get("trace.redact_secrets"):
            from archx_agent.helpers import redaction

            for key in (
                "ARCHX_GEMINI_API_KEY",
                "ARCHX_OPENAI_API_KEY",
                "GEMINI_API_KEY",
                "OPENAI_API_KEY",
            ):
                value = os.environ.get(key)
                if value:
                    redaction.register_secret(value)
        return ws

    def close(self) -> None:
        if self.mcp is not None:
            try:
                self.mcp.close()
            except Exception:  # noqa: BLE001 - closing must never block shutdown
                pass
        for runtime in self._runtimes.values():
            try:
                runtime.close()
            except Exception:  # noqa: BLE001
                pass
        self._runtimes.clear()
        try:
            self.events.record("system", "workspace.closed", level="summary")
            self.events.flush(2.0)
        except Exception:  # noqa: BLE001
            pass
        self.coordinator.stop()
        self.events.close()
        self.store.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
