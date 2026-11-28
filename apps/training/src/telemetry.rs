//! Purpose: Implements atomic-gated neural telemetry (`Off` = 0% overhead) for layer norms, dead-unit detection, 16×16 heatmaps, and MoE router load.

use candle_core::{Tensor, backprop::GradStore};
use candle_nn::VarMap;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TelemetryMode {
    Off = 0,
    Every25 = 1,
    Every10 = 2,
    OnPauseOnly = 3,
}

impl TelemetryMode {
    pub const ALL: [Self; 4] = [Self::Off, Self::Every25, Self::Every10, Self::OnPauseOnly];

    pub fn from_u8(v: u8) -> Self {
        match v {
            1 => Self::Every25,
            2 => Self::Every10,
            3 => Self::OnPauseOnly,
            _ => Self::Off,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Off => "Off · 0% overhead",
            Self::Every25 => "Sample every 25 steps · <1%",
            Self::Every10 => "Sample every 10 steps · ~1%",
            Self::OnPauseOnly => "Snapshot on pause only",
        }
    }

    pub fn badge(self) -> &'static str {
        match self {
            Self::Off => "0% COST",
            Self::Every25 => "<1% SAMPLED",
            Self::Every10 => "~1% SAMPLED",
            Self::OnPauseOnly => "ON PAUSE",
        }
    }

    pub fn should_sample(self, step: usize, forced: bool) -> bool {
        if forced {
            return true;
        }
        match self {
            Self::Off | Self::OnPauseOnly => false,
            Self::Every25 => step == 1 || step % 25 == 0,
            Self::Every10 => step == 1 || step % 10 == 0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum HealthState {
    Healthy,
    Quiet,
    Hot,
}

impl HealthState {
    pub fn label(self) -> &'static str {
        match self {
            Self::Healthy => "healthy",
            Self::Quiet => "low grad",
            Self::Hot => "high norm",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LayerHealth {
    pub label: String,
    pub weight_l2: f32,
    pub grad_l2: f32,
    pub abs_mean: f32,
    pub std_dev: f32,
    pub near_zero_pct: f32,
    pub state: HealthState,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct NeuralSnapshot {
    pub step: usize,
    pub inspected_layer: usize,
    pub inspected_matrix_name: String,
    pub layers: Vec<LayerHealth>,
    /// 16×16 row-major normalized values in `[-1.0, 1.0]`.
    pub weight_tile: Vec<f32>,
    pub weight_peak: f32,
    /// 16×16 row-major normalized gradient values in `[-1.0, 1.0]`.
    pub grad_tile: Vec<f32>,
    pub grad_peak: f32,
    /// Percentage of routed tokens handled by each expert (sums to ~100%).
    pub expert_load_pct: Vec<f32>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct StepPoint {
    pub step: usize,
    pub train_loss: f32,
    pub val_loss: Option<f32>,
    pub perplexity: f32,
    pub lr: f64,
    pub grad_norm: f32,
    pub tokens_per_sec: f32,
}

pub fn capture_neural_snapshot(
    varmap: &VarMap,
    grads: Option<&GradStore>,
    n_layers: usize,
    inspected_layer: usize,
    expert_counts: &[usize],
    step: usize,
) -> NeuralSnapshot {
    let map = varmap.data().lock().unwrap();
    let target_layer = inspected_layer.min(n_layers.saturating_sub(1));

    let mut groups: Vec<(String, String)> = Vec::with_capacity(n_layers + 2);
    groups.push(("Embeddings".to_owned(), "tok_embeddings.".to_owned()));
    for l in 0..n_layers {
        groups.push((format!("Layer {l:02}"), format!("layers.{l}.")));
    }
    groups.push(("Output Head".to_owned(), "final_norm.".to_owned()));

    let mut layers = Vec::with_capacity(groups.len());
    for (label, prefix) in &groups {
        let mut w_sq = 0.0f64;
        let mut g_sq = 0.0f64;
        let mut abs_sum = 0.0f64;
        let mut sum = 0.0f64;
        let mut count = 0usize;
        let mut near_zero = 0usize;

        for (name, var) in map.iter() {
            let matches_group = name.starts_with(prefix)
                || (prefix == "final_norm." && name.starts_with("lm_head."));
            if !matches_group {
                continue;
            }
            if let Ok(vals) = var.as_tensor().flatten_all().and_then(|t| t.to_vec1::<f32>()) {
                for &v in &vals {
                    let vf = f64::from(v);
                    w_sq += vf * vf;
                    abs_sum += vf.abs();
                    sum += vf;
                    if v.abs() < 1e-4 {
                        near_zero += 1;
                    }
                }
                count += vals.len();
            }
            if let Some(gs) = grads {
                if let Some(gt) = gs.get(var) {
                    if let Ok(g_scalar) = gt.sqr().and_then(|s| s.sum_all()).and_then(|s| s.to_scalar::<f32>()) {
                        g_sq += f64::from(g_scalar);
                    }
                }
            }
        }

        let denom = count.max(1) as f64;
        let mean = sum / denom;
        let variance = ((w_sq / denom) - mean * mean).max(0.0);
        let weight_l2 = w_sq.sqrt() as f32;
        let grad_l2 = g_sq.sqrt() as f32;
        let state = if grad_l2 > 5.0 || !grad_l2.is_finite() {
            HealthState::Hot
        } else if grads.is_some() && grad_l2 < 1e-5 {
            HealthState::Quiet
        } else {
            HealthState::Healthy
        };

        layers.push(LayerHealth {
            label: label.clone(),
            weight_l2,
            grad_l2,
            abs_mean: (abs_sum / denom) as f32,
            std_dev: variance.sqrt() as f32,
            near_zero_pct: (near_zero as f32 * 100.0) / (count.max(1) as f32),
            state,
        });
    }

    let preferred = [
        format!("layers.{target_layer}.attn.wq.weight"),
        format!("layers.{target_layer}.mlp.w_up.weight"),
        format!("layers.{target_layer}.moe.router.weight"),
        "tok_embeddings.weight".to_owned(),
    ];
    let mut chosen_name = String::new();
    let mut weight_tile = vec![0.0f32; 256];
    let mut weight_peak = 0.0f32;
    let mut grad_tile = vec![0.0f32; 256];
    let mut grad_peak = 0.0f32;

    for cand in &preferred {
        if let Some(var) = map.get(cand) {
            chosen_name = cand.clone();
            let (wt, wp) = downsample_16x16(var.as_tensor());
            weight_tile = wt;
            weight_peak = wp;
            if let Some(gs) = grads {
                if let Some(gt) = gs.get(var) {
                    let (grt, grp) = downsample_16x16(gt);
                    grad_tile = grt;
                    grad_peak = grp;
                }
            }
            break;
        }
    }

    let total_routed: usize = expert_counts.iter().sum();
    let expert_load_pct = if total_routed > 0 {
        expert_counts
            .iter()
            .map(|&c| (c as f32 * 100.0) / total_routed as f32)
            .collect()
    } else {
        Vec::new()
    };

    NeuralSnapshot {
        step,
        inspected_layer: target_layer,
        inspected_matrix_name: chosen_name,
        layers,
        weight_tile,
        weight_peak,
        grad_tile,
        grad_peak,
        expert_load_pct,
    }
}

fn downsample_16x16(t: &Tensor) -> (Vec<f32>, f32) {
    let dims = t.dims();
    if dims.len() < 2 {
        return (vec![0.0; 256], 0.0);
    }
    let rows = dims[0].max(1);
    let cols = dims[1].max(1);
    let Ok(flat) = t.flatten_all().and_then(|f| f.to_vec1::<f32>()) else {
        return (vec![0.0; 256], 0.0);
    };
    if flat.len() < rows * cols {
        return (vec![0.0; 256], 0.0);
    }

    let mut tile = Vec::with_capacity(256);
    let mut peak = 0.0f32;
    for r in 0..16 {
        let r0 = (r * rows) / 16;
        let r1 = (((r + 1) * rows) / 16).max(r0 + 1).min(rows);
        for c in 0..16 {
            let c0 = (c * cols) / 16;
            let c1 = (((c + 1) * cols) / 16).max(c0 + 1).min(cols);
            let mut sum = 0.0f32;
            let mut n = 0usize;
            for rr in r0..r1 {
                for cc in c0..c1 {
                    sum += flat[rr * cols + cc];
                    n += 1;
                }
            }
            let avg = sum / (n.max(1) as f32);
            peak = peak.max(avg.abs());
            tile.push(avg);
        }
    }

    let norm = peak.max(1e-7);
    for v in &mut tile {
        *v = (*v / norm).clamp(-1.0, 1.0);
    }
    (tile, peak)
}
