"""URL classification shared by providers and transports without upward imports."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def is_loopback_url(url: str | None) -> bool:
    """Only literal loopback addresses and exact localhost qualify as local.

    Do not resolve DNS here: a remote name such as 127.example.com is not an IP,
    and classification must not trust a hostname prefix or a changing DNS answer.
    Unspecified addresses (0.0.0.0/::) are bind addresses, not loopback endpoints.
    """
    if not url:
        return False
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = parsed.hostname
        if host == "localhost":
            return True
        return bool(host and ipaddress.ip_address(host).is_loopback)
    except ValueError:
        return False
