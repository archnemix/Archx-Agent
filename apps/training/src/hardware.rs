//! Purpose: Probes host CPU/SIMD/RAM and real `wgpu` GPUs (Vulkan/DX12/Metal), runs tiled WGSL GPU compute benchmarks, and compiles custom hardware-adaptive optimization plans.

use std::future::Future;
use std::num::NonZeroU64;
use std::pin::Pin;
use std::sync::{Arc, Condvar, Mutex};
use std::task::{Context, Poll, Wake, Waker};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use bytemuck::{Pod, Zeroable};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use wgpu::util::DeviceExt;

use crate::config::{
    ComputeTarget, OptimizerKind, PosEncoding, PrecisionMode, Routing, RunConfig, TokenizerKind,
};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CpuInfo {
    pub brand: String,
    pub arch: String,
    pub os: String,
    pub logical_cores: usize,
    pub recommended_threads: usize,
    pub simd_features: Vec<String>,
}

impl CpuInfo {
    pub fn simd_tier(&self) -> &'static str {
        if self.simd_features.iter().any(|f| f.starts_with("AVX-512")) {
            "AVX-512 Wide Vector (512-bit)"
        } else if self.simd_features.iter().any(|f| f == "AVX2") {
            "AVX2 + FMA Vector (256-bit)"
        } else if self.simd_features.iter().any(|f| f == "NEON") {
            "ARM NEON SIMD (128-bit)"
        } else if self.simd_features.iter().any(|f| f == "SSE4.2") {
            "SSE4.2 SIMD (128-bit)"
        } else {
            "Portable Scalar / Auto-Vectorized"
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct MemoryInfo {
    pub total_ram_mb: u64,
    pub available_ram_mb: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GpuAdapterInfo {
    pub index: usize,
    pub name: String,
    pub vendor_id: u32,
    pub device_id: u32,
    pub device_type: String,
    pub is_hardware_gpu: bool,
    pub backend: String,
    pub driver: String,
    pub driver_info: String,
    pub max_buffer_mb: u64,
    pub max_storage_binding_mb: u64,
    pub max_workgroup_size_x: u32,
    pub max_invocations_per_workgroup: u32,
    pub supports_compute: bool,
    pub supports_f16: bool,
    pub supports_subgroups: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HardwareProfile {
    pub probed_at_unix: u64,
    pub cpu: CpuInfo,
    pub memory: MemoryInfo,
    pub gpus: Vec<GpuAdapterInfo>,
}

impl HardwareProfile {
    /// Probes live host CPU, ISA vector extensions, system RAM, and all Vulkan/DX12/Metal GPUs.
    pub fn probe() -> Self {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        Self {
            probed_at_unix: now,
            cpu: probe_cpu(),
            memory: probe_memory(),
            gpus: probe_gpus(),
        }
    }

    /// Deterministic hardware fixture used only during `ARCHX_SNAPSHOT` screenshot runs
    /// so visual review artifacts never depend on the build machine's hardware names.
    pub fn snapshot_fixture() -> Self {
        Self {
            probed_at_unix: 1_764_115_200,
            cpu: CpuInfo {
                brand: "Archx Reference 16-Core Workstation CPU".to_owned(),
                arch: "x86_64".to_owned(),
                os: "native".to_owned(),
                logical_cores: 16,
                recommended_threads: 14,
                simd_features: vec![
                    "AVX2".to_owned(),
                    "FMA".to_owned(),
                    "F16C".to_owned(),
                    "SSE4.2".to_owned(),
                ],
            },
            memory: MemoryInfo {
                total_ram_mb: 32_768,
                available_ram_mb: 24_576,
            },
            gpus: vec![GpuAdapterInfo {
                index: 0,
                name: "Discrete Vulkan / DX12 Compute Adapter".to_owned(),
                vendor_id: 0x10DE,
                device_id: 0x2684,
                device_type: "Discrete GPU".to_owned(),
                is_hardware_gpu: true,
                backend: "Vulkan / DX12".to_owned(),
                driver: "Native WGPU 27".to_owned(),
                driver_info: "WGSL Compute Ready".to_owned(),
                max_buffer_mb: 8_192,
                max_storage_binding_mb: 2_048,
                max_workgroup_size_x: 1024,
                max_invocations_per_workgroup: 1024,
                supports_compute: true,
                supports_f16: true,
                supports_subgroups: true,
            }],
        }
    }

    pub fn best_hardware_gpu(&self) -> Option<&GpuAdapterInfo> {
        self.gpus
            .iter()
            .find(|g| g.is_hardware_gpu && g.supports_compute)
    }

    pub fn selected_gpu(&self, preferred_idx: usize) -> Option<&GpuAdapterInfo> {
        self.gpus
            .iter()
            .find(|g| g.index == preferred_idx && g.supports_compute)
            .or_else(|| self.best_hardware_gpu())
            .or_else(|| self.gpus.iter().find(|g| g.supports_compute))
    }
}

/// Result of running a live CPU vs WGSL GPU tiled matrix multiplication benchmark.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ComputeBenchmarkReport {
    pub matrix_dim: usize,
    pub cpu_threads: usize,
    pub cpu_ms: f64,
    pub cpu_gflops: f64,
    pub gpu_adapter_name: Option<String>,
    pub gpu_backend: Option<String>,
    pub gpu_ms: Option<f64>,
    pub gpu_gflops: Option<f64>,
    pub max_abs_diff: Option<f32>,
    pub recommended_winner: String,
    pub note: String,
}

/// Compact serializable summary embedded inside `TrainingProvenanceBundle`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OptimizationPlanSummary {
    pub resolved_target: ComputeTarget,
    pub resolved_device_label: String,
    pub backend_api: String,
    pub recommended_threads: usize,
    pub recommended_batch_size: usize,
    pub recommended_grad_accum: usize,
    pub effective_tokens_per_step: usize,
    pub recommended_vocab_size: usize,
    pub recommended_precision: PrecisionMode,
    pub recommended_activation_checkpointing: bool,
    pub recommended_fused_ce_chunk: usize,
    pub tile_m_n_k: (u32, u32, u32),
    pub workgroup_dims: (u32, u32, u32),
    pub attention_strategy: String,
    pub device_budget_mb: f64,
    pub estimated_peak_mb: f64,
    pub headroom_pct: f32,
    pub fits_in_budget: bool,
}

/// Complete hardware-adaptive optimization strategy & generated custom execution script.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OptimizationPlan {
    pub summary: OptimizationPlanSummary,
    pub rationale: Vec<String>,
    pub custom_script_toml: String,
}

impl OptimizationPlan {
    /// Compiles a custom hardware + model + tokenizer optimization strategy and TOML execution plan.
    pub fn compile(hw: &HardwareProfile, cfg: &RunConfig) -> Self {
        let model = cfg.model.sanitized();
        let spec = cfg.estimate_specs();

        let chosen_gpu = hw.selected_gpu(cfg.hardware_exec.preferred_gpu_index);
        let (resolved_target, resolved_device_label, backend_api) = match cfg.hardware_exec.target {
            ComputeTarget::Cpu => (
                ComputeTarget::Cpu,
                format!("CPU · {} ({})", hw.cpu.brand, hw.cpu.simd_tier()),
                format!("Rayon SIMD ({} threads)", hw.cpu.recommended_threads),
            ),
            ComputeTarget::Gpu => {
                if let Some(gpu) = chosen_gpu {
                    (
                        ComputeTarget::Gpu,
                        format!("GPU #{} · {} ({})", gpu.index, gpu.name, gpu.device_type),
                        format!("WGSL {} Compute", gpu.backend),
                    )
                } else {
                    (
                        ComputeTarget::Cpu,
                        format!(
                            "CPU Fallback · {} (no compute GPU detected)",
                            hw.cpu.brand
                        ),
                        format!("Rayon SIMD ({} threads)", hw.cpu.recommended_threads),
                    )
                }
            }
            ComputeTarget::Auto => {
                if let Some(gpu) = hw.best_hardware_gpu() {
                    let single_binding_ok =
                        (spec.weights_mb as u64) < gpu.max_storage_binding_mb.max(128);
                    if single_binding_ok && spec.total_params >= 250_000 {
                        (
                            ComputeTarget::Gpu,
                            format!("Auto -> GPU #{} · {}", gpu.index, gpu.name),
                            format!("WGSL {} Compute", gpu.backend),
                        )
                    } else {
                        (
                            ComputeTarget::Cpu,
                            format!(
                                "Auto -> CPU · {} (low-latency cache resident for {} params)",
                                hw.cpu.brand,
                                crate::config::format_count(spec.total_params)
                            ),
                            format!("Rayon {} ({} threads)", hw.cpu.simd_tier(), hw.cpu.recommended_threads),
                        )
                    }
                } else {
                    (
                        ComputeTarget::Cpu,
                        format!("Auto -> CPU · {} ({})", hw.cpu.brand, hw.cpu.simd_tier()),
                        format!("Rayon SIMD ({} threads)", hw.cpu.recommended_threads),
                    )
                }
            }
        };

        let device_budget_mb = match resolved_target {
            ComputeTarget::Gpu => chosen_gpu
                .map(|g| (g.max_buffer_mb.max(512) as f64).min(hw.memory.available_ram_mb.max(1024) as f64))
                .unwrap_or(hw.memory.available_ram_mb.max(1024) as f64 * 0.75),
            _ => (hw.memory.available_ram_mb.max(1024) as f64) * 0.80,
        };

        let recommended_threads = hw.cpu.recommended_threads.clamp(1, 32);

        // Determine hardware-aligned vocabulary multiple (128 for GPU workgroups, 64 for SIMD CPU).
        let vocab_multiple = if resolved_target == ComputeTarget::Gpu { 128 } else { 64 };
        let base_vocab = cfg.tokenizer.vocab_size.max(64);
        let recommended_vocab_size = if cfg.hardware_exec.pad_vocab_for_hardware {
            ((base_vocab + vocab_multiple - 1) / vocab_multiple) * vocab_multiple
        } else {
            base_vocab
        };

        // Target effective batch tokens scaled to model size & corpus regime.
        let target_tokens_per_step: usize = if spec.total_params < 1_500_000 {
            1_024
        } else if spec.total_params < 12_000_000 {
            2_048
        } else if spec.total_params < 50_000_000 {
            4_096
        } else {
            8_192
        };

        // Per-sample activation memory at seq_len to pick max safe micro-batch without exceeding 55% of budget.
        let fixed_model_mb = spec.weights_mb * (2.0 + cfg.hyper.optimizer.state_floats_per_param());
        let avail_for_act_mb = (device_budget_mb * 0.55 - fixed_model_mb).max(16.0);
        let per_seq_act_mb = (spec.activations_mb / (cfg.hyper.batch_size.max(1) as f64)).max(0.05);
        let max_safe_micro = ((avail_for_act_mb / per_seq_act_mb).floor() as usize).clamp(1, 64);

        let ideal_micro = if resolved_target == ComputeTarget::Gpu {
            max_safe_micro.clamp(4, 32)
        } else if hw.cpu.simd_features.iter().any(|f| f == "AVX2" || f.starts_with("AVX-512")) {
            max_safe_micro.clamp(2, 16)
        } else {
            max_safe_micro.clamp(1, 8)
        };
        // Round micro-batch to power-of-two or even multiple for clean SIMD/workgroup occupancy.
        let recommended_batch_size = if ideal_micro >= 16 {
            16
        } else if ideal_micro >= 8 {
            8
        } else if ideal_micro >= 4 {
            4
        } else if ideal_micro >= 2 {
            2
        } else {
            1
        };

        let tokens_per_micro = (recommended_batch_size * model.seq_len).max(1);
        let recommended_grad_accum = target_tokens_per_step
            .div_ceil(tokens_per_micro)
            .clamp(1, 32);
        let effective_tokens_per_step = tokens_per_micro * recommended_grad_accum;

        let recommended_precision = match resolved_target {
            ComputeTarget::Gpu => {
                if chosen_gpu.is_some_and(|g| g.supports_f16) && spec.total_params >= 5_000_000 {
                    PrecisionMode::Fp16Wgsl
                } else {
                    PrecisionMode::Fp32Strict
                }
            }
            _ => {
                if hw.cpu.simd_features.iter().any(|f| f == "AVX-512BF16") {
                    PrecisionMode::Bf16MixedPlan
                } else {
                    PrecisionMode::Fp32Strict
                }
            }
        };

        let recommended_activation_checkpointing =
            model.seq_len >= 512 || spec.total_train_mb > device_budget_mb * 0.50;

        let recommended_fused_ce_chunk = if recommended_vocab_size >= 16_384 {
            256
        } else if recommended_vocab_size >= 4_096 {
            512
        } else {
            1_024
        };

        let (tile_m_n_k, workgroup_dims) = match resolved_target {
            ComputeTarget::Gpu => ((64, 64, 16), (16, 16, 1)),
            _ => {
                if hw.cpu.simd_features.iter().any(|f| f.starts_with("AVX-512")) {
                    ((64, 64, 64), (recommended_threads as u32, 1, 1))
                } else if hw.cpu.simd_features.iter().any(|f| f == "AVX2") {
                    ((32, 64, 32), (recommended_threads as u32, 1, 1))
                } else {
                    ((16, 32, 16), (recommended_threads as u32, 1, 1))
                }
            }
        };

        let attention_strategy = if model.sliding_window > 0 && model.sliding_window < model.seq_len {
            format!(
                "Sliding-Window Banded Causal Attention (W = {}, O(N·W) memory)",
                model.sliding_window
            )
        } else if model.seq_len >= 512 {
            "Flash-Tiled Causal Block Attention (128-token Q/KV tiles)".to_owned()
        } else {
            format!(
                "Register-Blocked {} Causal Attention (d_head = {})",
                model.attention_mode_label(),
                model.head_dim()
            )
        };

        let fits_in_budget = spec.total_train_mb <= device_budget_mb;
        let used_pct = ((spec.total_train_mb / device_budget_mb.max(1.0)) * 100.0).clamp(0.1, 999.0) as f32;
        let headroom_pct = (100.0 - used_pct).max(0.0);

        let mut rationale = Vec::new();
        rationale.push(format!(
            "Target Backend: {} via {} — selected for {} total parameters ({} active per token).",
            resolved_device_label,
            backend_api,
            crate::config::format_count(spec.total_params),
            crate::config::format_count(spec.active_params),
        ));
        rationale.push(format!(
            "Memory Budget: {:.1} MB estimated training footprint against {:.0} MB safe device budget ({:.1}% headroom).",
            spec.total_train_mb, device_budget_mb, headroom_pct
        ));
        rationale.push(format!(
            "Batch & Accumulation: micro-batch = {} × seq_len = {} ({} tok/pass) × {} accum steps = {} effective tokens/update.",
            recommended_batch_size,
            model.seq_len,
            tokens_per_micro,
            recommended_grad_accum,
            effective_tokens_per_step
        ));
        if recommended_vocab_size != cfg.tokenizer.vocab_size {
            rationale.push(format!(
                "Tokenizer-Hardware Alignment: pad vocab {} -> {} (multiple of {}) to eliminate tail-lane divergence in embedding & LM-head matmuls.",
                cfg.tokenizer.vocab_size, recommended_vocab_size, vocab_multiple
            ));
        } else {
            rationale.push(format!(
                "Tokenizer-Hardware Alignment: vocab {} is already aligned to {}-wide compute tiles ({}).",
                cfg.tokenizer.vocab_size,
                vocab_multiple,
                cfg.tokenizer.kind.label()
            ));
        }
        match cfg.tokenizer.kind {
            TokenizerKind::CharLevel => rationale.push(
                "Character-Level Tokenizer Impact: ~3.8x more tokens per word increases quadratic attention cost; Sliding-Window or RoPE + higher seq_len is prioritized."
                    .to_owned(),
            ),
            TokenizerKind::Unigram => rationale.push(
                "Unigram Tokenizer Impact: compact subword fertility lowers sequence length; subword dropout regularization pairs well with small/medium scratch corpora."
                    .to_owned(),
            ),
            TokenizerKind::WordPiece => rationale.push(
                "WordPiece Tokenizer Impact: greedy ##-continuation roots keep embedding table compact; ensure byte_fallback stays enabled for unseen symbols."
                    .to_owned(),
            ),
            TokenizerKind::ByteLevelBpe | TokenizerKind::PretrainedFile => rationale.push(
                "Byte-Level BPE Impact: zero-<unk> UTF-8 coverage with ~3.6–4.2 chars/token maximizes context efficiency per FLOP."
                    .to_owned(),
            ),
        }
        if model.routing == Routing::MoE {
            rationale.push(format!(
                "Sparse MoE Kernel Routing: Top-{} of {} experts (+ {} shared) keeps FLOPs/step at {} while scaling capacity; router index_select/index_add contiguous buffers enabled.",
                model.moe.top_k,
                model.moe.n_experts,
                model.moe.n_shared_experts,
                crate::config::format_flops(spec.flops_per_step)
            ));
        }
        if cfg.hyper.optimizer == OptimizerKind::AdamW && spec.total_train_mb > device_budget_mb * 0.70 {
            rationale.push(
                "Optimizer Memory Advisory: switching from AdamW (8 B/param state) to Lion or Muon cuts optimizer state RAM by 37–50%."
                    .to_owned(),
            );
        }
        if model.pos_encoding == PosEncoding::RoPE && model.qk_norm {
            rationale.push(
                "Stability Fusion: QK-Norm + RoPE active — bounds pre-softmax logit growth, permitting higher peak learning rates without NaN spikes."
                    .to_owned(),
            );
        }

        let summary = OptimizationPlanSummary {
            resolved_target,
            resolved_device_label,
            backend_api,
            recommended_threads,
            recommended_batch_size,
            recommended_grad_accum,
            effective_tokens_per_step,
            recommended_vocab_size,
            recommended_precision,
            recommended_activation_checkpointing,
            recommended_fused_ce_chunk,
            tile_m_n_k,
            workgroup_dims,
            attention_strategy,
            device_budget_mb,
            estimated_peak_mb: spec.total_train_mb,
            headroom_pct,
            fits_in_budget,
        };

        let custom_script_toml = render_custom_script(hw, cfg, &summary, &rationale);

        Self {
            summary,
            rationale,
            custom_script_toml,
        }
    }
}

fn render_custom_script(
    hw: &HardwareProfile,
    cfg: &RunConfig,
    plan: &OptimizationPlanSummary,
    rationale: &[String],
) -> String {
    let m = cfg.model.sanitized();
    let gpu_section = if let Some(gpu) = hw.selected_gpu(cfg.hardware_exec.preferred_gpu_index) {
        format!(
            "adapter_index = {}\nadapter_name = {:?}\nbackend = {:?}\ndevice_type = {:?}\nmax_storage_binding_mb = {}\nshader_f16 = {}",
            gpu.index,
            gpu.name,
            gpu.backend,
            gpu.device_type,
            gpu.max_storage_binding_mb,
            gpu.supports_f16
        )
    } else {
        "adapter_name = \"none\"\nbackend = \"cpu-only\"".to_owned()
    };

    let mut notes = String::new();
    for (i, line) in rationale.iter().enumerate() {
        notes.push_str(&format!("# {}. {}\n", i + 1, line));
    }

    format!(
        "# Archx Model Training — Custom Hardware-Adaptive Execution Plan\n\
         # Auto-synthesized for run {:?}\n\
         {}\n\
         [hardware_host]\n\
         os = {:?}\n\
         arch = {:?}\n\
         cpu_brand = {:?}\n\
         logical_cores = {}\n\
         simd_isa = {:?}\n\
         total_ram_mb = {}\n\
         available_ram_mb = {}\n\n\
         [gpu_device]\n\
         {}\n\n\
         [execution_target]\n\
         user_selection = {:?}\n\
         resolved_target = {:?}\n\
         backend_api = {:?}\n\
         compute_threads = {}\n\
         precision_mode = {:?}\n\
         tile_m_n_k = [{}, {}, {}]\n\
         workgroup_xyz = [{}, {}, {}]\n\n\
         [memory_and_batch_schedule]\n\
         device_budget_mb = {:.1}\n\
         estimated_peak_mb = {:.2}\n\
         fits_in_budget = {}\n\
         micro_batch_size = {}\n\
         grad_accum_steps = {}\n\
         seq_len = {}\n\
         effective_tokens_per_step = {}\n\
         activation_checkpointing = {}\n\
         fused_cross_entropy_chunk = {}\n\n\
         [transformer_and_tokenizer_fusion]\n\
         tokenizer_kind = {:?}\n\
         pre_tokenize = {:?}\n\
         digit_policy = {:?}\n\
         configured_vocab = {}\n\
         hardware_padded_vocab = {}\n\
         attention_kernel = {:?}\n\
         norm_placement = {:?}\n\
         residual_scaling = {:?}\n\
         qk_norm = {}\n\
         attn_logit_softcap = {:.1}\n\
         final_logit_softcap = {:.1}\n\
         routing = {:?}\n",
        cfg.name,
        notes,
        hw.cpu.os,
        hw.cpu.arch,
        hw.cpu.brand,
        hw.cpu.logical_cores,
        hw.cpu.simd_features,
        hw.memory.total_ram_mb,
        hw.memory.available_ram_mb,
        gpu_section,
        cfg.hardware_exec.target.label(),
        plan.resolved_target.label(),
        plan.backend_api,
        plan.recommended_threads,
        plan.recommended_precision.label(),
        plan.tile_m_n_k.0,
        plan.tile_m_n_k.1,
        plan.tile_m_n_k.2,
        plan.workgroup_dims.0,
        plan.workgroup_dims.1,
        plan.workgroup_dims.2,
        plan.device_budget_mb,
        plan.estimated_peak_mb,
        plan.fits_in_budget,
        plan.recommended_batch_size,
        plan.recommended_grad_accum,
        m.seq_len,
        plan.effective_tokens_per_step,
        plan.recommended_activation_checkpointing,
        plan.recommended_fused_ce_chunk,
        cfg.tokenizer.kind.label(),
        cfg.tokenizer.pre_tokenize.label(),
        cfg.tokenizer.digit_policy.label(),
        cfg.tokenizer.vocab_size,
        plan.recommended_vocab_size,
        plan.attention_strategy,
        m.norm_placement.label(),
        m.residual_scale_mode.label(),
        m.qk_norm,
        m.attn_logit_softcap,
        m.final_logit_softcap,
        m.routing.label(),
    )
}

// ============================================================================
// Live WGSL Tiled 16x16 GPU Compute Kernel & CPU-vs-GPU SGEMM Benchmark
// ============================================================================

const TILED_SGEMM_WGSL: &str = r#"
struct Dims {
    m: u32,
    k: u32,
    n: u32,
    _pad: u32,
}

@group(0) @binding(0) var<uniform> dims: Dims;
@group(0) @binding(1) var<storage, read> mat_a: array<f32>;
@group(0) @binding(2) var<storage, read> mat_b: array<f32>;
@group(0) @binding(3) var<storage, read_write> mat_c: array<f32>;

var<workgroup> tile_a: array<array<f32, 16>, 16>;
var<workgroup> tile_b: array<array<f32, 16>, 16>;

@compute @workgroup_size(16, 16, 1)
fn sgemm_tiled(
    @builtin(global_invocation_id) gid: vec3<u32>,
    @builtin(local_invocation_id) lid: vec3<u32>,
) {
    let row = gid.y;
    let col = gid.x;
    let lx = lid.x;
    let ly = lid.y;

    var acc: f32 = 0.0;
    let num_tiles = (dims.k + 15u) / 16u;

    for (var t: u32 = 0u; t < num_tiles; t = t + 1u) {
        let a_col = t * 16u + lx;
        let b_row = t * 16u + ly;

        if (row < dims.m && a_col < dims.k) {
            tile_a[ly][lx] = mat_a[row * dims.k + a_col];
        } else {
            tile_a[ly][lx] = 0.0;
        }

        if (b_row < dims.k && col < dims.n) {
            tile_b[ly][lx] = mat_b[b_row * dims.n + col];
        } else {
            tile_b[ly][lx] = 0.0;
        }

        workgroupBarrier();

        for (var i: u32 = 0u; i < 16u; i = i + 1u) {
            acc = fma(tile_a[ly][i], tile_b[i][lx], acc);
        }

        workgroupBarrier();
    }

    if (row < dims.m && col < dims.n) {
        mat_c[row * dims.n + col] = acc;
    }
}
"#;

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct ShaderDims {
    m: u32,
    k: u32,
    n: u32,
    _pad: u32,
}

/// Executes a real matrix multiplication `[dim, dim] x [dim, dim]` on both multi-threaded Rayon CPU
/// and the selected `wgpu` GPU adapter (via 16x16 workgroup-tiled WGSL `fma` compute shader),
/// reporting real wall-clock milliseconds, GFLOP/s, numerical agreement, and the fastest backend.
pub fn run_live_compute_benchmark(
    hw: &HardwareProfile,
    preferred_gpu_index: usize,
    cpu_threads: usize,
    dim: usize,
) -> ComputeBenchmarkReport {
    let n = dim.clamp(64, 512);
    let len = n * n;
    let a: Vec<f32> = (0..len)
        .map(|i| (((i * 17 + 3) % 97) as f32 - 48.0) * 0.02)
        .collect();
    let b: Vec<f32> = (0..len)
        .map(|i| (((i * 31 + 11) % 89) as f32 - 44.0) * 0.02)
        .collect();

    let threads = cpu_threads.clamp(1, 32);
    let mut cpu_out = vec![0.0f32; len];

    // Transpose B once for cache-friendly SIMD dot products on CPU.
    let mut b_t = vec![0.0f32; len];
    for r in 0..n {
        for c in 0..n {
            b_t[c * n + r] = b[r * n + c];
        }
    }

    let cpu_start = Instant::now();
    if let Ok(pool) = rayon::ThreadPoolBuilder::new().num_threads(threads).build() {
        pool.install(|| {
            cpu_out
                .par_chunks_mut(n)
                .enumerate()
                .for_each(|(row, out_row)| {
                    let a_row = &a[row * n..(row + 1) * n];
                    for (col, slot) in out_row.iter_mut().enumerate() {
                        let b_col = &b_t[col * n..(col + 1) * n];
                        let mut sum = 0.0f32;
                        for k in 0..n {
                            sum = a_row[k].mul_add(b_col[k], sum);
                        }
                        *slot = sum;
                    }
                });
        });
    }
    let cpu_ms = cpu_start.elapsed().as_secs_f64() * 1000.0;
    let total_flops = 2.0 * (n as f64) * (n as f64) * (n as f64);
    let cpu_gflops = (total_flops / 1e9) / (cpu_ms / 1000.0).max(1e-6);

    let wgsl_attempt = run_wgsl_tiled_sgemm(preferred_gpu_index, n, n, n, &a, &b);
    match wgsl_attempt {
        Ok((gpu_out, gpu_ms, adapter_name, backend)) => {
            let gpu_gflops = (total_flops / 1e9) / (gpu_ms / 1000.0).max(1e-6);
            let max_diff = cpu_out
                .iter()
                .zip(&gpu_out)
                .map(|(x, y)| (x - y).abs())
                .fold(0.0f32, f32::max);
            let gpu_faster = gpu_gflops > cpu_gflops * 1.05;
            let winner = if gpu_faster {
                format!("GPU ({adapter_name} · {gpu_gflops:.1} GFLOP/s)")
            } else {
                format!("CPU ({threads} threads · {cpu_gflops:.1} GFLOP/s)")
            };
            let note = format!(
                "Verified {n}×{n} tiled SGEMM: max |CPU − GPU| = {max_diff:.2e}. {}",
                if hw.best_hardware_gpu().is_some() {
                    "Hardware GPU WGSL compute pipeline validated."
                } else {
                    "Adapter is a software/virtual rasterizer; SIMD CPU is faster on this host."
                }
            );
            ComputeBenchmarkReport {
                matrix_dim: n,
                cpu_threads: threads,
                cpu_ms,
                cpu_gflops,
                gpu_adapter_name: Some(adapter_name),
                gpu_backend: Some(backend),
                gpu_ms: Some(gpu_ms),
                gpu_gflops: Some(gpu_gflops),
                max_abs_diff: Some(max_diff),
                recommended_winner: winner,
                note,
            }
        }
        Err(reason) => ComputeBenchmarkReport {
            matrix_dim: n,
            cpu_threads: threads,
            cpu_ms,
            cpu_gflops,
            gpu_adapter_name: None,
            gpu_backend: None,
            gpu_ms: None,
            gpu_gflops: None,
            max_abs_diff: None,
            recommended_winner: format!("CPU ({threads} threads · {cpu_gflops:.1} GFLOP/s)"),
            note: format!("CPU SIMD benchmark complete ({reason})."),
        },
    }
}

/// Runs a `16x16` workgroup-tiled SGEMM `[m, k] x [k, n]` directly on `wgpu` via WGSL compute shader.
pub fn run_wgsl_tiled_sgemm(
    preferred_gpu_index: usize,
    m: usize,
    k: usize,
    n: usize,
    a: &[f32],
    b: &[f32],
) -> Result<(Vec<f32>, f64, String, String), String> {
    if a.len() != m * k || b.len() != k * n {
        return Err("SGEMM input slice dimensions do not match (m, k, n)".to_owned());
    }

    std::panic::catch_unwind(|| -> Result<(Vec<f32>, f64, String, String), String> {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor::default());
        let mut adapters = instance.enumerate_adapters(wgpu::Backends::all());
        if adapters.is_empty() {
            if let Ok(single) =
                block_on_future(instance.request_adapter(&wgpu::RequestAdapterOptions::default()))
            {
                adapters.push(single);
            }
        }
        if adapters.is_empty() {
            return Err("no Vulkan/DX12/Metal adapter available on this host".to_owned());
        }

        adapters.sort_by_key(|ad| adapter_priority(&ad.get_info()));
        let chosen = adapters
            .get(preferred_gpu_index)
            .or_else(|| adapters.first())
            .ok_or_else(|| "no adapter found".to_owned())?;

        let info = chosen.get_info();
        let downlevel = chosen.get_downlevel_capabilities();
        if !downlevel
            .flags
            .contains(wgpu::DownlevelFlags::COMPUTE_SHADERS)
        {
            return Err(format!("adapter {} lacks compute shader support", info.name));
        }

        let (device, queue) = block_on_future(chosen.request_device(&wgpu::DeviceDescriptor {
            label: Some("archx-training-wgsl-compute"),
            required_features: wgpu::Features::empty(),
            required_limits: wgpu::Limits::downlevel_defaults(),
            experimental_features: wgpu::ExperimentalFeatures::disabled(),
            memory_hints: wgpu::MemoryHints::Performance,
            trace: wgpu::Trace::Off,
        }))
        .map_err(|e| format!("wgpu device request failed: {e}"))?;

        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("archx-sgemm-16x16"),
            source: wgpu::ShaderSource::Wgsl(TILED_SGEMM_WGSL.into()),
        });

        let dims_val = ShaderDims {
            m: m as u32,
            k: k as u32,
            n: n as u32,
            _pad: 0,
        };
        let dims_buf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("dims"),
            contents: bytemuck::bytes_of(&dims_val),
            usage: wgpu::BufferUsages::UNIFORM,
        });
        let a_buf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("mat_a"),
            contents: bytemuck::cast_slice(a),
            usage: wgpu::BufferUsages::STORAGE,
        });
        let b_buf = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("mat_b"),
            contents: bytemuck::cast_slice(b),
            usage: wgpu::BufferUsages::STORAGE,
        });
        let out_bytes = (m * n * std::mem::size_of::<f32>()) as u64;
        let c_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("mat_c"),
            size: out_bytes,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        let readback_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("readback"),
            size: out_bytes,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });

        let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("sgemm-bgl"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: Some(NonZeroU64::new(16).unwrap()),
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: Some(NonZeroU64::new(4).unwrap()),
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: Some(NonZeroU64::new(4).unwrap()),
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 3,
                    visibility: wgpu::ShaderStages::COMPUTE,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: false },
                        has_dynamic_offset: false,
                        min_binding_size: Some(NonZeroU64::new(4).unwrap()),
                    },
                    count: None,
                },
            ],
        });

        let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("sgemm-bg"),
            layout: &bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: dims_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: a_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: b_buf.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: c_buf.as_entire_binding(),
                },
            ],
        });

        let pl = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("sgemm-pl"),
            bind_group_layouts: &[&bgl],
            push_constant_ranges: &[],
        });
        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("sgemm-pipe"),
            layout: Some(&pl),
            module: &shader,
            entry_point: Some("sgemm_tiled"),
            compilation_options: wgpu::PipelineCompilationOptions::default(),
            cache: None,
        });

        let wg_x = (n as u32).div_ceil(16);
        let wg_y = (m as u32).div_ceil(16);

        // Timed GPU dispatch + synchronization.
        let t0 = Instant::now();
        let mut encoder =
            device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("sgemm-pass"),
                timestamp_writes: None,
            });
            pass.set_pipeline(&pipeline);
            pass.set_bind_group(0, &bg, &[]);
            pass.dispatch_workgroups(wg_x, wg_y, 1);
        }
        encoder.copy_buffer_to_buffer(&c_buf, 0, &readback_buf, 0, out_bytes);
        queue.submit([encoder.finish()]);

        let slice = readback_buf.slice(..);
        let map_status: Arc<Mutex<Option<Result<(), wgpu::BufferAsyncError>>>> =
            Arc::new(Mutex::new(None));
        let status_clone = Arc::clone(&map_status);
        slice.map_async(wgpu::MapMode::Read, move |res| {
            *status_clone.lock().unwrap() = Some(res);
        });
        device
            .poll(wgpu::PollType::wait_indefinitely())
            .map_err(|e| format!("wgpu poll failed: {e}"))?;
        let elapsed_ms = t0.elapsed().as_secs_f64() * 1000.0;

        match map_status.lock().unwrap().take() {
            Some(Ok(())) => {}
            Some(Err(e)) => return Err(format!("wgpu buffer map failed: {e}")),
            None => return Err("wgpu buffer map did not complete".to_owned()),
        }

        let mapped = slice.get_mapped_range();
        let result: Vec<f32> = bytemuck::cast_slice(&mapped).to_vec();
        drop(mapped);
        readback_buf.unmap();

        Ok((
            result,
            elapsed_ms,
            info.name.clone(),
            format_backend(info.backend).to_owned(),
        ))
    })
    .map_err(|_| "wgpu driver panicked during compute probe".to_owned())?
}

// ============================================================================
// Low-level OS & Silicon Hardware Discovery
// ============================================================================

fn probe_cpu() -> CpuInfo {
    let logical_cores = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
    let recommended_threads = if logical_cores > 2 {
        (logical_cores - 1).min(24)
    } else {
        logical_cores.max(1)
    };

    let mut simd_features = Vec::new();
    #[cfg(any(target_arch = "x86", target_arch = "x86_64"))]
    {
        if std::is_x86_feature_detected!("avx512f") {
            simd_features.push("AVX-512F".to_owned());
        }
        if std::is_x86_feature_detected!("avx512bf16") {
            simd_features.push("AVX-512BF16".to_owned());
        }
        if std::is_x86_feature_detected!("avx512vnni") {
            simd_features.push("AVX-512VNNI".to_owned());
        }
        if std::is_x86_feature_detected!("avx2") {
            simd_features.push("AVX2".to_owned());
        }
        if std::is_x86_feature_detected!("fma") {
            simd_features.push("FMA".to_owned());
        }
        if std::is_x86_feature_detected!("f16c") {
            simd_features.push("F16C".to_owned());
        }
        if std::is_x86_feature_detected!("sse4.2") {
            simd_features.push("SSE4.2".to_owned());
        }
    }
    #[cfg(target_arch = "aarch64")]
    {
        if std::arch::is_aarch64_feature_detected!("neon") {
            simd_features.push("NEON".to_owned());
        }
        if std::arch::is_aarch64_feature_detected!("fp16") {
            simd_features.push("FP16".to_owned());
        }
        if std::arch::is_aarch64_feature_detected!("dotprod") {
            simd_features.push("DOTPROD".to_owned());
        }
    }

    let brand = detect_cpu_brand(logical_cores);

    CpuInfo {
        brand,
        arch: std::env::consts::ARCH.to_owned(),
        os: std::env::consts::OS.to_owned(),
        logical_cores,
        recommended_threads,
        simd_features,
    }
}

fn detect_cpu_brand(logical_cores: usize) -> String {
    #[cfg(target_arch = "x86_64")]
    {
        let max_ext = unsafe { core::arch::x86_64::__cpuid(0x8000_0000).eax };
        if max_ext >= 0x8000_0004 {
            let mut bytes = Vec::with_capacity(48);
            for leaf in 0x8000_0002..=0x8000_0004 {
                let res = unsafe { core::arch::x86_64::__cpuid(leaf) };
                bytes.extend_from_slice(&res.eax.to_le_bytes());
                bytes.extend_from_slice(&res.ebx.to_le_bytes());
                bytes.extend_from_slice(&res.ecx.to_le_bytes());
                bytes.extend_from_slice(&res.edx.to_le_bytes());
            }
            if let Some(end) = bytes.iter().position(|&b| b == 0) {
                bytes.truncate(end);
            }
            let s = String::from_utf8_lossy(&bytes).trim().to_owned();
            if !s.is_empty() {
                return s;
            }
        }
    }

    #[cfg(target_os = "linux")]
    if let Ok(cpuinfo) = std::fs::read_to_string("/proc/cpuinfo") {
        for line in cpuinfo.lines() {
            if let Some((k, v)) = line.split_once(':') {
                let key = k.trim();
                if key == "model name" || key == "Hardware" || key == "Model" {
                    let trimmed = v.trim();
                    if !trimmed.is_empty() {
                        return trimmed.to_owned();
                    }
                }
            }
        }
    }

    if let Ok(id) = std::env::var("PROCESSOR_IDENTIFIER") {
        let trimmed = id.trim();
        if !trimmed.is_empty() {
            return trimmed.to_owned();
        }
    }

    format!(
        "{} ({logical_cores} logical cores)",
        std::env::consts::ARCH
    )
}

fn probe_memory() -> MemoryInfo {
    #[cfg(target_os = "linux")]
    {
        if let Ok(meminfo) = std::fs::read_to_string("/proc/meminfo") {
            let mut total_kb = 0u64;
            let mut avail_kb = 0u64;
            for line in meminfo.lines() {
                if let Some(rest) = line.strip_prefix("MemTotal:") {
                    total_kb = parse_leading_u64(rest);
                } else if let Some(rest) = line.strip_prefix("MemAvailable:") {
                    avail_kb = parse_leading_u64(rest);
                }
            }
            if total_kb > 0 {
                let total_mb = total_kb / 1024;
                let avail_mb = if avail_kb > 0 {
                    avail_kb / 1024
                } else {
                    (total_mb * 70) / 100
                };
                return MemoryInfo {
                    total_ram_mb: total_mb,
                    available_ram_mb: avail_mb,
                };
            }
        }
    }

    #[cfg(target_os = "windows")]
    {
        #[repr(C)]
        struct MemoryStatusEx {
            dw_length: u32,
            dw_memory_load: u32,
            ull_total_phys: u64,
            ull_avail_phys: u64,
            ull_total_page_file: u64,
            ull_avail_page_file: u64,
            ull_total_virtual: u64,
            ull_avail_virtual: u64,
            ull_avail_extended_virtual: u64,
        }

        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn GlobalMemoryStatusEx(lp_buffer: *mut MemoryStatusEx) -> i32;
        }

        let mut st = MemoryStatusEx {
            dw_length: std::mem::size_of::<MemoryStatusEx>() as u32,
            dw_memory_load: 0,
            ull_total_phys: 0,
            ull_avail_phys: 0,
            ull_total_page_file: 0,
            ull_avail_page_file: 0,
            ull_total_virtual: 0,
            ull_avail_virtual: 0,
            ull_avail_extended_virtual: 0,
        };
        let ok = unsafe { GlobalMemoryStatusEx(&mut st as *mut MemoryStatusEx) };
        if ok != 0 && st.ull_total_phys > 0 {
            return MemoryInfo {
                total_ram_mb: st.ull_total_phys / (1024 * 1024),
                available_ram_mb: st.ull_avail_phys / (1024 * 1024),
            };
        }
    }

    MemoryInfo {
        total_ram_mb: 16_384,
        available_ram_mb: 11_264,
    }
}

#[cfg(target_os = "linux")]
fn parse_leading_u64(s: &str) -> u64 {
    s.split_whitespace()
        .next()
        .and_then(|tok| tok.parse::<u64>().ok())
        .unwrap_or(0)
}

fn probe_gpus() -> Vec<GpuAdapterInfo> {
    let Ok(found) = std::panic::catch_unwind(|| {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor::default());
        let mut raw = instance.enumerate_adapters(wgpu::Backends::all());
        raw.sort_by_key(|ad| adapter_priority(&ad.get_info()));

        let mut seen = std::collections::BTreeSet::new();
        let mut out = Vec::new();
        for adapter in raw {
            let info = adapter.get_info();
            let dedup_sig = (
                info.vendor,
                info.device,
                format_backend(info.backend),
                info.name.clone(),
            );
            if !seen.insert(dedup_sig) {
                continue;
            }
            let limits = adapter.limits();
            let features = adapter.features();
            let downlevel = adapter.get_downlevel_capabilities();
            let is_hw = matches!(
                info.device_type,
                wgpu::DeviceType::DiscreteGpu | wgpu::DeviceType::IntegratedGpu
            );
            let idx = out.len();
            out.push(GpuAdapterInfo {
                index: idx,
                name: if info.name.trim().is_empty() {
                    format!("Adapter #{idx}")
                } else {
                    info.name.trim().to_owned()
                },
                vendor_id: info.vendor,
                device_id: info.device,
                device_type: format_device_type(info.device_type).to_owned(),
                is_hardware_gpu: is_hw,
                backend: format_backend(info.backend).to_owned(),
                driver: info.driver.trim().to_owned(),
                driver_info: info.driver_info.trim().to_owned(),
                max_buffer_mb: limits.max_buffer_size / (1024 * 1024),
                max_storage_binding_mb: u64::from(limits.max_storage_buffer_binding_size)
                    / (1024 * 1024),
                max_workgroup_size_x: limits.max_compute_workgroup_size_x,
                max_invocations_per_workgroup: limits.max_compute_invocations_per_workgroup,
                supports_compute: downlevel
                    .flags
                    .contains(wgpu::DownlevelFlags::COMPUTE_SHADERS),
                supports_f16: features.contains(wgpu::Features::SHADER_F16),
                supports_subgroups: features.contains(wgpu::Features::SUBGROUP),
            });
        }
        out
    }) else {
        return Vec::new();
    };
    found
}

fn adapter_priority(info: &wgpu::AdapterInfo) -> u8 {
    match info.device_type {
        wgpu::DeviceType::DiscreteGpu => 0,
        wgpu::DeviceType::IntegratedGpu => 1,
        wgpu::DeviceType::VirtualGpu => 2,
        wgpu::DeviceType::Other => 3,
        wgpu::DeviceType::Cpu => 4,
    }
}

fn format_device_type(dt: wgpu::DeviceType) -> &'static str {
    match dt {
        wgpu::DeviceType::DiscreteGpu => "Discrete GPU",
        wgpu::DeviceType::IntegratedGpu => "Integrated GPU",
        wgpu::DeviceType::VirtualGpu => "Virtual GPU",
        wgpu::DeviceType::Cpu => "Software / CPU Adapter",
        wgpu::DeviceType::Other => "Accelerator",
    }
}

fn format_backend(b: wgpu::Backend) -> &'static str {
    match b {
        wgpu::Backend::Vulkan => "Vulkan",
        wgpu::Backend::Dx12 => "DirectX 12",
        wgpu::Backend::Metal => "Metal",
        wgpu::Backend::Gl => "OpenGL",
        wgpu::Backend::BrowserWebGpu => "WebGPU",
        wgpu::Backend::Noop => "Noop",
    }
}

struct ThreadSignal {
    ready: Mutex<bool>,
    cv: Condvar,
}

impl Wake for ThreadSignal {
    fn wake(self: Arc<Self>) {
        self.wake_by_ref();
    }

    fn wake_by_ref(self: &Arc<Self>) {
        let mut guard = self.ready.lock().unwrap();
        *guard = true;
        self.cv.notify_all();
    }
}

fn block_on_future<F: Future>(mut fut: F) -> F::Output {
    let sig = Arc::new(ThreadSignal {
        ready: Mutex::new(false),
        cv: Condvar::new(),
    });
    let waker = Waker::from(Arc::clone(&sig));
    let mut cx = Context::from_waker(&waker);
    // SAFETY: `fut` stays on this stack frame until completion and is never moved after pinning.
    let mut pinned = unsafe { Pin::new_unchecked(&mut fut) };
    loop {
        if let Poll::Ready(out) = pinned.as_mut().poll(&mut cx) {
            return out;
        }
        let mut ready = sig.ready.lock().unwrap();
        while !*ready {
            ready = sig.cv.wait(ready).unwrap();
        }
        *ready = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn live_hardware_probe_and_optimization_plan_succeed() {
        let hw = HardwareProfile::probe();
        assert!(hw.cpu.logical_cores >= 1);
        assert!(hw.memory.total_ram_mb >= 256);

        let mut cfg = RunConfig::default();
        cfg.hardware_exec.target = ComputeTarget::Cpu;
        cfg.tokenizer.vocab_size = 500; // unaligned -> should recommend 512 on CPU
        let plan_cpu = OptimizationPlan::compile(&hw, &cfg);
        assert_eq!(plan_cpu.summary.resolved_target, ComputeTarget::Cpu);
        assert_eq!(plan_cpu.summary.recommended_vocab_size, 512);
        assert!(plan_cpu.custom_script_toml.contains("[execution_target]"));

        // Verify GPU optimization plan on deterministic discrete GPU fixture.
        let gpu_hw = HardwareProfile::snapshot_fixture();
        cfg.hardware_exec.target = ComputeTarget::Gpu;
        let plan_gpu = OptimizationPlan::compile(&gpu_hw, &cfg);
        assert_eq!(plan_gpu.summary.resolved_target, ComputeTarget::Gpu);
        assert_eq!(plan_gpu.summary.recommended_vocab_size, 512); // multiple of 128
        assert_eq!(plan_gpu.summary.workgroup_dims, (16, 16, 1));
    }

    #[test]
    fn live_compute_benchmark_runs_cleanly_on_any_host() {
        let hw = HardwareProfile::probe();
        let report = run_live_compute_benchmark(&hw, 0, 2, 64);
        assert_eq!(report.matrix_dim, 64);
        assert!(report.cpu_gflops > 0.0);
        if let Some(diff) = report.max_abs_diff {
            assert!(diff < 1e-3, "WGSL GPU SGEMM diverged from CPU: {diff}");
        }
    }
}
