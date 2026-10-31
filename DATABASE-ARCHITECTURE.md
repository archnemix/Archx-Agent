# ArchX Agent Database Architecture

Inherited Node database design, reviewed for the 1.0.0 foundation. These are storage mechanisms, not evidence that every user-facing feature is complete.

ArchX Agent now uses **SQLite as the source of truth** for structured application data. The database is `archx.db` inside the user-selected data directory. Large binary assets stay on the filesystem; SQLite stores their metadata and derived representations.

## Database rules

1. SQLite owns configuration, providers, models/endpoints, profiles, prompts, conversations, messages, memories, summaries, context state and request logs.
2. `media/` is the filesystem object area. An asset row stores its path, MIME type, size, hash and derived descriptions/transcripts/OCR.
3. Chat history is never replaced by summaries. Raw messages remain authoritative; summaries are derived data.
4. Embeddings are stored separately from their source object so the same message or memory can have embeddings from multiple models.
5. Model endpoints are capability-oriented. `endpoint_kind` can represent future `chat`, `audio`, `image`, `video`, `ocr`, `embedding`, or other endpoint families without changing provider rows.
6. The current chat mode is `simple-chat`. It has no tools. Additional modes register through `lib/modes/` and are stored on each chat as `mode_id`.
7. Legacy JSON files are imported once, verified against the imported state, and renamed to `*.migrated-<timestamp>` backups. They are not used as the active store afterwards.

## Table inventory

There are **20 SQLite tables**, grouped as follows.

### A. Database and runtime configuration — 4 tables

| Table | Purpose | Important relations |
|---|---|---|
| `db_meta` | Schema/version metadata | none |
| `settings` | User/application settings stored as typed JSON values | system prompt settings mirror `system_prompts` |
| `app_state` | Small mutable pointers such as active provider/model/profile/chat | points by ID into domain tables |
| `modes` | Registered chat/application modes and their declared capabilities | `chats.mode_id -> modes.id` |

### B. Providers, models and model profiles — 5 tables

| Table | Purpose | Important relations |
|---|---|---|
| `providers` | Provider connection/configuration and encrypted API key | parent of `model_endpoints`; parent of profile items |
| `models` | Canonical model identity | parent of `model_endpoints`; referenced by `profile_items` |
| `model_endpoints` | A provider's concrete endpoint for a model/capability | `provider_id -> providers`; `model_id -> models` |
| `profiles` | Reusable model fallback profiles | parent of `profile_items` |
| `profile_items` | Ordered provider/model candidates inside a profile | `profile_id -> profiles`, `provider_id -> providers`, `model_id -> models` |

The split between `models` and `model_endpoints` is intentional. A future model may exist once while having multiple provider implementations or endpoint kinds:

```text
models
  └── model_endpoints
       ├── provider A / chat
       ├── provider A / audio
       ├── provider B / chat
       └── provider C / embedding
```

This avoids designing the application around one chat-only model API.

### C. Conversations and context — 6 tables

| Table | Purpose | Important relations |
|---|---|---|
| `system_prompts` | Reusable system prompt definitions | referenced by `chats.system_prompt_id` |
| `chats` | Conversation identity, title, mode and prompt selection | parent of `messages`, summaries, assets and context state |
| `messages` | Exact message history | `chat_id -> chats` |
| `message_embeddings` | Vector representations of individual messages | `message_id -> messages` |
| `conversation_summaries` | Derived summaries of a chat or message range | `chat_id -> chats` |
| `chat_context_state` | Runtime/context-management bookkeeping for a chat/model pair | `chat_id -> chats` |

`messages` is the archival source. `conversation_summaries` and `chat_context_state` never replace it.

### D. Memory and assets — 4 tables

| Table | Purpose | Important relations |
|---|---|---|
| `memories` | Durable memory records across permanent, project, learning, procedural, task and knowledge scopes | optional `scope_type/scope_id` references an owning entity without forcing one universal owner table |
| `memory_embeddings` | Embeddings for durable memories | `memory_id -> memories` |
| `assets` | Metadata/derived representations for filesystem-stored images, audio, video and documents | optionally linked to `chats` and `messages` |
| `asset_embeddings` | Embeddings for image/audio/video/document assets | `asset_id -> assets` |

The asset itself is **not** stored as a SQLite BLOB by default. `storage_path` points to the user's selected filesystem area.

### E. Operational diagnostics — 1 table

| Table | Purpose | Important relations |
|---|---|---|
| `request_logs` | Request/activity journal used by the debug UI | indexed by timestamp, chat and trace ID |

Simple logs remain metadata-only. Detailed logging stores an encrypted envelope in the same table.

## Relationship map

```text
modes ────────────────< chats
                         │
                         ├────< messages ────< message_embeddings
                         │
                         ├────< conversation_summaries
                         │
                         ├────< chat_context_state
                         │
                         └────< assets

providers ────< model_endpoints >──── models
    │                 │                 │
    │                 │                 └────< profile_items
    │                 │
    │                 └──── endpoint capability metadata
    │
    └────< profile_items >──── profiles

system_prompts ─────< chats

memories ───────────< memory_embeddings
assets ─────────────< asset_embeddings

app_state ── stores small active IDs into the above domain objects
settings  ── stores application settings; prompt definitions are normalized in system_prompts
```

## Current implementation vs. future work

Implemented now:

- SQLite persistence and automatic JSON migration
- normalized providers/models/model endpoints/profile relationships
- exact chat/message persistence
- summary and embedding persistence APIs (message, memory and asset vectors)
- durable memory persistence APIs
- asset metadata APIs
- active context-state persistence
- SQLite request logging
- registered `simple-chat` mode

Not automatically generated yet:

- automatic message embedding jobs
- automatic 2–5-message chat summarization jobs
- automatic permanent/project/learner/procedural memory extraction
- vector similarity search inside SQLite
- native audio/image/video/OCR execution
- additional chat modes

Those are deliberately kept out of the storage migration so they can be added as separate pipelines without changing the underlying data model.

## Storage and migration behavior

The data directory remains user-selectable. Moving it creates and verifies a complete SQLite database first, switches the pointer only after verification, then removes the old database/files. `media/` is kept alongside the database so large objects can be streamed directly from disk.

The fixed OS configuration directory still contains the pointer and manifest. The manifest now reports:

```json
{
  "storage": {
    "engine": "sqlite",
    "database": ".../archx.db"
  }
}
```

## Why SQLite here

SQLite is the system-of-record because ArchX needs relational state in addition to vectors: providers, endpoints, model capabilities, conversations, messages, prompts, memories, assets and runtime state. Embeddings are therefore stored behind their own tables and APIs rather than making a vector database the primary application database.

## 1.0.0 persistence corrections

Conversation writes now include `branches_json`, which was previously read but not
written. The existing message `meta_json` column reserves `_archxMessage` for tool
cards and separate failure text; it is unpacked back into browser message fields
on load. Existing public metadata stays separate. No schema reset is required.
