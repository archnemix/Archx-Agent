<!-- Purpose: Defines the repository's working, documentation, implementation, and testing rules. -->
# Working rules

Read this file before each implementation change. If a requirement is unclear, ask the user rather than assume an answer. Keep work civil, clear, and efficient. Protect quality even if the user later requests a rushed batch of features: explain the specific quality or testing risk, refuse to skip necessary work, and propose a smaller complete step. Do not over-test, over-engineer, or spend disproportionate time on low-risk details.

## Repository structure

- Prefer readability, clear names, and a clear separation of responsibilities over cleverness.
- A file should contain only content related to its named purpose; keep files manageable in size and split by responsibility, not arbitrarily.
- Each folder should contain only relevant material and have a short README explaining its purpose.
- Start each Markdown or source file with a concise purpose comment, including otherwise-empty files. For strict JSON, which cannot contain comments, use a first `_description` field instead. Respect formats that prohibit comments.
- Keep internal support material in `internels/`; add a skill at `internels/skills/<name>.md` only when useful.
- Do not create unrelated files or proceed to the next roadmap step until the current feature or bug is complete and tested, except where two pieces must be developed together.

## Planning and records

- `Docs/Plan/Architecture.md`: agreed product scope, features, and architecture; establish it with the user before deriving the initial roadmap.
- `Docs/Roadmap.md`: ordered, fully completable implementation steps; update when approved scope changes.
- `Docs/Change.md`: new user-requested ideas or scope changes and their roadmap implications.
- `Docs/Changelog.md`: concise features added, changed, removed, or replaced by release; do not invent versions.
- `Docs/Thinking.md`: update after each round of work with concise decisions, rationale, problems, and resolutions; record useful conclusions rather than private internal reasoning.
- `Docs/Technical.md`: stack, component/file responsibilities, interfaces, inputs, and outputs. Keep it consistent with `Docs/Files_Info.json`.
- `Docs/Files_Info.json`: maintain a navigable inventory of files, their purposes, inputs, outputs, and responsibilities whenever files change.
- `Docs/Logic.md`: maintain user-action-to-component/function call flows, with file paths, inputs, outputs, and important failure paths as they become implemented. Keep it synchronized with code so failures can be traced without reading the whole repository.
- `Docs/Workaround.md`: record necessary workarounds, constraints, and how to use them.
- `Docs/Secrets.md`: record only exact secret *names* and descriptions of user-configured GitHub secrets; never store values.
- `Docs/Research.json`: keyed summaries and exact source URLs of research performed; do not invent research.

## Implementation

- Before writing code for a file, list the libraries, APIs, and other dependencies it will use, check current authoritative online documentation for their versions and usage, and record the findings in `Docs/Research.json`. If access is unavailable, explain the blocker rather than guessing. Update relevant documentation as implementation changes.
- Write clean, modular code. Avoid boilerplate comments and needless cross-file coupling; comment only where it clarifies something non-obvious, apart from the required file-purpose comment.
- Ask about ambiguous product behavior or requirements; measure or test competing implementation claims where appropriate.

## Tests and evidence

- Test important behavior without redundant tests. Run a file's focused unit tests when it is created or modified; do not rerun unchanged files' unit tests solely for repetition.
- Run relevant integration tests when connected system components are added, removed, or modified.
- Run every applicable test on GitHub's Linux, Windows, and macOS runners for compatibility. Do not claim cross-platform success until the runner results exist.
- Record the exact test command, inputs, and outputs in a clearly organized, versioned test-results directory. Retain results for the current and two preceding versions only. Never commit credentials or sensitive test output.
- Documentation-only changes need documentation/format validation, not fabricated code tests.

## GitHub Actions workaround

- For jobs that need more resources or access than the sandbox offers, use a narrowly scoped workflow triggered by a deliberate tracked-file change. Keep workflow inputs and outputs organized.
- Write needed logs and generated results into appropriate tracked repository directories rather than relying on Actions artifacts. Guard against recursive workflow triggers from result commits, and avoid storing secrets in logs or outputs.
- Use at most five concurrent runners across matrices and workflows. Prefer the local environment for small tasks; use Actions for heavier work or access requiring user-configured GitHub secrets.
- Document workflow details in `Docs/Workaround.md` when a workflow is actually needed. Ask the user to configure needed secret names, document those names in `Docs/Secrets.md`, and never request or write secret values.
