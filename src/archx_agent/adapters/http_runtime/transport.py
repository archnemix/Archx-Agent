"""HttpChatRuntime transport."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from archx_agent.helpers.exceptions import (
    MalformedOutputError,
    NetworkFailureError,
    ProviderOutageError,
    RateLimitedError,
)
from archx_agent.adapters.http_runtime.error_payloads import _safe_body


class HttpChatRuntimeTransportMixin:
    """Transport responsibility for HttpChatRuntime."""

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        headers.update(self.extra_headers)
        attempt = 0
        while True:
            request = urllib.request.Request(
                url, data=data, headers=headers, method=method
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - user-configured endpoint
                    raw = response.read()
                    break
            except urllib.error.HTTPError as exc:
                payload = _safe_body(exc)
                error = self._classify_http(exc.code, payload, url)
                if (
                    isinstance(error, (RateLimitedError, ProviderOutageError))
                    and attempt < self.max_retries
                ):
                    attempt += 1
                    time.sleep(min(2**attempt * 0.25, 4.0))
                    continue
                raise error from None
            except (socket.timeout, TimeoutError) as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    time.sleep(min(2**attempt * 0.25, 4.0))
                    continue
                raise NetworkFailureError(
                    f"timed out calling {url}", provider=self.provider
                ) from exc
            except urllib.error.URLError as exc:
                raise NetworkFailureError(
                    f"cannot reach {url}: {exc.reason}",
                    provider=self.provider,
                    endpoint=url,
                ) from exc
            except OSError as exc:
                raise NetworkFailureError(
                    f"connection failed calling {url}",
                    provider=self.provider,
                    endpoint=url,
                ) from exc
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise MalformedOutputError(
                    "endpoint returned a non-object JSON response",
                    provider=self.provider,
                )
            return parsed
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedOutputError(
                f"endpoint {url} returned a non-JSON body", provider=self.provider
            ) from exc
