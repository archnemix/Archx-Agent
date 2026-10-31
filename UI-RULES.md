# Archx Agent — UI Rules & Design Schema (1.0.0 foundation)

This file is the **single source of truth for how the UI is spaced, typed and
structured**. It is plain markdown on purpose: add a rule here when you add a
UI pattern, delete the rule when you delete the pattern, and keep the code
matching the file. Imported historical version labels are provenance, not product metadata. Reviewers should diff UI changes against this document.

---

## 1. Principles

1. **Calm over clever.** Surfaces arrive with a 170–180 ms ease pop-in; nothing
   bounces, parallaxes or auto-plays. Motion only explains state changes.
2. **The conversation is the page.** Chrome (topbar, sidebar, composer) stays
   visually quieter than message content: muted colors, 1px borders, no heavy
   fills next to the message column.
3. **Never rebuild what a human is touching.** Streaming repaints must keep
   DOM identity for scrollable surfaces (code blocks, tables, reasoning
   panels). See rule 6.3.
4. **Every destructive or surprising action is confirmable or reversible.**
   Confirm dialogs for wipe/delete/move; toasts report outcomes.
5. **Local-first honesty.** The UI always states where data lives and whether
   keys exist (`endpoint-badge`, `privacy-note`, Storage page).

## 2. Spacing scale (tokens)

All gaps, paddings and margins resolve to the scale defined in
`public/css/base.css` (`:root`):

| token   | px  | used for                                                        |
|---------|-----|-----------------------------------------------------------------|
| `--sp-0`| 2   | micro gaps (list rows, icon optics)                             |
| `--sp-1`| 4   | tight inline gaps (badge rows, button icons)                    |
| `--sp-2`| 8   | default control gap: buttons in a row, field label → input, card rows |
| `--sp-3`| 12  | control padding (buttons, inputs), panel head padding, section item gap |
| `--sp-4`| 16  | card padding, topbar padding, grid gutters, page column gap     |
| `--sp-5`| 20  | section padding inside pages, modal body padding                |
| `--sp-6`| 24  | page header padding, message column top padding                 |
| `--sp-7`| 32  | large separations (page footer room, debug list bottom room)    |
| `--sp-8`| 40  | page-bottom breathing room (settings body bottom padding)       |

Rules:
- **2.1** Never introduce a raw px value for gap/padding/margin in new CSS;
  pick the nearest token. (Existing raw values were normalized in 1.7.0.)
- **2.2** Related things sit closer than unrelated things: items inside a
  control `--sp-1/2`, between controls `--sp-2/3`, between cards `--sp-4`,
  between sections `--sp-6/7`.
- **2.3** Vertical rhythm inside a card: head → body `--sp-3`, body rows
  `--sp-2`, card → next card `--sp-4`.
- **2.4** Page shell: topbar `--sp-3 --sp-4`; page head `--sp-6 --sp-6 --sp-3`;
  settings body `--sp-5` sides, `--sp-8` bottom.

## 3. Typography

- Base: `15px/1.6` system sans (body), mono for ids/code/timestamps.
- Scale: 10–11.5 px meta & badges · 12–12.5 px hints/controls · 13.5 px list
  rows & buttons · 15 px body · 16–19 px section titles · 26 px hero.
- Hints use `--muted`; never below `--muted-2` on any theme (contrast floor
  ≈ 4.5:1 at 11 px+).
- Uppercase eyebrows (`SECTION LABELS`) only with `letter-spacing ≥ .08em`
  and 10–11 px.

## 4. Color & theme

- Four themes (`dark`, `light`, `soft` = Warm, `funky`) driven purely by CSS
  custom properties in `base.css`. No component may hard-code a color; it must use a
  token (`--panel`, `--border`, `--accent`, `--danger`, `--ok`, `--warn`, …).
- Accent is monochrome (white on dark / black on light). Status colors are
  reserved: `--ok` success/connected, `--warn` config changes, `--danger`
  destructive/error, `--accent-2` secondary info (encryption, fallbacks).
- Syntax highlighting: dark hljs sheet is bundled; light/warm themes override
  token colors in `chat.css` (§ "light/soft theme syntax highlighting").
- `funky` is the single expressive theme: textures (dot grid, zigzag ribbon,
  confetti washes), gradient primaries/avatars, dashed panel borders, sticker
  shadows — all inline CSS/SVG data-URIs, scoped strictly to
  `[data-theme="funky"]`. Professional themes never gain textures.
- Selection state on option rows (profiles, prompts) is shown with an
  enable/disable **switch** (green = on), never with a bright inset line
  [6.8].

## 5. Components

- **Buttons**: `.btn` (default), `.btn.primary` (one per view where possible),
  `.btn.ghost` (contextual), `.btn.danger` (destructive), `.btn.tiny` (row
  actions). Padding `--sp-2 --sp-3`; tiny `--sp-1 --sp-2`.
- **Cards/panels**: 1px `--border`, radius `--radius-lg`, background
  `--panel`; head rows separated by 1px border, padding `--sp-3 --sp-4`.
- **Menus/popovers**: absolute, `top: calc(100% + 8px)`, radius
  `--radius-lg`, `--shadow`, pop-in animation; close on outside click & Esc.
- **Modals**: centered card, sticky head, `--sp-5` body gaps; confirm modals
  always offer Cancel.
- **Toasts**: bottom-right, 3 px status edge, auto-expire ≤ 7 s.
- **Empty states**: centered, icon/eyebrow + one sentence + the next action
  as a button. Never a blank panel.

## 6. Behaviour rules (how things must act)

- **6.1 Focus**: clicking non-interactive text blurs the composer (no caret
  blinking while reading); any printable key on the chat page refocuses the
  composer (ChatGPT/Grok-style).
- **6.2 Scroll pinning**: message list follows the bottom while pinned;
  scrolling up unpins and shows the "Jump to latest" pill; clicking it
  re-pins.
- **6.3 Streaming surfaces**: code blocks / tables / reasoning panels keep
  their DOM identity while tokens arrive (`public/js/blocks.js`). The actively
  growing block auto-follows its bottom edge; scrolling up inside it pauses
  following; returning to the bottom re-arms it. Completed blocks are never
  re-rendered or re-scrolled. Final paint after completion is in-place (no
  DOM rebuild, no scroll jump).
- **6.4 Navigation during generation** is allowed; the stream keeps writing
  to its own chat. Only one generation per chat is allowed; different chats may generate concurrently.
  Save, paint, tool, debug and model metadata belong to their originating chat.
- **6.5 Model lists** are cached per provider (5 min TTL, in-flight dedupe);
  explicit refresh only via "refresh list" / "Fetch models".
- **6.6 Polling** (debug page, chat debug) probes `/api/logs/rev` first and
  fetches payloads only when the revision changed.
- **6.7 Retries**: any provider probe (connectivity, model test, batch test)
  gets 2 attempts by default; only transient failures retry (408/429/5xx and
  network errors), never 4xx auth/validation.
- **6.8 Profiles** are managed-on by default but routing defaults to
  *No profile*; opening a profile in Settings never changes routing [6.8].
- **6.10 Durability**: every state write goes through the single-writer
  queue with a replayable journal (`write-queue.jsonl`); crashes between
  enqueue and drain lose nothing.
- **6.11 Branches**: destructive edits (edit-&-resend, regenerate) archive
  the old continuation; the composer's ⑂ menu can reopen any of them;
  switching archives the current tail first. "No profile" is a first-class
  bordered option row in the profile menu, not ghost text.
- **6.9 Caret** (`streaming cursor`) exists only while a message is actually
  pending; messages loaded from storage are never pending.

## 7. Pages & navigation

- Five main pages: Chat, Studio, Memory, Debug and Settings. Settings has its own section navigation.
- Settings sections: General · Tools · System prompts · Providers · Models ·
  **Profiles** · Storage · Danger zone. One section visible at a time; the
  section nav is a left rail (top row on ≤760 px).
- Profiles live on their own page (1.7.0) so Models ends at catalog curation.
- Chat debug is a popover anchored to the topbar; on ≥1000 px the message
  column reserves space so the popover never covers conversation.

## 8. Accessibility floor

- All interactive elements are real `<button>/<input>/<select>` with titles
  or aria-labels; focus-visible outline 2 px accent.
- Hit targets ≥ 26 px; icon buttons 32 px.
- `prefers-reduced-motion` disables animations/transitions.
- Text selectable everywhere except controls that declare `user-select:none`
  (summaries, badges).

## 9. Changing these rules

1. Edit this file first (add/remove/adjust the rule).
2. Implement in CSS/JS in the same change.
3. Note the rule number in `PROGRESS.md` (the current verification log).

## 10. Interrupted replies

Keep already received answer/thinking when a stream fails. Show its error separately,
mark completion unconfirmed if the final marker is absent, and never resend a POST
automatically. Stop is distinct from provider failure. Concurrent chat saves must not
replace each other in a single-target debounce slot.

## Memory library and mode controls

Use the existing neutral theme, not neon gradients or a second visual language.
A category bar, labelled search, compact rows and one detail pane provide progressive
disclosure. Destructive actions belong beside the selected item and require confirmation;
bulk storage cleanup stays inside a collapsed overview. On phones, list and detail
stack. Native switch inputs use a background thumb rather than unreliable input
pseudo-elements, with keyboard/focus behaviour preserved.

Keep mode selection inside Chat. Simple conversations may convert only to available,
implemented modes; conversion to a specialised mode locks that conversation. Disabled
future modes are named honestly, not presented as working chat prompts.

Design research: NN/G recommends visual hierarchy, progressive disclosure and filtering
for complex applications [1](https://www.nngroup.com/courses/application-ux/), and showing
only task-relevant form controls [3](https://www.nngroup.com/articles/4-principles-reduce-cognitive-load/).
These are interaction principles, not a template copied over the chosen reference.
