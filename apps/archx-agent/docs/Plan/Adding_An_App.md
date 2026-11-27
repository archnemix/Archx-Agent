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

You work on YOUR OWN BRANCH, never on the main line. Check out a branch from the
base code you were given and keep all of your work there:

    git checkout -b app/<id>-<your-name> origin/<the-branch-you-were-given>

Push only to that branch (`git push -u origin app/<id>-<your-name>`). Never push
to the main branch, never force-push, never merge the main line into yours. When
your app is finished, green and you have reported it, you are done: the launcher
owner imports your branch after the owner of the product has confirmed the app
works. Do not open a pull request into the main line yourself.

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
  1. `cargo test -p <id>` passes (or the "App harness" workflow is green). Rust
     may not be installed where you work, so push and read the CI result; never
     claim a test you did not see pass.
  2. `git push -u origin app/<id>-<your-name>` from your branch, then run
     "App harness" with app = <id> on that branch. It writes the log back to
     your branch. A `SKIP` render line for a brand-new app is expected: the
     launcher can only draw a crate it already links, and only the launcher
     owner adds that.
  3. Only then: set `ready = true` and `status = "live"` in app.toml, and tell
     the launcher owner to import your branch and host it (§7 steps 5-7).

  ready = true alone does NOT publish the app. Publishing is the launcher owner's
  one-line release switch; until it is added your app is HELD, which is correct
  and visible in launcher settings. Never add that line yourself.

If you need the launcher changed, do not edit it: write the request into
apps/<id>/docs/Launcher_Request.md using the template in §8 and report it.

Report back with: the files you created, the CI run that passed, anything you
changed outside apps/<id>/ (one line: the workspace member), and any launcher
request you wrote.
```

If the other app will be worked on **in parallel** with this one, everything above
still holds — that is what `ready = false` is for. Two rules keep the two work
streams from colliding:

* one folder per app, one app per branch;
* the only shared files are the root `Cargo.toml` members list (add one line,
  never reorder) and this document (ask before editing it).

### Starting a branch, and how it comes back here

This is the whole workflow, in the order it happens.

**1. You hand over the base.** Give the other AI the repository URL and the exact
branch to start from (today: `arena/53d9bc26-archx-agent`, or a tag/commit you
name). One line is enough, and it is what belongs in the hand-off: *"clone this
repo, branch from `<branch>`, work only in `apps/<id>/`, push only your branch."*
Do not give out a copy of your working tree as a zip: a branch is what makes the
import a reviewable diff instead of a folder somebody has to trust.

**2. It branches, and stays on that branch.**

```text
git clone https://github.com/archnemix/Archx-Agent && cd Archx-Agent
git checkout -b app/<id>-<your-name> origin/arena/53d9bc26-archx-agent
# ... build, commit, push ...
git push -u origin app/<id>-<your-name>
```

The branch name is `app/<id>-<who>`. One app per branch; a branch with two apps
cannot be imported in one piece.

**3. It proves the app there.** `cargo test -p <id>` locally if Rust is
available; otherwise push and run `Actions → App harness → app: <id>` on its own
branch. That job builds and tests only that crate and writes the log back onto
its own branch. A green run on its own branch is the only evidence that counts —
a screenshot from somebody's laptop is not.

The job also tries to render the app inside the launcher, and for a brand-new app
it logs `SKIP: ... not in this release`. That is correct, not a failure: the
launcher hosts apps **in-process**, so it can only draw an app whose crate it
already links. Until the launcher owner adds that link (step 6), the app's own
crate and its tests are the evidence. An app that wants a picture before then
should ship its own snapshot runner inside `apps/<id>/`.

**4. It stops and reports.** Branch name, CI run id, the files it touched, and any
`Launcher_Request.md` it wrote. It does not merge, and it does not add its own
`register` line.

**5. You look at it, and you confirm it works.**

```text
# on your machine, without touching the main line:
git fetch origin app/<id>-<your-name>
git diff --stat origin/arena/53d9bc26-archx-agent...origin/app/<id>-<your-name>
```

Three things to read in that diff before you run anything:

* every changed path is under `apps/<id>/` — plus **at most one line** in the root
  `Cargo.toml` members list. Anything else is a launcher edit by an app author
  and goes back with the reason;
* no secret, token, key or `.env` in the patch (`git diff | grep -iE 'sk-|api[_-]?key|token'`
  is a fast first pass);
* `app.toml` has `ready = true`, `status = "live"`, and a `view` that exists.

Then build and test it out of tree, so your working copy stays clean:

```text
git worktree add /tmp/<id> origin/app/<id>-<your-name>
cd /tmp/<id> && cargo test -p <id> && cargo build -p <id>
```

**6. You import it.** Merging is the import, and it happens only after step 5.
Import is *not* publishing: after this merge the app compiles, but it is `Held`,
so it has no tile and appears in Lab settings as held out of this build.

```text
git checkout arena/53d9bc26-archx-agent && git pull --rebase
git merge --no-ff origin/app/<id>-<your-name> -m "Import app/<id>"
```

**7. You add hosting, then check the design, then publish.** This is the part only
you can do, because it is the part that touches the launcher:

1. link the crate: add `archx-<id> = { path = "apps/<id>" }` (or the crate's real
   name) to the root `Cargo.toml` `[dependencies]`;
2. add its one arm in `src/navigation.rs` (the `hosted` match) and its `Page`
   variant — that is what makes the rail entry and tile open something;
3. add `.register("<id>")` to `src/main.rs::release()` and `COMPILED_APPS` in
   `shared/src/apps.rs`, keeping the contract test green;
4. run the full `GUI review` and look at the rendered screenshot: is the app's
   surface inside the Lab's own padding, type scale, borders and colours?

Only when 1–4 are all true is the app published. If the design does not fit, the
fix is a shared token or a manifest field, never a launcher branch on the app's
name (§9.3). If the app is not ready to be seen after all, delete the `register`
line: it goes back to `Held` and Lab settings says so — nothing is silently
dropped.

If two approved branches both add a line to the root `Cargo.toml`, the merge is a
one-line conflict in that list: keep both lines, ordered as the file already is.
That conflict is the whole reason each app owns a folder and nothing else.

**What "import" is not.** It is not a copy of files off somebody's disk, and it is
not a cherry-pick of "just the app folder" from a branch that also changed the
launcher. If a branch mixes launcher edits into app work, send it back: a clean
branch is the price of a fast import.

## 7b. The host contract: what the launcher actually calls

This is the part you cannot infer from `view = "home::view"`. The launcher hosts
an app **in-process**, the way it hosts the Agent, so it needs a few more hooks
before it can open your app. Write your crate against this list; if you match it,
step 7 of the import is a wiring change and nothing else.

```rust
// In apps/<id>/src/home.rs — the only function the manifest names.
pub fn view(app: &App) -> Element<'_, Message>;

// In apps/<id>/src/app.rs
pub struct App { … }
impl App {
    /// The launcher loads the persisted document and hands it over. `None` on a
    /// first run or in a snapshot run. A second app loads its own document with
    /// `storage::load_app_body("<id>", "<area>")` instead.
    pub fn new(persisted: Option<PersistedSettings>) -> Self;

    pub fn update(&mut self, message: Message) -> Task<Message>;

    /// Pages are the app's own enum. The launcher names a surface with a short
    /// string ("home", "settings", "debug") and the app maps it.
    pub fn enter_surface(&mut self, surface: &str);

    /// Called when the user leaves for the launcher: abort in-flight work and
    /// settle state, so nothing keeps running behind another page.
    pub fn leave_app(&mut self) -> Task<Message>;

    /// Set when your app wants the launcher to go back to Discover on its own
    /// (the "Back to launcher" button). The launcher reads it after every update.
    pub left_for_launcher: bool;

    /// Screenshot runs only: pin one surface and skip anything restored from
    /// disk, so a review image never depends on the author's machine.
    pub fn prepare_snapshot(&mut self, surface: &str);
}
```

**What the launcher gives you, and what it does not:**

* **Text scale** — it holds `DisplaySettings` (per-area `TextScale`) and writes it
  to `settings.json`. It can hand the whole struct to your app at start-up; it
  does **not** yet push live changes into a second app. Use
  `archx_shared::persist::TextScale` for your own type sizes so a scale change
  lands the day that wiring does.
* **Memory scope** — this is `Launcher::Scope` in `src/app.rs` and it is
  **the launcher's own type**, not a shared one (the Agent keeps a private copy).
  A second app should treat scope as advisory and keep its own resident-data
  policy; asking for it to be promoted to `archx_shared` is a legitimate
  `Launcher_Request.md`.
* **Vault keys** — use `archx_shared::credentials::Vault` directly. One vault for
  the whole Lab: a key saved by the Agent is the same key your app reads. Never
  invent a second vault and never pass key text between apps.
* **Timers** — iced returns `Subscription` from the *application*, not from the
  page, so the launcher owns subscriptions. An app that needs a repeating clock
  (a live loss curve, say) must drive it from a `Message` the launcher ticks, or
  ask for one. Today the launcher only ticks for page transitions and snapshots.

**Persistence is per app, and there are two ways to get it wrong:**

```rust
// Wrong: overwrites Archx Agent's own files (settings.json, chats.json, …).
storage::save(storage::Area::Settings, document)?;

// Right: root()/apps/<id>/<area>.json, same checks, same envelope.
storage::save_app("<id>", "settings", document)?;
let document = storage::load_app_body("<id>", "settings");
storage::wipe_app("<id>", "settings");
```

Both names are slugs (lowercase, digits, `-`); `app_path` returns `None` for
anything else, so an id can never walk out of its folder.

**Naming.** The folder is the app id (`apps/training/`); the crate is `crate =
"archx-training"` in the manifest. They are different strings on purpose, and the
`App harness` reads `crate` from your manifest — it does not assume the two match.

## 8. Releasing an app, and holding one back

`ready` decides what the *launcher* sees at runtime. Publishing is a separate,
deliberate act, because the launcher hosts apps **in-process**: an app can only
run if its Rust crate is compiled into the launcher binary. So "publish" and
"hold" are answered by the build, not by a file an app can edit.

There are exactly two gates, and both are one line:

| Gate | Where | Publish | Hold |
| --- | --- | --- | --- |
| The crate is built | root `Cargo.toml` → `[workspace] members` | `"apps/<id>"` present | remove the line |
| The app is in the release | `src/main.rs` → `release()` | `.register("<id>")` present | remove the line |

A folder that declares code but is not registered is **held**: `App::release()`
returns `Release::Held`, `registered()` filters it out, and launcher settings list
it as "held out of this build" so the hold is never silent. Nothing inside
`apps/<id>/` can change this — that is the point.

```rust
// src/main.rs
pub fn release() -> archx_shared::apps::Builder {
    archx_shared::apps::Builder::new()
        .register("archx-agent")
        // .register("training")   <- uncomment when training is ready to publish
}
```

### Checking one app while it is held

The `App harness` workflow builds and tests **one app on its own**

```
Actions → App harness → Run workflow → app: <id>
```

It runs `cargo test -p <id>` and `cargo build -p <id>`, records the result in that
app's own `docs/Test_Results/`, and never touches the release. If the app is also
in the release it renders the launcher and screenshots it; if it is held it says
so and stops after the build.

The launcher has one harness-only switch for looking at a held app:
`ARCHX_SNAPSHOT_APPS=<id>` marks that one app as present **for this run only**.
It is read once at start-up, never saved, and changes nothing about what a real
build contains.

### If an app needs the launcher changed

Apps cannot edit the launcher, so a needed change becomes a request. Write it in
your app folder, then stop:

```
apps/<id>/docs/Launcher_Request.md
```

<!-- template: copy this block into apps/<id>/docs/Launcher_Request.md -->
```markdown
# Launcher change requested

What: one change per file. Example: "Show an app's version under its status line."
Why: what the app cannot do without it.
Design fit: which existing token or component it uses (Plan/Architecture.md), and
  a one-line sketch. If it needs a new token, say so explicitly.
Screenshot or mock: optional, in this folder.
Requested by: <branch or agent>, <date>
```

Answered requests get a `## Answer` line appended with the build that carried it.

The launcher owner (the main assistant) reads these notes, applies the change to
the **one** launcher — never a fork — following the design scheme, and ships it
with the next build so the app and the launcher land together. A note that asks
for a second launcher, or for the launcher to branch on an app's name, is
rejected: that is the one thing the manifest system exists to prevent.

### What "in parallel" actually means

| Situation | What compiles | What you can test |
| --- | --- | --- |
| App A released, app B being built | A only | A in the launcher; B with `App harness` |
| Both released, B still rough | A and B | both; B can be held by deleting its `register` line |
| B needs a launcher change | A and B | A normally; B after the change lands |

A held app still compiles in the workspace if it is a member, so the author gets
a guaranteed build; deleting the member entry stops even that, and the `App
harness` job is then the only thing that builds it.

## 9. Standing instructions to the main assistant

These are the standing orders for the assistant that owns the launcher. They
exist so app work can arrive at any time and be integrated in one pass.

1. **Read every `apps/*/docs/Launcher_Request.md` first**, before changing a line
   of the launcher. A request is the only way an app asks for a launcher change.
2. For each request: check it against the design scheme (tokens and components in
   `Plan/Architecture.md`). If it fits, implement it once, in the shared launcher.
   If it does not, reply in the same file under a `## Answer` heading with the
   reason and the closest thing that does fit.
3. **Never fork the launcher, and never branch on an app's name.** If a tile needs
   a different treatment, it becomes a manifest field or a shared style token.
4. **Release in one batch**: collect finished apps, add their `register` lines and
   workspace members together, run the full GUI review, and land them in one
   build. An app is published when its tile renders and its harness job is green.
5. **Keep a hold visible**: a ready app that is not registered must appear in
   launcher settings as held. Never silently drop an app.
6. **Delete a request file once it is answered** (or leave it with `## Answer`);
   do not let answered requests pile up.
