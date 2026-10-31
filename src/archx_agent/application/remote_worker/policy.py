"""Worker credential validation and fail-closed HTTP bind policy."""
from __future__ import annotations

import ipaddress


def validate_token(token: str | None) -> str | None:
    if token is not None and (
        not isinstance(token, str)
        or not token
        or len(token) > 4096
        or any(not 33 <= ord(char) <= 126 for char in token)
    ):
        raise ValueError("worker token must be 1-4096 printable ASCII characters without whitespace")
    return token


def require_authenticated_bind(host: str, *, token: str | None, allow_exec: bool) -> None:
    """Only a numeric loopback training-only bind may omit a credential.

    Hostnames require a token rather than trusting a DNS/hosts-file interpretation of
    'localhost'. The policy is checked before constructing a listening socket.
    """
    validate_token(token)
    if not isinstance(host, str) or not host:
        raise ValueError("worker host must be a nonempty address string")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if token is None and (allow_exec or not loopback):
        raise ValueError(
            "executable or non-loopback workers require a bearer token; "
            "use --token-env NAME and private transport/TLS"
        )
