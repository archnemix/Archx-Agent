# Archx Agent 1.0.0

A local-first AI workspace built on the user-selected reference interface. Chat,
provider/model setup, thinking, streaming code/tables, conversation branches, Studio,
Memory, Debug and Settings form the starting product—not twenty unfinished modes.

This repository now contains a **Node.js application**, not the previous Python app.
The new 1.0.0 version starts from the supplied reference's 1.9.0 source and retains its
MIT licence. It is a source version reset, not a published npm or desktop release.

## Run from source

Install **Node.js 22.5 or newer** (a current Node 22 LTS or newer is recommended).
From this directory, run:

```sh
npm ci
npm start -- --no-open
```

Open the printed address, normally `http://127.0.0.1:4173`. In Settings → Providers,
add your Ollama endpoint (`http://127.0.0.1:11434/v1`), leave its key empty, fetch/add
your model and choose it in Chat. Other providers can use their supported adapters.

For an explicit separate data folder:

```sh
node bin/archx-agent.js webui --data-dir ./my-data --no-open
```

Do not point this version at the former Python `real-ui-home` database: no Python-to-
Node data migration is implemented. Keep it backed up. Existing reference-version
Node data should also be backed up before testing. Keys are encrypted with a machine-
identity-derived key; this is not protection against an attacker controlling the same OS.

## Guides

- [Using the application](docs/USER_GUIDE.md): installation and everyday flows.
- [Technical guide](docs/TECHNICAL_GUIDE.md): responsibilities, storage and verification.
- [Testing the live application](docs/LIVE_TESTING.md): Memory controls, temporary chat, and the real-model runner session.
- [UI rules](UI-RULES.md): the visual and interaction contract.
- [Complete features and acceptance requirements](docs/FEATURE_REQUIREMENTS.md): full feature sequence and current gaps.
- [Plan](PLAN.md), [progress](PROGRESS.md), [decisions](THINKING.md).
- [Database architecture](DATABASE-ARCHITECTURE.md), [memory architecture](MEMORY-ARCHITECTURE.md)
  and [chat debug map](CHATDEBUG-MAP.md): inherited technical references.

## Honest scope

The inherited Web toggle searches from a question, supplies result snippets and shows
source cards; supplied links can be read separately. Iterative autonomous research is
still planned. Studio operations require suitable models/providers. A model exposes
thinking only if its provider returns it. No real provider, live search, Windows or
Tauri desktop validation is implied by fixture tests.

Run `npm test` for the new baseline checks. Browser checks are documented in the
technical guide. The old Python source/tests/workflows are intentionally removed.

## How work moves forward

One whole feature at a time, beginning with Simple Mode. Necessary behaviour checks
come before a live personal test by the user. Only their acceptance closes the
feature and allows the next one to start. Old milestones and reset percentages are
retired; useful existing regression checks remain, without duplicate test inflation.
