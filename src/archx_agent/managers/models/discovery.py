"""Discover/register local model files and refresh observed availability facts."""

from __future__ import annotations

from pathlib import Path

from archx_agent.helpers.exceptions import NotFoundError, ValidationError
from archx_agent.helpers.timeutil import iso_now, new_id
from archx_agent.managers.models.files import observe_file
from archx_agent.managers.models.naming import parse_gguf_name
from archx_agent.managers.models.records import ModelRecord


class ModelManagerDiscoveryMixin:
    """Local catalogue discovery, not a native-inference validator."""

    def discover_local(
        self, directory: str | None = None, *, recursive: bool = True
    ) -> list[ModelRecord]:
        """Scan configured roots for GGUF files; never fall back to the process cwd."""
        configured = directory or self.models_root
        if not configured:
            return []
        root = Path(configured).expanduser()
        if not root.exists():
            return []
        if not root.is_dir():
            raise ValidationError(
                "model discovery root must be a directory", path=str(root)
            )
        pattern = "**/*.gguf" if recursive else "*.gguf"
        found = [
            self.register_local_file(path)
            for path in sorted(root.glob(pattern))
            if path.is_file()
        ]
        if found:
            self.trace(
                "system",
                "models.discovered",
                payload={"count": len(found), "root": str(root)},
            )
        return found

    def register_local_file(
        self, path: str | Path, *, hash_file: str | None = None
    ) -> ModelRecord:
        p = Path(path).expanduser()
        try:
            resolved = p.resolve()
        except (OSError, RuntimeError) as exc:
            raise ValidationError(
                "cannot resolve model file path", path=str(p)
            ) from exc
        existing = self.store.query_one(
            "SELECT sha256 FROM models WHERE provider='local' AND path=?",
            (str(resolved),),
        )
        observation = observe_file(
            p,
            hash_file=hash_file == "always"
            or (
                hash_file is None
                and (self.hash_files or bool(existing and existing["sha256"]))
            ),
        )
        facts = observation["facts"]
        if observation["state"] == "missing":
            raise NotFoundError(f"model file not found: {p}", path=str(p))
        if not facts["is_file"] or (
            observation["state"] == "invalid" and facts["size_bytes"] is None
        ):
            raise ValidationError(observation["error"], path=str(p))
        # A tiny regular file remains visible as invalid, never as proof of inference.
        claims = parse_gguf_name(p.name)
        record = ModelRecord(
            id=new_id("mdl_"),
            name=p.stem,
            provider="local",
            runtime="llama-cpp",
            path=str(resolved),
            model_ref=None,
            format="gguf" if p.suffix.lower() == ".gguf" else p.suffix.lstrip("."),
            quantization=claims.get("quantization"),
            param_count=claims.get("param_count"),
            context_length=2048,
            size_bytes=facts["size_bytes"],
            sha256=observation["sha256"],
            facts=facts,
            claims=claims,
            user_metadata={},
            verified_capabilities=[],
            capability_basis={},
            verification_state="unverified",
            state=observation["state"],
            tags=[],
            notes=None,
            success_count=0,
            failure_count=0,
            discovered_at=iso_now(),
            updated_at=iso_now(),
            last_used_at=None,
            last_error=observation["error"],
        )
        result = self._write("model.register", {"model": record.to_dict()})
        return self.require(result["id"])

    def refresh_states(self) -> dict[str, int]:
        """Recheck all local rows, including tiny replacements and disabled intent."""
        changed = {"missing": 0, "restored": 0}
        # The catalogue can exceed the presentation API's default 200-row page.
        rows = self.store.query(
            "SELECT id FROM models WHERE provider = 'local' AND state != 'removed' ORDER BY id"
        )
        for row in rows:
            record = self.require(row["id"])
            if not record.path:
                continue
            observation = observe_file(
                Path(record.path), hash_file=bool(record.sha256) or self.hash_files
            )
            result = self._write(
                "model.file_observation", {"id": record.id, "observation": observation}
            )
            if result["previous_state"] != "missing" and result["state"] == "missing":
                changed["missing"] += 1
            if result["previous_state"] in ("missing", "invalid") and result[
                "state"
            ] in ("usable", "disabled"):
                changed["restored"] += 1
        return changed
