"""M23: extension manifests, the trust boundary, and real extension tool processes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from archx_agent.application.workspace import open_workspace
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ConflictError,
    ExtensionError,
    NotFoundError,
    ToolNotFoundError,
    ToolTimeoutError,
)
from archx_agent.managers.extensions import validate_manifest

WORDCOUNT = """
import json, sys
request = json.load(sys.stdin)
text = request["arguments"].get("text", "")
words = [w for w in text.split() if w.strip()]
print(json.dumps({"words": len(words), "tool": request["tool"], "extension": request["extension"],
                  "echo": text.upper()}))
"""

FAILER = """
import sys
sys.stderr.write("the extension is having a bad day\\n")
raise SystemExit(3)
"""

NOJSON = """
print("this is not json")
"""

SLOW = """
import json, sys, time
json.load(sys.stdin)
time.sleep(30)
print(json.dumps({"done": True}))
"""


def make_extension(
    root: Path,
    *,
    name: str = "wordcount",
    version: str = "1.0.0",
    tools: list[dict] | None = None,
    scripts: dict[str, str] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for filename, source in (scripts or {"count.py": WORDCOUNT}).items():
        (root / filename).write_text(source)
    if tools is None:
        tools = [
            {
                "name": "count",
                "description": "count words in the text you pass",
                "capability": "process.exec",
                "command": [sys.executable, "count.py"],
                "inputs": {"text": {"type": "string", "description": "the text"}},
                "required": ["text"],
            }
        ]
    manifest = {"name": name, "version": version, "description": "test extension", "tools": tools}
    (root / "extension.json").write_text(json.dumps(manifest, indent=2))
    return root


@pytest.fixture()
def ws(tmp_path):
    with open_workspace(home=str(tmp_path / "home"), env={}) as workspace:
        yield workspace


@pytest.fixture()
def ext_dir(tmp_path):
    return make_extension(tmp_path / "ext" / "wordcount")


def _active(ws, path, name="wordcount"):
    extension = ws.extensions.install(path, trust=True, enable=True)
    return extension


# --------------------------------------------------------------------------
# manifest validation
# --------------------------------------------------------------------------
class TestManifestValidation:
    def test_a_good_manifest_is_normalised(self, ext_dir):
        manifest = validate_manifest(json.loads((ext_dir / "extension.json").read_text()), path=str(ext_dir))
        assert manifest["name"] == "wordcount"
        assert manifest["tools"][0]["capability"] == "process.exec"
        assert manifest["tools"][0]["risk"] == "high"  # capability risk wins over any claim
        assert manifest["tools"][0]["types"] == {"text": "str"}

    def test_manifest_cannot_lower_the_risk(self, ext_dir):
        raw = json.loads((ext_dir / "extension.json").read_text())
        raw["tools"][0]["risk"] = "low"
        raw["tools"][0]["capability"] = "shell.run"
        manifest = validate_manifest(raw, path=str(ext_dir))
        assert manifest["tools"][0]["risk"] == "high"
        assert manifest["tools"][0]["claimed_risk"] == "low"

    @pytest.mark.parametrize(
        "mutate,fragment",
        [
            (lambda m: m.pop("version"), "version"),
            (lambda m: m.update(name="Bad Name"), "lowercase"),
            (lambda m: m.update(tools=[]), "tools"),
            (lambda m: m["tools"][0].update(capability="fs.teleport"), "not one this build knows"),
            (lambda m: m["tools"][0].update(entry={"type": "python-import"}), "not supported"),
            (lambda m: m["tools"][0].update(command=[]), "non-empty list"),
            (lambda m: m["tools"][0].update(command=[sys.executable, "/etc/passwd"]), "outside the extension"),
            (lambda m: m["tools"][0].update(command=[sys.executable, "../../escape.py"]), "escapes the extension"),
            (lambda m: m["tools"][0].update(required=["nope"]), "not declared"),
            (lambda m: m["tools"].append(dict(m["tools"][0])), "duplicate tool"),
        ],
    )
    def test_bad_manifests_are_refused_with_a_reason(self, ext_dir, mutate, fragment):
        raw = json.loads((ext_dir / "extension.json").read_text())
        mutate(raw)
        with pytest.raises(ExtensionError) as exc:
            validate_manifest(raw, path=str(ext_dir))
        assert fragment in exc.value.message

    def test_missing_manifest_is_a_not_found(self, ws, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(NotFoundError, match="extension.json"):
            ws.extensions.install(empty)

    def test_invalid_json_is_reported(self, ws, tmp_path):
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "extension.json").write_text("{not json")
        with pytest.raises(ExtensionError, match="not valid JSON"):
            ws.extensions.install(broken)


# --------------------------------------------------------------------------
# install / trust / enable
# --------------------------------------------------------------------------
class TestExtensionLifecycle:
    def test_install_records_but_registers_nothing(self, ws, ext_dir):
        extension = ws.extensions.install(ext_dir)
        assert extension.trust == "untrusted"
        assert extension.enabled is False
        assert len(extension.manifest_hash or "") == 64
        assert not any(spec.name.startswith("ext.wordcount") for spec in ws.tools.specs())
        rows = ws.extensions.tools_of(extension.id)
        assert [row["name"] for row in rows] == ["count"]
        assert rows[0]["enabled"] == 0

    def test_installing_the_same_manifest_twice_is_refused(self, ws, ext_dir):
        ws.extensions.install(ext_dir)
        with pytest.raises(ConflictError, match="already installed"):
            ws.extensions.install(ext_dir)

    def test_reinstall_with_a_new_version_resets_trust(self, ws, ext_dir):
        first = _active(ws, ext_dir)
        assert first.trusted
        make_extension(ext_dir, version="1.1.0")
        second = ws.extensions.install(ext_dir)
        assert second.version == "1.1.0"
        assert second.trust == "untrusted"
        assert "manifest changed" in (second.notes or "")
        assert not any(spec.name.startswith("ext.wordcount") for spec in ws.tools.specs())

    def test_trust_registers_and_untrust_removes(self, ws, ext_dir):
        extension = ws.extensions.install(ext_dir, enable=True)
        ws.extensions.trust(extension.name)
        assert any(spec.name == "ext.wordcount.count" for spec in ws.tools.specs())
        ws.extensions.trust(extension.name, trusted=False)
        with pytest.raises(ToolNotFoundError):
            ws.tools.execute("ext.wordcount.count", {"text": "hi"})

    def test_enable_without_trust_registers_nothing(self, ws, ext_dir):
        extension = ws.extensions.install(ext_dir)
        updated = ws.extensions.set_enabled(extension.name, enabled=True)
        assert updated.enabled and not updated.trusted
        assert not any(spec.name.startswith("ext.wordcount") for spec in ws.tools.specs())

    def test_disabling_removes_the_tool(self, ws, ext_dir):
        extension = _active(ws, ext_dir)
        ws.extensions.set_enabled(extension.name, enabled=False)
        with pytest.raises(ToolNotFoundError):
            ws.tools.execute("ext.wordcount.count", {"text": "hi"})

    def test_extensions_can_be_switched_off_globally(self, ws, ext_dir):
        ws.config.set("extensions.enabled", False)
        extension = ws.extensions.install(ext_dir, trust=True, enable=True)
        assert not any(spec.name.startswith("ext.wordcount") for spec in ws.tools.specs())
        with pytest.raises(ToolNotFoundError):
            ws.tools.execute(ws.extensions.spec_name("wordcount", "count"), {"text": "hi"})
        # and an already-installed extension stops registering when the switch is checked again
        ws.extensions.set_enabled(extension.name, enabled=True)
        assert not any(spec.name.startswith("ext.wordcount") for spec in ws.tools.specs())

    def test_remove_deletes_rows_and_specs(self, ws, ext_dir):
        extension = _active(ws, ext_dir)
        ws.extensions.remove(extension.name)
        assert ws.extensions.extensions() == []
        assert ws.extensions.tools_of(extension.id) == []
        assert not any(spec.name.startswith("ext.wordcount") for spec in ws.tools.specs())

    def test_status_reports_registration_counts(self, ws, ext_dir):
        _active(ws, ext_dir)
        status = ws.extensions.status()[0]
        assert status["tool_count"] == 1
        assert status["registered"] == 1
        assert status["trust"] == "trusted"

    def test_state_survives_a_reopen(self, tmp_path, ext_dir):
        home = str(tmp_path / "reopen")
        with open_workspace(home=home, env={}) as first:
            _active(first, ext_dir)
        with open_workspace(home=home, env={}) as second:
            rows = second.extensions.extensions()
            assert rows[0].trusted and rows[0].enabled
            assert second.extensions.tools_of(rows[0].id)[0]["enabled"] == 1


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------
class TestExtensionExecution:
    def test_the_tool_needs_its_capability_then_really_runs(self, ws, ext_dir):
        _active(ws, ext_dir)
        with pytest.raises(ApprovalRequiredError) as exc:
            ws.tools.execute("ext.wordcount.count", {"text": "one two three"})
        assert exc.value.capability == "process.exec"
        ws.permissions.approve(exc.value.approval_id)
        run = ws.tools.execute("ext.wordcount.count", {"text": "one two three"})
        assert run.status == "succeeded"
        assert run.result["words"] == 3
        assert run.result["echo"] == "ONE TWO THREE"
        assert run.result["tool"] == "count"
        assert run.result["extension"] == "wordcount"

    def test_missing_argument_is_a_validation_error(self, ws, ext_dir):
        _active(ws, ext_dir)
        ws.permissions.grant("process.exec", subject="ext.wordcount.count", duration="persistent", confirm=True)
        from archx_agent.helpers.exceptions import ToolValidationError

        with pytest.raises(ToolValidationError, match="requires text"):
            ws.tools.execute("ext.wordcount.count", {})

    def test_a_failing_process_is_a_failed_run_with_stderr(self, ws, tmp_path):
        root = make_extension(
            tmp_path / "ext" / "failer",
            name="failer",
            scripts={"fail.py": FAILER},
            tools=[
                {
                    "name": "boom",
                    "description": "fails",
                    "capability": "process.exec",
                    "command": [sys.executable, "fail.py"],
                    "inputs": {},
                }
            ],
        )
        ws.extensions.install(root, trust=True, enable=True)
        ws.permissions.grant("process.exec", subject="ext.failer.boom", duration="persistent", confirm=True)
        with pytest.raises(ExtensionError, match="bad day"):
            ws.tools.execute("ext.failer.boom", {})
        assert ws.tools.runs(tool="ext.failer.boom")[0]["status"] == "failed"

    def test_non_json_output_is_reported(self, ws, tmp_path):
        root = make_extension(
            tmp_path / "ext" / "nojson",
            name="nojson",
            scripts={"nojson.py": NOJSON},
            tools=[
                {
                    "name": "quiet",
                    "description": "prints prose",
                    "capability": "process.exec",
                    "command": [sys.executable, "nojson.py"],
                    "inputs": {},
                }
            ],
        )
        ws.extensions.install(root, trust=True, enable=True)
        ws.permissions.grant("process.exec", subject="ext.nojson.quiet", duration="persistent", confirm=True)
        with pytest.raises(ExtensionError, match="did not print JSON"):
            ws.tools.execute("ext.nojson.quiet", {})

    def test_a_hanging_extension_is_killed(self, ws, tmp_path):
        root = make_extension(
            tmp_path / "ext" / "slow",
            name="slow",
            scripts={"slow.py": SLOW},
            tools=[
                {
                    "name": "wait",
                    "description": "hangs",
                    "capability": "process.exec",
                    "command": [sys.executable, "slow.py"],
                    "inputs": {},
                }
            ],
        )
        ws.config.set("tools.timeout_seconds", 1)
        ws.extensions.install(root, trust=True, enable=True)
        ws.permissions.grant("process.exec", subject="ext.slow.wait", duration="persistent", confirm=True)
        with pytest.raises(ToolTimeoutError, match="timed out"):
            ws.tools.execute("ext.slow.wait", {})

    def test_untrusting_mid_flight_stops_execution(self, ws, ext_dir):
        extension = _active(ws, ext_dir)
        ws.permissions.grant("process.exec", subject="ext.wordcount.count", duration="persistent", confirm=True)
        run = ws.tools.execute("ext.wordcount.count", {"text": "one two"})
        assert run.status == "succeeded"
        # untrust, then call the handler directly through the registry's declared spec
        ws.extensions.trust(extension.name, trusted=False)
        with pytest.raises(ToolNotFoundError):
            ws.tools.execute("ext.wordcount.count", {"text": "one two"})

    def test_extension_runs_in_its_own_directory_without_secrets(self, ws, tmp_path, monkeypatch):
        monkeypatch.setenv("ARCHX_EXT_SECRET", "do-not-leak")
        root = make_extension(
            tmp_path / "ext" / "envcheck",
            name="envcheck",
            scripts={
                "env.py": (
                    "import json, os, sys\n"
                    "json.load(sys.stdin)\n"
                    "print(json.dumps({'secret': os.environ.get('ARCHX_EXT_SECRET'),"
                    " 'cwd': os.getcwd(), 'keys': sorted(os.environ)}))\n"
                )
            },
            tools=[
                {
                    "name": "peek",
                    "description": "reports its environment",
                    "capability": "process.exec",
                    "command": [sys.executable, "env.py"],
                    "inputs": {},
                }
            ],
        )
        ws.extensions.install(root, trust=True, enable=True)
        ws.permissions.grant("process.exec", subject="ext.envcheck.peek", duration="persistent", confirm=True)
        run = ws.tools.execute("ext.envcheck.peek", {})
        assert run.result["secret"] is None
        assert set(run.result["keys"]) == {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}
        assert Path(run.result["cwd"]).name == "envcheck"

    def test_extension_traces_are_recorded(self, ws, ext_dir):
        _active(ws, ext_dir)
        ws.permissions.grant("process.exec", subject="ext.wordcount.count", duration="persistent", confirm=True)
        ws.tools.execute("ext.wordcount.count", {"text": "a b"})
        ws.events.flush()
        names = {e.name for e in ws.events.query(kind="extension", limit=50)}
        assert {"installed", "tools.synced", "tool.ran"} <= names

    def test_a_second_tool_with_another_capability_is_separately_gated(self, ws, tmp_path, ext_dir):
        # add a second tool that claims shell.run, then prove one grant does not cover it
        raw = json.loads((ext_dir / "extension.json").read_text())
        raw["tools"].append(
            {
                "name": "shell",
                "description": "runs a command",
                "capability": "shell.run",
                "command": [sys.executable, "count.py"],
                "inputs": {"text": {"type": "string"}},
                "required": ["text"],
            }
        )
        (ext_dir / "extension.json").write_text(json.dumps(raw))
        _active(ws, ext_dir)
        ws.permissions.grant("process.exec", subject="ext.wordcount.count", duration="persistent", confirm=True)
        assert ws.tools.execute("ext.wordcount.count", {"text": "x"}).status == "succeeded"
        with pytest.raises(ApprovalRequiredError) as exc:
            ws.tools.execute("ext.wordcount.shell", {"text": "x"})
        assert exc.value.capability == "shell.run"

    def test_extension_tool_name_is_sanitised(self, ws, tmp_path):
        root = make_extension(
            tmp_path / "ext" / "odd",
            name="odd-balls",
            tools=[
                {
                    "name": "say.hello",
                    "description": "speaks",
                    "capability": "process.exec",
                    "command": [sys.executable, "count.py"],
                    "inputs": {"text": {"type": "string"}},
                }
            ],
        )
        extension = ws.extensions.install(root, trust=True, enable=True)
        assert ws.extensions.spec_name(extension.name, "say.hello") == "ext.odd-balls.say.hello"

    def test_updated_manifest_adds_a_tool(self, ws, ext_dir):
        _active(ws, ext_dir)
        raw = json.loads((ext_dir / "extension.json").read_text())
        raw["tools"].append(
            {
                "name": "second",
                "description": "another counter",
                "capability": "process.exec",
                "command": [sys.executable, "count.py"],
                "inputs": {"text": {"type": "string"}},
            }
        )
        raw["version"] = "2.0.0"
        (ext_dir / "extension.json").write_text(json.dumps(raw))
        ws.extensions.install(ext_dir)
        ws.extensions.trust("wordcount")
        ws.extensions.set_enabled("wordcount", enabled=True)
        names = {spec.name for spec in ws.tools.specs()}
        assert {"ext.wordcount.count", "ext.wordcount.second"} <= names
