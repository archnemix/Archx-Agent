//! Purpose: Implements native Rust optimizers (`AdamW`, `Muon`, `Lion`, `SGD + Nesterov`), true memory-saving per-micro-step gradient accumulation, global gradient clipping, and learning-rate schedules.

use std::f64::consts::PI;

use candle_core::{DType, Result as CandleResult, Tensor, Var, backprop::GradStore};
use candle_nn::VarMap;

use crate::config::{Hyperparams, LrSchedule, OptimizerKind, PrecisionMode};

struct TrackedParam {
    name: String,
    var: Var,
    is_muon_2d: bool,
    no_decay: bool,
    m: Tensor,
    v: Option<Tensor>,
    grad_acc: Option<Tensor>,
}

/// Unified optimizer operating on named `VarMap` variables with true per-micro-step
/// gradient accumulation (freeing forward activation graphs after each micro-batch).
pub struct StepOptimizer {
    kind: OptimizerKind,
    params: Vec<TrackedParam>,
    step_num: usize,
    beta1: f64,
    beta2: f64,
    weight_decay: f64,
    eps: f64,
}

impl StepOptimizer {
    pub fn new(varmap: &VarMap, hyper: &Hyperparams) -> CandleResult<Self> {
        let map = varmap.data().lock().unwrap();
        let mut names: Vec<String> = map.keys().cloned().collect();
        names.sort();

        let mut params = Vec::with_capacity(names.len());
        for name in names {
            let var = map[&name].clone();
            if !var.dtype().is_float() {
                continue;
            }
            let dims = var.dims();
            let is_hidden_layer =
                name.starts_with("layers.") && !name.contains("norm") && !name.ends_with(".bias");
            let is_muon_2d =
                hyper.optimizer == OptimizerKind::Muon && dims.len() == 2 && is_hidden_layer;
            let no_decay = dims.len() < 2 || name.contains("norm") || name.ends_with(".bias");

            let m = Tensor::zeros(dims, DType::F32, var.device())?;
            let v = if matches!(hyper.optimizer, OptimizerKind::AdamW)
                || (hyper.optimizer == OptimizerKind::Muon && !is_muon_2d)
            {
                Some(Tensor::zeros(dims, DType::F32, var.device())?)
            } else {
                None
            };
            params.push(TrackedParam {
                name,
                var,
                is_muon_2d,
                no_decay,
                m,
                v,
                grad_acc: None,
            });
        }

        Ok(Self {
            kind: hyper.optimizer,
            params,
            step_num: 0,
            beta1: hyper.beta1.clamp(0.5, 0.999),
            beta2: hyper.beta2.clamp(0.8, 0.9999),
            weight_decay: hyper.weight_decay.max(0.0),
            eps: 1e-8,
        })
    }

    /// Clears all accumulated micro-batch gradients before starting a new optimizer step.
    pub fn zero_accum(&mut self) {
        for p in &mut self.params {
            p.grad_acc = None;
        }
    }

    /// Accumulates gradients from one micro-batch (`scaled_loss.backward()`) so the caller
    /// can drop the micro-batch forward activation graph immediately after this call.
    pub fn accumulate_grads(&mut self, grads: &GradStore) -> CandleResult<()> {
        for p in &mut self.params {
            if let Some(g) = grads.get(&p.var) {
                let g_detached = g.detach();
                p.grad_acc = Some(match &p.grad_acc {
                    Some(prev) => (prev + &g_detached)?,
                    None => g_detached,
                });
            }
        }
        Ok(())
    }

    /// Applies one full optimization step using the gradients accumulated via `accumulate_grads`,
    /// then clears the gradient accumulator. Returns the global pre-clip L2 gradient norm.
    pub fn step_accumulated(&mut self, lr: f64, max_grad_norm: f32) -> CandleResult<f32> {
        let mut total_sq = 0.0f64;
        for p in &self.params {
            if let Some(g) = &p.grad_acc {
                let sq = g.sqr()?.sum_all()?.to_scalar::<f32>()? as f64;
                total_sq += sq;
            }
        }
        let grad_norm = total_sq.sqrt() as f32;
        if !grad_norm.is_finite() {
            self.zero_accum();
            return Ok(grad_norm);
        }

        let clip_scale = if max_grad_norm > 0.0 && grad_norm > max_grad_norm {
            f64::from(max_grad_norm / (grad_norm + 1e-6))
        } else {
            1.0
        };

        self.step_num += 1;
        let t = self.step_num as i32;

        for p in &mut self.params {
            let Some(raw_g) = p.grad_acc.take() else {
                continue;
            };
            apply_single_param_update(
                self.kind,
                p,
                &raw_g,
                clip_scale,
                lr,
                t,
                self.beta1,
                self.beta2,
                self.weight_decay,
                self.eps,
            )?;
        }

        Ok(grad_norm)
    }

    /// Convenience single-shot step from a `GradStore` (equivalent to `zero_accum` + `accumulate_grads` + `step_accumulated`).
    pub fn step_with_grads(
        &mut self,
        grads: &GradStore,
        lr: f64,
        max_grad_norm: f32,
    ) -> CandleResult<f32> {
        self.zero_accum();
        self.accumulate_grads(grads)?;
        self.step_accumulated(lr, max_grad_norm)
    }

    /// When mixed precision (`BF16` or `FP16` weights + `FP32` accumulator) is selected,
    /// projects hidden weights onto the target IEEE reduced-precision mantissa grid while
    /// keeping norms/embeddings and optimizer moments in full `FP32`.
    pub fn apply_mixed_precision_projection(&self, mode: PrecisionMode) -> CandleResult<()> {
        let low_dtype = match mode {
            PrecisionMode::Fp32Strict => return Ok(()),
            PrecisionMode::Bf16MixedPlan => DType::BF16,
            PrecisionMode::Fp16Wgsl => DType::F16,
        };
        for p in &self.params {
            if p.no_decay || !p.name.starts_with("layers.") {
                continue;
            }
            let quantized = p.var.as_tensor().to_dtype(low_dtype)?.to_dtype(DType::F32)?;
            p.var.set(&quantized)?;
        }
        Ok(())
    }
}

#[allow(clippy::too_many_arguments)]
fn apply_single_param_update(
    kind: OptimizerKind,
    p: &mut TrackedParam,
    raw_g: &Tensor,
    clip_scale: f64,
    lr: f64,
    t: i32,
    beta1: f64,
    beta2: f64,
    weight_decay: f64,
    eps: f64,
) -> CandleResult<()> {
    let g = if (clip_scale - 1.0).abs() > 1e-6 {
        (raw_g * clip_scale)?
    } else {
        raw_g.clone()
    };
    let wd = if p.no_decay { 0.0 } else { weight_decay };

    if p.is_muon_2d {
        let mu = beta1;
        p.m = ((&p.m * mu)? + &g)?;
        let nesterov = (&g + &(&p.m * mu)?)?;
        let orth = newton_schulz_orthogonalize(&nesterov, 5)?;
        let (rows, cols) = orth.dims2()?;
        let aspect_scale = (rows.max(cols) as f64 / rows.min(cols).max(1) as f64)
            .sqrt()
            .max(1.0);
        let muon_lr = lr * 3.0 * aspect_scale * 0.2;
        let decayed = if wd > 0.0 {
            (p.var.as_tensor() * (1.0 - lr * wd))?
        } else {
            p.var.as_tensor().clone()
        };
        p.var.set(&(&decayed - &(orth * muon_lr)?)?)?;
        return Ok(());
    }

    match kind {
        OptimizerKind::AdamW | OptimizerKind::Muon => {
            let v_ref = p.v.as_mut().expect("v allocated for AdamW");
            p.m = ((&p.m * beta1)? + &(&g * (1.0 - beta1))?)?;
            *v_ref = ((&*v_ref * beta2)? + &(&g.sqr()? * (1.0 - beta2))?)?;

            let bias1 = 1.0 - beta1.powi(t);
            let bias2 = 1.0 - beta2.powi(t);
            let m_hat = (&p.m / bias1)?;
            let v_hat = (&*v_ref / bias2)?;
            let step_dir = m_hat.broadcast_div(&(v_hat.sqrt()? + eps)?)?;

            let decayed = if wd > 0.0 {
                (p.var.as_tensor() * (1.0 - lr * wd))?
            } else {
                p.var.as_tensor().clone()
            };
            p.var.set(&(&decayed - &(step_dir * lr)?)?)?;
        }
        OptimizerKind::Lion => {
            let interp = ((&p.m * beta1)? + &(&g * (1.0 - beta1))?)?;
            let sign_t = tensor_sign(&interp)?;
            let lion_lr = lr * 0.3;
            let decayed = if wd > 0.0 {
                (p.var.as_tensor() * (1.0 - lion_lr * wd))?
            } else {
                p.var.as_tensor().clone()
            };
            p.var.set(&(&decayed - &(sign_t * lion_lr)?)?)?;
            p.m = ((&p.m * beta2)? + &(&g * (1.0 - beta2))?)?;
        }
        OptimizerKind::SgdNesterov => {
            let mu = beta1;
            let g_wd = if wd > 0.0 {
                (&g + &(p.var.as_tensor() * wd)?)?
            } else {
                g
            };
            p.m = ((&p.m * mu)? + &g_wd)?;
            let nesterov = (&g_wd + &(&p.m * mu)?)?;
            p.var.set(&(p.var.as_tensor() - &(nesterov * lr)?)?)?;
        }
    }
    let _ = &p.name;
    Ok(())
}

/// Computes Newton–Schulz quintic/cubic orthogonalization on a 2D gradient matrix.
fn newton_schulz_orthogonalize(g: &Tensor, steps: usize) -> CandleResult<Tensor> {
    let (r, c) = g.dims2()?;
    let transposed = r > c;
    let mut x = if transposed {
        g.t()?.contiguous()?
    } else {
        g.clone()
    };
    let frob = (x.sqr()?.sum_all()?.to_scalar::<f32>()?.sqrt() as f64) + 1e-7;
    x = (&x / frob)?;

    let (a, b, coef_c) = (3.4445f64, -4.7750f64, 2.0315f64);
    for _ in 0..steps {
        let xt = x.t()?.contiguous()?;
        let gram = x.matmul(&xt)?;
        let gram2 = gram.matmul(&gram)?;
        let comb = (&(&gram * b)? + &(&gram2 * coef_c)?)?;
        x = (&(&x * a)? + &comb.matmul(&x)?)?;
    }
    if transposed {
        x.t()?.contiguous()
    } else {
        Ok(x)
    }
}

fn tensor_sign(t: &Tensor) -> CandleResult<Tensor> {
    let vals = t.flatten_all()?.to_vec1::<f32>()?;
    let signed: Vec<f32> = vals
        .into_iter()
        .map(|v| {
            if v > 0.0 {
                1.0
            } else if v < 0.0 {
                -1.0
            } else {
                0.0
            }
        })
        .collect();
    Tensor::from_vec(signed, t.shape(), t.device())
}

/// Evaluates the learning rate for 1-based `step` under the configured schedule.
pub fn scheduled_lr(step: usize, hyper: &Hyperparams) -> f64 {
    let peak = hyper.lr.max(1e-8);
    let min_lr = peak * hyper.min_lr_ratio.clamp(0.0, 1.0);
    let total = hyper.total_steps.max(1);
    let warmup = hyper.warmup_steps.min(total.saturating_sub(1));

    if warmup > 0 && step <= warmup {
        return peak * (step as f64 / warmup as f64);
    }
    if step >= total {
        return match hyper.lr_schedule {
            LrSchedule::Constant => peak,
            _ => min_lr,
        };
    }

    let progress = (step.saturating_sub(warmup)) as f64 / (total - warmup).max(1) as f64;
    match hyper.lr_schedule {
        LrSchedule::Constant => peak,
        LrSchedule::Linear => peak + (min_lr - peak) * progress,
        LrSchedule::Cosine => {
            let cosine = 0.5 * (1.0 + (PI * progress).cos());
            min_lr + (peak - min_lr) * cosine
        }
        LrSchedule::Wsd => {
            if progress < 0.70 {
                peak
            } else {
                let decay_prog = (progress - 0.70) / 0.30;
                let cosine = 0.5 * (1.0 + (PI * decay_prog).cos());
                min_lr + (peak - min_lr) * cosine
            }
        }
        LrSchedule::InvSqrt => {
            let eff_w = warmup.max(8) as f64;
            (peak * (eff_w / (step as f64).max(eff_w)).sqrt()).max(min_lr)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use candle_core::Device;

    #[test]
    fn all_four_optimizers_reduce_quadratic_objective() {
        for kind in OptimizerKind::ALL {
            let vm = VarMap::new();
            {
                let mut map = vm.data().lock().unwrap();
                let t = Tensor::from_vec(vec![2.0f32, -3.0, 1.5, -1.0], (2, 2), &Device::Cpu)
                    .unwrap();
                map.insert("layers.0.mlp.w_up.weight".into(), Var::from_tensor(&t).unwrap());
            }
            let mut hyper = Hyperparams::default();
            hyper.optimizer = kind;
            hyper.lr = 0.08;
            let mut opt = StepOptimizer::new(&vm, &hyper).expect("opt");

            let initial = {
                let map = vm.data().lock().unwrap();
                map["layers.0.mlp.w_up.weight"]
                    .as_tensor()
                    .sqr()
                    .unwrap()
                    .sum_all()
                    .unwrap()
                    .to_scalar::<f32>()
                    .unwrap()
            };
            for s in 1..=15 {
                let loss = {
                    let map = vm.data().lock().unwrap();
                    map["layers.0.mlp.w_up.weight"]
                        .as_tensor()
                        .sqr()
                        .unwrap()
                        .mean_all()
                        .unwrap()
                };
                let grads = loss.backward().unwrap();
                let _ = opt
                    .step_with_grads(&grads, scheduled_lr(s, &hyper), 1.0)
                    .unwrap();
            }
            let after = {
                let map = vm.data().lock().unwrap();
                map["layers.0.mlp.w_up.weight"]
                    .as_tensor()
                    .sqr()
                    .unwrap()
                    .sum_all()
                    .unwrap()
                    .to_scalar::<f32>()
                    .unwrap()
            };
            assert!(
                after < initial,
                "{kind:?} failed to reduce objective: {initial} -> {after}"
            );
        }
    }

    #[test]
    fn per_micro_batch_accum_matches_full_batch_gradient_step_exactly() {
        let init_vals = vec![1.2f32, -0.8, 0.5, -1.7];
        let x_full = Tensor::from_vec(vec![1.0f32, 2.0, -1.0, 0.5, 0.3, -1.5, 2.2, -0.4], (4, 2), &Device::Cpu).unwrap();

        let vm_full = VarMap::new();
        let vm_accum = VarMap::new();
        {
            let t1 = Tensor::from_vec(init_vals.clone(), (2, 2), &Device::Cpu).unwrap();
            let t2 = Tensor::from_vec(init_vals, (2, 2), &Device::Cpu).unwrap();
            vm_full.data().lock().unwrap().insert("layers.0.mlp.w_up.weight".into(), Var::from_tensor(&t1).unwrap());
            vm_accum.data().lock().unwrap().insert("layers.0.mlp.w_up.weight".into(), Var::from_tensor(&t2).unwrap());
        }
        let hyper = Hyperparams::default();
        let mut opt_full = StepOptimizer::new(&vm_full, &hyper).unwrap();
        let mut opt_accum = StepOptimizer::new(&vm_accum, &hyper).unwrap();

        // Full batch (B=4)
        let w_f = vm_full.data().lock().unwrap()["layers.0.mlp.w_up.weight"].as_tensor().clone();
        let loss_full = x_full.matmul(&w_f).unwrap().sqr().unwrap().mean_all().unwrap();
        let norm_full = opt_full.step_with_grads(&loss_full.backward().unwrap(), 1e-3, 1.0).unwrap();

        // 2 micro-batches of B=2 freeing graph after each backward()
        opt_accum.zero_accum();
        for chunk in 0..2 {
            let x_sub = x_full.narrow(0, chunk * 2, 2).unwrap();
            let w_a = vm_accum.data().lock().unwrap()["layers.0.mlp.w_up.weight"].as_tensor().clone();
            let loss_sub = x_sub.matmul(&w_a).unwrap().sqr().unwrap().mean_all().unwrap().affine(0.5, 0.0).unwrap();
            let g_sub = loss_sub.backward().unwrap();
            opt_accum.accumulate_grads(&g_sub).unwrap();
        }
        let norm_accum = opt_accum.step_accumulated(1e-3, 1.0).unwrap();
        assert!((norm_full - norm_accum).abs() < 1e-5);

        let after_f = vm_full.data().lock().unwrap()["layers.0.mlp.w_up.weight"].as_tensor().flatten_all().unwrap().to_vec1::<f32>().unwrap();
        let after_a = vm_accum.data().lock().unwrap()["layers.0.mlp.w_up.weight"].as_tensor().flatten_all().unwrap().to_vec1::<f32>().unwrap();
        for (a, b) in after_f.iter().zip(after_a.iter()) {
            assert!((a - b).abs() < 1e-6, "Mismatch: {a} vs {b}");
        }
    }

    #[test]
    fn lr_schedules_warm_up_and_stay_bounded() {
        let mut h = Hyperparams::default();
        h.lr = 1e-3;
        h.min_lr_ratio = 0.1;
        h.warmup_steps = 10;
        h.total_steps = 100;
        for sched in LrSchedule::ALL {
            h.lr_schedule = sched;
            assert!(scheduled_lr(1, &h) < h.lr);
            assert!((scheduled_lr(10, &h) - h.lr).abs() < 1e-9);
            assert!(scheduled_lr(100, &h) >= h.lr * 0.1 - 1e-9);
        }
    }
}
