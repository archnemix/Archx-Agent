//! Purpose: Implements native Rust optimizers (`AdamW`, `Muon`, `Lion`, `SGD + Nesterov`), global gradient clipping, and learning-rate schedules.

use std::f64::consts::PI;

use candle_core::{DType, Result as CandleResult, Tensor, Var, backprop::GradStore};
use candle_nn::VarMap;

use crate::config::{Hyperparams, LrSchedule, OptimizerKind};

struct TrackedParam {
    name: String,
    var: Var,
    is_muon_2d: bool,
    no_decay: bool,
    m: Tensor,
    v: Option<Tensor>,
}

/// Unified optimizer operating on named `VarMap` variables.
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
            let is_hidden_layer = name.starts_with("layers.") && !name.contains("norm") && !name.ends_with(".bias");
            let is_muon_2d = hyper.optimizer == OptimizerKind::Muon && dims.len() == 2 && is_hidden_layer;
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

    /// Computes global gradient L2 norm across all tracked variables and applies
    /// synchronized `max_norm` scaling when `max_norm > 0.0`, returning the pre-clip norm.
    /// Applies one optimization step with `lr`.
    pub fn step_with_grads(
        &mut self,
        grads: &GradStore,
        lr: f64,
        max_grad_norm: f32,
    ) -> CandleResult<f32> {
        let mut total_sq = 0.0f64;
        for p in &self.params {
            if let Some(g) = grads.get(&p.var) {
                let sq = g.sqr()?.sum_all()?.to_scalar::<f32>()? as f64;
                total_sq += sq;
            }
        }
        let grad_norm = total_sq.sqrt() as f32;
        if !grad_norm.is_finite() {
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
            let Some(raw_g) = grads.get(&p.var) else {
                continue;
            };
            let g = if (clip_scale - 1.0).abs() > 1e-6 {
                (raw_g * clip_scale)?
            } else {
                raw_g.clone()
            };
            let wd = if p.no_decay { 0.0 } else { self.weight_decay };

            if p.is_muon_2d {
                // Muon: Nesterov momentum + 5-step Newton–Schulz orthogonalization on 2D hidden matrices.
                let mu = self.beta1;
                p.m = ((&p.m * mu)? + &g)?;
                let nesterov = (&g + &(&p.m * mu)?)?;
                let orth = newton_schulz_orthogonalize(&nesterov, 5)?;
                let (rows, cols) = orth.dims2()?;
                let aspect_scale = (rows.max(cols) as f64 / rows.min(cols).max(1) as f64).sqrt().max(1.0);
                // Muon uses a ~3x larger effective matrix step relative to base AdamW lr.
                let muon_lr = lr * 3.0 * aspect_scale * 0.2;
                let decayed = if wd > 0.0 {
                    (p.var.as_tensor() * (1.0 - lr * wd))?
                } else {
                    p.var.as_tensor().clone()
                };
                p.var.set(&(&decayed - &(orth * muon_lr)?)?)?;
                continue;
            }

            match self.kind {
                OptimizerKind::AdamW | OptimizerKind::Muon => {
                    let v_ref = p.v.as_mut().expect("v allocated for AdamW");
                    p.m = ((&p.m * self.beta1)? + &(&g * (1.0 - self.beta1))?)?;
                    *v_ref = ((&*v_ref * self.beta2)? + &(&g.sqr()? * (1.0 - self.beta2))?)?;

                    let bias1 = 1.0 - self.beta1.powi(t);
                    let bias2 = 1.0 - self.beta2.powi(t);
                    let m_hat = (&p.m / bias1)?;
                    let v_hat = (&*v_ref / bias2)?;
                    let step_dir = m_hat.broadcast_div(&(v_hat.sqrt()? + self.eps)?)?;

                    let decayed = if wd > 0.0 {
                        (p.var.as_tensor() * (1.0 - lr * wd))?
                    } else {
                        p.var.as_tensor().clone()
                    };
                    p.var.set(&(&decayed - &(step_dir * lr)?)?)?;
                }
                OptimizerKind::Lion => {
                    // Lion: update = sign(beta1 * m + (1 - beta1) * g), m = beta2 * m + (1 - beta2) * g
                    let interp = ((&p.m * self.beta1)? + &(&g * (1.0 - self.beta1))?)?;
                    let sign_t = tensor_sign(&interp)?;
                    // Lion uses ~0.3x the scalar lr of AdamW so defaults stay stable.
                    let lion_lr = lr * 0.3;
                    let decayed = if wd > 0.0 {
                        (p.var.as_tensor() * (1.0 - lion_lr * wd))?
                    } else {
                        p.var.as_tensor().clone()
                    };
                    p.var.set(&(&decayed - &(sign_t * lion_lr)?)?)?;
                    p.m = ((&p.m * self.beta2)? + &(&g * (1.0 - self.beta2))?)?;
                }
                OptimizerKind::SgdNesterov => {
                    let mu = self.beta1;
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
        }

        Ok(grad_norm)
    }
}

/// Computes Newton–Schulz quintic/cubic orthogonalization on a 2D gradient matrix.
fn newton_schulz_orthogonalize(g: &Tensor, steps: usize) -> CandleResult<Tensor> {
    let (r, c) = g.dims2()?;
    let transposed = r > c;
    let mut x = if transposed { g.t()?.contiguous()? } else { g.clone() };
    let frob = (x.sqr()?.sum_all()?.to_scalar::<f32>()?.sqrt() as f64) + 1e-7;
    x = (&x / frob)?;

    // Quintic coefficients (a=3.4445, b=-4.7750, c=2.0315) from Muon.
    let (a, b, coef_c) = (3.4445f64, -4.7750f64, 2.0315f64);
    for _ in 0..steps {
        let xt = x.t()?.contiguous()?;
        let gram = x.matmul(&xt)?; // [m, m] where m = min(r, c)
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
            // Warmup -> 70% Stable plateau -> 30% Cosine decay.
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
                let t = Tensor::from_vec(vec![2.0f32, -3.0, 1.5, -1.0], (2, 2), &Device::Cpu).unwrap();
                map.insert("layers.0.mlp.w_up.weight".into(), Var::from_tensor(&t).unwrap());
            }
            let mut hyper = Hyperparams::default();
            hyper.optimizer = kind;
            hyper.lr = 0.08;
            let mut opt = StepOptimizer::new(&vm, &hyper).expect("opt");

            let initial = {
                let map = vm.data().lock().unwrap();
                map["layers.0.mlp.w_up.weight"].as_tensor().sqr().unwrap().sum_all().unwrap().to_scalar::<f32>().unwrap()
            };
            for s in 1..=15 {
                let loss = {
                    let map = vm.data().lock().unwrap();
                    map["layers.0.mlp.w_up.weight"].as_tensor().sqr().unwrap().mean_all().unwrap()
                };
                let grads = loss.backward().unwrap();
                let _ = opt.step_with_grads(&grads, scheduled_lr(s, &hyper), 1.0).unwrap();
            }
            let after = {
                let map = vm.data().lock().unwrap();
                map["layers.0.mlp.w_up.weight"].as_tensor().sqr().unwrap().sum_all().unwrap().to_scalar::<f32>().unwrap()
            };
            assert!(after < initial, "{kind:?} failed to reduce objective: {initial} -> {after}");
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
