"""Archx Agent command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any, Iterable, Sequence

from archx_agent import BRAND, __version__
from archx_agent.application.chat import ChatService
from archx_agent.application.workspace import Workspace, open_workspace
from archx_agent.helpers.backup_recovery import (
    apply_retention,
    create_backup,
    list_backups,
    preview_restore,
    restore_backup,
    verify_backup,
)
from archx_agent.helpers.config import list_settings, load_config, resolve_secret
from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ArchxError,
    ModelNotFoundError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    PathEscapesRootError,
    ToolError,
    ToolValidationError,
    ValidationError,
)
from archx_agent.helpers.jsonio import json_text
from archx_agent.application.search import SEARCH_KINDS
from archx_agent.managers.memory import CATEGORIES, KINDS as MEMORY_KINDS, MemoryManager
from archx_agent.managers.models import VERIFICATION_STATES
from archx_agent.managers.permissions import CAPABILITIES

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_DENIED = 4
EXIT_UNAVAILABLE = 5
EXIT_DEGRADED = 3  # the command ran but the thing it checked is not healthy


# --------------------------------------------------------------------------
# output helpers
# --------------------------------------------------------------------------
def emit(text: str = "") -> None:
    print(text)


def emit_json(data: Any) -> None:
    print(json_text(data))


def table(rows: Sequence[Sequence[Any]], headers: Sequence[str]) -> str:
    cells = [[str(c) for c in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in cells:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], min(len(cell), 60))
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    out.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in cells:
        out.append("  ".join(cell[:60].ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(out)


def fail(message: str, code: int = EXIT_ERROR) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def _add_leaf_flags(parser: argparse.ArgumentParser) -> None:
    """Allow the global flags after the subcommand as well as before it.

    ``default=SUPPRESS`` means an omitted flag does not overwrite the value the
    top-level parser already parsed.
    """
    for action in parser._actions:  # noqa: SLF001 - argparse has no public API for this
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for sub in action.choices.values():
                sub.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                                 help=argparse.SUPPRESS)
                sub.add_argument("--home", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
                sub.add_argument("--config", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
                sub.add_argument("--allow-simulated", action="store_true", default=argparse.SUPPRESS,
                                 help=argparse.SUPPRESS)
                _add_leaf_flags(sub)


def _is_loopback(url: str | None) -> bool:
    from archx_agent.managers.providers import is_loopback_url

    return is_loopback_url(url)


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    """Let ``--json``/``--home`` also be written after the subcommand.

    Users type ``archx-agent memory list --json`` far more often than the global
    form, and argparse would otherwise reject it. ``SUPPRESS`` defaults mean an
    unset subparser flag does not clobber the value parsed at the top level.
    """
    existing = {opt for action in parser._actions for opt in action.option_strings}  # noqa: SLF001

    def add(flags: list[str], **kwargs) -> None:
        if not any(flag in existing for flag in flags):
            parser.add_argument(*flags, **kwargs)

    add(["--json"], action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    add(["--home"], default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    add(["--config"], default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    add(["--allow-simulated"], action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)


def _decorate_leaf_parsers(parser: argparse.ArgumentParser) -> None:
    for action in parser._actions:  # noqa: SLF001 - argparse has no public API for this
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for child in action.choices.values():
                if any(isinstance(a, argparse._SubParsersAction) for a in child._actions):  # noqa: SLF001
                    _decorate_leaf_parsers(child)
                else:
                    _add_global_flags(child)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archx-agent",
        description=f"{BRAND} - a modular, local-first AI operating environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            examples:
              archx-agent init
              archx-agent models add-http --name local-llama --base-url http://127.0.0.1:8080 --model smollm2
              archx-agent chat --message "hello"
              archx-agent memory add --kind permanent --title "Prefers metric" --content "Use metric units" --category preference
              archx-agent memory search python
              archx-agent trace list --limit 20
            """
        ),
    )
    parser.add_argument("--version", action="version", version=f"{BRAND} {__version__}")
    parser.add_argument("--home", help="Archx home directory (default ~/.archx or $ARCHX_PATHS_HOME)")
    parser.add_argument("--config", help="configuration file to load")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--allow-simulated",
        action="store_true",
        help="allow the simulated test-double runtime (never a substitute for a real model)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the home directory, config and database")
    sub.add_parser("info", help="show workspace information")
    sub.add_parser("doctor", help="check the environment and report problems")

    # -- config ---------------------------------------------------------
    cfg = sub.add_parser("config", help="inspect and edit settings")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    cfg_sub.add_parser("list", help="list every setting with defaults")
    cfg_get = cfg_sub.add_parser("get", help="read a setting")
    cfg_get.add_argument("key")
    cfg_set = cfg_sub.add_parser("set", help="change a setting")
    cfg_set.add_argument("key")
    cfg_set.add_argument("value")
    cfg_sub.add_parser("show", help="show the resolved configuration and provenance")

    # -- models ---------------------------------------------------------
    models = sub.add_parser("models", help="model catalogue and discovery")
    m_sub = models.add_subparsers(dest="models_command", required=True)
    m_sub.add_parser("list", help="list known models")
    m_discover = m_sub.add_parser("discover", help="scan a directory for GGUF files")
    m_discover.add_argument("--dir", help="directory to scan (default: the models directory)")
    m_discover.add_argument("--no-recursive", action="store_true")
    m_add_http = m_sub.add_parser("add-http", help="register an OpenAI-compatible endpoint")
    m_add_http.add_argument("--name", required=True)
    m_add_http.add_argument("--base-url", required=True)
    m_add_http.add_argument("--model", required=True, help="remote model identifier")
    m_add_http.add_argument("--provider", default=None, help="provider label (default derived from the URL)")
    m_add_http.add_argument("--context-length", type=int, default=8192)
    m_add_http.add_argument("--credential-ref", help="secret://env/NAME reference (never the key itself)")
    m_add_http.add_argument("--capability", action="append", default=[])
    m_add_http.add_argument("--verification", default="inferred", choices=list(VERIFICATION_STATES))
    m_add_gemini = m_sub.add_parser(
        "add-gemini", help="register a Google Gemini model and run real inference through it"
    )
    m_add_gemini.add_argument("--name", required=True)
    m_add_gemini.add_argument("--model", required=True, help="model id, e.g. gemini-2.0-flash")
    m_add_gemini.add_argument(
        "--credential-ref", default="secret://env/GEMINI_API_KEY",
        help="where the key lives: secret://env/NAME or secret://file/PATH (never the key itself)",
    )
    m_add_gemini.add_argument("--base-url", default=None,
                              help="override the endpoint (default: Google's generativelanguage host)")
    m_add_gemini.add_argument("--api-version", default="v1beta")
    m_add_gemini.add_argument("--context-length", type=int, default=1048576)
    m_add_gemini.add_argument("--capability", action="append", default=[])
    m_add_gemini.add_argument("--verification", default="inferred", choices=list(VERIFICATION_STATES))
    m_add_sdk = m_sub.add_parser(
        "add-sdk",
        help="register a model driven by a vendor's official Python SDK (openai, anthropic, google, mistral)",
    )
    m_add_sdk.add_argument("--name", required=True)
    m_add_sdk.add_argument("--sdk", required=True, help="which vendor client to use (see `models sdks`)")
    m_add_sdk.add_argument("--model", required=True, help="the model id the vendor serves")
    m_add_sdk.add_argument("--base-url", default=None,
                           help="override the endpoint (a stub, a tunnel, a proxy)")
    m_add_sdk.add_argument("--credential-ref", default=None,
                           help="defaults to secret://env/<the SDK's own variable>")
    m_add_sdk.add_argument("--context-length", type=int, default=131072)
    m_add_sdk.add_argument("--capability", action="append", default=[])
    m_add_sdk.add_argument("--verification", default="inferred", choices=list(VERIFICATION_STATES))
    m_sdks = m_sub.add_parser("sdks", help="which vendor SDKs are installed in this interpreter")
    m_add_scripted = m_sub.add_parser("add-scripted", help="register the simulated test double (no inference)")
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
    m_verify.add_argument("--state", default="verified", choices=list(VERIFICATION_STATES))
    m_pref = m_sub.add_parser("prefer", help="mark a model as preferred for a task")
    m_pref.add_argument("model")
    m_pref.add_argument("--task", action="append", required=True)
    m_remove = m_sub.add_parser("remove", help="remove a model from the catalogue")
    m_remove.add_argument("model")
    m_remove.add_argument("--delete-file", action="store_true")
    m_route = m_sub.add_parser("route", help="show which model the router would pick, and why")
    m_route.add_argument("--task", default="chat")
    m_route.add_argument("--require", action="append", help="required capability (repeatable)")
    m_route.add_argument("--model", help="evaluate one specific model")
    m_route.add_argument("--min-context", type=int, help="tokens of context the task needs")
    m_route.add_argument("--allow-unverified", action="store_true",
                         help="permit a capability that has only been claimed")
    m_route.add_argument("--allow-cloud", action="store_true", help="let the router choose remote models")
    m_probe = m_sub.add_parser("probe", help="exercise a capability and record the result")
    m_probe.add_argument("model")
    m_probe.add_argument("--capability", default="chat", choices=["chat", "tools", "json"])
    m_caps = m_sub.add_parser("capabilities", help="capability states with their evidence")
    m_caps.add_argument("model", nargs="?")
    m_sub.add_parser("storage", help="show model storage usage")
    m_compare = m_sub.add_parser("compare", help="compare models side by side")
    m_compare.add_argument("models", nargs="+")

    # -- chat -----------------------------------------------------------
    chat = sub.add_parser("chat", help="chat with the configured model")
    chat.add_argument("--message", "-m", help="send one message and exit")
    chat.add_argument("--conversation", "-c", help="conversation id to continue")
    chat.add_argument("--model", help="model id or name")
    chat.add_argument("--strategy", choices=["oldest_first", "summarize", "ai_select", "manual", "ai_proposed"])
    chat.add_argument("--manual-ids", help="comma separated message ids for the manual strategy")
    chat.add_argument("--proposal", help="approved proposal id for the ai_proposed strategy")
    chat.add_argument("--system", help="system prompt override")
    chat.add_argument("--stream", action="store_true", help="stream tokens as they arrive")
    chat.add_argument("--temperature", type=float)
    chat.add_argument("--max-tokens", type=int)
    chat.add_argument("--show-context", action="store_true", help="print the context manifest after replying")

    # -- conversations --------------------------------------------------
    conv = sub.add_parser("conv", help="manage conversations")
    c_sub = conv.add_subparsers(dest="conv_command", required=True)
    c_sub.add_parser("list", help="list conversations")
    c_new = c_sub.add_parser("new", help="create a conversation")
    c_new.add_argument("title", nargs="?", default="New conversation")
    c_show = c_sub.add_parser("show", help="show a conversation")
    c_show.add_argument("conversation")
    c_search = c_sub.add_parser("search", help="search titles and messages")
    c_search.add_argument("query")
    c_rename = c_sub.add_parser("rename", help="rename a conversation")
    c_rename.add_argument("conversation")
    c_rename.add_argument("title")
    c_delete = c_sub.add_parser("delete", help="delete a conversation")
    c_delete.add_argument("conversation")
    c_delete.add_argument("--hard", action="store_true")
    c_delete.add_argument("--yes", action="store_true")
    c_restore = c_sub.add_parser("restore", help="restore a soft-deleted conversation")
    c_restore.add_argument("conversation")
    c_clear = c_sub.add_parser("clear", help="hide messages from context without deleting them")
    c_clear.add_argument("conversation")
    c_export = c_sub.add_parser("export", help="export a conversation")
    c_export.add_argument("conversation")
    c_export.add_argument("--format", choices=["json", "markdown"], default="json")
    c_export.add_argument("--out")

    # -- memory ---------------------------------------------------------
    memory = sub.add_parser("memory", help="the six memory systems")
    mem_sub = memory.add_subparsers(dest="memory_command", required=True)
    mem_add = mem_sub.add_parser("add", help="store a memory")
    mem_add.add_argument("--kind", required=True, choices=list(MEMORY_KINDS))
    mem_add.add_argument("--title", required=True)
    mem_add.add_argument("--content", required=True)
    mem_add.add_argument("--category", default="note", choices=list(CATEGORIES))
    mem_add.add_argument("--project", help="project id (required for project memory)")
    mem_add.add_argument("--conversation", help="conversation id (required for active memory)")
    mem_add.add_argument("--task", help="task id (active memory)")
    mem_add.add_argument("--tags", help="comma separated tags")
    mem_add.add_argument("--pinned", action="store_true")
    mem_add.add_argument("--slot", help="logical slot; a new value supersedes the old one")
    mem_add.add_argument("--verification", choices=list(VERIFICATION_STATES))
    mem_add.add_argument("--problem", help="solution memory: the problem")
    mem_add.add_argument("--solution", help="solution memory: the solution")
    mem_add.add_argument("--topic", help="learning memory: topic")
    mem_add.add_argument("--evidence", help="solution memory: how it was verified")
    mem_add.add_argument("--limitations")
    mem_add.add_argument("--environment")
    mem_add.add_argument("--allow-duplicate", action="store_true")
    mem_add.add_argument("--source", default="user", help="who/what produced this memory (user, tool, import, model)")
    mem_add.add_argument("--provenance-origin", help="where the fact came from (file, url, conversation, review)")
    mem_add.add_argument("--outcome", choices=["passed", "failed", "skipped", "in_progress"],
                         help="learning memory: the recorded outcome")
    mem_add.add_argument("--confidence", type=float, default=0.8)
    mem_list = mem_sub.add_parser("list", help="list memories")
    mem_list.add_argument("--kind", action="append", choices=list(MEMORY_KINDS))
    mem_list.add_argument("--project")
    mem_list.add_argument("--conversation")
    mem_list.add_argument("--status", default="active")
    mem_list.add_argument("--limit", type=int, default=50)
    mem_show = mem_sub.add_parser("show", help="show one memory with provenance and history")
    mem_show.add_argument("memory")
    mem_history = mem_sub.add_parser("history", help="version history of one memory")
    mem_history.add_argument("memory")
    mem_search = mem_sub.add_parser("search", help="search memories")
    mem_search.add_argument("query")
    mem_search.add_argument("--kind", action="append", choices=list(MEMORY_KINDS))
    mem_search.add_argument("--limit", type=int, default=10)
    mem_edit = mem_sub.add_parser("edit", help="edit a memory (the previous version is kept)")
    mem_edit.add_argument("memory")
    mem_edit.add_argument("--title")
    mem_edit.add_argument("--content")
    mem_edit.add_argument("--verification", choices=list(VERIFICATION_STATES))
    mem_edit.add_argument("--pinned", action="store_true")
    mem_edit.add_argument("--status")
    mem_delete = mem_sub.add_parser("delete", help="delete a memory")
    mem_delete.add_argument("memory")
    mem_delete.add_argument("--hard", action="store_true")
    mem_delete.add_argument("--yes", action="store_true")
    mem_retrieve = mem_sub.add_parser("retrieve", help="show what memory would be injected")
    mem_retrieve.add_argument("--conversation")
    mem_retrieve.add_argument("--project")
    mem_retrieve.add_argument("--query")
    mem_retrieve.add_argument("--budget", type=int, default=400)
    mem_retrieve.add_argument("--include-archival", action="store_true")
    mem_profile = mem_sub.add_parser("profile", help="learning profile")
    mem_profile.add_argument("--learner", default="default")
    mem_sub.add_parser("policy", help="documented policy for each memory kind")
    mem_sub.add_parser("stats", help="memory statistics")
    mem_retention = mem_sub.add_parser("retention", help="apply the retention policy")
    mem_retention.add_argument("--archival-days", type=int, default=365)

    # -- projects -------------------------------------------------------
    proj = sub.add_parser("projects", help="project identity (project memory is scoped to a project)")
    proj_sub = proj.add_subparsers(dest="project_command", required=True)
    proj_create = proj_sub.add_parser("create", help="create a project")
    proj_create.add_argument("name")
    proj_create.add_argument("--path", help="workspace directory")
    proj_create.add_argument("--description", default="")
    proj_sub.add_parser("list", help="list projects")
    proj_show = proj_sub.add_parser("show", help="show one project")
    proj_show.add_argument("project")
    proj_rename = proj_sub.add_parser("rename", help="rename a project")
    proj_rename.add_argument("project")
    proj_rename.add_argument("name")
    proj_archive = proj_sub.add_parser("archive", help="archive a project")
    proj_archive.add_argument("project")
    proj_link = proj_sub.add_parser("link", help="attach a conversation to a project")
    proj_link.add_argument("project")
    proj_link.add_argument("conversation")

    # -- providers ------------------------------------------------------
    prov = sub.add_parser("providers", help="local/cloud providers, privacy terms, consent, usage")
    prov_sub = prov.add_subparsers(dest="provider_command", required=True)
    prov_sub.add_parser("catalogue", help="known provider templates (claims, not facts)")
    p_list = prov_sub.add_parser("list", help="registered providers")
    p_list.add_argument("--kind", choices=["local", "cloud", "custom"])
    p_add = prov_sub.add_parser("add", help="register a provider")
    p_add.add_argument("name")
    p_add.add_argument("--template", help="known template slug (openai, anthropic, google, openai-compatible-local)")
    p_add.add_argument("--kind", choices=["local", "cloud", "custom"])
    p_add.add_argument("--api-style", choices=["openai", "anthropic", "gemini", "custom"])
    p_add.add_argument("--base-url")
    p_add.add_argument("--model-family")
    p_add.add_argument("--auth-ref", help="secret://env/NAME (never the key itself)")
    p_add.add_argument("--local", action="store_true", help="endpoint runs on this machine (loopback only)")
    p_add.add_argument("--notes", default="")
    p_add.add_argument("--price-in", type=float, help="cost per 1k input tokens, if you want estimates")
    p_add.add_argument("--price-out", type=float)
    p_add.add_argument("--currency", default="USD")
    p_show = prov_sub.add_parser("show", help="one provider with effective privacy view")
    p_show.add_argument("provider")
    p_confirm = prov_sub.add_parser("confirm", help="record what YOU confirmed about the provider's data handling")
    p_confirm.add_argument("provider")
    p_confirm.add_argument("--data-leaves-device", required=True, choices=["yes", "no"])
    p_confirm.add_argument("--training-use", default="unknown")
    p_confirm.add_argument("--retention", default="unknown")
    p_confirm.add_argument("--region", default="unknown")
    p_consent = prov_sub.add_parser("consent", help="record explicit consent to send data remotely")
    p_consent.add_argument("provider")
    p_consent.add_argument("--note", default="")
    p_revoke = prov_sub.add_parser("revoke", help="withdraw consent")
    p_revoke.add_argument("provider")
    p_enable = prov_sub.add_parser("enable", help="enable a provider")
    p_enable.add_argument("provider")
    p_disable = prov_sub.add_parser("disable", help="disable a provider")
    p_disable.add_argument("provider")
    p_check = prov_sub.add_parser("check", help="probe reachability/auth (never sends prompt content)")
    p_check.add_argument("provider")
    p_check.add_argument("--timeout", type=float, default=4.0)
    p_quota = prov_sub.add_parser("quota", help="declare (and enforce) a daily quota")
    p_quota.add_argument("provider")
    p_quota.add_argument("--requests-per-day", type=int)
    p_quota.add_argument("--tokens-per-day", type=int)
    p_usage = prov_sub.add_parser("usage", help="usage and estimated cost")
    p_usage.add_argument("provider", nargs="?")
    p_usage.add_argument("--days", type=int, default=30)
    p_usage.add_argument("--by-day", action="store_true")
    prov_sub.add_parser("privacy", help="privacy view of every registered provider")
    p_remove = prov_sub.add_parser("remove", help="remove a provider record")
    p_remove.add_argument("provider")
    prov_sub.add_parser("stats", help="provider counts")

    # -- context --------------------------------------------------------
    ctx = sub.add_parser("context", help="context strategies and manifests")
    ctx_sub = ctx.add_subparsers(dest="context_command", required=True)
    ctx_build = ctx_sub.add_parser("build", help="build and show a context manifest")
    ctx_build.add_argument("conversation")
    ctx_build.add_argument("--strategy", required=True, choices=["oldest_first", "summarize", "ai_select", "manual", "ai_proposed"])
    ctx_build.add_argument("--message", default="What should I do next?")
    ctx_build.add_argument("--budget", type=int)
    ctx_build.add_argument("--manual-ids")
    ctx_build.add_argument("--proposal")
    ctx_propose = ctx_sub.add_parser("propose", help="make an AI-proposed change (nothing applied)")
    ctx_propose.add_argument("conversation")
    ctx_propose.add_argument("--budget", type=int)
    ctx_reject = ctx_sub.add_parser("reject", help="reject a proposal (nothing changes)")
    ctx_reject.add_argument("proposal")
    ctx_reject.add_argument("--reason", default="rejected by the user")
    ctx_proposals = ctx_sub.add_parser("proposals", help="list proposals for a conversation")
    ctx_proposals.add_argument("conversation")
    ctx_manifests = ctx_sub.add_parser("manifests", help="list stored manifests")
    ctx_manifests.add_argument("conversation")
    ctx_summaries = ctx_sub.add_parser("summaries", help="list summaries for a conversation")
    ctx_summaries.add_argument("conversation")
    ctx_show = ctx_sub.add_parser("show", help="show one manifest")
    ctx_show.add_argument("manifest")

    # -- embeddings -----------------------------------------------------
    emb = sub.add_parser("embeddings", help="embedding index and semantic search")
    e_sub = emb.add_subparsers(dest="embedding_command", required=True)
    e_sub.add_parser("status", help="provider, dimension and coverage")
    e_backfill = e_sub.add_parser("backfill", help="embed memories and messages missing a vector")
    e_backfill.add_argument("--limit", type=int, default=500)
    e_conv = e_sub.add_parser("embed-conversation", help="embed a conversation's messages")
    e_conv.add_argument("conversation")
    e_search = e_sub.add_parser("search", help="semantic search over memory")
    e_search.add_argument("query")
    e_search.add_argument("-k", type=int, default=5)
    e_search.add_argument("--threshold", type=float)
    e_purge = e_sub.add_parser("purge", help="delete vectors (all, or one model's)")
    e_purge.add_argument("--model")
    e_purge.add_argument("--yes", action="store_true")

    ev = sub.add_parser("eval", help="evaluations")
    ev_sub = ev.add_subparsers(dest="eval_command", required=True)
    ev_ret = ev_sub.add_parser("retrieval", help="score retrieval modes against a labelled test set")
    ev_ret.add_argument("--dataset", default="data/retrieval_set.json")
    ev_ret.add_argument("--k", type=int, default=5)
    ev_ret.add_argument("--out", help="write a markdown report here")
    ev_ret.add_argument(
        "--no-scratch",
        action="store_true",
        help="use this workspace instead of a temporary scratch workspace",
    )

    # -- tools & permissions --------------------------------------------
    tools = sub.add_parser("tools", help="tool registry, permissions-aware execution and run history")
    t2_sub = tools.add_subparsers(dest="tools_command", required=True)
    t2_sub.add_parser("list", help="every registered tool with its capability and risk")
    t2_show = t2_sub.add_parser("show", help="one tool: inputs, roots and active grants")
    t2_show.add_argument("tool")
    t2_run = t2_sub.add_parser("run", help="run a tool (needs a grant or an approved request)")
    t2_run.add_argument("tool")
    t2_run.add_argument("--arg", action="append", default=[], metavar="key=value",
                        help="tool argument (repeatable)")
    t2_run.add_argument("--dry-run", action="store_true", help="preview without changing anything")
    t2_run.add_argument("--conversation", help="conversation scope for the permission check")
    t2_run.add_argument("--task", help="task scope for the permission check")
    t2_run.add_argument("--project", help="project scope for the permission check")
    t2_run.add_argument("--purpose", help="why this is being run (kept in the trace)")
    t2_runs = t2_sub.add_parser("runs", help="recent tool runs, including refusals")
    t2_runs.add_argument("--tool")
    t2_runs.add_argument("--limit", type=int, default=20)

    perms = sub.add_parser("permissions", help="capabilities, grants and denials")
    pm_sub = perms.add_subparsers(dest="permissions_command", required=True)
    pm_sub.add_parser("capabilities", help="protected operations and their risk")
    pm_list = pm_sub.add_parser("list", help="recorded grants")
    pm_list.add_argument("--capability")
    pm_list.add_argument("--subject")
    pm_list.add_argument("--all", action="store_true", help="include revoked grants")
    pm_grant = pm_sub.add_parser("grant", help="record an explicit grant")
    pm_grant.add_argument("capability")
    pm_grant.add_argument("--subject", default="*", help="tool name, or '*' for any subject")
    pm_grant.add_argument("--duration", choices=["once", "task", "conversation", "project", "persistent"],
                          help="how broad the grant is (default: permissions.default_duration)")
    pm_grant.add_argument("--for", dest="for_hours", type=int, help="expire after N hours")
    pm_grant.add_argument("--reason", default="")
    pm_grant.add_argument("--conversation")
    pm_grant.add_argument("--task")
    pm_grant.add_argument("--project")
    pm_grant.add_argument("--confirm", action="store_true",
                          help="confirm a persistent grant (without it, it is downgraded)")
    pm_revoke = pm_sub.add_parser("revoke", help="revoke a grant")
    pm_revoke.add_argument("grant")
    pm_revoke.add_argument("--reason", default="")
    pm_check = pm_sub.add_parser("check", help="would this operation be allowed? (creates nothing)")
    pm_check.add_argument("capability")
    pm_check.add_argument("--subject", required=True)
    pm_check.add_argument("--conversation")
    pm_check.add_argument("--task")
    pm_check.add_argument("--project")
    pm_sub.add_parser("prune", help="revoke expired grants")

    approvals = sub.add_parser("approvals", help="the approval centre")
    ap_sub = approvals.add_subparsers(dest="approvals_command", required=True)
    ap_list = ap_sub.add_parser("list", help="requests waiting for a decision")
    ap_list.add_argument("--status", choices=["pending", "approved", "denied", "expired"])
    ap_list.add_argument("--limit", type=int, default=50)
    ap_show = ap_sub.add_parser("show", help="one approval request")
    ap_show.add_argument("approval")
    ap_approve = ap_sub.add_parser("approve", help="approve exactly what was requested")
    ap_approve.add_argument("approval")
    ap_approve.add_argument("--reason", default="")
    ap_approve.add_argument("--for", dest="for_hours", type=int, help="time-box the resulting grant")
    ap_deny = ap_sub.add_parser("deny", help="deny a request (no grant is created)")
    ap_deny.add_argument("approval")
    ap_deny.add_argument("--reason", default="denied by the user")

    # -- MCP -------------------------------------------------------------
    mcp = sub.add_parser("mcp", help="MCP client servers and the optional MCP server")
    mc_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mc_sub.add_parser("servers", help="configured servers, trust and tool counts")
    mc_sub.add_parser("list", help="alias for servers")
    mc_add = mc_sub.add_parser("add", help="register a server (nothing runs yet)")
    mc_add.add_argument("name")
    mc_add.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    # dest is not "command": that name belongs to the top-level subcommand and
    # argparse would overwrite it, making the handler lookup fail.
    mc_add.add_argument("--command", dest="server_command", help="stdio: the program to run")
    mc_add.add_argument("--arg", action="append", default=[], metavar="value",
                        help="stdio: one argument for the command (repeatable)")
    mc_add.add_argument("--url", help="http: the JSON-RPC endpoint")
    mc_add.add_argument("--env", action="append", default=[], metavar="KEY=value")
    mc_add.add_argument("--header", action="append", default=[], metavar="Name=value")
    mc_add.add_argument("--trust", action="store_true", help="trust it at registration time")
    mc_add.add_argument("--enable", action="store_true", help="enable it at registration time")
    mc_show = mc_sub.add_parser("show", help="one server with its discovered tools")
    mc_show.add_argument("server")
    for verb, text in (("enable", "let a trusted server register its tools"),
                       ("disable", "unregister a server's tools"),
                       ("trust", "accept what the server advertises"),
                       ("untrust", "stop accepting it (tools are unregistered)")):
        sub_verb = mc_sub.add_parser(verb, help=text)
        sub_verb.add_argument("server")
    mc_remove = mc_sub.add_parser("remove", help="remove a server and its tools")
    mc_remove.add_argument("server")
    mc_sync = mc_sub.add_parser("sync", help="connect, discover tools and register them if allowed")
    mc_sync.add_argument("server")
    mc_tools = mc_sub.add_parser("tools", help="tools discovered from a server")
    mc_tools.add_argument("server")
    mc_call = mc_sub.add_parser("call", help="call a discovered tool (needs an mcp.call grant)")
    mc_call.add_argument("server")
    mc_call.add_argument("tool")
    mc_call.add_argument("--arg", action="append", default=[], metavar="key=value")
    mc_call.add_argument("--conversation")
    mc_call.add_argument("--task")
    mc_call.add_argument("--project")
    mc_call.add_argument("--purpose")
    mc_serve = mc_sub.add_parser("serve", help="expose a whitelist of tools as an MCP server")
    mc_serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    mc_serve.add_argument("--host")
    mc_serve.add_argument("--port", type=int)

    # -- extensions ------------------------------------------------------
    ext = sub.add_parser("extensions", help="install, trust and call extension tools")
    ex_sub = ext.add_subparsers(dest="extensions_command", required=True)
    ex_sub.add_parser("list", help="installed extensions and their trust")
    ex_install = ex_sub.add_parser("install", help="install a directory containing extension.json")
    ex_install.add_argument("path")
    ex_install.add_argument("--trust", action="store_true")
    ex_install.add_argument("--enable", action="store_true")
    ex_show = ex_sub.add_parser("show", help="manifest and tool rows for one extension")
    ex_show.add_argument("extension")
    for verb, text in (("trust", "register the extension's tools"),
                       ("untrust", "unregister them"),
                       ("enable", "make a trusted extension's tools available"),
                       ("disable", "unregister them temporarily")):
        sub_verb = ex_sub.add_parser(verb, help=text)
        sub_verb.add_argument("extension")
    ex_remove = ex_sub.add_parser("remove", help="remove an extension and its tools")
    ex_remove.add_argument("extension")
    ex_tools = ex_sub.add_parser("tools", help="tools recorded for an extension")
    ex_tools.add_argument("extension")
    ex_call = ex_sub.add_parser("call", help="call an extension tool (needs a grant)")
    ex_call.add_argument("extension")
    ex_call.add_argument("tool")
    ex_call.add_argument("--arg", action="append", default=[], metavar="key=value")
    ex_call.add_argument("--conversation")
    ex_call.add_argument("--task")
    ex_call.add_argument("--project")
    ex_call.add_argument("--purpose")

    # -- agent workflows -------------------------------------------------
    agent = sub.add_parser("agent", help="agent workflows: user-directed and model-proposed plans")
    ag_sub = agent.add_subparsers(dest="agent_command", required=True)
    ag_plan = ag_sub.add_parser("plan", help="ask a model for a plan (stored unapproved)")
    ag_plan.add_argument("goal")
    ag_plan.add_argument("--model")
    ag_plan.add_argument("--name")
    ag_list = ag_sub.add_parser("list", help="workflow records")
    ag_list.add_argument("--status")
    ag_list.add_argument("--mode")
    ag_list.add_argument("--limit", type=int, default=20)
    ag_show = ag_sub.add_parser("show", help="definition, steps and subagent tasks")
    ag_show.add_argument("workflow")
    ag_run = ag_sub.add_parser("run", help="run a stored workflow")
    ag_run.add_argument("workflow")
    ag_run.add_argument("--approve", action="store_true",
                        help="approve a model-proposed plan and pass checkpoints")
    ag_file = ag_sub.add_parser("run-file", help="run a user-written workflow definition (JSON)")
    ag_file.add_argument("path")
    ag_file.add_argument("--approve", action="store_true")
    ag_template = ag_sub.add_parser("run-template", help="run a built-in workflow template")
    ag_template.add_argument("template")
    ag_template.add_argument("--input", action="append", default=[], metavar="key=value")
    ag_template.add_argument("--approve", action="store_true")
    ag_sub.add_parser("templates", help="built-in user-directed workflows")
    ag_approve = ag_sub.add_parser("approve", help="approve a proposed plan without running it")
    ag_approve.add_argument("workflow")
    ag_reject = ag_sub.add_parser("reject", help="reject a proposed plan")
    ag_reject.add_argument("workflow")
    ag_reject.add_argument("--reason")
    ag_cancel = ag_sub.add_parser("cancel", help="cancel a workflow")
    ag_cancel.add_argument("workflow")
    ag_cancel.add_argument("--reason")
    ag_rerun = ag_sub.add_parser("rerun", help="start a NEW run of the same definition")
    ag_rerun.add_argument("workflow")
    ag_rerun.add_argument("--approve", action="store_true")
    ag_steps = ag_sub.add_parser("steps", help="step records for a workflow")
    ag_steps.add_argument("workflow")
    ag_sub.add_parser("stats", help="workflow counts")

    # -- scheduled jobs --------------------------------------------------
    jobs = sub.add_parser("jobs", help="durable job queue: submit, run, pause, resume, recover")
    jb_sub = jobs.add_subparsers(dest="jobs_command", required=True)
    jb_submit = jb_sub.add_parser("submit", help="queue a job (queued is not done)")
    jb_kinds = jb_submit.add_subparsers(dest="job_kind", required=True)

    def _job_options(p) -> None:
        p.add_argument("--title")
        p.add_argument("--priority", type=int, default=5, help="0-9, higher runs first")
        p.add_argument("--timeout", type=int, help="hard deadline in seconds")
        p.add_argument("--max-attempts", type=int, help="attempts before a crash leaves it interrupted")
        p.add_argument("--dedupe-key", help="return the existing live job with this key instead of queueing twice")
        p.add_argument("--project")
        p.add_argument("--job-json", dest="payload", metavar="JSON",
                       help="extra payload as a JSON object")
        p.add_argument("--run", action="store_true",
                       help="drain the queue right after submitting")

    jb_cmd = jb_kinds.add_parser("command", help="run a local command as a job")
    jb_cmd.add_argument("job_command", metavar="command",
                        help="command line (split like a shell; run without one)")
    jb_cmd.add_argument("--cwd")
    _job_options(jb_cmd)

    jb_wf = jb_kinds.add_parser("workflow", help="run a stored workflow as a job")
    jb_wf.add_argument("workflow")
    jb_wf.add_argument("--approve", action="store_true", help="approve a proposed plan / checkpoints")
    _job_options(jb_wf)

    jb_res = jb_kinds.add_parser("research", help="run a research question as a job")
    jb_res.add_argument("question")
    jb_res.add_argument("--mode", choices=["local", "web", "mixed"])
    jb_res.add_argument("--url", action="append", default=[], metavar="URL")
    jb_res.add_argument("--max-subquestions", type=int)
    jb_res.add_argument("--no-model", action="store_true")
    _job_options(jb_res)

    jb_list = jb_sub.add_parser("list", help="job records (newest first)")
    jb_list.add_argument("--status")
    jb_list.add_argument("--kind", choices=["command", "workflow", "research"])
    jb_list.add_argument("--limit", type=int, default=20)
    jb_sub.add_parser("queue", help="what would run next, in order")
    jb_show = jb_sub.add_parser("show", help="one job plus the task timeline it wrote")
    jb_show.add_argument("job")
    jb_logs = jb_sub.add_parser("logs", help="stdout/stderr (or the error) of a finished job")
    jb_logs.add_argument("job")
    jb_run = jb_sub.add_parser("run", help="execute queued jobs (drain by default)")
    jb_run.add_argument("--once", action="store_true", help="run at most one job")
    jb_run.add_argument("--max-jobs", type=int, help="stop after this many jobs")
    jb_run.add_argument("--max-seconds", type=float, help="stop claiming new work after this long")
    jb_run.add_argument("--concurrency", type=int, help="override scheduler.max_concurrent_jobs")
    jb_run.add_argument("--kind", choices=["command", "workflow", "research"])
    jb_pause = jb_sub.add_parser("pause", help="pause a queued job, or request a running one stop")
    jb_pause.add_argument("job")
    jb_resume = jb_sub.add_parser("resume", help="requeue a paused job (continues from its cursor)")
    jb_resume.add_argument("job")
    jb_cancel = jb_sub.add_parser("cancel", help="cancel a job (kills a running command)")
    jb_cancel.add_argument("job")
    jb_cancel.add_argument("--reason")
    jb_retry = jb_sub.add_parser("retry", help="requeue a failed/interrupted job")
    jb_retry.add_argument("job")
    jb_retry.add_argument("--force", action="store_true", help="retry even when attempts are used up")
    jb_sub.add_parser("stats", help="counts by status and kind")
    jb_recover = jb_sub.add_parser("recover", help="requeue jobs whose worker disappeared")
    jb_recover.add_argument("--stale-after", type=int,
                            help="a live worker is considered stale after this many seconds")
    jb_sub.add_parser("reap", help="fail running jobs whose hard deadline has passed")

    # -- unified search --------------------------------------------------
    srch = sub.add_parser("search", help="one search across conversations, memory, tasks, workflows and files")
    srch.add_argument("query")
    srch.add_argument("--kind", action="append", choices=list(SEARCH_KINDS),
                      help="limit to one source (repeatable)")
    srch.add_argument("--limit", type=int,
                      help="merged results (default: search.default_limit)")
    srch.add_argument("--per-source", type=int,
                      help="hits per source (default: search.per_source)")
    srch.add_argument("--project")
    srch.add_argument("--conversation")
    srch.add_argument("--no-files", action="store_true", help="skip file contents")

    # -- coding workspace ------------------------------------------------
    code = sub.add_parser("code", help="Coding workspace: edit, run and test code, all through the permission centre")
    cd_sub = code.add_subparsers(dest="code_command", required=True)
    cd_open = cd_sub.add_parser("open", help="open a session on a directory inside the tool roots")
    cd_open.add_argument("--root", help="the directory (default: the first tool root)")
    cd_open.add_argument("--title", help="what this session is for")
    cd_open.add_argument("--note")
    cd_open.add_argument("--project")
    cd_list = cd_sub.add_parser("list", help="sessions, newest first")
    cd_list.add_argument("--status", choices=["open", "closed"])
    cd_list.add_argument("--limit", type=int, default=20)
    cd_show = cd_sub.add_parser("show", help="one session: its edits, its runs, its counts")
    cd_show.add_argument("session")
    cd_read = cd_sub.add_parser("read", help="read a file (needs fs.read)")
    cd_read.add_argument("session")
    cd_read.add_argument("path")
    cd_read.add_argument("--start-line", type=int, default=1)
    cd_read.add_argument("--max-lines", type=int)
    cd_ls = cd_sub.add_parser("ls", help="list a directory (needs fs.read)")
    cd_ls.add_argument("session")
    cd_ls.add_argument("path", nargs="?", default=".")
    cd_ls.add_argument("--limit", type=int, default=200)
    cd_write = cd_sub.add_parser("write", help="create or replace a file, recording the diff (needs fs.write)")
    cd_write.add_argument("session")
    cd_write.add_argument("path")
    cd_write.add_argument("--content", help="the new text; '-' reads stdin")
    cd_write.add_argument("--file", help="read the new text from a local file")
    cd_write.add_argument("--note")
    cd_rm = cd_sub.add_parser("delete", help="delete a file, recording the diff (needs fs.delete)")
    cd_rm.add_argument("session")
    cd_rm.add_argument("path")
    cd_rm.add_argument("--note")
    cd_run = cd_sub.add_parser("run", help="run a command in the session root (needs shell.run)")
    cd_run.add_argument("session")
    # dest is NOT "command": that is the top-level subcommand dest, and reusing it made
    # `code run <session> "echo hi"` overwrite args.command, so main() found no handler.
    cd_run.add_argument("code_line", metavar="command",
                        help="the command line, split like a shell but run without one")
    cd_run.add_argument("--timeout", type=int, help="seconds before the process is killed")
    cd_run.add_argument("--cwd", help="a directory inside the session root")
    cd_test = cd_sub.add_parser("test", help="run a named check from archx.checks.json")
    cd_test.add_argument("session")
    cd_test.add_argument("--check", default="test", help="which check (default: test)")
    cd_checks = cd_sub.add_parser("checks", help="the checks this project declares")
    cd_checks.add_argument("session")
    cd_diff = cd_sub.add_parser("diff", help="the session's whole patch")
    cd_diff.add_argument("session")
    cd_diff.add_argument("--write", metavar="PATH", help="also save the patch here")
    cd_runs = cd_sub.add_parser("runs", help="the runner's ledger for a session")
    cd_runs.add_argument("session")
    cd_runs.add_argument("--limit", type=int, default=20)
    cd_rerun = cd_sub.add_parser("rerun", help="run a recorded command again")
    cd_rerun.add_argument("run")
    cd_close = cd_sub.add_parser("close", help="close a session (the record stays readable)")
    cd_close.add_argument("session")
    cd_close.add_argument("--note")
    cd_sub.add_parser("stats", help="how many sessions, edits and runs this home holds")

    # -- experiment -----------------------------------------------------
    exp = sub.add_parser(
        "experiment", help="Experimental Mode: run a declared command, keep the numbers, compare runs"
    )
    ex_sub = exp.add_subparsers(dest="experiment_command", required=True)
    ex_create = ex_sub.add_parser("create", help="declare an experiment: a command and its parameters")
    ex_create.add_argument("name")
    # dest is NOT "command": that is the top-level subcommand dest, and reusing it made
    # `experiment create X --command "..."` overwrite args.command, so main() found no handler.
    ex_create.add_argument("--command", dest="experiment_line", required=True,
                           help="the command line, with {placeholders} for the parameters")
    ex_create.add_argument("--root", help="where it runs (default: the first tool root)")
    ex_create.add_argument("--hypothesis", help="what you expect, in one sentence")
    ex_create.add_argument("--param", action="append", default=[], metavar="NAME[=DEFAULT]",
                           help="declare a parameter (repeatable)")
    ex_create.add_argument("--metric-source", choices=["none", "stdout-json", "file"],
                           default="none",
                           help="where the numbers come from (default: nowhere)")
    ex_create.add_argument("--metric-file", metavar="PATH",
                           help="the JSON file the run writes (for --metric-source file)")
    ex_list = ex_sub.add_parser("list", help="experiments, newest first")
    ex_list.add_argument("--status", choices=["open", "closed"])
    ex_list.add_argument("--limit", type=int, default=20)
    ex_show = ex_sub.add_parser("show", help="one experiment: its runs, metrics and counts")
    ex_show.add_argument("experiment")
    ex_run = ex_sub.add_parser("run", help="run it once (needs shell.run)")
    ex_run.add_argument("experiment")
    ex_run.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                        help="override a parameter (repeatable)")
    ex_run.add_argument("--timeout", type=int, help="seconds before the process is killed")
    ex_run.add_argument("--seed", help="a note about what made this run different")
    ex_run.add_argument("--note")
    ex_compare = ex_sub.add_parser("compare", help="line the runs up and name the best one")
    ex_compare.add_argument("experiment")
    ex_compare.add_argument("--metric", help="which metric (default: the first one recorded)")
    ex_compare.add_argument("--minimise", "--minimize", dest="minimise", action="store_true",
                            help="lower is better")
    ex_compare.add_argument("--limit", type=int, default=50)
    ex_runs = ex_sub.add_parser("runs", help="every run of an experiment")
    ex_runs.add_argument("experiment")
    ex_runs.add_argument("--limit", type=int, default=50)
    ex_close = ex_sub.add_parser("close", help="close an experiment (the runs stay readable)")
    ex_close.add_argument("experiment")
    ex_reopen = ex_sub.add_parser("reopen", help="reopen a closed experiment")
    ex_reopen.add_argument("experiment")
    ex_del = ex_sub.add_parser("delete", help="delete an experiment and its runs")
    ex_del.add_argument("experiment")
    ex_del.add_argument("--yes", action="store_true")
    ex_sub.add_parser("stats", help="experiment counts")

    # -- play -----------------------------------------------------------
    play = sub.add_parser(
        "play", help="Play Mode: board games the rules referee, and simulations you can replay"
    )
    pl_sub = play.add_subparsers(dest="play_command", required=True)
    pl_new = pl_sub.add_parser("new", help="start a game (default: play.default_game)")
    pl_new.add_argument("game", nargs="?", choices=["tictactoe", "connect4", "nim"],
                        help="which game (default: play.default_game)")
    pl_new.add_argument("--seed", type=int, help="recorded with the game, for the engine's choices")
    pl_show = pl_sub.add_parser("show", help="the board, whose turn it is, and the legal moves")
    pl_show.add_argument("game")
    pl_show.add_argument("--moves", type=int, default=8, help="how many recent moves to show")
    pl_move = pl_sub.add_parser("move", help="propose a move; the rules accept it or say why not")
    pl_move.add_argument("game")
    pl_move.add_argument("move")
    pl_engine = pl_sub.add_parser("engine", help="let the built-in engine play the side to move")
    pl_engine.add_argument("game")
    pl_engine.add_argument("--seed", type=int, help="override the game's recorded seed")
    pl_auto = pl_sub.add_parser("auto", help="let the engine play several plies, stopping at the end")
    pl_auto.add_argument("game")
    pl_auto.add_argument("--plies", type=int, default=1, help="how many moves (default 1)")
    pl_auto.add_argument("--seed", type=int)
    pl_resign = pl_sub.add_parser("resign", help="abandon a game (the moves stay readable)")
    pl_resign.add_argument("game")
    pl_resign.add_argument("--winner", help="who is credited with the win, if anyone")
    pl_hist = pl_sub.add_parser("history", help="every move, including the ones the rules refused")
    pl_hist.add_argument("game")
    pl_list = pl_sub.add_parser("list", help="games, newest first")
    pl_list.add_argument("--status", choices=["open", "finished", "abandoned"])
    pl_list.add_argument("--limit", type=int, default=20)
    pl_sim = pl_sub.add_parser("sim", help="run a deterministic simulation and record its hash")
    pl_sim.add_argument("--width", type=int, default=40)
    pl_sim.add_argument("--height", type=int, default=20)
    pl_sim.add_argument("--steps", type=int, default=20)
    pl_sim.add_argument("--seed", type=int, default=0)
    pl_sim.add_argument("--density", type=float, default=0.3)
    pl_sim.add_argument("--no-board", dest="board", action="store_false",
                        help="do not print the final grid")
    pl_sims = pl_sub.add_parser("sims", help="recorded simulations, newest first")
    pl_sims.add_argument("--limit", type=int, default=20)
    pl_replay = pl_sub.add_parser("replay", help="recompute a simulation and check its hash")
    pl_replay.add_argument("sim")
    pl_sub.add_parser("stats", help="game, move and simulation counts")

    # -- voice and media ------------------------------------------------
    voice = sub.add_parser(
        "voice", help="Voice and media: measure files, keep transcripts, say what cannot be heard"
    )
    vo_sub = voice.add_subparsers(dest="voice_command", required=True)
    vo_probe = vo_sub.add_parser("probe", help="measure a file's bytes (needs fs.read)")
    vo_probe.add_argument("path")
    vo_probe.add_argument("--retain", action="store_true",
                          help="keep a copy of the bytes (needs voice.retain_audio)")
    vo_probe.add_argument("--force", action="store_true",
                          help="store a second row even if these bytes are already known")
    vo_list = vo_sub.add_parser("list", help="measured media, newest first")
    vo_list.add_argument("--kind", choices=["image", "audio", "text", "unknown"])
    vo_list.add_argument("--limit", type=int, default=20)
    vo_show = vo_sub.add_parser("show", help="one asset: what the bytes said, its words, its attempts")
    vo_show.add_argument("asset")
    vo_tr = vo_sub.add_parser("transcribe", help="ask for words (refused: this build has no speech model)")
    vo_tr.add_argument("asset")
    vo_say = vo_sub.add_parser("say", help="ask for speech (refused: this build has no speech model)")
    vo_say.add_argument("text")
    vo_add = vo_sub.add_parser("transcript", help="the words a person wrote for a recording")
    vo_add_sub = vo_add.add_subparsers(dest="transcript_command", required=True)
    vo_add_add = vo_add_sub.add_parser("add", help="attach words you typed")
    vo_add_add.add_argument("asset")
    vo_add_add.add_argument("--text")
    vo_add_add.add_argument("--file", help="read the words from a file (needs fs.read)")
    vo_add_list = vo_add_sub.add_parser("list", help="the words attached to an asset")
    vo_add_list.add_argument("asset")
    vo_at = vo_sub.add_parser("attempts", help="every attempt to hear or speak, refusals included")
    vo_at.add_argument("--asset")
    vo_at.add_argument("--limit", type=int, default=30)
    vo_sub.add_parser("stats", help="what this home holds, and what it still cannot do")

    # -- datasets -------------------------------------------------------
    data = sub.add_parser(
        "dataset", help="Dataset preparation: candidates, cleaning with reasons, stable splits"
    )
    ds_sub = data.add_subparsers(dest="dataset_command", required=True)
    ds_new = ds_sub.add_parser("create", help="a named corpus over one or more source paths")
    ds_new.add_argument("name")
    ds_new.add_argument("--source", action="append", default=[], metavar="PATH",
                        help="a file or directory inside the tool roots (repeatable)")
    ds_new.add_argument("--license", help="what you may do with it; unstated is recorded as unknown")
    ds_new.add_argument("--notes")
    ds_scan = ds_sub.add_parser("scan", help="measure every candidate and write a row per candidate")
    ds_scan.add_argument("dataset")
    ds_clean = ds_sub.add_parser("clean", help="apply the rules; every removal keeps its reason")
    ds_clean.add_argument("dataset")
    ds_clean.add_argument("--min-chars", type=int, default=0)
    ds_clean.add_argument("--no-dedupe", dest="dedupe", action="store_false",
                          help="keep byte-identical copies")
    ds_clean.add_argument("--normalize", action="store_true",
                          help="also collapse copies that differ only in whitespace or case")
    ds_clean.add_argument("--keep-empty", dest="drop_empty", action="store_false")
    ds_clean.add_argument("--require-license", action="store_true",
                          help="refuse to clean a dataset whose license is unknown")
    ds_split = ds_sub.add_parser("split", help="assign each record to train/val/test (stable, seeded)")
    ds_split.add_argument("dataset")
    ds_split.add_argument("--train", type=float, default=0.8)
    ds_split.add_argument("--val", type=float, default=0.1)
    ds_split.add_argument("--test", type=float, default=0.1)
    ds_split.add_argument("--seed", default="0")
    ds_build = ds_sub.add_parser("build", help="write the JSONL export and record the manifest hash")
    ds_build.add_argument("dataset")
    ds_build.add_argument("--force", action="store_true",
                          help="build even though some records have no split")
    ds_verify = ds_sub.add_parser("verify", help="recompute the manifest from disk and disagree if it moved")
    ds_verify.add_argument("dataset")
    ds_show = ds_sub.add_parser("show", help="one dataset: counts, splits, ledger")
    ds_show.add_argument("dataset")
    ds_recs = ds_sub.add_parser("records", help="the candidates, kept and dropped")
    ds_recs.add_argument("dataset")
    ds_recs.add_argument("--status", choices=["kept", "dropped"])
    ds_recs.add_argument("--split", choices=["train", "val", "test"])
    ds_recs.add_argument("--limit", type=int, default=50)
    ds_expl = ds_sub.add_parser("explain", help="why one file is in the dataset, or why it is not")
    ds_expl.add_argument("record")
    ds_steps = ds_sub.add_parser("steps", help="the ledger: what each step took in and gave back")
    ds_steps.add_argument("dataset")
    ds_list = ds_sub.add_parser("list", help="datasets, newest first")
    ds_list.add_argument("--limit", type=int, default=20)
    ds_sub.add_parser("stats", help="dataset and record counts")

    # -- gui ------------------------------------------------------------
    gui = sub.add_parser("gui", help="the local web GUI (a client of this same app)")
    gui_sub = gui.add_subparsers(dest="gui_command", required=True)
    gui_serve = gui_sub.add_parser("serve", help="serve the GUI and print its token")
    gui_serve.add_argument("--host", default=None, help="bind address (default gui.host)")
    gui_serve.add_argument("--port", type=int, default=None, help="port (0 picks a free one)")
    gui_serve.add_argument("--allow-remote", action="store_true",
                           help="allow a non-loopback bind (the token becomes the only boundary)")
    gui_serve.add_argument("--token", default=None, help="use a specific token instead of a random one")
    gui_serve.add_argument("--open", dest="open_browser", action="store_true", default=None,
                           help="open the URL in a browser")
    gui_serve.add_argument("--no-open", dest="open_browser", action="store_false",
                           help="never open a browser")
    gui_sub.add_parser("routes", help="list every endpoint the GUI serves")

    res = sub.add_parser("research", help="Researcher Mode: plan, read real sources, cite them")
    res_sub = res.add_subparsers(dest="research_command", required=True)
    res_run = res_sub.add_parser("run", help="research a question end to end")
    res_run.add_argument("question")
    res_run.add_argument("--mode", choices=["local", "web", "mixed"],
                         help="where to look (default: research.default_mode)")
    res_run.add_argument("--url", action="append", default=[], metavar="URL",
                         help="seed URL (repeatable); web and mixed modes need at least one")
    res_run.add_argument("--urls-from", metavar="FILE",
                         help="read seed URLs from a file, one per line")
    res_run.add_argument("--max-subquestions", type=int)
    res_run.add_argument("--subquestion", action="append", default=[], metavar="TEXT",
                         help="use this subquestion instead of planning (repeatable)")
    res_run.add_argument("--format", choices=["markdown", "html", "md"])
    res_run.add_argument("--out", help="write the report here (default: <home>/research/<run>.md)")
    res_run.add_argument("--model")
    res_run.add_argument("--no-model", action="store_true",
                         help="do not call a model at all (extractive report, stated as such)")
    res_run.add_argument("--allow-private-hosts", action="store_true",
                         help="let net.fetch reach loopback/private addresses (needs the grant too)")
    res_list = res_sub.add_parser("list", help="research runs (newest first)")
    res_list.add_argument("--status")
    res_list.add_argument("--closed", action="store_true", help="only runs you marked done")
    res_list.add_argument("--open", action="store_true", help="only runs you have not marked done")
    res_list.add_argument("--limit", type=int, default=20)
    res_show = res_sub.add_parser("show", help="one run: plan, coverage, limitations, sources")
    res_show.add_argument("run")
    res_sources = res_sub.add_parser("sources", help="the sources a run read, and the failures")
    res_sources.add_argument("run")
    res_report = res_sub.add_parser("report", help="print the stored report")
    res_report.add_argument("run")
    res_report.add_argument("--write", help="also write it to this path")
    res_verify = res_sub.add_parser("verify", help="re-check every citation in the report")
    res_verify.add_argument("run")
    res_search = res_sub.add_parser("search", help="search past research runs")
    res_search.add_argument("query")
    res_search.add_argument("--limit", type=int, default=10)
    res_close = res_sub.add_parser("close", help="mark a run done - your call, not the runner's")
    res_close.add_argument("run")
    res_close.add_argument("--note", help="what settled it")
    res_reopen = res_sub.add_parser("reopen", help="undo a close")
    res_reopen.add_argument("run")
    res_sub.add_parser("stats", help="research counts")
    res_del = res_sub.add_parser("delete", help="delete a run and its sources")
    res_del.add_argument("run")
    res_del.add_argument("--yes", action="store_true")

    # -- learning ------------------------------------------------------
    learn = sub.add_parser("learning", help="Learning Mode: goals, reviewable items, sessions")
    ln_sub = learn.add_subparsers(dest="learning_command", required=True)

    ln_goal = ln_sub.add_parser("goal", help="the goal: what you are learning and what counts as done")
    ln_goal_sub = ln_goal.add_subparsers(dest="learning_goal_command", required=True)
    ln_goal_new = ln_goal_sub.add_parser("create", help="create a goal")
    ln_goal_new.add_argument("title")
    ln_goal_new.add_argument("--objective", help="what you want to be able to do (default: the title)")
    ln_goal_new.add_argument("--topic", help="the subject, used by the planner and search")
    ln_goal_new.add_argument("--level", choices=["beginner", "intermediate", "advanced"],
                             default="beginner")
    ln_goal_new.add_argument("--criteria", action="append", default=[], metavar="TEXT",
                             help="a success criterion (repeatable). Completion is measured against these")
    ln_goal_new.add_argument("--priority", type=int, default=5, help="0-9, higher sorts first")
    ln_goal_new.add_argument("--target-date", help="when you mean to be done (ISO date)")
    ln_goal_list = ln_goal_sub.add_parser("list", help="goals, active first")
    ln_goal_list.add_argument("--status", choices=["active", "paused", "completed", "abandoned"])
    ln_goal_list.add_argument("--limit", type=int, default=20)
    ln_goal_show = ln_goal_sub.add_parser("show", help="one goal with its items, schedule and stats")
    ln_goal_show.add_argument("goal")
    ln_goal_edit = ln_goal_sub.add_parser("edit", help="change a goal")
    ln_goal_edit.add_argument("goal")
    ln_goal_edit.add_argument("--title")
    ln_goal_edit.add_argument("--objective")
    ln_goal_edit.add_argument("--topic")
    ln_goal_edit.add_argument("--level", choices=["beginner", "intermediate", "advanced"])
    ln_goal_edit.add_argument("--priority", type=int)
    ln_goal_edit.add_argument("--status", choices=["active", "paused", "completed", "abandoned"])
    ln_goal_edit.add_argument("--criteria", action="append", default=[], metavar="TEXT")
    ln_goal_done = ln_goal_sub.add_parser("complete", help="close a goal against your criteria")
    ln_goal_done.add_argument("goal")
    ln_goal_done.add_argument("--note", help="what convinced you it is done")
    ln_goal_del = ln_goal_sub.add_parser("delete", help="delete a goal and everything under it")
    ln_goal_del.add_argument("goal")
    ln_goal_del.add_argument("--yes", action="store_true")

    ln_item = ln_sub.add_parser("item", help="what is studied: a question with an answer, hints and a schedule")
    ln_item_sub = ln_item.add_subparsers(dest="learning_item_command", required=True)
    ln_item_add = ln_item_sub.add_parser("add", help="add one item to a goal")
    ln_item_add.add_argument("goal")
    ln_item_add.add_argument("prompt")
    ln_item_add.add_argument("--expected", help="the answer Archx can check exactly (omit to self-grade)")
    ln_item_add.add_argument("--hint", action="append", default=[], metavar="TEXT",
                             help="a hint, ordered; repeat for the ladder")
    ln_item_add.add_argument("--explanation", help="shown after the attempt, right or wrong")
    ln_item_add.add_argument("--subtopic")
    ln_item_list = ln_item_sub.add_parser("list", help="items of a goal, with their schedule")
    ln_item_list.add_argument("goal")
    ln_item_list.add_argument("--due", action="store_true", help="only what is due now")
    ln_item_list.add_argument("--status", choices=["new", "learning", "review", "mastered"])
    ln_item_edit = ln_item_sub.add_parser("edit", help="change an item's question, answer key or hints")
    ln_item_edit.add_argument("item")
    ln_item_edit.add_argument("--prompt", help="reword the question")
    ln_item_edit.add_argument("--expected", help="the answer Archx can check exactly")
    ln_item_edit.add_argument("--hint", action="append", default=None, metavar="TEXT",
                              help="replace the whole ladder; repeat for each rung, in order")
    ln_item_edit.add_argument("--add-hint", action="append", default=[], metavar="TEXT",
                              help="append one rung to the end of the ladder")
    ln_item_edit.add_argument("--clear-hints", action="store_true", help="remove every hint")
    ln_item_edit.add_argument("--explanation", help="shown after the attempt, right or wrong")
    ln_item_edit.add_argument("--subtopic")
    ln_item_del = ln_item_sub.add_parser("delete", help="delete one item")
    ln_item_del.add_argument("item")
    ln_item_del.add_argument("--yes", action="store_true")

    ln_plan = ln_sub.add_parser("plan", help="propose items for a goal (checkpoints without a model)")
    ln_plan.add_argument("goal")
    ln_plan.add_argument("--no-model", action="store_true", help="use rule checkpoints only")
    ln_plan.add_argument("--max", type=int, dest="max_items")
    ln_plan.add_argument("--model")
    ln_next = ln_sub.add_parser("next", help="what to study now, and why")
    ln_next.add_argument("goal")
    ln_ask = ln_sub.add_parser("ask", help="the next question, with the answer and hints removed")
    ln_ask.add_argument("goal")
    ln_hint = ln_sub.add_parser("hint", help="reveal one hint (refused until you have tried)")
    ln_hint.add_argument("item")
    ln_hint.add_argument("--level", type=int, default=1)
    ln_answer = ln_sub.add_parser("answer", help="answer an item and see the grade and the new schedule")
    ln_answer.add_argument("item")
    ln_answer.add_argument("answer")
    ln_answer.add_argument("--self-rate", type=int, help="1-5, needed when the item has no expected answer")
    ln_answer.add_argument("--session", help="attach to a session (default: the open one, or a new one)")
    ln_answer.add_argument("--hints", type=int, default=0, help="how many hints you used")

    ln_session = ln_sub.add_parser("session", help="a sitting of practice, review or explanation")
    ln_session_sub = ln_session.add_subparsers(dest="learning_session_command", required=True)
    ln_session_start = ln_session_sub.add_parser("start", help="start a session on a goal")
    ln_session_start.add_argument("goal")
    ln_session_start.add_argument("--mode", choices=["practice", "review", "explain"], default="practice")
    ln_session_list = ln_session_sub.add_parser("list", help="recent sessions")
    ln_session_list.add_argument("--goal")
    ln_session_list.add_argument("--limit", type=int, default=10)
    ln_session_end = ln_session_sub.add_parser("end", help="close a session and summarise it")
    ln_session_end.add_argument("session")

    ln_review = ln_sub.add_parser("review", help="start a review session of everything due")
    ln_review.add_argument("goal")
    ln_review.add_argument("--limit", type=int)
    ln_stats = ln_sub.add_parser("stats", help="progress counts")
    ln_stats.add_argument("goal", nargs="?")
    ln_search = ln_sub.add_parser("search", help="search goals and items")
    ln_search.add_argument("query")
    ln_search.add_argument("--limit", type=int, default=10)
    ln_report = ln_sub.add_parser("report", help="print a progress report (and optionally write it)")
    ln_report.add_argument("goal")
    ln_report.add_argument("--write", help="write the report here")

    # -- simple mode -----------------------------------------------------
    simple = sub.add_parser("simple", help="Simple Mode: ask in plain language (no subcommand = chat loop)")
    sm_sub = simple.add_subparsers(dest="simple_command")
    sm_ask = sm_sub.add_parser("ask", help="ask one question and see what was done and why")
    sm_ask.add_argument("text")
    sm_ask.add_argument("--model")
    sm_ask.add_argument("--conversation")
    sm_sub.add_parser("status", help="model, memory, tasks and queue in plain language")
    sm_sub.add_parser("help", help="what Simple Mode understands")

    # -- task history ---------------------------------------------------
    tasks = sub.add_parser("tasks", help="task history, artifacts and reproduction records")
    tk_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    tk_list = tk_sub.add_parser("list", help="recent tasks (newest first)")
    tk_list.add_argument("--status", choices=["queued", "running", "completed", "failed", "cancelled", "interrupted"])
    tk_list.add_argument("--type", dest="task_type")
    tk_list.add_argument("--project")
    tk_list.add_argument("--conversation")
    tk_list.add_argument("--since")
    tk_list.add_argument("--limit", type=int, default=20)
    tk_show = tk_sub.add_parser("show", help="one task: fields, timeline, tool runs, artifacts")
    tk_show.add_argument("task")
    for verb, text in (("start", "record a task and mark it running"),
                       ("queue", "record a task without starting it")):
        node = tk_sub.add_parser(verb, help=text)
        node.add_argument("--type", dest="task_type", default="system")
        node.add_argument("--title")
        node.add_argument("--project")
        node.add_argument("--conversation")
        node.add_argument("--model")
        node.add_argument("--parent")
    tk_done = tk_sub.add_parser("complete", help="mark a task completed")
    tk_done.add_argument("task")
    tk_done.add_argument("--summary")
    tk_fail = tk_sub.add_parser("fail", help="mark a task failed with a reason")
    tk_fail.add_argument("task")
    tk_fail.add_argument("--error", required=True)
    tk_cancel = tk_sub.add_parser("cancel", help="cancel a task")
    tk_cancel.add_argument("task")
    tk_cancel.add_argument("--reason")
    tk_log = tk_sub.add_parser("log", help="append a step to a task's timeline")
    tk_log.add_argument("task")
    tk_log.add_argument("--kind", default="note")
    tk_log.add_argument("--detail")
    tk_q = tk_sub.add_parser("question", help="record an open question on a task")
    tk_q.add_argument("task")
    tk_q.add_argument("--text", required=True)
    tk_r = tk_sub.add_parser("resolve", help="resolve an open question (index or text)")
    tk_r.add_argument("task")
    tk_r.add_argument("question")
    tk_art = tk_sub.add_parser("artifacts", help="artifacts recorded for a task")
    tk_art.add_argument("task")
    tk_add = tk_sub.add_parser("attach", help="record a file as a task artifact (and a content version)")
    tk_add.add_argument("task")
    tk_add.add_argument("path")
    tk_add.add_argument("--kind", default="file")
    tk_add.add_argument("--name")
    tk_repro = tk_sub.add_parser("reproduce", help="can this task be reproduced? what would it take?")
    tk_repro.add_argument("task")
    tk_repro.add_argument("--record", action="store_true", help="store the assessment as a record")
    tk_repro.add_argument("--verify", metavar="REPRODUCTION_ID",
                          help="re-check an existing record against today's environment")
    tk_sub.add_parser("stats", help="task counts by status and type")

    # -- version history ------------------------------------------------
    versions = sub.add_parser("versions", help="content versions: history, diff, restore")
    v_sub = versions.add_subparsers(dest="versions_command", required=True)
    v_list = v_sub.add_parser("list", help="versions of one subject")
    v_list.add_argument("subject_type")
    v_list.add_argument("subject_id")
    v_record = v_sub.add_parser("record", help="record the current content as a version")
    v_record.add_argument("subject_type")
    v_record.add_argument("subject_id")
    v_record.add_argument("--content")
    v_record.add_argument("--file")
    v_record.add_argument("--note", default="")
    v_record.add_argument("--label")
    v_record.add_argument("--by", default="user")
    v_record.add_argument("--no-content", action="store_true",
                          help="record only checksum and size (binary or large content)")
    v_show = v_sub.add_parser("show", help="one version (content included)")
    v_show.add_argument("subject_type")
    v_show.add_argument("subject_id")
    v_show.add_argument("version", nargs="?", default="latest")
    v_diff = v_sub.add_parser("diff", help="unified diff between two versions")
    v_diff.add_argument("subject_type")
    v_diff.add_argument("subject_id")
    v_diff.add_argument("--from", dest="from_version")
    v_diff.add_argument("--to", dest="to_version")
    v_restore = v_sub.add_parser("restore", help="write an old version as a new version")
    v_restore.add_argument("subject_type")
    v_restore.add_argument("subject_id")
    v_restore.add_argument("version")
    v_restore.add_argument("--note", default="")
    v_sub.add_parser("subjects", help="subjects that have versions")

    # -- database -------------------------------------------------------
    db = sub.add_parser("db", help="database health, backup and restore")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("check", help="integrity check and table counts")
    db_sub.add_parser("stats", help="row counts for every table")
    db_backup = db_sub.add_parser("backup", help="create a backup")
    db_backup.add_argument("--label", default="manual")
    db_sub.add_parser("backups", help="list backups")
    db_verify = db_sub.add_parser("verify", help="verify a backup")
    db_verify.add_argument("backup")
    db_preview = db_sub.add_parser("preview-restore", help="preview a restore (changes nothing)")
    db_preview.add_argument("backup")
    db_restore = db_sub.add_parser("restore", help="restore a backup (the current db is renamed aside)")
    db_restore.add_argument("backup")
    db_restore.add_argument("--yes", action="store_true")
    db_retention = db_sub.add_parser("retention", help="retire old backups")
    db_retention.add_argument("--keep", type=int, default=10)
    db_sub.add_parser("journal", help="show recent write-journal entries")

    # -- trace ----------------------------------------------------------
    trace = sub.add_parser("trace", help="debug and trace")
    t_sub = trace.add_subparsers(dest="trace_command", required=True)
    t_list = t_sub.add_parser("list", help="list events")
    t_list.add_argument("--kind", action="append")
    t_list.add_argument("--conversation")
    t_list.add_argument("--task")
    t_list.add_argument("--run")
    t_list.add_argument("--status")
    t_list.add_argument("--limit", type=int, default=30)
    t_list.add_argument("--newest-first", action="store_true")
    t_show = t_sub.add_parser("show", help="show one event")
    t_show.add_argument("event")
    t_tree = t_sub.add_parser("tree", help="show the causal tree for an event")
    t_tree.add_argument("event")
    t_sub.add_parser("errors", help="recent errors and denials")
    t_sub.add_parser("summary", help="event counts by kind and status")
    t_export = t_sub.add_parser("export", help="export events as JSONL (redacted)")
    t_export.add_argument("--out", required=True)
    t_export.add_argument("--conversation")
    t_retention = t_sub.add_parser("retention", help="apply trace retention")
    t_retention.add_argument("--days", type=int)

    _add_leaf_flags(parser)
    _decorate_leaf_parsers(parser)
    return parser


# --------------------------------------------------------------------------
# workspace helper
# --------------------------------------------------------------------------
def _workspace(args: argparse.Namespace, *, create: bool = True) -> Workspace:
    return open_workspace(
        home=args.home,
        config_path=args.config,
        overrides=None,
        allow_test_double=getattr(args, "allow_simulated", False),
    )


def _require(simulated_ok: bool, allow: bool) -> bool:
    return bool(allow or simulated_ok)


# --------------------------------------------------------------------------
# command handlers
# --------------------------------------------------------------------------
def cmd_init(args: argparse.Namespace) -> int:
    cfg = load_config(home=args.home, config_path=args.config, create=False)
    with open_workspace(home=args.home, config_path=args.config) as ws:
        cfg = ws.config
        found = ws.models.discover_local()
        data = {
            "home": str(cfg.home),
            "database": str(ws.store.path),
            "events": str(ws.events.path),
            "config": str(cfg.source_file or (cfg.home / "config.json")),
            "schema_version": ws.store.schema_version(),
            "models_discovered": [m.name for m in found],
            "warnings": ws.warnings,
        }
        if args.json:
            emit_json(data)
        else:
            emit(f"{BRAND} initialised")
            emit(f"  home       {data['home']}")
            emit(f"  database   {data['database']}")
            emit(f"  traces     {data['events']}")
            emit(f"  config     {data['config']}")
            emit(f"  schema     v{data['schema_version']}")
            if found:
                emit(f"  models     discovered {len(found)}: {', '.join(m.name for m in found)}")
            else:
                emit("  models     none found in the models directory")
                emit("             add one with: archx-agent models add-http ...")
            for warning in ws.warnings:
                emit(f"  warning    {warning}")
    return EXIT_OK


def cmd_info(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        data = ws.info()
        data["memory"] = ws.memory.stats()
        data["models"] = [m.name for m in ws.models.list()]
        if args.json:
            emit_json(data)
        else:
            emit(f"{BRAND} {__version__}")
            emit(f"  home            {data['home']}")
            emit(f"  database        {data['database']}")
            emit(f"  trace database  {data['events']}")
            emit(f"  schema          v{data['schema_version']} (expected v{data['expected_schema_version']})")
            emit(f"  conversations   {data['conversations']}")
            emit(f"  memories        {data['memories']}")
            emit(f"  models          {', '.join(data['models']) or 'none configured'}")
            for warning in data["warnings"]:
                emit(f"  warning         {warning}")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []
    cfg = load_config(home=args.home, config_path=args.config, create=False)
    for key in ("paths.home", "storage.db_path", "storage.events_path"):
        path = Path(cfg.get(key))
        target = path if key != "storage.db_path" else path.parent
        writable = os.access(target if target.exists() else target.parent, os.W_OK)
        checks.append((key, writable, str(target)))
    try:
        with _workspace(args) as ws:
            integrity = ws.store.integrity_check()
            checks.append(("database integrity", integrity == ["ok"], ", ".join(integrity)))
            models = ws.models.list()
            checks.append(("model catalogue", bool(models), f"{len(models)} model(s)"))
            usable = [m for m in models if m.is_usable]
            checks.append(("usable models", bool(usable), ", ".join(m.name for m in usable) or "none"))
            try:
                record = ws.resolve_model()
                runtime = ws.runtime_for(record)
                health = runtime.health()
                checks.append(("runtime", health.ok, f"{record.name}: {health.detail}"))
            except ArchxError as exc:
                checks.append(("runtime", False, exc.message))
            checks.append(
                ("tracing", ws.events.count() >= 0, f"{ws.events.count()} event(s) at {ws.events.path}")
            )
    except ArchxError as exc:
        checks.append(("workspace", False, exc.message))
    ok = all(passed for _name, passed, _detail in checks)
    if args.json:
        emit_json({"ok": ok, "checks": [{"check": n, "ok": p, "detail": d} for n, p, d in checks]})
    else:
        for name, passed, detail in checks:
            emit(f"[{'ok' if passed else 'FAIL'}] {name}: {detail}")
    return EXIT_OK if ok else EXIT_ERROR


def cmd_config(args: argparse.Namespace) -> int:
    cfg = load_config(home=args.home, config_path=args.config, create=False)
    if args.config_command == "list":
        rows = list_settings()
        if args.json:
            emit_json(rows)
        else:
            emit(table([[r["key"], r["type"], str(r["default"])[:30], r["description"][:60]] for r in rows],
                       ["setting", "type", "default", "description"]))
        return EXIT_OK
    if args.config_command == "get":
        value = cfg.get(args.key)
        emit_json({"key": args.key, "value": value, "source": cfg.provenance.get(args.key)}) if args.json else emit(
            f"{args.key} = {value}  (source: {cfg.provenance.get(args.key)})"
        )
        return EXIT_OK
    if args.config_command == "set":
        raw: Any = args.value
        expected = {row["key"]: row["type"] for row in list_settings()}.get(args.key)
        if expected == "list":
            # Accept both a JSON array and a comma-separated list; a JSON string that is
            # not an array is almost always a quoting mistake, so say so.
            text = args.value.strip()
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    return fail(f"{args.key} is a list; that is not valid JSON: {exc}", EXIT_USAGE)
                if not isinstance(parsed, list):
                    return fail(f"{args.key} expects a list, got {type(parsed).__name__}", EXIT_USAGE)
                raw = parsed
            else:
                raw = [part.strip() for part in text.split(",") if part.strip()]
        try:
            cfg.set(args.key, raw, source="cli")
        except ArchxError as exc:
            return fail(f"{args.key}: {exc.message}", EXIT_USAGE)
        path = Path(args.config) if args.config else cfg.home / "config.json"
        existing = {}
        if path.exists():
            existing = json.loads(path.read_text()).get("settings", {})
        existing[args.key] = cfg.get(args.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json_text({"version": cfg.version, "settings": existing}) + "\n")
        emit(f"set {args.key} = {cfg.get(args.key)} in {path}")
        return EXIT_OK
    emit_json(cfg.to_dict()) if args.json else emit(json_text(cfg.to_dict()))
    return EXIT_OK


def cmd_models(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        command = args.models_command
        if command == "list":
            ws.models.refresh_states()
            records = ws.models.list()
            if args.json:
                emit_json([m.to_dict() for m in records])
            else:
                if not records:
                    emit("no models configured")
                    emit("  local:  archx-agent models discover --dir /path/to/gguf")
                    emit("  http:   archx-agent models add-http --name x --base-url http://127.0.0.1:8080 --model y")
                    return EXIT_OK
                emit(
                    table(
                        [
                            [
                                m.name[:28],
                                m.provider,
                                m.runtime,
                                m.state,
                                ",".join(m.verified_capabilities) or "-",
                                f"{m.size_bytes // (1024*1024)}MB" if m.size_bytes else "-",
                            ]
                            for m in records
                        ],
                        ["name", "provider", "runtime", "state", "verified", "size"],
                    )
                )
            return EXIT_OK
        if command == "discover":
            found = ws.models.discover_local(args.dir, recursive=not args.no_recursive)
            if args.json:
                emit_json([m.to_dict() for m in found])
            else:
                if not found:
                    emit(f"no GGUF files found in {args.dir or ws.config.get('paths.models')}")
                for m in found:
                    emit(f"registered {m.name}  ({m.state}, {m.quantization or 'unknown quant'})")
            return EXIT_OK
        if command == "add-http":
            record = ws.models.register_remote(
                args.name,
                provider=args.provider
                or ("local-http" if _is_loopback(args.base_url) else "remote-http"),
                runtime="openai-http",
                model_ref=args.model,
                base_url=args.base_url,
                context_length=args.context_length,
                capabilities=args.capability or ["chat"],
                verification=args.verification,
            )
            if args.credential_ref:
                metadata = dict(record.user_metadata)
                metadata["credential_ref"] = args.credential_ref
                record = ws.models.update(record.id, user_metadata=metadata)
            emit(f"registered {record.name} ({record.id}) provider={record.provider} runtime={record.runtime}")
            emit(f"  endpoint {args.base_url}")
            emit("  note: capabilities are claims until verified with `archx-agent models verify`")
            return EXIT_OK
        if command == "sdks":
            from archx_agent.adapters.sdk_transport import SDKS, sdk_available

            for key, spec in SDKS.items():
                ok, why = sdk_available(key)
                if args.json:
                    continue
                emit(f"{key:10s} {spec.label:16s} {'installed' if ok else 'MISSING':10s} "
                     f"{spec.package:14s} key from {spec.env_var}")
                if not ok:
                    emit(f"           {why}")
            if args.json:
                emit_json({
                    key: {"installed": sdk_available(key)[0], "package": spec.package,
                          "env_var": spec.env_var, "base_url": spec.default_base_url}
                    for key, spec in SDKS.items()
                })
            return EXIT_OK
        if command == "add-sdk":
            from archx_agent.adapters.sdk_transport import SDKS, sdk_available

            if args.sdk not in SDKS:
                return fail(f"unknown SDK {args.sdk!r} (known: {', '.join(sorted(SDKS))})", EXIT_USAGE)
            try:
                record = ws.register_sdk(
                    args.name,
                    sdk=args.sdk,
                    model_ref=args.model,
                    base_url=args.base_url,
                    credential_ref=args.credential_ref,
                    context_length=args.context_length,
                    capabilities=args.capability or ["chat"],
                    verification=args.verification,
                )
            except ArchxError as exc:
                return fail(exc.message, EXIT_USAGE)
            spec = SDKS[args.sdk]
            emit(f"registered {record.name} ({record.id}) provider={record.provider} runtime={record.runtime}")
            emit(f"  sdk      {spec.package} (`{spec.import_name}`)")
            emit(f"  model    {record.model_ref}")
            emit(f"  endpoint {(record.facts or {}).get('base_url') or 'the SDK default'}")
            emit(f"  key      read at use time from {(record.user_metadata or {}).get('credential_ref')} (never stored)")
            installed, why = sdk_available(args.sdk)
            emit(f"  sdk      {'installed' if installed else 'NOT installed - ' + why}")
            ready, why = ws.runtime_availability(record)
            emit(f"  runtime  {'ready' if ready else 'not ready'} - {why}")
            emit("note: capabilities are claims until measured with `archx-agent models probe`")
            return EXIT_OK
        if command == "add-gemini":
            from archx_agent.adapters.gemini_runtime import DEFAULT_BASE_URL

            base_url = (args.base_url or DEFAULT_BASE_URL).rstrip("/")
            if not str(args.credential_ref).startswith("secret://"):
                return fail(
                    "credentials must be a secret://env/NAME or secret://file/PATH reference, "
                    "not the key itself (the key would end up in the config, the trace and the logs)",
                    EXIT_USAGE,
                )
            record = ws.register_gemini(
                args.name,
                model_ref=args.model,
                base_url=base_url,
                credential_ref=args.credential_ref,
                api_version=args.api_version,
                context_length=args.context_length,
                capabilities=args.capability or ["chat"],
                verification=args.verification,
            )
            emit(f"registered {record.name} ({record.id}) provider={record.provider} runtime={record.runtime}")
            emit(f"  model    {record.model_ref}")
            emit(f"  endpoint {base_url}/{args.api_version}")
            emit(f"  key      read at use time from {args.credential_ref} (never stored)")
            ready, why = ws.runtime_availability(record)
            emit(f"  runtime  {'ready' if ready else 'not ready'} - {why}")
            if str(base_url).startswith("https://") and not record.provider.startswith("local"):
                if ws.config.get("model.local_only"):
                    emit("")
                    emit("note: model.local_only is true, so a chat turn will refuse to send")
                    emit("      anything to this endpoint until you set it false deliberately.")
                emit("note: this endpoint is remote; `providers add google`, confirm its privacy")
                emit("      terms and record consent before the first call (see docs/PROVIDERS.md).")
            emit("note: capabilities are claims until measured with `archx-agent models probe`")
            return EXIT_OK
        if command == "add-scripted":
            record = ws.models.register_remote(
                args.name,
                provider="test-double",
                runtime="scripted",
                model_ref="simulated",
                context_length=8192,
                capabilities=["chat"],
                verification="unverified",
                claims={"simulated": True},
            )
            if record.name != args.name:
                emit(
                    f"a simulated model is already registered as {record.name!r} ({record.id}); "
                    "one test double is enough - reusing it"
                )
            else:
                emit(f"registered SIMULATED model {record.name} ({record.id})")
            emit("  this runtime performs no inference; it exists to exercise the app offline")
            return EXIT_OK
        if command == "show":
            record = ws.models.get(args.model)
            if record.is_err:
                record = ws.models.by_name(args.model)
            if record.is_err:
                return fail(f"no model matches {args.model!r}")
            m = record.value
            history = ws.models.capability_history(m.id)
            data = m.to_dict()
            data["capability_tests"] = history
            if args.json:
                emit_json(data)
                return EXIT_OK
            emit(f"{m.name}   ({m.id})")
            emit(f"  provider        {m.provider}")
            emit(f"  runtime         {m.runtime}")
            emit(f"  state           {m.state}")
            emit(f"  path / ref      {m.path or m.model_ref}")
            emit(f"  context         {m.context_length}")
            emit(f"  quantization    {m.quantization or 'unknown'} (claim)")
            emit(f"  verified caps   {', '.join(m.verified_capabilities) or 'none'}")
            emit(f"  verification    {m.verification_state}")
            emit(f"  usage           {m.success_count} ok / {m.failure_count} failed")
            if m.claims:
                emit(f"  claims          {json_text(m.claims)}")
            if m.facts:
                emit(f"  facts           {json_text(m.facts)}")
            if history:
                emit("  capability tests")
                for row in history[:5]:
                    emit(f"    {row['capability']}: {row['outcome']} ({row['run_at']})")
            return EXIT_OK
        if command in ("enable", "disable"):
            record = ws.models.get(args.model)
            if record.is_err:
                record = ws.models.by_name(args.model)
            if record.is_err:
                return fail(f"no model matches {args.model!r}")
            updated = ws.models.set_enabled(record.value.id, command == "enable")
            emit(f"{updated.name} is now {updated.state}")
            return EXIT_OK
        if command == "verify":
            record = ws.models.get(args.model)
            if record.is_err:
                record = ws.models.by_name(args.model)
            if record.is_err:
                return fail(f"no model matches {args.model!r}")
            updated = ws.models.set_verified_capabilities(
                record.value.id, args.capability, basis=args.basis, verification_state=args.state
            )
            emit(f"verified capabilities for {updated.name}: {', '.join(updated.verified_capabilities)}")
            return EXIT_OK
        if command == "prefer":
            record = ws.models.get(args.model)
            if record.is_err:
                record = ws.models.by_name(args.model)
            if record.is_err:
                return fail(f"no model matches {args.model!r}")
            updated = ws.models.set_preferred_for(record.value.id, args.task)
            emit(f"{updated.name} preferred for: {', '.join(args.task)}")
            return EXIT_OK
        if command == "remove":
            record = ws.models.get(args.model)
            if record.is_err:
                record = ws.models.by_name(args.model)
            if record.is_err:
                return fail(f"no model matches {args.model!r}")
            ws.models.remove(record.value.id, delete_file=args.delete_file)
            emit(f"removed {record.value.name}")
            return EXIT_OK
        if command == "route":
            required = args.require or None
            try:
                decision = ws.route_model(
                    task=args.task,
                    model_id=args.model,
                    required=required,
                    allow_unverified=True if args.allow_unverified else None,
                    allow_cloud=True if args.allow_cloud else None,
                    min_context_tokens=args.min_context,
                )
            except ArchxError as exc:
                return fail(exc.message, EXIT_UNAVAILABLE if isinstance(exc, ModelNotFoundError) else EXIT_USAGE)
            data = decision.to_dict()
            if args.json:
                emit_json(data)
            else:
                if decision.chosen is None:
                    emit("no eligible model")
                else:
                    emit(f"chosen    {decision.chosen.name}  ({decision.chosen.id})")
                emit(f"task      {decision.task}  required={list(decision.required)}")
                emit(f"why       {decision.explanation()}")
                if decision.fallbacks:
                    emit("fallbacks " + ", ".join(m.name for m in decision.fallbacks))
                for candidate in decision.candidates:
                    if candidate.eligible:
                        mark = "*" if decision.chosen and candidate.model_id == decision.chosen.id else " "
                        emit(f"  {mark} {candidate.name:<24} score {candidate.score:6.1f}  eligible")
                    else:
                        emit(f"    {candidate.name:<24} rejected: {candidate.blockers[0]}")
            return EXIT_OK
        if command == "probe":
            try:
                result = ws.router.probe(args.model, args.capability)
            except ArchxError as exc:
                return fail(exc.message, EXIT_USAGE)
            if args.json:
                emit_json(result)
            else:
                emit(f"{result['capability']}: {result['outcome']}  ({result['detail']})")
                emit(f"  latency {result['latency_ms']} ms")
                state = result["state_after"]
                emit(f"  state now {state['state']} ({state['basis']})")
                emit("  this drove the runtime; the result is recorded and the router will use it")
            return EXIT_OK if result["outcome"] == "passed" else EXIT_DEGRADED
        if command == "capabilities":
            if args.model:
                record = ws.models.get(args.model)
                if record.is_err:
                    record = ws.models.by_name(args.model)
                if record.is_err:
                    return fail(f"no model matches {args.model!r}")
                matrix = ws.models.capability_matrix(record.value.id)
                if args.json:
                    emit_json({"model": record.value.name, "capabilities": matrix})
                else:
                    emit(f"{record.value.name} ({record.value.id})")
                    for capability, state in matrix.items():
                        emit(f"  {capability:<14} {state['state']:<12} {state['basis']}")
                return EXIT_OK
            rows = []
            for record in ws.models.list():
                for capability, state in ws.models.capability_matrix(record.id).items():
                    rows.append([record.name, capability, state["state"], state["basis"]])
            if args.json:
                emit_json([{"model": r[0], "capability": r[1], "state": r[2], "basis": r[3]} for r in rows])
            else:
                emit(table(rows, ["model", "capability", "state", "basis"])) if rows else emit("no models")
            return EXIT_OK
        if command == "storage":
            data = ws.models.storage_summary()
            emit_json(data) if args.json else emit(json_text(data))
            return EXIT_OK
        if command == "compare":
            rows = ws.models.compare(args.models)
            if args.json:
                emit_json(rows)
            else:
                emit(
                    table(
                        [[r["name"], r["provider"], r["state"], r["context_length"], r["verification_state"],
                          f"{r['success_count']}/{r['failure_count']}"] for r in rows],
                        ["name", "provider", "state", "ctx", "verification", "ok/fail"],
                    )
                )
            return EXIT_OK
    return EXIT_USAGE


def cmd_chat(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        service = ChatService(ws, ws.context)
        params = None
        if args.temperature is not None or args.max_tokens is not None:
            from archx_agent.adapters.model_runtime import GenerationParams

            params = GenerationParams(
                temperature=args.temperature if args.temperature is not None else ws.config.get("model.temperature"),
                max_tokens=args.max_tokens if args.max_tokens is not None else ws.config.get("model.output_budget"),
            )
        manual_ids = [x.strip() for x in (args.manual_ids or "").split(",") if x.strip()] or None
        try:
            reply = service.send(
                args.message or "",
                conversation_id=args.conversation,
                model_id=args.model,
                strategy=args.strategy,
                manual_ids=manual_ids,
                approved_proposal_id=args.proposal,
                system_prompt=args.system,
                stream_callback=(lambda piece: print(piece, end="", flush=True)) if args.stream else None,
                params=params,
            )
        except ProviderError as exc:
            return fail(f"{type(exc).__name__}: {exc.message}", EXIT_UNAVAILABLE)
        if args.json:
            emit_json(reply.to_dict())
        else:
            if args.stream:
                emit()
            else:
                emit(reply.text)
            emit()
            emit(
                f"[model {reply.model['name']} ({reply.model['provider']})"
                f"{' SIMULATED' if reply.simulated else ''} | "
                f"{reply.latency_ms:.0f}ms | context {reply.manifest.tokens_used}/{reply.manifest.budget} tokens"
                f" | strategy {reply.manifest.strategy}]"
            )
            for warning in reply.warnings:
                emit(f"[warning] {warning}")
            if args.show_context:
                emit(json_text(reply.manifest.to_dict()))
        return EXIT_OK


def cmd_conv(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        command = args.conv_command
        if command == "list":
            conversations = ws.conversations.list_conversations()
            if args.json:
                emit_json([c.to_dict() for c in conversations])
            else:
                if not conversations:
                    emit("no conversations yet")
                else:
                    emit(
                        table(
                            [[c.id, c.title[:40], c.updated_at, c.project_id or "-"] for c in conversations],
                            ["id", "title", "updated", "project"],
                        )
                    )
            return EXIT_OK
        if command == "new":
            conv = ws.conversations.create(args.title)
            emit(f"created conversation {conv.id} ({conv.title})")
            return EXIT_OK
        if command == "show":
            conv = ws.conversations.require(args.conversation)
            messages = ws.conversations.messages(conv.id, include_excluded=True)
            if args.json:
                emit_json({"conversation": conv.to_dict(), "messages": [m.to_dict() for m in messages]})
            else:
                emit(f"{conv.title}   ({conv.id})")
                emit(f"created {conv.created_at}   updated {conv.updated_at}   messages {len(messages)}")
                for message in messages:
                    flag = " [hidden]" if message.excluded else (" [pinned]" if message.pinned else "")
                    emit(f"\n{message.seq:>3} {message.role}{flag}: {message.content[:500]}")
            return EXIT_OK
        if command == "search":
            hits = ws.conversations.search(args.query)
            if args.json:
                emit_json(hits)
            else:
                if not hits:
                    emit(f"no conversations match {args.query!r}")
                for hit in hits:
                    emit(f"{hit['conversation_id']}  {hit['title'][:40]}  ({hit['matched']})")
                    emit(f"    {hit['excerpt']}")
            return EXIT_OK
        if command == "rename":
            conv = ws.conversations.rename(args.conversation, args.title)
            emit(f"renamed to {conv.title}")
            return EXIT_OK
        if command == "delete":
            if args.hard and not args.yes:
                return fail("hard delete removes messages; re-run with --yes to confirm", EXIT_USAGE)
            result = ws.conversations.delete(args.conversation, hard=args.hard, confirm=args.yes)
            emit(f"{args.conversation}: {result}")
            return EXIT_OK
        if command == "restore":
            conv = ws.conversations.restore(args.conversation)
            emit(f"restored {conv.title}")
            return EXIT_OK
        if command == "clear":
            hidden = ws.conversations.clear_context(args.conversation)
            emit(f"hid {hidden} message(s) from the active context (history preserved)")
            return EXIT_OK
        if command == "export":
            text = ws.conversations.export(args.conversation, fmt=args.format)
            if args.out:
                Path(args.out).write_text(text)
                emit(f"wrote {args.out}")
            else:
                emit(text)
            return EXIT_OK
    return EXIT_USAGE


def cmd_memory(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        command = args.memory_command
        manager = ws.memory
        if command == "history":
            rows = manager.history(args.memory)
            emit_json(rows) if args.json else (
                emit(table([[r["version"], r["change"], r["changed_at"]] for r in rows],
                           ["version", "change", "changed_at"])) if rows else emit("no history")
            )
            return EXIT_OK
        if command == "add":
            details = {}
            if args.problem:
                details["problem"] = args.problem
            if args.solution:
                details["solution"] = args.solution
            if args.topic:
                details["topic"] = args.topic
            if args.evidence:
                details["evidence"] = [args.evidence]
            if args.outcome:
                details["outcome"] = args.outcome
            result = manager.add(
                args.kind,
                args.title,
                args.content,
                category=args.category,
                project_id=args.project,
                conversation_id=args.conversation,
                task_id=args.task,
                tags=[t.strip() for t in (args.tags or "").split(",") if t.strip()],
                pinned=args.pinned,
                slot=args.slot,
                verification=args.verification,
                details=details or None,
                evidence=[args.evidence] if args.evidence else None,
                environment=args.environment,
                limitations=args.limitations,
                allow_duplicate=args.allow_duplicate,
                source=args.source,
                provenance={"origin": args.provenance_origin} if args.provenance_origin else None,
                confidence=args.confidence,
            )
            if result.is_err:
                return fail(f"{result.error.message}")
            memory = result.value
            if args.json:
                emit_json(memory.to_dict())
            else:
                emit(f"stored {memory.kind} memory {memory.id}")
                emit(f"  scope     {memory.scope}" + (f" ({memory.scope_id})" if memory.scope_id else ""))
                emit(f"  category  {memory.category}")
                if memory.slot:
                    emit(f"  slot      {memory.slot}")
            return EXIT_OK
        if command == "list":
            memories = manager.list(
                kinds=args.kind,
                project_id=args.project,
                conversation_id=args.conversation,
                status=args.status,
                limit=args.limit,
            )
            if args.json:
                emit_json([m.to_dict() for m in memories])
            else:
                if not memories:
                    emit("no memories")
                else:
                    emit(
                        table(
                            [[m.id, m.kind, m.category, m.title[:40], m.status, m.created_at[:19]] for m in memories],
                            ["id", "kind", "category", "title", "status", "created"],
                        )
                    )
            return EXIT_OK
        if command == "show":
            result = manager.get(args.memory, include_deleted=True)
            if result.is_err:
                return fail(result.error.message)
            memory = result.value
            if args.json:
                data = memory.to_dict()
                data["history"] = manager.history(memory.id)
                data["sources"] = manager.sources(memory.id)
                emit_json(data)
            else:
                emit(f"{memory.title}   ({memory.id})")
                emit(f"  kind        {memory.kind}")
                emit(f"  scope       {memory.scope}" + (f" ({memory.scope_id})" if memory.scope_id else ""))
                emit(f"  category    {memory.category}")
                emit(f"  status      {memory.status}")
                emit(f"  source      {memory.source}")
                emit(f"  provenance  {json_text(memory.provenance)}")
                emit(f"  created     {memory.created_at}   updated {memory.updated_at}   version {memory.version}")
                if memory.verification:
                    emit(f"  verification {memory.verification}")
                if memory.limitations:
                    emit(f"  limitations {memory.limitations}")
                if memory.artifact_path:
                    emit(f"  artifact    {memory.artifact_path}")
                emit(f"  content     {memory.content}")
                sources = manager.sources(memory.id)
                if sources:
                    emit("  sources")
                    for src in sources:
                        emit(f"    {src['source_type']}: {src['reference'] or ''} {src['retrieved_at']}")
                history = manager.history(memory.id)
                if history:
                    emit("  history")
                    for entry in history:
                        emit(f"    v{entry['version']} {entry['change']} at {entry['changed_at']}")
            return EXIT_OK
        if command == "search":
            outcome = manager.search(args.query, kinds=args.kind, limit=args.limit)
            if args.json:
                emit_json(
                    {
                        "mode": outcome.mode,
                        "degraded": outcome.degraded,
                        "degraded_reason": outcome.degraded_reason,
                        "hits": [
                            {"memory": h.memory.to_dict(), "score": h.score, "reason": h.reason} for h in outcome.hits
                        ],
                    }
                )
            else:
                if outcome.degraded:
                    emit(f"[degraded] {outcome.degraded_reason}")
                if not outcome.hits:
                    emit(f"no memories match {args.query!r}")
                for hit in outcome.hits:
                    emit(f"{hit.score:6.2f}  {hit.memory.kind:<9} {hit.memory.title[:50]}")
                    emit(f"        {hit.memory.id}  ({hit.reason})")
            return EXIT_OK
        if command == "edit":
            fields: dict[str, Any] = {}
            if args.title is not None:
                fields["title"] = args.title
            if args.content is not None:
                fields["content"] = args.content
            if args.verification is not None:
                fields["verification"] = args.verification
            if args.pinned:
                fields["pinned"] = True
            if args.status is not None:
                fields["status"] = args.status
            if not fields:
                return fail("nothing to change; pass --title/--content/--verification/--pinned/--status")
            updated = manager.update(args.memory, **fields)
            emit(f"updated {updated.id} to version {updated.version}")
            return EXIT_OK
        if command == "delete":
            if args.hard and not args.yes:
                return fail("hard delete is irreversible; re-run with --yes", EXIT_USAGE)
            emit(f"{args.memory}: {manager.delete(args.memory, hard=args.hard)}")
            return EXIT_OK
        if command == "retrieve":
            result = manager.retrieve_for_context(
                budget_tokens=args.budget,
                conversation_id=args.conversation,
                project_id=args.project,
                query=args.query,
                include_archival=args.include_archival,
            )
            if args.json:
                emit_json(result.to_dict())
            else:
                emit(f"budget {result.budget} tokens, used {result.tokens_used}")
                if result.degraded:
                    emit(f"[degraded] {result.notes}")
                for item in result.included:
                    emit(f"  + {item['kind']:<9} {item['title'][:50]}  ({item['tokens']}t) - {item['reason']}")
                for item in result.omitted:
                    emit(f"  - {item.get('kind')} {item.get('ref_id')}  ({item.get('tokens')}t) - {item.get('reason')}")
            return EXIT_OK
        if command == "profile":
            profile = manager.learner_profile(args.learner)
            emit_json(profile) if args.json else emit(json_text(profile))
            return EXIT_OK
        if command == "policy":
            policy = MemoryManager.policy()
            if args.json:
                emit_json(policy)
            else:
                for kind, entry in policy.items():
                    emit(f"{kind}")
                    emit(f"  purpose   {entry['purpose']}")
                    emit(f"  scope     {', '.join(entry['scope'])}")
                    emit(f"  injected  {entry['injected']}")
                    emit(f"  lifetime  {entry['lifetime']}")
                    emit(f"  requires  {', '.join(entry['requires'])}")
                    emit("")
            return EXIT_OK
        if command == "stats":
            stats = manager.stats()
            emit_json(stats) if args.json else emit(json_text(stats))
            return EXIT_OK
        if command == "retention":
            counts = manager.apply_retention(archival_retention_days=args.archival_days)
            emit_json(counts) if args.json else emit(json_text(counts))
            return EXIT_OK
    return EXIT_USAGE


def cmd_providers(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.providers
        command = args.provider_command
        if command == "catalogue":
            rows = manager.catalogue()
            emit_json(rows) if args.json else emit(
                table([[r["slug"], r["kind"], "yes" if r["is_local"] else "no", r["base_url"] or "-"] for r in rows],
                      ["template", "kind", "local", "base_url"])
            )
            return EXIT_OK
        if command == "list":
            rows = [p.to_dict() for p in manager.list(kind=args.kind)]
            emit_json(rows) if args.json else (
                emit(table([[r["id"], r["name"], r["kind"], "local" if r["is_local"] else "cloud",
                             "consented" if r["consented"] else ("n/a" if not r["requires_consent"] else "no consent"),
                             r["blocking_reason"] or "usable"] for r in rows],
                           ["id", "name", "kind", "scope", "consent", "state"])) if rows
                else emit("no providers registered")
            )
            return EXIT_OK
        if command == "add":
            result = manager.add(
                args.name,
                template=args.template,
                kind=args.kind,
                api_style=args.api_style,
                base_url=args.base_url,
                model_family=args.model_family,
                auth_ref=args.auth_ref,
                is_local=True if args.local else None,
                notes=args.notes,
                price_in_per_1k=args.price_in,
                price_out_per_1k=args.price_out,
                currency=args.currency,
            )
            if result.is_err:
                return fail(result.error.message, EXIT_USAGE)
            data = result.value.to_dict()
            if args.json:
                emit_json(data)
            else:
                emit(f"registered provider {data['id']}  {data['name']} "
                     f"({'on this machine' if data['is_local'] else 'remote'}, {data['kind']})")
                if data["blocking_reason"]:
                    emit(f"  not usable yet: {data['blocking_reason']}")
            return EXIT_OK
        if command == "show":
            result = manager.get(args.provider)
            if result.is_err:
                return fail(result.error.message)
            data = result.value.to_dict()
            emit_json(data) if args.json else emit(json_text(data))
            return EXIT_OK
        if command == "confirm":
            result = manager.confirm_privacy(
                args.provider,
                data_leaves_device=args.data_leaves_device == "yes",
                training_use=args.training_use,
                retention=args.retention,
                region=args.region,
            )
            if result.is_err:
                return fail(result.error.message, EXIT_USAGE)
            emit_json(result.value.to_dict()) if args.json else emit(
                f"privacy terms recorded for {result.value.name}: data_leaves_device="
                f"{result.value.data_leaves_device}; training_use={args.training_use}; "
                f"retention={args.retention}"
            )
            return EXIT_OK
        if command == "consent":
            result = manager.consent(args.provider, note=args.note)
            if result.is_err:
                return fail(result.error.message, EXIT_USAGE)
            emit_json(result.value.to_dict()) if args.json else emit(
                f"consent recorded for {result.value.name} (version {result.value.consent_version})"
            )
            return EXIT_OK
        if command == "revoke":
            result = manager.revoke_consent(args.provider)
            if result.is_err:
                return fail(result.error.message)
            emit(f"consent revoked for {result.value.name}: no request will be sent until you consent again")
            return EXIT_OK
        if command in ("enable", "disable"):
            result = manager.enable(args.provider, enabled=command == "enable")
            if result.is_err:
                return fail(result.error.message)
            emit_json(result.value.to_dict()) if args.json else emit(
                f"{result.value.name} {'enabled' if result.value.enabled else 'disabled'}"
            )
            return EXIT_OK
        if command == "check":
            result = manager.check(args.provider, timeout=args.timeout)
            if result.is_err:
                return fail(result.error.message)
            data = result.value
            if args.json:
                emit_json(data)
            else:
                emit(f"{data['status']}  ({data['detail']})")
                if data.get("latency_ms") is not None:
                    emit(f"  latency {data['latency_ms']} ms")
                if data.get("models_seen") is not None:
                    emit(f"  models seen {data['models_seen']}")
                emit("  note: this probes the models endpoint; it never sends prompt content")
            return EXIT_OK if data["status"] in ("reachable", "model_missing") else EXIT_DEGRADED
        if command == "quota":
            if args.requests_per_day is None and args.tokens_per_day is None:
                existing = manager.get(args.provider)
                if existing.is_err:
                    return fail(existing.error.message)
                emit_json(existing.value.quotas) if args.json else emit(json_text(existing.value.quotas) if existing.value.quotas else "no quota declared")
                return EXIT_OK
            result = manager.set_quota(
                args.provider,
                max_requests_per_day=args.requests_per_day,
                max_tokens_per_day=args.tokens_per_day,
            )
            if result.is_err:
                return fail(result.error.message)
            emit_json(result.value.quotas) if args.json else emit(
                f"quota for {result.value.name}: {result.value.quotas}"
            )
            return EXIT_OK
        if command == "usage":
            if args.provider:
                result = manager.get(args.provider)
                if result.is_err:
                    return fail(result.error.message)
                data = manager.usage(result.value.id, days=args.days)
                if args.by_day:
                    data = {"summary": data, "daily": manager.usage_by_day(result.value.id, days=args.days)}
                emit_json(data) if args.json else emit(json_text(data))
                return EXIT_OK
            rows = [
                {"provider": p.name, **manager.usage(p.id, days=args.days)} for p in manager.list()
            ]
            emit_json(rows) if args.json else (
                emit(table([[r["provider"], r["requests"], r["tokens_in"], r["tokens_out"], r["errors"],
                             r["estimated_cost"] if r["estimated_cost"] is not None else "-"] for r in rows],
                           ["provider", "requests", "tokens_in", "tokens_out", "errors", "est. cost"]))
                if rows else emit("no providers registered")
            )
            return EXIT_OK
        if command == "privacy":
            rows = manager.privacy_report()
            def leaves_cell(row):
                value = row["data_leaves_device"]
                label = "yes" if value else ("no" if value is False else "unknown")
                source = row["effective_privacy"]["sources"].get("data_leaves_device")
                if source == "user-confirmed":
                    return f"{label} (you confirmed)"
                if source and source.startswith("derived"):
                    return f"{label} (from URL)"
                if source:
                    return f"{label} (vendor claim)"
                return label

            emit_json(rows) if args.json else (
                emit(table([[r["name"], r["kind"], "yes" if r["is_local"] else "no", leaves_cell(r),
                             "yes" if r["consented"] else "no",
                             r["blocking_reason"] or "usable"] for r in rows],
                           ["provider", "kind", "local", "leaves device", "consent", "state"]))
                if rows else emit("no providers registered")
            )
            return EXIT_OK
        if command == "remove":
            result = manager.remove(args.provider)
            if result.is_err:
                return fail(result.error.message)
            emit(f"removed provider {result.value}")
            return EXIT_OK
        if command == "stats":
            data = manager.stats()
            emit_json(data) if args.json else emit(json_text(data))
            return EXIT_OK
    return EXIT_USAGE


def cmd_projects(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.projects
        command = args.project_command
        if command == "create":
            project = manager.create(args.name, root_path=args.path, description=args.description)
            emit_json(project.to_dict()) if args.json else emit(
                f"created project {project.id}  {project.name}" + (f"  ({project.path})" if project.path else "")
            )
            return EXIT_OK
        if command == "list":
            rows = [p.to_dict() for p in manager.list(include_archived=False)]
            emit_json(rows) if args.json else (
                emit(table([[r["id"], r["name"], r["path"] or "-", r["created_at"]] for r in rows],
                           ["id", "name", "path", "created"])) if rows else emit("no projects")
            )
            return EXIT_OK
        if command == "show":
            result = manager.get(args.project)
            if result.is_err:
                return fail(result.error.message)
            emit_json(result.value.to_dict()) if args.json else emit(json_text(result.value.to_dict()))
            return EXIT_OK
        if command == "rename":
            result = manager.rename(args.project, args.name)
            if result.is_err:
                return fail(result.error.message)
            emit_json(result.value.to_dict()) if args.json else emit(f"renamed {result.value.id} -> {result.value.name}")
            return EXIT_OK
        if command == "archive":
            result = manager.archive(args.project)
            if result.is_err:
                return fail(result.error.message)
            emit(f"archived {args.project} (memory and history are preserved)")
            return EXIT_OK
        if command == "link":
            result = ws.conversations.attach_project(args.conversation, args.project)
            if result.is_err:
                return fail(result.error.message)
            emit(f"linked conversation {args.conversation} to project {args.project}")
            return EXIT_OK
    return EXIT_USAGE


def cmd_context(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.context
        if args.context_command == "build":
            manual_ids = [x.strip() for x in (args.manual_ids or "").split(",") if x.strip()] or None
            if args.strategy in ("summarize", "ai_proposed"):
                record = ws.resolve_model(task="chat")
                service = ws.chat
                manager.summarizer = service.summarizer_for(record)
                runtime = ws.runtime_for(record)
                manager.summary_generator = (
                    "simulated-test-double" if getattr(runtime, "simulated", False) else "model"
                )
            manifest = manager.build(
                args.conversation,
                strategy=args.strategy,
                user_message=args.message,
                budget_tokens=args.budget,
                manual_ids=manual_ids,
                approved_proposal_id=args.proposal,
            )
            if args.json:
                emit_json(manifest.to_dict())
            else:
                emit(f"manifest {manifest.id}  strategy={manifest.strategy}")
                emit(f"budget {manifest.budget}  used {manifest.tokens_used}  memory {manifest.memory_tokens}")
                if manifest.degraded:
                    emit(f"[degraded] {manifest.notes}")
                emit("included:")
                for item in manifest.included:
                    emit(f"  + {item.kind:<8} {item.ref_id[:22]:<22} {item.tokens:>4}t  {item.reason[:50]}")
                if manifest.omitted:
                    emit("omitted:")
                    for item in manifest.omitted:
                        emit(f"  - {item.get('kind','-'):<8} {str(item.get('ref_id'))[:22]:<22} {item.get('tokens','?')}t  {item.get('reason','')[:50]}")
            return EXIT_OK
        if args.context_command == "propose":
            proposal = manager.propose(args.conversation, budget_tokens=args.budget)
            data = proposal.to_dict()
            data["note"] = "nothing was applied; approve by building with --proposal <id>"
            if args.json:
                emit_json(data)
            else:
                emit(json_text(data))
                emit("(nothing was applied; approve by building with --proposal <id>)")
            return EXIT_OK
        if args.context_command == "reject":
            manager.reject_proposal(args.proposal, reason=args.reason)
            emit(f"proposal {args.proposal} rejected: {args.reason} (history unchanged)")
            return EXIT_OK
        if args.context_command == "proposals":
            rows = manager.proposals(args.conversation)
            emit_json(rows) if args.json else emit(json_text(rows))
            return EXIT_OK
        if args.context_command == "manifests":
            rows = manager.manifests(args.conversation)
            emit_json(rows) if args.json else emit(
                table([[r["id"], r["strategy"], r["tokens_used"], r["token_budget"], r["created_at"]] for r in rows],
                      ["id", "strategy", "used", "budget", "created"])
            ) if rows else emit("no manifests")
            return EXIT_OK
        if args.context_command == "summaries":
            rows = [s.to_dict() for s in manager.summaries(args.conversation)]
            emit_json(rows) if args.json else emit(json_text(rows))
            return EXIT_OK
        if args.context_command == "show":
            result = manager.manifest(args.manifest)
            if result.is_err:
                return fail(result.error.message)
            emit_json(result.value) if args.json else emit(json_text(result.value))
            return EXIT_OK
    return EXIT_USAGE


def cmd_embeddings(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.embeddings
        if manager is None:
            return fail("no embedding subsystem is configured", EXIT_UNAVAILABLE)
        command = args.embedding_command
        if command == "status":
            data = manager.status()
            data["memory"] = ws.memory.stats()["embedding_states"]
            data["enabled"] = data.get("provider") is not None
            data["hint"] = (
                "enable with: archx-agent config set memory.embeddings_enabled true"
                if not data["enabled"]
                else "disable with: archx-agent config set memory.embeddings_enabled false"
            )
            if args.json:
                emit_json(data)
            else:
                provider = data["provider"]
                if provider is None:
                    emit("embedding provider: none configured")
                    emit("  enable with: archx-agent config set memory.embeddings_enabled true")
                    emit("  (local-hash is the offline default; it is lexical, not semantic)")
                else:
                    emit(
                        f"provider {provider['id']} model={provider['model_id']} dim={provider['dim']} "
                        f"semantic={provider['semantic']} local={provider['local']}"
                    )
                emit(f"states           {data['states']}")
                emit(f"stale vectors    {data['stale_vectors']}")
                emit(f"threshold        {data['threshold']}")
            return EXIT_OK
        if command == "backfill":
            result = manager.backfill(limit=args.limit)
            emit_json(result) if args.json else emit(json_text(result))
            return EXIT_OK
        if command == "embed-conversation":
            result = manager.embed_conversation(args.conversation)
            emit_json(result) if args.json else emit(json_text(result))
            return EXIT_OK
        if command == "search":
            if manager.provider is None:
                return fail(
                    "embedding search needs a provider; embeddings are disabled "
                    "(enable with: archx-agent config set memory.embeddings_enabled true)",
                    EXIT_UNAVAILABLE,
                )
            found = manager.search(
                args.query, owner_types=("memory",), k=args.k, threshold=args.threshold
            )
            if args.json:
                emit_json(
                    {
                        "degraded": found.degraded,
                        "degraded_reason": found.degraded_reason,
                        "model_id": found.model_id,
                        "scanned": found.scanned,
                        "results": [n.to_dict() for n in found.neighbours],
                    }
                )
            else:
                if found.degraded:
                    emit(f"[degraded] {found.degraded_reason}")
                emit(f"scanned {found.scanned} vector(s) with {found.model_id or 'no model'}")
                for neighbour in found.neighbours:
                    memory = ws.memory.get(neighbour.owner_id)
                    title = memory.value.title if memory.is_ok else "(missing)"
                    emit(f"  {neighbour.score:.3f}  {title[:60]}  {neighbour.owner_id}")
            return EXIT_OK
        if command == "purge":
            if not args.yes:
                return fail("purging vectors is irreversible; re-run with --yes", EXIT_USAGE)
            removed = manager.purge(model_id=args.model)
            payload = {"deleted": removed, "model_id": args.model}
            emit_json(payload) if args.json else emit(f"removed {removed} vector(s)")
            return EXIT_OK
    return EXIT_USAGE


def cmd_eval(args: argparse.Namespace) -> int:
    from archx_agent.application.retrieval_eval import load_dataset, render_markdown, run_evaluation

    if args.eval_command != "retrieval":
        return EXIT_USAGE
    dataset_path = args.dataset
    if not Path(dataset_path).exists():
        candidate = Path(__file__).resolve().parents[4] / dataset_path
        if candidate.exists():
            dataset_path = str(candidate)
        else:
            return fail(f"dataset not found: {args.dataset}")
    dataset = load_dataset(dataset_path)
    if args.no_scratch:
        with _workspace(args) as ws:
            report = run_evaluation(dataset, memory=ws.memory, embeddings=ws.embeddings, k=args.k)
    else:
        import tempfile

        scratch = tempfile.mkdtemp(prefix="archx-eval-")
        overrides = {"memory.embeddings_enabled": True, "memory.embedding_provider": "local-hash"}
        with open_workspace(home=scratch, overrides=overrides) as ws:
            report = run_evaluation(dataset, memory=ws.memory, embeddings=ws.embeddings, k=args.k)
        report["scratch_home"] = scratch
    report["dataset_path"] = dataset_path
    markdown = render_markdown(report)
    if args.out:
        Path(args.out).write_text(markdown + "\n")
        emit(f"wrote {args.out}")
    if args.json:
        emit_json(report)
    else:
        emit(markdown)
    return EXIT_OK


def _parse_tool_args(pairs: Sequence[str] | None) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValidationError(f"--arg expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise ValidationError(f"--arg expects a name before '=', got {pair!r}")
        if key in args:
            raise ValidationError(f"--arg {key} given twice")
        args[key] = value
    return args


def _execute_tool(ws, manager, name: str, arguments: dict[str, Any], args: argparse.Namespace) -> int:
    """Run one tool through the registry and report the outcome consistently."""
    from archx_agent.managers.tools import ToolContext

    context = ToolContext(
        conversation_id=getattr(args, "conversation", None),
        task_id=getattr(args, "task", None),
        project_id=getattr(args, "project", None),
        purpose=getattr(args, "purpose", None) or "",
    )
    try:
        run = manager.execute(
            name,
            arguments,
            dry_run=bool(getattr(args, "dry_run", False)),
            context=context,
            requester="cli",
        )
    except (PermissionDeniedError, ToolError, ArchxError) as exc:
        payload = {
            "tool": name,
            "status": "denied" if isinstance(exc, PermissionDeniedError) else "error",
            "error": exc.message,
            "approval_id": getattr(exc, "approval_id", None),
            "capability": getattr(exc, "capability", None),
            "run": getattr(exc, "run", None).to_dict() if getattr(exc, "run", None) else None,
        }
        if args.json:
            emit_json(payload)
        else:
            print(f"{payload['status']}: {exc.message}", file=sys.stderr)
            if payload["approval_id"]:
                print(
                    f"approve with: archx-agent approvals approve {payload['approval_id']}",
                    file=sys.stderr,
                )
        if isinstance(exc, PermissionDeniedError):
            return EXIT_DENIED
        if isinstance(exc, PathEscapesRootError):
            return EXIT_DENIED
        if isinstance(exc, ToolValidationError):
            return EXIT_USAGE
        if isinstance(exc, ToolError):
            return EXIT_ERROR
        return EXIT_USAGE
    data = run.to_dict()
    if args.json:
        emit_json(data)
    else:
        if run.dry_run:
            emit("[dry run] nothing was changed on disk")
        emit(f"{run.tool} {run.status} in {run.duration_ms}ms  (run {run.id})")
        if run.result:
            emit_json(run.result)
        if run.error:
            emit(f"error: {run.error}")
    return EXIT_OK if run.ok else EXIT_ERROR


def cmd_tools(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.tools
        if manager is None:
            return fail("no tool registry is available in this workspace", EXIT_UNAVAILABLE)
        command = args.tools_command
        if command == "list":
            rows = manager.registry()
            if args.json:
                emit_json(rows)
            else:
                emit(
                    table(
                        [
                            [
                                row["name"],
                                row["capability"] or "-",
                                row["risk"],
                                "yes" if row["supports_dry_run"] else "no",
                                "-" if row["active_grants"] is None else str(row["active_grants"]),
                                row["summary"][:44],
                            ]
                            for row in rows
                        ],
                        ["tool", "capability", "risk", "dry-run", "grants", "what it does"],
                    )
                )
                emit("")
                emit(
                    "a tool with capability '-' needs no permission; every other tool needs a "
                    "grant or an approved request"
                )
            return EXIT_OK
        if command == "show":
            spec = manager.spec(args.tool)
            data = spec.to_dict()
            data["roots"] = ws.tool_roots()
            data["recent_runs"] = manager.runs(tool=spec.name, limit=5)
            if spec.capability:
                data["grants"] = [g.to_dict() for g in ws.permissions.grants(capability=spec.capability)]
            if args.json:
                emit_json(data)
            else:
                emit(f"{spec.name}  risk={spec.risk}  capability={spec.capability or '(none)'}")
                emit(f"  {spec.summary}")
                emit(f"  side effects: {spec.side_effects}   dry run: {'yes' if spec.supports_dry_run else 'no'}")
                if spec.inputs:
                    emit("  inputs:")
                    for name, description in spec.inputs.items():
                        mark = "*" if name in spec.required else " "
                        emit(f"   {mark} {name:<16} {description}")
                emit(f"  roots: {', '.join(str(r) for r in data['roots'])}")
                if data.get("grants"):
                    emit("  grants:")
                    for grant in data["grants"]:
                        emit(f"   {grant['id']}  {grant['scope']}  by {grant['granted_by']}")
                else:
                    emit("  grants: none")
            return EXIT_OK
        if command == "run":
            arguments = _parse_tool_args(args.arg)
            return _execute_tool(ws, manager, args.tool, arguments, args)
        if command == "runs":
            rows = manager.runs(tool=args.tool, limit=args.limit)
            if args.json:
                emit_json(rows)
            else:
                if not rows:
                    emit("no tool runs")
                else:
                    emit(
                        table(
                            [
                                [
                                    row.get("seq"),
                                    row["started_at"][11:19],
                                    row["tool_name"],
                                    row["status"],
                                    "dry" if row["dry_run"] else "",
                                    (row.get("error") or "")[:44],
                                ]
                                for row in rows
                            ],
                            ["seq", "time", "tool", "status", "dry", "error"],
                        )
                    )
            return EXIT_OK
    return EXIT_USAGE


def cmd_permissions(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.permissions
        if manager is None:
            return fail("no permission centre is available in this workspace", EXIT_UNAVAILABLE)
        command = args.permissions_command
        if command == "capabilities":
            rows = manager.capabilities()
            emit_json(rows) if args.json else emit(
                table([[r["name"], r["risk"], r["effect"], r["description"]] for r in rows],
                      ["capability", "risk", "effect", "meaning"])
            )
            return EXIT_OK
        if command == "list":
            grants = manager.grants(
                capability=args.capability,
                subject=args.subject,
                include_revoked=args.all,
            )
            if args.json:
                emit_json([g.to_dict() for g in grants])
            else:
                if not grants:
                    emit("no grants")
                else:
                    emit(
                        table(
                            [
                                [g.id, g.capability, g.subject, g.scope,
                                 g.expires_at or "-", g.use_count,
                                 "revoked" if g.revoked_at else "active"]
                                for g in grants
                            ],
                            ["grant", "capability", "subject", "scope", "expires", "uses", "state"],
                        )
                    )
            return EXIT_OK
        if command == "grant":
            grant = manager.grant(
                args.capability,
                subject=args.subject,
                duration=args.duration,
                reason=args.reason or "",
                conversation_id=args.conversation,
                task_id=args.task,
                project_id=args.project,
                hours=args.for_hours,
                confirm=args.confirm,
            )
            if args.json:
                emit_json(grant.to_dict())
            else:
                emit(f"granted {grant.summary}  (id {grant.id}, by {grant.granted_by})")
                if grant.notes:
                    emit(f"note: {grant.notes}")
                if grant.expires_at:
                    emit(f"expires {grant.expires_at}")
            return EXIT_OK
        if command == "revoke":
            grant = manager.revoke(args.grant, reason=args.reason or "")
            emit_json(grant.to_dict()) if args.json else emit(f"revoked {grant.id} ({grant.capability})")
            return EXIT_OK
        if command == "check":
            decision = manager.check(
                args.capability,
                subject=args.subject,
                conversation_id=args.conversation,
                task_id=args.task,
                project_id=args.project,
                consume=False,
                purpose="permissions check",
                request_approval_on_denial=False,
            )
            if args.json:
                emit_json(decision.to_dict())
            else:
                emit(f"{'allowed' if decision.allowed else 'denied'}: {decision.reason}")
            return EXIT_OK if decision.allowed else EXIT_DENIED
        if command == "prune":
            count = manager.prune_expired()
            emit_json({"revoked": count}) if args.json else emit(f"revoked {count} expired grant(s)")
            return EXIT_OK
    return EXIT_USAGE


def cmd_approvals(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.permissions
        if manager is None:
            return fail("no permission centre is available in this workspace", EXIT_UNAVAILABLE)
        command = args.approvals_command
        if command == "list":
            if args.status:
                rows = manager.approvals(status=args.status, limit=args.limit)
            else:
                rows = manager.pending(limit=args.limit)
            if args.json:
                emit_json([a.to_dict() for a in rows])
            else:
                if not rows:
                    emit("nothing waiting for approval")
                else:
                    emit(
                        table(
                            [
                                [a.id, a.capability, a.subject, a.scope,
                                 a.expires_at or "-", (a.purpose or "")[:36]]
                                for a in rows
                            ],
                            ["approval", "capability", "subject", "scope", "expires", "purpose"],
                        )
                    )
                    emit("")
                    emit("approve with: archx-agent approvals approve <approval>")
            return EXIT_OK
        if command == "show":
            approval = manager.get_approval(args.approval)
            if approval.is_err:
                return fail(approval.error.message)
            emit_json(approval.value.to_dict()) if args.json else emit(json_text(approval.value.to_dict()))
            return EXIT_OK
        if command == "approve":
            try:
                approval, grant = manager.approve(
                    args.approval, reason=args.reason or "", hours=args.for_hours
                )
            except ValidationError as exc:
                return fail(exc.message, EXIT_USAGE)
            if args.json:
                emit_json({"approval": approval.to_dict(), "grant": grant.to_dict()})
            else:
                emit(f"approved {approval.id}: {grant.summary}")
                emit(f"grant {grant.id} ({grant.scope}); re-run the operation to use it")
            return EXIT_OK
        if command == "deny":
            try:
                approval = manager.deny(args.approval, reason=args.reason or "denied by the user")
            except ValidationError as exc:
                return fail(exc.message, EXIT_USAGE)
            emit_json(approval.to_dict()) if args.json else emit(
                f"denied {approval.id} ({approval.capability}); no grant was created"
            )
            return EXIT_OK
    return EXIT_USAGE


def _pairs(pairs: Sequence[str] | None, *, flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValidationError(f"{flag} expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        out[key.strip()] = value
    return out


def cmd_mcp(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.mcp
        command = getattr(args, "mcp_command", None)
        if command in ("servers", "list"):
            rows = manager.status()
            if args.json:
                emit_json(rows)
            else:
                if not rows:
                    emit("no MCP servers configured")
                else:
                    emit(
                        table(
                            [
                                [r["name"], r["transport"], "yes" if r["trusted"] else "no",
                                 "yes" if r["enabled"] else "no", r["tools"], r["registered"],
                                 r["last_status"] or "-"]
                                for r in rows
                            ],
                            ["server", "transport", "trusted", "enabled", "tools", "callable", "status"],
                        )
                    )
                    emit("")
                    emit("a discovered tool only becomes callable when the server is trusted AND enabled,"
                         " and every call still needs an mcp.call grant")
            return EXIT_OK
        if command == "add":
            server = manager.add_server(
                args.name,
                transport=args.transport,
                command=args.server_command,
                args=list(args.arg or []),
                url=args.url,
                env=_pairs(args.env, flag="--env"),
                headers=_pairs(args.header, flag="--header"),
                enabled=args.enable,
                trusted=args.trust,
            )
            if args.json:
                emit_json(server.to_dict())
            else:
                emit(f"added MCP server {server.name} ({server.transport}) id {server.id}")
                emit(f"  trusted={server.trusted} enabled={server.enabled}")
                emit(f"  next: archx-agent mcp sync {server.name}")
            return EXIT_OK
        if command == "show":
            server = manager.server(args.server)
            data = server.to_dict()
            data["tools"] = manager.tools_of(server.id)
            emit_json(data) if args.json else emit(json_text(data))
            return EXIT_OK
        if command in ("enable", "disable"):
            server = manager.enable(args.server, enabled=command == "enable")
            emit_json(server.to_dict()) if args.json else emit(
                f"{server.name}: enabled={server.enabled}"
                + ("" if server.enabled and server.trusted else " (no tools are callable until it is trusted too)")
            )
            return EXIT_OK
        if command in ("trust", "untrust"):
            server = manager.trust(args.server, trusted=command == "trust")
            if args.json:
                emit_json(server.to_dict())
            else:
                emit(f"{server.name}: trusted={server.trusted}")
                if not server.trusted:
                    emit("its tools were unregistered; nothing it advertises can run")
            return EXIT_OK
        if command == "remove":
            server = manager.remove_server(args.server)
            emit_json(server.to_dict()) if args.json else emit(f"removed MCP server {server.name}")
            return EXIT_OK
        if command == "sync":
            try:
                result = manager.sync(args.server)
            except ArchxError as exc:
                return fail(exc.message, EXIT_UNAVAILABLE)
            if args.json:
                emit_json(result)
            else:
                emit(f"{result['server']}: protocol {result['protocol_version']} "
                     f"({result['server_info'].get('name', '?')})")
                emit(f"discovered {len(result['discovered'])} tool(s)")
                for tool in result["discovered"]:
                    emit(f"  - {tool['name']:<20} {tool['description'][:50]}")
                if result["registered"]:
                    emit(f"registered {len(result['registered'])} callable tool(s): "
                         + ", ".join(result["registered"]))
                else:
                    emit(f"nothing registered: {result['reason']}")
            return EXIT_OK
        if command == "tools":
            rows = manager.tools_of(args.server)
            emit_json(rows) if args.json else emit(
                table([[r["name"], r["capability"], r["risk"], "yes" if r["enabled"] else "no",
                        (r["description"] or "")[:44]] for r in rows],
                      ["tool", "capability", "risk", "callable", "description"])
            ) if rows else emit("no tools discovered (run `archx-agent mcp sync <server>`)")
            return EXIT_OK
        if command == "call":
            arguments = _parse_tool_args(args.arg)
            server = manager.server(args.server)
            discovered = {row["name"] for row in manager.tools_of(server.id)}
            if args.tool not in discovered:
                return fail(
                    f"{server.name} does not expose {args.tool!r} "
                    f"(discovered: {', '.join(sorted(discovered)) or 'nothing - run mcp sync'})",
                    EXIT_USAGE,
                )
            name = manager.registered_tool_name(args.server, args.tool)
            return _execute_tool(ws, ws.tools, name, arguments, args)
        if command == "serve":
            from archx_agent.interfaces.mcp_server import ArchxMcpServer

            try:
                server = ArchxMcpServer(ws)
            except ArchxError as exc:
                return fail(exc.message, EXIT_USAGE)
            if args.transport == "stdio":
                print("serving MCP over stdio (pid %d)" % os.getpid(), file=sys.stderr)
                server.serve_stdio()
                return EXIT_OK
            httpd = server.serve_http(host=args.host, port=args.port)
            print(f"serving MCP over http on {args.host}:{httpd.server_port}", file=sys.stderr)
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                httpd.server_close()
            return EXIT_OK
    return EXIT_USAGE


def cmd_extensions(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.extensions
        command = args.extensions_command
        if command == "list":
            rows = manager.status()
            if args.json:
                emit_json(rows)
            else:
                if not rows:
                    emit("no extensions installed")
                else:
                    emit(
                        table(
                            [
                                [r["name"], r["version"], r["trust"],
                                 "yes" if r["enabled"] else "no", r["tool_count"], r["registered"]]
                                for r in rows
                            ],
                            ["extension", "version", "trust", "enabled", "tools", "registered"],
                        )
                    )
                    emit("")
                    emit("installing records the manifest; trusting and enabling are separate acts,"
                         " and every tool call still needs a grant")
            return EXIT_OK
        if command == "install":
            path = args.path
            if not Path(path).exists():
                candidate = ws.extensions_dir() / path
                if candidate.exists():
                    path = str(candidate)
            extension = manager.install(path, trust=args.trust, enable=args.enable)
            if args.json:
                emit_json(extension.to_dict())
            else:
                emit(f"installed {extension.name} {extension.version} (id {extension.id})")
                emit(f"  manifest sha256 {extension.manifest_hash}")
                emit(f"  trust={extension.trust} enabled={extension.enabled}")
                for tool in extension.manifest.get("tools") or []:
                    emit(f"  tool {tool['name']:<16} needs {tool['capability']} (risk {tool['risk']})")
                if not (extension.trusted and extension.enabled):
                    emit(f"  nothing is callable yet: archx-agent extensions trust {extension.name} "
                         f"&& archx-agent extensions enable {extension.name}")
            return EXIT_OK
        if command == "show":
            extension = manager.extension(args.extension)
            data = extension.to_dict()
            data["manifest"] = extension.manifest
            data["tool_rows"] = manager.tools_of(extension.id)
            emit_json(data) if args.json else emit(json_text(data))
            return EXIT_OK
        if command in ("trust", "untrust"):
            extension = manager.trust(args.extension, trusted=command == "trust")
            emit_json(extension.to_dict()) if args.json else emit(
                f"{extension.name}: trust={extension.trust}"
                + (" (tools registered)" if extension.trusted and extension.enabled
                   else " (nothing callable)")
            )
            return EXIT_OK
        if command in ("enable", "disable"):
            extension = manager.set_enabled(args.extension, enabled=command == "enable")
            emit_json(extension.to_dict()) if args.json else emit(
                f"{extension.name}: enabled={extension.enabled}"
                + (" (tools registered)" if extension.trusted and extension.enabled
                   else " (nothing callable)")
            )
            return EXIT_OK
        if command == "remove":
            extension = manager.remove(args.extension)
            emit_json(extension.to_dict()) if args.json else emit(
                f"removed extension {extension.name}"
            )
            return EXIT_OK
        if command == "tools":
            extension = manager.extension(args.extension)
            rows = manager.tools_of(extension.id)
            emit_json(rows) if args.json else emit(
                table([[r["name"], r["capability"], r["risk"], "yes" if r["enabled"] else "no",
                        (r["description"] or "")[:44]] for r in rows],
                      ["tool", "capability", "risk", "callable", "description"])
            ) if rows else emit("no tools recorded")
            return EXIT_OK
        if command == "call":
            arguments = _parse_tool_args(args.arg)
            extension = manager.extension(args.extension)
            name = manager.spec_name(extension.name, args.tool)
            return _execute_tool(ws, ws.tools, name, arguments, args)
    return EXIT_USAGE


def cmd_agent(args: argparse.Namespace) -> int:
    from archx_agent.application.agent import WorkflowFailed
    from archx_agent.managers.workflows import TEMPLATES

    with _workspace(args) as ws:
        manager = ws.workflows
        command = args.agent_command
        if command == "templates":
            rows = [
                {"name": name, "goal": definition.get("goal"), "steps": len(definition.get("steps") or [])}
                for name, definition in TEMPLATES.items()
            ]
            emit_json(rows) if args.json else emit(
                table([[r["name"], r["steps"], r["goal"]] for r in rows], ["template", "steps", "goal"])
            )
            return EXIT_OK
        if command == "plan":
            try:
                workflow = ws.agent.plan(args.goal, model_id=args.model, name=args.name)
            except ApprovalRequiredError:
                raise
            if args.json:
                emit_json(workflow.to_dict())
            else:
                emit(f"{workflow.id}  proposed  {workflow.name}  ({len(workflow.steps)} steps)")
                for index, step in enumerate(workflow.steps, start=1):
                    emit(f"  {index}. {step.kind:<10} {step.title}")
                emit("")
                emit(f"a model proposed this plan. Review it, then: archx-agent agent run {workflow.id} --approve")
            return EXIT_OK
        if command == "list":
            rows = manager.list(status=args.status, mode=args.mode, limit=args.limit)
            if args.json:
                emit_json([row.to_dict(with_definition=False) for row in rows])
            else:
                if not rows:
                    emit("no workflows")
                else:
                    emit(table(
                        [[row.id, row.mode, row.status, len(row.steps), row.name[:44], row.created_at[11:19]]
                         for row in rows],
                        ["workflow", "mode", "status", "steps", "name", "created"],
                    ))
            return EXIT_OK
        if command == "show":
            workflow = manager.require(args.workflow)
            steps = manager.steps(workflow.id)
            children = ws.tasks.children(workflow.task_id) if workflow.task_id else []
            data = {
                **workflow.to_dict(),
                "steps": [step.to_dict() for step in steps],
                "children": [child.to_dict() for child in children],
            }
            if args.json:
                emit_json(data)
            else:
                emit(f"{workflow.id}  {workflow.mode}  [{workflow.status}]  {workflow.name}")
                if workflow.goal:
                    emit(f"  goal: {workflow.goal}")
                if workflow.task_id:
                    emit(f"  task: {workflow.task_id}")
                if workflow.error:
                    emit(f"  error: {workflow.error}")
                emit("")
                emit("  plan:")
                for index, step in enumerate(workflow.steps, start=1):
                    emit(f"   {index}. {step.kind:<10} {step.title}")
                    if step.tool:
                        emit(f"      tool={step.tool} args={json_text(step.args)}")
                    if step.prompt:
                        emit(f"      prompt: {step.prompt[:120]}")
                    if step.goal:
                        emit(f"      goal: {step.goal[:120]} ({len(step.steps)} nested step(s))")
                    if step.continue_on_error:
                        emit("      continue_on_error: true")
                if steps:
                    emit("")
                    emit(table(
                        [[step.seq, step.kind, step.status, step.tokens, (step.error or step.output or "")[:40]]
                         for step in steps],
                        ["seq", "kind", "status", "tokens", "output / error"],
                    ))
                if children:
                    emit("")
                    emit(f"  subagent tasks: {', '.join(child.id for child in children)}")
            return EXIT_OK
        if command == "rerun":
            original = manager.require(args.workflow)
            replacement = manager.create(
                original.definition,
                mode=original.mode,
                status="approved",
                model_id=original.model_id,
                goal=original.goal,
                metadata={"replaces": original.id, "mode": original.mode},
            )
            workflow = replacement
            code, result = _execute_workflow(ws, workflow, approve=args.approve)
            if args.json:
                emit_json({**result, "workflow": ws.workflows.get(workflow.id).to_dict()})
            else:
                emit(f"new run {workflow.id} (replaces {original.id})  {result['status']}")
                for step in result["steps"]:
                    emit(f"   {step['seq']:>3}  {step['kind']:<10} {step['status']:<10} "
                         f"{(step.get('output') or step.get('error') or '')[:60]}")
                if result.get("summary"):
                    emit("")
                    emit(result["summary"][:800])
                if result.get("approval_id"):
                    emit(f"approve with: archx-agent approvals approve {result['approval_id']}")
            return code
        if command in ("run", "run-file", "run-template"):
            if command == "run-file":
                path = Path(args.path).expanduser()
                if not path.is_file():
                    return fail(f"no workflow file at {path}", EXIT_USAGE)
                try:
                    definition = json.loads(path.read_text())
                except json.JSONDecodeError as exc:
                    return fail(f"{path} is not valid JSON: {exc}", EXIT_USAGE)
                workflow = manager.create(definition, status="approved", goal=definition.get("goal"))
            elif command == "run-template":
                template = TEMPLATES.get(args.template)
                if template is None:
                    return fail(
                        f"unknown template {args.template!r} (known: {', '.join(sorted(TEMPLATES))})",
                        EXIT_USAGE,
                    )
                inputs = _pairs(args.input, flag="--input")
                definition = _render_definition(template, inputs)
                workflow = manager.create(definition, status="approved", goal=definition.get("goal"))
            else:
                workflow = manager.require(args.workflow)
            code, result = _execute_workflow(ws, workflow, approve=args.approve)
            if args.json:
                emit_json({**result, "workflow": ws.workflows.get(workflow.id).to_dict()})
            else:
                emit(f"workflow {result['workflow_id']}  {result['status']}")
                emit(f"  task {result['task_id']}   steps {len(result['steps'])}   tokens {result['tokens']}"
                     f"   {result['elapsed_ms']}ms")
                for step in result["steps"]:
                    mark = "ok" if step["status"] == "succeeded" else step["status"]
                    emit(f"   {step['seq']:>3}  {step['kind']:<10} {mark:<10} {(step.get('output') or step.get('error') or '')[:64]}")
                if result.get("summary"):
                    emit("")
                    emit("summary:")
                    emit(result["summary"][:1200])
                if result.get("approval_id"):
                    emit("")
                    emit(f"approve with: archx-agent approvals approve {result['approval_id']}")
            return code
        if command == "approve":
            workflow = manager.approve(manager.require(args.workflow).id)
            emit_json(workflow.to_dict()) if args.json else emit(
                f"{workflow.id} approved; run it with: archx-agent agent run {workflow.id}"
            )
            return EXIT_OK
        if command == "reject":
            workflow = manager.reject(args.workflow, reason=args.reason or "rejected by the user")
            emit_json(workflow.to_dict()) if args.json else emit(f"{workflow.id} rejected: {workflow.error}")
            return EXIT_OK
        if command == "cancel":
            workflow = manager.cancel(args.workflow, reason=args.reason or "cancelled by the user")
            emit_json(workflow.to_dict()) if args.json else emit(f"{workflow.id} cancelled")
            return EXIT_OK
        if command == "steps":
            workflow = manager.require(args.workflow)
            rows = manager.steps(workflow.id)
            if args.json:
                emit_json([step.to_dict() for step in rows])
            else:
                emit(table(
                    [[step.seq, step.kind, step.status, step.tokens, (step.error or "")[:40]]
                     for step in rows],
                    ["seq", "kind", "status", "tokens", "error"],
                ))
            return EXIT_OK
        if command == "stats":
            data = manager.stats()
            emit_json(data) if args.json else emit(
                f"workflows: {data['total']}  steps: {data['steps']}\n" +
                "\n".join(f"  {status:<10} {count}" for status, count in sorted(data["by_status"].items()))
            )
            return EXIT_OK
    return EXIT_USAGE


def _render_definition(definition: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Substitute ``{{input.*}}`` in a template *before* it becomes a workflow."""
    from archx_agent.managers.workflows import render_inputs

    return render_inputs(definition, inputs)


def _execute_workflow(ws, workflow, *, approve: bool) -> tuple[int, dict[str, Any]]:
    from archx_agent.application.agent import WorkflowFailed

    try:
        result = ws.agent.run(workflow.id, approve=approve)
    except ApprovalRequiredError as exc:
        print(f"approval required: {exc.message}", file=sys.stderr)
        current = ws.workflows.get(workflow.id)
        return EXIT_DENIED, {
            "workflow_id": current.id, "task_id": current.task_id or "", "status": current.status,
            "steps": [], "summary": "", "tokens": 0, "elapsed_ms": 0.0,
            "cancelled": False, "approval_id": getattr(exc, "approval_id", None),
        }
    except WorkflowFailed as exc:
        print(f"workflow failed: {exc.message}", file=sys.stderr)
        current = ws.workflows.get(workflow.id)
        return EXIT_ERROR, {
            "workflow_id": current.id, "task_id": current.task_id or "", "status": current.status,
            "steps": exc.steps, "summary": "", "tokens": 0, "elapsed_ms": 0.0,
            "cancelled": False, "approval_id": exc.approval_id,
        }
    return EXIT_OK, result.to_dict()


def cmd_search(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        if ws.search is None:
            return fail("search is not available in this workspace", EXIT_UNAVAILABLE)
        try:
            report = ws.search.search(
                args.query,
                kinds=args.kind,
                limit=args.limit,
                per_source=args.per_source,
                project_id=args.project,
                conversation_id=args.conversation,
                include_files=False if args.no_files else None,
            )
        except ValidationError as exc:
            return fail(exc.message, EXIT_USAGE)
        if args.json:
            emit_json(report.to_dict())
            return EXIT_OK
        if not report.hits:
            emit(f"no matches for \"{report.query}\"")
        else:
            for hit in report.hits:
                emit(f"[{hit.kind}] {hit.title}  ({hit.score:.2f})")
                if hit.snippet:
                    emit(f"    {hit.snippet}")
                if hit.ref:
                    emit(f"    -> {hit.ref}")
        if report.counts:
            emit("")
            emit("sources: " + ", ".join(f"{k} {v}" for k, v in sorted(report.counts.items())))
        for note in report.degraded:
            emit(f"degraded: {note}")
        for kind, reason in sorted(report.skipped.items()):
            emit(f"skipped {kind}: {reason}")
        emit(f"({report.elapsed_ms:.0f}ms, scanned {sum(report.scanned.values())} record(s))")
        return EXIT_OK


def cmd_learning(args: argparse.Namespace) -> int:
    """`learning ...` - goals, items, sessions, hints, answers and schedules."""
    from archx_agent.application.learning import HintBeforeAttempt, NothingToStudy

    with _workspace(args) as ws:
        if ws.learning is None:
            return fail("Learning Mode is not available in this workspace", EXIT_UNAVAILABLE)
        manager, tutor = ws.learning, ws.tutor
        command = args.learning_command

        if command == "goal":
            sub = args.learning_goal_command
            if sub == "create":
                goal = manager.create_goal(
                    args.title,
                    objective=args.objective,
                    topic=args.topic,
                    level=args.level,
                    success_criteria=args.criteria,
                    priority=args.priority,
                    target_date=args.target_date,
                )
                if args.json:
                    emit_json(goal.to_dict())
                    return EXIT_OK
                emit(f"created goal {goal.id}  {goal.title}")
                emit(f"  level     {goal.level}")
                emit(f"  objective {goal.objective}")
                if goal.success_criteria:
                    emit("  done when " + "; ".join(goal.success_criteria))
                emit("")
                emit(f"next: archx-agent learning plan {goal.id}   (propose items for this goal)")
                return EXIT_OK
            if sub == "list":
                goals = manager.list_goals(status=args.status, limit=args.limit)
                if args.json:
                    emit_json([goal.to_dict() for goal in goals])
                    return EXIT_OK
                if not goals:
                    emit("no goals yet - start with: archx-agent learning goal create \"Rust ownership\"")
                    return EXIT_OK
                emit(table(
                    [[goal.id, goal.status, goal.level, goal.title[:44],
                      manager.stats(goal.id)["items"], manager.stats(goal.id)["due"], goal.updated_at]
                     for goal in goals],
                    ["id", "status", "level", "title", "items", "due", "updated"],
                ))
                return EXIT_OK
            if sub == "show":
                goal = manager.require_goal(args.goal)
                items = manager.items(goal.id)
                stats = manager.stats(goal.id)
                sessions = manager.sessions(goal.id, limit=5)
                if args.json:
                    emit_json({
                        "goal": goal.to_dict(),
                        "items": [item.to_dict() for item in items],
                        "stats": stats,
                        "sessions": [session.to_dict() for session in sessions],
                    })
                    return EXIT_OK
                emit(f"{goal.id}  {goal.title}")
                emit(f"  status    {goal.status}   level {goal.level}   priority {goal.priority}")
                emit(f"  objective {goal.objective}")
                if goal.topic:
                    emit(f"  topic     {goal.topic}")
                if goal.success_criteria:
                    for criterion in goal.success_criteria:
                        emit(f"  done when {criterion}")
                emit(f"  items     {stats['items']} ({', '.join(f'{k} {v}' for k, v in stats['by_status'].items()) or 'none'})   due {stats['due']}")
                emit(f"  attempts  {stats['attempts']}   correct {stats['correct']}"
                     + (f" ({stats['accuracy']:.0%})" if stats["accuracy"] is not None else ""))
                if items:
                    emit("")
                    emit(table(
                        [[item.id, item.status, "yes" if item.due else "no", item.streak,
                          f"{item.interval_days:g}d", item.prompt[:60]]
                         for item in items],
                        ["item", "status", "due", "streak", "interval", "prompt"],
                    ))
                else:
                    emit("")
                    emit(f"next: archx-agent learning plan {goal.id}   (or add one with item add)")
                if sessions:
                    emit("")
                    emit(table(
                        [[session.id, session.mode, session.status, session.items_attempted,
                          session.items_correct, session.started_at] for session in sessions],
                        ["session", "mode", "status", "answered", "correct", "started"],
                    ))
                return EXIT_OK
            if sub == "edit":
                fields = {}
                for name in ("title", "objective", "topic", "level", "priority", "status"):
                    value = getattr(args, name)
                    if value is not None:
                        fields[name] = value
                if args.criteria:
                    fields["success_criteria"] = args.criteria
                if not fields:
                    return fail("nothing to change: pass at least one option", EXIT_USAGE)
                goal = manager.update_goal(args.goal, **fields)
                if args.json:
                    emit_json(goal.to_dict())
                    return EXIT_OK
                emit(f"updated {goal.id}: " + ", ".join(sorted(fields)))
                return EXIT_OK
            if sub == "complete":
                goal = manager.complete_goal(args.goal, note=args.note or "")
                if args.json:
                    emit_json(goal.to_dict())
                    return EXIT_OK
                emit(f"completed {goal.id}  {goal.title}")
                emit("  this is your call against your criteria - Archx did not decide it for you")
                return EXIT_OK
            if sub == "delete":
                goal = manager.require_goal(args.goal)
                if not args.yes:
                    return fail(
                        f"deleting {goal.id} removes its items, sessions and attempts; "
                        "re-run with --yes",
                        EXIT_USAGE,
                    )
                result = manager.delete_goal(goal.id)
                emit(f"deleted {goal.id}" + ("" if args.json else " (with its items and attempts)"))
                if args.json:
                    emit_json(result)
                return EXIT_OK

        if command == "item":
            sub = args.learning_item_command
            if sub == "add":
                item = manager.add_item(
                    args.goal, args.prompt, expected=args.expected, hints=args.hint,
                    explanation=args.explanation, subtopic=args.subtopic,
                )
                if args.json:
                    emit_json(item.to_dict())
                    return EXIT_OK
                emit(f"added item {item.id} to {item.goal_id}")
                emit(f"  prompt {item.prompt}")
                if item.expected:
                    emit(f"  graded against: {item.expected}")
                else:
                    emit("  no expected answer: this item is self-graded (--self-rate)")
                if item.hints:
                    emit(f"  hints  {len(item.hints)}")
                return EXIT_OK
            if sub == "edit":
                item = manager.require_item(args.item)
                changes: dict[str, object] = {}
                if args.prompt:
                    changes["topic"] = args.prompt
                if args.expected is not None:
                    changes["expected"] = args.expected
                if args.explanation is not None:
                    changes["explanation"] = args.explanation
                if args.subtopic is not None:
                    changes["subtopic"] = args.subtopic
                if args.clear_hints and args.add_hint:
                    changes["hints"] = list(args.add_hint)
                elif args.clear_hints:
                    changes["hints"] = []
                elif args.hint is not None:
                    changes["hints"] = args.hint
                elif args.add_hint:
                    changes["hints"] = [*item.hints, *args.add_hint]
                if not changes:
                    return fail(
                        "nothing to change: pass --prompt, --expected, --hint, --add-hint,"
                        " --clear-hints, --explanation or --subtopic",
                        EXIT_USAGE,
                    )
                updated = manager.update_item(item.id, **changes)
                if args.json:
                    emit_json(updated.to_dict())
                    return EXIT_OK
                emit(f"updated item {updated.id}")
                emit(f"  prompt {updated.prompt}")
                emit(f"  ladder {len(updated.hints)} hint(s)")
                emit("  graded against: " + (updated.expected or "your own rating (self)"))
                return EXIT_OK
            if sub == "list":
                items = manager.due_items(args.goal) if args.due else manager.items(
                    args.goal, status=args.status
                )
                if args.json:
                    emit_json([item.to_dict() for item in items])
                    return EXIT_OK
                if not items:
                    emit("nothing due" if args.due else "no items yet")
                    return EXIT_OK
                emit(table(
                    [[item.id, item.status, "yes" if item.due else "no", item.streak,
                      f"{item.interval_days:g}d", item.due_at or "-", item.prompt[:56]]
                     for item in items],
                    ["item", "status", "due", "streak", "interval", "next review", "prompt"],
                ))
                return EXIT_OK
            if sub == "delete":
                item = manager.require_item(args.item)
                if not args.yes:
                    return fail(f"deleting {item.id} removes its attempts; re-run with --yes", EXIT_USAGE)
                result = manager.delete_item(item.id)
                if args.json:
                    emit_json(result)
                else:
                    emit(f"deleted {item.id}")
                return EXIT_OK

        if command == "plan":
            outcome = tutor.plan(
                args.goal, use_model=not bool(args.no_model), max_items=args.max_items,
                model_id=args.model,
            )
            if args.json:
                emit_json(outcome)
                return EXIT_OK
            emit(f"planned {len(outcome['items'])} item(s) by {outcome['planned_by']}")
            emit(f"  why: {outcome['why']}")
            for item in outcome["items"]:
                emit(f"  - {item['id']}  {item['prompt'][:70]}")
            if outcome["planned_by"] == "rules":
                emit("")
                emit("these are checkpoints of your own goal, not a curriculum: edit or delete them")
            return EXIT_OK

        if command == "next":
            try:
                payload = tutor.next_item(args.goal)
            except NothingToStudy as exc:
                if args.json:
                    emit_json({"nothing_to_study": True, "message": exc.message})
                else:
                    emit(exc.message)
                return EXIT_DEGRADED
            if args.json:
                emit_json(payload)
                return EXIT_OK
            item = payload["item"]
            emit(f"{item['id']}  {item['prompt']}")
            emit(f"  why        {payload['why']}")
            emit(f"  status     {item['status']}   due now {payload['due_count']}"
                 + (f"   hints {item['hint_count']}" if item["hint_count"] else ""))
            emit("")
            emit(f"next: archx-agent learning answer {item['id']} \"...\""
                 + ("   (or --self-rate 1-5)" if not item["expected"] else ""))
            return EXIT_OK

        if command == "ask":
            try:
                payload = tutor.ask(args.goal)
            except NothingToStudy as exc:
                if args.json:
                    emit_json({"nothing_to_study": True, "message": exc.message})
                else:
                    emit(exc.message)
                return EXIT_DEGRADED
            if args.json:
                emit_json(payload)
                return EXIT_OK
            item = payload["item"]
            emit(item["prompt"])
            emit(f"  item       {item['id']}")
            emit(f"  why        {payload['why']}")
            emit(f"  due now    {payload['due_count']}")
            emit("  answer with `learning answer` - the answer key and the hint ladder are not shown here")
            return EXIT_OK

        if command == "hint":
            try:
                payload = tutor.hint(args.item, level=args.level)
            except HintBeforeAttempt as exc:
                if args.json:
                    emit_json({"refused": True, "message": exc.message})
                else:
                    emit(exc.message)
                return EXIT_DEGRADED
            if args.json:
                emit_json(payload)
                return EXIT_OK
            emit(f"hint {payload['level']} of {payload['total']}: {payload['hint']}")
            if payload["more"]:
                emit(f"  {payload['more']} more available with --level {payload['level'] + 1}")
            return EXIT_OK

        if command == "answer":
            outcome = tutor.answer(
                args.item, args.answer, self_rating=args.self_rate,
                session_id=args.session, hints_used=args.hints,
            )
            if args.json:
                emit_json(outcome)
                return EXIT_OK
            grade = outcome["grade"]
            emit(("correct" if grade["correct"] else "not yet") + f"  (graded by {grade['graded_by']})")
            emit(f"  {grade['feedback']}")
            schedule = outcome["schedule"]
            emit(f"  schedule   {schedule['why']}")
            emit(f"  next due   {schedule['due_at']}   status {schedule['status']}"
                 f"   ease {schedule['ease']:g}   streak {schedule['streak']}")
            if outcome.get("explanation"):
                emit(f"  explanation {outcome['explanation']}")
            if outcome["session"]:
                session = outcome["session"]
                emit(f"  session    {session['id']} ({session['items_attempted']} answered,"
                     f" {session['items_correct']} correct)")
            return EXIT_OK

        if command == "session":
            sub = args.learning_session_command
            if sub == "start":
                outcome = tutor.start_session(args.goal, mode=args.mode)
                if args.json:
                    emit_json(outcome)
                    return EXIT_OK
                session = outcome["session"]
                emit(f"started {session['mode']} session {session['id']} on {session['goal_id']}")
                if outcome.get("task_id"):
                    emit(f"  task {outcome['task_id']} (this sitting is in the task history)")
                emit(f"  queue {len(outcome['queue'])} item(s)")
                for item in outcome["queue"][:10]:
                    emit(f"    - {item['id']}  {item['prompt'][:60]}")
                return EXIT_OK
            if sub == "list":
                sessions = manager.sessions(args.goal, limit=args.limit)
                if args.json:
                    emit_json([session.to_dict() for session in sessions])
                    return EXIT_OK
                if not sessions:
                    emit("no sessions yet")
                    return EXIT_OK
                emit(table(
                    [[session.id, session.goal_id, session.mode, session.status,
                      session.items_attempted, session.items_correct, session.graded_by or "-",
                      session.started_at] for session in sessions],
                    ["session", "goal", "mode", "status", "answered", "correct", "graded by", "started"],
                ))
                return EXIT_OK
            if sub == "end":
                outcome = tutor.end_session(args.session)
                if args.json:
                    emit_json(outcome)
                    return EXIT_OK
                emit(f"closed {outcome['session']['id']}")
                emit(f"  {outcome['summary']}")
                return EXIT_OK

        if command == "review":
            try:
                outcome = tutor.review(args.goal, limit=args.limit)
            except NothingToStudy as exc:
                if args.json:
                    emit_json({"nothing_due": True, "message": exc.message})
                else:
                    emit(exc.message)
                return EXIT_DEGRADED
            if args.json:
                emit_json(outcome)
                return EXIT_OK
            emit(f"review session {outcome['session']['id']} with {len(outcome['items'])} due item(s)")
            for item in outcome["items"]:
                emit(f"  - {item['id']}  {item['prompt'][:64]}")
            return EXIT_OK

        if command == "stats":
            stats = manager.stats(args.goal)
            if args.json:
                emit_json(stats)
                return EXIT_OK
            if args.goal:
                emit(f"{stats['title']}  ({stats['status']})")
                emit(f"  items     {stats['items']}   mastered {stats['mastered']}   due {stats['due']}")
                emit(f"  attempts  {stats['attempts']}   correct {stats['correct']}"
                     + (f" ({stats['accuracy']:.0%})" if stats["accuracy"] is not None else ""))
                emit(f"  sessions  {stats['sessions']}")
            else:
                emit(f"goals     {stats['goals']}")
                emit(f"items     {stats['items']}   mastered {stats['mastered']}   due {stats['due']}")
                emit(f"attempts  {stats['attempts']}   correct {stats['correct']}"
                     + (f" ({stats['accuracy']:.0%})" if stats["accuracy"] is not None else ""))
                emit(f"sessions  {stats['sessions']}")
            return EXIT_OK

        if command == "search":
            hits = manager.search(args.query, limit=args.limit)
            if args.json:
                emit_json(hits)
                return EXIT_OK
            if not hits:
                emit("no learning matches")
                return EXIT_OK
            emit(table([[hit["kind"], hit["id"], hit["status"], f"{hit['score']:.2f}", hit["title"][:60]]
                        for hit in hits], ["kind", "id", "status", "score", "title"]))
            return EXIT_OK

        if command == "report":
            if args.write:
                path = tutor.write_report(args.goal, args.write)
                emit(f"wrote {path}")
                return EXIT_OK
            text = tutor.report(args.goal)
            if args.json:
                emit_json({"report": text})
            else:
                emit(text.rstrip())
            return EXIT_OK

    return fail(f"unknown learning command {command!r}", EXIT_USAGE)


def cmd_gui(args: argparse.Namespace) -> int:
    """`gui serve` / `gui routes`."""
    from archx_agent.interfaces.gui.server import GuiApi, GuiServer

    if args.gui_command == "routes":
        with _workspace(args) as ws:
            api = GuiApi(ws, token="inspection-only")
            rows = [[definition.method, definition.pattern.pattern, definition.doc]
                    for definition in api.routes()]
            if args.json:
                emit(json.dumps([{"method": m, "path": p, "doc": d} for m, p, d in rows], indent=2))
            else:
                emit(table(rows, ["method", "path", "what it does"]))
        return EXIT_OK

    with _workspace(args) as ws:
        host = args.host or str(ws.config.get("gui.host"))
        port = args.port if args.port is not None else int(ws.config.get("gui.port"))
        allow_remote = bool(args.allow_remote or ws.config.get("gui.allow_remote"))
        loopback = host in {"127.0.0.1", "::1", "localhost"}
        if not loopback and not allow_remote:
            return fail(
                f"refusing to bind {host!r}: pass --allow-remote if you mean it "
                "(the token is then the only boundary between the network and your data)",
                EXIT_USAGE,
            )
        api = GuiApi(
            ws,
            token=args.token,
            token_ttl_minutes=int(ws.config.get("gui.session_minutes")),
            allow_remote=allow_remote,
            max_body_bytes=int(ws.config.get("gui.max_body_bytes")),
        )
        server = GuiServer(api, host=host, port=int(port))
        open_browser = ws.config.get("gui.open_browser") if args.open_browser is None else args.open_browser
        emit(f"Archx GUI on {server.url}")
        emit(f"  home      {ws.config.home}")
        emit(f"  bind      {host}:{server.port}{'  (remote bind allowed)' if allow_remote else '  (loopback only)'}")
        emit(f"  access token: {api.token}")
        emit(f"  open      {server.token_url}")
        emit("")
        emit("The token is this process's only key: anyone with it can act as you in this app.")
        emit("Writes from a browser need the session cookie, which only this page can obtain.")
        emit("Press Ctrl-C to stop.")
        # stdout is a pipe when this runs under a script or a test; without a flush the
        # banner (and the token) is invisible until the process exits.
        sys.stdout.flush()
        if open_browser:
            import threading as _threading
            import webbrowser

            _threading.Timer(0.4, lambda: webbrowser.open(server.token_url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            emit("")
            emit("stopped")
        finally:
            server.stop()
    return EXIT_OK


def cmd_research(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        if ws.research is None:
            return fail("Researcher Mode is not available in this workspace", EXIT_UNAVAILABLE)
        command = args.research_command

        if command == "run":
            urls = list(args.url or [])
            if getattr(args, "urls_from", None):
                try:
                    with open(args.urls_from, "r", encoding="utf-8") as handle:
                        urls.extend(
                            line.strip() for line in handle
                            if line.strip() and not line.strip().startswith("#")
                        )
                except OSError as exc:
                    return fail(f"cannot read {args.urls_from}: {exc}", EXIT_USAGE)
            from archx_agent.application.researcher import ResearchBlocked

            try:
                outcome = ws.researcher.run(
                    args.question,
                    mode=args.mode,
                    urls=urls,
                    max_subquestions=args.max_subquestions,
                    subquestions=list(args.subquestion or []) or None,
                    model_id=args.model,
                    out=args.out,
                    report_format=args.format,
                    use_model=not bool(args.no_model),
                    allow_private_hosts=True if args.allow_private_hosts else None,
                )
            except ResearchBlocked as blocked:
                if args.json:
                    emit_json({
                        "run": ws.research.get(blocked.run_id).to_dict() if blocked.run_id else None,
                        "blocked": True,
                        "approval_id": blocked.approval_id,
                        "message": blocked.message,
                    })
                else:
                    emit("Web research needs a capability I cannot grant for you.")
                    emit(f"  {blocked.message}")
                    if blocked.approval_id:
                        emit("")
                        emit(f"next: archx-agent approvals approve {blocked.approval_id}")
                return EXIT_DENIED
            except (ValidationError, NotFoundError) as exc:
                return fail(getattr(exc, "message", str(exc)), EXIT_USAGE)

            run = outcome["run"]
            verification = outcome["verification"]
            if args.json:
                emit_json({
                    "run": run,
                    "report_path": outcome["report_path"],
                    "verification": verification,
                    "plan_meta": outcome["plan_meta"],
                    "model_reading": outcome["model_reading"],
                })
            else:
                emit(f"{run['id']}  {run['status']}  {run['question'][:70]}")
                emit(f"  mode {run['mode']}   plan by {run['planned_by']}   "
                     f"coverage {run['coverage']:.0%}   {run['evidence_count']} usable source(s)")
                emit(f"  report: {outcome['report_path']}")
                for line in outcome["report"].splitlines():
                    if line.startswith("- **"):
                        emit(f"  {line[2:]}")
                if run["limitations"]:
                    emit("")
                    emit("limitations:")
                    for note in run["limitations"]:
                        emit(f"  - {note}")
                emit("")
                emit(f"next: archx-agent research show {run['id']}")
            problems = not verification["ok"]
            if run["status"] != "completed":
                return EXIT_DEGRADED
            return EXIT_DEGRADED if problems else EXIT_OK

        if command == "list":
            if getattr(args, "closed", False) and getattr(args, "open", False):
                return fail("--closed and --open contradict each other", EXIT_USAGE)
            closed = True if getattr(args, "closed", False) else (
                False if getattr(args, "open", False) else None
            )
            rows = ws.research.list(limit=args.limit, status=args.status, closed=closed)
            if args.json:
                emit_json([row.to_dict() for row in rows])
            elif not rows:
                emit("no research runs")
            else:
                emit(table(
                    [[row.id, row.status, "done" if row.closed else "open",
                      f"{row.coverage:.0%}", row.evidence_count,
                      row.planned_by, row.mode, row.question[:40], row.created_at[11:19]]
                     for row in rows],
                    ["run", "status", "closed", "cover", "src", "plan", "mode", "question", "created"],
                ))
            return EXIT_OK

        if command in {"show", "sources", "report", "verify"}:
            try:
                run = ws.research.get(args.run)
            except NotFoundError as exc:
                return fail(getattr(exc, "message", str(exc)), EXIT_USAGE)
            sources = ws.research.sources(run.id)
            if command == "show":
                if args.json:
                    emit_json({**run.to_dict(), "sources": [s.to_dict() for s in sources]})
                    return EXIT_OK
                emit(f"{run.id}  {run.status}  {run.question}")
                emit(f"  mode {run.mode}   plan by {run.planned_by}   coverage {run.coverage:.0%}   "
                     f"{run.evidence_count} usable source(s)   task {run.task_id or '-'}")
                if run.report_path:
                    emit(f"  report {run.report_path}")
                emit("")
                emit("plan:")
                for index, item in enumerate(run.plan, start=1):
                    emit(f"  {index}. {item.get('question')}")
                    emit(f"     ({item.get('why') or 'no reason'})")
                if run.limitations:
                    emit("")
                    emit("limitations:")
                    for note in run.limitations:
                        emit(f"  - {note}")
                return EXIT_OK
            if command == "sources":
                if args.json:
                    emit_json([s.to_dict() for s in sources])
                    return EXIT_OK
                if not sources:
                    emit("this run recorded no sources")
                else:
                    from archx_agent.application.researcher import citation_numbers

                    labels = citation_numbers(sources)
                    emit(table(
                        [[f"S{labels[s.id]}" if s.id in labels else "-",
                          s.kind, s.status, f"{s.relevance or 0:.2f}", s.stance,
                          (s.title or "")[:36], (s.ref or s.url or "")[:44]]
                         for s in sources],
                        ["cite", "kind", "status", "rel", "stance", "title", "ref"],
                    ))
                    failed = [s for s in sources if s.status != "fetched"]
                    if failed:
                        emit("")
                        emit("could not be read:")
                        for source in failed:
                            emit(f"  {source.ref}: {source.error}")
                return EXIT_OK
            if command == "report":
                if not run.report:
                    return fail(f"run {run.id} has no stored report", EXIT_DEGRADED)
                if args.write:
                    with open(args.write, "w", encoding="utf-8") as handle:
                        handle.write(run.report)
                    emit(f"wrote {args.write}")
                else:
                    emit(run.report)
                return EXIT_OK
            # verify
            from archx_agent.application.researcher import ResearchRunner, citation_numbers

            labels = citation_numbers(sources)
            result = ResearchRunner.verify(run.report or "", list(labels.values()))
            if args.json:
                emit_json(result)
            else:
                emit(f"citations      {result['citations']}")
                emit(f"sources cited  {len(result['sources_cited'])} of {len(result['sources_available'])}")
                emit(f"unknown refs   {len(result['unknown_citations'])}")
                emit(f"uncited claims {len(result['uncited_claims'])}")
                for claim in result["uncited_claims"][:5]:
                    emit(f"  - {claim}")
                emit("result: " + ("ok" if result["ok"] else "problems found"))
            return EXIT_OK if result["ok"] else EXIT_DEGRADED

        if command in {"close", "reopen"}:
            try:
                if command == "close":
                    run = ws.research.close(args.run, note=args.note or "")
                else:
                    run = ws.research.reopen(args.run)
            except NotFoundError as exc:
                return fail(getattr(exc, "message", str(exc)), EXIT_USAGE)
            if args.json:
                emit_json(run.to_dict())
                return EXIT_OK
            if command == "close":
                emit(f"closed {run.id}  {run.question[:60]}")
                emit(f"  the run itself was {run.status} at {run.coverage:.0%} coverage")
                emit("  this is your call, not a coverage threshold - reopen it with `research reopen`")
            else:
                emit(f"reopened {run.id}  {run.question[:60]}")
            return EXIT_OK

        if command == "search":
            try:
                rows = ws.research.search(args.query, limit=args.limit)
            except ValidationError as exc:
                return fail(exc.message, EXIT_USAGE)
            if args.json:
                emit_json(rows)
            elif not rows:
                emit(f"no research about {args.query!r}")
            else:
                for row in rows:
                    emit(f"{row['id']}  {row['status']}  {row['coverage']:.0%}  {row['question'][:60]}")
            return EXIT_OK

        if command == "stats":
            stats = ws.research.stats()
            if args.json:
                emit_json(stats)
            else:
                emit(f"runs    {stats['total']}")
                emit(f"sources {stats['sources']}")
                for status, count in sorted(stats["by_status"].items()):
                    emit(f"  {status}: {count}")
            return EXIT_OK

        if command == "delete":
            if not args.yes:
                return fail("deleting a research run needs --yes", EXIT_USAGE)
            try:
                run = ws.research.get(args.run)
            except NotFoundError as exc:
                return fail(getattr(exc, "message", str(exc)), EXIT_USAGE)
            sources = len(ws.research.sources(run.id))
            ws.research.delete(run.id)
            emit(f"deleted {run.id} (with {sources} source row(s))")
            return EXIT_OK

    return fail(f"unknown research command {command!r}", EXIT_USAGE)


def _render_simple(result) -> None:
    emit(result.headline)
    if result.detail:
        for line in result.detail.splitlines():
            emit(f"  {line}" if not line.startswith(" ") else line)
    if result.next_step:
        emit("")
        emit(f"next: {result.next_step}")
    emit("")
    emit(f"(why: {result.why})")


def cmd_simple(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        if ws.simple is None:
            return fail("Simple Mode is not available in this workspace", EXIT_UNAVAILABLE)
        command = getattr(args, "simple_command", None)
        if command == "status":
            result = ws.simple.status()
        elif command == "help":
            result = ws.simple.help()
        elif command == "ask":
            try:
                result = ws.simple.ask(
                    args.text,
                    model_id=getattr(args, "model", None),
                    conversation_id=getattr(args, "conversation", None),
                )
            except ArchxError as exc:
                code = EXIT_USAGE if isinstance(exc, ValidationError) else EXIT_ERROR
                return fail(getattr(exc, "message", str(exc)), code)
        else:
            return _simple_loop(ws, args)
        if args.json:
            emit_json(result.to_dict())
        else:
            _render_simple(result)
        if result.data.get("approval_id"):
            return EXIT_DENIED
        return EXIT_OK


def _simple_loop(ws, args: argparse.Namespace) -> int:
    """A small REPL. Chat keeps one conversation; every line is explained."""
    if args.json:
        return fail("--json needs a subcommand (ask/status/help)", EXIT_USAGE)
    conversation_id = None
    emit(f"{BRAND} Simple Mode - type /help for what I understand, /quit to leave.")
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            emit("")
            return EXIT_OK
        line = line.strip()
        if not line:
            continue
        if line in {"/quit", "/exit", "quit", "exit"}:
            return EXIT_OK
        try:
            result = ws.simple.ask(line, conversation_id=conversation_id)
        except ValidationError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            continue
        except ArchxError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            continue
        if result.intent == "quit":
            return EXIT_OK
        if result.data.get("conversation_id"):
            conversation_id = result.data["conversation_id"]
        _render_simple(result)


def cmd_jobs(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.jobs
        runner = ws.scheduler
        if manager is None or runner is None:
            return fail("the job scheduler is not available in this workspace", EXIT_UNAVAILABLE)
        command = args.jobs_command

        if command == "submit":
            payload: dict[str, Any] = {}
            if args.job_kind == "command":
                payload["command"] = args.job_command
                if getattr(args, "cwd", None):
                    payload["cwd"] = args.cwd
            elif args.job_kind == "research":
                payload["question"] = args.question
                payload["mode"] = args.mode
                payload["urls"] = list(args.url or [])
                payload["max_subquestions"] = args.max_subquestions
                payload["use_model"] = not bool(args.no_model)
                if not args.title:
                    args.title = f"research: {args.question}"[:120]
            else:
                payload["workflow"] = args.workflow
                payload["approve"] = bool(args.approve)
            if getattr(args, "payload", None):
                try:
                    extra = json.loads(args.payload)
                except ValueError as exc:
                    return fail(f"--job-json is not valid JSON: {exc}", EXIT_USAGE)
                if not isinstance(extra, dict):
                    return fail("--job-json must be a JSON object", EXIT_USAGE)
                payload.update(extra)
            job = manager.enqueue(
                args.job_kind,
                args.title,
                payload,
                priority=args.priority,
                timeout=args.timeout,
                max_attempts=args.max_attempts,
                project_id=args.project,
                dedupe_key=args.dedupe_key,
            )
            if args.json and args.run:
                pass  # one JSON document, emitted by _drain_jobs below
            elif args.json:
                emit_json(job.to_dict())
            else:
                queued = manager.stats()["queued"]
                emit(f"{job.id}  {job.kind}  {job.status}  queue #{job.queue_seq}  {job.title}")
                emit(f"  timeout {job.timeout_seconds}s  attempts {job.attempts}/{job.max_attempts}"
                     f"  priority {job.priority}  ({queued} queued)")
                emit(f"  run it with: archx-agent jobs run   (or inspect: jobs show {job.id})")
            if args.run:
                return _drain_jobs(ws, args, manager, runner, submitted=job)
            return EXIT_OK

        if command == "list":
            rows = manager.list(status=args.status, kind=args.kind, limit=args.limit)
            if args.json:
                emit_json([row.to_dict() for row in rows])
            else:
                if not rows:
                    emit("no jobs")
                else:
                    emit(table(
                        [[row.id, row.kind, row.status, row.queue_seq,
                          f"{row.attempts}/{row.max_attempts}", row.title[:40],
                          row.created_at[11:19]]
                         for row in rows],
                        ["job", "kind", "status", "seq", "att", "title", "created"],
                    ))
            return EXIT_OK

        if command == "queue":
            rows = manager.queue()
            if args.json:
                emit_json([row.to_dict() for row in rows])
            else:
                if not rows:
                    emit("the queue is empty")
                else:
                    emit(table(
                        [[row.queue_seq, row.priority, row.kind, row.title[:44], row.id]
                         for row in rows],
                        ["seq", "priority", "kind", "title", "job"],
                    ))
            return EXIT_OK

        if command == "show":
            job = manager.require(args.job)
            data: dict[str, Any] = job.to_dict()
            if job.task_id:
                found = ws.tasks.find(job.task_id)
                if found.is_ok:
                    data["task"] = found.value.to_dict()
                    data["timeline"] = ws.tasks.timeline(job.task_id)
            if job.kind == "workflow" and job.payload.get("workflow"):
                workflow = ws.workflows.find(str(job.payload["workflow"]))
                if workflow is not None:
                    data["workflow"] = workflow.to_dict(with_definition=False)
                    data["steps"] = [
                        {"seq": step.seq, "kind": step.kind, "status": step.status,
                         "title": step.title, "error": step.error}
                        for step in ws.workflows.steps(workflow.id)
                    ]
            if args.json:
                emit_json(data)
            else:
                emit(f"{job.id}  {job.kind}  [{job.status}]  {job.title}")
                emit(f"  queue #{job.queue_seq}  priority {job.priority}"
                     f"  attempts {job.attempts}/{job.max_attempts}")
                if job.timeout_seconds:
                    emit(f"  deadline {job.deadline or '-'}  (timeout {job.timeout_seconds}s)")
                if job.worker:
                    emit(f"  worker {job.worker}  pid {job.pid}")
                if job.cursor:
                    emit(f"  cursor: {job.cursor} step(s) done")
                if job.message:
                    emit(f"  message: {job.message}")
                if job.error:
                    emit(f"  error: {job.error}")
                if job.task_id:
                    emit(f"  task: {job.task_id}")
                emit("")
                timeline = data.get("timeline") or []
                if timeline:
                    emit("  timeline:")
                    for entry in timeline:
                        emit(f"    {entry['seq']:>3}  {entry.get('kind',''):<20} {(entry.get('detail') or '')[:90]}")
                for step in data.get("steps") or []:
                    emit(f"  step {step['seq']}: {step['kind']} [{step['status']}] {step['title']}")
            return EXIT_OK

        if command == "logs":
            job = manager.require(args.job)
            result = job.result or {}
            if args.json:
                emit_json({"job_id": job.id, "status": job.status, "error": job.error,
                           "result": result})
                return EXIT_OK
            if result.get("stdout"):
                emit(result["stdout"].rstrip())
            if result.get("stderr"):
                emit("-- stderr --")
                emit(result["stderr"].rstrip())
            if job.result and "exit_code" in job.result:
                emit(f"-- exit {job.result['exit_code']} in {job.result.get('duration_ms', 0):.0f}ms --")
            if job.error:
                print(f"error: {job.error}", file=sys.stderr)
            if not result.get("stdout") and not result.get("stderr") and not job.error:
                emit("(no output recorded)")
            return EXIT_OK

        if command == "run":
            return _drain_jobs(ws, args, manager, runner)

        if command == "pause":
            job = manager.require(args.job)
            paused = manager.pause(job.id)
            if paused.status == "running":
                emit(f"{paused.id}  pause requested; it stops at the next step boundary")
            else:
                emit(f"{paused.id}  {paused.status}")
            return EXIT_OK

        if command == "resume":
            job = manager.require(args.job)
            resumed = manager.resume(job.id)
            emit(f"{resumed.id}  {resumed.status}  (continues from step {resumed.cursor})")
            return EXIT_OK

        if command == "cancel":
            job = manager.require(args.job)
            cancelled = manager.cancel(job.id, reason=args.reason or "cancelled by the user")
            emit(f"{cancelled.id}  {cancelled.status}"
                 + ("  (cancel requested; a running command is killed)" if cancelled.status == "running" else ""))
            return EXIT_OK

        if command == "retry":
            job = manager.require(args.job)
            retried = manager.retry(job.id, force=args.force)
            emit(f"{retried.id}  {retried.status}  attempts {retried.attempts}/{retried.max_attempts}")
            return EXIT_OK

        if command == "stats":
            stats = manager.stats()
            if args.json:
                emit_json(stats)
            else:
                emit(f"jobs: {stats['total']}  queued {stats['queued']}  running {stats['running']}"
                     f"  paused {stats['paused']}")
                for status, count in sorted(stats["by_status"].items()):
                    emit(f"  {status:<12} {count}")
                for kind, count in sorted(stats["by_kind"].items()):
                    emit(f"  {kind:<12} {count}")
            return EXIT_OK

        if command == "recover":
            recovered = manager.recover(stale_after=args.stale_after)
            if args.json:
                emit_json(recovered)
            else:
                emit(f"requeued {recovered['requeued']}  interrupted {recovered['interrupted']}"
                     f"  left alone {recovered['skipped']}")
                for job_id in recovered["requeued_ids"]:
                    emit(f"  requeued  {job_id}")
                for job_id in recovered["interrupted_ids"]:
                    emit(f"  interrupted  {job_id}")
            return EXIT_OK

        if command == "reap":
            reaped = manager.reap_expired()
            if args.json:
                emit_json(reaped)
            else:
                emit(f"failed {reaped['expired']} job(s) whose deadline had passed")
                for job_id in reaped["ids"]:
                    emit(f"  timed out  {job_id}")
            return EXIT_OK
    return EXIT_USAGE


def _drain_jobs(ws, args: argparse.Namespace, manager, runner, submitted=None) -> int:
    """Run queued work and report every job it touched."""
    once = bool(getattr(args, "once", False))
    max_jobs = 1 if once else getattr(args, "max_jobs", None)
    results = runner.drain(
        max_jobs=max_jobs,
        max_seconds=getattr(args, "max_seconds", None),
        concurrency=getattr(args, "concurrency", None),
        kinds=[args.job_kind] if getattr(args, "job_kind", None) else None,
    )
    stats = manager.stats()
    if getattr(args, "json", False):
        payload: dict[str, Any] = {
            "ran": [job.to_dict() for job in results],
            "stats": stats,
        }
        if submitted is not None:
            payload["submitted"] = submitted.to_dict()
        emit_json(payload)
    else:
        if not results:
            emit("no queued jobs ran")
        else:
            emit(table(
                [[job.id, job.kind, job.status, f"{job.attempts}/{job.max_attempts}",
                  (job.error or job.message or "")[:44]]
                 for job in results],
                ["job", "kind", "status", "att", "note"],
            ))
        emit(f"queue: {stats['queued']} queued, {stats['running']} running,"
             f" {stats['paused']} paused")
    if any(job.status in ("failed", "cancelled") for job in results):
        return EXIT_ERROR
    if stats["queued"] or stats["running"] or stats["paused"]:
        return EXIT_DEGRADED
    return EXIT_OK


def cmd_tasks(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.tasks
        if manager is None:
            return fail("no task history is available in this workspace", EXIT_UNAVAILABLE)
        command = args.tasks_command
        if command == "list":
            rows = manager.list(
                status=args.status,
                kind=getattr(args, "task_type", None),
                project_id=args.project,
                conversation_id=args.conversation,
                since=args.since,
                limit=args.limit,
            )
            if args.json:
                emit_json([row.to_dict() for row in rows])
            else:
                if not rows:
                    emit("no tasks")
                else:
                    emit(
                        table(
                            [
                                [row.seq, row.created_at[11:19], row.type, row.status,
                                 len(row.tools), len(row.unresolved), row.title[:46]]
                                for row in rows
                            ],
                            ["seq", "time", "type", "status", "tools", "open", "title"],
                        )
                    )
            return EXIT_OK
        if command == "show":
            task = manager.get(args.task)
            data = {
                **task.to_dict(),
                "timeline": manager.timeline(task.id),
                "tool_runs": manager.tool_runs(task.id),
                "artifacts": [a.to_dict() for a in manager.artifacts(task.id)],
                "reproductions": [r.to_dict(with_environment=False) for r in ws.reproduction.records(task.id, limit=5)]
                if ws.reproduction is not None else [],
            }
            if args.json:
                emit_json(data)
            else:
                emit(f"{task.id}  {task.type}  [{task.status}]  {task.title}")
                emit(f"  created {task.created_at}   started {task.started_at or '-'}   finished {task.completed_at or '-'}")
                if task.conversation_id:
                    emit(f"  conversation {task.conversation_id}")
                if task.project_id:
                    emit(f"  project {task.project_id}")
                if task.model_id:
                    emit(f"  model {task.model_id}")
                if task.tools:
                    emit(f"  tools {', '.join(task.tools)}")
                if task.error:
                    emit(f"  error {task.error}")
                if task.unresolved:
                    emit("  open questions:")
                    for index, question in enumerate(task.unresolved):
                        emit(f"   [{index}] {question}")
                if data["timeline"]:
                    emit("")
                    emit("  timeline:")
                    for entry in data["timeline"]:
                        emit(f"   {entry['seq']:>4}  {entry['at'][11:19]}  {entry['kind']:<12} {(entry['detail'] or '')[:80]}")
                if data["tool_runs"]:
                    emit("")
                    emit(table(
                        [[run.get("seq"), run["tool_name"], run["status"], (run.get("error") or "")[:40]]
                         for run in data["tool_runs"]],
                        ["seq", "tool", "status", "error"],
                    ))
                if data["artifacts"]:
                    emit("")
                    emit(table(
                        [[a["id"], a["kind"], a["name"], a["size"], "present" if a["exists"] else "MISSING",
                          (a["metadata"].get("version") or "-")]
                         for a in data["artifacts"]],
                        ["artifact", "kind", "name", "bytes", "file", "version"],
                    ))
                if data["reproductions"]:
                    emit("")
                    emit(table(
                        [[r["id"], r["fidelity"], r["created_at"][11:19]]
                         for r in data["reproductions"]],
                        ["reproduction", "fidelity", "recorded"],
                    ))
            return EXIT_OK
        if command in ("start", "queue"):
            task = manager.create(
                args.task_type,
                args.title,
                conversation_id=args.conversation,
                project_id=args.project,
                parent_task_id=args.parent,
                model_id=args.model,
                start=command == "start",
                manual=True,
            )
            emit_json(task.to_dict()) if args.json else emit(
                f"{task.id}  {task.type}  [{task.status}]  {task.title}"
            )
            return EXIT_OK
        if command == "complete":
            task = manager.complete(args.task, summary=args.summary)
            emit_json(task.to_dict()) if args.json else emit(f"{task.id} completed")
            return EXIT_OK
        if command == "fail":
            task = manager.fail(args.task, args.error)
            emit_json(task.to_dict()) if args.json else emit(f"{task.id} failed: {task.error}")
            return EXIT_OK
        if command == "cancel":
            task = manager.cancel(args.task, args.reason or "")
            emit_json(task.to_dict()) if args.json else emit(f"{task.id} cancelled")
            return EXIT_OK
        if command == "log":
            seq = manager.log(args.task, args.kind, detail=args.detail)
            manager.get(args.task)
            emit_json({"task": args.task, "seq": seq}) if args.json else emit(
                f"{args.task}: logged {args.kind} (step {seq})"
            )
            return EXIT_OK
        if command == "question":
            task = manager.add_question(args.task, args.text)
            emit_json(task.to_dict()) if args.json else emit(
                f"{task.id}: {len(task.unresolved)} open question(s)"
            )
            return EXIT_OK
        if command == "resolve":
            task = manager.resolve_question(args.task, args.question)
            emit_json(task.to_dict()) if args.json else emit(
                f"{task.id}: {len(task.unresolved)} open question(s) remain"
            )
            return EXIT_OK
        if command == "artifacts":
            rows = manager.artifacts(args.task)
            emit_json([a.to_dict() for a in rows]) if args.json else (
                emit(table([[a.id, a.kind, a.name, a.size, "present" if a.exists else "MISSING"]
                            for a in rows], ["artifact", "kind", "name", "bytes", "file"]))
                if rows else emit("no artifacts")
            )
            return EXIT_OK
        if command == "attach":
            artifact = manager.attach_artifact(args.task, args.path, kind=args.kind, name=args.name)
            emit_json(artifact.to_dict()) if args.json else emit(
                f"{artifact.id}  {artifact.name}  {artifact.size} bytes  sha256 {artifact.checksum[:12]}...\n"
                f"version {(artifact.metadata.get('version') or 'not recorded')}"
            )
            return EXIT_OK
        if command == "reproduce":
            if ws.reproduction is None:
                return fail("no reproduction manager is available", EXIT_UNAVAILABLE)
            if args.verify:
                data = ws.reproduction.verify(args.verify)
                if args.json:
                    emit_json(data)
                else:
                    emit(f"recorded {data['recorded']}, now {data['current']}")
                    if data["new_blockers"]:
                        emit(f"  new: {', '.join(data['new_blockers'])}")
                    if data["resolved"]:
                        emit(f"  resolved: {', '.join(data['resolved'])}")
                    if data["changed_settings"]:
                        emit(f"  settings changed: {', '.join(sorted(data['changed_settings']))}")
                    for issue in data["issues"]:
                        emit(f"  [{issue['level']}] {issue['code']}: {issue['detail']}")
                return EXIT_OK if not data["changed"] else EXIT_DEGRADED
            data = ws.reproduction.assess(args.task)
            record = None
            if args.record:
                record = ws.reproduction.capture(args.task)
            payload = {**data, "record": record.to_dict() if record else None}
            if args.json:
                emit_json(payload)
            else:
                emit(f"fidelity: {data['fidelity']}")
                for issue in data["issues"]:
                    emit(f"  [{issue['level']}] {issue['code']}: {issue['detail']}")
                if data["environment"].get("model"):
                    model = data["environment"]["model"]
                    emit(f"model: {model.get('name') or model.get('id')} ({model.get('runtime')})")
                emit("")
                emit("commands:")
                for command_line in data["commands"]:
                    emit(f"  {command_line}")
                if record:
                    emit("")
                    emit(f"recorded as {record.id} ({record.fidelity})")
            return EXIT_OK if data["fidelity"] != "impossible" else EXIT_DEGRADED
        if command == "stats":
            data = manager.stats()
            if args.json:
                emit_json(data)
            else:
                emit(f"tasks: {data['total']}")
                for status, count in sorted(data["by_status"].items()):
                    emit(f"  {status:<12} {count}")
                emit(f"open questions on {data['with_open_questions']} task(s)")
                emit(f"artifacts: {data['artifacts']}")
            return EXIT_OK
    return EXIT_USAGE


def cmd_versions(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        manager = ws.versions
        if manager is None:
            return fail("no version store is available in this workspace", EXIT_UNAVAILABLE)
        command = args.versions_command
        if command == "list":
            versions = manager.history(args.subject_type, args.subject_id)
            if args.json:
                emit_json([v.to_dict() for v in versions])
            else:
                if not versions:
                    emit("no versions recorded")
                else:
                    emit(table(
                        [[v.version, v.created_at[11:19], v.created_by, v.size,
                          "yes" if v.content_stored else "no", v.note[:40]]
                         for v in versions],
                        ["version", "time", "by", "bytes", "content", "note"],
                    ))
            return EXIT_OK
        if command == "record":
            write = manager.record(
                args.subject_type,
                args.subject_id,
                content=args.content,
                path=args.file,
                note=args.note,
                created_by=args.by,
                version=args.label,
                store_content=False if args.no_content else None,
            )
            if args.json:
                emit_json(write.to_dict())
            else:
                if write.created:
                    emit(f"recorded {write.version.version} of {write.version.subject_type} "
                         f"{write.version.subject_id} ({write.version.size} bytes, "
                         f"sha256 {write.version.checksum[:12]}...)")
                else:
                    emit(f"nothing recorded: {write.reason}")
            return EXIT_OK
        if command == "show":
            version = manager.at(args.subject_type, args.subject_id, args.version)
            data = version.to_dict(with_content=True)
            if args.json:
                emit_json(data)
            else:
                emit(f"{version.subject_type} {version.subject_id} {version.version}"
                     f"  ({version.size} bytes, {version.created_at}, by {version.created_by})")
                if version.restored_from:
                    emit(f"restored from {version.restored_from}")
                if version.note:
                    emit(f"note: {version.note}")
                emit("")
                emit(version.content if version.content_stored else "(content was not stored)")
            return EXIT_OK
        if command == "diff":
            data = manager.diff(
                args.subject_type, args.subject_id,
                args.from_version, args.to_version,
            )
            if args.json:
                emit_json(data)
            else:
                emit(f"{data['from']} -> {data['to']}: +{data['added']} -{data['removed']}")
                emit(data["text"] or "(no textual difference)")
            return EXIT_OK
        if command == "restore":
            write = manager.restore(
                args.subject_type, args.subject_id, args.version, note=args.note
            )
            emit_json(write.to_dict()) if args.json else emit(
                f"restored {args.version} as {write.version.version} of "
                f"{write.version.subject_type} {write.version.subject_id} (history kept)"
            )
            return EXIT_OK
        if command == "subjects":
            rows = manager.subjects()
            if args.json:
                emit_json(rows)
            else:
                emit(table([[r["subject_type"], r["subject_id"], r["versions"], r["latest_ordinal"]]
                            for r in rows], ["type", "subject", "versions", "latest"]))
            return EXIT_OK
    return EXIT_USAGE


def cmd_db(args: argparse.Namespace) -> int:
    command = args.db_command
    if command == "restore":
        cfg = load_config(home=args.home, config_path=args.config, create=False)
        preview = preview_restore(args.backup, cfg.get("storage.db_path"))
        if not preview["backup_ok"]:
            return fail("backup failed verification: " + "; ".join(preview["problems"]))
        if not args.yes:
            emit(json_text(preview))
            emit("re-run with --yes to restore (the current database is renamed aside, never deleted)")
            return EXIT_USAGE
        result = restore_backup(args.backup, cfg.get("storage.db_path"))
        emit_json(result) if args.json else emit(json_text(result))
        return EXIT_OK
    with _workspace(args) as ws:
        if command == "check":
            integrity = ws.store.integrity_check()
            fk = ws.store.foreign_key_check()
            data = {
                "integrity": integrity,
                "foreign_keys": fk,
                "schema_version": ws.store.schema_version(),
                "tables": ws.store.table_counts(),
                "journal": ws.coordinator.journal(5),
            }
            if args.json:
                emit_json(data)
            else:
                emit(f"integrity     {', '.join(integrity)}")
                emit(f"foreign keys  {'ok' if not fk else fk}")
                emit(f"schema        v{data['schema_version']}")
                emit(f"tables        {len(data['tables'])}")
                emit(f"write journal {len(data['journal'])} recent entries")
            return EXIT_OK if integrity == ["ok"] and not fk else EXIT_ERROR
        if command == "stats":
            counts = ws.store.table_counts()
            emit_json(counts) if args.json else emit(
                table([[k, v] for k, v in sorted(counts.items())], ["table", "rows"])
            )
            return EXIT_OK
        if command == "backup":
            info = create_backup(ws.store.path, ws.config.path("paths.backups"), label=args.label)
            emit_json(info.to_dict()) if args.json else emit(f"backup written to {info.path} ({info.size} bytes)")
            return EXIT_OK
        if command == "backups":
            rows = list_backups(ws.config.path("paths.backups"))
            if args.json:
                emit_json(rows)
            else:
                if not rows:
                    emit("no backups")
                for row in rows:
                    emit(f"{row['path']}  {row['size']} bytes  {row['created_at']}")
            return EXIT_OK
        if command == "verify":
            report = verify_backup(args.backup)
            emit_json(report) if args.json else emit(
                ("ok: " if report["ok"] else "FAILED: ") + ("; ".join(report["problems"]) or "verified")
            )
            return EXIT_OK if report["ok"] else EXIT_ERROR
        if command == "preview-restore":
            emit_json(preview_restore(args.backup, ws.store.path)) if args.json else emit(
                json_text(preview_restore(args.backup, ws.store.path))
            )
            return EXIT_OK
        if command == "retention":
            retired = apply_retention(ws.config.path("paths.backups"), keep=args.keep)
            emit_json({"retired": retired}) if args.json else emit(f"retired {len(retired)} backup(s) to _retired/")
            return EXIT_OK
        if command == "journal":
            rows = ws.coordinator.journal(20)
            if args.json:
                emit_json(rows)
            else:
                emit(table([[r["op_id"], r["kind"], r["state"], r["created_at"]] for r in rows],
                           ["op", "kind", "state", "created"]))
            return EXIT_OK
    return EXIT_USAGE


def cmd_trace(args: argparse.Namespace) -> int:
    with _workspace(args) as ws:
        store = ws.events
        store.flush()
        command = args.trace_command
        if command == "list":
            events = store.query(
                kind=args.kind,
                conversation_id=args.conversation,
                task_id=args.task,
                run_id=args.run,
                status=args.status,
                limit=args.limit,
                newest_first=args.newest_first,
            )
            if args.json:
                emit_json([e.to_dict() for e in events])
            else:
                if not events:
                    emit("no events")
                else:
                    emit(
                        table(
                            [[e.seq, e.ts[11:19], e.kind, e.name, e.status,
                              (e.payload.get("model_name") or e.payload.get("tool") or "")] for e in events],
                            ["seq", "time", "kind", "name", "status", "detail"],
                        )
                    )
            return EXIT_OK
        if command == "show":
            event = store.get(args.event)
            if event is None:
                return fail(f"no event {args.event}")
            emit_json(event.to_dict()) if args.json else emit(json_text(event.to_dict()))
            return EXIT_OK
        if command == "tree":
            try:
                tree = store.trace_tree(args.event)
            except ArchxError as exc:
                return fail(exc.message)
            emit_json(tree) if args.json else emit(json_text(tree))
            return EXIT_OK
        if command == "errors":
            events = store.recent_errors(30)
            if args.json:
                emit_json([e.to_dict() for e in events])
            else:
                if not events:
                    emit("no errors recorded")
                for event in events:
                    emit(f"{event.seq} {event.ts[11:19]} {event.kind}/{event.name} [{event.status}] {event.error or ''}")
            return EXIT_OK
        if command == "summary":
            rows = store.summaries()
            emit_json(rows) if args.json else emit(
                table([[r["kind"], r["status"], r["n"], r["first_seq"], r["last_seq"]] for r in rows],
                      ["kind", "status", "count", "first", "last"])
            )
            return EXIT_OK
        if command == "export":
            path = store.export_jsonl(args.out, conversation_id=args.conversation)
            emit(f"exported {path}")
            return EXIT_OK
        if command == "retention":
            removed = store.apply_retention(
                max_age_days=args.days if args.days is not None else ws.config.get("trace.retention_days"),
                max_events=ws.config.get("trace.max_events"),
            )
            emit(f"removed {removed} event(s)")
            return EXIT_OK
    return EXIT_USAGE


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def cmd_code(args: argparse.Namespace) -> int:
    """`code ...` - the coding workspace: edit, run and test under the permission centre.

    Exit codes follow the run, not the tool: a passing check is 0, a failing one is 1 (the same
    number the command itself returned), a timeout is 3 and a refusal is 4 with the approval named.
    """
    from archx_agent.helpers.exceptions import ApprovalRequiredError, PermissionDeniedError

    with _workspace(args) as ws:
        service = ws.code
        command = args.code_command
        try:
            if command == "open":
                session = service.open(
                    args.root, title=args.title, note=args.note, project_id=args.project
                )
                if getattr(args, "json", False):
                    emit_json(session.to_dict())
                    return EXIT_OK
                emit(f"opened {session.id}  {session.title}")
                emit(f"  root      {session.root}")
                emit(f"  task      {session.task_id or '-'}")
                emit(f"  next      archx-agent code write {session.id} hello.py --content 'print(1)'")
                emit("           (a write needs fs.write: archx-agent permissions grant fs.write)")
                return EXIT_OK

            if command == "list":
                sessions = service.sessions(status=args.status, limit=args.limit)
                if getattr(args, "json", False):
                    emit_json([s.to_dict() for s in sessions])
                    return EXIT_OK
                if not sessions:
                    emit("no coding sessions yet (archx-agent code open --root .)")
                    return EXIT_OK
                for session in sessions:
                    mark = "open  " if session.open else "closed"
                    emit(f"{session.id}  {mark}  {session.title}  {session.root}")
                return EXIT_OK

            if command == "show":
                shown = service.show(args.session)
                if getattr(args, "json", False):
                    emit_json(shown)
                    return EXIT_OK
                session = shown["session"]
                emit(f"{session['id']}  {session['title']}  [{session['status']}]")
                emit(f"  root   {session['root']}")
                emit(f"  task   {session['task_id'] or '-'}")
                stats = shown["stats"]
                emit(f"  edits  {stats['changes']} (+{stats['added']}/-{stats['removed']})")
                emit(f"  runs   {stats['runs']} ({stats['failed']} not passed)")
                if shown["changes"]:
                    emit("")
                    for change in shown["changes"]:
                        emit(f"  {change['action']:<7} {change['path']}  "
                             f"+{change['added']}/-{change['removed']}")
                if shown["runs"]:
                    emit("")
                    for run in shown["runs"]:
                        emit(f"  {run['status']:<8} exit {run['exit_code']}  "
                             f"{int(run['duration_ms'] or 0)} ms  {run['command'][:60]}")
                return EXIT_OK

            if command == "read":
                result = service.read(
                    args.session, args.path,
                    start_line=args.start_line, max_lines=args.max_lines,
                )
                if getattr(args, "json", False):
                    emit_json(result)
                    return EXIT_OK
                emit(result.get("content") or "")
                if result.get("truncated"):
                    emit(f"[truncated: {result.get('total_lines')} lines in the file]")
                return EXIT_OK

            if command == "ls":
                listing = service.list_dir(args.session, args.path, limit=args.limit)
                if getattr(args, "json", False):
                    emit_json(listing)
                    return EXIT_OK
                for entry in listing["entries"]:
                    size = "-" if entry["size"] is None else str(entry["size"])
                    emit(f"  {entry['kind']:<4} {size:>8}  {entry['name']}")
                if listing["truncated"]:
                    emit(f"[{listing['count']} entries, showing {len(listing['entries'])}]")
                return EXIT_OK

            if command == "write":
                if args.content is not None and args.file:
                    return fail("pass --content or --file, not both", EXIT_USAGE)
                if args.file:
                    content = Path(args.file).read_text(encoding="utf-8")
                elif args.content == "-":
                    content = sys.stdin.read()
                elif args.content is not None:
                    content = args.content
                else:
                    return fail("a write needs --content TEXT, --content - or --file PATH", EXIT_USAGE)
                change = service.write(args.session, args.path, content, note=args.note)
                if getattr(args, "json", False):
                    emit_json(change.to_dict())
                    return EXIT_OK
                emit(f"{change.action} {change.path}  +{change.added}/-{change.removed}")
                if change.artifact_id:
                    emit(f"  diff     {change.artifact_id}")
                return EXIT_OK

            if command == "delete":
                change = service.delete(args.session, args.path, note=args.note)
                if getattr(args, "json", False):
                    emit_json(change.to_dict())
                    return EXIT_OK
                emit(f"deleted {change.path}  (+{change.added}/-{change.removed})")
                return EXIT_OK

            if command in {"run", "test"}:
                if command == "run":
                    run = service.run(
                        args.session, args.code_line, timeout=args.timeout, cwd=args.cwd
                    )
                else:
                    run = service.test(args.session, args.check)
                if getattr(args, "json", False):
                    emit_json(run.to_dict())
                    return _run_exit(run)
                if run.stdout:
                    emit(run.stdout.rstrip())
                if run.stderr:
                    print(run.stderr.rstrip(), file=sys.stderr)
                label = f"check {run.check_name}" if run.check_name else "run"
                emit(f"[{label} {run.status}: exit {run.exit_code} in "
                     f"{int(run.duration_ms or 0)} ms]")
                if run.artifact_id:
                    emit(f"[output saved as {run.artifact_id}]")
                return _run_exit(run)

            if command == "checks":
                listing = service.checks(args.session)
                if getattr(args, "json", False):
                    emit_json(listing)
                    return EXIT_OK
                if not listing["checks"]:
                    emit(listing["reason"])
                    return EXIT_OK
                emit(f"{len(listing['checks'])} check(s) from {listing['source']}")
                for check in listing["checks"]:
                    timeout = f"  ({check['timeout']}s)" if check["timeout"] else ""
                    emit(f"  {check['name']:<10} {check['command']}{timeout}")
                return EXIT_OK

            if command == "diff":
                patch = service.diff(args.session)
                if args.write:
                    Path(args.write).write_text(patch["patch"], encoding="utf-8")
                if getattr(args, "json", False):
                    emit_json(patch)
                    return EXIT_OK
                if not patch["patch"]:
                    emit("this session made no changes")
                    return EXIT_OK
                emit(patch["patch"].rstrip("\n"))
                emit("")
                emit(f"[{len(patch['files'])} file(s), +{patch['added']}/-{patch['removed']}]")
                if args.write:
                    emit(f"[written to {args.write}]")
                return EXIT_OK

            if command == "runs":
                runs = service.runs(args.session, limit=args.limit)
                if getattr(args, "json", False):
                    emit_json([run.to_dict() for run in runs])
                    return EXIT_OK
                if not runs:
                    emit("nothing has been run in this session")
                    return EXIT_OK
                for run in runs:
                    name = f"[{run.check_name}] " if run.check_name else ""
                    emit(f"{run.id}  {run.status:<8} exit {str(run.exit_code):<4} "
                         f"{int(run.duration_ms or 0):>6} ms  {name}{run.command[:70]}")
                return EXIT_OK

            if command == "rerun":
                run = service.rerun(args.run)
                if getattr(args, "json", False):
                    emit_json(run.to_dict())
                    return _run_exit(run)
                if run.stdout:
                    emit(run.stdout.rstrip())
                if run.stderr:
                    print(run.stderr.rstrip(), file=sys.stderr)
                emit(f"[replay {run.status}: exit {run.exit_code} in "
                     f"{int(run.duration_ms or 0)} ms]")
                return _run_exit(run)

            if command == "close":
                session = service.close(args.session, note=args.note)
                if getattr(args, "json", False):
                    emit_json(session.to_dict())
                    return EXIT_OK
                emit(f"closed {session.id}  {session.title}")
                emit("  the edits and runs stay readable: archx-agent code show "
                     f"{session.id}")
                return EXIT_OK

            if command == "stats":
                data = service.stats()
                if getattr(args, "json", False):
                    emit_json(data)
                    return EXIT_OK
                emit(f"sessions {data['sessions']} ({data['open']} open)")
                emit(f"edits    {data['changes']}")
                emit(f"runs     {data['runs']} ({data['failed_runs']} not passed)")
                return EXIT_OK
        except ApprovalRequiredError as exc:
            approval = getattr(exc, "approval_id", None)
            hint = (
                f"approve it with: archx-agent approvals approve {approval}"
                if approval else "grant the capability with: archx-agent permissions grant <capability>"
            )
            return fail(f"{exc.message}\n{hint}", EXIT_DENIED)
        except PermissionDeniedError as exc:
            return fail(exc.message, EXIT_DENIED)

        return fail(f"unknown code command: {command}", EXIT_USAGE)


def _parse_assignments(values: list[str], *, what: str) -> dict[str, str]:
    """Parse repeated ``NAME=VALUE`` / ``NAME`` flags into a dict, refusing near-misses."""
    out: dict[str, str] = {}
    for raw in values:
        text = str(raw)
        if "=" in text:
            name, _, value = text.partition("=")
        else:
            name, value = text, ""
        name = name.strip()
        if not name:
            raise ValidationError(f"{what} {raw!r} has no name")
        if name in out:
            raise ValidationError(f"{what} {name!r} was given twice")
        out[name] = value.strip()
    return out


def cmd_experiment(args: argparse.Namespace) -> int:
    """`experiment ...` - declare a command, run it with parameters, compare the runs.

    Exit codes follow the run: passed 0, failed 1, timeout 3, refused 4 with the approval named.
    """
    from archx_agent.helpers.exceptions import ApprovalRequiredError, PermissionDeniedError

    command = args.experiment_command
    try:
        with _workspace(args) as ws:
            service = ws.experiment
            if command == "create":
                try:
                    params = _parse_assignments(args.param, what="parameter")
                except ValidationError as exc:
                    return fail(exc.message, EXIT_USAGE)
                declared = [
                    {"name": name, "default": (value if value != "" else None)}
                    for name, value in params.items()
                ]
                if args.metric_source == "file" and not args.metric_file:
                    return fail("--metric-source file needs --metric-file PATH", EXIT_USAGE)
                metrics = {"kind": args.metric_source}
                if args.metric_file:
                    metrics["path"] = args.metric_file
                experiment = service.create(
                    args.name,
                    args.experiment_line,
                    root=args.root,
                    hypothesis=args.hypothesis,
                    params=declared,
                    metrics=metrics,
                )
                if getattr(args, "json", False):
                    emit_json(experiment.to_dict())
                    return EXIT_OK
                emit(f"created {experiment.id}  {experiment.name}")
                emit(f"  root      {experiment.root}")
                emit(f"  command   {experiment.command}")
                if experiment.param_names():
                    defaults = ", ".join(
                        f"{entry['name']}={entry['default']}" for entry in experiment.params
                    )
                    emit(f"  params    {defaults}")
                source = experiment.metrics_source
                if source.get("kind") == "none":
                    emit("  metrics   none declared - an experiment that reads no numbers is "
                         "still a record, but it cannot be compared")
                elif source.get("kind") == "file":
                    emit(f"  metrics   {source.get('path')} (JSON object of numbers)")
                else:
                    emit("  metrics   the last line of stdout (JSON object of numbers)")
                emit(f"  next      archx-agent experiment run {experiment.id}")
                return EXIT_OK

            if command == "list":
                rows = service.list(status=args.status, limit=args.limit)
                if getattr(args, "json", False):
                    emit_json([row.to_dict() for row in rows])
                    return EXIT_OK
                if not rows:
                    emit("no experiments yet (archx-agent experiment create NAME --command ...)")
                    return EXIT_OK
                counts = ws.experiments.run_counts()
                for row in rows:
                    mark = "open  " if row.open else "closed"
                    stats = counts.get(row.id, {"runs": 0, "failed": 0})
                    emitted = f"{stats['runs']} run(s)"
                    if stats["failed"]:
                        emitted += f", {stats['failed']} not passed"
                    emit(f"{row.id}  {mark}  {row.name}  ({emitted})  {row.root}")
                return EXIT_OK

            if command == "show":
                shown = service.show(args.experiment)
                if getattr(args, "json", False):
                    emit_json(shown)
                    return EXIT_OK
                exp = shown["experiment"]
                emit(f"{exp['id']}  {exp['name']}  [{exp['status']}]")
                emit(f"  root      {exp['root']}")
                emit(f"  command   {exp['command']}")
                if exp["hypothesis"]:
                    emit(f"  expect    {exp['hypothesis']}")
                stats = shown["stats"]
                emit(f"  runs      {stats['runs']} ({stats['by_status']})")
                emit(f"  metrics   {', '.join(shown['metric_names']) or 'none recorded'}")
                if shown["runs"]:
                    emit("")
                    for run in shown["runs"]:
                        numbers = ", ".join(f"{k}={v:g}" for k, v in run["metrics"].items())
                        emit(f"  {run['id']}  {run['status']:<8} exit {str(run['exit_code']):<4} "
                             f"{numbers or (run['metrics_error'] or 'no metrics')}")
                return EXIT_OK

            if command == "run":
                try:
                    overrides = _parse_assignments(args.set, what="setting")
                except ValidationError as exc:
                    return fail(exc.message, EXIT_USAGE)
                run = service.run(
                    args.experiment, overrides, timeout=args.timeout, seed=args.seed,
                    note=args.note,
                )
                if getattr(args, "json", False):
                    emit_json(run.to_dict())
                    return _experiment_exit(run)
                if run.metrics:
                    emit(", ".join(f"{k}={v:g}" for k, v in run.metrics.items()))
                elif run.metrics_error:
                    emit(f"[no metrics: {run.metrics_error}]")
                emit(f"[{run.status}: exit {run.exit_code} in {int(run.duration_ms or 0)} ms]")
                if run.artifact_id:
                    emit(f"[output saved as {run.artifact_id}]")
                return _experiment_exit(run)

            if command == "compare":
                table = service.compare(
                    args.experiment, metric=args.metric, minimise=args.minimise,
                    limit=args.limit,
                )
                if getattr(args, "json", False):
                    emit_json(table)
                    return EXIT_OK
                exp = table["experiment"]
                if table["metric"]:
                    best = table["best"]
                    emit(f"{exp['name']}: {table['metric']} "
                         f"({table['direction']} wins, {len(table['runs'])} run(s))")
                    if best:
                        emit(f"  best  {best['run_id']}  {table['metric']}={best['value']:g}  "
                             f"{_params_text(best['params'])}")
                else:
                    emit(f"{exp['name']}: no metrics were ever read, so there is nothing to rank")
                failures = [run for run in table["runs"] if run["status"] != "passed"]
                for run in failures:
                    emit(f"  {run['id']}  {run['status']}  exit {run['exit_code']}")
                for note in table["notes"]:
                    emit(f"  note: {note}")
                return EXIT_OK

            if command == "runs":
                runs = service.runs(args.experiment, limit=args.limit)
                if getattr(args, "json", False):
                    emit_json([run.to_dict() for run in runs])
                    return EXIT_OK
                if not runs:
                    emit("this experiment has not been run yet")
                    return EXIT_OK
                for run in runs:
                    numbers = ", ".join(f"{k}={v:g}" for k, v in run.metrics.items())
                    emit(f"{run.id}  {run.status:<8} exit {str(run.exit_code):<4} "
                         f"{_params_text(run.params):<28} {numbers}")
                return EXIT_OK

            if command == "close":
                experiment = service.close(args.experiment)
                if getattr(args, "json", False):
                    emit_json(experiment.to_dict())
                    return EXIT_OK
                emit(f"closed {experiment.id}  {experiment.name}")
                emit(f"  the runs stay readable: archx-agent experiment show {experiment.id}")
                return EXIT_OK

            if command == "reopen":
                experiment = service.reopen(args.experiment)
                if getattr(args, "json", False):
                    emit_json(experiment.to_dict())
                    return EXIT_OK
                emit(f"reopened {experiment.id}  {experiment.name}")
                return EXIT_OK

            if command == "delete":
                if not args.yes:
                    return fail(
                        "deleting an experiment deletes its runs; pass --yes to confirm", EXIT_USAGE
                    )
                service.delete(args.experiment)
                if getattr(args, "json", False):
                    emit_json({"deleted": args.experiment})
                    return EXIT_OK
                emit(f"deleted {args.experiment}")
                return EXIT_OK

            if command == "stats":
                data = service.stats()
                if getattr(args, "json", False):
                    emit_json(data)
                    return EXIT_OK
                emit(f"experiments {data['experiments']} ({data['open']} open)")
                emit(f"runs        {data['runs']} ({data['failed_runs']} not passed)")
                emit(f"metrics     {data['metrics']}")
                return EXIT_OK
    except ApprovalRequiredError as exc:
        approval = getattr(exc, "approval_id", None)
        hint = (
            f"approve it with: archx-agent approvals approve {approval}"
            if approval
            else "grant the capability with: archx-agent permissions grant <capability>"
        )
        return fail(f"{exc.message}\n{hint}", EXIT_DENIED)
    except PermissionDeniedError as exc:
        return fail(exc.message, EXIT_DENIED)
    except NotFoundError as exc:
        return fail(exc.message, EXIT_ERROR)
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)

    return fail(f"unknown experiment command: {command}", EXIT_USAGE)


def _experiment_exit(run) -> int:
    """A run's own result as an exit code the shell can branch on."""
    if run.status == "passed":
        return EXIT_OK
    if run.status == "refused":
        return EXIT_DENIED
    if run.status == "timeout":
        return EXIT_DEGRADED
    return EXIT_ERROR


def _params_text(params: dict) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(params.items())) or "-"


def _run_exit(run) -> int:
    """A run's own result, as an exit code the shell can branch on."""
    if run.status == "passed":
        return EXIT_OK
    if run.status == "timeout":
        return EXIT_DEGRADED
    return EXIT_ERROR


def cmd_play(args: argparse.Namespace) -> int:
    """`play ...` - games the rules referee, and simulations that can be replayed.

    Exit codes: 0 the move was accepted (or the command succeeded), 1 the replay disagreed with
    the record, 2 the rules refused the move or the arguments made no sense. A refused move is an
    answer, not a crash: it is printed with the reason and written to the log like any other.
    """
    command = args.play_command
    try:
        with _workspace(args) as ws:
            service = ws.play_mode

            if command == "new":
                view = service.new(args.game, seed=args.seed)
                if args.json:
                    emit_json(view)
                    return EXIT_OK
                emit(f"started {view['id']}  {view['game_type']}")
                emit("")
                emit(view["board"])
                emit("")
                emit(f"  to move   {view['turn']}")
                emit(f"  moves     {', '.join(view['legal_moves'][:12])}"
                     + (" ..." if len(view["legal_moves"]) > 12 else ""))
                emit(f"  next      archx-agent play move {view['id']} <MOVE>")
                return EXIT_OK

            if command == "show":
                view = service.view(args.game, limit=args.moves)
                if args.json:
                    emit_json(view)
                    return EXIT_OK
                emit(view["board"])
                emit("")
                emit(f"  game      {view['id']}  {view['game_type']}  ({view['status']})")
                emit(f"  to move   {view['turn'] or '-'}")
                emit(f"  moves     {view['move_count']}")
                if view["legal_moves"]:
                    emit(f"  legal     {', '.join(view['legal_moves'][:14])}")
                outcome = view["outcome"]
                if outcome["over"]:
                    emit(f"  result    {outcome['winner'] or 'draw'} ({outcome['reason']})")
                if view["moves"]:
                    emit("")
                    for move in view["moves"]:
                        mark = "" if move["legal"] else f"   refused: {move['reason']}"
                        emit(f"  {move['seq']:>3}  {move['player']:<4} {move['action']}{mark}")
                return EXIT_OK

            if command == "move":
                result = service.move(args.game, args.move)
                if args.json:
                    emit_json(result)
                    return EXIT_OK if result["legal"] else EXIT_USAGE
                if not result["legal"]:
                    emit(f"refused: {result['reason']}")
                    emit(f"  game      {result['game_id']}  (the board did not change)")
                    emit(f"  to move   {result['turn']}")
                    return EXIT_USAGE
                emit(result["board"])
                emit("")
                emit(f"  played    {result['player']} {result['action']}")
                if result["outcome"]["over"]:
                    emit(f"  result    {result['outcome']['winner'] or 'draw'}"
                         f" ({result['outcome']['reason']})")
                else:
                    emit(f"  to move   {result['turn']}")
                return EXIT_OK

            if command == "engine":
                result = service.engine_move(args.game, seed=args.seed)
                if args.json:
                    emit_json(result)
                    return EXIT_OK
                emit(f"engine plays {result['action']} as {result['player']}")
                emit("")
                emit(result["board"])
                if result["outcome"]["over"]:
                    emit("")
                    emit(f"  result    {result['outcome']['winner'] or 'draw'}"
                         f" ({result['outcome']['reason']})")
                else:
                    emit("")
                    emit(f"  to move   {result['turn']}")
                return EXIT_OK

            if command == "auto":
                view = service.auto(args.game, plies=args.plies, seed=args.seed)
                if args.json:
                    emit_json(view)
                    return EXIT_OK
                for move in view["played"]:
                    emit(f"  {move['player']} {move['action']}")
                emit("")
                emit(view["board"])
                emit("")
                emit(f"  played    {len(view['played'])} move(s)  total {view['move_count']}")
                outcome = view["outcome"]
                if outcome["over"]:
                    emit(f"  result    {outcome['winner'] or 'draw'} ({outcome['reason']})")
                else:
                    emit(f"  to move   {view['turn']}")
                return EXIT_OK

            if command == "resign":
                view = service.resign(args.game, winner=args.winner)
                if args.json:
                    emit_json(view)
                    return EXIT_OK
                emit(f"abandoned {view['id']}")
                if view["winner"]:
                    emit(f"  winner    {view['winner']}")
                emit("  the moves are still there: archx-agent play history "
                     f"{view['id']}")
                return EXIT_OK

            if command == "history":
                history = service.history(args.game)
                if args.json:
                    emit_json(history)
                    return EXIT_OK
                emit(f"{history['id']}  {history['game_type']}  ({history['status']})")
                emit(f"  accepted  {history['legal']}")
                emit(f"  refused   {history['refused_count']}")
                if history["moves"]:
                    emit("")
                    rows = [
                        [m["seq"], m["player"], m["action"],
                         "yes" if m["legal"] else "no", m["reason"] or "", m["created_at"]]
                        for m in history["moves"]
                    ]
                    emit(table(rows, ["seq", "player", "move", "legal", "why", "when"]))
                return EXIT_OK

            if command == "list":
                games = service.games(status=args.status, limit=args.limit)
                if args.json:
                    emit_json(games)
                    return EXIT_OK
                if not games:
                    emit("no games yet (archx-agent play new)")
                    return EXIT_OK
                rows = [
                    [g["id"], g["game_type"], g["status"], g["winner"] or "-",
                     g["move_count"], g["created_at"]]
                    for g in games
                ]
                emit(table(rows, ["id", "game", "status", "winner", "moves", "created"]))
                return EXIT_OK

            if command == "sim":
                sim = service.simulate(
                    width=args.width, height=args.height, steps=args.steps,
                    seed=args.seed, density=args.density,
                )
                if args.json:
                    emit_json(sim)
                    return EXIT_OK
                emit(f"ran {sim['id']}  {sim['kind']}  {sim['width']}x{sim['height']}"
                     f"  {sim['steps']} step(s)  seed {sim['seed']}")
                emit(f"  rule      {sim['metadata'].get('rule', '-')}")
                emit(f"  alive     {sim['alive']}")
                emit(f"  series    {', '.join(str(n) for n in sim['series'][:14])}"
                     + (" ..." if len(sim["series"]) > 14 else ""))
                emit(f"  hash      {sim['final_hash']}")
                if args.board:
                    emit("")
                    for line in sim["rows"]:
                        emit("  " + line)
                emit("")
                emit(f"  check     archx-agent play replay {sim['id']}")
                return EXIT_OK

            if command == "sims":
                sims = service.sims(limit=args.limit)
                if args.json:
                    emit_json(sims)
                    return EXIT_OK
                if not sims:
                    emit("no simulations yet (archx-agent play sim)")
                    return EXIT_OK
                rows = [
                    [s["id"], s["kind"], f"{s['width']}x{s['height']}", s["steps"], s["seed"],
                     s["alive"], (s["final_hash"] or "-")[:12], s["created_at"]]
                    for s in sims
                ]
                emit(table(rows, ["id", "kind", "size", "steps", "seed", "alive", "hash",
                                  "created"]))
                return EXIT_OK

            if command == "replay":
                check = service.replay(args.sim)
                if args.json:
                    emit_json(check)
                    return EXIT_OK if check["matches"] else EXIT_ERROR
                emit(f"{check['id']}  {check['width']}x{check['height']}  {check['steps']} step(s)"
                     f"  seed {check['seed']}")
                emit(f"  stored      {check['stored_hash']}")
                emit(f"  recomputed  {check['recomputed_hash']}")
                if check["matches"]:
                    emit("  verdict     reproduced")
                    return EXIT_OK
                emit("  verdict     DIFFERENT - the record does not describe these parameters")
                return EXIT_ERROR

            if command == "stats":
                data = service.stats()
                if args.json:
                    emit_json(data)
                    return EXIT_OK
                emit(f"games       {data['games']} ({data['open']} open, "
                     f"{data['finished']} finished)")
                emit(f"moves       {data['moves']} ({data['refused_moves']} refused by the rules)")
                emit(f"sims        {data['sims']}")
                emit(f"built in    {', '.join(data['games_available'])}"
                     f"  (default: {data['default_game']})")
                return EXIT_OK

    except NotFoundError as exc:
        return fail(exc.message, EXIT_ERROR)
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)

    return fail(f"unknown play command: {command}", EXIT_USAGE)


def cmd_voice(args: argparse.Namespace) -> int:
    """`voice ...` - measure media, keep human transcripts, and refuse speech by name.

    Exit codes: 0 the command did what it was asked; 2 the input made no sense (an empty file, a
    transcript with no words, an image asked for words) or an attempt was refused by the mode
    itself. A refusal is `EXIT_DEGRADED` (3) for `transcribe`/`say`, because nothing broke: the
    build genuinely cannot hear, and a script needs to tell that apart from "you typed nothing".
    """
    command = args.voice_command
    try:
        with _workspace(args) as ws:
            service = ws.voice

            if command == "probe":
                asset = service.probe(args.path, retain=args.retain, force=args.force)
                if args.json:
                    emit_json(asset)
                    return EXIT_OK
                if asset.get("duplicate"):
                    emit(f"already measured: {asset['id']}  ({asset['created_at']})")
                    emit(f"  measured  {asset['this_probe']['path']}  {asset['bytes']} bytes")
                else:
                    emit(f"measured {asset['id']}  {asset['described']}")
                emit(f"  format    {asset['format']}   bytes {asset['bytes']}")
                emit(f"  sha256    {asset['sha256'][:32]}...  ({asset['facts'].get('hash_scope', '-')})")
                if asset["kind"] == "audio" and asset["duration_ms"] is not None:
                    emit(f"  duration  {asset['duration_ms']} ms")
                if asset["name_mismatch"]:
                    emit(f"  note      {asset['name_mismatch']}")
                for note in asset["facts"].get("notes", []):
                    emit(f"  note      {note}")
                if asset.get("metadata", {}).get("retained_path"):
                    emit(f"  retained  {asset['metadata']['retained_path']}")
                emit(f"  next      archx-agent voice show {asset['id']}")
                return EXIT_OK

            if command == "list":
                assets = service.assets(kind=args.kind, limit=args.limit)
                if args.json:
                    emit_json(assets)
                    return EXIT_OK
                if not assets:
                    emit("nothing measured yet (archx-agent voice probe PATH)")
                    return EXIT_OK
                rows = []
                for asset in assets:
                    size = (
                        f"{asset['width']}x{asset['height']}" if asset.get("width") else
                        f"{asset['duration_ms']} ms" if asset.get("duration_ms") is not None else "-"
                    )
                    rows.append([
                        asset["id"], asset["kind"], asset["format"], size,
                        asset["bytes"], "yes" if asset["name_mismatch"] else "no",
                        asset["created_at"],
                    ])
                emit(table(rows, ["id", "kind", "format", "size", "bytes", "mislabelled", "created"]))
                return EXIT_OK

            if command == "show":
                shown = service.view(args.asset)
                if args.json:
                    emit_json(shown)
                    return EXIT_OK
                emit(f"{shown['id']}  {shown['described']}")
                emit(f"  path      {shown['path']}")
                emit(f"  sha256    {shown['sha256']}")
                if shown["name_mismatch"]:
                    emit(f"  note      {shown['name_mismatch']}")
                for note in shown["facts"].get("notes", []):
                    emit(f"  note      {note}")
                if shown["transcripts"]:
                    emit("")
                    emit("  words:")
                    for transcript in shown["transcripts"]:
                        emit(f"    [{transcript['source']}] {transcript['text'][:100]}")
                else:
                    emit("")
                    emit("  words     none - this build cannot recognise speech")
                if shown["attempts"]:
                    emit("")
                    for attempt in shown["attempts"][:6]:
                        line = f"  {attempt['status']:<9} {attempt['action']:<10} {attempt['created_at']}"
                        emit(line)
                        if attempt["reason"]:
                            emit(f"    {attempt['reason'][:140]}")
                return EXIT_OK

            if command == "transcribe":
                result = service.transcribe(args.asset)
                if args.json:
                    emit_json(result)
                    return EXIT_DEGRADED
                emit(f"refused {result['asset_id']}  (attempt {result['attempt_id']})")
                for reason in result["reasons"]:
                    emit(f"  - {reason}")
                emit("")
                emit(f"  what you can do: {result['fix']}")
                return EXIT_DEGRADED

            if command == "say":
                result = service.say(args.text)
                if args.json:
                    emit_json(result)
                    return EXIT_DEGRADED
                emit(f"refused: nothing was synthesised  ({result['chars']} characters asked for)")
                for reason in result["reasons"]:
                    emit(f"  - {reason}")
                return EXIT_DEGRADED

            if command == "transcript":
                if args.transcript_command == "list":
                    transcripts = service.transcripts(args.asset)
                    if args.json:
                        emit_json(transcripts)
                        return EXIT_OK
                    if not transcripts:
                        emit("no words recorded for that asset")
                        return EXIT_OK
                    for transcript in transcripts:
                        emit(f"{transcript['id']}  [{transcript['source']}]  "
                             f"{transcript['chars']} chars  {transcript['created_at']}")
                        emit(f"  {transcript['text'][:200]}")
                    return EXIT_OK
                transcript = service.add_transcript(
                    args.asset, text=args.text, path=args.file
                )
                if args.json:
                    emit_json(transcript)
                    return EXIT_OK
                emit(f"recorded {transcript['id']}  [{transcript['source']}]  "
                     f"{transcript['chars']} chars")
                emit("  these are the words a person wrote; nothing recognised them")
                return EXIT_OK

            if command == "attempts":
                attempts = service.attempts(asset_id=args.asset, limit=args.limit)
                if args.json:
                    emit_json(attempts)
                    return EXIT_OK
                if not attempts:
                    emit("no attempts yet")
                    return EXIT_OK
                rows = [
                    [a["id"], a["action"], a["status"], a["asset_id"] or "-",
                     a["engine"] or "-", (a["reason"] or "")[:40], a["created_at"]]
                    for a in attempts
                ]
                emit(table(rows, ["id", "action", "status", "asset", "engine", "why", "when"]))
                return EXIT_OK

            if command == "stats":
                data = service.stats()
                if args.json:
                    emit_json(data)
                    return EXIT_OK
                emit(f"assets      {data['assets']} ({data['images']} image, "
                     f"{data['audio']} audio, {data['audio_ms']} ms of audio)")
                emit(f"mislabelled {data['mislabelled']} (the name disagrees with the bytes)")
                emit(f"transcripts {data['transcripts']} (all written by a person)")
                emit(f"attempts    {data['attempts']} ({data['refused']} refused)")
                emit(f"voice       {'on' if data['enabled'] else 'off'}; "
                     f"stt {data['stt_model'] or 'none'}, tts {data['tts_model'] or 'none'}")
                emit(f"can hear    {'yes' if data['can_transcribe'] else 'no'}")
                emit(f"can speak   {'yes' if data['can_speak'] else 'no'}")
                return EXIT_OK

    except NotFoundError as exc:
        return fail(exc.message, EXIT_ERROR)
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)
    except ArchxError as exc:
        return fail(exc.message, EXIT_ERROR)

    return fail(f"unknown voice command: {command}", EXIT_USAGE)


def cmd_dataset(args: argparse.Namespace) -> int:
    """`dataset ...` - prepare a corpus and keep every decision visible.

    Exit codes: 0 the step ran; 1 nothing matching that id or name; 2 the input made no sense (no
    sources, ratios that do not add up, cleaning before scanning) or a step was refused by the
    data itself - a leak across splits, a manifest that does not match the files. The refusal is
    exit 2, not a crash, because a corpus that cannot be split is a fact about the corpus.
    """
    command = args.dataset_command
    try:
        with _workspace(args) as ws:
            service = ws.data

            if command == "create":
                created = service.create(
                    args.name, list(args.source), license=args.license, notes=args.notes
                )
                if args.json:
                    emit_json(created)
                    return EXIT_OK
                emit(f"created {created['id']}  {created['name']!r}  ({created['status']})")
                emit(f"  sources   {', '.join(created['sources'])}")
                emit(f"  license   {created['license']}  ({created['license_note']})")
                emit(f"  next      archx-agent dataset scan {created['id']}")
                return EXIT_OK

            if command == "scan":
                scanned = service.scan(args.dataset)
                if args.json:
                    emit_json(scanned)
                    return EXIT_OK
                counts = scanned["counts"]
                emit(f"scanned {scanned['id']}  {counts['kept']} kept, {counts['dropped']} dropped")
                for record in scanned["records"] if "records" in scanned else service.records(
                    scanned["id"], limit=50
                ):
                    mark = "kept " if record["status"] == "kept" else "drop "
                    lines = record["lines"] or 0
                    detail = record["reason"] or (
                        f"{record['chars']} chars, {lines} line{'' if lines == 1 else 's'}"
                    )
                    emit(f"  {mark} {record['path']:<40} {detail}")
                emit(f"  next   archx-agent dataset clean {scanned['id']}")
                return EXIT_OK

            if command == "clean":
                cleaned = service.clean(
                    args.dataset,
                    min_chars=args.min_chars,
                    dedupe=args.dedupe,
                    normalize=args.normalize,
                    drop_empty=args.drop_empty,
                    require_license=args.require_license,
                )
                if args.json:
                    emit_json(cleaned)
                    return EXIT_OK
                step = [s for s in cleaned["transforms"] if s["kind"] == "clean"][-1]
                counts = cleaned["counts"]
                emit(f"cleaned {cleaned['id']}  {step['records_in']} -> {step['records_out']} kept")
                for rule, removed in sorted(step["report"]["removed"].items()):
                    if removed:
                        emit(f"  {rule:<10} removed {removed}")
                emit(f"  dropped  {counts['dropped']} records - each one kept with its reason")
                emit(f"  next     archx-agent dataset split {cleaned['id']} --seed 42")
                return EXIT_OK

            if command == "split":
                split = service.split(
                    args.dataset, train=args.train, val=args.val, test=args.test, seed=args.seed
                )
                if args.json:
                    emit_json(split)
                    return EXIT_OK
                by_split = split["splits"]["by_split"]
                emit(f"split {split['id']}  seed {split['seed']!r}")
                for name in ("train", "val", "test"):
                    emit(f"  {name:<6} {by_split.get(name, 0)}")
                emit("  each record's split follows from its own hash, so adding a file "
                     "tomorrow does not move today's rows")
                emit(f"  next   archx-agent dataset build {split['id']}")
                return EXIT_OK

            if command == "build":
                built = service.build(args.dataset, force=args.force)
                if args.json:
                    emit_json(built)
                    return EXIT_OK
                emit(f"built {built['id']}  {built['path']}  ({built['counts']['kept']} records)")
                emit(f"  manifest  {built['checksum']}")
                emit(f"  export    {built['metadata']['export_bytes']} bytes, "
                     f"sha256 {built['metadata']['export_checksum'][:16]}...")
                emit(f"  local     {built['metadata']['local_copy']}")
                emit(f"  next      archx-agent dataset verify {built['id']}")
                return EXIT_OK

            if command == "verify":
                result = service.verify(args.dataset)
                if args.json:
                    emit_json(result)
                    return EXIT_DEGRADED if not result["agrees"] else EXIT_OK
                emit(f"verify {result['dataset_id']}  {result['checked']} records checked")
                emit(f"  stored     {result['stored_checksum'] or '(none - never built)'}")
                emit(f"  recomputed {result['recomputed_checksum']}")
                emit(f"  {result['note']}")
                for difference in result["differences"][:10]:
                    if difference["kind"] == "changed":
                        emit(f"  changed   {difference['path']}")
                        emit(f"            recorded {str(difference['recorded'])[:16]}  "
                             f"found {str(difference['found'])[:16]}")
                    else:
                        emit(f"  missing   {difference['path']}")
                if not result["agrees"]:
                    emit("")
                    emit("  the dataset no longer matches its manifest. Rebuild it and record the "
                         "new hash, or restore the files; do not describe the old hash as current.")
                    return EXIT_DEGRADED
                return EXIT_OK

            if command == "show":
                shown = service.view(args.dataset)
                if args.json:
                    emit_json(shown)
                    return EXIT_OK
                counts = shown["counts"]
                emit(f"{shown['id']}  {shown['name']!r}  ({shown['status']})")
                emit(f"  license   {shown['license']}  ({shown['license_note']})")
                emit(f"  sources   {', '.join(shown['sources']) or '-'}")
                emit(f"  records   {counts['kept']} kept, {counts['dropped']} dropped")
                if counts["by_split"]:
                    emit("  splits    " + ", ".join(
                        f"{name} {count}" for name, count in sorted(counts["by_split"].items())
                    ))
                emit(f"  seed      {shown['seed'] or '-'}")
                emit(f"  manifest  {shown['checksum'] or '(not built)'}")
                if shown["path"]:
                    emit(f"  export    {shown['path']}")
                if shown["transforms"]:
                    emit("")
                    emit("  ledger:")
                    for step in shown["transforms"]:
                        emit(f"    {step['seq']}. {step['kind']:<7} "
                             f"{step['records_in']} -> {step['records_out']}  {step['created_at']}")
                return EXIT_OK

            if command == "records":
                records = service.records(
                    args.dataset, status=args.status, split=args.split, limit=args.limit
                )
                if args.json:
                    emit_json(records)
                    return EXIT_OK
                if not records:
                    emit("no records (archx-agent dataset scan DATASET)")
                    return EXIT_OK
                rows = [
                    [record["status"], record["split"] or "-", record["path"],
                     record["chars"] if record["chars"] is not None else "-",
                     (record["reason"] or "")[:44]]
                    for record in records
                ]
                emit(table(rows, ["status", "split", "path", "chars", "why"]))
                return EXIT_OK

            if command == "explain":
                explained = service.explain(args.record)
                if args.json:
                    emit_json(explained)
                    return EXIT_OK
                emit(explained["sentence"])
                for step in explained["steps"]:
                    emit(f"  {step['seq']}. {step['kind']:<7} {step['records_out']} records out")
                return EXIT_OK

            if command == "steps":
                steps = service.steps(args.dataset)
                if args.json:
                    emit_json(steps)
                    return EXIT_OK
                if not steps:
                    emit("no steps yet")
                    return EXIT_OK
                rows = [
                    [step["seq"], step["kind"], step["records_in"], step["records_out"],
                     json.dumps(step["report"])[:60], step["created_at"]]
                    for step in steps
                ]
                emit(table(rows, ["seq", "step", "in", "out", "report", "when"]))
                return EXIT_OK

            if command == "list":
                datasets = service.list(limit=args.limit)
                if args.json:
                    emit_json(datasets)
                    return EXIT_OK
                if not datasets:
                    emit("no datasets yet (archx-agent dataset create NAME --source PATH)")
                    return EXIT_OK
                rows = [
                    [dataset["id"], dataset["name"], dataset["status"],
                     dataset["record_count"] if dataset["record_count"] is not None else "-",
                     dataset["dropped_count"], dataset["license"], dataset["created_at"]]
                    for dataset in datasets
                ]
                emit(table(rows, ["id", "name", "status", "kept", "dropped", "license", "created"]))
                return EXIT_OK

            if command == "stats":
                data = service.stats()
                if args.json:
                    emit_json(data)
                    return EXIT_OK
                emit(f"datasets  {data['datasets']}  " +
                     ", ".join(f"{k} {v}" for k, v in sorted(data["by_status"].items())))
                emit(f"records   {data['records']} ({data['kept']} kept, {data['dropped']} dropped)")
                emit(f"bytes     {data['bytes_kept']} kept")
                emit(f"states    {' -> '.join(data['states'])}")
                emit("this build prepares corpora on this machine; it does not train on them "
                     "or send them anywhere")
                return EXIT_OK

    except NotFoundError as exc:
        return fail(exc.message, EXIT_ERROR)
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)
    except ArchxError as exc:
        return fail(exc.message, EXIT_ERROR)

    return fail(f"unknown dataset command: {command}", EXIT_USAGE)


HANDLERS = {
    "init": cmd_init,
    "info": cmd_info,
    "doctor": cmd_doctor,
    "config": cmd_config,
    "models": cmd_models,
    "chat": cmd_chat,
    "conv": cmd_conv,
    "memory": cmd_memory,
    "projects": cmd_projects,
    "providers": cmd_providers,
    "context": cmd_context,
    "embeddings": cmd_embeddings,
    "tools": cmd_tools,
    "permissions": cmd_permissions,
    "approvals": cmd_approvals,
    "mcp": cmd_mcp,
    "extensions": cmd_extensions,
    "agent": cmd_agent,
    "jobs": cmd_jobs,
    "search": cmd_search,
    "simple": cmd_simple,
    "research": cmd_research,
    "learning": cmd_learning,
    "code": cmd_code,
    "experiment": cmd_experiment,
    "play": cmd_play,
    "voice": cmd_voice,
    "dataset": cmd_dataset,
    "gui": cmd_gui,
    "tasks": cmd_tasks,
    "versions": cmd_versions,
    "eval": cmd_eval,
    "db": cmd_db,
    "trace": cmd_trace,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = HANDLERS.get(args.command)
    if handler is None:  # pragma: no cover - argparse enforces choices
        parser.print_help()
        return EXIT_USAGE
    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)
    except ArchxError as exc:
        return fail(f"{type(exc).__name__}: {exc.message}")
    except BrokenPipeError:  # pragma: no cover
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
