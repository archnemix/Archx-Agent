<!-- Purpose: The paste-ready hand-off for a second AI building one of the other apps. Lives beside the contract it references: Plan/Adding_An_App.md §7. Kept inside this app's docs on purpose, so the launcher owner's docs and each app author's docs never mix. -->
# Hand-off: what to tell the other AI

Paste everything inside the box into a fresh chat. Replace `<id>`, `<name>` and
`<what the app does>` — nothing else needs editing.

```text
You are building ONE app inside the Archx AI Lab repository at
github.com/archnemix/Archx-Agent: <id> (working title "<name>"). <what the app does>

YOUR BRANCH
  Work on ONE branch of your own, never on the main line. If your tool fixes the
  branch name (Arena does: arena/<uuid>-archx-agent), that branch IS your
  workspace — keep it, do not rename it, do not make a second one. Otherwise:

      git clone https://github.com/archnemix/Archx-Agent && cd Archx-Agent
      git checkout -b app/<id>-<your-name> origin/<base-branch-the-user-gave-you>
      git push -u origin app/<id>-<your-name>

  Push only your own branch.
  Never push to the main branch, never force-push, never merge the main line into
  yours. Do not open a pull request into the main line: the user confirms your
  app works, and only then does the launcher owner import your branch. One app
  per branch - two apps in one branch cannot be imported in one piece.

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
  1. Push your branch and read the CI result. Run "App harness" (app = <id>) on
     your branch: it builds and tests your app on its own, without touching the
     release, and writes the log back to your branch. Rust may not be installed
     where you work; never claim a test you did not see pass.
  2. If that job logs "SKIP: ... not in this release", that is expected for a
     brand-new app: the launcher hosts apps in-process, so it can only draw a
     crate it already links, and only the launcher owner adds that link. Your
     crate building and its tests passing are the evidence until then. If you
     want a picture, ship your own snapshot runner inside apps/<id>/.
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
  * your branch name and the CI run URL that passed;
  * the files you created;
  * anything you had to change outside apps/<id>/ (there should be exactly one
    line, and if there is more, say why);
  * any Launcher_Request.md you wrote.
  Then stop. Do not merge, and do not add the release line.
```

## Working in parallel with another app

Everything above still holds. Two extra rules keep the work streams apart:

* one app folder per branch — never two apps in one pull request;
* the only shared files are the root `Cargo.toml` members list (add one line,
  never reorder) and `Adding_An_App.md` itself (ask before editing it).

Because `ready = false` is the default for a new folder, a half-built app is
invisible to the launcher and to everybody else's tests. The first moment the
launcher changes is the moment an app is finished — which is the point.

## What the user does with that branch

The user stays the one who decides. The sequence is the same every time, and it is
written out in full in `Adding_An_App.md` §7 ("Starting a branch, and how it comes
back here"). In short:

1. **The other AI branches and pushes only its branch.** Nothing lands anywhere
   else, so the launcher cannot break while it works.
2. **The user checks the diff** — every path under `apps/<id>/`, plus at most one
   line in the root `Cargo.toml` members list.
3. **The user confirms the app works.** `git worktree add /tmp/<id>` on that
   branch, then `cargo test -p <id>`.
4. **The import is a merge**, `git merge --no-ff origin/app/<id>-<your-name>`.
   Import is not publishing: the app arrives `Held`, with no tile.
5. **The launcher owner adds hosting and the release line**, checks the design
   against the Lab's scheme, and runs the full `GUI review`. That is the moment
   the app is published — and deleting one `register` line holds it back again.

Nothing in this flow lets an app author edit the real launcher; they only ever
hold a copy for their own button, and the real one is added here, after the brand
and design check.
