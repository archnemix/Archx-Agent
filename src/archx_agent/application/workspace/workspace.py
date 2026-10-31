"""Workspace fields and composed accessors for workspace composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from archx_agent.adapters.model_runtime import ModelRuntime
from archx_agent.helpers.config import Config
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
from archx_agent.application.search import SearchService
from archx_agent.application.simple import SimpleMode
from archx_agent.application.workspace.lifecycle import WorkspaceLifecycleMixin
from archx_agent.application.workspace.services import WorkspaceServicesMixin
from archx_agent.application.workspace.models.availability import (
    WorkspaceModelsAvailabilityMixin,
)
from archx_agent.application.workspace.models.policy import WorkspaceModelsPolicyMixin
from archx_agent.application.workspace.models.runtimes import (
    WorkspaceModelsRuntimesMixin,
)
from archx_agent.application.workspace.models.routing import WorkspaceModelsRoutingMixin
from archx_agent.application.workspace.presentation import WorkspacePresentationMixin


@dataclass
class Workspace(
    WorkspaceLifecycleMixin,
    WorkspaceServicesMixin,
    WorkspaceModelsAvailabilityMixin,
    WorkspaceModelsPolicyMixin,
    WorkspaceModelsRuntimesMixin,
    WorkspaceModelsRoutingMixin,
    WorkspacePresentationMixin,
):
    """Compose workspace composition around shared collaborators."""

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

    learning: LearningManager | None = None

    coding: CodeManager | None = None

    experiments: ExperimentManager | None = None

    play: PlayManager | None = None

    media: MediaManager | None = None

    datasets: DatasetManager | None = None

    training: TrainingManager | None = None

    remote: RemoteManager | None = None

    execution: ExecutionManager | None = None

    scenes: SceneManager | None = None

    automations: AutomationManager | None = None

    reproduction: ReproductionManager | None = None

    router: Any = None

    context: ContextManager | None = None

    embeddings: EmbeddingManager | None = None

    warnings: list[str] = field(default_factory=list)

    _runtimes: dict[str, ModelRuntime] = field(default_factory=dict)
