"""Official-SDK transports.

Archx already speaks two wire protocols directly (`openai-http` for anything
OpenAI-compatible, `gemini` for Google's REST shape). That is the right default: it needs no
extra dependency and it cannot drift with a vendor's client release.

But "we build the HTTP body ourselves" is a claim, and the cheapest way to check it is to let
the vendor's own client build the same request. This module does exactly that: it drives the
**official Python SDKs** (`openai`, `anthropic`, `google-genai`, `mistralai`) and translates
their objects into the same `ChatResult` every other runtime returns.

Design notes that matter:

* **Optional, never required.** An SDK is imported lazily. If it is absent, `available()`
  returns a precise reason and the runtime refuses instead of pretending; `pytest` skips.
* **No hidden retries.** Every client is constructed with ``max_retries=0``. Retrying is the
  router's decision (it knows which errors are retryable and records the fallback); an SDK
  that silently retries twice would make one refused call look like three.
* **One error taxonomy.** Vendors raise different exception trees; they are mapped by class
  name *and* HTTP status into the same domain errors the HTTP runtimes use, so a 401 from
  OpenAI, Anthropic or Google produces the same sentence and the same `retryable=False`.
* **The key is scrubbed before it can be shown.** Some SDKs put the request (and therefore the
  credential) in the exception's message.

Public compatibility surface. Implementation responsibilities live in sibling modules.
"""

from .transport import SdkTransport as SdkTransport
from .registry import SdkSpec as SdkSpec, SDKS as SDKS, sdk_available as sdk_available
from .errors import (
    _QUOTA_WORDS as _QUOTA_WORDS,
    _STATUS_IN_TEXT as _STATUS_IN_TEXT,
    _status_of as _status_of,
    classify_sdk_error as classify_sdk_error,
)
from .compatibility import (
    _accepts as _accepts,
    _supported as _supported,
    _finish as _finish,
)
from .probe_tools import _OPENAI_PROBE_TOOL as _OPENAI_PROBE_TOOL
from .factory import transport_for as transport_for


__all__ = [
    "SDKS",
    "SdkSpec",
    "SdkTransport",
    "sdk_available",
    "classify_sdk_error",
    "transport_for",
]
