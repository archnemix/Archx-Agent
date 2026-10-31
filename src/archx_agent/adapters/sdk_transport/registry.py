"""Registry metadata and availability for vendor SDK transport."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SdkSpec:
    """One vendor's official client, and how to point it at an endpoint."""

    key: str  # the value used in the catalogue: "openai", "anthropic", …
    label: str
    package: str  # pip distribution name
    import_name: str  # what `import ...` needs
    provider_template: str  # the provider catalogue template slug
    env_var: str
    default_base_url: str | None
    api_style: str
    streaming: bool
    notes: str = ""
    #: does this client need a credential before it can be used at all? A local Ollama daemon
    #: does not, so a missing key must not mark the model unusable.
    key_required: bool = True


SDKS: dict[str, SdkSpec] = {
    "openai": SdkSpec(
        key="openai",
        label="OpenAI",
        package="openai",
        import_name="openai",
        provider_template="openai",
        env_var="OPENAI_API_KEY",
        default_base_url="https://api.openai.com/v1",
        api_style="openai",
        streaming=True,
    ),
    "anthropic": SdkSpec(
        key="anthropic",
        label="Anthropic",
        package="anthropic",
        import_name="anthropic",
        provider_template="anthropic",
        env_var="ANTHROPIC_API_KEY",
        default_base_url="https://api.anthropic.com",
        api_style="anthropic",
        streaming=True,
    ),
    "google": SdkSpec(
        key="google",
        label="Google Gemini",
        package="google-genai",
        import_name="google.genai",
        provider_template="google",
        env_var="GEMINI_API_KEY",
        default_base_url=None,  # the SDK owns it; an override must be explicit
        api_style="gemini",
        streaming=True,
    ),
    "mistral": SdkSpec(
        key="mistral",
        label="Mistral",
        package="mistralai",
        import_name="mistralai.client",
        provider_template="mistral",
        env_var="MISTRAL_API_KEY",
        default_base_url="https://api.mistral.ai",
        api_style="openai",
        streaming=True,
    ),
    "groq": SdkSpec(
        key="groq",
        label="Groq",
        package="groq",
        import_name="groq",
        provider_template="groq",
        env_var="GROQ_API_KEY",
        default_base_url="https://api.groq.com",  # the client appends /openai/v1 itself
        api_style="openai",
        streaming=True,
    ),
    "together": SdkSpec(
        key="together",
        label="Together",
        package="together",
        import_name="together",
        provider_template="together",
        env_var="TOGETHER_API_KEY",
        default_base_url="https://api.together.xyz",  # the client appends /v1 itself
        api_style="openai",
        streaming=True,
    ),
    "cohere": SdkSpec(
        key="cohere",
        label="Cohere",
        package="cohere",
        import_name="cohere",
        provider_template="cohere",
        env_var="COHERE_API_KEY",
        default_base_url="https://api.cohere.com",
        api_style="custom",
        streaming=True,
    ),
    "ollama": SdkSpec(
        key="ollama",
        label="Ollama",
        package="ollama",
        import_name="ollama",
        provider_template="ollama",
        env_var="OLLAMA_API_KEY",
        # No default: the client's own default is a local daemon on 127.0.0.1:11434, and
        # Ollama's cloud endpoint is opt-in. Guessing one would silently pick a different
        # service than the user expected.
        default_base_url=None,
        api_style="custom",
        streaming=True,
        key_required=False,
    ),
}


def sdk_available(key: str) -> tuple[bool, str]:
    """Is the vendor's client importable here? ``(ok, reason_if_not)``."""
    spec = SDKS.get(key)
    if spec is None:
        return False, f"unknown SDK {key!r} (known: {', '.join(sorted(SDKS))})"
    try:
        __import__(spec.import_name)
    except Exception as exc:  # noqa: BLE001 - any import failure means "not usable here"
        return False, (
            f"the {spec.label} SDK is not installed ({spec.import_name}: "
            f"{type(exc).__name__}); install it with `pip install {spec.package}`"
        )
    return True, "ready"
