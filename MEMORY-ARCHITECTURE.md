# Memory architecture

This is the inherited Node storage/context design, not proof of validated learning,
project-agent or autonomous research journeys.

The memory system is intentionally layered. The raw conversation is authoritative; everything else is a derived or scoped representation used to build a model-specific active context.

## Memory tiers

1. **Active / Working memory** — runtime context assembled for one request. It is not the canonical chat history.
2. **Archival / Episodic memory** — exact messages and message metadata. This is the durable record of what was actually said.
3. **Conversation Summary memory** — compressed summaries of individual chats. These are derived from archival messages.
4. **Permanent / Semantic memory** — small, rarely changed facts, preferences, rules and user-specific information.
5. **Project / Workspace memory** — durable current state of a project: architecture, decisions, constraints, asset paths, completed work, current stage, next steps and plans.
6. **Learning / Skill memory** — learner state, goals, concepts learned, weak areas, last lesson and next lesson.
7. **Procedural memory** — reusable solutions and methods that can be applied to future problems.
8. **Task / Goal memory** — active work items, status, blockers and goals that an agent can act on.
9. **Knowledge / Reference memory** — durable information extracted from documents, research and other reference sources.

## Not memory tiers

Two cross-cutting systems sit beside the tiers:

### Multimodal representation layer

Images, audio, video and documents keep their original filesystem asset plus derived representations such as:

- short description
- detailed description
- OCR
- transcript
- structured metadata
- embeddings

When a conversation moves from a multimodal-capable model to a text-only model, Active Memory can substitute an appropriate derived representation instead of dropping the conversation or injecting the full binary asset into the text context.

### Context engine

The context engine decides what Active Memory contains for a specific model. It can account for:

- model context window
- reserved output budget
- input/output modality support
- token estimates
- compaction policy
- retrieval relevance
- provider rate constraints such as TPM/RPM
- model changes inside the same conversation

TPM/RPM are request/rate constraints, not context-window sizes. They influence scheduling and context policy but are stored separately from the model's context capacity.

## SQLite mapping

- Archival messages → `chats`, `messages`, `message_embeddings`
- Conversation summaries → `conversation_summaries`
- Permanent/project/learning/procedural/task/knowledge memory → `memories`, `memory_embeddings`
- Assets and multimodal descriptions → `assets`
- Active context bookkeeping → `chat_context_state`

The implementation already exposes storage methods for summaries, memories, embeddings, assets and context state. The policies that decide **when** to create/update these records are intentionally separate from the database layer.

## Provenance

Durable memory records carry source/confidence/importance fields so future memory extraction can distinguish explicit user statements from inferred or imported information. This is important once agent modes can create and update memories automatically.
