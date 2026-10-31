"""Availability operations for workspace composition."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from archx_agent.adapters.gemini_runtime import DEFAULT_BASE_URL as GEMINI_BASE_URL
from archx_agent.adapters.sdk_transport import SDKS, sdk_available
from archx_agent.helpers.config import resolve_secret
from archx_agent.helpers.exceptions import (
    ArchxError,
    ValidationError,
)
from archx_agent.managers.models import ModelRecord
from archx_agent.managers.providers import is_loopback_url


class WorkspaceModelsAvailabilityMixin:
    """Models Availability responsibility for Workspace."""

    def runtime_availability(self, record: ModelRecord) -> tuple[bool, str]:
        """Can this model run here, checked *without* loading anything?

        Loading a GGUF to answer "is it usable?" would cost seconds and gigabytes; the
        router needs a cheap, honest answer instead. The checks mirror the runtimes'
        own preconditions exactly.
        """
        if record.runtime == "llama-cpp":
            from archx_agent.adapters.llama_cpp_runtime import (
                INSTALL_HINT,
                llama_cpp_available,
            )

            if not llama_cpp_available():
                return False, f"llama-cpp-python is not installed ({INSTALL_HINT})"
            if not record.path or not Path(record.path).exists():
                return False, f"model file not found: {record.path}"
            return True, "ready"
        base_url = (record.facts or {}).get("base_url")
        if record.runtime in ("openai-http", "http"):
            if not base_url:
                return False, "no base_url configured"
            return True, "ready"
        if record.runtime == "gemini":
            facts = record.facts or {}
            ref = (record.user_metadata or {}).get("credential_ref") or facts.get(
                "credential_ref"
            )
            if not ref:
                return False, (
                    "no API key reference; register the model with "
                    "--credential-ref secret://env/GEMINI_API_KEY"
                )
            try:
                if not resolve_secret(ref):
                    return (
                        False,
                        f"the secret reference {ref} resolved to an empty value",
                    )
            except ArchxError as exc:
                return (
                    False,
                    f"the secret reference {ref} could not be resolved: {exc.message}",
                )
            if not record.model_ref:
                return (
                    False,
                    "no model reference (register it with --model gemini-2.0-flash)",
                )
            endpoint = facts.get("base_url") or GEMINI_BASE_URL
            return True, f"ready (endpoint {endpoint})"
        if record.runtime == "sdk":
            facts = record.facts or {}
            sdk = facts.get("sdk") or record.provider
            ok, why = sdk_available(sdk)
            if not ok:
                return False, why
            ref = (record.user_metadata or {}).get("credential_ref") or facts.get(
                "credential_ref"
            )
            # A local Ollama daemon needs no credential; demanding one would mark a working
            # local model unusable. Anything that leaves the machine still needs a reference.
            key_optional = not SDKS[sdk].key_required and is_loopback_url(
                facts.get("base_url") or SDKS[sdk].default_base_url or ""
            )
            if key_optional:
                return (
                    True,
                    f"ready: a local {SDKS[sdk].label} needs no key (no data leaves this machine)",
                )
            if not ref:
                return False, (
                    f"no API key reference; register the model with --credential-ref "
                    f"secret://env/{SDKS[sdk].env_var}"
                )
            try:
                if not resolve_secret(ref):
                    return (
                        False,
                        f"the secret reference {ref} resolved to an empty value",
                    )
            except ArchxError as exc:
                return (
                    False,
                    f"the secret reference {ref} could not be resolved: {exc.message}",
                )
            if not record.model_ref:
                return (
                    False,
                    f"no model reference (register it with --model <{SDKS[sdk].label} model id>)",
                )
            endpoint = (
                facts.get("base_url") or SDKS[sdk].default_base_url or "the SDK default"
            )
            return True, f"ready via the {SDKS[sdk].package} SDK (endpoint {endpoint})"
        if record.runtime == "scripted":
            if not self.allow_test_double:
                return (
                    False,
                    "the simulated test double is disabled (use --allow-simulated)",
                )
            return True, "ready (simulated - performs no inference)"
        return False, f"unknown runtime {record.runtime!r}"

    def register_gemini(
        self,
        name: str,
        *,
        model_ref: str,
        base_url: str | None = None,
        credential_ref: str = "secret://env/GEMINI_API_KEY",
        api_version: str = "v1beta",
        context_length: int = 1_048_576,
        capabilities: Sequence[str] | None = None,
        verification: str = "inferred",
    ) -> ModelRecord:
        """Register a Gemini model. The credential is a *reference*, never the key.

        Both the CLI and the GUI go through this method so neither can quietly store a key.
        """
        from archx_agent.adapters.gemini_runtime import DEFAULT_BASE_URL

        endpoint = (base_url or DEFAULT_BASE_URL).rstrip("/")
        reference = str(credential_ref or "").strip()
        if not reference.startswith("secret://"):
            raise ValidationError(
                "credentials must be a secret://env/NAME or secret://file/PATH reference, not "
                "the key itself (a literal key would end up in the database, the trace and the logs)"
            )
        record = self.models.register_remote(
            name,
            provider="google",
            runtime="gemini",
            model_ref=model_ref,
            base_url=endpoint,
            context_length=context_length,
            capabilities=list(capabilities or ["chat"]),
            verification=verification,
        )
        metadata = dict(record.user_metadata or {})
        metadata["credential_ref"] = reference
        facts = dict(record.facts or {})
        facts["api_version"] = api_version
        return self.models.update(record.id, user_metadata=metadata, facts=facts)

    def register_sdk(
        self,
        name: str,
        *,
        sdk: str,
        model_ref: str,
        base_url: str | None = None,
        credential_ref: str | None = None,
        context_length: int = 131_072,
        capabilities: Sequence[str] | None = None,
        verification: str = "inferred",
    ) -> ModelRecord:
        """Register a model that will be driven by a vendor's official SDK.

        Shared by the CLI and the GUI for the same reason `register_gemini` is: one place
        enforces "the credential is a reference, never the key".
        """
        if sdk not in SDKS:
            raise ValidationError(
                f"unknown SDK {sdk!r} (known: {', '.join(sorted(SDKS))})"
            )
        reference = str(credential_ref or f"secret://env/{SDKS[sdk].env_var}").strip()
        if not reference.startswith("secret://"):
            raise ValidationError(
                "credentials must be a secret://env/NAME or secret://file/PATH reference, not "
                "the key itself (a literal key would end up in the database, the trace and the logs)"
            )
        record = self.models.register_remote(
            name,
            provider=SDKS[sdk].provider_template,
            runtime="sdk",
            model_ref=model_ref,
            base_url=base_url or SDKS[sdk].default_base_url,
            context_length=context_length,
            capabilities=list(capabilities or ["chat"]),
            verification=verification,
        )
        metadata = dict(record.user_metadata or {})
        metadata["credential_ref"] = reference
        facts = dict(record.facts or {})
        facts["sdk"] = sdk
        return self.models.update(record.id, user_metadata=metadata, facts=facts)
