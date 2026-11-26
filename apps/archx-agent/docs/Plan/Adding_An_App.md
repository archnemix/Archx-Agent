<!-- Purpose: The complete, self-contained guide an AI or a person follows to add an app to Archx AI Lab. -->
# Starting a new app in Archx AI Lab

Read this file alone and you have everything needed to add an app. Nothing here
requires reading the launcher's source, and nothing you do requires editing it.

## 0. The one-sentence contract

> An app is a folder under `apps/`, with an `app.toml` that declares whether it is
> **ready**, its crate, its entry file, the function the launcher renders, and
> where its docs live. The launcher registers only ready apps. When an app is
> ready and `status = "live"`, the launcher hosts it in-process. No launcher file
> ever changes.

Two switches, and they mean different things:

| Field | Question it answers | Effect |
| --- | --- | --- |
| `ready` | Is this app finished enough to exist in the product? | `false` (or missing) ⇒ **the launcher ignores the folder entirely**: no tile, no rail entry, no build, no test. `true` ⇒ the app is registered. |
| `status` | Once registered, how does it open? | `live` and `preview` open; `building` and `planned` show a card that says so. |

`ready = false` is what lets **two to five apps be built at the same time**: each
one sits in its own folder, dark to the launcher, until its author flips the
flag. Nothing a half-built app contains can move, rename or break a tile that
already works.

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
   ready = false                # keep the launcher dark while you build
   status = "building"          # live/preview open; building/planned do not
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

5. **Flip `ready = true` only when the app renders and `cargo test --workspace`
   passes.** Then set `status = "live"` to make the tile openable. Flipping
   `ready` is the one moment the launcher changes, and it needs no edit from you.

## 3. What the build enforces

These run in CI on every push (`shared/src/apps.rs`), so a wrong manifest fails
the build instead of shipping a broken tile:

| Test | Enforces |
| --- | --- |
| `every_shipped_manifest_parses_and_is_unique` | ids unique, id == folder |
| `every_manifest_matches_the_files_on_disk` | `entry` file, `docs` folder and `Cargo.toml` exist; contract problems are empty |
| `a_declared_crate_is_a_workspace_member` | your `apps/<id>` is in `[workspace] members` |
| `live_apps_declare_how_they_render` | every registered live app declares `crate` + `entry` + `view` |
| `a_reserved_folder_needs_no_code_yet` | a code-less, unready app is a valid manifest |
| `an_unready_folder_is_invisible_to_the_launcher` | `ready = false` or a missing `ready` line ⇒ no tile, for the launcher and for `find` |
| `a_ready_app_cannot_lie_about_being_open` | `ready = false` can never open, even with `status = "live"` |
| `a_manifest_cannot_smuggle_paths_out_of_its_folder` | no `../` escapes, ids cannot contain `/` |

## 4. Rules every app obeys

1. **Never edit the launcher to add an app.** If you need a launcher change, the
   manifest is missing a field — say so instead of hard-coding.
1b. **Never flip `ready = true` on someone else's app**, and never flip your own
   `ready` on while another branch is mid-change to the launcher. `ready` is the
   hand-off point between an app and the product.
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

## 7. The hand-off: what to tell the other AI

Copy the block below into a fresh chat when you want a second AI (or a second
person) to build one of the other apps. It is written so it can be pasted
verbatim; nothing in it needs explaining first.

```text
You are building ONE app inside the Archx AI Lab repository: <id> (working title
"<name>"). Work only inside apps/<id>/. Do not edit the launcher: src/*.rs,
Cargo.toml at the repository root, or apps/archx-agent/**.

Read these two files first, in this order:
  1. apps/archx-agent/docs/Plan/Adding_An_App.md  (the contract you must satisfy)
  2. apps/archx-agent/docs/Thinking.md           (why the shared layers exist)

Your app already has the shape it needs:
  apps/<id>/app.toml      ready = false   <- keep it false until you are done
  apps/<id>/docs/         write your own docs here, nowhere else

Build rules:
  * Cargo: crate name archx-<id>, lib name archx_<id>, edition 2024,
    depends on archx-shared (path = "../../shared") and iced 0.14.
    Register it by adding one entry to the root [workspace] members:
    "apps/<id>". That single line is the only file outside your folder you touch.
  * Export `pub fn view(app: &App) -> Element<'_, Message>` from home.rs and
    declare `view = "home::view"` in app.toml.
  * Import shared behaviour; never copy it. storage, credentials, provider_api,
    diagnostics, style, persist and model_meta all live in archx_shared.
  * Never put a secret in a file, a log or a URL. Keys go through
    archx_shared::credentials into the OS vault.
  * Every persisted file must be written through archx_shared::storage::save and
    read through storage::load_body (the envelope is added for you).

How you know you are done:
  1. `cargo test --workspace` passes. Rust is not installed locally in every
     environment, so push and read the CI result; never claim a test you did not
     see pass.
  2. The app renders in the launcher, opens, and closes back to Discover.
  3. Only then: set `ready = true` and `status = "live"` in app.toml.

Report back with: the files you created, the CI run that passed, and anything you
had to change outside apps/<id>/ (there should be exactly one line).
```

If the other app will be worked on **in parallel** with this one, everything above
still holds — that is what `ready = false` is for. Two rules keep the two work
streams from colliding:

* one folder per app, one app per branch;
* the only shared files are the root `Cargo.toml` members list (add one line,
  never reorder) and this document (ask before editing it).
