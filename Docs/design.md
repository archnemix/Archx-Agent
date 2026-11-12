<!-- Purpose: Defines the single source of truth for the AI Lab launcher’s visual tokens, typography and review criteria. -->
# Archx AI Lab — design system

## Scope and identity

Archx AI Lab is Archnemix's AI/ML launcher. **Archx Agent** is the future six-mode chat-and-agent app; Model Training and Fine-tuning are separate future destinations. Model Monitor is hidden for now, not cancelled. Unbuilt destinations always say *Coming Later* or *In Development* and never imply a model is running. The user-supplied Archnemix mark remains the sidebar and OS icon identity. Do not copy another launcher's brand or assets.

## Color tokens

These values correspond to constants in `src/style.rs`; reuse semantic roles rather than inventing card-specific text colors.

| Role | Value | Use |
| --- | --- | --- |
| Canvas | `#080808` | Main background |
| Rail | `#0D0D0D` | Sidebar behind the **transparent** logo |
| Surface | `#141414` | Featured text side and About panel |
| Line | `#333333` | Thin boundaries and inactive phase markers |
| Primary | `#F4F4F4` | Key headings, current phase, interactive text |
| Secondary | `#B2B2B2` | Descriptions and supporting labels |
| Muted | `#919191` | Small but legible eyebrow, disabled and utility text |

The selected navigation pill retains the restrained graphite gradient, silver rim and subtle lower shadow. Agent and model-workspace panels use dark native gradients, with no neon or expensive blur. Measured WCAG-style contrast: muted text `#919191` against `#202020` is about **5.17:1** and against canvas about **6.35:1**; do not darken small type below this role. Logo alpha must remain intact in the sidebar; the Windows/titlebar icon can keep its black backing.

## Font roles and weight budget

Bundle licensed **Manrope** for regular body copy, navigation and utility labels; use **Space Grotesk** selectively for editorial headings and kinetic model-workspace words. Agent's accepted `ARCHX / AGENT` kinetic visual stays in Manrope, preserving its current character. `src/style.rs` holds reusable `DISPLAY` (Space Grotesk Medium), `DISPLAY_BOLD` (Space Grotesk Semibold) and `LABEL` (Manrope Medium) definitions. Both font binaries are registered in `src/main.rs`; default body remains Manrope Regular.

| Role | Size | Weight | Where |
| --- | --- | --- | --- |
| Page heading | 38px | Space Grotesk Medium | Home title; About uses 35px where necessary |
| Section heading | 24px | Space Grotesk Medium | `AI workspaces` |
| Model kinetic word | 35px | Space Grotesk Semibold | **Only one** changing emphasis word per Training/Fine-tuning tile |
| Agent kinetic display | existing 39–52px | Manrope Regular | Existing approved Agent wordmark hierarchy; do not restyle casually |
| Tile name | 17px | Space Grotesk Medium | Inert destination names below panels |
| Body / nav | 14–16px | Manrope Regular / navigation Medium | Descriptions and navigation |
| Eyebrow / status | 11px, occasionally 10px in constrained panel footers | Manrope Medium | Short uppercase labels, never long instructions |

Do **not** bold every heading, caption or navigation row. Semibold is reserved for the two model-workspace kinetic words; page and section headings use Medium, leaving the Agent's larger wordmark and the selected navigation as primary emphasis. Keep short lines and whitespace around large display type; don't pack stage labels into a corner.

## Spacing, layout and motion

`src/style.rs` defines a 4px micro increment and reusable major spacing steps **8 / 16 / 24 / 36px** (`SPACE_1..4`). Use 4px for within-label optical gaps, 8px between closely related words, 16px for tile internals and tile-to-label rhythm, 24px for adjacent text blocks, and 36px between major page sections. The sidebar remains 220px wide; the supplied transparent mark displays at 116 × 116 without a black square. Major surfaces have rounded 10–15px corners and one-pixel borders. At 1024px-wide macOS runner captures, the shelf may continue below the fold but stays scrollable.

The Agent hero and tile retain the synchronized six-mode text/marker cycle (1500ms on Home, paused on About). Training and Fine-tuning are visually distinct **typographic labs**, not static captions or 3D objects: **Model Forge** communicates creating/training a model; **Refinement Studio** communicates adapting an existing one. On hover only, a central editorial word and a three-part phase marker change every 700ms. The words (`DESIGN / TRAIN / EVALUATE` and `SELECT / ADAPT / VALIDATE`) are conceptual, **not live operational progress**; pointer exit resets to the first state. Cards remain inert and labelled Coming Later. Avoid continuous idle animation for these two model tiles. Reduced-motion and RAM/CPU preference settings remain future requirements, not silently implemented.

## Cross-OS review gate

After a GUI change, build/run on Linux, Windows, and macOS; inspect Home, About, Agent frozen phases and both model-card hover phases. Put screenshots only in `Docs/Test_Results/Unreleased/visual/` and tests/build/PE logs only in `Docs/Test_Results/Unreleased/non_visual/`. Static phase captures demonstrate distinct render states but cannot establish live motion smoothness or actual mouse movement; user hands-on review remains required. Windows release must have GUI subsystem 2, but `CompanyName=Archnemix` is not a verified code signature. Continue to ship a repository-hosted portable Windows build for review without claiming it is signed.
