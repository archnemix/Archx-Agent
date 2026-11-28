//! Purpose: Defines the composable model taxonomy, Slice 1 Transformer/MoE hyperparameters, presets, and live RAM/FLOPs estimators.

use serde::{Deserialize, Serialize};

/// Axis A: Input/output modality. Slice 1 implements `Text` end-to-end.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Modality {
    Text,
    Image,
    Audio,
    Multimodal,
    Ocr,
}

impl Modality {
    pub const ALL: [Self; 5] = [Self::Text, Self::Image, Self::Audio, Self::Multimodal, Self::Ocr];

    pub fn label(self) -> &'static str {
        match self {
            Self::Text => "Text · Language",
            Self::Image => "Image · Vision",
            Self::Audio => "Audio · Speech",
            Self::Multimodal => "Multimodal",
            Self::Ocr => "OCR · Document",
        }
    }

    pub fn is_live_in_slice(self) -> bool {
        matches!(self, Self::Text)
    }
}

/// Axis B: Generative training objective. Slice 1 implements `Autoregressive`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Mechanism {
    Autoregressive,
    DiscreteDiffusion,
    ContinuousDiffusion,
    FlowMatching,
    Seq2Seq,
}

impl Mechanism {
    pub const ALL: [Self; 5] = [
        Self::Autoregressive,
        Self::DiscreteDiffusion,
        Self::ContinuousDiffusion,
        Self::FlowMatching,
        Self::Seq2Seq,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Autoregressive => "Autoregressive (Causal)",
            Self::DiscreteDiffusion => "Discrete Diffusion (Masked)",
            Self::ContinuousDiffusion => "Continuous Diffusion",
            Self::FlowMatching => "Flow Matching",
            Self::Seq2Seq => "Seq2Seq",
        }
    }

    pub fn is_live_in_slice(self) -> bool {
        matches!(self, Self::Autoregressive)
    }
}

/// Axis C: Sequence/spatial backbone. Slice 1 implements `Transformer`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Backbone {
    Transformer,
    Mamba,
    Jamba,
    Rwkv,
    DiT,
    UNet,
    Hypernetwork,
}

impl Backbone {
    pub const ALL: [Self; 7] = [
        Self::Transformer,
        Self::Mamba,
        Self::Jamba,
        Self::Rwkv,
        Self::DiT,
        Self::UNet,
        Self::Hypernetwork,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Transformer => "Transformer",
            Self::Mamba => "Mamba (SSM)",
            Self::Jamba => "Jamba (Hybrid)",
            Self::Rwkv => "RWKV",
            Self::DiT => "DiT",
            Self::UNet => "UNet",
            Self::Hypernetwork => "Hypernetwork",
        }
    }

    pub fn is_live_in_slice(self) -> bool {
        matches!(self, Self::Transformer)
    }
}

/// Axis D: Feed-forward routing (`Dense` and `MoE` are both live in Slice 1).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Routing {
    Dense,
    MoE,
}

impl Routing {
    pub const ALL: [Self; 2] = [Self::Dense, Self::MoE];

    pub fn label(self) -> &'static str {
        match self {
            Self::Dense => "Dense FFN",
            Self::MoE => "Mixture-of-Experts (MoE)",
        }
    }
}

/// Quick size presets so users can start immediately or customize every field.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Preset {
    Nano,
    Micro,
    Small,
    Base,
    Custom,
}

impl Preset {
    pub const ALL: [Self; 5] = [Self::Nano, Self::Micro, Self::Small, Self::Base, Self::Custom];

    pub fn label(self) -> &'static str {
        match self {
            Self::Nano => "Nano · instant CPU",
            Self::Micro => "Micro · ~2M",
            Self::Small => "Small · ~15M",
            Self::Base => "Base · ~45M",
            Self::Custom => "Custom",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum DatasetSource {
    BuiltinTinyDialogues,
    BuiltinRustCode,
    BuiltinLogicQa,
    BuiltinClassicVerse,
    LocalPath,
    HuggingFaceHub,
    KaggleDataset,
    CustomUrl,
}

impl DatasetSource {
    pub const ALL: [Self; 8] = [
        Self::BuiltinTinyDialogues,
        Self::BuiltinRustCode,
        Self::BuiltinLogicQa,
        Self::BuiltinClassicVerse,
        Self::LocalPath,
        Self::HuggingFaceHub,
        Self::KaggleDataset,
        Self::CustomUrl,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::BuiltinTinyDialogues => "Built-in · Tiny Dialogues & Stories",
            Self::BuiltinRustCode => "Built-in · Rust & Algorithms",
            Self::BuiltinLogicQa => "Built-in · Science & Logic Q&A",
            Self::BuiltinClassicVerse => "Built-in · Classic Verse",
            Self::LocalPath => "Local File or Folder",
            Self::HuggingFaceHub => "Hugging Face Hub",
            Self::KaggleDataset => "Kaggle Dataset",
            Self::CustomUrl => "Custom HTTPS URL",
        }
    }

    pub fn is_builtin(self) -> bool {
        matches!(
            self,
            Self::BuiltinTinyDialogues
                | Self::BuiltinRustCode
                | Self::BuiltinLogicQa
                | Self::BuiltinClassicVerse
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DatasetConfig {
    pub source: DatasetSource,
    pub local_path: String,
    pub hf_repo: String,
    pub hf_split: String,
    pub hf_config: String,
    pub kaggle_slug: String,
    pub kaggle_file: String,
    pub custom_url: String,
    pub text_field: String,
    pub prompt_field: String,
    pub response_field: String,
    pub max_remote_rows: usize,
    pub deduplicate: bool,
    pub min_chars: usize,
    pub max_chars: usize,
    pub train_pct: u8,
    pub val_pct: u8,
    pub shuffle_seed: u64,
}

impl Default for DatasetConfig {
    fn default() -> Self {
        Self {
            source: DatasetSource::BuiltinTinyDialogues,
            local_path: String::new(),
            hf_repo: "roneneldan/TinyStories".to_owned(),
            hf_split: "train".to_owned(),
            hf_config: "default".to_owned(),
            kaggle_slug: String::new(),
            kaggle_file: "train.jsonl".to_owned(),
            custom_url: String::new(),
            text_field: "text".to_owned(),
            prompt_field: "prompt".to_owned(),
            response_field: "response".to_owned(),
            max_remote_rows: 500,
            deduplicate: true,
            min_chars: 8,
            max_chars: 8192,
            train_pct: 90,
            val_pct: 10,
            shuffle_seed: 42,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TokenizerKind {
    ByteLevelBpe,
    WordPiece,
    Unigram,
    CharLevel,
    PretrainedFile,
}

impl TokenizerKind {
    pub const ALL: [Self; 5] = [
        Self::ByteLevelBpe,
        Self::WordPiece,
        Self::Unigram,
        Self::CharLevel,
        Self::PretrainedFile,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::ByteLevelBpe => "Byte-Level BPE",
            Self::WordPiece => "WordPiece",
            Self::Unigram => "Unigram",
            Self::CharLevel => "Character-Level",
            Self::PretrainedFile => "Load tokenizer.json",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TokenizerConfig {
    pub kind: TokenizerKind,
    pub vocab_size: usize,
    pub min_frequency: usize,
    pub pretrained_path: String,
    pub sequence_packing: bool,
    pub add_bos_eos: bool,
    pub lowercase: bool,
}

impl Default for TokenizerConfig {
    fn default() -> Self {
        Self {
            kind: TokenizerKind::ByteLevelBpe,
            vocab_size: 512,
            min_frequency: 2,
            pretrained_path: String::new(),
            sequence_packing: true,
            add_bos_eos: true,
            lowercase: false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum NormKind {
    RmsNorm,
    LayerNorm,
}

impl NormKind {
    pub const ALL: [Self; 2] = [Self::RmsNorm, Self::LayerNorm];

    pub fn label(self) -> &'static str {
        match self {
            Self::RmsNorm => "RMSNorm",
            Self::LayerNorm => "LayerNorm",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ActivationKind {
    SwiGlu,
    GeGlu,
    Gelu,
    Silu,
    Relu2,
}

impl ActivationKind {
    pub const ALL: [Self; 5] = [Self::SwiGlu, Self::GeGlu, Self::Gelu, Self::Silu, Self::Relu2];

    pub fn label(self) -> &'static str {
        match self {
            Self::SwiGlu => "SwiGLU",
            Self::GeGlu => "GeGLU",
            Self::Gelu => "GELU",
            Self::Silu => "SiLU",
            Self::Relu2 => "ReLU²",
        }
    }

    pub fn is_gated(self) -> bool {
        matches!(self, Self::SwiGlu | Self::GeGlu)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PosEncoding {
    RoPE,
    Sinusoidal,
    Learned,
    None,
}

impl PosEncoding {
    pub const ALL: [Self; 4] = [Self::RoPE, Self::Sinusoidal, Self::Learned, Self::None];

    pub fn label(self) -> &'static str {
        match self {
            Self::RoPE => "RoPE (Rotary)",
            Self::Sinusoidal => "Sinusoidal",
            Self::Learned => "Learned Absolute",
            Self::None => "NoPos (Causal Mask)",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum InitDist {
    Normal,
    XavierUniform,
    KaimingNormal,
}

impl InitDist {
    pub const ALL: [Self; 3] = [Self::Normal, Self::XavierUniform, Self::KaimingNormal];

    pub fn label(self) -> &'static str {
        match self {
            Self::Normal => "Normal (σ)",
            Self::XavierUniform => "Xavier Uniform",
            Self::KaimingNormal => "Kaiming Normal",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MoEConfig {
    pub n_experts: usize,
    pub top_k: usize,
    pub n_shared_experts: usize,
    pub aux_loss_weight: f32,
    pub z_loss_weight: f32,
    pub router_jitter: f32,
}

impl Default for MoEConfig {
    fn default() -> Self {
        Self {
            n_experts: 4,
            top_k: 2,
            n_shared_experts: 1,
            aux_loss_weight: 0.02,
            z_loss_weight: 0.001,
            router_jitter: 0.01,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TransformerConfig {
    pub vocab_size: usize,
    pub seq_len: usize,
    pub n_layers: usize,
    pub d_model: usize,
    pub n_heads: usize,
    pub n_kv_heads: usize,
    pub d_ff: usize,
    pub norm: NormKind,
    pub norm_eps: f64,
    pub activation: ActivationKind,
    pub pos_encoding: PosEncoding,
    pub rope_theta: f32,
    pub qk_norm: bool,
    pub tie_embeddings: bool,
    pub use_bias: bool,
    pub dropout: f32,
    pub sliding_window: usize, // 0 = full causal context
    pub routing: Routing,
    pub moe: MoEConfig,
    pub init_dist: InitDist,
    pub init_std: f32,
    pub residual_scale: bool,
    pub init_seed: u64,
}

impl Default for TransformerConfig {
    fn default() -> Self {
        Self::from_preset(Preset::Nano, Routing::Dense)
    }
}

impl TransformerConfig {
    pub fn from_preset(preset: Preset, routing: Routing) -> Self {
        let (seq_len, n_layers, d_model, n_heads, n_kv_heads, d_ff) = match preset {
            Preset::Nano => (96, 3, 96, 4, 2, 256),
            Preset::Micro => (160, 4, 192, 6, 2, 512),
            Preset::Small => (256, 6, 384, 6, 2, 1024),
            Preset::Base | Preset::Custom => (512, 8, 512, 8, 4, 1536),
        };
        Self {
            vocab_size: 512,
            seq_len,
            n_layers,
            d_model,
            n_heads,
            n_kv_heads,
            d_ff,
            norm: NormKind::RmsNorm,
            norm_eps: 1e-5,
            activation: ActivationKind::SwiGlu,
            pos_encoding: PosEncoding::RoPE,
            rope_theta: 10_000.0,
            qk_norm: true,
            tie_embeddings: true,
            use_bias: false,
            dropout: 0.0,
            sliding_window: 0,
            routing,
            moe: MoEConfig::default(),
            init_dist: InitDist::Normal,
            init_std: 0.02,
            residual_scale: true,
            init_seed: 42,
        }
    }

    /// Normalizes invariants so invalid combinations (such as `d_model % n_heads != 0`
    /// or `n_heads % n_kv_heads != 0`) self-heal cleanly before tensor allocation.
    pub fn sanitized(&self) -> Self {
        let mut cfg = self.clone();
        cfg.vocab_size = cfg.vocab_size.clamp(16, 262_144);
        cfg.seq_len = cfg.seq_len.clamp(16, 8192);
        cfg.n_layers = cfg.n_layers.clamp(1, 64);
        cfg.n_heads = cfg.n_heads.clamp(1, 64);
        // Ensure d_model is a multiple of 2 * n_heads so RoPE pairs always align.
        let unit = (cfg.n_heads * 2).max(2);
        cfg.d_model = ((cfg.d_model.max(unit) + unit - 1) / unit) * unit;
        cfg.n_kv_heads = cfg.n_kv_heads.clamp(1, cfg.n_heads);
        while cfg.n_heads % cfg.n_kv_heads != 0 && cfg.n_kv_heads > 1 {
            cfg.n_kv_heads -= 1;
        }
        cfg.d_ff = cfg.d_ff.clamp(cfg.d_model, 32_768);
        cfg.moe.n_experts = cfg.moe.n_experts.clamp(2, 32);
        cfg.moe.top_k = cfg.moe.top_k.clamp(1, cfg.moe.n_experts);
        cfg.moe.n_shared_experts = cfg.moe.n_shared_experts.min(4);
        cfg.dropout = cfg.dropout.clamp(0.0, 0.5);
        cfg.init_std = cfg.init_std.clamp(0.001, 0.25);
        cfg
    }

    pub fn head_dim(&self) -> usize {
        self.d_model / self.n_heads.max(1)
    }

    pub fn attention_mode_label(&self) -> &'static str {
        if self.n_kv_heads == self.n_heads {
            "MHA"
        } else if self.n_kv_heads == 1 {
            "MQA"
        } else {
            "GQA"
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OptimizerKind {
    AdamW,
    Muon,
    Lion,
    SgdNesterov,
}

impl OptimizerKind {
    pub const ALL: [Self; 4] = [Self::AdamW, Self::Muon, Self::Lion, Self::SgdNesterov];

    pub fn label(self) -> &'static str {
        match self {
            Self::AdamW => "AdamW",
            Self::Muon => "Muon + AdamW",
            Self::Lion => "Lion (Low RAM)",
            Self::SgdNesterov => "SGD + Nesterov",
        }
    }

    /// Approximate extra floats stored per parameter for optimizer state.
    pub fn state_floats_per_param(self) -> f64 {
        match self {
            Self::AdamW => 2.0,
            Self::Muon => 1.25,
            Self::Lion => 1.0,
            Self::SgdNesterov => 1.0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LrSchedule {
    Cosine,
    Wsd,
    Linear,
    InvSqrt,
    Constant,
}

impl LrSchedule {
    pub const ALL: [Self; 5] = [Self::Cosine, Self::Wsd, Self::Linear, Self::InvSqrt, Self::Constant];

    pub fn label(self) -> &'static str {
        match self {
            Self::Cosine => "Warmup + Cosine",
            Self::Wsd => "Warmup-Stable-Decay",
            Self::Linear => "Warmup + Linear",
            Self::InvSqrt => "Inverse Sqrt",
            Self::Constant => "Warmup + Constant",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Hyperparams {
    pub master_seed: u64,
    pub optimizer: OptimizerKind,
    pub lr_schedule: LrSchedule,
    pub lr: f64,
    pub min_lr_ratio: f64,
    pub weight_decay: f64,
    pub beta1: f64,
    pub beta2: f64,
    pub grad_clip_norm: f32,
    pub label_smoothing: f32,
    pub batch_size: usize,
    pub grad_accum_steps: usize,
    pub total_steps: usize,
    pub warmup_steps: usize,
    pub eval_every: usize,
    pub checkpoint_every: usize,
    pub nan_rollback: bool,
    pub compute_threads: usize,
}

impl Default for Hyperparams {
    fn default() -> Self {
        let default_threads = std::thread::available_parallelism()
            .map(|n| n.get().saturating_sub(1).clamp(1, 8))
            .unwrap_or(2);
        Self {
            master_seed: 42,
            optimizer: OptimizerKind::AdamW,
            lr_schedule: LrSchedule::Cosine,
            lr: 3e-3,
            min_lr_ratio: 0.1,
            weight_decay: 0.01,
            beta1: 0.9,
            beta2: 0.95,
            grad_clip_norm: 1.0,
            label_smoothing: 0.0,
            batch_size: 8,
            grad_accum_steps: 1,
            total_steps: 120,
            warmup_steps: 12,
            eval_every: 20,
            checkpoint_every: 40,
            nan_rollback: true,
            compute_threads: default_threads,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SamplingConfig {
    pub temperature: f32,
    pub top_p: f32,
    pub top_k: usize,
    pub repetition_penalty: f32,
    pub max_new_tokens: usize,
    pub seed: u64,
    pub ab_compare: bool,
}

impl Default for SamplingConfig {
    fn default() -> Self {
        Self {
            temperature: 0.7,
            top_p: 0.9,
            top_k: 32,
            repetition_penalty: 1.08,
            max_new_tokens: 96,
            seed: 42,
            ab_compare: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RunConfig {
    pub name: String,
    pub modality: Modality,
    pub mechanism: Mechanism,
    pub backbone: Backbone,
    pub preset: Preset,
    pub dataset: DatasetConfig,
    pub tokenizer: TokenizerConfig,
    pub model: TransformerConfig,
    pub hyper: Hyperparams,
    pub sampling: SamplingConfig,
}

impl Default for RunConfig {
    fn default() -> Self {
        Self {
            name: "tiny-transformer-v1".to_owned(),
            modality: Modality::Text,
            mechanism: Mechanism::Autoregressive,
            backbone: Backbone::Transformer,
            preset: Preset::Nano,
            dataset: DatasetConfig::default(),
            tokenizer: TokenizerConfig::default(),
            model: TransformerConfig::default(),
            hyper: Hyperparams::default(),
            sampling: SamplingConfig::default(),
        }
    }
}

/// Real-time analytical parameter, RAM, KV-cache, and FLOPs breakdown.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ModelSpecEstimate {
    pub total_params: usize,
    pub active_params: usize,
    pub weights_mb: f64,
    pub optimizer_mb: f64,
    pub activations_mb: f64,
    pub kv_cache_kb: f64,
    pub total_train_mb: f64,
    pub flops_per_step: f64,
}

impl RunConfig {
    pub fn estimate_specs(&self) -> ModelSpecEstimate {
        let m = self.model.sanitized();
        let d = m.d_model;
        let head_dim = m.head_dim();
        let kv_dim = m.n_kv_heads * head_dim;

        let mut embed_params = m.vocab_size * d;
        if m.pos_encoding == PosEncoding::Learned {
            embed_params += m.seq_len * d;
        }
        let lm_head_params = if m.tie_embeddings { 0 } else { m.vocab_size * d };

        // Attention projections: Wq (d*d) + Wk (d*kv) + Wv (d*kv) + Wo (d*d).
        let bias_attn = if m.use_bias { d + 2 * kv_dim + d } else { 0 };
        let qk_norm_params = if m.qk_norm { 2 * head_dim } else { 0 };
        let attn_params = 2 * d * d + 2 * d * kv_dim + bias_attn + qk_norm_params;

        // One FFN block: gated uses 3 matrices (gate, up, down); standard uses 2 (up, down).
        let ffn_matrices = if m.activation.is_gated() { 3 } else { 2 };
        let single_ffn = ffn_matrices * d * m.d_ff
            + if m.use_bias {
                (ffn_matrices - 1) * m.d_ff + d
            } else {
                0
            };

        let (ffn_total_per_layer, ffn_active_per_layer) = match m.routing {
            Routing::Dense => (single_ffn, single_ffn),
            Routing::MoE => {
                let router = d * m.moe.n_experts;
                let total = router + (m.moe.n_experts + m.moe.n_shared_experts) * single_ffn;
                let active = router + (m.moe.top_k + m.moe.n_shared_experts) * single_ffn;
                (total, active)
            }
        };

        let norm_per_layer = match m.norm {
            NormKind::RmsNorm => 2 * d,
            NormKind::LayerNorm => 4 * d,
        };
        let final_norm = match m.norm {
            NormKind::RmsNorm => d,
            NormKind::LayerNorm => 2 * d,
        };

        let total_params = embed_params
            + lm_head_params
            + final_norm
            + m.n_layers * (attn_params + ffn_total_per_layer + norm_per_layer);
        let active_params = embed_params
            + lm_head_params
            + final_norm
            + m.n_layers * (attn_params + ffn_active_per_layer + norm_per_layer);

        let bytes_per_f32 = 4.0;
        let weights_mb = (total_params as f64 * bytes_per_f32) / (1024.0 * 1024.0);
        let grads_mb = weights_mb;
        let optimizer_mb =
            weights_mb * self.hyper.optimizer.state_floats_per_param();

        let tokens_per_micro = (self.hyper.batch_size.max(1) * m.seq_len) as f64;
        // Activation estimate across layers (QKV + scores + FFN intermediates).
        let act_floats_per_tok =
            m.n_layers as f64 * (4.0 * d as f64 + 2.0 * m.d_ff as f64 + m.seq_len as f64 * m.n_heads as f64);
        let activations_mb =
            (tokens_per_micro * act_floats_per_tok * bytes_per_f32) / (1024.0 * 1024.0);

        let kv_cache_kb = (m.n_layers * 2 * kv_dim * m.seq_len) as f64 * bytes_per_f32 / 1024.0;
        let total_train_mb = weights_mb + grads_mb + optimizer_mb + activations_mb;

        let effective_tokens = tokens_per_micro * self.hyper.grad_accum_steps.max(1) as f64;
        let flops_per_step = 6.0 * (active_params as f64) * effective_tokens;

        ModelSpecEstimate {
            total_params,
            active_params,
            weights_mb,
            optimizer_mb,
            activations_mb,
            kv_cache_kb,
            total_train_mb,
            flops_per_step,
        }
    }
}

pub fn format_count(n: usize) -> String {
    if n >= 1_000_000_000 {
        format!("{:.2}B", n as f64 / 1_000_000_000.0)
    } else if n >= 1_000_000 {
        format!("{:.2}M", n as f64 / 1_000_000.0)
    } else if n >= 1_000 {
        format!("{:.1}K", n as f64 / 1_000.0)
    } else {
        n.to_string()
    }
}

pub fn format_flops(flops: f64) -> String {
    if flops >= 1e12 {
        format!("{:.2} TFLOPs", flops / 1e12)
    } else if flops >= 1e9 {
        format!("{:.2} GFLOPs", flops / 1e9)
    } else if flops >= 1e6 {
        format!("{:.1} MFLOPs", flops / 1e6)
    } else {
        format!("{:.0} FLOPs", flops)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_keeps_head_and_kv_divisibility_valid() {
        let mut cfg = TransformerConfig::default();
        cfg.d_model = 100;
        cfg.n_heads = 6;
        cfg.n_kv_heads = 4;
        let clean = cfg.sanitized();
        assert_eq!(clean.d_model % (clean.n_heads * 2), 0);
        assert_eq!(clean.n_heads % clean.n_kv_heads, 0);
    }

    #[test]
    fn moe_increases_total_params_more_than_active_params() {
        let mut dense = RunConfig::default();
        dense.model.routing = Routing::Dense;
        let mut moe = dense.clone();
        moe.model.routing = Routing::MoE;
        moe.model.moe.n_experts = 6;
        moe.model.moe.top_k = 2;
        moe.model.moe.n_shared_experts = 0;

        let d_est = dense.estimate_specs();
        let m_est = moe.estimate_specs();
        assert!(m_est.total_params > m_est.active_params);
        assert!(m_est.total_params > d_est.total_params * 2);
    }

    #[test]
    fn lion_uses_less_optimizer_memory_than_adamw() {
        let mut a = RunConfig::default();
        a.hyper.optimizer = OptimizerKind::AdamW;
        let mut b = a.clone();
        b.hyper.optimizer = OptimizerKind::Lion;
        assert!(b.estimate_specs().optimizer_mb < a.estimate_specs().optimizer_mb);
    }
}
