"""Composition and shared configuration for provider metadata."""

from __future__ import annotations

from archx_agent.helpers.urls import is_loopback_url as is_loopback_url
from archx_agent.managers.base import BaseManager
from archx_agent.managers.providers.constants import PROVIDER_TABLES
from archx_agent.managers.providers.writes import ProviderManagerWritesMixin
from archx_agent.managers.providers.catalogue import ProviderManagerCatalogueMixin
from archx_agent.managers.providers.usage import ProviderManagerUsageMixin
from archx_agent.managers.providers.consent import ProviderManagerConsentMixin
from archx_agent.managers.providers.management import ProviderManagerManagementMixin


class ProviderManager(
    ProviderManagerWritesMixin,
    ProviderManagerCatalogueMixin,
    ProviderManagerUsageMixin,
    ProviderManagerConsentMixin,
    ProviderManagerManagementMixin,
    BaseManager,
):
    """Provider catalogue, privacy metadata, availability checks and usage."""

    tables = PROVIDER_TABLES
