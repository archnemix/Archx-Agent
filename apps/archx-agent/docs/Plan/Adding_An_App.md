<!-- Purpose: The complete, self-contained guide an AI or a person follows to add an app to Archx AI Lab. -->
# Starting a new app in Archx AI Lab

Read this file alone and you have everything needed to add an app. Nothing here
requires reading the launcher's source, and nothing you do requires editing it.

## 0. The one-sentence contract

> An app is a folder under `apps/`, with an `app.toml` that declares its crate,
> its entry file, the function the launcher renders, and where its docs live.
> The launcher discovers it, shows a tile, and — once `status = "live"` — hosts it
> in-process. No launcher file changes.

## 1. Layout of the Lab

```
Cargo.toml              workspace members: "shared", "apps/archx-agent", ...
src/                    the launcher (Discover, rail, transition, Lab settings)
shared/                 archx-shared: vault, transports, storage, diagnostics, tokens
shared/assets/          brand, fonts, icons, model metadata
apps/<id>/              ONE APP: app.toml, Cargo.toml, src/, assets/, docs/
```

Three crates exist today: `archx-ai-lab` (binary, root), `archx-shared`
(`shared/`), `archx-agent` (`apps/archx-agent/`).

## 2. Create the app, step by step

1. **Make the folder and manifest.**

   ```bash
   mkdir -p apps/<id>/src apps/<id>/docs
   ```

   `apps/<id>/app.toml` (`<id>` must equal the folder name):

   ```toml
   id = "<id>"
   name = "My App"
   category = "SOMETHING SHORT"
   summary = "One sentence shown on the tile."
   status = "building"          # live opens; building shows but does not open
   art = "workbench"            # "agent" for a word-mark panel
   crate = "archx-my-app"       # omit while there is no code
   entry = "src/lib.rs"
   view = "home::view"          # the function the launcher calls
   docs = "docs"
   requires = ["archx-shared"]
   [[modes]]
   name = "ONE"
   [[modes]]
   name = "TWO"
   ```

2. **Make the crate.** `apps/<id>/Cargo.toml`:

   ```toml
   [package]
   name = "archx-my-app"
   version = "0.1.0"
   edition = "2024"
   publish = false

   [lib]
   name = "archx_my_app"
   path = "src/lib.rs"

   [dependencies]
   archx-shared = { path = "../../shared" }
   iced = { version = "0.14.0", features = ["tokio", "image", "svg", "markdown", "sipper"] }
   ```

3. **Register the crate** in the root `Cargo.toml`:

   ```toml
   [workspace]
   members = ["shared", "apps/archx-agent", "apps/<id>"]

   [dependencies]
   archx-my-app = { path = "apps/<id>" }
   ```

   This is the only line that mentions your app, and it is a path, not a name the
   launcher branches on.

4. **Write the entry function.** `apps/<id>/src/home.rs`:

   ```rust
   use iced::Element;
   use iced::widget::container;
   use archx_shared::style;

   /// The launcher calls exactly this signature.
   pub fn view(app: &App) -> Element<'_, Message> {
       container(/* your UI */).width(iced::Fill).height(iced::Fill).style(style::canvas).into()
   }
   ```

   `apps/<id>/src/lib.rs`:

   ```rust
   pub mod app;
   pub mod home;
   ```

5. **Flip to live** when it renders: `status = "live"`. The tile becomes
   openable and the launcher hosts it in-process.

## 3. What the build enforces

These run in CI on every push (`shared/src/apps.rs`), so a wrong manifest fails
the build instead of shipping a broken tile:

| Test | Enforces |
| --- | --- |
| `every_shipped_manifest_parses_and_is_unique` | ids unique, id == folder |
| `every_manifest_matches_the_files_on_disk` | `entry` file, `docs` folder and `Cargo.toml` exist; contract problems are empty |
| `a_declared_crate_is_a_workspace_member` | your `apps/<id>` is in `[workspace] members` |
| `live_apps_declare_how_they_render` | `status = "live"` implies `crate` + `entry` + `view` |
| `a_reserved_folder_needs_no_code_yet` | a code-less app is valid |
| `a_manifest_cannot_smuggle_paths_out_of_its_folder` | no `../` escapes, ids cannot contain `/` |

## 4. Rules every app obeys

1. **Never edit the launcher to add an app.** If you need a launcher change, the
   manifest is missing a field — say so instead of hard-coding.
2. **Never fork the launcher.** One application, several workspaces.
3. **Shared code comes from `archx-shared`.** Do not copy `storage`, `credentials`,
   `provider_api`, `diagnostics`, `style` or `persist` into an app folder.
4. **Settings belong to the owner.** The launcher keeps per-area text scale, the
   memory scope it hands to apps, the apps folder and wiping. An app keeps its own
   providers, models, runtime and storage pages.
5. **Secrets only in the OS vault** (`archx_shared::credentials`). Never in a file,
   never in a log, never in a URL.
6. **Wiping is explicit and per area**, and must state what it left alone.
7. **Evidence over claims.** Build/test output is recorded by CI under
   `apps/<id>/docs/Test_Results/Unreleased/`, not asserted by hand.

## 5. How the launcher talks to an app

- It renders the app with `view(app) -> Element<Message>`.
- It sends the app messages through the app's own `Message` enum.
- It tells the app which of its surfaces to show with a surface id:
  `"agent"`, `"settings"`, `"debug"` (an app decides what those mean).
- It reads back one flag: the app asks to leave with its own message, and the
  launcher returns to Discover.
- Nothing else is shared. The app never sees launcher state, and the launcher
  never sees app state.

## 6. Where to write your docs

Keep everything inside your app folder so the two apps never collide:

```
apps/<id>/docs/README.md              index (start here)
apps/<id>/docs/Architecture.md        modules, data flow
apps/<id>/docs/Decisions.md           what was chosen and rejected, with sources
apps/<id>/docs/Test_Results/           CI evidence
```

The Agent's records are in `apps/archx-agent/docs/`; the reserved second app's
space is `apps/training/docs/`. Read the Agent's
[Thinking.md](../../archx-agent/docs/Thinking.md) for the reasoning behind the
shared layers (persistence, rotation, diagnostics) before duplicating any of it.
