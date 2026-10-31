"""Compose GUI routes, authentication, dispatch and static assets."""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any
from archx_agent.interfaces.gui.protocol import (
    ASSETS as ASSETS,
    COOKIE_NAME as COOKIE_NAME,
    CSRF_HEADER as CSRF_HEADER,
    CSRF_VALUE as CSRF_VALUE,
    TOKEN_PARAM as TOKEN_PARAM,
    _SECURITY_HEADERS as _SECURITY_HEADERS,
    _CONTENT_TYPES as _CONTENT_TYPES,
    ApiError as ApiError,
    error_for as error_for,
    Request as Request,
    Response as Response,
    SSEStream as SSEStream,
    Route as Route,
    route as route,
    _positive_int as _positive_int,
)
from archx_agent.interfaces.gui.routes.overview import OverviewRoutes
from archx_agent.interfaces.gui.routes.models import ModelsRoutes
from archx_agent.interfaces.gui.routes.chat import ChatRoutes
from archx_agent.interfaces.gui.routes.memory import MemoryRoutes
from archx_agent.interfaces.gui.routes.jobs import JobsRoutes
from archx_agent.interfaces.gui.routes.access import AccessRoutes
from archx_agent.interfaces.gui.routes.research import ResearchRoutes
from archx_agent.interfaces.gui.routes.learning import LearningRoutes
from archx_agent.interfaces.gui.routes.code import CodeRoutes
from archx_agent.interfaces.gui.routes.experiments import ExperimentsRoutes
from archx_agent.interfaces.gui.routes.play import PlayRoutes
from archx_agent.interfaces.gui.routes.voice import VoiceRoutes
from archx_agent.interfaces.gui.routes.datasets import DatasetsRoutes
from archx_agent.interfaces.gui.routes.training import TrainingRoutes
from archx_agent.interfaces.gui.routes.remote import RemoteRoutes
from archx_agent.interfaces.gui.routes.exec import ExecRoutes
from archx_agent.interfaces.gui.routes.automations import AutomationsRoutes
from archx_agent.interfaces.gui.routes.scenes import ScenesRoutes

from .authentication import GuiAuthenticationMixin
from .dispatch import GuiDispatchMixin
from .assets import GuiAssetsMixin

class GuiApi(GuiAuthenticationMixin, GuiDispatchMixin, GuiAssetsMixin, OverviewRoutes, ModelsRoutes, ChatRoutes, MemoryRoutes, JobsRoutes, AccessRoutes, ResearchRoutes, LearningRoutes, CodeRoutes, ExperimentsRoutes, PlayRoutes, VoiceRoutes, DatasetsRoutes, TrainingRoutes, RemoteRoutes, ExecRoutes, AutomationsRoutes, ScenesRoutes):
    'Every GUI operation, with no sockets involved (so it is testable and reusable).'

    def __init__(
        self,
        workspace,
        *,
        token: str | None = None,
        token_ttl_minutes: int = 720,
        allow_remote: bool = False,
        max_body_bytes: int = 1_048_576,
        max_auth_failures: int = 20,
    ) -> None:
        self.ws = workspace
        self.token = token or secrets.token_urlsafe(24)
        self.token_ttl_minutes = max(1, int(token_ttl_minutes))
        self.allow_remote = bool(allow_remote)
        self.max_body_bytes = max(1024, int(max_body_bytes))
        self.max_auth_failures = max(3, int(max_auth_failures))
        self.started_at = time.time()
        self.requests = 0
        self.auth_failures = 0
        self._opener: Any = None
        self._auth_window: list[float] = []
        self._lock = threading.Lock()
