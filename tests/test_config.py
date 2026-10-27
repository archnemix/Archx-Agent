from __future__ import annotations

import json
import os

import pytest

from archx_agent.helpers.config import (
    CONFIG_VERSION,
    SECRET_MARKER,
    Config,
    defaults,
    list_settings,
    load_config,
    mask_secret,
    resolve_secret,
)
from archx_agent.helpers.exceptions import ConfigError, ValidationError
from archx_agent.helpers.redaction import REDACTED, redact, redact_text, register_secret
from archx_agent.helpers.tokens import HeuristicTokenizer, default_tokenizer


class TestConfig:
    def test_defaults_and_derived_paths(self, tmp_path):
        cfg = load_config(home=tmp_path / "h", env={})
        assert cfg.get("general.brand") == "Archx Agent"
        assert cfg.path("storage.db_path") == tmp_path / "h" / "archx.db"
        assert cfg.path("paths.artifacts") == tmp_path / "h" / "artifacts"
        assert cfg.provenance["model.local_only"] == "default"

    def test_file_env_override_precedence(self, tmp_path):
        home = tmp_path / "h"
        home.mkdir()
        (home / "config.json").write_text(
            json.dumps({"version": CONFIG_VERSION, "settings": {"model.temperature": 0.5, "model.context_limit": 4096}})
        )
        cfg = load_config(home=home, env={"ARCHX_MODEL_TEMPERATURE": "0.9"})
        assert cfg.get("model.temperature") == 0.9
        assert cfg.provenance["model.temperature"] == "env:ARCHX_MODEL_TEMPERATURE"
        assert cfg.get("model.context_limit") == 4096
        cfg2 = load_config(
            home=home, env={"ARCHX_MODEL_TEMPERATURE": "0.9"}, overrides={"model.temperature": 0.1}
        )
        assert cfg2.get("model.temperature") == 0.1
        assert cfg2.provenance["model.temperature"] == "override"

    def test_unknown_key_names_file_and_key(self, tmp_path):
        home = tmp_path / "h"
        home.mkdir()
        (home / "config.json").write_text(json.dumps({"version": 2, "settings": {"model.nope": 1}}))
        with pytest.raises(ConfigError) as exc:
            load_config(home=home, env={})
        assert "model.nope" in str(exc.value)
        assert "unknown setting" in str(exc.value)

    def test_invalid_value_names_setting_and_expected_type(self, tmp_path):
        home = tmp_path / "h"
        home.mkdir()
        (home / "config.json").write_text(json.dumps({"version": 2, "settings": {"model.context_limit": "lots"}}))
        with pytest.raises(ConfigError) as exc:
            load_config(home=home, env={})
        assert "model.context_limit" in str(exc.value)
        assert "integer" in str(exc.value)

    def test_env_boolean_forms(self, tmp_path):
        for raw, expected in [("true", True), ("0", False), ("yes", True), ("off", False)]:
            cfg = load_config(home=tmp_path / "h", env={"ARCHX_MODEL_LOCAL_ONLY": raw})
            assert cfg.get("model.local_only") is expected
        with pytest.raises(ConfigError):
            load_config(home=tmp_path / "h", env={"ARCHX_MODEL_LOCAL_ONLY": "maybe"})

    def test_cross_field_validation(self, tmp_path):
        with pytest.raises(ConfigError):
            load_config(home=tmp_path / "h", env={}, overrides={"model.output_budget": 5000})
        with pytest.raises(ConfigError):
            load_config(
                home=tmp_path / "h",
                env={},
                overrides={"model.local_only": True, "model.allow_cloud_fallback": True},
            )

    def test_newer_config_version_rejected(self, tmp_path):
        home = tmp_path / "h"
        home.mkdir()
        (home / "config.json").write_text(json.dumps({"version": 99, "settings": {}}))
        with pytest.raises(ConfigError):
            load_config(home=home, env={})

    def test_create_writes_file_and_dirs(self, tmp_path):
        home = tmp_path / "h"
        cfg = load_config(home=home, env={}, create=True)
        assert (home / "config.json").exists()
        assert (home / "models").is_dir()
        saved = json.loads((home / "config.json").read_text())
        assert saved["version"] == CONFIG_VERSION

    def test_secret_references(self, tmp_path):
        assert resolve_secret("secret://env/MY_KEY", env={"MY_KEY": "abc"}) == "abc"
        with pytest.raises(ConfigError):
            resolve_secret("secret://env/MISSING", env={})
        with pytest.raises(ConfigError):
            resolve_secret("literal-key-value")
        assert resolve_secret("literal-key-value", allow_literal=True) == "literal-key-value"
        with pytest.raises(ConfigError):
            resolve_secret("secret://vault/x", env={})
        secret_file = tmp_path / "k.txt"
        secret_file.write_text("from-file\n")
        assert resolve_secret(f"secret://file/{secret_file}", env={}) == "from-file"

    def test_to_dict_hides_secrets(self, tmp_path):
        cfg = load_config(home=tmp_path / "h", env={})
        cfg.set("model.default_id", "secret://env/FAKE")
        assert "FAKE" in str(cfg.to_dict(redact_secrets=False))
        assert "FAKE" not in str(cfg.to_dict())
        assert mask_secret("abcdefghijklmn") .startswith("abcd")
        assert "abcdefghijklmn" not in mask_secret("abcdefghijklmn")

    def test_set_validates(self, tmp_path):
        cfg = load_config(home=tmp_path / "h", env={})
        with pytest.raises(ValidationError):
            cfg.set("context.strategy", "magic")
        with pytest.raises(Exception):
            cfg.set("does.not.exist", 1)

    def test_every_spec_key_documented(self):
        rows = list_settings()
        assert len(rows) == len(defaults())
        assert all(row["description"] for row in rows)

    def test_diff(self, tmp_path):
        a = load_config(home=tmp_path / "a", env={})
        b = load_config(home=tmp_path / "b", env={})
        diff = a.diff(b)
        assert "paths.home" in diff


class TestRedaction:
    def test_known_patterns(self):
        samples = [
            "sk-abcdefghijklmnopqrstuvwx",
            "ghp_" + "a" * 30,
            "hf_" + "b" * 30,
            "AIza" + "c" * 35,
            "Bearer abcdefghijklmnop",
            "eyJhbGciOiJI.eyJzdWIiOiIx.SflKxwRJSM",
            "AKIAIOSFODNN7EXAMPLE",
        ]
        for sample in samples:
            assert sample.split()[0][:6] in redact_text(f"value={sample}") or REDACTED in redact_text(sample), sample
            assert redact_text(f"prefix {sample} suffix").count(REDACTED) >= 1, sample

    def test_url_credentials(self):
        out = redact_text("https://user:hunter2@example.com/x")
        assert "hunter2" not in out

    def test_registered_secret_and_headers(self):
        register_secret("plain-secret-value")
        assert "plain-secret-value" not in redact_text("x plain-secret-value y")
        out = redact_text("Authorization: tokenvalue12345")
        assert "tokenvalue12345" not in out

    def test_sensitive_keys_in_structures(self):
        payload = {"api_key": "anything", "nested": {"password": "p"}, "list": ["sk-" + "z" * 20]}
        cleaned = redact(payload)
        assert cleaned["api_key"] == REDACTED
        assert cleaned["nested"]["password"] == REDACTED
        assert REDACTED in cleaned["list"][0]

    def test_unicode_preserved(self):
        assert redact_text("مرحبا بالعالم") == "مرحبا بالعالم"

    def test_empty_inputs(self):
        assert redact_text("") == ""
        assert redact({}) == {}
        assert redact(None) is None


class TestTokens:
    def test_heuristic_is_monotonic(self):
        tok = HeuristicTokenizer()
        assert tok.count("") == 0
        assert tok.count("hello world") >= 2
        assert tok.count("a" * 100) > tok.count("a" * 10)
        long_text = "word " * 1000
        assert tok.count(long_text) > 900

    def test_count_messages(self):
        tok = default_tokenizer()
        assert tok.count_messages([]) == 3
        assert tok.count_messages([{"role": "user", "content": "hello"}]) > 4

    def test_unicode_counts(self):
        tok = HeuristicTokenizer()
        assert tok.count("日本語のテキスト") > 0


class TestHomeResolution:
    def test_env_home_selects_its_own_config_file(self, tmp_path):
        """ARCHX_PATHS_HOME must locate that home's config file, not ~/.archx/config.json."""
        home = tmp_path / "envhome"
        home.mkdir()
        (home / "config.json").write_text(
            '{"version": 1, "settings": {"model.context_limit": 1234}}', encoding="utf-8"
        )
        config = load_config(env={"ARCHX_PATHS_HOME": str(home)})
        assert config.get("paths.home") == str(home)
        assert config.get("model.context_limit") == 1234
        assert config.provenance["paths.home"] == "env:ARCHX_PATHS_HOME"

    def test_explicit_home_beats_env_home(self, tmp_path):
        config = load_config(home=str(tmp_path / "explicit"), env={"ARCHX_PATHS_HOME": str(tmp_path / "env")})
        assert config.get("paths.home") == str(tmp_path / "explicit")
        assert config.provenance["paths.home"] == "argument"
