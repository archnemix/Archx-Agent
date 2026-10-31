"""Compose AgentRunner responsibilities and initialize dependencies."""

from __future__ import annotations


from .execution import AgentRunnerExecutionMixin
from .steps import AgentRunnerStepsMixin
from .planning import AgentRunnerPlanningMixin

class AgentRunner(AgentRunnerExecutionMixin, AgentRunnerStepsMixin, AgentRunnerPlanningMixin):
    'Executes stored workflows against this workspace.'

    def __init__(self, workspace) -> None:
        self.ws = workspace
