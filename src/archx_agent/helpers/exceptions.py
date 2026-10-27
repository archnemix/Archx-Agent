"""The single exception hierarchy for Archx Agent.

Rules
-----
* Data-producing operations return ``Result``; failures raise a domain
  exception from this module.
* Exception messages describe *what* failed without embedding secrets.
* Provider failures are classified into precise subclasses so that callers can
  distinguish "rate limited" from "model does not exist".
"""

from __future__ import annotations

from typing import Any


class ArchxError(Exception):
    """Base class for every domain error raised by Archx Agent."""

    #: stable machine-readable code used in traces and results
    code = "archx_error"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "type": type(self).__name__,
            "message": self.message,
            "context": dict(self.context),
        }

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


# --------------------------------------------------------------------------
# configuration / validation
# --------------------------------------------------------------------------
class ConfigError(ArchxError):
    code = "config_error"


class ValidationError(ArchxError):
    code = "validation_error"


class NotFoundError(ArchxError):
    code = "not_found"


class ConflictError(ArchxError):
    code = "conflict"


class DuplicateError(ConflictError):
    code = "duplicate"


class UnsupportedOperationError(ArchxError):
    """The operation is legitimate but not supported by the current setup."""

    code = "unsupported"


class ContextOverflowError(ArchxError):
    """The required content does not fit the model's context window."""

    code = "context_overflow"


class DeferredCapabilityError(UnsupportedOperationError):
    """A capability exists in the product spec but is not implemented/verified."""

    code = "deferred_capability"


# --------------------------------------------------------------------------
# paths / storage
# --------------------------------------------------------------------------
class PathError(ArchxError):
    code = "path_error"


class PathEscapesRootError(PathError):
    code = "path_escapes_root"


class StorageError(ArchxError):
    code = "storage_error"


class StorageBusyError(StorageError):
    code = "storage_busy"


class StorageCorruptError(StorageError):
    code = "storage_corrupt"


class SchemaVersionError(StorageError):
    code = "schema_version"


class BackupError(StorageError):
    code = "backup_error"


class RestoreError(StorageError):
    code = "restore_error"


class WriteBackpressureError(StorageError):
    code = "write_backpressure"


# --------------------------------------------------------------------------
# permissions
# --------------------------------------------------------------------------
class PermissionDeniedError(ArchxError):
    code = "permission_denied"


class ApprovalRequiredError(PermissionDeniedError):
    code = "approval_required"


class ConsentRequiredError(PermissionDeniedError):
    """Sending data to a remote provider needs the user's explicit consent."""

    code = "consent_required"


class PrivacyUnknownError(PermissionDeniedError):
    """A provider whose data-handling terms are unknown may not be used."""

    code = "privacy_unknown"


# --------------------------------------------------------------------------
# providers / runtimes
# --------------------------------------------------------------------------
class ProviderError(ArchxError):
    """Base class for model/provider failures.

    ``retryable`` tells the scheduler whether a retry could plausibly help.
    """

    code = "provider_error"
    retryable = False

    def __init__(self, message: str, *, provider: str = "", model: str = "", **context: Any) -> None:
        super().__init__(message, **context)
        self.provider = provider
        self.model = model
        self.context.setdefault("provider", provider)
        self.context.setdefault("model", model)


class ModelNotFoundError(ProviderError):
    code = "model_not_found"


class AuthDeniedError(ProviderError):
    code = "auth_denied"


class EntitlementError(ProviderError):
    code = "entitlement"


class RateLimitedError(ProviderError):
    code = "rate_limited"
    retryable = True


class QuotaExhaustedError(ProviderError):
    code = "quota_exhausted"


class ProviderOutageError(ProviderError):
    code = "provider_outage"
    retryable = True


class NetworkFailureError(ProviderError):
    code = "network_failure"
    retryable = True


class UnsupportedCapabilityError(ProviderError):
    """The model cannot do the requested operation (verified unsupported)."""

    code = "unsupported_capability"


class InvalidRequestError(ProviderError):
    code = "invalid_request"


class MalformedOutputError(ProviderError):
    code = "malformed_output"
    retryable = True


class LocalRuntimeFailureError(ProviderError):
    code = "local_runtime_failure"


class ResourceExhaustedError(ProviderError):
    code = "resource_exhausted"
    retryable = True


class ModelUnavailableError(ProviderError):
    code = "model_unavailable"


PROVIDER_ERROR_MAP: dict[str, type[ProviderError]] = {
    "model_not_found": ModelNotFoundError,
    "auth_denied": AuthDeniedError,
    "entitlement": EntitlementError,
    "rate_limited": RateLimitedError,
    "quota_exhausted": QuotaExhaustedError,
    "provider_outage": ProviderOutageError,
    "network_failure": NetworkFailureError,
    "unsupported_capability": UnsupportedCapabilityError,
    "invalid_request": InvalidRequestError,
    "malformed_output": MalformedOutputError,
    "local_runtime_failure": LocalRuntimeFailureError,
    "resource_exhausted": ResourceExhaustedError,
    "model_unavailable": ModelUnavailableError,
}


# --------------------------------------------------------------------------
# tools / execution
# --------------------------------------------------------------------------
class ToolError(ArchxError):
    code = "tool_error"


class ToolNotFoundError(ToolError):
    code = "tool_not_found"


class ToolTimeoutError(ToolError):
    code = "tool_timeout"
    retryable = True


class ToolValidationError(ToolError):
    code = "tool_validation"


class ExecutionError(ArchxError):
    code = "execution_error"


class SandboxError(ExecutionError):
    code = "sandbox_error"


class MCPServerError(ArchxError):
    code = "mcp_error"


class ExperimentError(ArchxError):
    code = "experiment_error"


class SchedulerError(ArchxError):
    code = "scheduler_error"


class JobRejectedError(SchedulerError):
    code = "job_rejected"


class JobCancelledError(SchedulerError):
    code = "job_cancelled"


__all__ = [name for name, obj in list(globals().items()) if isinstance(obj, type) and issubclass(obj, Exception)]
