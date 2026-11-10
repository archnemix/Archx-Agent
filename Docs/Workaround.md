<!-- Purpose: Records necessary tooling and access workarounds without creating unused workflows. -->
# Workarounds

## GitHub Actions for constrained environments

When local resources or network access are insufficient, use a deliberately triggered workflow with scoped paths. Store required logs and outputs in organized repository directories, not only as Actions artifacts; avoid recursive triggers when committing results. Cap concurrent runners at five. For tests, use Linux, Windows, and macOS runners, recording commands, inputs, and outputs by version, retaining only the current and two previous versions. Never write credentials into the repository or logs. Create the workflow only when a concrete job requires it; document its trigger and output locations here at that time.

## Native GUI builds without a local Rust toolchain

The current sandbox has no `rustc` or `cargo`. `.github/workflows/gui.yml` deliberately triggers on source/config changes or edits to `internels/ci-trigger.txt`. It runs Linux, Windows, and macOS sequentially (no more than one runner concurrently), commits build/test logs and running-app screenshots to `Docs/Test_Results/Unreleased/`, and places the Windows portable executable at `deliverables/Unreleased/windows/archx-ai-lab.exe`. Generated-result commits do not match the workflow's trigger paths. The user chose repository-hosted binaries; monitor repository size and retain only the current plus two previous versions. The CI results must be checked before claiming a successful build or visual match. Snapshot mode is opt-in via `ARCHX_SNAPSHOT=<path>`.
