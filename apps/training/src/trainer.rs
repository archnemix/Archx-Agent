//! Purpose: Orchestrates background multi-threaded Transformer training, validation, NaN rollback, `.safetensors` checkpoints, and streaming Playground inference.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU8, AtomicUsize, Ordering};
use std::time::{Duration, Instant};

use candle_core::{DType, Device, Tensor};
use candle_nn::VarMap;

use crate::config::{RunConfig, SamplingConfig};
use crate::dataset::PreparedDataset;
use crate::optim::{StepOptimizer, scheduled_lr};
use crate::rng::Rng;
use crate::telemetry::{NeuralSnapshot, StepPoint, TelemetryMode, capture_neural_snapshot};
use crate::tokenizer::{ASSISTANT_ID, EOS_ID, LabTokenizer, PAD_ID, USER_ID};
use crate::transformer::TransformerModel;

/// Shared lock-free flags allowing the UI to pause, resume, snapshot, save, or stop a live run.
pub struct TrainControl {
    pub stop: AtomicBool,
    pub paused: AtomicBool,
    pub save_now: AtomicBool,
    pub snapshot_now: AtomicBool,
    pub telemetry_mode: AtomicU8,
    pub inspected_layer: AtomicUsize,
}

impl TrainControl {
    pub fn new(mode: TelemetryMode, inspected_layer: usize) -> Arc<Self> {
        Arc::new(Self {
            stop: AtomicBool::new(false),
            paused: AtomicBool::new(false),
            save_now: AtomicBool::new(false),
            snapshot_now: AtomicBool::new(false),
            telemetry_mode: AtomicU8::new(mode as u8),
            inspected_layer: AtomicUsize::new(inspected_layer),
        })
    }
}

#[derive(Debug, Clone)]
pub enum TrainEvent {
    Started {
        vocab_size: usize,
        train_windows: usize,
        val_windows: usize,
        run_dir: PathBuf,
    },
    Step {
        point: StepPoint,
        neural: Option<NeuralSnapshot>,
    },
    Checkpoint {
        tag: String,
        step: usize,
        loss: f32,
        path: PathBuf,
    },
    Journal(String),
    Finished {
        final_step: usize,
        best_loss: f32,
        stopped_early: bool,
        run_dir: PathBuf,
    },
}

#[derive(Debug, Clone)]
pub enum GenerationEvent {
    Token { slot: u8, text_so_far: String, tokens_generated: usize },
    Done { slot: u8, full_text: String, tokens_generated: usize, tok_per_sec: f32 },
}

/// Runs the complete training pipeline on a dedicated Rayon pool, invoking `emit`
/// as each step, checkpoint, or sampled neural snapshot completes.
pub fn execute_training_pipeline<F>(
    mut run_cfg: RunConfig,
    dataset: PreparedDataset,
    tokenizer: LabTokenizer,
    run_dir: PathBuf,
    control: Arc<TrainControl>,
    mut emit: F,
) -> Result<(), String>
where
    F: FnMut(TrainEvent),
{
    if dataset.train_docs.is_empty() {
        return Err("Dataset has no training documents.".to_owned());
    }

    run_cfg.model.vocab_size = tokenizer.vocab_size();
    run_cfg.model.init_seed = run_cfg.hyper.master_seed;
    let model_cfg = run_cfg.model.sanitized();

    std::fs::create_dir_all(&run_dir)
        .map_err(|_| format!("Could not create run folder {}", run_dir.display()))?;
    tokenizer.save_to_path(&run_dir.join("tokenizer.json"))?;

    let train_windows = tokenizer.build_windows(
        &dataset.train_docs,
        model_cfg.seq_len,
        run_cfg.tokenizer.sequence_packing,
        run_cfg.tokenizer.add_bos_eos,
    );
    let val_windows = tokenizer.build_windows(
        &dataset.val_docs,
        model_cfg.seq_len,
        run_cfg.tokenizer.sequence_packing,
        run_cfg.tokenizer.add_bos_eos,
    );
    if train_windows.is_empty() {
        return Err("No token windows could be constructed from the dataset.".to_owned());
    }

    emit(TrainEvent::Started {
        vocab_size: tokenizer.vocab_size(),
        train_windows: train_windows.len(),
        val_windows: val_windows.len(),
        run_dir: run_dir.clone(),
    });

    let threads = run_cfg.hyper.compute_threads.clamp(1, 32);
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build()
        .map_err(|e| format!("Could not build compute thread pool: {e}"))?;

    pool.install(|| -> Result<(), String> {
        let device = Device::Cpu;
        let model = TransformerModel::new(&model_cfg, device.clone())
            .map_err(|e| format!("Failed initializing Transformer: {e}"))?;
        let mut optimizer = StepOptimizer::new(&model.varmap, &run_cfg.hyper)
            .map_err(|e| format!("Failed initializing optimizer: {e}"))?;

        let mut rng = Rng::new(run_cfg.hyper.master_seed ^ 0xA5A5_5A5A_1234_5678);
        let mut best_loss = f32::INFINITY;
        let mut healthy_backup = snapshot_varmap(&model.varmap);
        let mut lr_backoff = 1.0f64;

        let total_steps = run_cfg.hyper.total_steps.max(1);
        let batch_size = run_cfg.hyper.batch_size.max(1);
        let accum_steps = run_cfg.hyper.grad_accum_steps.max(1);
        let seq_len = model_cfg.seq_len;

        let mut order: Vec<usize> = (0..train_windows.len()).collect();
        rng.shuffle(&mut order);
        let mut cursor = 0usize;

        for step in 1..=total_steps {
            while control.paused.load(Ordering::Relaxed) && !control.stop.load(Ordering::Relaxed) {
                if control.snapshot_now.swap(false, Ordering::Relaxed) {
                    let inspected = control.inspected_layer.load(Ordering::Relaxed);
                    let snap = capture_neural_snapshot(
                        &model.varmap,
                        None,
                        model_cfg.n_layers,
                        inspected,
                        &[],
                        step,
                    );
                    emit(TrainEvent::Step {
                        point: StepPoint {
                            step,
                            train_loss: best_loss.min(10.0),
                            val_loss: None,
                            perplexity: best_loss.min(10.0).exp(),
                            lr: scheduled_lr(step, &run_cfg.hyper) * lr_backoff,
                            grad_norm: 0.0,
                            tokens_per_sec: 0.0,
                        },
                        neural: Some(snap),
                    });
                }
                std::thread::sleep(Duration::from_millis(60));
            }
            if control.stop.load(Ordering::Relaxed) {
                let latest_dir = run_dir.join("latest");
                let _ = save_bundle(&model, &tokenizer, &run_cfg, &latest_dir);
                emit(TrainEvent::Finished {
                    final_step: step.saturating_sub(1),
                    best_loss,
                    stopped_early: true,
                    run_dir: run_dir.clone(),
                });
                return Ok(());
            }

            let step_start = Instant::now();
            let mut accum_loss = Tensor::zeros((), DType::F32, &device)
                .map_err(|e| format!("Tensor error: {e}"))?;
            let mut ce_sum = 0.0f32;
            let mut expert_totals = if model_cfg.routing == crate::config::Routing::MoE {
                vec![0usize; model_cfg.moe.n_experts]
            } else {
                Vec::new()
            };

            for _ in 0..accum_steps {
                let (x_batch, y_batch) = next_batch(
                    &train_windows,
                    &mut order,
                    &mut cursor,
                    &mut rng,
                    batch_size,
                    seq_len,
                    &device,
                )
                .map_err(|e| format!("Batch construction failed: {e}"))?;

                let fwd = model
                    .forward_step(
                        &x_batch,
                        Some(&y_batch),
                        run_cfg.hyper.label_smoothing,
                        Some(&mut rng),
                    )
                    .map_err(|e| format!("Forward pass failed at step {step}: {e}"))?;

                let micro_total = fwd.total_loss.expect("targets supplied");
                let micro_ce = fwd
                    .ce_loss
                    .expect("ce")
                    .to_scalar::<f32>()
                    .map_err(|e| format!("Scalar read failed: {e}"))?;
                ce_sum += micro_ce / (accum_steps as f32);

                let scaled = micro_total
                    .affine(1.0 / (accum_steps as f64), 0.0)
                    .map_err(|e| format!("Loss scale failed: {e}"))?;
                accum_loss = accum_loss
                    .add(&scaled)
                    .map_err(|e| format!("Loss accum failed: {e}"))?;

                for (slot, c) in expert_totals.iter_mut().zip(fwd.expert_counts) {
                    *slot += c;
                }
            }

            if !ce_sum.is_finite()
                || (run_cfg.hyper.nan_rollback
                    && best_loss.is_finite()
                    && step > 5
                    && ce_sum > best_loss * 5.5 + 2.0)
            {
                restore_varmap(&model.varmap, &healthy_backup);
                lr_backoff = (lr_backoff * 0.5).max(0.05);
                emit(TrainEvent::Journal(format!(
                    "Step {step}: instability detected (loss={ce_sum:.4}); restored last healthy weights and scaled LR by 0.5×."
                )));
                continue;
            }

            let grads = accum_loss
                .backward()
                .map_err(|e| format!("Backward pass failed at step {step}: {e}"))?;
            let lr = scheduled_lr(step, &run_cfg.hyper) * lr_backoff;
            let grad_norm = optimizer
                .step_with_grads(&grads, lr, run_cfg.hyper.grad_clip_norm)
                .map_err(|e| format!("Optimizer step failed at step {step}: {e}"))?;

            let elapsed = step_start.elapsed().as_secs_f32().max(1e-4);
            let tokens_processed = (batch_size * accum_steps * seq_len) as f32;
            let tokens_per_sec = tokens_processed / elapsed;

            let val_loss = if !val_windows.is_empty()
                && (step == 1
                    || step == total_steps
                    || (run_cfg.hyper.eval_every > 0 && step % run_cfg.hyper.eval_every == 0))
            {
                Some(evaluate_validation(&model, &val_windows, batch_size, seq_len, &device))
            } else {
                None
            };

            let tracked_metric = val_loss.unwrap_or(ce_sum);
            if tracked_metric.is_finite() && tracked_metric < best_loss {
                best_loss = tracked_metric;
                healthy_backup = snapshot_varmap(&model.varmap);
                let best_dir = run_dir.join("best");
                if save_bundle(&model, &tokenizer, &run_cfg, &best_dir).is_ok()
                    && (step == 1 || step == total_steps || step % 10 == 0)
                {
                    emit(TrainEvent::Checkpoint {
                        tag: "best".to_owned(),
                        step,
                        loss: best_loss,
                        path: best_dir,
                    });
                }
            }

            let want_periodic = run_cfg.hyper.checkpoint_every > 0
                && step % run_cfg.hyper.checkpoint_every == 0;
            let manual_save = control.save_now.swap(false, Ordering::Relaxed);
            if want_periodic || manual_save || step == total_steps {
                let latest_dir = run_dir.join("latest");
                if save_bundle(&model, &tokenizer, &run_cfg, &latest_dir).is_ok() {
                    emit(TrainEvent::Checkpoint {
                        tag: if manual_save { "manual".into() } else { "latest".into() },
                        step,
                        loss: ce_sum,
                        path: latest_dir,
                    });
                }
            }

            let mode = TelemetryMode::from_u8(control.telemetry_mode.load(Ordering::Relaxed));
            let force_snap = control.snapshot_now.swap(false, Ordering::Relaxed);
            let neural = if mode.should_sample(step, force_snap) {
                let inspected = control.inspected_layer.load(Ordering::Relaxed);
                Some(capture_neural_snapshot(
                    &model.varmap,
                    Some(&grads),
                    model_cfg.n_layers,
                    inspected,
                    &expert_totals,
                    step,
                ))
            } else {
                None
            };

            let ppl = ce_sum.min(12.0).exp();
            emit(TrainEvent::Step {
                point: StepPoint {
                    step,
                    train_loss: ce_sum,
                    val_loss,
                    perplexity: ppl,
                    lr,
                    grad_norm,
                    tokens_per_sec,
                },
                neural,
            });
        }

        emit(TrainEvent::Finished {
            final_step: total_steps,
            best_loss,
            stopped_early: false,
            run_dir,
        });
        Ok(())
    })
}

fn save_bundle(
    model: &TransformerModel,
    tokenizer: &LabTokenizer,
    run_cfg: &RunConfig,
    dir: &Path,
) -> Result<(), String> {
    model.save_checkpoint(dir)?;
    tokenizer.save_to_path(&dir.join("tokenizer.json"))?;
    if let Ok(meta) = serde_json::to_vec_pretty(run_cfg) {
        let _ = std::fs::write(dir.join("run_config.json"), meta);
    }
    Ok(())
}

fn next_batch(
    windows: &[Vec<u32>],
    order: &mut [usize],
    cursor: &mut usize,
    rng: &mut Rng,
    batch_size: usize,
    seq_len: usize,
    device: &Device,
) -> candle_core::Result<(Tensor, Tensor)> {
    let mut x_vals = Vec::with_capacity(batch_size * seq_len);
    let mut y_vals = Vec::with_capacity(batch_size * seq_len);
    for _ in 0..batch_size {
        if *cursor >= order.len() {
            rng.shuffle(order);
            *cursor = 0;
        }
        let win = &windows[order[*cursor]];
        *cursor += 1;
        x_vals.extend_from_slice(&win[..seq_len]);
        y_vals.extend_from_slice(&win[1..seq_len + 1]);
    }
    let x = Tensor::from_vec(x_vals, (batch_size, seq_len), device)?;
    let y = Tensor::from_vec(y_vals, (batch_size, seq_len), device)?;
    Ok((x, y))
}

fn evaluate_validation(
    model: &TransformerModel,
    val_windows: &[Vec<u32>],
    batch_size: usize,
    seq_len: usize,
    device: &Device,
) -> f32 {
    let take = val_windows.len().min(batch_size.max(2));
    if take == 0 {
        return 0.0;
    }
    let mut x_vals = Vec::with_capacity(take * seq_len);
    let mut y_vals = Vec::with_capacity(take * seq_len);
    for win in val_windows.iter().take(take) {
        x_vals.extend_from_slice(&win[..seq_len]);
        y_vals.extend_from_slice(&win[1..seq_len + 1]);
    }
    let Ok(x) = Tensor::from_vec(x_vals, (take, seq_len), device) else {
        return 0.0;
    };
    let Ok(y) = Tensor::from_vec(y_vals, (take, seq_len), device) else {
        return 0.0;
    };
    model
        .forward_step(&x, Some(&y), 0.0, None)
        .ok()
        .and_then(|out| out.ce_loss)
        .and_then(|ce| ce.to_scalar::<f32>().ok())
        .unwrap_or(0.0)
}

fn snapshot_varmap(varmap: &VarMap) -> HashMap<String, Vec<f32>> {
    let map = varmap.data().lock().unwrap();
    let mut out = HashMap::with_capacity(map.len());
    for (name, var) in map.iter() {
        if let Ok(vals) = var.as_tensor().flatten_all().and_then(|t| t.to_vec1::<f32>()) {
            out.insert(name.clone(), vals);
        }
    }
    out
}

fn restore_varmap(varmap: &VarMap, backup: &HashMap<String, Vec<f32>>) {
    let map = varmap.data().lock().unwrap();
    for (name, vals) in backup {
        if let Some(var) = map.get(name) {
            if let Ok(t) = Tensor::from_vec(vals.clone(), var.shape(), var.device()) {
                let _ = var.set(&t);
            }
        }
    }
}

/// Streams autoregressive tokens from a saved checkpoint directory (`best/` or `latest/`).
pub fn generate_from_checkpoint<F>(
    checkpoint_dir: &Path,
    turns: &[(String, String)],
    prompt: &str,
    sampling: &SamplingConfig,
    slot: u8,
    stop_flag: &AtomicBool,
    mut emit: F,
) -> Result<String, String>
where
    F: FnMut(GenerationEvent),
{
    let model = TransformerModel::load_checkpoint(checkpoint_dir, Device::Cpu)?;
    let tk_path = if checkpoint_dir.join("tokenizer.json").is_file() {
        checkpoint_dir.join("tokenizer.json")
    } else {
        checkpoint_dir
            .parent()
            .map(|p| p.join("tokenizer.json"))
            .unwrap_or_else(|| checkpoint_dir.join("tokenizer.json"))
    };
    let tokenizer = LabTokenizer::load_from_path(&tk_path)?;

    let mut context = tokenizer.encode_chat_turns(turns, prompt);
    let mut generated: Vec<u32> = Vec::new();
    let mut rng = Rng::new(sampling.seed);
    let max_new = sampling.max_new_tokens.clamp(1, 512);
    let started = Instant::now();

    for _ in 0..max_new {
        if stop_flag.load(Ordering::Relaxed) {
            break;
        }
        let mut logits = model
            .next_token_logits(&context)
            .map_err(|e| format!("Inference error: {e}"))?;
        // Mask <pad> so generation never emits padding.
        if let Some(p) = logits.get_mut(PAD_ID as usize) {
            *p = -1e9;
        }
        let recent_start = context.len().saturating_sub(48);
        let next = rng.sample_logits(
            &logits,
            &context[recent_start..],
            sampling.temperature,
            sampling.top_k,
            sampling.top_p,
            sampling.repetition_penalty,
        );
        if next == EOS_ID || next == USER_ID || next == ASSISTANT_ID {
            break;
        }
        context.push(next);
        generated.push(next);

        let text_so_far = tokenizer.decode(&generated, true);
        emit(GenerationEvent::Token {
            slot,
            text_so_far,
            tokens_generated: generated.len(),
        });
    }

    let full_text = tokenizer.decode(&generated, true).trim().to_owned();
    let elapsed = started.elapsed().as_secs_f32().max(1e-4);
    let tok_per_sec = generated.len() as f32 / elapsed;
    emit(GenerationEvent::Done {
        slot,
        full_text: full_text.clone(),
        tokens_generated: generated.len(),
        tok_per_sec,
    });
    Ok(full_text)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{Preset, Routing, TokenizerKind};
    use crate::dataset::load_local_or_builtin;

    #[test]
    fn end_to_end_pipeline_trains_saves_checkpoint_and_generates_tokens() {
        let mut cfg = RunConfig::default();
        cfg.preset = Preset::Nano;
        cfg.tokenizer.kind = TokenizerKind::CharLevel;
        cfg.tokenizer.vocab_size = 128;
        cfg.model = crate::config::TransformerConfig::from_preset(Preset::Nano, Routing::Dense);
        cfg.model.n_layers = 2;
        cfg.model.d_model = 48;
        cfg.model.n_heads = 4;
        cfg.model.n_kv_heads = 2;
        cfg.model.d_ff = 96;
        cfg.model.seq_len = 32;
        cfg.hyper.batch_size = 4;
        cfg.hyper.total_steps = 18;
        cfg.hyper.warmup_steps = 3;
        cfg.hyper.lr = 8e-3;
        cfg.hyper.eval_every = 9;
        cfg.hyper.compute_threads = 2;

        let ds = load_local_or_builtin(&cfg.dataset).expect("dataset");
        let tk = LabTokenizer::train_or_load(&cfg.tokenizer, &ds.train_docs).expect("tokenizer");

        let dir = std::env::temp_dir().join(format!("archx-e2e-train-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let control = TrainControl::new(TelemetryMode::Every10, 0);

        let mut losses = Vec::new();
        let mut saw_neural = false;
        execute_training_pipeline(cfg.clone(), ds, tk, dir.clone(), control, |ev| match ev {
            TrainEvent::Step { point, neural } => {
                losses.push(point.train_loss);
                if neural.is_some() {
                    saw_neural = true;
                }
            }
            _ => {}
        })
        .expect("pipeline succeeds");

        assert_eq!(losses.len(), 18);
        assert!(saw_neural, "expected sampled neural snapshot on step 1/10");
        assert!(
            losses.last().copied().unwrap() < losses.first().copied().unwrap(),
            "loss must decrease over training: {losses:?}"
        );
        assert!(dir.join("best/model.safetensors").is_file());
        assert!(dir.join("latest/model.safetensors").is_file());

        let stop = AtomicBool::new(false);
        let mut samp = cfg.sampling.clone();
        samp.max_new_tokens = 16;
        let reply = generate_from_checkpoint(
            &dir.join("best"),
            &[],
            "Hello!",
            &samp,
            0,
            &stop,
            |_| {},
        )
        .expect("generates");
        assert!(!reply.is_empty() || samp.max_new_tokens > 0);
        let _ = std::fs::remove_dir_all(dir);
    }
}
