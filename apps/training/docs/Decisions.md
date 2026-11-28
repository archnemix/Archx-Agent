<!-- Purpose: Records key engineering decisions, trade-offs, and verified library behaviors for Model Training. -->
# Model Training — Engineering Decisions

## 1. Pure-Rust Engine (`candle` 0.11.1 + Pure-Rust `tokenizers` 0.23.1)

- **Decision:** Build the in-app training engine on `candle-core = "0.11.1"`, `candle-nn = "0.11.1"`, `safetensors = "0.8"`, and `tokenizers = { version = "0.23.1", default-features = false, features = ["fancy-regex"] }`.
- **Rationale:** Avoids Python, `libtorch`, and C/C++ native build dependencies (`candle` 0.11.1 switched `tokenizers` away from C `onig`, and disabling `tokenizers` default features omits `esaxx-rs/cpp`), ensuring clean single-binary builds on Linux, Windows, and macOS runners.

## 2. Explicit Deterministic PRNG (`SplitMix64`) Over `Device::Cpu.set_seed`

- **Finding:** Inspecting `candle-core/src/cpu_backend/mod.rs` showed `CpuDevice::set_seed` explicitly returns an error (`"cannot seed the CPU rng with set_seed"`).
- **Decision:** Implement `src/rng.rs` (`SplitMix64` + Box-Muller normal / Xavier / Kaiming / $1/\sqrt{2L}$ residual scaling) to populate `candle_nn::VarMap` tensors, batch shuffles, MoE router jitter, and generation sampling deterministically across all three OSes.

## 3. Zero-Overhead Neural Live View Sampling

- **Decision:** Gate neural tensor extraction behind an `AtomicU8` (`TelemetryMode::Off` by default).
- **Rationale:** Reading full weight and gradient tensors every step would copy megabytes off the hot path. With `Off` as default, training pays zero telemetry cost; when switched to `Every25` or `Every10`, only compact summary scalars and downsampled $16\times16$ tiles are sent to the UI.

## 4. `Task::sip` Streaming Without Launcher Clock Coupling

- **Decision:** Drive both training step updates and Playground token streaming through `iced::task::sipper` (`Task::sip(...).abortable()`), aborting active handles in `App::leave_app()`.
- **Rationale:** Matches `Archx Agent`'s async model without requiring a repeating timer subscription from the shared launcher.

## 5. Font-Free Inline SVG Vector Plots

- **Decision:** Render loss curves, LR schedules, $16\times16$ heatmaps, and MoE histograms as pure geometric SVG primitives (`<rect>`, `<line>`, `<polyline>`) via `svg::Handle::from_memory`, keeping all axis and legend text as native Iced `text(...)` widgets.
- **Rationale:** Gives crisp vector graphics using the workspace's existing `svg` feature while avoiding headless runner font-lookup differences inside `resvg` `<text>` nodes and respecting the macOS Manrope Normal-weight rule in `archx_shared::style`.
