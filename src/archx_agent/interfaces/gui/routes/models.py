"""HTTP endpoints for models. Authentication is enforced by GuiApi.dispatch."""

from __future__ import annotations


import json


import re


from pathlib import Path


from typing import Any


from urllib.parse import unquote


from archx_agent.helpers.exceptions import (
    ArchxError,
)


from archx_agent.helpers.jsonio import json_text


from archx_agent.adapters.sdk_transport import SDKS, sdk_available


from archx_agent.managers.providers import is_loopback_url


from archx_agent.interfaces.gui.protocol import ApiError, Request, route


class ModelsRoutes:
    @route(
        "GET",
        "/api/models",
        "The catalogue, with why each model can or cannot run here.",
    )
    def get_models(
        self, request: Request, match: re.Match[str]
    ) -> list[dict[str, Any]]:
        return [self._model_payload(record) for record in self.ws.models.list()]

    def _model_payload(self, record) -> dict[str, Any]:
        ready, why = self.ws.runtime_availability(record)
        provider = self.ws.provider_for(record)
        return {
            **record.to_dict(),
            "ready": ready,
            "ready_reason": why,
            "provider_id": provider.id if provider is not None else None,
            "gates": self._gates(record),
        }

    def _gates(self, record) -> list[dict[str, Any]]:
        """The ladder a remote model has to climb, and where it currently stands.

        These are the same conditions ``assert_remote_allowed`` enforces before a byte leaves
        the machine, so a refusal is legible in the page instead of mysterious.
        """
        base_url = (record.facts or {}).get("base_url")
        remote = (
            bool(base_url)
            and record.runtime in {"openai-http", "http", "gemini"}
            and not is_loopback_url(base_url)
        )
        if not remote:
            return [
                {
                    "key": "local",
                    "label": "endpoint is on this machine",
                    "ok": True,
                    "detail": "no data leaves the device, so no consent is needed",
                }
            ]
        provider = self.ws.provider_for(record)
        gates = [
            {
                "key": "consent_policy",
                "label": "cloud routing allowed",
                "ok": not self.ws.config.get("model.local_only"),
                "detail": "model.local_only is true: this build refuses remote endpoints by default",
            },
            {
                "key": "provider",
                "label": "endpoint is a registered provider",
                "ok": provider is not None,
                "detail": "register the provider so its privacy terms have somewhere to live",
            },
        ]
        # The last two rungs stay visible even when they cannot be climbed yet: a ladder
        # that grows rows as you go makes the remaining work invisible.
        gates.append(
            {
                "key": "privacy",
                "label": "privacy terms confirmed",
                "ok": bool(provider is not None and provider.privacy_known),
                "detail": (
                    provider.blocking_reason()
                    or "what this provider does with the data is recorded"
                )
                if provider is not None
                else "register the provider first",
            }
        )
        gates.append(
            {
                "key": "consent",
                "label": "you recorded consent",
                "ok": bool(provider is not None and provider.consented),
                "detail": (
                    provider.blocking_reason() or "consent on file, with a timestamp"
                )
                if provider is not None
                else "register the provider first",
            }
        )
        return gates

    @route(
        "GET",
        "/api/models/{model_id}",
        "One model, its readiness and the consent ladder.",
    )
    def get_model(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        record = self.ws.models.require(unquote(match.group("model_id")))
        return self._model_payload(record)

    @route(
        "GET",
        "/api/sdks",
        "Which vendor SDKs are installed, and the variable each expects.",
    )
    def get_sdks(self, request: Request, match: re.Match[str]) -> list[dict[str, Any]]:
        out = []
        for key, spec in SDKS.items():
            installed, why = sdk_available(key)
            out.append(
                {
                    "key": key,
                    "label": spec.label,
                    "package": spec.package,
                    "env_var": spec.env_var,
                    "base_url": spec.default_base_url,
                    "installed": installed,
                    "detail": why,
                }
            )
        return out

    @route(
        "POST", "/api/models", "Register a model whose key stays in the environment."
    )
    def post_model(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        body = request.payload()
        name = str(body.get("name") or "").strip()
        model_ref = str(body.get("model") or "").strip()
        if not name or not model_ref:
            raise ApiError(400, "validation", "a model needs a name and a model id")
        transport = str(body.get("transport") or "gemini")
        sdk = None if transport == "gemini" else transport
        if sdk is not None and sdk not in SDKS:
            raise ApiError(
                400,
                "unknown_sdk",
                f"unknown transport {transport!r} (gemini, or one of {', '.join(sorted(SDKS))})",
            )
        default_ref = (
            f"secret://env/{SDKS[sdk].env_var}"
            if sdk
            else "secret://env/GEMINI_API_KEY"
        )
        credential_ref = str(body.get("credential_ref") or default_ref).strip()
        if not credential_ref.startswith("secret://"):
            raise ApiError(
                400,
                "literal_secret",
                "the key itself is never sent to this server: give a secret://env/NAME or "
                "secret://file/PATH reference, and put the key in the environment",
            )
        base_url = str(body.get("base_url") or "").strip() or None
        if sdk is not None:
            try:
                record = self.ws.register_sdk(
                    name,
                    sdk=sdk,
                    model_ref=model_ref,
                    base_url=base_url,
                    credential_ref=credential_ref,
                    context_length=int(body.get("context_length") or 131_072),
                )
            except ArchxError as exc:
                raise ApiError(400, "validation", exc.message) from exc
            return self._model_payload(record)
        record = self.ws.register_gemini(
            name,
            model_ref=model_ref,
            base_url=base_url,
            credential_ref=credential_ref,
            api_version=str(body.get("api_version") or "v1beta"),
            context_length=int(body.get("context_length") or 1_048_576),
        )
        return self._model_payload(record)

    @route(
        "POST",
        "/api/models/{model_id}/probe",
        "Measure one capability by calling the model.",
    )
    def post_model_probe(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        record = self.ws.models.require(unquote(match.group("model_id")))
        capability = str(request.payload().get("capability") or "chat")
        try:
            result = self.ws.router.probe(record.id, capability=capability)
        except ArchxError as exc:
            # A failed probe is a measurement too: report it, never pretend it passed.
            raise ApiError(
                409, "probe_failed", exc.message, data={"model_id": record.id}
            ) from exc
        return {"model_id": record.id, "capability": capability, "result": result}

    @route(
        "POST",
        "/api/models/{model_id}/provider",
        "Register this model's endpoint as a provider.",
    )
    def post_model_provider(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        record = self.ws.models.require(unquote(match.group("model_id")))
        if self.ws.providers is None:
            raise ApiError(
                409, "no_providers", "this workspace has no provider registry"
            )
        existing = self.ws.provider_for(record)
        if existing is not None:
            return existing.to_dict()
        base_url = (record.facts or {}).get("base_url") or ""
        template = "google" if record.runtime == "gemini" else "openai"
        added = self.ws.providers.add(
            record.provider or template, template=template, base_url=base_url
        )
        if added.is_err:
            raise added.error
        return added.value.to_dict()

    @route(
        "GET",
        "/api/providers",
        "Registered providers and what is known about their data handling.",
    )
    def get_providers(
        self, request: Request, match: re.Match[str]
    ) -> list[dict[str, Any]]:
        if self.ws.providers is None:
            return []
        return [
            self._provider_payload(provider) for provider in self.ws.providers.list()
        ]

    @staticmethod
    def _provider_payload(provider) -> dict[str, Any]:
        return {
            **provider.to_dict(),
            "privacy_known": bool(provider.privacy_known),
            "consented": bool(provider.consented),
            "blocking_reason": provider.blocking_reason(),
        }

    @route(
        "POST",
        "/api/providers/{provider_id}/privacy",
        "Record what you confirmed about a provider.",
    )
    def post_provider_privacy(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        if self.ws.providers is None:
            raise ApiError(
                409, "no_providers", "this workspace has no provider registry"
            )
        body = request.payload()
        leaves = body.get("data_leaves_device")
        if not isinstance(leaves, bool):
            raise ApiError(
                400,
                "validation",
                "data_leaves_device must be true or false, answered deliberately",
            )
        result = self.ws.providers.confirm_privacy(
            unquote(match.group("provider_id")),
            data_leaves_device=leaves,
            training_use=str(body.get("training_use") or "unknown"),
            retention=str(body.get("retention") or "unknown"),
            region=str(body.get("region") or "unknown"),
        )
        if result.is_err:
            raise result.error
        return self._provider_payload(result.value)

    @route(
        "POST",
        "/api/providers/{provider_id}/consent",
        "Record consent to send data to a provider.",
    )
    def post_provider_consent(
        self, request: Request, match: re.Match[str]
    ) -> dict[str, Any]:
        if self.ws.providers is None:
            raise ApiError(
                409, "no_providers", "this workspace has no provider registry"
            )
        result = self.ws.providers.consent(
            unquote(match.group("provider_id")),
            note=str(request.payload().get("note") or "consent recorded in the GUI"),
        )
        if result.is_err:
            raise result.error
        return self._provider_payload(result.value)

    @route(
        "POST",
        "/api/settings/model.local_only",
        "Turn cloud routing on or off for this home.",
    )
    def post_local_only(self, request: Request, match: re.Match[str]) -> dict[str, Any]:
        value = request.payload().get("value")
        if not isinstance(value, bool):
            raise ApiError(400, "validation", "value must be true or false")
        self.ws.config.set("model.local_only", value, source="gui")
        self._persist_config()
        self._record_setting("model.local_only", value)
        return {
            "key": "model.local_only",
            "value": self.ws.config.get("model.local_only"),
        }

    def _persist_config(self) -> None:
        """Write the settings file the way `config set` does, so a restart agrees with the page."""
        path = Path(self.ws.config.home) / "config.json"
        settings: dict[str, Any] = {}
        if path.exists():
            try:
                settings = json.loads(path.read_text()).get("settings", {})
            except (OSError, json.JSONDecodeError):
                settings = {}
        settings["model.local_only"] = self.ws.config.get("model.local_only")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json_text({"version": self.ws.config.version, "settings": settings}) + "\n"
        )

    def _record_setting(self, key: str, value: Any) -> None:
        events = getattr(self.ws, "events", None)
        if events is None:
            return
        try:
            events.record(
                "settings",
                "settings.changed",
                payload={"key": key, "value": value, "via": "gui"},
            )
        except Exception:  # noqa: BLE001 - an audit failure must not undo the setting
            pass
