"""Runtimes operations for workspace composition."""

from __future__ import annotations

import os

from archx_agent.adapters.gemini_runtime import (
    DEFAULT_BASE_URL as GEMINI_BASE_URL,
    GeminiChatRuntime,
)
from archx_agent.adapters.sdk_runtime import SdkChatRuntime
from archx_agent.adapters.sdk_transport import SDKS
from archx_agent.adapters.http_runtime import HttpChatRuntime
from archx_agent.adapters.llama_cpp_runtime import LlamaCppRuntime
from archx_agent.adapters.model_runtime import ModelRuntime, ModelSpec
from archx_agent.adapters.scripted_runtime import ScriptedRuntime
from archx_agent.helpers.config import resolve_secret
from archx_agent.helpers.exceptions import (
    ArchxError,
    ConfigError,
    ValidationError,
)
from archx_agent.managers.models import ModelRecord


class WorkspaceModelsRuntimesMixin:
    """Models Runtimes responsibility for Workspace."""

    def runtime_for(self, record: ModelRecord) -> ModelRuntime:
        self.assert_remote_allowed(record)
        key = f"{record.runtime}:{record.id}"
        cached = self._runtimes.get(key)
        if cached is not None and cached.loaded:
            return cached
        runtime = self._build_runtime(record)
        self._runtimes[key] = runtime
        return runtime

    def _build_runtime(self, record: ModelRecord) -> ModelRuntime:
        if record.runtime == "llama-cpp":
            runtime = LlamaCppRuntime(n_ctx=record.context_length)
            runtime.load(
                ModelSpec(
                    id=record.id,
                    provider=record.provider,
                    runtime=record.runtime,
                    path=record.path,
                    context_length=record.context_length
                    or self.config.get("model.context_limit"),
                    quantization=record.quantization,
                )
            )
            return runtime
        if record.runtime in ("openai-http", "http"):
            base_url = (record.facts or {}).get("base_url") or os.environ.get(
                "ARCHX_HTTP_BASE_URL"
            )
            if not base_url:
                raise ConfigError(
                    f"model {record.name!r} uses an HTTP runtime but no base_url is configured "
                    "(set model facts.base_url or ARCHX_HTTP_BASE_URL)"
                )
            ref = (record.user_metadata or {}).get("credential_ref") or (
                record.facts or {}
            ).get("credential_ref")
            api_key = resolve_secret(ref) if ref else None
            runtime = HttpChatRuntime(
                base_url, api_key=api_key, provider=record.provider
            )
            runtime.load(
                ModelSpec(
                    id=record.id,
                    provider=record.provider,
                    runtime=record.runtime,
                    model=record.model_ref,
                    context_length=record.context_length
                    or self.config.get("model.context_limit"),
                )
            )
            return runtime
        if record.runtime == "gemini":
            facts = record.facts or {}
            base_url = facts.get("base_url") or GEMINI_BASE_URL
            ref = (record.user_metadata or {}).get("credential_ref") or facts.get(
                "credential_ref"
            )
            if not ref:
                raise ConfigError(
                    f"model {record.name!r} is a Gemini model but has no credential reference; "
                    "register it with --credential-ref secret://env/GEMINI_API_KEY"
                )
            api_key = resolve_secret(ref)
            runtime = GeminiChatRuntime(
                base_url,
                api_key=api_key,
                api_version=str(facts.get("api_version") or "v1beta"),
            )
            runtime.load(
                ModelSpec(
                    id=record.id,
                    provider=record.provider,
                    runtime=record.runtime,
                    model=record.model_ref,
                    context_length=record.context_length
                    or self.config.get("model.context_limit"),
                )
            )
            return runtime
        if record.runtime == "sdk":
            facts = record.facts or {}
            sdk = facts.get("sdk") or record.provider
            if sdk not in SDKS:
                raise ConfigError(
                    f"model {record.name!r} names an unknown SDK {sdk!r} "
                    f"(known: {', '.join(sorted(SDKS))})"
                )
            ref = (record.user_metadata or {}).get("credential_ref") or facts.get(
                "credential_ref"
            )
            if not ref:
                raise ConfigError(
                    f"model {record.name!r} uses the {SDKS[sdk].label} SDK but has no credential "
                    f"reference; register it with --credential-ref secret://env/{SDKS[sdk].env_var}"
                )
            api_key = ""
            if ref:
                try:
                    api_key = resolve_secret(ref)
                except ArchxError:
                    if SDKS[sdk].key_required:
                        raise
                    # a local daemon: the absent key is the documented case, not an error
                    api_key = ""
            runtime = SdkChatRuntime(
                sdk,
                api_key=api_key,
                base_url=facts.get("base_url") or None,
            )
            runtime.load(
                ModelSpec(
                    id=record.id,
                    provider=record.provider,
                    runtime=record.runtime,
                    model=record.model_ref,
                    context_length=record.context_length
                    or self.config.get("model.context_limit"),
                )
            )
            return runtime
        if record.runtime == "scripted":
            runtime = ScriptedRuntime(enabled=self.allow_test_double)
            runtime.load(
                ModelSpec(
                    id=record.id,
                    provider=record.provider,
                    runtime=record.runtime,
                    model=record.model_ref,
                    context_length=record.context_length
                    or self.config.get("model.context_limit"),
                )
            )
            return runtime
        raise ValidationError(
            f"model {record.name!r} has unknown runtime {record.runtime!r} "
            "(expected llama-cpp, openai-http or scripted)"
        )
