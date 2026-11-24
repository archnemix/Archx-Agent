# Quadrant visual & code audit — color/shade/spacing conformance (2026-11-23)

Method: every reference capture (`reference/reference-{chat,models,import-fixture}-1280.png`) and native capture (`visual/linux-*.png`) was split into four 640×400 quadrants and compared pair-wise at zoom, backed by pixel sampling (tile maps + exact hex probes) and a palette-conformance scan that flags every rendered color outside the 1.9.0 `base.css` token table. The reference CSS/JS source is the exact ground truth for values (`#000000` is `#000000` on the same screen — any drift is a defect).

## Ground-truth token table (reference `base.css`, dark theme)

| token | value | token | value |
|---|---|---|---|
| `--bg` | `#000000` | `--text` | `#f4f4f4` |
| `--bg-2` | `#0b0b0b` | `--text-2` | `#d4d4d4` |
| `--panel` | `#101010` | `--muted` | `#8a8a8a` |
| `--panel-2` | `#1a1a1a` | `--muted-2` | `#5c5c5c` |
| `--panel-3` | `#232323` | `--accent` | `#ffffff` (fills) |
| `--border` | `#2c2c2c` | `--accent-ink` | `#000000` |
| `--border-2` | `#404040` | `--user-bubble` | `#161616` |
| `--danger` | `#ef4444` | `--ok` | `#22c55e` |
| `--danger-soft` | `rgba(239,68,68,.12)` | `--warn` | `#eab308` |
| `--code-bg` | `#0c0c0c` | radii | 8 / 12 / 16 |

## Issues found (quadrant analysis + code), and the fix applied in `31d7a4b`

### Colors / highlighting

| # | Where | Found (native) | Reference | Fix |
|---|---|---|---|---|
| 1 | All borders/dividers (`LINE`) | `#333333` | `--border #2c2c2c` | const realigned |
| 2 | Secondary text (`GREY`) | `#b2b2b2` | `--muted #8a8a8a` | const realigned |
| 3 | Tertiary text (`DIM`) | `#919191` | `--muted #8a8a8a` (ref has one muted) | aliased to `#8a8a8a` |
| 4 | Success/failed colors | `#7ecf96` / `#e28b8b` | `--ok #22c55e` / `--danger #ef4444` | consts realigned |
| 5 | Primary fills (New chat, Add a provider, send, checkbox, toggle-on, avatar) | `#f4f4f4` | `--accent #ffffff` | new `ACCENT` used for fills; `WHITE` stays type `#f4f4f4` |
| 6 | Ghost/tiny button text | grey `#b2b2b2` | `.btn` color is `--text #f4f4f4` | text → `#f4f4f4` |
| 7 | Send button | grey `#6c6c6c` (disabled 40% white over panel) | web never disables send — always `--accent` | always accent; no-op guards unchanged |
| 8 | Stop button (while streaming) | transparent ghost | `.send-btn` (accent) with stop icon | accent + black icon |
| 9 | Model-menu selected row / provider selection | solid white fill or invented `#2b2b2b` | `.model-opt.sel` = `accent 10%` wash | `accent_wash()` rgba(1,1,1,.10) |
| 10 | Import dialog scrim | `rgba(0,0,0,.78)` (proved by dimmed New chat sampling `#363636`) | `.modal` overlay `rgba(0,0,0,.55)` | 0.55 |
| 11 | Import rows | invented `#373739`/`#171717` fills per row | `.model-import-row` transparent, hover `--panel-2` on `--bg-2` list | rows always transparent |
| 12 | Import row ID text | grey when unchecked | white (`--text`) always | white |
| 13 | Probe-fail dot | red `#ef4444`-ish | only passing dots go `--ok`; failed keeps `--muted-2` | quiet dot |
| 14 | Probe evidence sub-line | loud red/green text | `.import-detail summary` quiet `--muted` | `--muted` (pill keeps the only strong color) |
| 15 | Probe pills | `FAILURE` pastel borders | `.mini-tag.import-ok/.bad`: `--ok`/`--danger` text on 45% tint borders | via consts + `tag_badge` |
| 16 | Thinking panel | `#0c0c0c` fill, `#2b2b2b` border, r9 | `.thinking` = `accent 3%` wash, dashed `--border-2`, r12 | wash + `#404040` + r12 (dashed not available in Iced) |
| 17 | Code-block header | `#171717` fill | `--panel #101010` + `--border` | tokens |
| 18 | Error bubble | invented `#251112/#6c2e2e` | `--danger-soft` + `danger 45%` border | exact rgba values |
| 19 | Settings eyebrows ("MODEL CONTROL", "CATALOG", …) | grey `#919191` 11px | `.set-sec h4` = `--accent` white, 13px, uppercase, bold | white 12px bold (Iced has no letter-spacing) |
| 20 | Sub-nav active row (Models) | full grey box border | `.set-nav-btn.active` = `--panel` + inset 2px `--accent` left bar | `sub_nav` + drawn white bar |
| 21 | Verified toggle | white mini-toggle pill + inside label | reference uses a quiet switch widget + outside bold label/desc | drawn switch (36×20, knob) + stacked label |
| 22 | Text inputs | `#1c1c1e` fill, `#828287` focus | `--bg-2` field, `--border`, focus `--accent`, r12 | composer_input rewritten |
| 23 | Topbar monogram tile | `#2c2c2c` fill + `#464646` border | `.system-prompt-glyph` transparent + `--border-2`, r6 | tokens |
| 24 | Scrollbars (settings/models/import/model menu/chat log) | Iced default `#5d626d` thumb + `#43474e` track — a visible grey column on every scrollable page | browser overlay bars, dark | `quiet_scroll` on all seven scrollables |
| 25 | Primary hover | `#d9d9d9` | `filter: brightness(.92)` = `#ebebeb` | `#ebebeb` |
| 26 | Inputs/fields, `provider_choice` default | invented `#111111/#232323/#2b2b2b` blues | transparent / `--panel-2` / wash | tokens |
| 27 | Mini-toggle hover text | `#f4f4f4` | `--text-2 #d4d4d4` | `TEXT_2` |

### Spacing / layout (measured in the quadrant sheets)

| # | Where | Found (native) | Reference | Fix |
|---|---|---|---|---|
| 28 | Rail nav row pitch | 33px | 40px (`8/8` padding + 4 gap, 13.5px) | padding/gap/size |
| 29 | "New chat" height | 46px (fixed 40 + padding) | ~33px (`8/16` padding) | `.btn` padding |
| 30 | Empty state position | vertically centered (~80px lower) | 9vh top margin (`.empty`) | top-aligned + 72px |
| 31 | Empty-state gaps | 20 / 10 / 24 | 20 / 8 / 24 (`h2` margin `20 0 8`, `p` `0 0 24`) | 24 / 8 / 24 |
| 32 | Sub-nav rows | uneven pitch 37/51 (bogus spacer) | uniform 41px | spacer removed, gap 4 |
| 33 | Sub-nav column | no right divider | `--border` right rule | 1px divider |
| 34 | Page head | no bottom rule | `.page-head` bottom border | 1px divider |
| 35 | Page head type | 22px / 13px | 24px / 12.5px | sizes |
| 36 | Composer action row | toggle bottom-left, send bottom-right | `.composer-bar`: actions (chip + send) bottom-right | toggle moved next to send |
| 37 | Privacy note | `chats session-/only` hyphen wrap | single tidy line | copy shortened (`OS vault keys · session-only chats`) |
| 38 | Endpoint badge | fill + r12 | transparent + `--border`, r12, 8px padding | transparent, padding 8 |
| 39 | Manual-ID block | placeholder doubles as label | explicit white 13px label + `e.g. my-finetune-v2` placeholder | label added |
| 40 | Buttons ("Add a provider", etc.) | `11/18` padding | `.btn` `8/16` | padding |

## Functional checks re-run (not visual)

61 unit/state tests (12 reference-token regressions + 49 behavior tests) + the real-Smol wrapper run in CI on Linux/Windows/macOS; staged-import, consent, probe-confirm, and reasoning-collapse behavior unchanged by this presentation pass (diff touches `style.rs`/view code only).

## Known remaining differences (intentional, unchanged)

- Missing web features are absent, not faked: 5 sidebar destinations, Temp/Select, theme/delete footer icons, profile/system-prompt selectors, Chat debug, Web tool, durable chats, Studio/Memory/Debug.
- Copy stays honest-native ("OS credential vault", "session-only"), not the web's data-area wording.
- Brand mark is the supplied Archnemix mark; Iced cannot do dashed borders or letter-spacing (thinking panel border, eyebrow tracking).
- Native import rows show fuller bounded probe evidence (quiet sub-lines) than the web's collapsed `<details>`.
- These fixtures are synthetic/offline: no claims about live providers, real pointer/scroll behavior, a11y, or pixel-identity.
