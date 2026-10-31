"""GUI API authentication responsibility."""

from __future__ import annotations

import hashlib
import hmac
import time
from http.cookies import SimpleCookie
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


class GuiAuthenticationMixin:
    def _cookie_value(self) -> str:
        """The cookie is derived from the token, so a leaked cookie is a leaked token.

        The cookie does not contain the raw token. The browser client separately keeps
        that token in tab-scoped sessionStorage; restarting the server invalidates
        both the old token and every cookie because a new token is minted.
        """
        return hmac.new(
            self.token.encode(), b"archx-gui-session", hashlib.sha256
        ).hexdigest()

    def open_session(self, token: str) -> Response:
        if not self._token_ok(token):
            self._record_auth_failure()
            raise ApiError(
                401, "unauthorized", "that token is not this session's token"
            )
        cookie = (
            f"{COOKIE_NAME}={self._cookie_value()}; Path=/; HttpOnly; SameSite=Strict; "
            f"Max-Age={self.token_ttl_minutes * 60}"
        )
        return Response(
            payload={"ok": True, "expires_in": self.token_ttl_minutes * 60},
            headers={"Set-Cookie": cookie},
        )

    def _token_ok(self, candidate: str | None) -> bool:
        if not candidate:
            return False
        return hmac.compare_digest(candidate, self.token)

    def _record_auth_failure(self) -> None:
        now = time.time()
        with self._lock:
            self.auth_failures += 1
            self._auth_window = [
                stamp for stamp in self._auth_window if now - stamp < 60.0
            ]
            self._auth_window.append(now)
            if len(self._auth_window) > self.max_auth_failures:
                raise ApiError(
                    429, "too_many_attempts", "too many bad tokens; wait a minute"
                )

    def _authenticate(self, request: Request) -> None:
        """Accept the token (header, bearer, query) or the cookie this server issued."""
        handle = request.headers.get("authorization", "")
        if handle.lower().startswith("bearer ") and self._token_ok(handle[7:].strip()):
            return
        if self._token_ok(request.headers.get("x-archx-token")):
            return
        if request.token is not None and self._token_ok(request.token):
            return
        cookie = SimpleCookie()
        try:
            cookie.load(request.headers.get("cookie", ""))
        except Exception:  # noqa: BLE001 - a malformed cookie is simply unauthenticated
            cookie = SimpleCookie()
        morsel = cookie.get(COOKIE_NAME)
        if morsel is not None and hmac.compare_digest(
            morsel.value, self._cookie_value()
        ):
            request.via_cookie = True
            return
        self._record_auth_failure()
        raise ApiError(401, "unauthorized", "this GUI needs its access token")

    @staticmethod
    def _require_csrf(request: Request) -> None:
        """On a cookie-authenticated write, demand a header a cross-site page cannot set."""
        header = request.headers.get(CSRF_HEADER, "")
        if header == CSRF_VALUE:
            return
        # A caller presenting the token itself (curl, the acceptance script) is not a
        # browser and cannot be tricked into a cross-site request by a page it visits.
        if request.headers.get("x-archx-token") or request.headers.get("authorization"):
            return
        # A request carrying no credential at all cannot be riding a session cookie, so CSRF
        # is the wrong refusal: there is nothing to forge yet. Fall through and let
        # authentication answer "you have not identified yourself", which is what happened.
        cookie = SimpleCookie()
        try:
            cookie.load(request.headers.get("cookie", ""))
        except Exception:  # noqa: BLE001 - a malformed cookie is simply not a credential
            cookie = SimpleCookie()
        if cookie.get(COOKIE_NAME) is None:
            return
        raise ApiError(
            403,
            "csrf",
            f"a write needs the {CSRF_HEADER}: {CSRF_VALUE} header",
        )
