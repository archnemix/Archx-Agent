<!-- Purpose: The paste-ready hand-off for a second AI building one of the other apps. Canonical copy lives in apps/archx-agent/docs/Plan/Adding_An_App.md §7. -->
# Hand-off: what to tell the other AI

Paste everything inside the box into a fresh chat. Replace `<id>`, `<name>` and
`<what the app does>` — nothing else needs editing.

```text
You are building ONE app inside the Archx AI Lab repository at
github.com/archnemix/Archx-Agent: <id> (working title "<name>"). <what the app does>

SCOPE
  Work only inside apps/<id>/. You may add exactly one line outside it: the
  workspace member entry in the root Cargo.toml. Do not edit src/*.rs (the
  launcher), apps/archx-agent/** (another team's app), or shared/** (the shared
  crate). If you think you need to, stop and say why.

READ FIRST, IN THIS ORDER
  1. apps/archx-agent/docs/Plan/Adding_An_App.md
       - the contract: manifest fields, crate layout, the view signature,
         the build-time tests, and the seven rules every app obeys.
  2. apps/archx-agent/docs/Thinking.md
       - why the shared layers exist: persistence, key rotation, diagnostics.
         Do not re-invent any of them.

YOUR FOLDER ALREADY EXISTS
  apps/<id>/app.toml   ready = false   <- KEEP IT false until you are finished
  apps/<id>/docs/      your docs go here, nowhere else

  ready = false means the launcher does not register your app at all: no tile, no
  rail entry, no build. That is deliberate. It is how two to five apps are built
  at the same time without disturbing a launcher that already works. When you are
  done you flip one flag, and the app appears.

BUILD RULES
  * Cargo: crate name archx-<id>, lib name archx_<id>, edition 2024,
    depends on archx-shared (path = "../../shared") and iced 0.14.
    Workspace registration is one added entry in the root [workspace] members:
    "apps/<id>". Add it, never reorder the list.
  * Export `pub fn view(app: &App) -> Element<'_, Message>` from
    apps/<id>/src/home.rs and declare `view = "home::view"` in app.toml.
  * Import shared behaviour; never copy it. storage, credentials, provider_api,
    diagnostics, style, persist, model_meta and apps all live in archx_shared.
  * Never put a secret in a file, a log or a URL. Keys go through
    archx_shared::credentials into the OS vault.
  * Persist through archx_shared::storage::save and read with storage::load_body.
    save() adds the versioned envelope for you; do not write one yourself.
  * Tests that touch storage get their own directory with
    storage::set_thread_directory (thread-local). Do not set ARCHX_CONFIG_DIR.

HOW YOU KNOW YOU ARE DONE
  1. Push your branch and read the CI result. Run "App harness" with app = <id>:
     it builds and tests your app on its own, without touching the release. Rust
     may not be installed where you work; never claim a test you did not see pass.
  2. The harness renders it, it opens, and it returns to Discover with its Back
     button.
  3. Only then, in app.toml: ready = true and status = "live".

  ready = true does NOT publish the app by itself. Publishing is the launcher
  owner's one-line release switch (`src/main.rs::release()`). Until they add it,
  your app is HELD — which is correct, visible in launcher settings, and exactly
  how several apps get built at once. Never add that line yourself.

IF YOU NEED THE LAUNCHER CHANGED
  Do not edit it. Write apps/<id>/docs/Launcher_Request.md (template in
  Adding_An_App.md §8) with what/why/design-fit, and report it. The launcher
  owner applies it once, in the shared launcher, never in a forked one.

REPORT BACK WITH
  * the files you created;
  * the CI run URL that passed;
  * anything you had to change outside apps/<id>/ (there should be exactly one
    line, and if there is more, say why).
```

## Working in parallel with another app

Everything above still holds. Two extra rules keep the work streams apart:

* one app folder per branch — never two apps in one pull request;
* the only shared files are the root `Cargo.toml` members list (add one line,
  never reorder) and `Adding_An_App.md` itself (ask before editing it).

Because `ready = false` is the default for a new folder, a half-built app is
invisible to the launcher and to everybody else's tests. The first moment the
launcher changes is the moment an app is finished — which is the point.
