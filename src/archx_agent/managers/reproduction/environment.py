"""ReproductionManager: environment operations."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from .records import _SENSITIVE_SETTINGS, Issue, _is_loopback


class ReproductionManagerEnvironmentMixin:
    def _setting(self, key: str) -> Any:
        if self.config is None:
            return None
        try:
            return self.config.get(key)
        except Exception:  # noqa: BLE001 - an unknown key must not break a capture
            return None

    def _settings_snapshot(self) -> dict[str, Any]:
        return {key: self._setting(key) for key in _SENSITIVE_SETTINGS}

    def _model_state(self, model_id: str) -> tuple[dict[str, Any], list[Issue]]:
        issues: list[Issue] = []
        info: dict[str, Any] = {"id": model_id}
        record = None
        if self.models is not None:
            found = self.models.get(model_id)
            record = found.value if found.is_ok else None
        if record is None:
            info.update({"registered": False, "available": False})
            issues.append(
                Issue(
                    "blocker",
                    "model_missing",
                    f"the model {model_id} is no longer registered; a replay would select a different model",
                )
            )
            return info, issues
        runtime = record.runtime
        info.update(
            {
                "registered": True,
                "name": record.name,
                "runtime": runtime,
                "provider": record.provider,
                "path": record.path,
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
                "context_length": record.context_length,
            }
        )
        if runtime == "scripted":
            info["simulated"] = True
            issues.append(
                Issue(
                    "caveat",
                    "model_simulated",
                    f"{record.name} is a simulated test double: it performs no inference, "
                    "so its answer cannot be reproduced",
                )
            )
        elif runtime == "llama-cpp":
            exists = bool(record.path) and Path(str(record.path)).exists()
            info["path_exists"] = exists
            if not exists:
                info["simulated"] = False
                issues.append(
                    Issue(
                        "blocker",
                        "model_file_missing",
                        f"the model file for {record.name} is missing ({record.path or 'no path'})",
                    )
                )
        else:
            base_url = (record.facts or {}).get("base_url")
            info["base_url"] = base_url
            remote = bool(base_url) and not _is_loopback(base_url)
            info["remote"] = remote
            if remote:
                issues.append(
                    Issue(
                        "caveat",
                        "model_remote",
                        f"{record.name} runs at {base_url}: the provider can change the model "
                        "or its sampling without notice",
                    )
                )
        return info, issues
