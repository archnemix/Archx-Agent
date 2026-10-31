# Working decisions

## One foundation

Use the supplied Node reference as the main application at version 1.0.0. The
rejected implementation, old milestone system and historical completion claims
are not the active plan. Preserve requirements in plain English, not competing code.
Useful reference-based bug fixes stay in place; removing working chat fixes is not
necessary to retire the old implementation.

## One complete feature at a time

Start with Simple Mode. A full feature includes its setup, actual useful output,
necessary integrations, persistence, clean controls, errors, cancellation and recovery.
Do not label a subset complete while essential parts are postponed. Agree the
feature's supported scope before implementing it; do not silently narrow requirements.

Use the minimum meaningful tests for distinct paths and risks. Keep useful existing
checks, avoid duplicates, and never treat quantity as quality or acceptance.

Expose the actual app on the live port so the user can configure a provider/key and
test it personally. Wait for their acceptance, fix findings in the same feature, then
move on. Current acceptance count is zero. Agent Mode has not started as a complete
implemented feature. See the feature requirements for the full sequence and gaps.

## Memory and real-model testing pass

The user explicitly requested this usability pass before continuing the feature
sequence. Keep the reference theme; use a searchable library with category counts,
selectable details, confirmations and safe per-item deletion. Preserve generated
Studio files as actual library assets. Do not claim semantic indexing when search
scans saved text. A temporary chat must be excluded before transport/persistence and
before request logging, not merely hidden in the sidebar.

Use a whole-app runner preview instead of pretending this sandbox can reach a
Cloudflare model endpoint. The session uses actual small and reasoning models through
Ollama plus real speech/transcription/OCR engines. Only the explicitly named image
fixture is fixed output. The public repository's artifact link is not private hosting.
Keep user data out of that disposable shared session. Necessary tests were added for
five distinct lifecycle/library/privacy/file-boundary behaviours, not duplicate counts.
