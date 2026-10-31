"""Transport construction for vendor SDK transport."""

from __future__ import annotations

from archx_agent.helpers.exceptions import (
    ProviderError,
)
from archx_agent.adapters.sdk_transport.registry import SDKS

from .transport import SdkTransport


def transport_for(
    key: str, *, api_key: str, base_url: str | None = None, timeout: float = 60.0
) -> SdkTransport:
    if key not in SDKS:
        raise ProviderError(f"unknown SDK {key!r} (known: {', '.join(sorted(SDKS))})")
    return SdkTransport(key=key, api_key=api_key, base_url=base_url, timeout=timeout)
