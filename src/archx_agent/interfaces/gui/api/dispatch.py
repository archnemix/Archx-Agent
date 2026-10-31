"""GUI API dispatch responsibility."""

from __future__ import annotations

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


class GuiDispatchMixin:
    def routes(self) -> list[Route]:
        found: list[Route] = []
        for name in dir(self):
            attr = getattr(self, name, None)
            definition = getattr(attr, "_route", None)
            if isinstance(definition, Route):
                found.append(definition)
        return sorted(found, key=lambda r: (r.pattern.pattern, r.method))

    def dispatch(self, request: Request) -> Response | SSEStream:
        with self._lock:
            self.requests += 1
        try:
            if request.method == "OPTIONS":
                raise ApiError(
                    405, "no_cors", "this server does not answer CORS preflights"
                )
            if request.path == "/api/health":
                # The one endpoint that answers without a token, so a monitor can ask if the
                # process is alive. It reports nothing but liveness, and it answers GET only -
                # a DELETE that returns a health payload is a routing accident, not a feature.
                # Refused before the CSRF check: there is no write here to protect, so the
                # honest answer is "this path does not take that verb", not "you forgot a
                # header". `HEAD` arrives as GET (the body is suppressed on the way out).
                if request.method != "GET":
                    raise ApiError(405, "method_not_allowed", "health answers GET")
                return Response(payload={"ok": True, "data": self.health()})
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                self._require_csrf(request)
            if request.path == "/api/session" and request.method == "POST":
                token = str(request.payload().get("token", ""))
                return self.open_session(token)
            self._authenticate(request)
            for definition in self.routes():
                if definition.method != request.method:
                    continue
                match = definition.pattern.match(request.path)
                if match is None:
                    continue
                result = definition.handler(self, request, match)
                if isinstance(result, (Response, SSEStream)):
                    return result
                if isinstance(result, (bytes, str)):
                    return Response(payload=result)
                return Response(payload={"ok": True, "data": result})
            raise ApiError(
                404, "no_route", f"no route for {request.method} {request.path}"
            )
        except ApiError as exc:
            return self._error_response(exc)
        except BaseException as exc:  # noqa: BLE001 - every failure becomes JSON
            return self._error_response(error_for(exc))

    def _error_response(self, exc: ApiError) -> Response:
        return Response(
            status=exc.status,
            payload={
                "ok": False,
                "error": {"code": exc.code, "message": exc.message, "data": exc.data},
            },
        )
