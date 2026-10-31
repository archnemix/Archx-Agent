# Chat debugging: code locations and timeline

## The moving parts

| piece | where | what it does |
|---|---|---|
| `recordChatDebug(category, label, detail, chat)` | `public/js/state.js` | client-side ring buffer of local events (`other`), also stamped onto the supplied originating chat (defaults to active chat) (`debugEvents`, `debugTraceIds`) |
| `POST /api/chat` | `lib/server.js` | logs every provider attempt (`apiCalls`) with full request/response detail, keyed by `traceId` / `chatId` |
| `GET /api/chat-debug` | `lib/server.js` | returns `{ apiCalls, tools, other, providers }` for the trace ids of one chat |
| `toggleChatDebug(force)` | `public/js/ui.js` | shows/hides `#chat-debug-pop`, adds `#page-chat.dbg-open` (message column reflow), paints from cache, then fetches |
| `loadChatDebug()` | `public/js/ui.js` | async fetch → stores `chatDebugData`, rebuilds counts + provider filter, calls `renderChatDebug()` |
| `renderChatDebug()` | `public/js/ui.js` | builds the rows for the active tab (`api` / `tools` / `other`) into `#chat-debug-list` (the scroller: `max-height:52vh; overflow-y:auto`) |
| `startChatDebugAutoRefresh()` | `public/js/ui.js` | 3 s timer while the pop is open, tab is visible and page is `chat`; since 1.7.0 it first probes `GET /api/logs/rev` and only fetches payloads when the journal revision (or the chat's local debug events) changed |
| `formatDebugEvent(e)` | `public/js/ui.js` | one `<article class="chat-debug-item" data-log-id=…>` with time, label, error line and the JSON `<pre>` |

## Timeline of what happens (second by second)

- **t=0 — you click “Chat debug”.** `toggleChatDebug(true)`: pop un-hides (170ms pop-in), `.dbg-open` shrinks the message column, `renderChatDebug()` paints **cached** rows immediately (instant, no flash), then `loadChatDebug()` fetches fresh data.
- **t≈0.1 — fetch lands.** counts (`API calls / Tools / Other`), provider filter options and rows repaint.
- **t=3, 6, 9… — auto-refresh.** `loadChatDebug()` fetches; `renderChatDebug()` decides:
  - row-set signature identical → **return without touching the DOM** (your scroll, your selection, untouched);
  - rows changed → repaint, then **re-anchor** (below).
- **you scroll to an entry and read it.** Whatever happens at the next tick, the entry you had at the top of the viewport stays at the top, at the same offset inside it.
- **you switch chat / tab / provider filter.** Signature changes → repaint; anchor is best-effort by id (falls back to top when the entry no longer exists in this view).
- **you close the pop.** Timer keeps running but skips work unless the pop is open again.

## The bug you reported, precisely

Old behaviour: every refresh replaced `list.innerHTML` and then restored only
`list.scrollTop` (a pixel number). Two failure modes:

1. Entry **heights above you change** between refreshes (a streaming request
   gains `ms`, `usage`, an error line…) → the same pixel offset now points at a
   different place: you land at the *top* of the request you were mid-way
   through. Exactly your symptom.
2. Even with no changes at all, the DOM was rebuilt 20× a minute for nothing.

## The fix (1.6.6)

```
sig = tab + providerFilter + ids(rows)
if sig === lastSig → do nothing
else:
   remember (id of entry at viewport top, offset into it)
   repaint
   find same id → scrollTop = entry.offsetTop + offset
```

Anchoring by **identity + intra-entry offset** is immune to height changes
anywhere in the list; the signature skip removes pointless repaints entirely.
