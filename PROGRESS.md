# Current feature status

## Position against the requirements

The active product is the supplied Node reference, version 1.0.0. The rejected
Python implementation is absent from the active tree; its historical claims do
not count as product progress. Old milestone/reset percentages are retired.

**Accepted full features: 0/17 (0% accepted, not percentage of code written).**
The complete list and acceptance boundaries are in
[Complete features and acceptance requirements](docs/FEATURE_REQUIREMENTS.md).

## Current feature: Simple Mode — awaiting full verification and user acceptance

Present: provider/key setup, connection/model controls, chat, provider-returned
thinking, streaming, Stop, conversations, edit/regenerate/branches and SQLite storage.
Presence is not acceptance. Previous local checks exercised selected fixture-backed
provider/chat paths, concurrent conversations, failure handling, Stop and reload.
They did not certify real inference or every chat control. Full edit/regeneration/
branch behaviour, real provider use and the user's usability test remain open.

Agent Mode is not implemented. Research is only inherited one-shot search/snippets,
not the required autonomous question-driven research. Other areas are listed plainly
in the feature requirements; database tables and visible pages are not full features.

## Available for personal testing

Port 4173 serves the real reference-based app with its own separate data area and no
seeded provider credentials. The user can enter a key in Settings → Providers, test,
save, select a model and chat. The app sends requests through its backend. Never
paste keys into conversation or point this app at the old Python database.

## Verification policy

Keep meaningful existing checks; add only missing distinct behaviour/risk checks.
Do not use test totals or structural cleanup as feature completion. No new tests or
new product modes were added for this planning reset. User acceptance is the gate.

After this documentation/UI wording cleanup, the existing regression suite and
browser journey were rerun successfully, with no additional tests added. External
provider access can be blocked by this sandbox's outbound network restrictions;
entering a key is supported, but successful real inference is not promised here.

## Requested Memory/UI/model-testing pass

Implemented: searchable/paged Memory categories, item details, add/edit/delete saved
knowledge, targeted chat/message/code/file deletion, generated Studio image/speech
asset storage, file previews/downloads and safe file ownership checks. Deleting a
message also clears matching branch copies and derived conversation context/logs.

New chat reuses an empty draft. Temporary chats are not sent to persistence, are not
retained in server state or request logs, and are discarded when leaving the chat.
Switch geometry is fixed without input pseudo-elements. Chat exposes a mode picker;
unimplemented modes stay disabled and specialised modes are locked server-side.

Verification: 33 Node checks pass (five additional distinct behaviour checks); the
existing Chromium journey was extended rather than replaced by a duplicate suite.
It passes draft reuse, temporary-state exclusion/discard, Memory search/deletion,
saved-knowledge add/edit/delete and switch geometry, plus existing chat/provider/
stream/reload checks, with zero page errors and no 390px horizontal page overflow.

Previous Q6 GitHub run 41205612331 passed the real-model startup gate and published a Cloudflare
session artifact. Models: SmolLM2 135M Q6_K, Qwen3 0.6B reasoning via Ollama, Whisper
tiny transcription, eSpeak speech and Tesseract OCR. Fixed-image delivery is labelled
as a fixture, not generation. The live link is in the [preview-link artifact](https://github.com/archnemix/Archx-Agent/actions/runs/41205612331/artifacts/13043588337).
Artifact download from this sandbox was blocked by its Azure redirect; the user can
download it directly through GitHub in their browser.
This is not general vision, high-quality neural TTS, or real image generation.

No full original feature is marked user-accepted by these checks. Await personal
feedback. See the live-testing guide for session expiry, privacy and supported scope.

## Requested four-bit model session

The user requested running the model and continuing independent testing, not just
handing over setup instructions. Session 41206423857 is starting SmolLM2 **135M**
Q4_K_M through Ollama (the available Smol model is not 125M). A real-browser gate now
sends a conversation and follow-up through the guarded app, checks saved reload,
records actual responses/screenshots, and removes its test chat before handoff.
Startup/results are pending; no browser success is claimed until the job passes.
