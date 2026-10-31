"""Services operations for workspace composition."""

from __future__ import annotations

from archx_agent.helpers.exceptions import (
    ConfigError,
)
from archx_agent.application.automations import AutomationService


class WorkspaceServicesMixin:
    """Services responsibility for Workspace."""

    @property
    def agent(self):
        """The workflow runner (imported lazily so the composition root stays acyclic)."""
        from archx_agent.application.agent import AgentRunner

        return AgentRunner(self)

    @property
    def researcher(self):
        """The research runner (imported lazily so the composition root stays acyclic)."""
        from archx_agent.application.researcher import ResearchRunner

        return ResearchRunner(self)

    @property
    def tutor(self):
        """The learning service (imported lazily so the composition root stays acyclic)."""
        from archx_agent.application.learning import LearningService

        return LearningService(self)

    @property
    def code(self):
        """The coding workspace (imported lazily to keep the composition root acyclic)."""
        from archx_agent.application.coding import CodingWorkspace

        return CodingWorkspace(self)

    @property
    def experiment(self):
        """The experimental-mode runner (imported lazily to keep the composition root acyclic)."""
        from archx_agent.application.experiments import ExperimentService

        return ExperimentService(self)

    @property
    def voice(self):
        """The voice and media service (imported lazily to keep the composition root acyclic)."""
        from archx_agent.application.voice import VoiceService

        return VoiceService(self)

    @property
    def data(self):
        """The dataset service (imported lazily to keep the composition root acyclic)."""
        from archx_agent.application.datasets import DatasetService

        return DatasetService(self)

    @property
    def trainer(self):
        """The training service (imported lazily to keep the composition root acyclic)."""
        from archx_agent.application.training import TrainingService

        return TrainingService(self)

    @property
    def remotes(self):
        """The remote compute service (imported lazily to keep the composition root acyclic)."""
        from archx_agent.application.remote import RemoteService

        return RemoteService(self)

    @property
    def automation(self):
        return AutomationService(self)

    @property
    def scene_workflow(self):
        from archx_agent.application.scenes import SceneService

        return SceneService(self)

    @property
    def exec_env(self):
        """Execution targets and runs (imported lazily to keep the composition root acyclic)."""
        from archx_agent.application.execution import ExecutionService

        return ExecutionService(self)

    @property
    def play_mode(self):
        """Games and simulations (imported lazily to keep the composition root acyclic)."""
        from archx_agent.application.play import PlayService

        return PlayService(self)

    @property
    def chat(self):
        """The chat service (imported lazily to keep the composition root acyclic)."""
        from archx_agent.application.chat import ChatService

        if self.context is None:
            raise ConfigError("workspace has no context manager")
        return ChatService(self, self.context)
