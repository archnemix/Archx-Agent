<!-- Purpose: Answers item 5's "research the best single or hybrid persistence mechanism" with a decision, and records the reference analysis item 8 asked for. -->
# Persistence: which mechanism, and why not more of them

Two separate questions were folded together in the list, and they have different
answers. The first is where settings and chat history live. The second is where
a *test run* lives. Deciding them separately is what keeps this small.

## 1. Settings and chats: files, not a database

| Candidate | Verdict | Why |
| --- | --- | --- |
| One JSON file per area (current) | **Keep** | The data is small and enumerable: ten providers, a model list, a display record, the chat list. It is read once at start and written on a handful of events. Writes are already atomic (temp file + rename) and every write passes a credential guard that refuses a document containing a key-shaped field. |
| SQLite | Rejected | It adds a native dependency, a schema, a migration path and a second thing that can corrupt, to answer questions nobody asks. No query here is more complicated than "find by id" over a few hundred rows. |
| Embedded key-value store | Rejected | Same cost, less inspectable. A user who wants to know what the Agent remembers can open the JSON today. |
| Hybrid: files for settings, database for chats | Rejected | The chat store is already a single JSON document with an upsert path and a bound on size. A second mechanism would mean two backup stories, two wipe paths and two failure modes, and the wipe story is a feature the owner explicitly asked for. |

The rule that matters more than the format: **one writer per file.** A second
writer is how the old `Agent::save_display` could have silently dropped the
launcher's memory matrix. That is why the launcher persists through
`Agent::save_launcher`, which reads the on-disk document, replaces exactly two
fields, and writes it back.

### Where each thing lives

| File | Owner | Overwritten by |
| --- | --- | --- |
| `settings.json` | the app | settings changes; `display` and `launcher_budget` are replaced field-wise, never wholesale, by the launcher |
| `chats.json` | the app | sending, editing, deleting a chat |
| `model-tests.json` | the app | a finished test row, the end of a run, or an explicit wipe |
| `debug/journal.json` | the app | every recorded request, bounded by a cap |

## 2. Test runs: the same file, one more field

A run is a fact about the past: who was asked, what came back, when, and whether
a request was even sent. It belongs next to the results it describes, so it is
the `run` field of `model-tests.json` — one writer, one wipe, one file to attach
to a bug report.

`apps/archx-agent/src/test_journal.rs` holds it:

* **Written as it arrives.** Every finished row is persisted immediately, so a
  crash, a closed dialog or a kill loses only the rows in flight.
* **Only a re-run overwrites.** `begin()` is the single call that discards the
  stored run, and it is only reached from `ConfirmCatalogProbe`.
* **Provenance per row.** `Source::Provider` means a request was sent and
  answered; `Source::NotSent` means it never left this machine (no usable key, an
  unapproved endpoint). Before this, both were stored as one opaque failure
  string, which is how a local refusal could be mistaken for a provider outage.
* **Our timeout travels with the row.** `request_timeout_secs` is recorded at
  the time of the run, so a time-out can be read years later as *our* 45 s limit
  rather than the provider's quota.
* **Never attempted is counted.** A cancelled run reports
  `N not attempted` instead of looking like a run that tested everything.

## 3. Closing the dialog is not cancelling

Item 5 said a click outside the testing dialog must not stop the run. The
behaviour is now:

| Action | Effect on a run in flight |
| --- | --- |
| click outside the dialog, press × | **nothing**; the run continues, rows keep saving, Settings reports progress |
| "Stop testing" in the dialog | cancels remaining requests; rows already received stay saved |
| "Wipe results" in Settings | deletes the file and the in-memory run |
| start a re-run | begins a new run id; this is the only path that replaces results |

## 4. Appendix: how the reference presents reasoning (item 8)

The owner asked for this to be established from the reference's HTML/CSS/JS
rather than from description. What those files actually do:

| Layer | File | Fact |
| --- | --- | --- |
| markup | `public/js/blocks.js` `ensureThinking()` | reasoning is a `<details class="thinking">` whose summary reads `Thinking…` while streaming and `Reasoning` afterwards |
| body | same function | `body.textContent = msg.reasoning` — **a text node, not parsed HTML**, i.e. preformatted text |
| styling | `public/css/chat.css` `.thinking-body` | `white-space: pre-wrap; font-size: 13px; color: muted` |
| height | same rule | `max-height: 300px; overflow-y: auto` — the panel scrolls at 300 px, it does not grow unbounded |
| open state | `blocks.js` | open while streaming unless the user has toggled it; collapsed on completion unless the user toggled it; the user's toggle always wins |
| streaming scroll | `followScroll(body)` | the reasoning scroller follows its own tail while text arrives |

Ours now matches on every row: the 300 px cap, the open-while-streaming and
collapse-on-completion rules with a user toggle that wins, the label change, and
preformatted text instead of Markdown. Where we deliberately differ: an explicit
"open by default" preference, which the reference does not have, is honoured for
an untouched panel.
