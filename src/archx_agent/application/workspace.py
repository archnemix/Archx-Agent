"""The workspace: one opened Archx environment (database, trace, managers, runtimes).

Opening a workspace is explicit and ordered:

1. resolve configuration (file + env + overrides);
2. create directories;
3. open the primary database;
4. back it up before a schema upgrade, then migrate;
5. open the trace database (separate file, best effort);
6. create the shared write coordinator and replay any interrupted intents;
7. wire managers and register their write kinds.

Failure at any step raises a domain error with enough context to act on, and
never leaves a half-initialised workspace silently usable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from archx_agent import __version__
from archx_agent.adapters.embedding_runtime import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    HttpEmbeddingProvider,
    SentenceTransformerProvider,
)
from archx_agent.adapters.http_runtime import HttpChatRuntime
from archx_agent.adapters.llama_cpp_runtime import LlamaCppRuntime
from archx_agent.adapters.extension_runtime import ExtensionRuntime
from archx_agent.adapters.local_tools import LocalToolRuntime
from archx_agent.adapters.model_runtime import ModelRuntime, ModelSpec
from archx_agent.adapters.scripted_runtime import ENV_FLAG, ScriptedRuntime
from archx_agent.helpers.backup_recovery import create_backup
from archx_agent.helpers.config import Config, load_config, resolve_secret
from archx_agent.helpers.events import EventStore
from archx_agent.helpers.exceptions import (
    ConfigError,
    ConsentRequiredError,
    ModelNotFoundError,
    PermissionDeniedError,
    PrivacyUnknownError,
    ValidationError,
)
from archx_agent.helpers.sqlite_store import SqliteStore
from archx_agent.helpers.timeutil import iso_now
from archx_agent.helpers.write_coordinator import WriteCoordinator
from archx_agent.managers.context import ContextManager
from archx_agent.managers.embeddings import EmbeddingManager
from archx_agent.managers.conversation import ConversationManager
from archx_agent.managers.extensions import ExtensionManager
from archx_agent.managers.jobs import JobManager
from archx_agent.managers.mcp import McpManager
from archx_agent.managers.memory import MemoryManager
from archx_agent.managers.models import ModelManager, ModelRecord
from archx_agent.managers.permissions import PermissionManager
from archx_agent.managers.projects import ProjectManager
from archx_agent.managers.providers import ProviderManager, is_loopback_url
from archx_agent.managers.reproduction import ReproductionManager
from archx_agent.managers.research import ResearchManager
from archx_agent.managers.tasks import TaskManager
from archx_agent.managers.tools import ToolManager
from archx_agent.managers.versions import VersionManager
from archx_agent.managers.workflows import WorkflowManager
from archx_agent.application.router import ModelRouter
from archx_agent.application.scheduler import JobRunner
from archx_agent.application.search import SearchService
from archx_agent.application.simple import SimpleMode
from archx_agent.managers.schema import MIGRATIONS, SCHEMA_VERSION


@dataclass
class Workspace:
    config: Config
    store: SqliteStore
    coordinator: WriteCoordinator
    events: EventStore
    conversations: ConversationManager
    projects: ProjectManager
    memory: MemoryManager
    models: ModelManager
    providers: ProviderManager | None = None
    permissions: PermissionManager | None = None
    tools: ToolManager | None = None
    mcp: McpManager | None = None
    extensions: ExtensionManager | None = None
    versions: VersionManager | None = None
    tasks: TaskManager | None = None
    workflows: WorkflowManager | None = None
    jobs: JobManager | None = None
    scheduler: Any = None
    search: SearchService | None = None
    simple: SimpleMode | None = None
    research: ResearchManager | None = None
    reproduction: ReproductionManager | None = None
    router: Any = None
    context: ContextManager | None = None
    embeddings: EmbeddingManager | None = None
    warnings: list[str] = field(default_factory=list)
    _runtimes: dict[str, ModelRuntime] = field(default_factory=dict)

    # -- lifecycle --------------------------------------------------------
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
    ) -> "Workspace":
        config = load_config(home=home, config_path=config_path, env=env, overrides=overrides, create=create)
        # The environment flag is a legitimate way to enable the test double (the CLI
        # passes it explicitly too); treat either as "the user asked for it".
        environ = os.environ if env is None else env
        enabled = allow_test_double if allow_test_double is not None else (
            environ.get(ENV_FLAG) == "1"
        )
        return cls.from_config(config, allow_test_double=enabled)

    @classmethod
    def from_config(cls, config: Config, *, allow_test_double: bool = False) -> "Workspace":
        warnings: list[str] = []
        config.ensure_dirs()
        db_path = config.path("storage.db_path")
        store = SqliteStore(db_path, wal=config.get("storage.journal_mode") == "wal")
        try:
            current_version = store.schema_version()
            target = SCHEMA_VERSION
            if current_version and current_version < target and config.get("storage.auto_backup"):
                try:
                    info = create_backup(db_path, config.path("paths.backups"), label="pre-migration")
                    warnings.append(f"backed up v{current_version} database before migration: {info.path.name}")
                except Exception as exc:  # noqa: BLE001 - backup failure must warn, not block
                    warnings.append(f"pre-migration backup failed ({exc}); continuing without it")
            store.migrate(MIGRATIONS)
            coordinator = WriteCoordinator(store, name="main", max_queue=config.get("storage.write_queue_size"))
        except Exception:
            store.close()
            raise

        events_path = config.path("storage.events_path")
        try:
            events = EventStore(events_path, capture_level=config.get("trace.capture_level"))
        except Exception as exc:  # noqa: BLE001 - tracing must never block the app
            warnings.append(f"trace store unavailable ({exc}); continuing without tracing")
            events = EventStore(Path(events_path).with_name("events-fallback.db"), capture_level="summary")

        try:
            replayed = coordinator.replay()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"journal replay failed: {exc}")
            replayed = 0

        conversations = ConversationManager(store, coordinator, events=events)
        projects = ProjectManager(
            store, coordinator, events=events, projects_root=str(config.path("paths.projects"))
        )
        memory = MemoryManager(
            store,
            coordinator,
            events=events,
            artifacts_root=str(config.path("paths.artifacts")),
            duplicate_threshold=config.get("memory.duplicate_threshold"),
            active_ttl_minutes=config.get("memory.active_ttl_minutes"),
        )
        models = ModelManager(store, coordinator, events=events, models_root=str(config.path("paths.models")))
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
        permissions = PermissionManager(store, coordinator, events=events, config=config)
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
        ws.mcp = McpManager(store, coordinator, events=events, config=config, tools=ws.tools)
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
        ws.research = ResearchManager(
            store, coordinator, events=events, config=config
        )
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
            ws.warnings.append(f"replayed {replayed} interrupted write(s) from the journal")
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

            for key in ("ARCHX_GEMINI_API_KEY", "ARCHX_OPENAI_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
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

    @property
    def agent(self):
        """The workflow runner (imported lazily so the composition root stays acyclic)."""
        from .agent import AgentRunner

        return AgentRunner(self)

    @property
    def researcher(self):
        """The research runner (imported lazily so the composition root stays acyclic)."""
        from .researcher import ResearchRunner

        return ResearchRunner(self)

    @property
    def chat(self):
        """The chat service (imported lazily to keep the composition root acyclic)."""
        from .chat import ChatService

        if self.context is None:
            raise ConfigError("workspace has no context manager")
        return ChatService(self, self.context)

    def __enter__(self) -> "Workspace":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- helpers ----------------------------------------------------------
    @property
    def allow_test_double(self) -> bool:
        return bool(getattr(self, "_allow_test_double", False))

    def info(self) -> dict[str, Any]:
        return {
            "home": str(self.config.home),
            "database": str(self.store.path),
            "events": str(self.events.path),
            "schema_version": self.store.schema_version(),
            "expected_schema_version": SCHEMA_VERSION,
            "models": len(self.models.list()),
            "conversations": self.conversations.stats()["active_conversations"],
            "memories": self.memory.stats()["total_active"],
            "tasks": self.tasks.stats()["total"] if self.tasks is not None else 0,
            "workflows": self.workflows.stats()["total"] if self.workflows is not None else 0,
            "warnings": self.warnings,
            "opened_at": iso_now(),
        }

    # -- runtime resolution ----------------------------------------------
    def runtime_availability(self, record: ModelRecord) -> tuple[bool, str]:
        """Can this model run here, checked *without* loading anything?

        Loading a GGUF to answer "is it usable?" would cost seconds and gigabytes; the
        router needs a cheap, honest answer instead. The checks mirror the runtimes'
        own preconditions exactly.
        """
        if record.runtime == "llama-cpp":
            from archx_agent.adapters.llama_cpp_runtime import INSTALL_HINT, llama_cpp_available

            if not llama_cpp_available():
                return False, f"llama-cpp-python is not installed ({INSTALL_HINT})"
            if not record.path or not Path(record.path).exists():
                return False, f"model file not found: {record.path}"
            return True, "ready"
        base_url = (record.facts or {}).get("base_url")
        if record.runtime in ("openai-http", "http"):
            if not base_url:
                return False, "no base_url configured"
            return True, "ready"
        if record.runtime == "scripted":
            if not self.allow_test_double:
                return False, "the simulated test double is disabled (use --allow-simulated)"
            return True, "ready (simulated - performs no inference)"
        return False, f"unknown runtime {record.runtime!r}"

    # -- tools ------------------------------------------------------------
    def tool_roots(self, project_id: str | None = None) -> list[str]:
        """Directories tools may touch: explicit config, else the project, else a sandbox."""
        if self.tools is not None:
            live = self.tools.roots()
            if live:
                return live
        configured = [str(x).strip() for x in (self.config.get("tools.roots") or []) if str(x).strip()]
        if configured:
            return [str(Path(x).expanduser().resolve()) for x in configured]
        if project_id and self.projects is not None:
            record = self.projects.get(project_id)
            if record.is_ok and record.value.root_path:
                return [str(Path(record.value.root_path).expanduser().resolve())]
        return [str(Path(self.config.path("paths.home")) / "workspace")]

    def extensions_dir(self) -> Path:
        configured = self.config.get("extensions.directory")
        directory = Path(configured).expanduser() if configured else Path(self.config.path("paths.home")) / "extensions"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def tool_info(self) -> dict[str, Any]:
        info = self.info() if self.tools is not None else {"home": str(self.config.home)}
        return {
            "home": info.get("home", str(self.config.home)),
            "database": info.get("database"),
            "schema_version": info.get("schema_version"),
            "models": info.get("models"),
            "conversations": info.get("conversations"),
            "memories": info.get("memories"),
        }

    def runtime_for(self, record: ModelRecord) -> ModelRuntime:
        self.assert_remote_allowed(record)
        key = f"{record.runtime}:{record.id}"
        cached = self._runtimes.get(key)
        if cached is not None and cached.loaded:
            return cached
        runtime = self._build_runtime(record)
        self._runtimes[key] = runtime
        return runtime

    def assert_remote_allowed(self, record: ModelRecord) -> None:
        """Refuse to send data off this machine unless the user opted in.

        Three independent gates, all of which must pass for a non-loopback endpoint:

        1. ``model.local_only`` must be false (it is true by default);
        2. the endpoint must belong to a registered provider;
        3. that provider must have *known* privacy terms and recorded consent.
        """
        base_url = (record.facts or {}).get("base_url") if record.facts else None
        if record.runtime != "openai-http" or not base_url:
            return
        if is_loopback_url(base_url):
            return
        if self.config.get("model.local_only"):
            raise PermissionDeniedError(
                "refusing to send data to a remote endpoint: model.local_only is true. "
                "Register the endpoint as a provider and set model.local_only=false deliberately."
            )
        provider = self._provider_for(record)
        if provider is None:
            raise ConsentRequiredError(
                f"the endpoint {base_url} is not a registered provider. Add it with "
                "`archx-agent providers add <name> --template openai` (or --base-url), confirm its "
                "privacy terms and record consent before sending anything."
            )
        if not provider.privacy_known:
            raise PrivacyUnknownError(provider.blocking_reason() or "provider privacy terms unknown")
        if not provider.consented:
            raise ConsentRequiredError(provider.blocking_reason() or "provider consent missing")

    def _provider_for(self, record: ModelRecord):
        if self.providers is None:
            return None
        base_url = (record.facts or {}).get("base_url")
        for provider in self.providers.list():
            if base_url and provider.base_url and provider.base_url.rstrip("/") == str(base_url).rstrip("/"):
                return provider
            if provider.slug == (record.provider or "").lower() or provider.name == record.provider:
                return provider
        return None

    def record_usage(self, record: ModelRecord, *, tokens_in: int, tokens_out: int, ok: bool, error: str | None = None) -> None:
        """Attribute usage to the owning provider when one is registered."""
        if self.providers is None:
            return
        provider = self._provider_for(record)
        if provider is None:
            return
        self.providers.record_usage(
            provider.id,
            model_ref=record.model_ref or record.name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            ok=ok,
            error=error,
        )

    def _build_runtime(self, record: ModelRecord) -> ModelRuntime:
        if record.runtime == "llama-cpp":
            runtime = LlamaCppRuntime(n_ctx=record.context_length)
            runtime.load(
                ModelSpec(
                    id=record.id,
                    provider=record.provider,
                    runtime=record.runtime,
                    path=record.path,
                    context_length=record.context_length or self.config.get("model.context_limit"),
                    quantization=record.quantization,
                )
            )
            return runtime
        if record.runtime in ("openai-http", "http"):
            base_url = (record.facts or {}).get("base_url") or os.environ.get("ARCHX_HTTP_BASE_URL")
            if not base_url:
                raise ConfigError(
                    f"model {record.name!r} uses an HTTP runtime but no base_url is configured "
                    "(set model facts.base_url or ARCHX_HTTP_BASE_URL)"
                )
            ref = (record.user_metadata or {}).get("credential_ref") or (record.facts or {}).get("credential_ref")
            api_key = resolve_secret(ref) if ref else None
            runtime = HttpChatRuntime(base_url, api_key=api_key, provider=record.provider)
            runtime.load(
                ModelSpec(
                    id=record.id,
                    provider=record.provider,
                    runtime=record.runtime,
                    model=record.model_ref,
                    context_length=record.context_length or self.config.get("model.context_limit"),
                )
            )
            return runtime
        if record.runtime == "scripted":
            runtime = ScriptedRuntime(enabled=self.allow_test_double)
            runtime.load(
                ModelSpec(
                    id=record.id,
                    provider=record.provider,
                    runtime=record.runtime,
                    model=record.model_ref,
                    context_length=record.context_length or self.config.get("model.context_limit"),
                )
            )
            return runtime
        raise ValidationError(
            f"model {record.name!r} has unknown runtime {record.runtime!r} "
            "(expected llama-cpp, openai-http or scripted)"
        )

    def resolve_model(self, model_id: str | None = None, *, task: str = "chat") -> ModelRecord:
        """Resolve which model to use for a task (capability-safe routing, M21)."""
        decision = self.route_model(task=task, model_id=model_id)
        if decision.chosen is None:  # pragma: no cover - route_model raises instead
            raise ModelNotFoundError("no model is eligible", task=task)
        return decision.chosen

    def route_model(
        self,
        *,
        task: str = "chat",
        model_id: str | None = None,
        required: Sequence[str] | None = None,
        allow_unverified: bool | None = None,
        allow_cloud: bool | None = None,
        min_context_tokens: int | None = None,
        exclude: Sequence[str] = (),
    ) -> Any:
        """Route a task to a model, returning the full decision."""
        if self.router is None:  # pragma: no cover - always built in from_config
            raise ConfigError("workspace has no router")
        return self.router.route(
            task,
            required=required,
            model_id=model_id,
            allow_unverified=allow_unverified,
            allow_cloud=allow_cloud,
            allow_simulated=self.allow_test_double,
            min_context_tokens=min_context_tokens,
            exclude=exclude,
        )

    def model_choice_explanation(self, record: ModelRecord) -> dict[str, Any]:
        return {
            "model_id": record.id,
            "name": record.name,
            "provider": record.provider,
            "runtime": record.runtime,
            # Locality is derived from the endpoint, never from a label: a model
            # called "local-http" pointing at api.openai.com is not local.
            "local": (
                True
                if record.runtime in ("llama-cpp", "scripted")
                else is_loopback_url((record.facts or {}).get("base_url"))
            ),
            "verified_capabilities": record.verified_capabilities,
            "verification_state": record.verification_state,
            "policy_local_only": bool(self.config.get("model.local_only")),
            "baseline": record.user_metadata.get("baseline", False),
        }


def _build_embedding_provider(config: Config) -> tuple[EmbeddingProvider | None, str | None]:
    """Build the embedding provider, or explain why there is none.

    Remote embeddings are off by default and always require an explicit
    preference; we never silently send memory text to a remote service.
    """
    if not config.get("memory.embeddings_enabled"):
        return None, None
    kind = (config.get("memory.embedding_provider") or "local-hash").lower()
    if kind in ("local-hash", "hash", "archx-hash"):
        try:
            return HashEmbeddingProvider(), None
        except Exception as exc:  # noqa: BLE001
            return None, f"local hash embeddings unavailable: {exc}"
    if kind in ("http", "http-embeddings"):
        base_url = os.environ.get("ARCHX_EMBEDDING_BASE_URL", "")
        model = os.environ.get("ARCHX_EMBEDDING_MODEL", "")
        if not base_url or not model:
            return None, (
                "memory.embedding_provider=http needs ARCHX_EMBEDDING_BASE_URL and ARCHX_EMBEDDING_MODEL"
            )
        if not config.get("memory.remote_embeddings") and base_url.startswith(("http://", "https://")):
            host = base_url.split("//")[-1].split("/")[0].split(":")[0]
            if host not in ("127.0.0.1", "localhost", "::1"):
                return None, (
                    "remote embedding endpoint configured but memory.remote_embeddings is false; "
                    "embeddings are disabled"
                )
        api_key = os.environ.get("ARCHX_EMBEDDING_API_KEY")
        try:
            return HttpEmbeddingProvider(base_url, model=model, api_key=api_key), None
        except Exception as exc:  # noqa: BLE001
            return None, f"http embedding provider failed to initialise: {exc}"
    if kind in ("sentence-transformers", "st"):
        try:
            return SentenceTransformerProvider(), None
        except Exception as exc:  # noqa: BLE001
            return None, (
                f"local semantic embeddings unavailable ({exc}); "
                "keyword retrieval stays active and is reported as degraded"
            )
    return None, f"unknown embedding provider {kind!r}; semantic retrieval disabled"


def _build_tool_runtime(config) -> tuple[LocalToolRuntime | None, str | None]:
    """Create the file/shell sandbox, or explain why tools cannot run."""
    roots = [str(Path(x).expanduser()) for x in (config.get("tools.roots") or []) if str(x).strip()]
    if not roots:
        roots = [str(Path(config.path("paths.home")) / "workspace")]
    try:
        for root in roots:
            Path(root).mkdir(parents=True, exist_ok=True)
        runtime = LocalToolRuntime(
            roots=tuple(roots),
            max_file_bytes=int(config.get("tools.max_file_bytes")),
            max_output_bytes=int(config.get("tools.max_output_bytes")),
            timeout_seconds=int(config.get("tools.timeout_seconds")),
            denylist=tuple(str(x) for x in (config.get("tools.shell_denylist") or [])),
            home=str(Path(config.path("paths.home"))),
        )
        return runtime, None
    except Exception as exc:  # noqa: BLE001 - tools are optional, the rest still works
        return None, f"tool runtime unavailable ({exc}); tools will refuse to run"


def open_workspace(
    *,
    home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
    allow_test_double: bool | None = None,
) -> Workspace:
    return Workspace.open(
        home=home,
        config_path=config_path,
        env=env,
        overrides=overrides,
        allow_test_double=allow_test_double,
    )


__all__ = ["Workspace", "open_workspace"]
