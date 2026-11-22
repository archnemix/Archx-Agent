# archx-agent

**A local, multi-provider AI workspace with SQLite persistence and pluggable model endpoints — with a data area you choose yourself and keys encrypted at rest.**

Install it, run `archx-agent webui`, add as many providers as you like (Anthropic, Gemini, Groq, OpenAI, OpenRouter, Together, DeepSeek, Mistral, Ollama, LM Studio, vLLM…), pick a provider → model from the two-level picker, and chat with streaming, **visible model reasoning**, markdown and syntax-highlighted code. The chat UI works from the very first start with **no key configured** — connecting a provider is optional and can be done whenever you're ready.

```
npm install -g archx-agent
archx-agent webui
```

Then open the printed URL (default <http://127.0.0.1:4173>) — it opens automatically.

---

## Features

- 📄 **Three real pages, not popups** — hash-routed: `#/chat`, `#/settings` (section nav: click a section and only it is shown — General / System prompts / Providers / Models / Profiles / Storage / Danger), and `#/debug`: a beautiful log viewer fed by the request journal (kind badges, status, latency, tokens, expandable full JSON — everything stored *except* API keys), with filter, auto-refresh and clear.
- 📊 **Guaranteed tables** — three-layer pipeline: (1) normalization pass de-indents model-indented tables, un-glues them from paragraphs and repairs separator rows; (2) GFM render into decorated scrollable sheets (zebra, hover, alignment, copy-CSV); (3) if the parser still refuses, tables are converted by hand and token-swapped in. A table can no longer fail to render.
- 🧩 **Multiple providers, three wire protocols** — OpenAI-compatible, Anthropic-native and Gemini-native adapters; each provider = endpoint + encrypted key + its own model curation + free-only switch. Preset picker fills name/URL/adapter; everything stays editable.
- 🧪 **Test before you add** — the add-models dialog probes every listed model (2 attempts each) and can add only the ones that actually answer; single-model and Test-all use the same retry policy. The top-bar picker lists providers on the left; hover or click one and its curated models appear on the right.
- 🆓 **Free-only mode per provider** — keeps just models tagged free (`:free` / `-free` suffix or zero pricing, OpenRouter-style). If the provider has none, the UI warns you and lets you add your own ids instead.
- 🧠 **Reasoning / thinking view** — when a model emits reasoning (`reasoning_content`, `reasoning` or `thinking` deltas — DeepSeek-R1, Qwen3, Groq parsed reasoning, OpenRouter…), it streams into a collapsible "Thinking…" panel above the answer and is stored with the message. Toggle in Settings → Generation.
- 🔐 **Encrypted keys** — API keys are stored only as AES-256-GCM ciphers in the data area. The wrap key is **never written anywhere**: it is re-derived on every launch from stable machine identity (OS machine-id / Windows MachineGuid / macOS IOPlatformUUID + platform/arch/home/user) via scrypt, decrypted in RAM only while a request runs, and re-derived fresh next launch. Local disk theft yields ciphertext, not keys.
- 📜 **Request logs for the future debug dashboard** — request activity is journaled in SQLite (`request_logs`). Simple logs contain safe metadata; detailed logs encrypt the payload at rest. The dashboard reads the same journal.
- 💾 **Your data, your place** — first start asks where data lives (OS default / custom folder / project-local `.archx-agent` / memory-only). Move it later from Settings → Storage or `--data-dir`: **copy → verify → switch → delete originals**, so a failed move never loses anything.
-  **No forced setup** — the UI always loads; with zero providers it simply says "No provider configured" and offers an Add button. Local servers work with no key at all.
-  **Token-by-token streaming** — SSE proxied verbatim, stop button (`Esc`), tokens/s + latency readout.
- 🧠 **Multi-chat sidebar** — auto-titled, delete/switch, all persisted.
- 📝 **Markdown + code + tables** — markdown-it + highlight.js served locally (no CDN); code blocks and tables render as decorated panels with copy buttons (code → clipboard, tables → CSV), zebra-striped scrollable sheets with sticky-styled headers.
- ✍️ **Chat ergonomics** — regenerate, edit & resend, copy (includes reasoning), system prompt, temperature, max-tokens, stream toggle, dark/light theme.

## How it works

```
┌────────────────────────────── your machine ──────────────────────────────┐
│  browser tab (es-modules UI)         archx-agent server (localhost)      │
│  ┌─────────────────────────┐  HTTP  ┌────────────────────────────────┐   │
│  │ provider→model picker   │ ─────► │ /api/providers · /api/chat     │   │
│  │ reasoning panels, chats │ ◄───── │ key decrypted in RAM per req   │   │
│  └─────────────────────────┘  SSE   └───────┬──────────────┬─────────┘   │
│                                            │              │              │
│                              ┌─────────────▼───────┐      │              │
│                              │ data area (yours)   │      │              │
│                              │  archx.db          │      │              │
│                              │  ├ structured data │      │              │
│                              │  └ media/          │      │              │
│                              └─────────────────────┘      │              │
└────────────────────────────────────────────────────────────┼─────────────┘
                                                  HTTPS      ▼
                                    provider A · provider B · provider C …
                                    (any OpenAI-compatible /v1 endpoint)
```

1. `archx-agent webui` starts an Express server on `127.0.0.1` and opens your browser. First start: the CLI asks where the data area should be (a pointer config such as `%APPDATA%\archx-agent\config.json` remembers it).
2. The UI boots **always** — no key needed. Add providers whenever you like; keys are encrypted with the machine-derived wrap key before hitting disk.
3. Chat requests name a provider; the server decrypts that key in RAM, attaches `Authorization: Bearer …`, proxies to the endpoint and re-emits the SSE stream (content **and** reasoning deltas) unchanged.
4. Every request is journaled in the SQLite `request_logs` table (what ran, against which provider/model/mode, status, latency, usage and errors).
5. Moving the data area creates and verifies the new SQLite database first, switches the pointer, then removes the old database/files. Large assets remain in `media/`.

### Key encryption, honestly

The wrap key = `scrypt(platform | kernel | arch | homedir | user | machine-id)`. It survives CPU/RAM/GPU swaps and disk moves on the same machine/OS install. Consequences:

- **Disk theft / data-area copies / casual malware**: ciphertext only. ✔
- **OS reinstall or renamed machine identity**: fingerprint changes → old ciphers won't open → the UI says "key undecryptable, re-enter" (nothing crashes, chats stay). ✔
- **Malware that can also read this package's source on the same box**: could re-derive the key. This is defence-in-depth, not a HSM. For absolute protection use a hardware-backed store.

## Compatible endpoints

| Provider | Base URL |
| --- | --- |
| Groq | `https://api.groq.com/openai/v1` |
| OpenAI | `https://api.openai.com/v1` |
| OpenRouter (free models tagged `:free`) | `https://openrouter.ai/api/v1` |
| Together AI | `https://api.together.xyz/v1` |
| DeepSeek (reasoning models show thinking) | `https://api.deepseek.com/v1` |
| Mistral | `https://api.mistral.ai/v1` |
| Anthropic (native adapter) | `https://api.anthropic.com/v1` |
| Google Gemini (native adapter) | `https://generativelanguage.googleapis.com/v1beta` |
| Ollama (local, no key) | `http://localhost:11434/v1` |
| LM Studio (local, no key) | `http://localhost:1234/v1` |
| vLLM (local, no key) | `http://localhost:8000/v1` |

## CLI

```
archx-agent webui [options]
archx-agent help | version

  -p, --port <port>        Port to bind             (default: 4173, auto-increments if busy)
  -H, --host <host>        Host to bind             (default: 127.0.0.1 — localhost only)
      --no-open            Do not auto-open the browser
      --data-dir <path>    Use / create this data area (existing data migrates there safely)
      --no-store           Run memory-only (nothing persisted, no logs)
      --choose-storage     Re-run the first-start storage chooser
      --base-url <url>     Create/update a provider with this endpoint
      --key <key>          Store this API key (encrypted) for that provider
      --model <id>         Preferred model id
```

## Settings page (in the UI)

- **Generation** — system prompt, temperature, max tokens, streaming, show-reasoning toggle.
- **Providers** — add/edit/delete providers, key status (masked), which one is active.
- **Models** — per provider: live list with hide/show, hidden list, custom ids, **free-only** switch with a warning when the provider has no free-tagged models.
- **Storage** — current data area, SQLite database + filesystem asset area, move-to-path with fail-safe migration, quick actions, memory-only.
- **Danger zone** — wipe providers, keys, chats, settings and logs.

### The manifest

The manifest lives at a **fixed, non-movable path** next to the pointer config (`%APPDATA%\archx-agent\manifest.json` on Windows, `~/.config/archx-agent/manifest.json` on Linux) — data-area migrations never move or delete it. It is rewritten on boot, migration and wipe:

```json
{
  "app":     { "name": "archx-agent", "version": "1.6.10", "installPath": "…/node_modules/archx-agent", "node": "v22…", "platform": "win32/x64" },
  "storage": { "engine": "sqlite", "database": "…/archx.db", "dataDir": "…", "pointerConfig": "…" },
  "paths":   { "database": "archx.db", "media": "media" }
}
```

So any tool (or future version) opening the folder knows that `archx.db` is the structured source of truth and `media/` is the large-object area.

## Database architecture

The 1.6.10 database contains **20 SQLite tables** in five categories: runtime configuration (4), provider/model/profile data (5), conversations/context (6), memory/assets (3), and request diagnostics (1). `DATABASE-ARCHITECTURE.md` documents every table, primary relationships, migration behavior, and the filesystem boundary. `MEMORY-ARCHITECTURE.md` documents the nine memory tiers plus the multimodal representation and context-engine layers.

Node **22.5+** is required because 1.6.10 uses Node's built-in `node:sqlite`, so no extra SQLite native dependency is needed.

## Storage evolution

SQLite is now the primary database. Large images, audio, video and documents remain on the user-selected filesystem. Embeddings have dedicated SQLite tables so the vector implementation can evolve independently; a vector extension or external vector service can be added later without replacing the relational source of truth. See `DATABASE-ARCHITECTURE.md` and `MEMORY-ARCHITECTURE.md`.

See `DATABASE-ARCHITECTURE.md` for the table inventory, relationships and migration strategy.

## Privacy & security model

- Binds to localhost unless you pass `--host`.
- Keys: encrypted at rest, decrypted in RAM per request, sent only to their own endpoint over its TLS.
- Logs contain metadata only — no keys, no prompts, no completions.
- No telemetry, no CDN, no external assets at runtime.
- `--no-store` = fully ephemeral mode (v1.0 behaviour).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `npm install -g` → *Could not determine Node.js install directory* (Windows) | npm global-prefix issue, not this package. Local-install + `npx archx-agent webui`, or `nvm use <ver>` / admin shell / Node LTS reinstall. |
| "key undecryptable — re-enter" | Machine identity changed (OS reinstall). Chats/settings survive; just re-enter the key. |
| `401 Incorrect API key` | Wrong/missing key for that provider. |
| `Connection refused` | Local server not running / other port. |
| Free-only shows nothing | Provider has no free-tagged models — the warning explains; add custom ids or turn it off. |
| Port in use | Auto-picks next free port, prints URL. |
| Self-signed local TLS | `NODE_EXTRA_CA_CERTS=/path/ca.pem` before starting. |

## Development

```
npm install && npm start     # run
npm test                     # smoke: providers, crypto, reasoning, logs, migration
```

```
bin/archx-agent.js     CLI: args, storage chooser, banner, browser launch
lib/paths.js           pointer config + per-OS default dirs
lib/keys.js            machine-fingerprint wrap key + AES-256-GCM ciphers
lib/logger.js          requests-*.jsonl journal (future dashboard)
lib/store.js           providers/chats/settings persistence + v1 migration + safe moves
lib/server.js          express: static UI + /api (providers, chat SSE, storage, logs)
lib/proxy.js           OpenAI client: /models + streaming completions incl. reasoning
public/css/            base · components · chat
public/js/             main · ui · chat · render · state · api · markdown · dom
test/                  mock upstream (reasoning + :free models) + smoke test
```

## Publishing

```
npm login && npm publish --access public
```

## License

MIT

## 1.4.1 UI / diagnostics improvements

- Providers are managed inline in Settings; no add/edit modal is required.
- Provider reachability tests and explicit model-response tests are available from Settings.
- OpenRouter providers use `openrouter/free` as the built-in default when no specific model is selected.
- Enabling Free-only moves currently known non-free live models into that provider's Hidden list and restores the previous Hidden list when disabled.
- Debug entries remain expanded across live refreshes and show request/response detail when detailed encrypted logging is enabled.
- Simple logs remain metadata-only. Detailed logs are encrypted at rest with a separate machine-bound key derived at runtime and are never stored in plaintext.
- Markdown tables have a fenced-code-aware parser fallback and rendered-table actions for CSV, TSV, JSON, HTML and Markdown; code blocks can be downloaded with a useful filename and language-derived extension.


## 1.5.0 Major UI / model profile upgrade

- Reworked Markdown rendering so headings, horizontal rules, lists, tables and fenced code blocks are parsed and presented as UI elements rather than raw escaped Markdown.
- Reworked Debug into a readable, scrollable/expandable diagnostics view with Comfortable and Compact density modes so large log histories do not collapse into unreadable rows.
- Code and table downloads generate content-specific filenames instead of reusing the chat title.
- Model profiles are now global reusable profiles that can combine models from different providers, support ordered priority/fallback, and can be exposed as a third selector in Chat when the advanced profile option is enabled.
- The advanced profile selector is disabled by default, preserving the simpler existing chat experience.

### Model profiles (1.5.0)

Settings → Models supports global multi-provider model profiles. A profile is an explicit enabled-model set; selecting it makes only those models available for that provider. Profile membership is an explicit user choice and can enable a model even when the provider is in free-only mode. Free-only auto-hiding remains separately tracked so it can be reversed without overwriting manual choices.


## 1.6.1 UI / model management fixes

- Models now use only **Enabled** and **Disabled** status lists; provider models and custom models share the same controls.
- Removed the separate Available / Hidden / Custom model lists from the main Models workspace.
- Profile model lists now have independent scroll surfaces so long provider catalogs remain usable.
- Increased the visual separation between Models and Profiles.


- Provider creation and editing now use explicit add/edit state so saving one provider no longer silently turns the next provider into an edit of the previous provider; multiple providers/models can be added without refreshing.
- Debug is organized by activity type (All, API calls, Tool calls, Provider changes, Local configuration and Storage) with a redesigned control/header area.
- Debug auto-refresh preserves expanded entries, nested payload scroll positions and the main feed position instead of jumping back to metadata or the top.
- Chat Debug is scoped to the active chat trace so unrelated debug activity is not mixed into the current conversation.
- System prompts now have reusable saved entries, per-chat selection, an explicit no-prompt option, and request diagnostics that record whether a system prompt was included.
- 1.6.10 moves structured persistence from JSON files to SQLite, adds the mode registry used by the current Simple chat mode, and fixes streaming fenced-code rendering so a generated code block becomes scrollable before the closing fence arrives.

## 1.6.2 Professional UI refresh

- Replaced the neon gradient treatment with solid, muted blue-grey accents and calmer surfaces.
- Added **Soft** alongside Dark and Light: an off-white, low-glare working theme saved with the existing appearance preference.
- Simplified the Chat header: model selection remains primary; fallback profiles stay available in Settings instead of crowding the active conversation controls.
- Added an explicit Appearance selector in Settings and made the sidebar control cycle Dark → Light → Soft.
- Preserved unsent composer text when sending is blocked because no provider is configured or a response is already streaming.
- Kept model, profile and system-prompt behavior compatible with 1.6.1 while clarifying their roles in the interface.

## 1.6.4 Visual-behaviour fixes and polish

Fixes driven by a frame-by-frame review of a real usage recording, then verified
in a headless browser with layout measurements (not by eye alone):

- **Chat debug no longer covers the conversation.** The panel is absolutely
  positioned; while it is open the message column now reserves horizontal space
  on viewports ≥1000px, so bubbles are never hidden underneath it.
- **Debug toolbar checkbox unstretched.** `.dbg-tools input` also matched the
  auto-refresh checkbox and applied `flex: 1 1 320px; min-width: 200px` to it,
  tearing the checkbox ~140px away from its label. The rule is now scoped to
  text inputs, and the log search field is capped at 420px so the toolbar keeps
  a balanced left-categories / right-tools rhythm.
- **Status dots mean something again.** The connection dot and the sidebar
  endpoint badge were green even with no provider configured; both are neutral
  grey until a provider is active, then green (accent while streaming, red on
  error).
- **Sidebar footer no longer ellipsizes everything.** "keys encrypted · stored
  on this machine" and the version now wrap onto two lines instead of showing
  "stored on this ma… v1…".
- **Light/Soft contrast raised.** `--muted`/`--muted-2`/`--warn` were too pale on
  white for 11–12px log timestamps, tabs and hints; the tokens are darker now.
- **Honest system-prompt label.** With no chat open the header showed
  "No system prompt" although new chats inherit the default; it now shows the
  default prompt's name.
- **Debug rows say what changed.** Provider/config events append their changed
  fields (e.g. `· freeOnly, models`) instead of leaving the row body empty.
- **Motion polish.** Menus, the chat-debug panel, modals and toasts ease in
  (170ms), theme switches cross-fade surfaces (220ms), and all of it collapses
  to instant under `prefers-reduced-motion`.
- Topbar wraps instead of squeezing on medium widths; chat-debug auto-refresh
  eased from 2.5s to 3s.

## 1.6.5 Menu behaviour, debug-panel feel, sidebar and profile picker fixes

Driven by user-reported behaviour with screenshots; re-verified headlessly.

- **Topbar menus are mutually exclusive.** Opening the model picker now closes
  the system-prompt menu (and vice versa); previously the system-prompt menu
  stayed open on top of the model menu.
- **Profile picker visible again.** `renderModelUI` hid `#profile-wrap`
  unconditionally, so with Advanced Profiles enabled there was no way to
  select or clear a fallback chain from Chat. It now shows whenever the mode
  is on, and choosing an explicit model detaches the profile with a toast that
  says so.
- **Chat debug keeps your place.** Auto-refresh (3s) no longer resets the
  panel's scroll position, and returning to Chat paints cached rows instantly
  before refreshing — no empty flash, no jump to the top while reading.
- **Sidebar footer pinned.** On Settings/Debug (chat list hidden) the endpoint
  badge / theme / privacy block floated up under the nav; `margin-top: auto`
  keeps it at the bottom on every page.
- **Settings → Prompts.** The system-prompt manager (previously reachable only
  via Chat → Default → Manage) now has its own entry in the Settings nav.
- **Debug category tabs bigger** (11.5px → 13px, roomier padding).
- **Data area guarantee documented in the manifest:** the launch folder is
  never adopted as the data area (reinstall-safe); it is reserved as the future
  per-chat tool workspace. Tools themselves are intentionally not part of this
  release.

## 1.6.6 System-prompt hot-switch, section reorg, profile routing lock, chat-debug anchor fix

- **Settings reorganised.** Temperature / max tokens / streaming / reasoning /
  advanced profiles / Appearance moved to **General**; the tab is now named
  **System prompts** and contains only the prompt manager, the hot-switch
  method card and the variables table.
- **Prompt variables table** lives under the prompt editor (token, meaning,
  copy button) instead of the old one-line strip in General.
- **Prompt editor action bar** (hint + Use for new chats + Delete + Save) now
  has breathing room and a separator instead of sitting on the textarea edge.
- **System-prompt hot-switch (new feature).** Each chat keeps a *stack* of
  enabled prompts, toggled per prompt from the Chat prompt menu ("send"
  checkboxes; the visual box shows exactly what will be sent). Two methods,
  switchable in Settings → System prompts:
  - *Stack (default):* the selected prompt is sent first as `system`; every
    additional enabled prompt follows as another `system` message prefixed
    `update:`. There is no separate "hybrid" engine; "stack" is the actual
    implementation.
  - *Replace:* only the selected prompt is sent, as the single first `system`
    message — the model never sees earlier wording.
  Disabled prompts are never sent. Chat debug records the exact stack
  (names, tags, char counts) with every request.
- **Profile routing lock.** The profile menu option is now **"No profile"**
  (not "Direct model"). While a profile is active, direct model picking is
  disabled and the model menu explains why; choosing "No profile" re-enables it.
- **Chat-debug scroll anchor.** Repaints now (1) skip the DOM entirely when the
  row set is unchanged and (2) otherwise restore the reading position by
  *entry id + offset into that entry*, so auto-refresh can no longer jump you
  to the top of the request you were reading. See `CHATDEBUG-MAP.md`.

## Provider adapter architecture

Provider transport is selected by a small registry in `lib/providers/`. The server only asks an adapter for model discovery and model execution; the adapter owns the wire protocol, streaming parser, and provider-specific errors. `openai-compatible`, `anthropic` and `gemini` ship built-in; any future adapter can register alongside them and appear in the provider editor without changing the chat engine or storage schema.

This is plugin-style modularity rather than automatic npm-plugin discovery: adapters must still be registered by code at startup. That keeps the core deterministic while avoiding provider-specific conditionals throughout the app.

## 1.6.10 SQLite persistence, memory foundations, modes and streaming code rendering

- SQLite is the source of truth for providers, model endpoints, profiles, settings, prompts, chats, messages, summaries, memory records, assets metadata, active context state and request logs.
- Legacy JSON files are imported and verified, then retained as timestamped `.migrated-*` backups.
- Model endpoints are capability-oriented so future chat, audio, image, video, OCR and embedding endpoints can share the same schema.
- The current chat is persisted as `simple-chat`, a no-tools mode registered under `lib/modes/`; new modes can be added without rewriting storage.
- Memory storage primitives now cover archival messages, conversation summaries, permanent/project/learning/procedural/task/knowledge records, embeddings, multimodal asset descriptions and context state.
- Streaming fenced code is temporarily closed for rendering while generation is still in progress, so the `<pre>` element exists immediately and its scroll position can be preserved between token repaints.

## 1.6.9 Batch model deletion, personalization onboarding, prompt transparency, provider adapters

- Model lists support multi-select deletion, with one confirmation and one atomic server update. Profile entries are kept paused so deleted models can be restored later if re-added.
- New model profiles require a non-empty name, and profile names are unique case-insensitively. Existing duplicate names are normalized on upgrade without changing their model membership.
- First launch shows a small personalization form for name, preferred name, age and agent name. The values stay in local settings and are included transparently in the effective system instructions sent to the model.
- Chat → System prompt now shows an exact effective-preview for the next request, including prompt order, template expansion and personalization context.
- Streaming code blocks preserve their own scroll position while tokens arrive, so long generated files remain scrollable before generation finishes.
- Provider transport is now an adapter registry. The current built-in adapter is `openai-compatible`; future native protocols can be added without changing chat routing or storage code.

## 1.6.8 Model curation, profile pausing, faster toggles, first-run prompt

- Provider model lists now use explicit local curation: fetched models are offered in a checklist before they enter the app. Unchecked models are never added. **Fetch models** later shows only provider models not already in the local list.
- Added per-model **Delete** alongside Enable/Disable. Deleting removes a model from the provider list without destroying the profile entry; a future fetch can discover the model again.
- Added **Test all** for configured provider models. Passing models are enabled; failing models are disabled. Profiles keep their entries and automatically skip globally disabled models.
- Profiles no longer need a second global enable/disable setting. Global model state applies everywhere, while a profile can independently **Pause/Resume** an item without removing it from the fallback chain.
- Profile model management now has a real provider tab strip and its own scrollable list so multiple providers remain clickable and usable at short viewport heights.
- Model enabled/disabled changes update the UI optimistically before the server round-trip, keeping the Chat homepage responsive.
- New installs ship with a useful editable default system prompt. A first-boot seed only fills an empty/missing default once; later edits, including intentionally empty content, are preserved.

## 1.6.7 Prompt checkboxes everywhere, calmer debug, persistent Chats rail

- **Prompt sending is now pure checkboxes.** The Chat prompt menu lists every
  saved prompt with a tick box; a chat sends exactly the ticked prompts
  (default first, later ones tagged `update:` in stack mode, merged into one
  message in replace mode). New chats start with only the **default** prompt
  ticked. Anything — including the default — can be unticked; all unticked
  means no system message, so the old "No system prompt" menu entry is gone.
- **Simplified prompt editor.** Settings → System prompts now shows a plain
  list (default pinned with a badge, never deletable but fully editable) plus
  one editor: click a prompt to open it, change name/text, Save. "New prompt"
  drafts an empty one and focuses the name field. The confusing saved-prompt
  dropdown and "Use for new chats" button are gone.
- **Chats rail persists.** The sidebar Chats list and New chat button stay
  visible on Settings and Debug too; New chat jumps home to a blank chat and
  clicking any chat opens it from wherever you are. Nav button renamed Chats.
- **Debug categories consolidated 6 → 4:** All · API & models · Tools ·
  Config & storage (provider/settings/storage events share one bucket).
- **Reasoning panel scroll fixed:** streaming repaints no longer reset the
  panel's open/closed state or its scroll position, so you can read and scroll
  thinking while it is still being written.
