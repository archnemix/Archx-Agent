//! Purpose: Defines the composable model taxonomy, Engine #1 Transformer/MoE hyperparameters, Tokenizer rules, Hardware execution targets, Seed hierarchy, and RAM/FLOPs estimators.

use serde::{Deserialize, Serialize};

use crate::rng::{PrngAlgorithm, SeedHierarchy};

/// Axis A: Input/output modality. Slice 1/2 implements `Text` end-to-end.
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

/// Axis B: Generative training objective.
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

/// Axis C: Sequence/spatial backbone. Engine #1 is `Transformer`.
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

/// Axis D: Feed-forward routing (`Dense` and `MoE` are both live).
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
            Self::Unigram => "Unigram (Viterbi)",
            Self::CharLevel => "Character-Level",
            Self::PretrainedFile => "Load tokenizer.json",
        }
    }

    pub fn family_badge(self) -> &'static str {
        match self {
            Self::ByteLevelBpe => "GPT-4 / Llama-3 / Qwen",
            Self::WordPiece => "BERT / Electra",
            Self::Unigram => "SentencePiece / Gemma / T5",
            Self::CharLevel => "Karpathy / Algorithmic",
            Self::PretrainedFile => "External HF JSON",
        }
    }
}

/// Pre-tokenization boundary rule applied before subword merges or scoring.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum PreTokenizeMode {
    #[default]
    Gpt4Regex,
    WhitespacePunct,
    CodeIndentAware,
    RawStream,
}

impl PreTokenizeMode {
    pub const ALL: [Self; 4] = [
        Self::Gpt4Regex,
        Self::WhitespacePunct,
        Self::CodeIndentAware,
        Self::RawStream,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Gpt4Regex => "GPT-4 / Llama-3 Boundaries",
            Self::WhitespacePunct => "Whitespace + Punctuation",
            Self::CodeIndentAware => "Code & Indent Aware",
            Self::RawStream => "Cross-Boundary Raw Stream",
        }
    }
}

/// Controls how numeric literals are segmented before subword merges.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum DigitPolicy {
    IndividualDigits,
    #[default]
    ChunksOf3,
    WholeNumbers,
}

impl DigitPolicy {
    pub const ALL: [Self; 3] = [Self::IndividualDigits, Self::ChunksOf3, Self::WholeNumbers];

    pub fn label(self) -> &'static str {
        match self {
            Self::IndividualDigits => "Single Digits (0-9 · Math Optimal)",
            Self::ChunksOf3 => "1-to-3 Digit Groups (GPT-4 / Llama-3)",
            Self::WholeNumbers => "Merge Full Numbers",
        }
    }
}

/// Text normalization applied prior to pre-tokenization.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum UnicodeNorm {
    #[default]
    None,
    CleanWhitespace,
    Lowercase,
}

impl UnicodeNorm {
    pub const ALL: [Self; 3] = [Self::None, Self::CleanWhitespace, Self::Lowercase];

    pub fn label(self) -> &'static str {
        match self {
            Self::None => "Raw UTF-8 (Lossless)",
            Self::CleanWhitespace => "Normalize Control & CRLF",
            Self::Lowercase => "Case-Folded Lowercase",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TokenizerConfig {
    pub kind: TokenizerKind,
    pub vocab_size: usize,
    pub min_frequency: usize,
    pub pretrained_path: String,
    pub sequence_packing: bool,
    pub add_bos_eos: bool,
    pub lowercase: bool,
    #[serde(default)]
    pub pre_tokenize: PreTokenizeMode,
    #[serde(default)]
    pub digit_policy: DigitPolicy,
    #[serde(default)]
    pub normalization: UnicodeNorm,
    #[serde(default = "default_true")]
    pub byte_fallback: bool,
    #[serde(default = "default_pad_multiple")]
    pub pad_to_multiple: usize,
    #[serde(default)]
    pub subword_dropout: f32,
    #[serde(default)]
    pub custom_special_tokens: String,
}

fn default_true() -> bool {
    true
}

fn default_pad_multiple() -> usize {
    64
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
            pre_tokenize: PreTokenizeMode::Gpt4Regex,
            digit_policy: DigitPolicy::ChunksOf3,
            normalization: UnicodeNorm::None,
            byte_fallback: true,
            pad_to_multiple: 64,
            subword_dropout: 0.0,
            custom_special_tokens: "<think>,</think>".to_owned(),
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

/// Layer normalization topology inside each Transformer residual block.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum NormPlacement {
    #[default]
    PreNorm,
    PostNorm,
    SandwichNorm,
}

impl NormPlacement {
    pub const ALL: [Self; 3] = [Self::PreNorm, Self::PostNorm, Self::SandwichNorm];

    pub fn label(self) -> &'static str {
        match self {
            Self::PreNorm => "Pre-Norm (Llama / GPT-2)",
            Self::PostNorm => "Post-Norm (Vaswani 2017)",
            Self::SandwichNorm => "Sandwich-Norm (Gemma-2)",
        }
    }
}

/// Residual projection scaling scheme for deep/wide stability.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum ResidualScaleMode {
    Standard,
    #[default]
    Gpt2DepthScaled,
    MuPWidthScaled,
}

impl ResidualScaleMode {
    pub const ALL: [Self; 3] = [Self::Standard, Self::Gpt2DepthScaled, Self::MuPWidthScaled];

    pub fn label(self) -> &'static str {
        match self {
            Self::Standard => "1.0x Unscaled",
            Self::Gpt2DepthScaled => "1 / √(2·L) Depth Scale",
            Self::MuPWidthScaled => "μP Width + Depth Scale",
        }
    }
}

/// RoPE frequency scaling mode for extended context horizons.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum RopeScalingMode {
    #[default]
    None,
    Linear2x,
    Linear4x,
    NtkDynamic,
}

impl RopeScalingMode {
    pub const ALL: [Self; 4] = [
        Self::None,
        Self::Linear2x,
        Self::Linear4x,
        Self::NtkDynamic,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::None => "Standard RoPE",
            Self::Linear2x => "Linear 2x Interpolation",
            Self::Linear4x => "Linear 4x Interpolation",
            Self::NtkDynamic => "NTK-Aware Base Scaling",
        }
    }
}

/// Input embedding variance scaling.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum EmbedScaleMode {
    #[default]
    One,
    SqrtDModel,
}

impl EmbedScaleMode {
    pub const ALL: [Self; 2] = [Self::One, Self::SqrtDModel];

    pub fn label(self) -> &'static str {
        match self {
            Self::One => "1.0x Raw",
            Self::SqrtDModel => "√d_model (Gemma / Vaswani)",
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
    TruncatedNormal,
    XavierUniform,
    KaimingNormal,
}

impl InitDist {
    pub const ALL: [Self; 4] = [
        Self::Normal,
        Self::TruncatedNormal,
        Self::XavierUniform,
        Self::KaimingNormal,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Normal => "Normal (σ)",
            Self::TruncatedNormal => "Truncated Normal (±2σ)",
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
    #[serde(default)]
    pub norm_placement: NormPlacement,
    pub norm_eps: f64,
    pub activation: ActivationKind,
    pub pos_encoding: PosEncoding,
    pub rope_theta: f32,
    #[serde(default)]
    pub rope_scaling: RopeScalingMode,
    #[serde(default)]
    pub embed_scale: EmbedScaleMode,
    pub qk_norm: bool,
    pub tie_embeddings: bool,
    pub use_bias: bool,
    pub dropout: f32,
    pub sliding_window: usize, // 0 = full causal context
    #[serde(default)]
    pub attn_logit_softcap: f32, // 0.0 = disabled; e.g. 30.0 or 50.0 = Gemma-2 tanh softcap
    #[serde(default)]
    pub final_logit_softcap: f32, // 0.0 = disabled; e.g. 30.0 = output logit tanh softcap
    pub routing: Routing,
    pub moe: MoEConfig,
    pub init_dist: InitDist,
    pub init_std: f32,
    #[serde(default = "default_trunc_sigma")]
    pub truncated_sigma: f32,
    pub residual_scale: bool,
    #[serde(default)]
    pub residual_scale_mode: ResidualScaleMode,
    pub init_seed: u64,
    #[serde(default)]
    pub prng_algorithm: PrngAlgorithm,
}

fn default_trunc_sigma() -> f32 {
    2.0
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
            norm_placement: NormPlacement::PreNorm,
            norm_eps: 1e-5,
            activation: ActivationKind::SwiGlu,
            pos_encoding: PosEncoding::RoPE,
            rope_theta: 10_000.0,
            rope_scaling: RopeScalingMode::None,
            embed_scale: EmbedScaleMode::One,
            qk_norm: true,
            tie_embeddings: true,
            use_bias: false,
            dropout: 0.0,
            sliding_window: 0,
            attn_logit_softcap: 0.0,
            final_logit_softcap: 0.0,
            routing,
            moe: MoEConfig::default(),
            init_dist: InitDist::TruncatedNormal,
            init_std: 0.02,
            truncated_sigma: 2.0,
            residual_scale: true,
            residual_scale_mode: ResidualScaleMode::Gpt2DepthScaled,
            init_seed: 42,
            prng_algorithm: PrngAlgorithm::SplitMix64,
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
        cfg.truncated_sigma = cfg.truncated_sigma.clamp(1.0, 5.0);
        cfg.attn_logit_softcap = cfg.attn_logit_softcap.clamp(0.0, 200.0);
        cfg.final_logit_softcap = cfg.final_logit_softcap.clamp(0.0, 200.0);
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

/// User-selected hardware compute execution target.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum ComputeTarget {
    #[default]
    Auto,
    Cpu,
    Gpu,
}

impl ComputeTarget {
    pub const ALL: [Self; 3] = [Self::Auto, Self::Cpu, Self::Gpu];

    pub fn label(self) -> &'static str {
        match self {
            Self::Auto => "Auto · Best Detected Hardware",
            Self::Cpu => "CPU · Multi-Threaded SIMD",
            Self::Gpu => "GPU · WGSL Compute (Vulkan / DX12 / Metal)",
        }
    }
}

/// Numeric precision execution plan.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum PrecisionMode {
    #[default]
    Fp32Strict,
    Bf16MixedPlan,
    Fp16Wgsl,
}

impl PrecisionMode {
    pub const ALL: [Self; 3] = [Self::Fp32Strict, Self::Bf16MixedPlan, Self::Fp16Wgsl];

    pub fn label(self) -> &'static str {
        match self {
            Self::Fp32Strict => "FP32 Master & Compute (Exact)",
            Self::Bf16MixedPlan => "BF16 Weights + FP32 Accumulator",
            Self::Fp16Wgsl => "FP16 WGSL Shader + FP32 Master",
        }
    }

    pub fn activation_bytes_per_elem(self) -> f64 {
        match self {
            Self::Fp32Strict => 4.0,
            Self::Bf16MixedPlan | Self::Fp16Wgsl => 2.0,
        }
    }
}

/// Hardware execution & custom optimization preferences stored with the run.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HardwareExecConfig {
    pub target: ComputeTarget,
    pub preferred_gpu_index: usize,
    pub precision: PrecisionMode,
    pub auto_tune_batch_and_threads: bool,
    pub activation_checkpointing: bool,
    pub pad_vocab_for_hardware: bool,
    pub fused_ce_chunk_tokens: usize,
}

impl Default for HardwareExecConfig {
    fn default() -> Self {
        Self {
            target: ComputeTarget::Auto,
            preferred_gpu_index: 0,
            precision: PrecisionMode::Fp32Strict,
            auto_tune_batch_and_threads: true,
            activation_checkpointing: false,
            pad_vocab_for_hardware: true,
            fused_ce_chunk_tokens: 512,
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
    #[serde(default)]
    pub hardware_exec: HardwareExecConfig,
    #[serde(default)]
    pub seeds: SeedHierarchy,
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
            hardware_exec: HardwareExecConfig::default(),
            seeds: SeedHierarchy::default(),
            hyper: Hyperparams::default(),
            sampling: SamplingConfig::default(),
        }
    }
}

/// Progressive UI complexity tier so non-technical users get a calm, plain-English
/// workflow while everyday builders and ML researchers still control every parameter.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum UiComplexity {
    #[default]
    Simple,
    Standard,
    Expert,
}

impl UiComplexity {
    pub const ALL: [Self; 3] = [Self::Simple, Self::Standard, Self::Expert];

    pub fn label(self) -> &'static str {
        match self {
            Self::Simple => "Simple",
            Self::Standard => "Normal",
            Self::Expert => "Advanced",
        }
    }

    pub fn subtitle(self) -> &'static str {
        match self {
            Self::Simple => "Guided plain-English setup — train a model in 3 clicks without technical jargon.",
            Self::Standard => "Everyday builder controls — size predictor, token-to-param ratio, layers, batch & seed.",
            Self::Expert => "Full research lab — every tokenizer rule, RoPE/norm topology, MoE router, GPU kernel & SHA-256 knob.",
        }
    }
}

/// Real-time analytical parameter, RAM, KV-cache, and FLOPs breakdown.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
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

/// Exact disk & runtime memory size forecast for exported checkpoints and local inference.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct SizePrediction {
    pub total_params: usize,
    pub active_params: usize,
    /// Exact `.safetensors` single-checkpoint size in FP32 (`4 bytes/param` + JSON header).
    pub fp32_safetensors_mb: f64,
    /// Half-precision (`BF16` / `FP16`) checkpoint size (`2 bytes/param` + header).
    pub fp16_bf16_mb: f64,
    /// 8-bit quantized deployment estimate (`~1.05 bytes/param` including scales).
    pub int8_quant_mb: f64,
    /// 4-bit group-quantized deployment estimate (`~0.56 bytes/param` including scales).
    pub int4_quant_mb: f64,
    /// Total disk space for a full run folder (`best/` + `latest/` + optional `genesis/` + `tokenizer.json` + logs).
    pub full_run_folder_mb: f64,
    /// Peak RAM/VRAM required during training (accounting for micro-batching, chunked CE & checkpointing).
    pub peak_train_ram_mb: f64,
    /// RAM required to chat with the model in Playground (`FP32` weights + context KV cache).
    pub chat_fp32_ram_mb: f64,
    /// RAM required for `FP16`/`BF16` inference (`2B` weights + context KV cache).
    pub chat_fp16_ram_mb: f64,
}

/// Chinchilla / Llama scaling-law analysis of scheduled training tokens vs. active model parameters.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TokenParamRatioSummary {
    pub active_params: usize,
    pub tokens_per_step: usize,
    pub scheduled_tokens: usize,
    pub tokens_per_param: f64,
    pub chinchilla_optimal_tokens: usize,
    pub chinchilla_optimal_steps: usize,
    pub corpus_tokens: Option<usize>,
    pub epochs_over_corpus: Option<f64>,
    pub status_badge: &'static str,
    pub plain_advice: String,
    pub is_balanced: bool,
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

        let bias_attn = if m.use_bias { d + 2 * kv_dim + d } else { 0 };
        let qk_norm_params = if m.qk_norm { 2 * head_dim } else { 0 };
        let attn_params = 2 * d * d + 2 * d * kv_dim + bias_attn + qk_norm_params;

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

        let norms_per_block = match m.norm_placement {
            NormPlacement::PreNorm | NormPlacement::PostNorm => 2,
            NormPlacement::SandwichNorm => 4,
        };
        let norm_per_layer = match m.norm {
            NormKind::RmsNorm => norms_per_block * d,
            NormKind::LayerNorm => norms_per_block * 2 * d,
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
        let optimizer_mb = weights_mb * self.hyper.optimizer.state_floats_per_param();

        let eff_micro_batch = if self.hardware_exec.activation_checkpointing && self.hyper.batch_size >= 2 {
            (self.hyper.batch_size / 2).max(1)
        } else {
            self.hyper.batch_size.max(1)
        };
        let tokens_per_micro = (eff_micro_batch * m.seq_len) as f64;
        let ckpt_factor = if self.hardware_exec.activation_checkpointing {
            ((m.n_layers as f64).sqrt() / (m.n_layers.max(1) as f64)).min(0.65)
        } else {
            1.0
        };
        let act_bytes = self.hardware_exec.precision.activation_bytes_per_elem();
        let act_floats_per_tok = m.n_layers as f64
            * (4.0 * d as f64 + 2.0 * m.d_ff as f64 + m.seq_len as f64 * m.n_heads as f64);
        let ce_tokens = if self.hardware_exec.fused_ce_chunk_tokens > 0 {
            tokens_per_micro.min(self.hardware_exec.fused_ce_chunk_tokens as f64)
        } else {
            tokens_per_micro
        };
        let logits_mb = (ce_tokens * m.vocab_size as f64 * 4.0) / (1024.0 * 1024.0);
        let activations_mb =
            (tokens_per_micro * act_floats_per_tok * act_bytes * ckpt_factor) / (1024.0 * 1024.0)
                + logits_mb;

        let kv_cache_kb = (m.n_layers * 2 * kv_dim * m.seq_len) as f64 * bytes_per_f32 / 1024.0;
        let total_train_mb = weights_mb + grads_mb + optimizer_mb + activations_mb;

        let effective_tokens =
            (self.hyper.batch_size.max(1) * m.seq_len * self.hyper.grad_accum_steps.max(1)) as f64;
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

    /// Predicts exact exported checkpoint file sizes across precisions and full run disk usage.
    pub fn predict_sizes(&self) -> SizePrediction {
        let est = self.estimate_specs();
        let header_mb = 0.025; // ~25 KB safetensors JSON tensor metadata header
        let mb = 1024.0 * 1024.0;
        let fp32_safetensors_mb = (est.total_params as f64 * 4.0) / mb + header_mb;
        let fp16_bf16_mb = (est.total_params as f64 * 2.0) / mb + header_mb;
        let int8_quant_mb = (est.total_params as f64 * 1.05) / mb + header_mb;
        let int4_quant_mb = (est.total_params as f64 * 0.56) / mb + header_mb;

        let ckpt_copies = if self.seeds.auto_export_genesis_init {
            3.0 // best + latest + genesis_step0
        } else {
            2.0 // best + latest
        };
        let tokenizer_and_meta_mb = (self.model.vocab_size as f64 * 28.0) / mb + 0.15;
        let full_run_folder_mb = fp32_safetensors_mb * ckpt_copies + tokenizer_and_meta_mb;

        let kv_mb = est.kv_cache_kb / 1024.0;
        let chat_fp32_ram_mb = fp32_safetensors_mb + kv_mb + 4.0;
        let chat_fp16_ram_mb = fp16_bf16_mb + kv_mb * 0.5 + 4.0;

        SizePrediction {
            total_params: est.total_params,
            active_params: est.active_params,
            fp32_safetensors_mb,
            fp16_bf16_mb,
            int8_quant_mb,
            int4_quant_mb,
            full_run_folder_mb,
            peak_train_ram_mb: est.total_train_mb,
            chat_fp32_ram_mb,
            chat_fp16_ram_mb,
        }
    }

    /// Computes live Tokens-per-Parameter ratio (Chinchilla 20× golden rule & corpus epoch check).
    pub fn token_param_ratio(&self, corpus_tokens: Option<usize>) -> TokenParamRatioSummary {
        let est = self.estimate_specs();
        let m = self.model.sanitized();
        let active_params = est.active_params.max(1);
        let tokens_per_step =
            (self.hyper.batch_size.max(1) * self.hyper.grad_accum_steps.max(1) * m.seq_len).max(1);
        let scheduled_tokens = self.hyper.total_steps.max(1).saturating_mul(tokens_per_step);
        let tokens_per_param = scheduled_tokens as f64 / active_params as f64;

        let chinchilla_optimal_tokens = active_params.saturating_mul(20);
        let chinchilla_optimal_steps =
            ((chinchilla_optimal_tokens + tokens_per_step - 1) / tokens_per_step).max(10);

        let epochs_over_corpus = corpus_tokens
            .filter(|&c| c > 0)
            .map(|c| scheduled_tokens as f64 / c as f64);

        let (status_badge, is_balanced, mut advice) = if tokens_per_param < 2.0 {
            (
                "Smoke Test (<2 tok/param)",
                false,
                format!(
                    "Only {:.1} tokens per parameter — good for a quick 10-second test, but increase steps to ~{} for Chinchilla-optimal learning (20 tok/param).",
                    tokens_per_param, chinchilla_optimal_steps
                ),
            )
        } else if tokens_per_param < 12.0 {
            (
                "Light Draft (Fast)",
                true,
                format!(
                    "{:.1} tokens per parameter — learns basic patterns quickly. Click '20× Optimal' ({} steps) for full Chinchilla convergence.",
                    tokens_per_param, chinchilla_optimal_steps
                ),
            )
        } else if tokens_per_param <= 30.0 {
            (
                "Chinchilla Optimal (~20×)",
                true,
                format!(
                    "{:.1} tokens per parameter — right inside the 15×–30× compute-optimal scaling sweet spot.",
                    tokens_per_param
                ),
            )
        } else if tokens_per_param <= 85.0 {
            (
                "Over-Trained · Smart Small Model",
                true,
                format!(
                    "{:.1} tokens per parameter — Llama/Qwen inference-optimal regime (packs maximum quality into a compact model).",
                    tokens_per_param
                ),
            )
        } else {
            (
                "Heavy Saturation (>85×)",
                false,
                format!(
                    "{:.1} tokens per parameter — diminishing returns unless your dataset is very large; consider scaling model width/layers up.",
                    tokens_per_param
                ),
            )
        };

        if let Some(ep) = epochs_over_corpus {
            if ep > 12.0 {
                advice.push_str(&format!(
                    " Note: repeats active dataset {:.1}× (risk of memorizing exact sentences — add more text or click 'Size Model to Dataset').",
                    ep
                ));
            } else {
                advice.push_str(&format!(" Passes over dataset ~{:.1}×.", ep));
            }
        }

        TokenParamRatioSummary {
            active_params,
            tokens_per_step,
            scheduled_tokens,
            tokens_per_param,
            chinchilla_optimal_tokens,
            chinchilla_optimal_steps,
            corpus_tokens,
            epochs_over_corpus,
            status_badge,
            plain_advice: advice,
            is_balanced,
        }
    }

    /// Updates `hyper.total_steps` (and proportional `warmup_steps`) so `scheduled_tokens / active_params`
    /// matches `target_ratio` (e.g. `20.0` for Chinchilla compute-optimal).
    pub fn apply_target_tokens_per_param(&mut self, target_ratio: f64) {
        let ratio = target_ratio.clamp(0.5, 200.0);
        let est = self.estimate_specs();
        let m = self.model.sanitized();
        let tok_per_step =
            (self.hyper.batch_size.max(1) * self.hyper.grad_accum_steps.max(1) * m.seq_len).max(1);
        let desired_tokens = ((est.active_params as f64) * ratio).round() as usize;
        let steps = ((desired_tokens + tok_per_step - 1) / tok_per_step).clamp(8, 200_000);
        self.hyper.total_steps = steps;
        self.hyper.warmup_steps = ((steps as f64 * 0.08).round() as usize).clamp(2, 2_000);
    }

    /// Automatically sizes Transformer depth/width AND step count to fit `corpus_tokens`
    /// at `target_ratio` tokens/parameter over `target_epochs` passes through the dataset.
    pub fn auto_size_model_for_dataset(
        &mut self,
        corpus_tokens: usize,
        target_ratio: f64,
        target_epochs: f64,
    ) {
        let ratio = target_ratio.clamp(2.0, 100.0);
        let epochs = target_epochs.clamp(1.0, 8.0);
        let budget_tokens = ((corpus_tokens.max(2_048) as f64) * epochs) as usize;
        let ideal_params = ((budget_tokens as f64) / ratio) as usize;

        // Pick clean hardware-aligned architecture tiers matching `ideal_params`.
        let (layers, d_model, n_heads, n_kv, d_ff, preset) = if ideal_params < 600_000 {
            (3, 96, 4, 2, 256, Preset::Nano)
        } else if ideal_params < 3_500_000 {
            (4, 160, 4, 2, 448, Preset::Micro)
        } else if ideal_params < 10_000_000 {
            (6, 256, 8, 4, 704, Preset::Custom)
        } else if ideal_params < 26_000_000 {
            (8, 384, 8, 4, 1024, Preset::Small)
        } else {
            (12, 512, 8, 4, 1408, Preset::Base)
        };

        self.preset = preset;
        self.model.n_layers = layers;
        self.model.d_model = d_model;
        self.model.n_heads = n_heads;
        self.model.n_kv_heads = n_kv;
        self.model.d_ff = d_ff;

        let m = self.model.sanitized();
        let tok_per_step =
            (self.hyper.batch_size.max(1) * self.hyper.grad_accum_steps.max(1) * m.seq_len).max(1);
        let steps = ((budget_tokens + tok_per_step - 1) / tok_per_step).clamp(12, 200_000);
        self.hyper.total_steps = steps;
        self.hyper.warmup_steps = ((steps as f64 * 0.08).round() as usize).clamp(2, 2_000);
    }
}

pub fn format_size_mb(mb: f64) -> String {
    if mb >= 1024.0 {
        format!("{:.2} GB", mb / 1024.0)
    } else if mb >= 10.0 {
        format!("{:.1} MB", mb)
    } else if mb >= 1.0 {
        format!("{:.2} MB", mb)
    } else {
        format!("{:.0} KB", (mb * 1024.0).max(1.0))
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
    fn lion_uses_less_optimizer_memory_than_adamw_and_checkpointing_shrinks_activations() {
        let mut a = RunConfig::default();
        a.model.n_layers = 8;
        a.hyper.optimizer = OptimizerKind::AdamW;
        let mut b = a.clone();
        b.hyper.optimizer = OptimizerKind::Lion;
        b.hardware_exec.activation_checkpointing = true;
        assert!(b.estimate_specs().optimizer_mb < a.estimate_specs().optimizer_mb);
        assert!(b.estimate_specs().activations_mb < a.estimate_specs().activations_mb);
    }

    #[test]
    fn size_prediction_and_chinchilla_ratio_adjuster_work() {
        let mut cfg = RunConfig::default();
        let sz = cfg.predict_sizes();
        assert!(sz.fp32_safetensors_mb > sz.fp16_bf16_mb);
        assert!(sz.fp16_bf16_mb > sz.int8_quant_mb);
        assert!(sz.int8_quant_mb > sz.int4_quant_mb);
        assert!(sz.full_run_folder_mb >= sz.fp32_safetensors_mb * 2.0);

        cfg.apply_target_tokens_per_param(20.0);
        let rep = cfg.token_param_ratio(Some(500_000));
        assert!(
            (rep.tokens_per_param - 20.0).abs() < 1.5,
            "Expected ~20 tok/param, got {}",
            rep.tokens_per_param
        );
        assert!(rep.is_balanced);

        cfg.auto_size_model_for_dataset(100_000_000, 20.0, 1.0);
        assert!(cfg.estimate_specs().total_params > 1_000_000);
    }
}
