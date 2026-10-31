"""Compose LearningService responsibilities and initialize dependencies."""

from __future__ import annotations


from .practice import LearningServicePracticeMixin
from .scheduling import LearningServiceSchedulingMixin
from .planning import LearningServicePlanningMixin
from .reporting import LearningServiceReportingMixin

class LearningService(LearningServicePracticeMixin, LearningServiceSchedulingMixin, LearningServicePlanningMixin, LearningServiceReportingMixin):
    'Sessions, hints, grades and schedules. The manager owns the rows.'

    def __init__(self, workspace) -> None:
        self.ws = workspace
        self.manager = workspace.learning
