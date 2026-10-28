"""Domain schema migrations.

Version blocks are permanent. Never renumber a released migration: the journal
and the ``schema_migrations`` table record applied versions, so renaming a
migration's content in place would silently diverge between machines.

    1  conversations & messages
    2  projects (project identity for Project Memory etc.)
    3  memory foundation (six systems, history, sources, artifacts)
    4  context manifests & summaries
    5  tasks, agent runs, artifacts, version links
    6  tools, permissions, approvals, MCP servers, extensions
    7  scheduler & jobs
    8  research, learning, experiments, play, media, datasets, training, remote, automations
    9  retrieval helpers (embeddings, indexes)
    10 model catalogue + providers + credential references
    11 context proposals (ai_proposed strategy)
    12 providers, privacy metadata, availability checks, usage/quotas
    13 tool permissions: grant usage counting, approval requests
    14 MCP servers/tools and extension trust
    15 task history: ordered task timeline, ordered content versions, repro indexes
    16 agent workflows: definitions, ordered step records
    17 scheduler: job attempts, timeouts, claim bookkeeping
    18 researcher mode: plans, coverage, sources that failed, the report itself
    19 learning mode: goals with criteria, reviewable items with a schedule, sessions, attempts
    20 research closure, 21 coding workspace, 22 experiments, 23 play, 24 media and voice
    25 datasets: a candidate record kept or dropped *with its reason*, and a manifest hash
"""

from __future__ import annotations

from archx_agent.helpers.sqlite_store import Migration

CONVERSATIONS_V1 = Migration(
    version=1,
    name="conversations",
    statements=(
        "CREATE TABLE IF NOT EXISTS conversations ("
        " id TEXT PRIMARY KEY,"
        " title TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_seq INTEGER NOT NULL DEFAULT 0,"
        " project_id TEXT,"
        " model_id TEXT,"
        " context_strategy TEXT,"
        " archived INTEGER NOT NULL DEFAULT 0,"
        " deleted_at TEXT,"
        " pinned INTEGER NOT NULL DEFAULT 0,"
        " metadata TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id)",
        "CREATE TABLE IF NOT EXISTS messages ("
        " id TEXT PRIMARY KEY,"
        " conversation_id TEXT NOT NULL,"
        " seq INTEGER NOT NULL,"
        " role TEXT NOT NULL,"
        " content TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " token_estimate INTEGER NOT NULL DEFAULT 0,"
        " pinned INTEGER NOT NULL DEFAULT 0,"
        " excluded INTEGER NOT NULL DEFAULT 0,"
        " tool_calls TEXT,"
        " tool_results TEXT,"
        " metadata TEXT,"
        " UNIQUE(conversation_id, seq))",
        "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, seq)",
        "CREATE TABLE IF NOT EXISTS conversation_settings ("
        " conversation_id TEXT PRIMARY KEY,"
        " key TEXT NOT NULL,"
        " value TEXT NOT NULL)",
    ),
)

PROJECTS_V2 = Migration(
    version=2,
    name="projects",
    statements=(
        "CREATE TABLE IF NOT EXISTS projects ("
        " id TEXT PRIMARY KEY,"
        " slug TEXT NOT NULL UNIQUE,"
        " name TEXT NOT NULL,"
        " root_path TEXT,"
        " description TEXT,"
        " status TEXT NOT NULL DEFAULT 'active',"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " metadata TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)",
    ),
)

MEMORY_V3 = Migration(
    version=3,
    name="memory",
    statements=(
        "CREATE TABLE IF NOT EXISTS memories ("
        " id TEXT PRIMARY KEY,"
        " kind TEXT NOT NULL,"
        " scope TEXT NOT NULL,"
        " scope_id TEXT,"
        " slot TEXT,"
        " title TEXT NOT NULL,"
        " content TEXT NOT NULL,"
        " summary TEXT,"
        " category TEXT NOT NULL,"
        " project_id TEXT,"
        " conversation_id TEXT,"
        " task_id TEXT,"
        " source TEXT NOT NULL,"
        " provenance TEXT NOT NULL,"
        " confidence REAL NOT NULL DEFAULT 0.8,"
        " status TEXT NOT NULL DEFAULT 'active',"
        " pinned INTEGER NOT NULL DEFAULT 0,"
        " tags TEXT,"
        " details TEXT,"
        " evidence TEXT,"
        " verification TEXT,"
        " environment TEXT,"
        " limitations TEXT,"
        " worked INTEGER,"
        " expires_at TEXT,"
        " last_accessed_at TEXT,"
        " access_count INTEGER NOT NULL DEFAULT 0,"
        " duplicate_of TEXT,"
        " supersedes TEXT,"
        " version INTEGER NOT NULL DEFAULT 1,"
        " embedding_state TEXT NOT NULL DEFAULT 'awaiting',"
        " embedding_ref TEXT,"
        " artifact_path TEXT,"
        " checksum TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " deleted_at TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_memories_kind_scope ON memories(kind, scope, scope_id)",
        "CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status)",
        "CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)",
        "CREATE TABLE IF NOT EXISTS memory_history ("
        " hid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " memory_id TEXT NOT NULL,"
        " version INTEGER NOT NULL,"
        " change TEXT NOT NULL,"
        " snapshot TEXT NOT NULL,"
        " changed_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_memory_history_memory ON memory_history(memory_id, version)",
        "CREATE TABLE IF NOT EXISTS memory_sources ("
        " sid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " memory_id TEXT NOT NULL,"
        " source_type TEXT NOT NULL,"
        " reference TEXT,"
        " excerpt TEXT,"
        " retrieved_at TEXT NOT NULL,"
        " checksum TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_memory_sources_memory ON memory_sources(memory_id)",
        "CREATE TABLE IF NOT EXISTS memory_retrievals ("
        " rid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " memory_id TEXT NOT NULL,"
        " used_at TEXT NOT NULL,"
        " reason TEXT,"
        " budget_tokens INTEGER,"
        " consumed_tokens INTEGER,"
        " conversation_id TEXT,"
        " task_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_memory_retrievals_memory ON memory_retrievals(memory_id)",
        "CREATE TABLE IF NOT EXISTS learning_events ("
        " id TEXT PRIMARY KEY,"
        " goal_id TEXT,"
        " topic TEXT NOT NULL,"
        " outcome TEXT NOT NULL,"
        " attempts INTEGER NOT NULL DEFAULT 1,"
        " mistakes TEXT,"
        " duration_seconds INTEGER,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_learning_events_topic ON learning_events(topic)",
    ),
)

CONTEXT_V4 = Migration(
    version=4,
    name="context",
    statements=(
        "CREATE TABLE IF NOT EXISTS context_manifests ("
        " id TEXT PRIMARY KEY,"
        " conversation_id TEXT NOT NULL,"
        " message_id TEXT,"
        " strategy TEXT NOT NULL,"
        " token_budget INTEGER NOT NULL,"
        " tokens_used INTEGER NOT NULL,"
        " omitted TEXT NOT NULL DEFAULT '[]',"
        " included TEXT NOT NULL DEFAULT '[]',"
        " notes TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_context_manifests_conversation ON context_manifests(conversation_id)",
        "CREATE TABLE IF NOT EXISTS summaries ("
        " id TEXT PRIMARY KEY,"
        " conversation_id TEXT NOT NULL,"
        " source_start_seq INTEGER NOT NULL,"
        " source_end_seq INTEGER NOT NULL,"
        " content TEXT NOT NULL,"
        " token_estimate INTEGER NOT NULL,"
        " generator TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " superseded_by TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_summaries_conversation ON summaries(conversation_id, source_start_seq)",
    ),
)

TASKS_V5 = Migration(
    version=5,
    name="tasks-history",
    statements=(
        "CREATE TABLE IF NOT EXISTS tasks ("
        " id TEXT PRIMARY KEY,"
        " type TEXT NOT NULL,"
        " title TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " conversation_id TEXT,"
        " project_id TEXT,"
        " parent_task_id TEXT,"
        " run_id TEXT,"
        " created_at TEXT NOT NULL,"
        " started_at TEXT,"
        " completed_at TEXT,"
        " model_id TEXT,"
        " agents TEXT,"
        " tools TEXT,"
        " resource_use TEXT,"
        " cost_estimate REAL,"
        " input_refs TEXT,"
        " output_refs TEXT,"
        " error TEXT,"
        " unresolved TEXT,"
        " trace_event_id TEXT,"
        " version_info TEXT,"
        " metadata TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_conversation ON tasks(conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)",
        "CREATE TABLE IF NOT EXISTS artifacts ("
        " id TEXT PRIMARY KEY,"
        " task_id TEXT,"
        " project_id TEXT,"
        " kind TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " path TEXT NOT NULL,"
        " rel_path TEXT,"
        " checksum TEXT,"
        " size INTEGER,"
        " mime TEXT,"
        " created_at TEXT NOT NULL,"
        " metadata TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id)",
        "CREATE TABLE IF NOT EXISTS version_records ("
        " id TEXT PRIMARY KEY,"
        " subject_type TEXT NOT NULL,"
        " subject_id TEXT NOT NULL,"
        " version TEXT NOT NULL,"
        " content TEXT NOT NULL,"
        " checksum TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " created_by TEXT,"
        " note TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_version_records_subject ON version_records(subject_type, subject_id)",
        "CREATE TABLE IF NOT EXISTS reproduction_records ("
        " id TEXT PRIMARY KEY,"
        " task_id TEXT NOT NULL,"
        " fidelity TEXT NOT NULL,"
        " blockers TEXT,"
        " environment TEXT,"
        " commands TEXT,"
        " created_at TEXT NOT NULL)",
    ),
)

TOOLS_V6 = Migration(
    version=6,
    name="tools-permissions",
    statements=(
        "CREATE TABLE IF NOT EXISTS permission_grants ("
        " id TEXT PRIMARY KEY,"
        " scope TEXT NOT NULL,"
        " capability TEXT NOT NULL,"
        " subject TEXT NOT NULL,"
        " constraints TEXT,"
        " duration TEXT NOT NULL,"
        " granted_by TEXT NOT NULL,"
        " reason TEXT,"
        " created_at TEXT NOT NULL,"
        " expires_at TEXT,"
        " revoked_at TEXT,"
        " revoked_by TEXT,"
        " conversation_id TEXT,"
        " task_id TEXT,"
        " project_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_perm_lookup ON permission_grants(capability, subject)",
        "CREATE INDEX IF NOT EXISTS idx_perm_scope ON permission_grants(scope, scope)",
        "CREATE TABLE IF NOT EXISTS tool_runs ("
        " id TEXT PRIMARY KEY,"
        " task_id TEXT,"
        " tool_name TEXT NOT NULL,"
        " arguments TEXT,"
        " status TEXT NOT NULL,"
        " result TEXT,"
        " started_at TEXT NOT NULL,"
        " ended_at TEXT,"
        " duration_ms REAL,"
        " error TEXT,"
        " permission_id TEXT,"
        " trace_event_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_tool_runs_tool ON tool_runs(tool_name, started_at)",
        "CREATE TABLE IF NOT EXISTS mcp_servers ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL UNIQUE,"
        " transport TEXT NOT NULL,"
        " command TEXT,"
        " args TEXT,"
        " url TEXT,"
        " env TEXT,"
        " enabled INTEGER NOT NULL DEFAULT 0,"
        " trusted INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_connected_at TEXT,"
        " last_error TEXT)",
        "CREATE TABLE IF NOT EXISTS mcp_tools ("
        " server_id TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " description TEXT,"
        " schema TEXT,"
        " enabled INTEGER NOT NULL DEFAULT 0,"
        " discovered_at TEXT NOT NULL,"
        " PRIMARY KEY(server_id, name))",
        "CREATE TABLE IF NOT EXISTS extensions ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL UNIQUE,"
        " version TEXT NOT NULL,"
        " path TEXT,"
        " manifest TEXT NOT NULL,"
        " trust TEXT NOT NULL DEFAULT 'untrusted',"
        " enabled INTEGER NOT NULL DEFAULT 0,"
        " installed_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_error TEXT)",
    ),
)

JOBS_V7 = Migration(
    version=7,
    name="scheduler",
    statements=(
        "CREATE TABLE IF NOT EXISTS jobs ("
        " id TEXT PRIMARY KEY,"
        " kind TEXT NOT NULL,"
        " title TEXT NOT NULL,"
        " payload TEXT,"
        " status TEXT NOT NULL,"
        " priority INTEGER NOT NULL DEFAULT 5,"
        " queue_seq INTEGER NOT NULL,"
        " created_at TEXT NOT NULL,"
        " started_at TEXT,"
        " ended_at TEXT,"
        " deadline TEXT,"
        " progress REAL NOT NULL DEFAULT 0,"
        " message TEXT,"
        " error TEXT,"
        " resource_estimate TEXT,"
        " resource_observed TEXT,"
        " result TEXT,"
        " task_id TEXT,"
        " project_id TEXT,"
        " cancelled INTEGER NOT NULL DEFAULT 0)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, queue_seq)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_kind ON jobs(kind)",
    ),
)

FEATURES_V8 = Migration(
    version=8,
    name="feature-modes",
    statements=(
        "CREATE TABLE IF NOT EXISTS research_runs ("
        " id TEXT PRIMARY KEY, status TEXT NOT NULL, question TEXT NOT NULL,"
        " subquestions TEXT, report_path TEXT, report_format TEXT,"
        " created_at TEXT NOT NULL, completed_at TEXT, limitations TEXT, task_id TEXT)",
        "CREATE TABLE IF NOT EXISTS research_sources ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, url TEXT NOT NULL,"
        " title TEXT, publisher TEXT, retrieved_at TEXT NOT NULL, excerpt TEXT,"
        " subsection TEXT, limitations TEXT, stance TEXT)",
        "CREATE TABLE IF NOT EXISTS learning_goals ("
        " id TEXT PRIMARY KEY, title TEXT NOT NULL, objective TEXT NOT NULL, level TEXT,"
        " status TEXT NOT NULL, path TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS learning_lessons ("
        " id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, topic TEXT NOT NULL, subtopic TEXT,"
        " position INTEGER NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,"
        " best_score REAL, content TEXT, exercise TEXT, updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS experiments ("
        " id TEXT PRIMARY KEY, title TEXT NOT NULL, hypothesis TEXT, baseline TEXT,"
        " target TEXT, criteria TEXT, status TEXT NOT NULL, deadline TEXT,"
        " config TEXT, created_at TEXT NOT NULL, completed_at TEXT, report_path TEXT, task_id TEXT)",
        "CREATE TABLE IF NOT EXISTS experiment_steps ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL, kind TEXT NOT NULL,"
        " description TEXT, changes TEXT, measurement TEXT, result TEXT, created_at TEXT NOT NULL, seq INTEGER)",
        "CREATE TABLE IF NOT EXISTS games ("
        " id TEXT PRIMARY KEY, game_type TEXT NOT NULL, status TEXT NOT NULL,"
        " state TEXT NOT NULL, config TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, winner TEXT)",
        "CREATE TABLE IF NOT EXISTS game_moves ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL, seq INTEGER NOT NULL,"
        " player TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL, legal INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS media_jobs ("
        " id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, prompt TEXT,"
        " model_id TEXT, output_path TEXT, metadata TEXT, created_at TEXT NOT NULL, completed_at TEXT, error TEXT, task_id TEXT)",
        "CREATE TABLE IF NOT EXISTS datasets ("
        " id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL, revision TEXT,"
        " license TEXT, format TEXT, record_count INTEGER, path TEXT, checksum TEXT,"
        " created_at TEXT NOT NULL, task_id TEXT, metadata TEXT)",
        "CREATE TABLE IF NOT EXISTS dataset_transforms ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id TEXT NOT NULL, seq INTEGER NOT NULL,"
        " kind TEXT NOT NULL, config TEXT NOT NULL, records_in INTEGER, records_out INTEGER,"
        " created_at TEXT NOT NULL, output_path TEXT, report TEXT)",
        "CREATE TABLE IF NOT EXISTS training_jobs ("
        " id TEXT PRIMARY KEY, method TEXT NOT NULL, base_model TEXT, dataset_id TEXT,"
        " status TEXT NOT NULL, config TEXT, preflight TEXT, metrics TEXT, checkpoints TEXT,"
        " created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, error TEXT, task_id TEXT)",
        "CREATE TABLE IF NOT EXISTS remote_jobs ("
        " id TEXT PRIMARY KEY, provider TEXT NOT NULL, status TEXT NOT NULL, config TEXT,"
        " estimate TEXT, actual TEXT, outputs TEXT, created_at TEXT NOT NULL,"
        " completed_at TEXT, error TEXT, approved_by TEXT, task_id TEXT)",
        "CREATE TABLE IF NOT EXISTS automations ("
        " id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, schedule TEXT NOT NULL,"
        " enabled INTEGER NOT NULL DEFAULT 1, config TEXT, permissions TEXT,"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_run_at TEXT,"
        " next_run_at TEXT, last_status TEXT, retry_policy TEXT)",
        "CREATE TABLE IF NOT EXISTS automation_runs ("
        " id TEXT PRIMARY KEY, automation_id TEXT NOT NULL, status TEXT NOT NULL,"
        " started_at TEXT NOT NULL, ended_at TEXT, output TEXT, error TEXT, task_id TEXT)",
    ),
)

RETRIEVAL_V9 = Migration(
    version=9,
    name="retrieval",
    statements=(
        "CREATE TABLE IF NOT EXISTS embeddings ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " owner_type TEXT NOT NULL,"
        " owner_id TEXT NOT NULL,"
        " model_id TEXT NOT NULL,"
        " dim INTEGER NOT NULL,"
        " vector BLOB NOT NULL,"
        " checksum TEXT NOT NULL,"
        " state TEXT NOT NULL DEFAULT 'embedded',"
        " created_at TEXT NOT NULL,"
        " UNIQUE(owner_type, owner_id, model_id))",
        "CREATE INDEX IF NOT EXISTS idx_embeddings_owner ON embeddings(owner_type, owner_id)",
        "CREATE TABLE IF NOT EXISTS retrieval_runs ("
        " id TEXT PRIMARY KEY,"
        " query TEXT NOT NULL,"
        " mode TEXT NOT NULL,"
        " model_id TEXT,"
        " results INTEGER NOT NULL,"
        " degraded INTEGER NOT NULL DEFAULT 0,"
        " notes TEXT,"
        " created_at TEXT NOT NULL)",
    ),
)

MODELS_V10 = Migration(
    version=10,
    name="model-catalogue",
    statements=(
        "CREATE TABLE IF NOT EXISTS models ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " provider TEXT NOT NULL,"
        " runtime TEXT NOT NULL,"
        " path TEXT,"
        " model_ref TEXT,"
        " format TEXT,"
        " quantization TEXT,"
        " param_count TEXT,"
        " context_length INTEGER,"
        " size_bytes INTEGER,"
        " sha256 TEXT,"
        " facts TEXT NOT NULL DEFAULT '{}',"
        " claims TEXT NOT NULL DEFAULT '{}',"
        " user_metadata TEXT NOT NULL DEFAULT '{}',"
        " verified_capabilities TEXT NOT NULL DEFAULT '[]',"
        " capability_basis TEXT NOT NULL DEFAULT '{}',"
        " verification_state TEXT NOT NULL DEFAULT 'unverified',"
        " state TEXT NOT NULL DEFAULT 'usable',"
        " tags TEXT NOT NULL DEFAULT '[]',"
        " notes TEXT,"
        " success_count INTEGER NOT NULL DEFAULT 0,"
        " failure_count INTEGER NOT NULL DEFAULT 0,"
        " discovered_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_used_at TEXT,"
        " last_error TEXT)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_models_identity"
        " ON models(provider, COALESCE(path,''), COALESCE(model_ref,''))",
        "CREATE INDEX IF NOT EXISTS idx_models_state ON models(state)",
        "CREATE INDEX IF NOT EXISTS idx_models_runtime ON models(runtime)",
        "CREATE TABLE IF NOT EXISTS model_capability_tests ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " model_id TEXT NOT NULL,"
        " capability TEXT NOT NULL,"
        " outcome TEXT NOT NULL,"
        " detail TEXT,"
        " latency_ms REAL,"
        " resources TEXT,"
        " run_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_cap_tests_model ON model_capability_tests(model_id, capability)",
        "CREATE TABLE IF NOT EXISTS providers ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL UNIQUE,"
        " kind TEXT NOT NULL,"
        " base_url TEXT,"
        " enabled INTEGER NOT NULL DEFAULT 0,"
        " requires_credential INTEGER NOT NULL DEFAULT 0,"
        " credential_ref TEXT,"
        " privacy TEXT NOT NULL DEFAULT '{}',"
        " quotas TEXT NOT NULL DEFAULT '{}',"
        " claims TEXT NOT NULL DEFAULT '{}',"
        " verified INTEGER NOT NULL DEFAULT 0,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_checked_at TEXT,"
        " last_status TEXT,"
        " last_error TEXT)",
        "CREATE TABLE IF NOT EXISTS provider_usage ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " provider TEXT NOT NULL,"
        " model_id TEXT,"
        " kind TEXT NOT NULL,"
        " prompt_tokens INTEGER NOT NULL DEFAULT 0,"
        " completion_tokens INTEGER NOT NULL DEFAULT 0,"
        " cost_estimate REAL,"
        " success INTEGER NOT NULL DEFAULT 1,"
        " error_code TEXT,"
        " occurred_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_provider_usage_provider ON provider_usage(provider, occurred_at)",
        "CREATE TABLE IF NOT EXISTS credentials ("
        " id TEXT PRIMARY KEY,"
        " provider TEXT NOT NULL,"
        " ref TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " last_checked_at TEXT,"
        " valid INTEGER)",
    ),
)

CONTEXT_PROPOSALS_V11 = Migration(
    version=11,
    name="context-proposals",
    statements=(
        "CREATE TABLE IF NOT EXISTS context_proposals ("
        " id TEXT PRIMARY KEY,"
        " conversation_id TEXT NOT NULL,"
        " strategy TEXT NOT NULL,"
        " payload TEXT NOT NULL,"
        " rationale TEXT,"
        " estimated_tokens INTEGER,"
        " created_at TEXT NOT NULL,"
        " approved_at TEXT,"
        " applied_manifest_id TEXT,"
        " rejected_at TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_context_proposals_conversation ON context_proposals(conversation_id)",
    ),
)

PROVIDERS_V12 = Migration(
    version=12,
    name="provider-privacy",
    statements=(
        # v10 already created `providers` and `provider_usage`. Extending them is the
        # only honest option: a second catalogue would be a second source of truth.
        # `privacy` (v10) holds vendor *claims*; `privacy_confirmed` holds what the
        # user confirmed. They are separate columns on purpose.
        "ALTER TABLE providers ADD COLUMN slug TEXT",
        "ALTER TABLE providers ADD COLUMN api_style TEXT",
        "ALTER TABLE providers ADD COLUMN is_local INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE providers ADD COLUMN model_family TEXT",
        "ALTER TABLE providers ADD COLUMN privacy_confirmed TEXT",
        "ALTER TABLE providers ADD COLUMN claim_source TEXT",
        "ALTER TABLE providers ADD COLUMN price_in_per_1k REAL",
        "ALTER TABLE providers ADD COLUMN price_out_per_1k REAL",
        "ALTER TABLE providers ADD COLUMN currency TEXT",
        "ALTER TABLE providers ADD COLUMN notes TEXT",
        "ALTER TABLE providers ADD COLUMN consent_at TEXT",
        "ALTER TABLE providers ADD COLUMN consent_version TEXT",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_providers_slug ON providers(slug)",
        "CREATE INDEX IF NOT EXISTS idx_providers_kind ON providers(kind)",
        "CREATE TABLE IF NOT EXISTS provider_checks ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " provider_id TEXT NOT NULL,"
        " checked_at TEXT NOT NULL,"
        " status TEXT NOT NULL,"        # reachable | auth_failed | unreachable | model_missing | rate_limited
        " latency_ms REAL,"
        " detail TEXT,"
        " models_seen INTEGER)",
        "CREATE INDEX IF NOT EXISTS idx_provider_checks_provider ON provider_checks(provider_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_provider_usage_time ON provider_usage(provider, occurred_at)",
    ),
)

PERMISSIONS_V13 = Migration(
    version=13,
    name="tool-permissions",
    statements=(
        # v6 created permission_grants/tool_runs. Extending the same tables keeps one
        # source of truth for authority: a second grant table would be a second answer
        # to "is this allowed?".
        "ALTER TABLE permission_grants ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE permission_grants ADD COLUMN last_used_at TEXT",
        "ALTER TABLE permission_grants ADD COLUMN approval_id TEXT",
        "ALTER TABLE permission_grants ADD COLUMN notes TEXT",
        "CREATE INDEX IF NOT EXISTS idx_perm_grant_lookup"
        " ON permission_grants(capability, subject, revoked_at)",
        "ALTER TABLE tool_runs ADD COLUMN approval_id TEXT",
        "ALTER TABLE tool_runs ADD COLUMN dry_run INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tool_runs ADD COLUMN truncated INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tool_runs ADD COLUMN seq INTEGER",
        "CREATE INDEX IF NOT EXISTS idx_tool_runs_seq ON tool_runs(seq)",
        # An approval is a *request* for one capability on one subject in one scope.
        # Approving it can only mint exactly that grant: there is no field a caller
        # could use to widen it.
        "CREATE TABLE IF NOT EXISTS approval_requests ("
        " id TEXT PRIMARY KEY,"
        " capability TEXT NOT NULL,"
        " subject TEXT NOT NULL,"
        " scope TEXT NOT NULL,"
        " conversation_id TEXT,"
        " task_id TEXT,"
        " project_id TEXT,"
        " requested_by TEXT NOT NULL,"
        " purpose TEXT,"
        " payload TEXT,"
        " status TEXT NOT NULL,"          # pending | approved | denied | expired
        " created_at TEXT NOT NULL,"
        " expires_at TEXT,"
        " decided_at TEXT,"
        " decided_by TEXT,"
        " decision_reason TEXT,"
        " grant_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_approval_lookup"
        " ON approval_requests(capability, subject, status)",
    ),
)

MCP_V14 = Migration(
    version=14,
    name="mcp-extensions",
    statements=(
        # v6 already has mcp_servers/mcp_tools/extensions; these columns extend the same
        # records so there is one answer to "what is this server and may it run?".
        "ALTER TABLE mcp_servers ADD COLUMN headers TEXT",
        "ALTER TABLE mcp_servers ADD COLUMN protocol_version TEXT",
        "ALTER TABLE mcp_servers ADD COLUMN last_status TEXT",
        "ALTER TABLE mcp_servers ADD COLUMN tools_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE mcp_servers ADD COLUMN last_error_at TEXT",
        "ALTER TABLE mcp_tools ADD COLUMN capability TEXT",
        "ALTER TABLE mcp_tools ADD COLUMN risk TEXT",
        "ALTER TABLE mcp_tools ADD COLUMN annotations TEXT",
        "ALTER TABLE mcp_tools ADD COLUMN last_synced_at TEXT",
        "CREATE INDEX IF NOT EXISTS idx_mcp_tools_name ON mcp_tools(name)",
        "ALTER TABLE extensions ADD COLUMN manifest_hash TEXT",
        "ALTER TABLE extensions ADD COLUMN trusted_by TEXT",
        "ALTER TABLE extensions ADD COLUMN trusted_at TEXT",
        "ALTER TABLE extensions ADD COLUMN notes TEXT",
        "CREATE TABLE IF NOT EXISTS extension_tools ("
        " id TEXT PRIMARY KEY,"
        " extension_id TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " description TEXT,"
        " capability TEXT,"
        " risk TEXT,"
        " schema TEXT,"
        " entry TEXT NOT NULL,"
        " enabled INTEGER NOT NULL DEFAULT 0,"
        " discovered_at TEXT NOT NULL,"
        " UNIQUE(extension_id, name))",
        "CREATE INDEX IF NOT EXISTS idx_extension_tools_name ON extension_tools(name)",
    ),
)

TASKS_V15 = Migration(
    version=15,
    name="task-history",
    statements=(
        # v5 created tasks/artifacts/version_records/reproduction_records. This block
        # adds the ordering and provenance those records need; it does not create a
        # second history. A task timeline is an explicit sequence, so it cannot
        # reorder itself when two steps happen inside the same millisecond.
        "CREATE TABLE IF NOT EXISTS task_log ("
        " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
        " task_id TEXT NOT NULL,"
        " at TEXT NOT NULL,"
        " kind TEXT NOT NULL,"
        " detail TEXT,"
        " event_id TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_task_log_task ON task_log(task_id, seq)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)",
        "ALTER TABLE version_records ADD COLUMN ordinal INTEGER",
        "ALTER TABLE version_records ADD COLUMN size INTEGER",
        "ALTER TABLE version_records ADD COLUMN restored_from TEXT",
        "ALTER TABLE version_records ADD COLUMN subject_key TEXT",
        "ALTER TABLE version_records ADD COLUMN content_stored INTEGER NOT NULL DEFAULT 1",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_version_records_ordinal"
        " ON version_records(subject_type, subject_id, ordinal)",
        "CREATE INDEX IF NOT EXISTS idx_artifacts_project ON artifacts(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_repro_task ON reproduction_records(task_id, created_at)",
        "ALTER TABLE reproduction_records ADD COLUMN app_version TEXT",
        "ALTER TABLE reproduction_records ADD COLUMN recorded_by TEXT",
    ),
)

WORKFLOWS_V16 = Migration(
    version=16,
    name="agent-workflows",
    statements=(
        # A workflow is a *definition* (data) plus ordered step records. It cannot grant
        # anything: every step that touches the machine goes through the tool registry and
        # therefore through the permission centre.
        "CREATE TABLE IF NOT EXISTS workflows ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " mode TEXT NOT NULL,"          # user | ai
        " status TEXT NOT NULL,"        # proposed | approved | running | completed | failed | cancelled
        " goal TEXT,"
        " definition TEXT NOT NULL,"
        " model_id TEXT,"
        " task_id TEXT,"
        " conversation_id TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " started_at TEXT,"
        " finished_at TEXT,"
        " error TEXT,"
        " metadata TEXT)",
        "CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status, created_at)",
        "CREATE TABLE IF NOT EXISTS workflow_steps ("
        " id TEXT PRIMARY KEY,"
        " workflow_id TEXT NOT NULL,"
        " seq INTEGER NOT NULL,"
        " kind TEXT NOT NULL,"
        " title TEXT,"
        " spec TEXT,"
        " status TEXT NOT NULL,"
        " started_at TEXT,"
        " ended_at TEXT,"
        " output TEXT,"
        " error TEXT,"
        " task_id TEXT,"
        " tokens INTEGER NOT NULL DEFAULT 0,"
        " metadata TEXT,"
        " UNIQUE(workflow_id, seq))",
        "CREATE INDEX IF NOT EXISTS idx_workflow_steps ON workflow_steps(workflow_id, seq)",
    ),
)

JOBS_V17 = Migration(
    version=17,
    name="scheduler-claims",
    statements=(
        # v7 created jobs. These columns are what a *worker* needs: who claimed the job,
        # which process is running it, how many attempts remain, and the queue index.
        "ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN timeout_seconds INTEGER",
        "ALTER TABLE jobs ADD COLUMN pid INTEGER",
        "ALTER TABLE jobs ADD COLUMN worker TEXT",
        "ALTER TABLE jobs ADD COLUMN requeued_at TEXT",
        "ALTER TABLE jobs ADD COLUMN control TEXT",
        "ALTER TABLE jobs ADD COLUMN cursor INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN dedupe_key TEXT",
        "CREATE INDEX IF NOT EXISTS idx_jobs_dedupe"
        " ON jobs(dedupe_key, status)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_queue"
        " ON jobs(status, priority DESC, queue_seq)",
    ),
)

RESEARCH_V18 = Migration(
    version=18,
    name="researcher-mode",
    statements=(
        # v8 reserved research_runs/research_sources. A research run needs more than a
        # question and a status: the plan it derived, what it could not establish, how much
        # of the question the evidence actually covered, and the report itself (so a report
        # is never only a file that may have been moved).
        "ALTER TABLE research_runs ADD COLUMN mode TEXT",
        "ALTER TABLE research_runs ADD COLUMN plan TEXT",
        "ALTER TABLE research_runs ADD COLUMN planned_by TEXT",
        "ALTER TABLE research_runs ADD COLUMN coverage REAL",
        "ALTER TABLE research_runs ADD COLUMN evidence_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE research_runs ADD COLUMN report TEXT",
        "ALTER TABLE research_runs ADD COLUMN error TEXT",
        "ALTER TABLE research_runs ADD COLUMN model_id TEXT",
        "ALTER TABLE research_runs ADD COLUMN settings TEXT",
        "ALTER TABLE research_runs ADD COLUMN updated_at TEXT",
        # A source is evidence or it is not. `kind`/`ref` say where it came from, `status`
        # says whether it was actually read, and the checksum makes the excerpt verifiable.
        "ALTER TABLE research_sources ADD COLUMN kind TEXT",
        "ALTER TABLE research_sources ADD COLUMN ref TEXT",
        "ALTER TABLE research_sources ADD COLUMN status TEXT",
        "ALTER TABLE research_sources ADD COLUMN error TEXT",
        "ALTER TABLE research_sources ADD COLUMN checksum TEXT",
        "ALTER TABLE research_sources ADD COLUMN bytes INTEGER",
        "ALTER TABLE research_sources ADD COLUMN relevance REAL",
        "ALTER TABLE research_sources ADD COLUMN credibility TEXT",
        "ALTER TABLE research_sources ADD COLUMN claims TEXT",
        "ALTER TABLE research_sources ADD COLUMN subquestion INTEGER",
        "CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_research_sources_run ON research_sources(run_id, id)",
    ),
)

LEARNING_V19 = Migration(
    version=19,
    name="learning-mode",
    statements=(
        # v8 reserved learning_goals/learning_lessons. M30 makes them real: a goal is a
        # promise with criteria, and a lesson is a *reviewable item* with its own schedule.
        "ALTER TABLE learning_goals ADD COLUMN topic TEXT",
        "ALTER TABLE learning_goals ADD COLUMN success_criteria TEXT",
        "ALTER TABLE learning_goals ADD COLUMN priority INTEGER NOT NULL DEFAULT 5",
        "ALTER TABLE learning_goals ADD COLUMN target_date TEXT",
        "ALTER TABLE learning_goals ADD COLUMN task_id TEXT",
        "ALTER TABLE learning_goals ADD COLUMN settings TEXT",
        "ALTER TABLE learning_goals ADD COLUMN completed_at TEXT",
        "ALTER TABLE learning_goals ADD COLUMN planned_by TEXT",
        "ALTER TABLE learning_goals ADD COLUMN source TEXT",
        # An item that cannot be scheduled cannot be reviewed. The interval, the ease and
        # the due date are stored, not recomputed from vibes at read time.
        "ALTER TABLE learning_lessons ADD COLUMN expected TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN hints TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN explanation TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN ease REAL NOT NULL DEFAULT 2.5",
        "ALTER TABLE learning_lessons ADD COLUMN interval_days REAL NOT NULL DEFAULT 0",
        "ALTER TABLE learning_lessons ADD COLUMN streak INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE learning_lessons ADD COLUMN lapses INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE learning_lessons ADD COLUMN correct_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE learning_lessons ADD COLUMN due_at TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN last_reviewed_at TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN created_at TEXT",
        "ALTER TABLE learning_lessons ADD COLUMN source TEXT",
        "CREATE TABLE IF NOT EXISTS learning_sessions ("
        " id TEXT PRIMARY KEY,"
        " goal_id TEXT NOT NULL,"
        " task_id TEXT,"
        " mode TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " started_at TEXT NOT NULL,"
        " ended_at TEXT,"
        " items_attempted INTEGER NOT NULL DEFAULT 0,"
        " items_correct INTEGER NOT NULL DEFAULT 0,"
        " hints_used INTEGER NOT NULL DEFAULT 0,"
        " graded_by TEXT,"
        " summary TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS learning_attempts ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " session_id TEXT,"
        " goal_id TEXT NOT NULL,"
        " item_id TEXT NOT NULL,"
        " answer TEXT,"
        " correct INTEGER NOT NULL DEFAULT 0,"
        " graded_by TEXT NOT NULL,"
        " self_rating INTEGER,"
        " hints_used INTEGER NOT NULL DEFAULT 0,"
        " feedback TEXT,"
        " interval_days REAL,"
        " due_at TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_learning_items_goal ON learning_lessons(goal_id, position)",
        "CREATE INDEX IF NOT EXISTS idx_learning_items_due ON learning_lessons(goal_id, due_at)",
        "CREATE INDEX IF NOT EXISTS idx_learning_sessions_goal ON learning_sessions(goal_id, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_learning_attempts_item ON learning_attempts(item_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_learning_attempts_session ON learning_attempts(session_id, id)",
    ),
)

RESEARCH_CLOSURE_V20 = Migration(
    version=20,
    name="research-closure",
    statements=(
        # A run's status describes what the runner did (completed / incomplete / failed). It
        # does not describe whether *you* are done with the question - and inferring that from
        # coverage is how a research tool starts flattering. Closure is a separate, explicit
        # fact: closed_at is set only by `research close`, never by the runner.
        "ALTER TABLE research_runs ADD COLUMN closed_at TEXT",
        "ALTER TABLE research_runs ADD COLUMN closed_note TEXT",
        "CREATE INDEX IF NOT EXISTS idx_research_runs_closed ON research_runs(closed_at)",
    ),
)

CODING_V21 = Migration(
    version=21,
    name="coding-workspace",
    statements=(
        # A coding session is a directory, a task and a decision: the directory is what the file
        # and shell tools may touch, the task is the record of what happened in it, and the
        # decision is the user's, taken once rather than per keystroke.
        "CREATE TABLE IF NOT EXISTS code_sessions ("
        " id TEXT PRIMARY KEY,"
        " title TEXT NOT NULL,"
        " root TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " task_id TEXT,"
        " project_id TEXT,"
        " note TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " closed_at TEXT,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        # Every edit is a row with its own unified diff, before and after checksums. The file on
        # disk is the truth; this is the account of how it got there, and it is what makes an
        # edit reviewable after the fact.
        "CREATE TABLE IF NOT EXISTS code_changes ("
        " id TEXT PRIMARY KEY,"
        " session_id TEXT NOT NULL,"
        " path TEXT NOT NULL,"
        " action TEXT NOT NULL,"
        " before_sha TEXT,"
        " after_sha TEXT,"
        " added INTEGER NOT NULL DEFAULT 0,"
        " removed INTEGER NOT NULL DEFAULT 0,"
        " diff TEXT NOT NULL,"
        " artifact_id TEXT,"
        " tool_run_id TEXT,"
        " note TEXT,"
        " created_at TEXT NOT NULL)",
        # The runner's ledger: the command that was asked for, the argv that actually ran, where,
        # how long, what came back. A refusal is a row too - it is the evidence that the
        # permission centre was consulted, and by which tool.
        "CREATE TABLE IF NOT EXISTS code_runs ("
        " id TEXT PRIMARY KEY,"
        " session_id TEXT NOT NULL,"
        " check_name TEXT,"
        " command TEXT NOT NULL,"
        " argv TEXT,"
        " cwd TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " exit_code INTEGER,"
        " duration_ms REAL,"
        " timeout_seconds INTEGER,"
        " timed_out INTEGER NOT NULL DEFAULT 0,"
        " stdout TEXT,"
        " stderr TEXT,"
        " artifact_id TEXT,"
        " tool_run_id TEXT,"
        " replayed_from TEXT,"
        " created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_code_changes_session ON code_changes(session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_code_runs_session ON code_runs(session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_code_sessions_status ON code_sessions(status, created_at)",
    ),
)

EXPERIMENTS_V22 = Migration(
    version=22,
    name="experiments",
    statements=(
        # An experiment is a question, a command and a declared way of reading the answer out of
        # it. The declaration is not decoration: it is what stops the tool inventing a metric.
        # The name is `experiment_specs`, not `experiments`: the v13 schema already has an
        # `experiments` table (a manual log with baseline/target/criteria that nothing reads), and
        # redefining a table someone might have rows in is not a migration, it is a surprise.
        "CREATE TABLE IF NOT EXISTS experiment_specs ("
        " id TEXT PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " hypothesis TEXT,"
        " command TEXT NOT NULL,"
        " root TEXT NOT NULL,"
        " params TEXT NOT NULL DEFAULT '[]',"
        " metrics_source TEXT NOT NULL DEFAULT '{}',"
        " status TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        # One row per execution: the parameters it actually ran with (after substitution), the
        # command it resolved to, and what came back. A failed run is a run, not an absence.
        "CREATE TABLE IF NOT EXISTS experiment_runs ("
        " id TEXT PRIMARY KEY,"
        " experiment_id TEXT NOT NULL,"
        " params TEXT NOT NULL DEFAULT '{}',"
        " command TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " exit_code INTEGER,"
        " duration_ms REAL,"
        " timeout_seconds INTEGER,"
        " metrics TEXT NOT NULL DEFAULT '{}',"
        " metrics_error TEXT,"
        " task_id TEXT,"
        " tool_run_id TEXT,"
        " artifact_id TEXT,"
        " seed TEXT,"
        " note TEXT,"
        " created_at TEXT NOT NULL)",
        # Metrics are rows so a comparison is a query, not a re-parse of every run's JSON.
        "CREATE TABLE IF NOT EXISTS experiment_metrics ("
        " run_id TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " value REAL,"
        " raw TEXT,"
        " PRIMARY KEY (run_id, name))",
        "CREATE INDEX IF NOT EXISTS idx_experiment_runs_experiment"
        " ON experiment_runs(experiment_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_experiment_metrics_name"
        " ON experiment_metrics(name, value)",
    ),
)

PLAY_V23 = Migration(
    version=23,
    name="play",
    statements=(
        # `games` and `game_moves` were reserved for this milestone in v8, so they are adopted
        # rather than redefined: ALTER keeps whatever a home already has, where CREATE TABLE IF
        # NOT EXISTS would silently leave the old shape in place (D157).
        "ALTER TABLE games ADD COLUMN seed INTEGER",
        "ALTER TABLE games ADD COLUMN move_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE games ADD COLUMN task_id TEXT",
        "ALTER TABLE games ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'",
        # Why a move was refused is evidence, not a detail: the illegal attempt is the record.
        "ALTER TABLE game_moves ADD COLUMN reason TEXT",
        "ALTER TABLE game_moves ADD COLUMN state_hash TEXT",
        # A simulation is a record of a deterministic run: the parameters, the series, and the
        # hash of the final grid, so `play sim replay` can disagree with it if it is wrong.
        "CREATE TABLE IF NOT EXISTS play_sims ("
        " id TEXT PRIMARY KEY,"
        " kind TEXT NOT NULL,"
        " width INTEGER NOT NULL,"
        " height INTEGER NOT NULL,"
        " steps INTEGER NOT NULL,"
        " seed INTEGER NOT NULL,"
        " density REAL NOT NULL DEFAULT 0.3,"
        " status TEXT NOT NULL,"
        " final_hash TEXT,"
        " alive INTEGER,"
        " series TEXT NOT NULL DEFAULT '[]',"
        " rows TEXT NOT NULL DEFAULT '[]',"
        " task_id TEXT,"
        " created_at TEXT NOT NULL,"
        " completed_at TEXT,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        "CREATE INDEX IF NOT EXISTS idx_game_moves_game ON game_moves(game_id, seq)",
        "CREATE INDEX IF NOT EXISTS idx_play_sims_created ON play_sims(created_at)",
    ),
)

MEDIA_V24 = Migration(
    version=24,
    name="media",
    statements=(
        # What a file *is*, measured from its own bytes. The row keeps the measurement and the
        # name's claim separately, because a `.png` that is really a JPEG is a finding.
        "CREATE TABLE IF NOT EXISTS media_assets ("
        " id TEXT PRIMARY KEY,"
        " kind TEXT NOT NULL,"
        " format TEXT NOT NULL,"
        " path TEXT NOT NULL,"
        " sha256 TEXT NOT NULL,"
        " bytes INTEGER NOT NULL,"
        " width INTEGER,"
        " height INTEGER,"
        " duration_ms INTEGER,"
        " sample_rate INTEGER,"
        " channels INTEGER,"
        " bits_per_sample INTEGER,"
        " name_claim TEXT,"
        " name_mismatch TEXT,"
        " facts TEXT NOT NULL DEFAULT '{}',"
        " task_id TEXT,"
        " created_at TEXT NOT NULL,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        # Every attempt to hear or speak is a row - including the ones this build must refuse,
        # because "there is no speech model here" is the most useful thing it can record.
        "CREATE TABLE IF NOT EXISTS voice_attempts ("
        " id TEXT PRIMARY KEY,"
        " asset_id TEXT,"
        " action TEXT NOT NULL,"
        " status TEXT NOT NULL,"
        " reason TEXT,"
        " engine TEXT,"
        " chars INTEGER,"
        " task_id TEXT,"
        " created_at TEXT NOT NULL,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        # A transcript says where it came from. Today the only honest source is a person.
        "CREATE TABLE IF NOT EXISTS voice_transcripts ("
        " id TEXT PRIMARY KEY,"
        " asset_id TEXT NOT NULL,"
        " text TEXT NOT NULL,"
        # A CHECK, not a convention: no speech model exists in this build, so the only honest
        # source is a person, and a row that claims otherwise cannot be written - not even by
        # hand, not even by a future migration that forgets to look.
        " source TEXT NOT NULL CHECK (source IN ('human')),"
        " created_at TEXT NOT NULL,"
        " task_id TEXT,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        "CREATE INDEX IF NOT EXISTS idx_media_sha ON media_assets(sha256)",
        "CREATE INDEX IF NOT EXISTS idx_media_created ON media_assets(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_voice_attempts_asset ON voice_attempts(asset_id)",
        "CREATE INDEX IF NOT EXISTS idx_voice_transcripts_asset ON voice_transcripts(asset_id)",
    ),
)

DATASETS_V25 = Migration(
    version=25,
    name="datasets",
    statements=(
        # `datasets` and `dataset_transforms` were reserved for this milestone in v8, so they are
        # adopted with ALTER rather than redefined: a home that already has rows keeps them, where
        # CREATE TABLE IF NOT EXISTS would silently leave the old shape in place (D157/D160).
        "ALTER TABLE datasets ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'",
        "ALTER TABLE datasets ADD COLUMN seed TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE datasets ADD COLUMN splits TEXT NOT NULL DEFAULT '{}'",
        "ALTER TABLE datasets ADD COLUMN dropped_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE datasets ADD COLUMN updated_at TEXT",
        # The manifest is the dataset's claim about itself; `checksum` (reserved in v8) holds the
        # hash over its sorted lines, so `dataset verify` can recompute and disagree.
        "ALTER TABLE dataset_transforms ADD COLUMN input_checksum TEXT",
        "ALTER TABLE dataset_transforms ADD COLUMN output_checksum TEXT",
        # One row per candidate, kept *or* dropped. A record that a cleaning rule removed keeps its
        # reason: a pipeline that deletes quietly cannot be audited, and "why is this file not in
        # my dataset" is the first question anyone asks.
        "CREATE TABLE IF NOT EXISTS dataset_records ("
        " id TEXT PRIMARY KEY,"
        " dataset_id TEXT NOT NULL,"
        " seq INTEGER NOT NULL,"
        " path TEXT NOT NULL,"
        " sha256 TEXT NOT NULL,"
        " bytes INTEGER NOT NULL,"
        " kind TEXT NOT NULL,"
        " chars INTEGER,"
        " lines INTEGER,"
        " split TEXT,"
        " status TEXT NOT NULL,"
        " reason TEXT,"
        " label TEXT,"
        " created_at TEXT NOT NULL,"
        " metadata TEXT NOT NULL DEFAULT '{}')",
        "CREATE INDEX IF NOT EXISTS idx_dataset_records_dataset"
        " ON dataset_records(dataset_id, status, seq)",
        "CREATE INDEX IF NOT EXISTS idx_dataset_records_sha ON dataset_records(dataset_id, sha256)",
        "CREATE INDEX IF NOT EXISTS idx_dataset_transforms_dataset"
        " ON dataset_transforms(dataset_id, seq)",
    ),
)

MIGRATIONS: tuple[Migration, ...] = (
    CONVERSATIONS_V1,
    PROJECTS_V2,
    MEMORY_V3,
    CONTEXT_V4,
    TASKS_V5,
    TOOLS_V6,
    JOBS_V7,
    FEATURES_V8,
    RETRIEVAL_V9,
    MODELS_V10,
    CONTEXT_PROPOSALS_V11,
    PROVIDERS_V12,
    PERMISSIONS_V13,
    MCP_V14,
    TASKS_V15,
    WORKFLOWS_V16,
    JOBS_V17,
    RESEARCH_V18,
    LEARNING_V19,
    RESEARCH_CLOSURE_V20,
    CODING_V21,
    EXPERIMENTS_V22,
    PLAY_V23,
    MEDIA_V24,
    DATASETS_V25,
)

SCHEMA_VERSION = max(m.version for m in MIGRATIONS)


__all__ = ["MIGRATIONS", "SCHEMA_VERSION"]
