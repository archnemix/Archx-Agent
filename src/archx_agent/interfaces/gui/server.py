"""Public GUI server API; separate application, transport and lifecycle owners."""

import functools as functools
import hashlib as hashlib
import hmac as hmac
import json as json
import secrets as secrets
import socket as socket
import threading as threading
import time as time
from http.cookies import SimpleCookie as SimpleCookie
from http.server import BaseHTTPRequestHandler as BaseHTTPRequestHandler, ThreadingHTTPServer as ThreadingHTTPServer
from pathlib import Path as Path
from typing import Any as Any
from urllib.parse import parse_qs as parse_qs, unquote as unquote, urlsplit as urlsplit
from archx_agent import __version__ as __version__
from archx_agent.interfaces.gui.protocol import ASSETS as ASSETS, COOKIE_NAME as COOKIE_NAME, CSRF_HEADER as CSRF_HEADER, CSRF_VALUE as CSRF_VALUE, TOKEN_PARAM as TOKEN_PARAM, _SECURITY_HEADERS as _SECURITY_HEADERS, _CONTENT_TYPES as _CONTENT_TYPES, ApiError as ApiError, error_for as error_for, Request as Request, Response as Response, SSEStream as SSEStream, Route as Route, route as route, _positive_int as _positive_int
from archx_agent.interfaces.gui.routes.overview import OverviewRoutes as OverviewRoutes
from archx_agent.interfaces.gui.routes.models import ModelsRoutes as ModelsRoutes
from archx_agent.interfaces.gui.routes.chat import ChatRoutes as ChatRoutes
from archx_agent.interfaces.gui.routes.memory import MemoryRoutes as MemoryRoutes
from archx_agent.interfaces.gui.routes.jobs import JobsRoutes as JobsRoutes
from archx_agent.interfaces.gui.routes.access import AccessRoutes as AccessRoutes
from archx_agent.interfaces.gui.routes.research import ResearchRoutes as ResearchRoutes
from archx_agent.interfaces.gui.routes.learning import LearningRoutes as LearningRoutes
from archx_agent.interfaces.gui.routes.code import CodeRoutes as CodeRoutes
from archx_agent.interfaces.gui.routes.experiments import ExperimentsRoutes as ExperimentsRoutes
from archx_agent.interfaces.gui.routes.play import PlayRoutes as PlayRoutes
from archx_agent.interfaces.gui.routes.voice import VoiceRoutes as VoiceRoutes
from archx_agent.interfaces.gui.routes.datasets import DatasetsRoutes as DatasetsRoutes
from archx_agent.interfaces.gui.routes.training import TrainingRoutes as TrainingRoutes
from archx_agent.interfaces.gui.routes.remote import RemoteRoutes as RemoteRoutes
from archx_agent.interfaces.gui.routes.exec import ExecRoutes as ExecRoutes
from archx_agent.interfaces.gui.routes.automations import AutomationsRoutes as AutomationsRoutes
from archx_agent.interfaces.gui.routes.scenes import ScenesRoutes as ScenesRoutes
from .api import GuiApi as GuiApi
from .http import GuiHandler as GuiHandler
from .lifecycle import GuiServer as GuiServer
from .transport_helpers import split_target as split_target, free_port as free_port
