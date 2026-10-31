"""Preflight operations for training workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archx_agent.helpers.exceptions import (
    NotFoundError,
    ValidationError,
)
from archx_agent.managers.training import (
    FINETUNE_METHODS,
    METHODS,
    RUNNABLE_METHODS,
)


class TrainingServicePreflightMixin:
    """Preflight responsibility for TrainingService."""

    def blockers(self, method: str, base_model: str | None = None) -> list[str]:
        """Every reason this build cannot fine-tune a transformer, in the order found."""
        reasons: list[str] = []
        if method not in FINETUNE_METHODS:
            return reasons
        if not self.ws.config.get("training.enabled", False):
            reasons.append(
                "training is off: `archx-agent config set training.enabled true`"
            )
        wanted = (
            base_model or str(self.ws.config.get("training.base_model", "") or "")
        ).strip()
        if not wanted:
            reasons.append(
                "no base model is named (training.base_model is empty), and this build ships no "
                "transformer weights"
            )
        else:
            record = self._model(wanted)
            if record is None:
                reasons.append(f"{wanted!r} is not a registered model")
            else:
                reasons.append(
                    f"model {record.name!r} is registered, but a chat runtime is not a trainer"
                )
        weights = str(self.ws.config.get("training.weights_dir", "") or "").strip()
        if not weights:
            reasons.append(
                "no training.weights_dir is configured, so no local checkpoint could be loaded"
            )
        elif not Path(weights).exists():
            reasons.append(
                f"training.weights_dir {weights!r} does not exist on this machine"
            )
        if not self._library_available("torch"):
            reasons.append(
                "no fine-tuning library is installed here (torch is not importable)"
            )
        if not self._gpu_present():
            reasons.append(
                "no CUDA device is visible: a step of LoRA on a real checkpoint needs one"
            )
        reasons.append(
            f"no adapter in this build can fine-tune anything: `{method}` is not implemented, and "
            "a registered model is not enough"
        )
        return reasons

    @staticmethod
    def _library_available(name: str) -> bool:
        import importlib.util

        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):  # pragma: no cover - a broken install
            return False

    @staticmethod
    def _gpu_present() -> bool:
        """A GPU is present when a CUDA device can actually be opened - not when a file exists."""
        import importlib.util

        if importlib.util.find_spec("torch") is None:
            return False
        try:  # pragma: no cover - only on a machine with torch installed
            import torch

            return bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001 - any failure means "not usable here"
            return False

    def _model(self, wanted: str):
        try:
            found = self.ws.models.get(wanted)
        except Exception:  # noqa: BLE001 - a miss is a normal outcome
            found = None
        if found is not None and not hasattr(found, "is_err"):
            return found
        if found is not None and not found.is_err:
            return found.value
        try:
            named = self.ws.models.by_name(wanted)
        except Exception:  # noqa: BLE001
            return None
        if hasattr(named, "is_err"):
            return None if named.is_err else named.value
        return named

    def preflight(
        self,
        *,
        method: str,
        dataset: str | None = None,
        base_model: str | None = None,
    ) -> dict[str, Any]:
        """What would have to be true before this run could mean anything, and what is true."""
        if method not in METHODS:
            raise ValidationError(
                f"unknown method {method!r} (this build knows {', '.join(METHODS)})"
            )
        checks: list[dict[str, Any]] = []

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"check": name, "ok": bool(ok), "detail": detail})

        check(
            "method",
            method in RUNNABLE_METHODS or method in FINETUNE_METHODS,
            f"{method} is a method this build knows",
        )
        if method in FINETUNE_METHODS:
            reasons = self.blockers(method, base_model)
            check("adapter", False, f"{method} cannot run here: {'; '.join(reasons)}")
            return {
                "method": method,
                "runnable": False,
                "checks": checks,
                "reasons": reasons,
                "note": "this build cannot fine-tune a transformer; nothing was attempted",
            }

        dataset_id = dataset
        dataset_view: dict[str, Any] | None = None
        if dataset_id:
            try:
                dataset_view = self.ws.data.view(dataset_id)
            except NotFoundError:
                dataset_view = None
        check(
            "dataset",
            dataset_view is not None,
            f"dataset {dataset_id!r} exists"
            if dataset_view
            else f"no such dataset: {dataset_id}",
        )
        if dataset_view:
            counts = dataset_view["counts"]
            check("records", counts["kept"] > 0, f"{counts['kept']} kept records")
            by_split = counts["by_split"]
            check(
                "split",
                bool(by_split),
                "the dataset has a split"
                if by_split
                else "the dataset has no split yet: run `dataset split`",
            )
            check(
                "validation",
                by_split.get("val", 0) + by_split.get("test", 0) > 0,
                f"{by_split.get('val', 0)} val and {by_split.get('test', 0)} test records",
            )
            check(
                "built",
                bool(dataset_view.get("checksum")),
                "the dataset was built and its manifest recorded"
                if dataset_view.get("checksum")
                else "the dataset was never built: run `dataset build`",
            )
            if dataset_view.get("checksum"):
                verified = self.ws.data.verify(dataset_view["id"])
                check("manifest", verified["agrees"], verified["note"])

        runnable = all(item["ok"] for item in checks)
        return {
            "method": method,
            "runnable": runnable,
            "checks": checks,
            "reasons": [
                f"{item['check']}: {item['detail']}"
                for item in checks
                if not item["ok"]
            ],
            "note": (
                "every check passed; this run would train a real model on this machine"
                if runnable
                else "at least one check failed, and a run would not be honest"
            ),
        }
