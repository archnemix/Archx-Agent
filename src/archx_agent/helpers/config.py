"""Validated, layered configuration.

Precedence (lowest to highest):

1. built-in defaults (the ``SPEC`` table below)
2. ``<home>/config.json``
3. environment variables ``ARCHX_<SECTION>_<KEY>``
4. explicit overrides passed by the caller (CLI flags)

Every key is declared in :data:`SPEC`, so an unknown key in ``config.json`` is a
hard error naming the file and the key - not a silent no-op. Error messages
always name the setting and the expected form, and never print secret values.
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .exceptions import ConfigError, ValidationError
from .jsonio import atomic_write_json, read_json
from .paths import ensure_directory

CONFIG_VERSION = 2
ENV_PREFIX = "ARCHX_"
SECRET_MARKER = "secret://"

# key -> (type, default, validator, description)
Validator = Callable[[Any], Any]


def _one_of(*choices: Any, allow_none: bool = False) -> Validator:
    def check(value: Any) -> Any:
        if value is None and allow_none:
            return None
        if value not in choices:
            raise ValidationError(f"expected one of {list(choices)}")
        return value

    return check


def _range(lo: float, hi: float, *, integer: bool = False) -> Validator:
    def check(value: Any) -> Any:
        num = float(value)
        if not lo <= num <= hi:
            raise ValidationError(f"expected a number between {lo} and {hi}")
        return int(num) if integer else num

    return check


def _path(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("expected a filesystem path")
    return os.path.expanduser(value)


def _bool(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValidationError("expected true or false")


def _str(value: Any) -> Any:
    if not isinstance(value, str):
        raise ValidationError("expected a string")
    return value


def _int(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("expected an integer") from exc


def _str_list(value: Any) -> Any:
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    if isinstance(value, (list, tuple)) and all(isinstance(x, str) for x in value):
        return list(value)
    raise ValidationError("expected a list of strings")


SPEC: dict[str, tuple[type, Any, Validator, str]] = {
    # ---- general
    "general.brand": (str, "Archx Agent", _str, "Displayed product name."),
    "general.profile": (str, "local", _one_of("local", "balanced", "cloud"), "Privacy profile presets."),
    # ---- paths
    "paths.home": (str, "~/.archx", _path, "Root directory for all Archx data."),
    "paths.models": (str, "", _path, "Directory holding local model files (default <home>/models)."),
    "paths.projects": (str, "", _path, "Directory for project workspaces (default <home>/projects)."),
    "paths.artifacts": (str, "", _path, "Directory for artifact blobs (default <home>/artifacts)."),
    "paths.backups": (str, "", _path, "Directory for backups (default <home>/backups)."),
    # ---- storage
    "storage.db_path": (str, "", _path, "Primary SQLite database (default <home>/archx.db)."),
    "storage.events_path": (str, "", _path, "Trace database (default <home>/events.db)."),
    "storage.journal_mode": (str, "wal", _one_of("wal", "delete"), "SQLite journal mode."),
    "storage.busy_timeout_ms": (int, 10000, _range(100, 120000, integer=True), "SQLite busy timeout."),
    "storage.write_queue_size": (int, 1024, _range(8, 100000, integer=True), "Writer queue depth."),
    "storage.backup_keep": (int, 10, _range(1, 1000, integer=True), "How many backups to retain."),
    "storage.auto_backup": (bool, True, _bool, "Back up before schema migrations."),
    # ---- trace
    "trace.capture_level": (str, "detailed", _one_of("summary", "detailed", "diagnostic"), "Default trace capture level."),
    "trace.retention_days": (int, 30, _range(1, 3650, integer=True), "Trace retention in days."),
    "trace.max_events": (int, 200000, _range(1000, 10000000, integer=True), "Maximum trace rows retained."),
    "trace.redact_secrets": (bool, True, _bool, "Run the redaction pass on traces/exports (should stay on)."),
    # ---- models / routing
    "model.default_id": (str, "", _str, "Default chat model id."),
    "model.local_only": (bool, True, _bool, "Never route to cloud providers unless the user opts out."),
    "model.context_limit": (int, 2048, _range(128, 2000000, integer=True), "Context window in tokens."),
    "model.output_budget": (int, 512, _range(32, 200000, integer=True), "Reserved tokens for the reply."),
    "model.temperature": (float, 0.2, _range(0.0, 2.0), "Default sampling temperature."),
    "model.prefer_verified": (bool, True, _bool, "Prefer capability-verified models."),
    "model.allow_cloud_fallback": (bool, False, _bool, "Allow automatic cloud fallback (off by default)."),
    # ---- router (capability-safe model selection)
    "router.require_verified": (bool, False, _bool,
        "Only route to models whose capability was proven by a recorded probe (chat included)."),
    "router.allow_unverified_chat": (bool, True, _bool,
        "Allow chat on models whose chat capability is only claimed (the decision records it)."),
    "router.allow_cloud": (bool, False, _bool,
        "Let the router *choose* a remote model by itself; explicit --model still works."),
    "router.prefer_local": (bool, True, _bool, "Prefer local models when abilities are equal."),
    "router.fallback": (bool, True, _bool,
        "After a retryable provider failure, try the next eligible model."),
    "router.max_fallbacks": (int, 2, _range(0, 10, integer=True), "Maximum fallback attempts."),
    # ---- context strategy
    "context.strategy": (str, "oldest_first", _one_of("oldest_first", "summarize", "ai_select", "manual", "ai_proposed"), "Context compaction strategy."),
    "context.reserve_tokens": (int, 256, _range(0, 32000, integer=True), "Head-room kept free in the context window."),
    "context.protect_pinned": (bool, True, _bool, "Never drop pinned messages/turns."),
    "context.memory_budget_ratio": (float, 0.25, _range(0.0, 0.9), "Share of the window memory retrieval may use."),
    # ---- memory
    "memory.active_ttl_minutes": (int, 240, _range(1, 100000, integer=True), "Active memory lifetime."),
    "memory.embeddings_enabled": (bool, False, _bool, "Enable embedding backfills."),
    "memory.remote_embeddings": (bool, False, _bool, "Allow remote embedding providers (opt-in)."),
    "memory.embedding_provider": (str, "local-hash", _str, "Embedding provider id."),
    "memory.duplicate_threshold": (float, 0.92, _range(0.5, 1.0), "Similarity above which a memory is a duplicate."),
    "memory.max_items_per_scope": (int, 2000, _range(10, 100000, integer=True), "Soft cap for retrieval scans."),
    # ---- permissions
    "permissions.default_duration": (str, "once",
        _one_of("once", "task", "conversation", "project", "persistent"),
        "Default grant duration; 'once' means one operation per approval."),
    "permissions.require_confirmation": (bool, True, _bool, "Confirm high-impact actions."),
    "permissions.denied_capabilities": (list, [], _str_list, "Capabilities that are always denied."),
    "permissions.approvals_enabled": (bool, True, _bool,
        "Queue an approval request when no grant covers an operation (instead of failing outright)."),
    "permissions.approval_ttl_minutes": (int, 60, _range(1, 10080, integer=True),
        "A pending approval expires after this long."),
    "permissions.max_pending_approvals": (int, 25, _range(1, 1000, integer=True),
        "Cap on queued approvals, so a loop cannot flood the queue."),
    "permissions.max_grant_hours": (int, 720, _range(1, 8760, integer=True),
        "Longest time-boxed grant that can be created (30 days by default)."),
    # ---- tools / mcp
    "tools.timeout_seconds": (int, 60, _range(1, 3600, integer=True), "Default tool timeout."),
    "tools.max_output_bytes": (int, 200000, _range(1024, 50000000, integer=True), "Truncate tool output above this size."),
    "tools.roots": (list, [], _str_list, "Directories file tools may touch (default: the project root, else <home>/workspace)."),
    "tools.max_file_bytes": (int, 2000000, _range(1024, 100000000, integer=True), "Largest file a tool may read in one call."),
    "tools.shell_enabled": (bool, True, _bool, "Register the shell.run tool (it still needs a grant to execute)."),
    "extensions.enabled": (bool, True, _bool,
        "Allow trusted extensions to register their tools."),
    "extensions.directory": (str, "", _path, "Where extensions are installed (default <home>/extensions)."),
    "tools.shell_denylist": (list,
        ["sudo", "su", "shutdown", "reboot", "halt", "poweroff", "mkfs", "dd",
         "fdisk", "parted", "mount", "umount", "chown", "chroot"],
        _str_list, "Executables shell.run refuses even with a grant."),
    "mcp.client_enabled": (bool, True, _bool, "Allow configured MCP client servers."),
    "mcp.client_timeout_seconds": (int, 20, _range(1, 600, integer=True),
        "Deadline for an MCP request (a wedged server must not freeze the CLI)."),
    "mcp.server_tools": (list, ["fs.read", "fs.list", "archx.info"], _str_list,
        "Tools the optional MCP server exposes (a whitelist, not the whole registry)."),
    "mcp.server_enabled": (bool, False, _bool, "Expose the optional MCP server (off by default)."),
    "mcp.server_host": (str, "127.0.0.1", _str, "Bind address for the MCP server."),
    "mcp.server_port": (int, 8848, _range(1, 65535, integer=True), "Port for the MCP server."),
    # ---- task history / versions / reproduction
    "tasks.enabled": (bool, True, _bool, "Record durable task history for chat turns and tool work."),
    "tasks.auto_record_chat": (bool, True, _bool,
        "Record one task per chat turn (disable to keep the history for explicit work only)."),
    "tasks.interrupt_stale_on_open": (bool, True, _bool,
        "On startup, mark tasks a previous process left running as interrupted."),
    "tasks.max_version_bytes": (int, 1048576, _range(1024, 100000000, integer=True),
        "Largest content a version record stores (larger content records only its checksum)."),
    # ---- scheduler
    "scheduler.max_concurrent_jobs": (int, 2, _range(1, 256, integer=True), "Maximum concurrent jobs."),
    "scheduler.cpu_limit_percent": (int, 80, _range(1, 100, integer=True), "CPU utilization ceiling."),
    "scheduler.memory_limit_mb": (int, 2048, _range(128, 1000000, integer=True), "Memory ceiling for jobs."),
    "scheduler.job_timeout_seconds": (int, 3600, _range(1, 864000, integer=True), "Hard job timeout."),
    "scheduler.max_attempts": (int, 2, _range(1, 100, integer=True),
        "Attempts a job gets before a crash leaves it interrupted."),
    "scheduler.poll_seconds": (float, 0.05, _range(0.001, 5),
        "How often the scheduler looks for work (and how often it checks a running child)."),
    "scheduler.stale_after_seconds": (int, 900, _range(30, 864000, integer=True),
        "A running job from another live process is considered stale after this long."),
    "scheduler.recover_on_open": (bool, True, _bool,
        "Requeue jobs whose worker disappeared when a workspace opens."),
    "scheduler.reap_on_open": (bool, True, _bool,
        "Fail running jobs whose hard deadline already passed when a workspace opens."),
    # ---- search / simple mode
    "search.default_limit": (int, 10, _range(1, 200, integer=True),
        "How many merged results a search returns when no limit is given."),
    "search.per_source": (int, 10, _range(1, 200, integer=True),
        "Maximum hits taken from each source before merging."),
    "search.include_files": (bool, True, _bool,
        "Search file contents inside the tool roots (never outside them)."),
    "search.max_files": (int, 400, _range(1, 100000, integer=True),
        "Stop scanning after this many files."),
    "search.max_file_bytes": (int, 262144, _range(1024, 100000000, integer=True),
        "Skip files larger than this when searching contents."),
    # ---- agents
    "agent.max_subagents": (int, 4, _range(1, 64, integer=True), "Concurrent subagents."),
    "agent.max_steps": (int, 40, _range(1, 1000, integer=True), "Agent step ceiling."),
    "agent.max_wall_seconds": (int, 1800, _range(10, 864000, integer=True), "Agent wall-clock ceiling."),
    "agent.token_budget": (int, 200000, _range(1000, 100000000, integer=True), "Token budget per task."),
    # ---- gui / interfaces
    "gui.host": (str, "0.0.0.0", _str, "GUI bind address."),
    "gui.port": (int, 8770, _range(1, 65535, integer=True), "GUI port."),
    "gui.theme": (str, "system", _one_of("system", "light", "dark"), "GUI theme."),
    # ---- voice / media
    "voice.enabled": (bool, False, _bool, "Enable voice features."),
    "voice.background_listening": (bool, False, _bool, "Allow wake-word listening (opt-in)."),
    "voice.wake_word": (str, "archx", _str, "Wake word."),
    "voice.retain_audio": (bool, False, _bool, "Persist raw audio."),
    # ---- automations
    "automations.enabled": (bool, True, _bool, "Enable scheduled tasks."),
    "automations.notify_channel": (str, "trace", _one_of("trace", "file", "webhook"), "Where run notifications go."),
    # ---- learning / research / experiments / play
    "learning.active_goal_limit": (int, 1, _range(1, 10, integer=True), "Concurrent learning goals."),
    "learning.try_first": (bool, False, _bool, "Encourage the learner to attempt before hints."),
    "research.max_subquestions": (int, 8, _range(1, 50, integer=True), "Research question decomposition cap."),
    "research.report_format": (str, "html", _one_of("html", "markdown"), "Research report output format."),
    "experiments.deadline_minutes": (int, 120, _range(1, 10080, integer=True), "Default experiment deadline."),
    "play.default_game": (str, "tictactoe", _one_of("tictactoe", "connect4", "nim"), "First built-in game."),
    # ---- training / remote / blender
    "training.max_hours": (int, 12, _range(1, 720, integer=True), "Training job ceiling."),
    "remote.require_approval": (bool, True, _bool, "Every remote dispatch needs approval."),
    "blender.executable": (str, "", _str, "Path to the Blender binary (empty = not installed)."),
    "blender.preview_resolution": (int, 480, _range(64, 4096, integer=True), "Preview render resolution."),
    # ---- extensions
    "extensions.allow_untrusted": (bool, False, _bool, "Load extensions without a trust review."),
    "extensions.directory": (str, "", _path, "Extension install directory."),
}

_PATH_DEFAULTS = {
    "paths.models": "models",
    "paths.projects": "projects",
    "paths.artifacts": "artifacts",
    "paths.backups": "backups",
    "storage.db_path": "archx.db",
    "storage.events_path": "events.db",
    "extensions.directory": "extensions",
}


def _env_name(key: str) -> str:
    return ENV_PREFIX + key.replace(".", "_").upper()


@dataclass
class Config:
    """Resolved configuration values plus provenance."""

    values: dict[str, Any]
    provenance: dict[str, str] = field(default_factory=dict)
    source_file: Path | None = None
    version: int = CONFIG_VERSION

    # -- access ----------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        if key not in SPEC:
            raise ConfigError(f"unknown setting {key!r}")
        return self.values.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def set(self, key: str, value: Any, *, source: str = "runtime") -> None:
        self.values[key] = _validate(key, value)
        self.provenance[key] = source

    def section(self, prefix: str) -> dict[str, Any]:
        return {k: v for k, v in self.values.items() if k.startswith(prefix + ".")}

    # -- derived paths ---------------------------------------------------
    @property
    def home(self) -> Path:
        return Path(self.get("paths.home"))

    def path(self, key: str) -> Path:
        value = self.get(key)
        if not value:
            raise ConfigError(f"path setting {key} is empty")
        return Path(value)

    def ensure_dirs(self) -> dict[str, Path]:
        created: dict[str, Path] = {}
        for key in ("paths.home", "paths.models", "paths.projects", "paths.artifacts", "paths.backups"):
            created[key] = ensure_directory(self.path(key))
        ensure_directory(self.path("storage.db_path").parent)
        ensure_directory(self.path("extensions.directory"))
        return created

    # -- serialisation ---------------------------------------------------
    def to_dict(self, *, redact_secrets: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {"version": self.version, "settings": {}}
        for key, value in sorted(self.values.items()):
            if redact_secrets and isinstance(value, str) and value.startswith(SECRET_MARKER):
                out["settings"][key] = SECRET_MARKER + "***"
            else:
                out["settings"][key] = value
        out["provenance"] = dict(sorted(self.provenance.items()))
        return out

    def save(self, path: str | os.PathLike[str]) -> Path:
        atomic_write_json(path, {"version": self.version, "settings": dict(sorted(self.values.items()))})
        return Path(path)

    # -- diffs -----------------------------------------------------------
    def diff(self, other: "Config") -> dict[str, tuple[Any, Any]]:
        keys = set(self.values) | set(other.values)
        return {k: (self.values.get(k), other.values.get(k)) for k in sorted(keys) if self.values.get(k) != other.values.get(k)}


def _validate(key: str, value: Any) -> Any:
    if key not in SPEC:
        raise ValidationError(f"unknown setting {key!r}")
    expected_type, _default, validator, _desc = SPEC[key]
    if expected_type is list:
        return validator(value)
    if expected_type is bool:
        return validator(value)
    if expected_type is int:
        if isinstance(value, bool):
            raise ValidationError("expected an integer (got a boolean)")
        try:
            return validator(int(value))
        except (TypeError, ValueError) as exc:
            raise ValidationError("expected an integer") from exc
    if expected_type is float:
        try:
            return validator(float(value))
        except (TypeError, ValueError) as exc:
            raise ValidationError("expected a number") from exc
    return validator(value)


def defaults() -> dict[str, Any]:
    return {key: copy.deepcopy(spec[1]) for key, spec in SPEC.items()}


def _expand_path_defaults(values: dict[str, Any]) -> dict[str, Any]:
    home = Path(values["paths.home"])
    for key, relative in _PATH_DEFAULTS.items():
        if not values.get(key):
            values[key] = str(home / relative)
    return values


def load_config(
    *,
    home: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
    create: bool = False,
) -> Config:
    """Resolve configuration from defaults, file, environment and overrides."""
    environ = dict(os.environ if env is None else env)
    values = defaults()
    provenance = {key: "default" for key in values}

    arg_home: str | None = None
    if home is not None:
        arg_home = os.path.expanduser(str(home))
        values["paths.home"] = arg_home
        provenance["paths.home"] = "argument"
    elif environ.get(ENV_PREFIX + "PATHS_HOME"):
        # The home directory can only be found from the environment before the
        # config file is located, otherwise ARCHX_PATHS_HOME would silently read
        # a different home's config file.
        values["paths.home"] = os.path.expanduser(environ[ENV_PREFIX + "PATHS_HOME"])
        provenance["paths.home"] = "environment"

    path = Path(config_path).expanduser() if config_path else None
    if path is None and environ.get(ENV_PREFIX + "CONFIG"):
        path = Path(os.path.expanduser(environ[ENV_PREFIX + "CONFIG"]))
    if path is None:
        path = Path(os.path.expanduser(values["paths.home"])) / "config.json"

    file_data = read_json(path) if path.exists() else None
    if file_data is not None:
        if not isinstance(file_data, dict):
            raise ConfigError(f"{path}: top-level config must be an object")
        version = int(file_data.get("version", 1))
        if version > CONFIG_VERSION:
            raise ConfigError(
                f"{path}: config version {version} is newer than this build ({CONFIG_VERSION}); upgrade Archx Agent"
            )
        settings = file_data.get("settings", file_data)
        if not isinstance(settings, dict):
            raise ConfigError(f"{path}: 'settings' must be an object")
        for key, raw in settings.items():
            if key in {"version", "provenance"}:
                continue
            if key not in SPEC:
                raise ConfigError(f"{path}: unknown setting {key!r} (see `archx-agent config list`)")
            try:
                values[key] = _validate(key, raw)
            except ValidationError as exc:
                expected_type, _d, _v, desc = SPEC[key]
                raise ConfigError(
                    f"{path}: invalid value for {key}: {exc.message}; expected {_type_name(expected_type)}. {desc}"
                ) from exc
            provenance[key] = f"file:{path}"

    for key in SPEC:
        env_key = _env_name(key)
        if env_key in environ and environ[env_key] != "":
            try:
                values[key] = _validate(key, environ[env_key])
            except ValidationError as exc:
                raise ConfigError(
                    f"environment variable {env_key}: invalid value for {key}: {exc.message};"
                    f" expected {_type_name(SPEC[key][0])}"
                ) from exc
            provenance[key] = f"env:{env_key}"

    if arg_home is not None:
        # An explicit --home beats the environment: the CLI argument is the more
        # specific instruction, and silently using a different database would be
        # the worst possible outcome.
        values["paths.home"] = arg_home
        provenance["paths.home"] = "argument"

    for key, raw in (overrides or {}).items():
        if raw is None:
            continue
        values[key] = _validate(key, raw)
        provenance[key] = "override"

    values = _expand_path_defaults(values)
    cfg = Config(values=values, provenance=provenance, source_file=path if path.exists() else None)
    if create:
        cfg.ensure_dirs()
        if not path.exists():
            cfg.save(path)
    _validate_cross_field(cfg)
    return cfg


def _type_name(t: type) -> str:
    return {str: "a string", int: "an integer", float: "a number", bool: "true/false", list: "a comma-separated list"}.get(
        t, t.__name__
    )


def _validate_cross_field(cfg: Config) -> None:
    if cfg.get("model.output_budget") >= cfg.get("model.context_limit"):
        raise ConfigError(
            "model.output_budget must be smaller than model.context_limit "
            f"(got output_budget={cfg.get('model.output_budget')}, context_limit={cfg.get('model.context_limit')})"
        )
    if cfg.get("storage.db_path") == cfg.get("storage.events_path"):
        raise ConfigError("storage.db_path and storage.events_path must differ (traces live in their own file)")
    if cfg.get("model.local_only") and cfg.get("model.allow_cloud_fallback"):
        raise ConfigError("model.local_only=true forbids model.allow_cloud_fallback=true")


def resolve_secret(value: str | None, *, env: Mapping[str, str] | None = None, allow_literal: bool = False) -> str | None:
    """Resolve ``secret://env/NAME`` or ``secret://file/PATH`` references.

    The returned value is intended for immediate use; it must never be logged.
    """
    if value is None:
        return None
    environ = os.environ if env is None else env
    if not value.startswith(SECRET_MARKER):
        if allow_literal:
            return value
        raise ConfigError(
            "credentials must be supplied as secret://env/NAME or secret://file/PATH, not as literal text"
        )
    ref = value[len(SECRET_MARKER) :]
    kind, _, target = ref.partition("/")
    if kind == "env":
        found = environ.get(target)
        if not found:
            raise ConfigError(f"secret reference {SECRET_MARKER}{ref} not found in environment ({target})")
        return found
    if kind == "file":
        path = Path(os.path.expanduser(target))
        if not path.exists():
            raise ConfigError(f"secret file not found for {SECRET_MARKER}{ref}")
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"cannot read secret file for {SECRET_MARKER}{ref}: {exc.strerror}") from exc
    raise ConfigError(f"unsupported secret reference scheme {kind!r} (use env/NAME or file/PATH)")


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-2:]} (masked)"


def list_settings() -> list[dict[str, Any]]:
    return [
        {"key": key, "type": _type_name(spec[0]), "default": spec[1], "description": spec[3]}
        for key, spec in sorted(SPEC.items())
    ]


__all__ = [
    "Config",
    "SPEC",
    "CONFIG_VERSION",
    "ENV_PREFIX",
    "defaults",
    "load_config",
    "resolve_secret",
    "mask_secret",
    "list_settings",
]
