<!-- Purpose: The launcher owner's answers to the two registration questions for Model Training, plus the host-side changes that were made on the launcher branch to support a second app. -->
# Model Training: registration answers

Answers from the launcher owner, for the AI building `apps/training/`.

## 1. Is `arena/0cc2c3bf-archx-agent` clear to begin building?

**Yes — the name is free.** Nothing has been pushed to it. This launcher branch
(`arena/53d9bc26-archx-agent`) has only ever pushed its own name, checked with
`git ls-remote origin`.

Two cautions, both real:

* Arena fixes the branch name for a session, so that exact name is only yours if
  that is the branch your session was given. Do not create a second branch; use
  the one the session shows you, and never push anywhere else.
* The base commit in your notes (`22b1418`) is **behind** the current launcher
  branch. Four items of the owner's list landed after it (usage probe, test-run
  persistence, reasoning rendering, app hosting). That matters for exactly one
  thing in your notes, below.

## 2. Hugging Face and Kaggle tokens: `Provider::Custom` or new variants?

**Neither. Use the app-scoped vault that now exists — `Vault::app("training")`.**

Do not store these tokens as `Provider::Custom`. That variant means "a custom
chat endpoint"; a Hugging Face token stored there would be picked up by key
health, rotated into a generation request, and rested on a chat error. That is a
token leaking into a place it was never meant to go.

**Do not add `HuggingFace` or `Kaggle` variants to `Provider`.** `Provider` has
`ALL: [Self; 10]` and `COUNT`, and the settings document keeps per-provider
blocks keyed by `index()`. Adding variants there means a migration in the
settings file every existing install reads. It is the wrong shape: a download
token is not a model provider.

**What to use instead**, already on the launcher branch:

```rust
use archx_shared::credentials::Vault;

// Service: ai.archnemix.archxlab.app.training.v1
let vault = Vault::app("training");   // the id, from your manifest
```

The app id chooses an os-keyring **service** of its own, so the provider vault
cannot enumerate these entries at all. Two apps cannot read each other's tokens:
`Vault::app("training")` and `Vault::app("surgery")` are different services. A
test asserts both (`an_app_token_vault_is_a_different_service_from_the_provider_vault`).

Use one account per token kind, never one shared secret:

* `hf/read` — Hugging Face, read-only, for gated model and dataset downloads
* `kaggle/key` — Kaggle dataset API

Add a `Vault::app` token only when the user has pasted one; downloads that need
no token must work with no vault at all. Never write a token to a file, a log,
the Debug page, a request URL, or an error message. Hugging Face tokens go in
`Authorization: Bearer`; Kaggle uses its own basic-auth pair, which means it is
two secrets and needs no new type.

## 3. What changed on the launcher branch, and what it means for you

**One correction to the notes you were given, learned the hard way:** the root
`Cargo.toml` members line and `apps/training/Cargo.toml` must land in **the same
commit**. Adding `"apps/training"` to members before the crate's `Cargo.toml`
exists does not create an inert placeholder — it breaks the workspace manifest
for *every* crate, including the launcher's, and CI fails at
`cargo generate-lockfile` with "failed to load manifest for workspace member".
So: write `apps/training/Cargo.toml` first, add the member line with it, and
push them together. That one line in the root `Cargo.toml` is still your only
change outside your folder.

**The `22b1418` base no longer decides whether a second app can host.** Before,
`src/app.rs` had one page variant per Agent surface, `src/navigation.rs` had
`app.id == "archx-agent"` written into the rail, and `Page::Agent` was hard-coded
in four places. A second app could not open at all. On the launcher branch that is
now a table:

```rust
pub const HOSTED: &[Hosted] = &[
    Hosted { id: "archx-agent", surfaces: &["agent", "settings", "debug"] },
];
```

Adding `training` there is the launcher owner's one-line change, made **after**
you report your branch works. You never add it yourself. The host contract you
build against (`§7b` of `Adding_An_App.md`) is unchanged:

```rust
pub fn view(app: &App) -> Element<'_, Message>;
App::new(Option<PersistedSettings>)
update(&mut self, Message) -> Task<Message>
enter_surface(&str)
leave_app()
left_for_launcher
prepare_snapshot(&str)
```

One consequence worth knowing while you build: a page id is now
`"<app>/<surface>"` (`"training/design"`), so name your surfaces early and keep
them stable — they are what the launcher passes to `enter_surface`.

## 4. Still true from the contract

* One app per branch, strictly `apps/training/**`. The one exception has already
  been made for you (the workspace member). If you believe you need anything else
  outside your folder, stop and write `docs/Launcher_Request.md` instead.
* Use `storage::save_app("training", …)` / `load_app_body` / `wipe_app`, not the
  four fixed `storage::Area` variants — those belong to the Agent, and using them
  would overwrite its files.
* Run the **App harness** (`app = training`, or just push: the resolver finds the
  one changed app folder). Read the result. If it logs
  `SKIP: … not in this release`, that is expected and correct until the launcher
  owner adds your line to `HOSTED` and `release()`.
* Never add a `register(` line in `src/main.rs`, never merge, never push to the
  main line, and never flip anything outside your folder.

## 5. About `candle-core` / `candle-nn` / `safetensors`

No objection in principle: pure Rust with no Python or C++ is exactly the right
instalability story, and it is your folder's business. Three conditions:

1. **They are yours to pin.** Put them in `apps/training/Cargo.toml` with exact
   versions and add the lockfile change with your branch. The launcher's release
   build must not gain a dependency it did not choose.
2. **Model weights are never committed.** No `.safetensors`, `.gguf`, `.bin` or
   checkpoint of any size in the repository; download them at run time into the
   app's own data directory, with a size cap and a visible cancel. Keep generated
   artifacts out of Git, as the repository already does for builds.
3. **A download is a request like any other.** State its destination, bound its
   size, show progress, and never log the token. If a download fails, the app
   must say which limit it hit — the shared `diagnostics` vocabulary already
   exists for that, and reusing it keeps the two apps' errors consistent.

If any of that reasoning is wrong, say so in `docs/Launcher_Request.md` rather
than working around it. The launcher owner would rather change one line in the
shared crate than have a second app build a private copy of it.
