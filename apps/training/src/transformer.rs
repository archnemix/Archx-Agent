//! Purpose: Implements the pure-Rust `candle` Autoregressive Transformer (`Dense` and Top-k `SparseMoE` with shared experts), `.safetensors` I/O, and token generation.

use std::path::Path;

use candle_core::{DType, Device, Module, Result as CandleResult, Tensor, Var, D};
use candle_nn::{Embedding, LayerNorm, Linear, VarMap, ops};

use crate::config::{ActivationKind, InitDist, NormKind, PosEncoding, Routing, TransformerConfig};
use crate::rng::Rng;
use crate::tokenizer::PAD_ID;

/// Deterministic variable allocator writing seeded float tensors directly into `VarMap`.
struct SeededBuilder<'a> {
    varmap: &'a VarMap,
    device: &'a Device,
    rng: Rng,
    dist: InitDist,
    base_std: f32,
}

impl<'a> SeededBuilder<'a> {
    fn new(varmap: &'a VarMap, device: &'a Device, cfg: &TransformerConfig) -> Self {
        Self {
            varmap,
            device,
            rng: Rng::new(cfg.init_seed),
            dist: cfg.init_dist,
            base_std: cfg.init_std,
        }
    }

    fn insert_var(&mut self, name: &str, vals: Vec<f32>, shape: &[usize]) -> CandleResult<Tensor> {
        let mut map = self.varmap.data().lock().unwrap();
        if let Some(existing) = map.get(name) {
            return Ok(existing.as_tensor().clone());
        }
        let tensor = Tensor::from_vec(vals, shape, self.device)?;
        let var = Var::from_tensor(&tensor)?;
        let out = var.as_tensor().clone();
        map.insert(name.to_owned(), var);
        Ok(out)
    }

    fn matrix(&mut self, name: &str, out_dim: usize, in_dim: usize, scale: f32) -> CandleResult<Tensor> {
        let count = out_dim * in_dim;
        let vals = match self.dist {
            InitDist::Normal => self.rng.normal_vec(count, 0.0, self.base_std * scale),
            InitDist::XavierUniform => self.rng.xavier_uniform_vec(in_dim, out_dim, count, scale),
            InitDist::KaimingNormal => self.rng.kaiming_normal_vec(in_dim, count, scale * 0.5),
        };
        self.insert_var(name, vals, &[out_dim, in_dim])
    }

    fn ones(&mut self, name: &str, dim: usize) -> CandleResult<Tensor> {
        self.insert_var(name, vec![1.0f32; dim], &[dim])
    }

    fn zeros(&mut self, name: &str, dim: usize) -> CandleResult<Tensor> {
        self.insert_var(name, vec![0.0f32; dim], &[dim])
    }

    fn linear(
        &mut self,
        prefix: &str,
        in_dim: usize,
        out_dim: usize,
        use_bias: bool,
        scale: f32,
    ) -> CandleResult<Linear> {
        let w = self.matrix(&format!("{prefix}.weight"), out_dim, in_dim, scale)?;
        let b = if use_bias {
            Some(self.zeros(&format!("{prefix}.bias"), out_dim)?)
        } else {
            None
        };
        Ok(Linear::new(w, b))
    }

    fn norm(&mut self, prefix: &str, dim: usize, kind: NormKind, eps: f64) -> CandleResult<LayerNorm> {
        let w = self.ones(&format!("{prefix}.weight"), dim)?;
        match kind {
            NormKind::RmsNorm => Ok(LayerNorm::rms_norm(w, eps)),
            NormKind::LayerNorm => {
                let b = self.zeros(&format!("{prefix}.bias"), dim)?;
                Ok(LayerNorm::new(w, b, eps))
            }
        }
    }
}

#[derive(Clone)]
struct RotaryCache {
    cos: Tensor, // [max_seq, head_dim / 2]
    sin: Tensor, // [max_seq, head_dim / 2]
}

impl RotaryCache {
    fn new(max_seq: usize, head_dim: usize, theta: f32, device: &Device) -> CandleResult<Self> {
        let half = head_dim / 2;
        let mut cos_vals = Vec::with_capacity(max_seq * half);
        let mut sin_vals = Vec::with_capacity(max_seq * half);
        for pos in 0..max_seq {
            for i in 0..half {
                let freq = 1.0 / theta.powf((2 * i) as f32 / head_dim.max(2) as f32);
                let angle = (pos as f32) * freq;
                cos_vals.push(angle.cos());
                sin_vals.push(angle.sin());
            }
        }
        Ok(Self {
            cos: Tensor::from_vec(cos_vals, (max_seq, half), device)?,
            sin: Tensor::from_vec(sin_vals, (max_seq, half), device)?,
        })
    }

    /// Applies rotary embedding to `x` of shape `[b, h, seq, head_dim]`.
    fn apply(&self, x: &Tensor, seq_len: usize) -> CandleResult<Tensor> {
        let half = x.dim(3)? / 2;
        let x1 = x.narrow(3, 0, half)?;
        let x2 = x.narrow(3, half, half)?;
        let cos = self.cos.narrow(0, 0, seq_len)?.unsqueeze(0)?.unsqueeze(0)?;
        let sin = self.sin.narrow(0, 0, seq_len)?.unsqueeze(0)?.unsqueeze(0)?;

        let rot1 = (x1.broadcast_mul(&cos)? - x2.broadcast_mul(&sin)?)?;
        let rot2 = (x1.broadcast_mul(&sin)? + x2.broadcast_mul(&cos)?)?;
        Tensor::cat(&[&rot1, &rot2], 3)
    }
}

#[derive(Clone)]
struct CausalSelfAttention {
    wq: Linear,
    wk: Linear,
    wv: Linear,
    wo: Linear,
    q_norm: Option<LayerNorm>,
    k_norm: Option<LayerNorm>,
    n_heads: usize,
    n_kv_heads: usize,
    head_dim: usize,
    rope: Option<RotaryCache>,
}

impl CausalSelfAttention {
    fn build(
        sb: &mut SeededBuilder<'_>,
        prefix: &str,
        cfg: &TransformerConfig,
        resid_scale: f32,
        rope: Option<RotaryCache>,
    ) -> CandleResult<Self> {
        let head_dim = cfg.head_dim();
        let kv_dim = cfg.n_kv_heads * head_dim;
        let wq = sb.linear(&format!("{prefix}.wq"), cfg.d_model, cfg.d_model, cfg.use_bias, 1.0)?;
        let wk = sb.linear(&format!("{prefix}.wk"), cfg.d_model, kv_dim, cfg.use_bias, 1.0)?;
        let wv = sb.linear(&format!("{prefix}.wv"), cfg.d_model, kv_dim, cfg.use_bias, 1.0)?;
        let wo = sb.linear(&format!("{prefix}.wo"), cfg.d_model, cfg.d_model, cfg.use_bias, resid_scale)?;

        let (q_norm, k_norm) = if cfg.qk_norm {
            (
                Some(sb.norm(&format!("{prefix}.q_norm"), head_dim, cfg.norm, cfg.norm_eps)?),
                Some(sb.norm(&format!("{prefix}.k_norm"), head_dim, cfg.norm, cfg.norm_eps)?),
            )
        } else {
            (None, None)
        };

        Ok(Self {
            wq,
            wk,
            wv,
            wo,
            q_norm,
            k_norm,
            n_heads: cfg.n_heads,
            n_kv_heads: cfg.n_kv_heads,
            head_dim,
            rope,
        })
    }

    fn forward(&self, x: &Tensor, causal_mask: &Tensor) -> CandleResult<Tensor> {
        let (b, seq, _) = x.dims3()?;
        let mut q = self
            .wq
            .forward(x)?
            .reshape((b, seq, self.n_heads, self.head_dim))?
            .transpose(1, 2)?
            .contiguous()?;
        let mut k = self
            .wk
            .forward(x)?
            .reshape((b, seq, self.n_kv_heads, self.head_dim))?
            .transpose(1, 2)?
            .contiguous()?;
        let v = self
            .wv
            .forward(x)?
            .reshape((b, seq, self.n_kv_heads, self.head_dim))?
            .transpose(1, 2)?
            .contiguous()?;

        if let (Some(qn), Some(kn)) = (&self.q_norm, &self.k_norm) {
            q = qn.forward(&q)?;
            k = kn.forward(&k)?;
        }

        if let Some(rope) = &self.rope {
            q = rope.apply(&q, seq)?;
            k = rope.apply(&k, seq)?;
        }

        let groups = self.n_heads / self.n_kv_heads;
        let k = repeat_kv(k, groups)?;
        let v = repeat_kv(v, groups)?;

        let scale = 1.0 / (self.head_dim as f64).sqrt();
        let scores = (q.matmul(&k.transpose(2, 3)?.contiguous()?)? * scale)?;
        let scores = scores.broadcast_add(causal_mask)?;
        let probs = ops::softmax(&scores, D::Minus1)?;
        let ctx = probs
            .matmul(&v.contiguous()?)?
            .transpose(1, 2)?
            .contiguous()?
            .reshape((b, seq, self.n_heads * self.head_dim))?;
        self.wo.forward(&ctx)
    }
}

fn repeat_kv(x: Tensor, n_rep: usize) -> CandleResult<Tensor> {
    if n_rep <= 1 {
        return Ok(x);
    }
    let (b, kv_heads, seq, head_dim) = x.dims4()?;
    x.unsqueeze(2)?
        .broadcast_as((b, kv_heads, n_rep, seq, head_dim))?
        .contiguous()?
        .reshape((b, kv_heads * n_rep, seq, head_dim))
}

#[derive(Clone)]
struct FeedForward {
    gate: Option<Linear>,
    up: Linear,
    down: Linear,
    activation: ActivationKind,
}

impl FeedForward {
    fn build(
        sb: &mut SeededBuilder<'_>,
        prefix: &str,
        cfg: &TransformerConfig,
        resid_scale: f32,
    ) -> CandleResult<Self> {
        let gate = if cfg.activation.is_gated() {
            Some(sb.linear(&format!("{prefix}.w_gate"), cfg.d_model, cfg.d_ff, cfg.use_bias, 1.0)?)
        } else {
            None
        };
        let up = sb.linear(&format!("{prefix}.w_up"), cfg.d_model, cfg.d_ff, cfg.use_bias, 1.0)?;
        let down = sb.linear(&format!("{prefix}.w_down"), cfg.d_ff, cfg.d_model, cfg.use_bias, resid_scale)?;
        Ok(Self {
            gate,
            up,
            down,
            activation: cfg.activation,
        })
    }

    fn forward(&self, x: &Tensor) -> CandleResult<Tensor> {
        let up_v = self.up.forward(x)?;
        let hidden = match (&self.gate, self.activation) {
            (Some(g), ActivationKind::SwiGlu) => (g.forward(x)?.silu()? * up_v)?,
            (Some(g), ActivationKind::GeGlu) => (g.forward(x)?.gelu()? * up_v)?,
            (_, ActivationKind::Gelu) => up_v.gelu()?,
            (_, ActivationKind::Silu) => up_v.silu()?,
            (_, ActivationKind::Relu2) => up_v.relu()?.sqr()?,
            _ => up_v.silu()?,
        };
        self.down.forward(&hidden)
    }
}

#[derive(Clone)]
struct SparseMoE {
    router: Linear,
    experts: Vec<FeedForward>,
    shared: Vec<FeedForward>,
    top_k: usize,
    aux_weight: f32,
    z_weight: f32,
    jitter: f32,
}

impl SparseMoE {
    fn build(
        sb: &mut SeededBuilder<'_>,
        prefix: &str,
        cfg: &TransformerConfig,
        resid_scale: f32,
    ) -> CandleResult<Self> {
        let router = sb.linear(
            &format!("{prefix}.router"),
            cfg.d_model,
            cfg.moe.n_experts,
            false,
            1.0,
        )?;
        let mut experts = Vec::with_capacity(cfg.moe.n_experts);
        for e in 0..cfg.moe.n_experts {
            experts.push(FeedForward::build(
                sb,
                &format!("{prefix}.experts.{e}"),
                cfg,
                resid_scale,
            )?);
        }
        let mut shared = Vec::with_capacity(cfg.moe.n_shared_experts);
        for s in 0..cfg.moe.n_shared_experts {
            shared.push(FeedForward::build(
                sb,
                &format!("{prefix}.shared.{s}"),
                cfg,
                resid_scale,
            )?);
        }
        Ok(Self {
            router,
            experts,
            shared,
            top_k: cfg.moe.top_k.clamp(1, cfg.moe.n_experts),
            aux_weight: cfg.moe.aux_loss_weight,
            z_weight: cfg.moe.z_loss_weight,
            jitter: cfg.moe.router_jitter,
        })
    }

    fn forward(
        &self,
        x: &Tensor,
        training_rng: Option<&mut Rng>,
    ) -> CandleResult<(Tensor, Tensor, Vec<usize>)> {
        let (b, seq, d) = x.dims3()?;
        let n_tokens = b * seq;
        let n_experts = self.experts.len();
        let x_flat = x.contiguous()?.reshape((n_tokens, d))?;

        let mut router_logits = self.router.forward(&x_flat)?;
        if let Some(rng) = training_rng {
            if self.jitter > 0.0 {
                let noise_vals: Vec<f32> = (0..(n_tokens * n_experts))
                    .map(|_| rng.uniform(-self.jitter, self.jitter))
                    .collect();
                let noise = Tensor::from_vec(noise_vals, (n_tokens, n_experts), x.device())?;
                router_logits = (router_logits + noise)?;
            }
        }

        let probs = ops::softmax(&router_logits, D::Minus1)?;
        let prob_rows = probs.to_vec2::<f32>()?;

        let mut mask_vals = vec![0.0f32; n_tokens * n_experts];
        let mut per_expert_tokens: Vec<Vec<u32>> = vec![Vec::new(); n_experts];
        let mut expert_counts = vec![0usize; n_experts];

        for (tok_idx, row) in prob_rows.iter().enumerate() {
            let mut order: Vec<(usize, f32)> = row.iter().copied().enumerate().collect();
            order.sort_by(|a, b| b.1.total_cmp(&a.1));
            for &(exp_id, _) in order.iter().take(self.top_k) {
                mask_vals[tok_idx * n_experts + exp_id] = 1.0;
                per_expert_tokens[exp_id].push(tok_idx as u32);
                expert_counts[exp_id] += 1;
            }
        }

        let mask = Tensor::from_vec(mask_vals, (n_tokens, n_experts), x.device())?;
        let masked_probs = (&probs * &mask)?;
        let denom = (masked_probs.sum_keepdim(D::Minus1)? + 1e-8)?;
        let gates = masked_probs.broadcast_div(&denom)?;

        // Load-balancing auxiliary loss + router z-loss.
        let frac = mask.mean(0)?; // [E]
        let mean_prob = probs.mean(0)?; // [E]
        let balance_loss = ((&frac * &mean_prob)?.sum_all()? * (n_experts as f64))?;

        let max_l = router_logits.max_keepdim(D::Minus1)?;
        let lse = (&max_l.squeeze(D::Minus1)?
            + &router_logits
                .broadcast_sub(&max_l)?
                .exp()?
                .sum(D::Minus1)?
                .log()?)?;
        let z_loss = lse.sqr()?.mean_all()?;

        let reg_loss = ((balance_loss * f64::from(self.aux_weight))?
            + (z_loss * f64::from(self.z_weight))?)?;

        let mut out_flat = Tensor::zeros((n_tokens, d), DType::F32, x.device())?;
        for (exp_id, indices) in per_expert_tokens.iter().enumerate() {
            if indices.is_empty() {
                continue;
            }
            let idx_t = Tensor::from_vec(indices.clone(), indices.len(), x.device())?;
            let sub_x = x_flat.index_select(&idx_t, 0)?;
            let sub_y = self.experts[exp_id].forward(&sub_x)?;
            let sub_gate = gates
                .narrow(1, exp_id, 1)?
                .contiguous()?
                .index_select(&idx_t, 0)?;
            let weighted = sub_y.broadcast_mul(&sub_gate)?.contiguous()?;
            out_flat = out_flat.index_add(&idx_t, &weighted, 0)?;
        }

        for shared_ffn in &self.shared {
            out_flat = (&out_flat + &shared_ffn.forward(&x_flat)?)?;
        }

        Ok((out_flat.reshape((b, seq, d))?, reg_loss, expert_counts))
    }
}

#[derive(Clone)]
enum BlockFfn {
    Dense(FeedForward),
    MoE(SparseMoE),
}

#[derive(Clone)]
struct TransformerBlock {
    attn_norm: LayerNorm,
    attn: CausalSelfAttention,
    ffn_norm: LayerNorm,
    ffn: BlockFfn,
}

pub struct ForwardOutput {
    pub logits: Tensor,
    pub ce_loss: Option<Tensor>,
    pub aux_loss: Tensor,
    pub total_loss: Option<Tensor>,
    /// Aggregated token dispatches per expert across MoE layers (empty for Dense).
    pub expert_counts: Vec<usize>,
}

/// Complete pure-Rust Autoregressive Transformer model paired with its `VarMap`.
pub struct TransformerModel {
    pub cfg: TransformerConfig,
    pub varmap: VarMap,
    pub device: Device,
    tok_embeddings: Embedding,
    pos_embeddings: Option<Tensor>, // [max_seq, d_model] for Learned or Sinusoidal
    layers: Vec<TransformerBlock>,
    final_norm: LayerNorm,
    lm_head: Option<Linear>,
}

impl TransformerModel {
    pub fn new(raw_cfg: &TransformerConfig, device: Device) -> CandleResult<Self> {
        let cfg = raw_cfg.sanitized();
        let varmap = VarMap::new();
        let mut sb = SeededBuilder::new(&varmap, &device, &cfg);

        let tok_w = sb.matrix("tok_embeddings.weight", cfg.vocab_size, cfg.d_model, 1.0)?;
        let tok_embeddings = Embedding::new(tok_w, cfg.d_model);

        let rope = if cfg.pos_encoding == PosEncoding::RoPE {
            Some(RotaryCache::new(
                cfg.seq_len.max(512) * 2,
                cfg.head_dim(),
                cfg.rope_theta,
                &device,
            )?)
        } else {
            None
        };

        let pos_embeddings = match cfg.pos_encoding {
            PosEncoding::Learned => Some(sb.matrix(
                "pos_embeddings.weight",
                cfg.seq_len.max(512) * 2,
                cfg.d_model,
                1.0,
            )?),
            PosEncoding::Sinusoidal => Some(build_sinusoidal_table(
                cfg.seq_len.max(512) * 2,
                cfg.d_model,
                &device,
            )?),
            PosEncoding::RoPE | PosEncoding::None => None,
        };

        let resid_scale = if cfg.residual_scale {
            1.0 / (2.0 * cfg.n_layers as f32).sqrt()
        } else {
            1.0
        };

        let mut layers = Vec::with_capacity(cfg.n_layers);
        for l in 0..cfg.n_layers {
            let p = format!("layers.{l}");
            let attn_norm = sb.norm(&format!("{p}.attn_norm"), cfg.d_model, cfg.norm, cfg.norm_eps)?;
            let attn = CausalSelfAttention::build(
                &mut sb,
                &format!("{p}.attn"),
                &cfg,
                resid_scale,
                rope.clone(),
            )?;
            let ffn_norm = sb.norm(&format!("{p}.ffn_norm"), cfg.d_model, cfg.norm, cfg.norm_eps)?;
            let ffn = match cfg.routing {
                Routing::Dense => BlockFfn::Dense(FeedForward::build(
                    &mut sb,
                    &format!("{p}.mlp"),
                    &cfg,
                    resid_scale,
                )?),
                Routing::MoE => BlockFfn::MoE(SparseMoE::build(
                    &mut sb,
                    &format!("{p}.moe"),
                    &cfg,
                    resid_scale,
                )?),
            };
            layers.push(TransformerBlock {
                attn_norm,
                attn,
                ffn_norm,
                ffn,
            });
        }

        let final_norm = sb.norm("final_norm", cfg.d_model, cfg.norm, cfg.norm_eps)?;
        let lm_head = if cfg.tie_embeddings {
            None
        } else {
            Some(sb.linear("lm_head", cfg.d_model, cfg.vocab_size, false, 1.0)?)
        };

        Ok(Self {
            cfg,
            varmap,
            device,
            tok_embeddings,
            pos_embeddings,
            layers,
            final_norm,
            lm_head,
        })
    }

    pub fn save_checkpoint(&self, dir: &Path) -> Result<(), String> {
        std::fs::create_dir_all(dir)
            .map_err(|_| format!("Could not create checkpoint folder {}", dir.display()))?;
        self.varmap
            .save(dir.join("model.safetensors"))
            .map_err(|e| format!("Failed saving model.safetensors: {e}"))?;
        let cfg_bytes = serde_json::to_vec_pretty(&self.cfg)
            .map_err(|_| "Failed serializing config.json".to_owned())?;
        std::fs::write(dir.join("config.json"), cfg_bytes)
            .map_err(|_| "Failed writing config.json".to_owned())?;
        Ok(())
    }

    pub fn load_checkpoint(dir: &Path, device: Device) -> Result<Self, String> {
        let cfg_bytes = std::fs::read(dir.join("config.json"))
            .map_err(|_| format!("Missing config.json in {}", dir.display()))?;
        let cfg: TransformerConfig = serde_json::from_slice(&cfg_bytes)
            .map_err(|_| "Corrupt checkpoint config.json".to_owned())?;
        let mut model = Self::new(&cfg, device)
            .map_err(|e| format!("Failed constructing Transformer graph: {e}"))?;
        model
            .varmap
            .load(dir.join("model.safetensors"))
            .map_err(|e| format!("Failed loading model.safetensors: {e}"))?;
        Ok(model)
    }

    /// Runs a forward pass over `input_ids` `[batch, seq]` and optionally computes
    /// masked next-token cross-entropy (+ label smoothing + MoE router regularization)
    /// against `targets` `[batch, seq]`.
    pub fn forward_step(
        &self,
        input_ids: &Tensor,
        targets: Option<&Tensor>,
        label_smoothing: f32,
        mut training_rng: Option<&mut Rng>,
    ) -> CandleResult<ForwardOutput> {
        let (b, seq) = input_ids.dims2()?;
        let mut h = self.tok_embeddings.forward(input_ids)?;
        if let Some(pos_table) = &self.pos_embeddings {
            let pos = pos_table.narrow(0, 0, seq)?.unsqueeze(0)?;
            h = h.broadcast_add(&pos)?;
        }

        let mask = build_causal_mask(seq, self.cfg.sliding_window, &self.device)?;
        let mut aux_total = Tensor::zeros((), DType::F32, &self.device)?;
        let mut agg_expert_counts = if self.cfg.routing == Routing::MoE {
            vec![0usize; self.cfg.moe.n_experts]
        } else {
            Vec::new()
        };

        for block in &self.layers {
            let attn_out = block.attn.forward(&block.attn_norm.forward(&h)?, &mask)?;
            h = (&h + &attn_out)?;

            let normed = block.ffn_norm.forward(&h)?;
            match &block.ffn {
                BlockFfn::Dense(mlp) => {
                    h = (&h + &mlp.forward(&normed)?)?;
                }
                BlockFfn::MoE(moe) => {
                    let rng_ref = training_rng.as_deref_mut();
                    let (moe_out, reg_loss, counts) = moe.forward(&normed, rng_ref)?;
                    h = (&h + &moe_out)?;
                    aux_total = (&aux_total + &reg_loss)?;
                    for (slot, c) in agg_expert_counts.iter_mut().zip(counts) {
                        *slot += c;
                    }
                }
            }
        }

        let h = self.final_norm.forward(&h)?;
        let logits = match &self.lm_head {
            Some(head) => head.forward(&h)?,
            None => {
                let w_t = self.tok_embeddings.embeddings().t()?.contiguous()?;
                h.reshape((b * seq, self.cfg.d_model))?
                    .matmul(&w_t)?
                    .reshape((b, seq, self.cfg.vocab_size))?
            }
        };

        let (ce_loss, total_loss) = if let Some(target_ids) = targets {
            let ce = masked_cross_entropy(&logits, target_ids, self.cfg.vocab_size, label_smoothing)?;
            let total = (&ce + &aux_total)?;
            (Some(ce), Some(total))
        } else {
            (None, None)
        };

        Ok(ForwardOutput {
            logits,
            ce_loss,
            aux_loss: aux_total,
            total_loss,
            expert_counts: agg_expert_counts,
        })
    }

    /// Computes next-token logits `[vocab_size]` for the final position of `context_ids`.
    pub fn next_token_logits(&self, context_ids: &[u32]) -> CandleResult<Vec<f32>> {
        let max_ctx = self.cfg.seq_len.max(16);
        let tail = if context_ids.len() > max_ctx {
            &context_ids[context_ids.len() - max_ctx..]
        } else {
            context_ids
        };
        let input = Tensor::from_vec(tail.to_vec(), (1, tail.len()), &self.device)?;
        let out = self.forward_step(&input, None, 0.0, None)?;
        let last = out.logits.narrow(1, tail.len() - 1, 1)?.squeeze(0)?.squeeze(0)?;
        last.to_vec1::<f32>()
    }
}

fn build_causal_mask(seq: usize, sliding_window: usize, device: &Device) -> CandleResult<Tensor> {
    let mut vals = Vec::with_capacity(seq * seq);
    for i in 0..seq {
        for j in 0..seq {
            let future = j > i;
            let outside_window = sliding_window > 0 && i.saturating_sub(j) >= sliding_window;
            if future || outside_window {
                vals.push(-1e9f32);
            } else {
                vals.push(0.0f32);
            }
        }
    }
    Tensor::from_vec(vals, (1, 1, seq, seq), device)
}

fn build_sinusoidal_table(max_seq: usize, d_model: usize, device: &Device) -> CandleResult<Tensor> {
    let mut vals = vec![0.0f32; max_seq * d_model];
    for pos in 0..max_seq {
        for i in (0..d_model).step_by(2) {
            let div = 10_000f32.powf(i as f32 / d_model.max(2) as f32);
            vals[pos * d_model + i] = ((pos as f32) / div).sin();
            if i + 1 < d_model {
                vals[pos * d_model + i + 1] = ((pos as f32) / div).cos();
            }
        }
    }
    Tensor::from_vec(vals, (max_seq, d_model), device)
}

fn masked_cross_entropy(
    logits: &Tensor,
    targets: &Tensor,
    vocab_size: usize,
    label_smoothing: f32,
) -> CandleResult<Tensor> {
    let (b, seq, _) = logits.dims3()?;
    let n = b * seq;
    let flat_logits = logits.reshape((n, vocab_size))?;
    let flat_targets_vec = targets.flatten_all()?.to_vec1::<u32>()?;

    let mut active_indices = Vec::with_capacity(n);
    let mut active_targets = Vec::with_capacity(n);
    for (idx, &tok) in flat_targets_vec.iter().enumerate() {
        if tok != PAD_ID && (tok as usize) < vocab_size {
            active_indices.push(idx as u32);
            active_targets.push(tok);
        }
    }
    if active_indices.is_empty() {
        return Tensor::zeros((), DType::F32, logits.device());
    }

    let idx_t = Tensor::from_vec(active_indices, active_targets.len(), logits.device())?;
    let tgt_t = Tensor::from_vec(active_targets, idx_t.dims1()?, logits.device())?;
    let sel_logits = flat_logits.index_select(&idx_t, 0)?;
    let log_probs = ops::log_softmax(&sel_logits, D::Minus1)?;
    let nll = candle_nn::loss::nll(&log_probs, &tgt_t)?;

    let eps = label_smoothing.clamp(0.0, 0.25);
    if eps > 1e-5 {
        let smooth_loss = log_probs.mean_all()?.neg()?;
        &(&nll * f64::from(1.0 - eps))? + &(&smooth_loss * f64::from(eps))?
    } else {
        Ok(nll)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn seeded_init_is_deterministic_and_checkpoint_roundtrips() {
        let mut cfg = TransformerConfig::from_preset(crate::config::Preset::Nano, Routing::Dense);
        cfg.vocab_size = 64;
        cfg.seq_len = 16;
        cfg.init_seed = 123;

        let m1 = TransformerModel::new(&cfg, Device::Cpu).expect("m1");
        let m2 = TransformerModel::new(&cfg, Device::Cpu).expect("m2");
        let mut cfg_other = cfg.clone();
        cfg_other.init_seed = 999;
        let m3 = TransformerModel::new(&cfg_other, Device::Cpu).expect("m3");

        let ctx = [1u32, 8, 12, 19];
        let l1 = m1.next_token_logits(&ctx).expect("logits 1");
        let l2 = m2.next_token_logits(&ctx).expect("logits 2");
        let l3 = m3.next_token_logits(&ctx).expect("logits 3");
        assert_eq!(l1, l2);
        assert_ne!(l1, l3);

        let dir = std::env::temp_dir().join(format!("archx-ckpt-test-{}", std::process::id()));
        m1.save_checkpoint(&dir).expect("save");
        let restored = TransformerModel::load_checkpoint(&dir, Device::Cpu).expect("load");
        assert_eq!(restored.next_token_logits(&ctx).expect("restored"), l1);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn sparse_moe_produces_differentiable_loss_and_expert_counts() {
        let mut cfg = TransformerConfig::from_preset(crate::config::Preset::Nano, Routing::MoE);
        cfg.vocab_size = 48;
        cfg.seq_len = 12;
        cfg.n_layers = 2;
        cfg.d_model = 32;
        cfg.n_heads = 4;
        cfg.n_kv_heads = 2;
        cfg.d_ff = 64;

        let model = TransformerModel::new(&cfg, Device::Cpu).expect("moe model");
        let x = Tensor::from_vec(vec![3u32; 24], (2, 12), &Device::Cpu).expect("x");
        let y = Tensor::from_vec(vec![5u32; 24], (2, 12), &Device::Cpu).expect("y");
        let mut rng = Rng::new(7);
        let out = model.forward_step(&x, Some(&y), 0.0, Some(&mut rng)).expect("fwd");
        let loss = out.total_loss.expect("total loss");
        let grads = loss.backward().expect("backward");
        assert!(loss.to_scalar::<f32>().expect("scalar").is_finite());
        assert_eq!(out.expert_counts.len(), cfg.moe.n_experts);
        assert!(out.expert_counts.iter().sum::<usize>() > 0);
        // Router weights must receive non-empty gradients.
        let map = model.varmap.data().lock().unwrap();
        let router_var = map.get("layers.0.moe.router.weight").expect("router var");
        assert!(grads.get(router_var).is_some());
    }
}
