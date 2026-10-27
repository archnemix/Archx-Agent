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
from archx_agent.helpers.exceptions import ArchxError, ProviderError, ValidationError
from archx_agent.helpers.jsonio import json_text
from archx_agent.managers.memory import CATEGORIES, KINDS as MEMORY_KINDS, MemoryManager
from archx_agent.managers.models import VERIFICATION_STATES

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
        try:
            cfg.set(args.key, args.value, source="cli")
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
