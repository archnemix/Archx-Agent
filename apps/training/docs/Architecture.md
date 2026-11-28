<!-- Purpose: Defines the composable architecture, module boundaries, optimizations, and Slice 1 specification of Model Training. -->
# Model Training — Architecture

## 1. Product Boundary

- **`Model Training` (`apps/training/`):** Creating and training brand-new models from scratch directly inside the native Rust desktop app (dataset import, tokenizer/codec construction, architecture & seed configuration, autograd training with live telemetry & optional neural inspection, `.safetensors` checkpointing, and instant post-training live chat/generation).
- **Zero external runtime:** All tensor math, reverse-mode autograd, optimizers, tokenization, and checkpoint serialization execute in pure Rust (`candle-core`, `candle-nn`, `safetensors`, `tokenizers`) inside the compiled binary.

## 2. Four Composable Model Axes

Model architecture is structured across four orthogonal axes so vertical slices extend cleanly without UI redesign:

1. **Modality:** `Text` *(Slice 1 live)* · `Image` · `Audio` · `Multimodal` · `OCR`
2. **Mechanism:** `Autoregressive` *(Slice 1 live)* · `DiscreteDiffusion` · `ContinuousDiffusion` · `FlowMatching` · `Seq2Seq`
3. **Backbone:** `Transformer` *(Slice 1 live)* · `Mamba` · `Jamba` · `Rwkv` · `DiT` · `UNet` · `Hypernetwork`
4. **Routing:** `Dense` *(Slice 1 live)* · `MoE` (Top-$k$ Mixture-of-Experts with optional shared experts — *Slice 1 live*)

## 3. Module Map (`apps/training/src/`)

| File | Responsibility |
| --- | --- |
| `lib.rs` | Public crate root exporting `app`, `home`, and training pipeline modules |
| `rng.rs` | Cross-platform deterministic `SplitMix64` PRNG, normal/Xavier/Kaiming initializers, seeded shuffles, and top-$k$/top-$p$ token sampling |
| `config.rs` | `RunConfig`, `DatasetConfig`, `TokenizerConfig`, `TransformerConfig`, `MoEConfig`, `Hyperparams`, presets (`Nano`..`Base`), and exact `ModelSpecEstimate` (total/active params, RAM breakdown, FLOPs/step) |
| `dataset.rs` | Built-in offline corpora, local `TXT`/`JSONL`/`CSV`/folder loaders, async Hugging Face Hub / Kaggle / HTTPS dataset importers (using OS `Vault` when authenticated), deduplication, length filters, and seeded train/val/test splits |
| `tokenizer.rs` | Native Rust `ByteLevelBpe`, `WordPiece`, `Unigram`, and `CharLevel` trainers + Hugging Face `tokenizer.json` import/export, chat-turn formatting, sequence packing, and live tokenization preview |
| `transformer.rs` | Pure-Rust `candle` Autoregressive Transformer supporting `MHA`/`GQA`/`MQA`, `RoPE`/learned/sinusoidal positions, `RMSNorm`/`LayerNorm`, `QK-Norm`, sliding window, `SwiGLU`/`GeGLU`/`GELU`/`SiLU`/`ReLU²` Dense FFNs, Top-$k$ `SparseMoE` with shared experts and load-balance/z-loss, `.safetensors` I/O, and streaming token generation |
| `optim.rs` | Native Rust `AdamW`, `Muon` (Newton–Schulz orthogonalized 2D updates + `AdamW` 1D/embeddings), `Lion`, and `SGD+Nesterov`, plus global gradient $L_2$ clipping and warmup + `Cosine`/`WSD`/`Linear`/`InvSqrt`/`Constant` LR schedules |
| `telemetry.rs` | Atomic-gated neural telemetry (`Off` = 0% hot-path overhead, `Every25`, `Every10`, `SnapshotNow`) capturing per-layer weight/grad norms, dead-unit %, $16\times16$ heatmaps, and MoE router utilization |
| `charts.rs` | Pure-Rust vector SVG generators (`iced::widget::svg::Handle`) for loss/val curves, LR/grad-norm sparklines, $16\times16$ heatmaps, MoE load histograms, and architecture block diagrams |
| `trainer.rs` | Background worker bridged via `iced::task::sipper` with configurable Rayon thread count, pause/resume/stop/save-now flags, gradient accumulation, NaN rollback guard, and `.safetensors` checkpoint management |
| `app.rs` | §7b host state machine, async task orchestration, app-scoped persistence (`storage::save_app("training", ...)`), and snapshot fixtures |
| `home.rs` | Single manifest-declared entry `pub fn view(app: &App) -> Element<'_, Message>` |
| `views.rs` | Native Iced surfaces matching `Archx Agent` chrome: 260px rail, `Pipeline` (4 stages + pinned right Live Spec Card + collapsible Expert drawers), `Neural live view`, `Playground` (streaming chat + Checkpoint A/B compare), `Settings`, and `Run journal` |
