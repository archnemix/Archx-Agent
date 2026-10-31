"""OpenAI-compatible HTTP runtime (llama_cpp.server, Ollama, vLLM, LM Studio).

This is a *real* client: it speaks the documented HTTP protocol and classifies
failures precisely. It is used for both local servers (``is_local=True`` when the
host is loopback) and remote providers.

Failure classification matters: a 429 (rate limit / quota) must never be
reported as "model does not exist", and a 401 must never be retried.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .runtime import HttpChatRuntime as HttpChatRuntime
from .error_payloads import (
    _safe_body as _safe_body,
    _extract_error_message as _extract_error_message,
)


__all__ = ["HttpChatRuntime"]
