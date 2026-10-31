"""Regressions for the repository cleanup, not a substitute for feature tests."""

from __future__ import annotations

import re
from typing import get_type_hints

from archx_agent.adapters.sdk_transport import SdkTransport
from archx_agent.helpers.config import SPEC
from archx_agent.interfaces.gui.server import ASSETS, GuiApi


def test_effective_gui_defaults_remain_loopback_and_allow_ephemeral_port():
    assert SPEC["gui.host"][1] == "127.0.0.1"
    assert SPEC["gui.port"][1] == 8765
    assert SPEC["gui.port"][2](0) == 0


def test_all_stream_annotations_can_be_resolved():
    for name in (
        "stream",
        "_stream_openai_shaped",
        "_stream_anthropic",
        "_stream_google",
        "_stream_cohere",
        "_stream_ollama",
    ):
        assert get_type_hints(getattr(SdkTransport, name))["return"]


def test_every_declared_browser_script_is_packaged_and_served():
    html = (ASSETS / "index.html").read_text()
    scripts = re.findall(r'<script src="/([^"/]+\.js)"></script>', html)
    assert scripts[-1] == "app.js", "initializers must register before the shell starts"
    assert len(scripts) == len(set(scripts))
    assert set(scripts) == {path.name for path in ASSETS.glob("*.js")}
    # Asset serving is independent of a workspace and must preserve exact bytes.
    api = GuiApi(None, token="asset-check")
    for name in scripts:
        response = api.asset(name)
        assert response.status == 200
        assert response.body == (ASSETS / name).read_bytes()


def test_loopback_classification_does_not_trust_a_dns_prefix():
    from archx_agent.helpers.urls import is_loopback_url

    for url in (
        "http://127.0.0.1",
        "http://127.9.8.7:8080",
        "https://[::1]",
        "http://LOCALHOST",
    ):
        assert is_loopback_url(url), url
    for url in (
        "http://127.attacker.example",
        "https://127.0.0.1.attacker.example",
        "http://localhost.attacker.example",
        "http://0.0.0.0",
        "http://[::]",
        "file://localhost/a",
        "http://[invalid",
        None,
    ):
        assert not is_loopback_url(url), url
