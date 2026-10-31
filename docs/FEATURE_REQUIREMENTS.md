# Complete features and acceptance requirements

## What this list means

This carries forward the original product areas and the user's later corrections,
not the rejected implementation or its milestone/completion claims. It is reconstructed
from the requirements preserved in Git and this conversation; it is not a claim that
an exhaustive, separately approved original specification exists.

Each numbered step is a usable feature, not an internal subsystem or a half-feature.
Before starting it, resolve its full expected behaviour with the user. Include its
necessary settings, storage, permissions, errors, cancellation and usable interface
in that feature. Do not postpone those essentials as “polish”. Dependencies needed
for a feature must work before that feature is submitted for acceptance.

A feature closes only when its agreed behaviour works end to end, necessary checks
pass, it is available in the live app, and the user personally tests and accepts it.
Tests check distinct behaviours and meaningful failures, not repeated variants to
inflate a count. Fix rejected behaviour in the same feature before moving forward.

## Feature sequence and current position

The current application is the supplied Node reference at product version 1.0.0.
Old Python implementations do not count as implementations in this application.
The order below is the proposed sequence, beginning with Simple Mode; no future
step is being opened in parallel. The user can change the order before a step starts.

| Step | Complete user-facing feature | What must work before acceptance | Current application |
|---|---|---|---|
| 1 | Simple Mode | Add/edit/remove a provider and key; test connection and an actual chosen model; list/add/select models; normal contextual conversation; genuine provider-returned thinking; readable code/tables; streaming and nonstreaming; Stop; edit/resend, regenerate and alternate branches; multiple saved chats, rename/delete, reload; honest model/network/save failures; clean desktop/mobile controls. No invented thinking or silent resend. | Reference implementation present; selected fixture paths verified. Real-key/model testing and full edit/regenerate/branch journey remain unaccepted. **Current step.** |
| 2 | Agent Mode | A natural-language task drives model-selected tools, planning, execution, inspection and correction through to a real result. Include required file/command/browser tools, approvals, safe execution boundaries, tool/MCP configuration where required, progress, cancellation, saved/resumable tasks, artifacts and truthful failure/recovery. Subagents must actually coordinate if included in the agreed requirement. | Not implemented as an end-to-end mode. A mode registry or chat prompt is not an agent. |
| 3 | Research Mode | Enter only a question; AI generates/refines searches, discovers and reads sources, compares evidence, cites retrieved passages, retains follow-up context and searches again when needed. Include network consent, limits, safe fetching, untrusted-page handling and honest inaccessible-source/search failures. Supplied URLs are optional. | One-shot web search/snippets and supplied-link reading exist; autonomous conversational research is incomplete. |
| 4 | Coding workspace | Open/create a real project; understand files; propose and apply reviewable changes; execute approved commands/tests; inspect errors and fix them; show diffs/results; retain work and permit recovery/undo. Deliver working project artifacts, not just generated snippets. | Not implemented as a complete workspace. Chat code rendering is not this feature. |
| 5 | Learning Mode | Establish a goal/level; teach a structured course; generate relevant exercises; evaluate answers with useful feedback; adapt to weaknesses; save and resume progress. Include required media/exercise types and clear assessment limits. | Not implemented as a complete learning journey. |
| 6 | Experimental Mode | Define an experiment, data, parameters and success metric; execute real runs safely; collect actual results; compare them; retain reproducible configuration, logs and artifacts; handle cancellation/failures. | Not implemented. |
| 7 | Play Mode | Select a supported game/activity; enforce its actual rules; provide model interaction, useful feedback, saved state and a complete finish/restart flow. Agree supported activities before implementation. | Not implemented. |
| 8 | Voice and media | Real microphone/audio input, transcription, conversational response and speech playback, plus the required image/video understanding or generation flows. Include model/capability selection, inputs, output saving, cancellation and explicit unsupported-provider errors. | Inherited Studio has image/audio/vision paths; the complete requested multimodal journey is unaccepted. |
| 9 | Persistent memory and retrieval | Inspect, add, correct and delete the required memory types; apply relevant memories/context to real conversations; retrieve documents with provenance; retain state across restarts; respect scope/privacy and explain context limits. | Memory/context storage and UI exist; original full memory/retrieval behaviour is not certified. |
| 10 | Model management | Discover/configure supported local/cloud models; distinguish capabilities from unverified claims; manage selection and required local model lifecycle; route to compatible endpoints; expose privacy/cost/fallback behaviour; test actual capabilities and report failures. | Reference provider/model controls and profiles exist; full original manager is unaccepted. Basic provider/model setup belongs to step 1 and cannot be deferred here. |
| 11 | Dataset preparation | Import agreed formats, inspect/clean/transform records, deduplicate and split without leakage, apply required tokenisation/chat templates, preview/validate, export/publish where required, retain provenance and recover failed jobs. | Not implemented. |
| 12 | Training and model modification | Use a prepared dataset to run actual supported training/fine-tuning; configure resources, show real progress/metrics, stop/resume where supported, save checkpoints, evaluate and load/serve the resulting model. Do not substitute a toy trainer for requested model fine-tuning. | Not implemented. |
| 13 | Remote compute | Configure/authenticate a supported remote machine/service, transfer inputs, execute and monitor a real job, reconnect/recover, retrieve verified results and control costs/resources. Include provisioning if required by the agreed provider scope. | Not implemented. |
| 14 | Execution environments | Select/configure the agreed execution backends; run real tasks with appropriate isolation, resource limits, approvals, mounted files and collected results; cancel/clean up; clearly report unavailable backends. An invocation wrapper is not proof of isolation. | No validated complete execution product. Necessary safe agent execution cannot be deferred to this step. |
| 15 | Blender and 3D | From a request, create and edit an actual scene in Blender, perform the agreed modelling/material/lighting/animation operations, render and export useful artifacts, inspect results and revise them; save/resume and show real failures. | Not implemented or run in this Node foundation. Old Blender evidence is not acceptance here. |
| 16 | Automations | Create, approve, schedule and manage real tasks; run them reliably with the required timezones/cron/triggers, permissions, history, notifications/results, cancellation and restart recovery. | Not implemented. |
| 17 | Installable application | Install, launch, configure, update and uninstall on agreed platforms; package the actual current app; preserve/backup/restore user data; protect keys and network access; provide usable diagnostics and recovery. Validate Windows/desktop directly before claiming support. | Browser source app runs. Inherited desktop wrapper is unvalidated; no certified installer or Python-data importer. |

## Counting

**0 of these 17 full features have the user's acceptance under this process (0%).**
That is an acceptance count, not a claim that no code exists, a code-completion
percentage, or an estimate of time. Feature sizes differ. There is no separate
“foundation completed” percentage competing with this list.

## Personal test handoff for the current feature

The live preview listens on port **4173**, bound to `0.0.0.0`. Open the Arena live
preview; the browser must not try to connect to its own localhost. Add your key
inside Settings → Providers, not in chat. Test connection, save, import/select a
model, then send a real message. The key is saved server-side in this sandbox's
separate data area, encrypted at rest; the app is not certified for public hosting.
Use a restricted/revocable testing key. Browser fixture tests did not use real keys.

Report what fails or feels unclear in Simple Mode. That feedback remains part of
step 1. Agent Mode does not become the active step just because a demo can run.

This sandbox restricts outbound network access. External model API endpoints may
be blocked even with a valid key; a provider error must not be presented as proof
that the key is invalid. Real-provider acceptance requires a reachable endpoint or
running this same source locally where the provider is accessible.
