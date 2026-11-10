<!-- Purpose: Records the discussed Archx Agent product scope, decisions, and unresolved architecture questions. -->
# Product plan and architecture

## Identity and direction

**Archx** abbreviates the Archnemix brand. **Archx AI Lab** is the desktop-first AI/ML superapp and launcher; **Archx Agent** is the chat-and-agent destination inside it. Future AI/ML areas include model training, fine-tuning, and observing models; their behavior is not specified yet. Usability, reliability, security, modularity, transparency, and user control are product goals, not comparative claims already proven. The starting screen should expose distinct components, with Archx Agent prominent; the user cited mobile-style launchers and LDPlayer/Epic Games Launcher as layout inspiration, not a request to copy them. Its visual direction is specified in `Docs/design.md`: modern minimalist graphite/black, professional bundled font, and restrained gray glass-like selected states, without neon. The requested build sequence starts with a complete home/app shell, then a chat interface and mode navigation, then each mode's real behavior one by one. Unimplemented capabilities must be visibly unavailable rather than pretending to work.

Iced is the selected Rust GUI framework. The user wants to avoid different OS webview engines and bundling a browser. Target Windows, macOS, and Linux **from the start**, with real compatibility checks on all three. Native rendering does not remove the need to check font, layout, and platform behavior. No other library or database is selected. At the end of each GUI implementation step, a Windows build must be downloadable for user testing, alongside Linux/Windows/macOS test evidence. Build-output delivery and retention need agreement before the first GUI step so large executables do not accumulate in Git.

Settings should give users control over resource use (lazy load, eager load, or selected preloads), storage location, and future features; secure defaults and understandable consequences are required. Exact controls and defaults are still to be designed.

## AI interaction modes

| Mode | Intended role | Distinct capability/memory direction |
| --- | --- | --- |
| Simple chat | Converse and optionally search the internet | Conversation history, summaries, stable user preferences |
| General task agent | Handle agentic tasks outside the specialized modes | Task state, permissions, and scoped tools; detailed memory/tool design later |
| Coding agent | Research, generate, execute, test, and publish code | Per-project structure, files, interfaces, and execution flow; tools to be scoped later |
| Learning agent | Interactive teaching with goals and feedback | Per-skill scope, progress, assessments, optional resources |
| Research agent | Deep, source-backed investigation | Per-topic findings, source URLs, and evidence/credibility information |
| Play agent | Build a game and take turns playing with the user while conversing | Game state, controls visible to the agent, turn loop; detailed design later |

Specific tool sets and MCP availability are **deferred** until each mode is designed. The six modes are interaction modes, not six independently implemented agents yet. General task agent was added at the user's request; its boundaries relative to the specialized modes need definition.

### Requested mode transitions

- Simple chat → coding, learning, research, or play as originally requested. Simple chat → general task agent is proposed with the new mode; confirm transition semantics before implementing it.
- Research → coding.
- No other transitions, including any mode → simple chat, are currently allowed. The user cites tool-history and mode-specific state as reasons.
- Open: whether an allowed transition changes the same chat's mode or starts a linked new chat, and how its messages, approvals, and memory carry over. Do not discard original history.

## Memory and context direction

Memory should be organized for selective retrieval rather than forcing the model to reread everything. Mode-specific records can be read by other modes; writes to another mode's records require user permission. The user additionally says *every* persistent memory modification requires user approval, including otherwise unrestricted modes; the exact approval workflow versus automatic AI-generated summaries needs clarification before implementation. Record authoring mode and modification time for approved changes. Access control, privacy, and scope must be designed even for reads.

- **Active context:** reserve room for the system instructions and model output; compact older conversation using an AI-generated summary before running out of context. Keep important facts, tasks, and references, while avoiding raw tool-call history in model input as requested. Open: which tool results the agent must see to act safely, how summary fidelity is verified, and how budget accounting works. The illustrative 8k example gave 1k system + 5k history + 3k output = **9k**, so these numbers cannot be adopted unchanged.
- **Conversation archive:** store individual messages with stable chat ID and in-chat ordering so an exact chat can be reconstructed; store an evolving chat summary for quick discovery. Optional per-message embeddings for semantic search, only when enabled/configured. Archive fidelity must not depend on the summary.
- **Stable profile:** rarely changed information such as preferred agent name (default “Archx Agent”), user name, and optional personal details. Consent and data minimization are especially important for sensitive data such as age.
- **Coding projects:** a project-oriented index of name, brief description, structure, key project docs, file roles/interfaces, and program flow. The supplied `ProjectA/` layout is an illustration, **not a chosen disk format**. Index updates and stale-index detection are open design questions.
- **Learning skills:** per-skill learning scope, progress, remaining goals, assessments, and optional links to watched/recommended videos or other resources.
- **Research topics:** per-topic research documents, exact source URLs, and credibility/evidence assessment; do not treat an unverified score as objective truth.
- **Workarounds/skills:** reusable resolution, applicable situations, usage steps, and whether it remains valid as dependencies or permissions change.
- **Play mode:** its persistent state and retention need later design; game state must remain distinct from chat narration.

Possible storage is local first or optional user-owned remote backup (the user mentioned a private Hugging Face repository/dataset, GitHub, and Google Cloud as examples). None is selected or assumed to be a private bucket with suitable permissions yet. Database choice must follow actual query, migration, search, security, and backup needs rather than popularity. Define retention, export, deletion, encryption/credential handling, and offline behavior before promising a security model.

## Architecture still to decide

- Does the agent run locally, remotely, or both? Which model providers/local runtimes are supported initially?
- Exact tool permissions and isolation, especially command execution, publishing, web access, and game-generated code.
- Persistent-write consent semantics: each write, batches, or explicit per-scope grants; can AI update summaries without prompting for every message?
- Active-context budget and tool result handling; retrieval/summary quality and staleness.
- Database/storage format and optional backup mechanics after access/query requirements are clear.
- Allowed transition mechanics and how archival/tool events differ from what the model receives.
- First complete user journey and the ordering of mode implementation. Define this with the user before finalizing the roadmap.
