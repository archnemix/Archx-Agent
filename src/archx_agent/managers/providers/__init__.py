"""Cloud and local provider catalogue with privacy metadata (M20).

The central rule: **a provider is not usable because it is configured, it is usable
because the user knows what happens to their data and said yes.** Two independent
conditions must hold before any request can be sent:

1. the provider's privacy metadata is *known* - either because it is local (derived
   from the URL, not from a claim) or because the user confirmed the terms;
2. the user recorded explicit consent for that provider (``consent_at``).

Documentation claims live in ``privacy_claims`` and are never presented as facts.
What the user confirmed lives in ``privacy_confirmed``. The effective view merges them
with the confirmed values winning, and reports which of the two supplied each field.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .manager import ProviderManager as ProviderManager
from .constants import (
    PROVIDER_TABLES as PROVIDER_TABLES,
    _SELECT as _SELECT,
    KINDS as KINDS,
    API_STYLES as API_STYLES,
    CONSENT_VERSION as CONSENT_VERSION,
    PRIVACY_FIELDS as PRIVACY_FIELDS,
    KNOWN_PROVIDERS as KNOWN_PROVIDERS,
)
from .records import Provider as Provider, _from_row as _from_row
from .probing import probe_provider as probe_provider, _count_models as _count_models
from .naming import _slug as _slug


__all__ = [
    "ProviderManager",
    "Provider",
    "KNOWN_PROVIDERS",
    "CONSENT_VERSION",
    "probe_provider",
    "is_loopback_url",
    "KINDS",
    "API_STYLES",
]


from archx_agent.helpers.urls import is_loopback_url as is_loopback_url
