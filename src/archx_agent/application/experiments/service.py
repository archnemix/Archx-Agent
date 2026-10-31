"""Compose ExperimentService responsibilities and initialize dependencies."""

from __future__ import annotations


from .catalogue import ExperimentServiceCatalogueMixin
from .execution import ExperimentServiceExecutionMixin
from .metrics import ExperimentServiceMetricsMixin

class ExperimentService(ExperimentServiceCatalogueMixin, ExperimentServiceExecutionMixin, ExperimentServiceMetricsMixin):
    'Create experiments, run them, and compare the runs honestly.'

    def __init__(self, ws) -> None:
        self.ws = ws
