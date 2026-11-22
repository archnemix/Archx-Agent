# Current user-supplied Agent UI reference

`archx-agent-reference.tar` is the received Archx Agent 1.9.0 archive, fetched with GitHub Actions from the user's Drive link. `archx-agent/` is its inspected extraction (MIT license preserved). The SHA-256 and member inventory are in `archive-inventory.txt`. This replaces the older screenshot/HTML reference, which was removed at the user's request.

Use `archx-agent/public/` (especially `index.html`, `css/`, `js/ui.js`, `js/blocks.js`) and `archx-agent/UI-RULES.md` as the target for a *native Iced recreation*. Do not ship the Node server or put provider keys into these public Git files. `node_modules/` and runtime data are not committed. Its backend is useful to understand interaction semantics but is **not** the native app's security implementation.
