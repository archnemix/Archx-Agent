"""Argument grammar for models commands."""

from __future__ import annotations

import argparse
from archx_agent.managers.models import VERIFICATION_STATES

def register_parser(sub: argparse._SubParsersAction) -> None:
    models = sub.add_parser("models", help="model catalogue and discovery")
    m_sub = models.add_subparsers(dest="models_command", required=True)
    m_sub.add_parser("list", help="list known models")
    m_discover = m_sub.add_parser("discover", help="scan a directory for GGUF files")
    m_discover.add_argument(
        "--dir", help="directory to scan (default: the models directory)"
    )
    m_discover.add_argument("--no-recursive", action="store_true")
    m_add_http = m_sub.add_parser(
        "add-http", help="register an OpenAI-compatible endpoint"
    )
    m_add_http.add_argument("--name", required=True)
    m_add_http.add_argument("--base-url", required=True)
    m_add_http.add_argument("--model", required=True, help="remote model identifier")
    m_add_http.add_argument(
        "--provider", default=None, help="provider label (default derived from the URL)"
    )
    m_add_http.add_argument("--context-length", type=int, default=8192)
    m_add_http.add_argument(
        "--credential-ref", help="secret://env/NAME reference (never the key itself)"
    )
    m_add_http.add_argument("--capability", action="append", default=[])
    m_add_http.add_argument(
        "--verification", default="inferred", choices=list(VERIFICATION_STATES)
    )
    m_add_gemini = m_sub.add_parser(
        "add-gemini",
        help="register a Google Gemini model and run real inference through it",
    )
    m_add_gemini.add_argument("--name", required=True)
    m_add_gemini.add_argument(
        "--model", required=True, help="model id, e.g. gemini-2.0-flash"
    )
    m_add_gemini.add_argument(
        "--credential-ref",
        default="secret://env/GEMINI_API_KEY",
        help="where the key lives: secret://env/NAME or secret://file/PATH (never the key itself)",
    )
    m_add_gemini.add_argument(
        "--base-url",
        default=None,
        help="override the endpoint (default: Google's generativelanguage host)",
    )
    m_add_gemini.add_argument("--api-version", default="v1beta")
    m_add_gemini.add_argument("--context-length", type=int, default=1048576)
    m_add_gemini.add_argument("--capability", action="append", default=[])
    m_add_gemini.add_argument(
        "--verification", default="inferred", choices=list(VERIFICATION_STATES)
    )
    m_add_sdk = m_sub.add_parser(
        "add-sdk",
        help="register a model driven by a vendor's official Python SDK (openai, anthropic, google, mistral)",
    )
    m_add_sdk.add_argument("--name", required=True)
    m_add_sdk.add_argument(
        "--sdk", required=True, help="which vendor client to use (see `models sdks`)"
    )
    m_add_sdk.add_argument(
        "--model", required=True, help="the model id the vendor serves"
    )
    m_add_sdk.add_argument(
        "--base-url",
        default=None,
        help="override the endpoint (a stub, a tunnel, a proxy)",
    )
    m_add_sdk.add_argument(
        "--credential-ref",
        default=None,
        help="defaults to secret://env/<the SDK's own variable>",
    )
    m_add_sdk.add_argument("--context-length", type=int, default=131072)
    m_add_sdk.add_argument("--capability", action="append", default=[])
    m_add_sdk.add_argument(
        "--verification", default="inferred", choices=list(VERIFICATION_STATES)
    )
    m_sub.add_parser("sdks", help="which vendor SDKs are installed in this interpreter")
    m_add_scripted = m_sub.add_parser(
        "add-scripted", help="register the simulated test double (no inference)"
    )
    m_add_scripted.add_argument("--name", default="simulated-demo")
    m_show = m_sub.add_parser("show", help="show one model in detail")
    m_show.add_argument("model")
    m_enable = m_sub.add_parser("enable", help="enable a model")
    m_enable.add_argument("model")
    m_disable = m_sub.add_parser("disable", help="disable a model")
    m_disable.add_argument("model")
    m_verify = m_sub.add_parser("verify", help="record which capabilities are verified")
    m_verify.add_argument("model")
    m_verify.add_argument("--capability", action="append", required=True)
    m_verify.add_argument("--basis", default="verified by capability test")
    m_verify.add_argument(
        "--state", default="verified", choices=list(VERIFICATION_STATES)
    )
    m_pref = m_sub.add_parser("prefer", help="mark a model as preferred for a task")
    m_pref.add_argument("model")
    m_pref.add_argument("--task", action="append", required=True)
    m_remove = m_sub.add_parser("remove", help="remove a model from the catalogue")
    m_remove.add_argument("model")
    m_remove.add_argument("--delete-file", action="store_true")
    m_route = m_sub.add_parser(
        "route", help="show which model the router would pick, and why"
    )
    m_route.add_argument("--task", default="chat")
    m_route.add_argument(
        "--require", action="append", help="required capability (repeatable)"
    )
    m_route.add_argument("--model", help="evaluate one specific model")
    m_route.add_argument(
        "--min-context", type=int, help="tokens of context the task needs"
    )
    m_route.add_argument(
        "--allow-unverified",
        action="store_true",
        help="permit a capability that has only been claimed",
    )
    m_route.add_argument(
        "--allow-cloud", action="store_true", help="let the router choose remote models"
    )
    m_probe = m_sub.add_parser(
        "probe", help="exercise a capability and record the result"
    )
    m_probe.add_argument("model")
    m_probe.add_argument(
        "--capability", default="chat", choices=["chat", "tools", "json"]
    )
    m_caps = m_sub.add_parser(
        "capabilities", help="capability states with their evidence"
    )
    m_caps.add_argument("model", nargs="?")
    m_sub.add_parser("storage", help="show model storage usage")
    m_compare = m_sub.add_parser("compare", help="compare models side by side")
    m_compare.add_argument("models", nargs="+")
