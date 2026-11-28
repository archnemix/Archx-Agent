<!-- Purpose: Ordered vertical-slice roadmap for Model Training inside Archx AI Lab. -->
# Model Training — Roadmap

Each slice is completed end-to-end (data, preprocessing, model graph, optimizer, live telemetry, `.safetensors` checkpoints, Playground inference, and CI tests) before starting the next slice.

## Slice 1 — Text Generation · Autoregressive Transformer (`Dense` & `MoE`) *(Current)*

- Dataset Hub: Built-in offline corpora, local `TXT`/`JSONL`/`CSV`/directory import, Hugging Face Hub / Kaggle / HTTPS fetchers, deterministic split & deduplication.
- Native Rust Tokenizer: `ByteLevelBpe`, `WordPiece`, `Unigram`, and `CharLevel` training + Hugging Face `tokenizer.json` import/export, sequence packing, and live token preview.
- Configurable Seeded Transformer: `MHA`/`GQA`/`MQA`, `RoPE`/learned/sinusoidal positions, `RMSNorm`/`LayerNorm`, `QK-Norm`, sliding window, `SwiGLU`/`GeGLU`/`GELU`/`SiLU`/`ReLU²` Dense FFN, and Top-$k$ `SparseMoE` (with shared experts + load-balance & z-loss).
- Optimizers & Schedules: `AdamW`, `Muon`, `Lion`, `SGD+Nesterov`, grad clipping, warmup + `Cosine`/`WSD`/`Linear`/`InvSqrt`/`Constant`.
- Visuals & Playground: Live Spec Card, SVG loss/LR/grad charts, atomic-gated Neural Live View ($16\times16$ heatmaps + layer norms + MoE load histogram), streaming Playground chat + Checkpoint A/B comparison, and app-scoped persistence.

## Slice 2 — Text Generation · State-Space & Hybrid Backbones (`Mamba`, `Jamba`, `RWKV`)

- Selective SSM (`Mamba`) blocks, custom interleaved `Jamba` (`Mamba + Attention + MoE`) block patterns, linear-attention `RWKV`, and selective $\Delta$-gate live telemetry.

## Slice 3 — Text Generation · Discrete Masked Diffusion

- Masked-token diffusion forward corruption schedules, bidirectional Diffusion Transformer (`DiT` text), per-timestep loss buckets, and live iterative token-unmasking Playground view.

## Slice 4 — Vision & Image Generation (`Continuous Diffusion`, `Flow Matching`, `DiT` & `UNet`)

- 2D image patchifier & folder/caption dataset loader, DDPM/DDIM & Rectified Flow objectives, timestep-conditioned `DiT` and `UNet` backbones, and live denoising strip preview.

## Slice 5 — Audio, Multimodal, OCR & Hypernetworks

- Audio mel-frame codec, Vision/Audio-to-Text multimodal projector & OCR `Seq2Seq` encoder-decoder, and conditioning `Hypernetwork` weight generator.
