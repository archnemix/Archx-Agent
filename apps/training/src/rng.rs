//! Purpose: Provides cross-platform deterministic PRNG (`SplitMix64`), parameter initializers, shuffles, and token sampling.

use std::f32::consts::TAU;

/// Deterministic 64-bit `SplitMix64` pseudo-random generator.
///
/// Using an explicit portable generator guarantees identical weight tensors,
/// dataset splits, batch ordering, and generation outputs on Linux, Windows,
/// and macOS for the same numeric seed, avoiding `candle`'s unseeded CPU RNG.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Rng {
    state: u64,
}

impl Rng {
    pub fn new(seed: u64) -> Self {
        // Mix zero so seed = 0 still produces a well-dispersed stream.
        Self { state: seed ^ 0x9E37_79B9_7F4A_7C15 }
    }

    /// Forks an independent child stream keyed by `salt`.
    pub fn fork(&self, salt: u64) -> Self {
        let mut copy = self.clone();
        let base = copy.next_u64();
        Self::new(base ^ salt.wrapping_mul(0xBF58_476D_1CE4_E5B9))
    }

    pub fn next_u64(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// Uniform float in `[0.0, 1.0)`.
    pub fn next_f32(&mut self) -> f32 {
        let bits = (self.next_u64() >> 40) as u32;
        (bits as f32) * (1.0 / ((1u32 << 24) as f32))
    }

    /// Uniform float in `[low, high)`.
    pub fn uniform(&mut self, low: f32, high: f32) -> f32 {
        low + (high - low) * self.next_f32()
    }

    /// Standard normal sample via Box-Muller transform.
    pub fn standard_normal(&mut self) -> f32 {
        let u1 = self.next_f32().clamp(1e-7, 1.0 - 1e-7);
        let u2 = self.next_f32();
        (-2.0 * u1.ln()).sqrt() * (TAU * u2).cos()
    }

    pub fn normal_vec(&mut self, count: usize, mean: f32, std: f32) -> Vec<f32> {
        let mut out = Vec::with_capacity(count);
        let mut i = 0;
        while i < count {
            let u1 = self.next_f32().clamp(1e-7, 1.0 - 1e-7);
            let u2 = self.next_f32();
            let r = (-2.0 * u1.ln()).sqrt();
            let theta = TAU * u2;
            out.push(mean + std * r * theta.cos());
            i += 1;
            if i < count {
                out.push(mean + std * r * theta.sin());
                i += 1;
            }
        }
        out
    }

    pub fn xavier_uniform_vec(&mut self, fan_in: usize, fan_out: usize, count: usize, scale: f32) -> Vec<f32> {
        let bound = (6.0 / (fan_in.max(1) + fan_out.max(1)) as f32).sqrt() * scale;
        (0..count).map(|_| self.uniform(-bound, bound)).collect()
    }

    pub fn kaiming_normal_vec(&mut self, fan_in: usize, count: usize, scale: f32) -> Vec<f32> {
        let std = (2.0 / fan_in.max(1) as f32).sqrt() * scale;
        self.normal_vec(count, 0.0, std)
    }

    pub fn usize_below(&mut self, upper: usize) -> usize {
        if upper <= 1 {
            return 0;
        }
        (self.next_u64() % (upper as u64)) as usize
    }

    /// Deterministic Fisher-Yates shuffle.
    pub fn shuffle<T>(&mut self, items: &mut [T]) {
        for i in (1..items.len()).rev() {
            let j = self.usize_below(i + 1);
            items.swap(i, j);
        }
    }

    /// Samples a token index from raw `logits` using repetition penalty,
    /// temperature, top-k, and nucleus (top-p) filtering.
    pub fn sample_logits(
        &mut self,
        logits: &[f32],
        recent_tokens: &[u32],
        temperature: f32,
        top_k: usize,
        top_p: f32,
        repetition_penalty: f32,
    ) -> u32 {
        if logits.is_empty() {
            return 0;
        }
        let mut adjusted = logits.to_vec();
        if (repetition_penalty - 1.0).abs() > 1e-4 {
            let pen = repetition_penalty.max(1.0);
            for &tok in recent_tokens {
                if let Some(val) = adjusted.get_mut(tok as usize) {
                    if *val > 0.0 {
                        *val /= pen;
                    } else {
                        *val *= pen;
                    }
                }
            }
        }

        // Greedy decoding when temperature <= 0.
        if temperature <= 1e-4 {
            return adjusted
                .iter()
                .enumerate()
                .max_by(|a, b| a.1.total_cmp(b.1))
                .map(|(idx, _)| idx as u32)
                .unwrap_or(0);
        }

        let inv_temp = 1.0 / temperature;
        let mut candidates: Vec<(usize, f32)> = adjusted
            .iter()
            .enumerate()
            .filter(|(_, v)| v.is_finite())
            .map(|(i, &v)| (i, v * inv_temp))
            .collect();

        if candidates.is_empty() {
            return 0;
        }

        candidates.sort_by(|a, b| b.1.total_cmp(&a.1));
        if top_k > 0 && candidates.len() > top_k {
            candidates.truncate(top_k);
        }

        let max_logit = candidates[0].1;
        let mut probs: Vec<(usize, f32)> = candidates
            .into_iter()
            .map(|(i, l)| (i, (l - max_logit).exp()))
            .collect();
        let total: f32 = probs.iter().map(|(_, p)| *p).sum::<f32>().max(1e-12);
        for (_, p) in &mut probs {
            *p /= total;
        }

        let clamped_p = top_p.clamp(0.01, 1.0);
        if clamped_p < 0.9999 {
            let mut cum = 0.0;
            let mut cutoff = probs.len();
            for (idx, (_, p)) in probs.iter().enumerate() {
                cum += *p;
                if cum >= clamped_p {
                    cutoff = idx + 1;
                    break;
                }
            }
            probs.truncate(cutoff.max(1));
            let renorm: f32 = probs.iter().map(|(_, p)| *p).sum::<f32>().max(1e-12);
            for (_, p) in &mut probs {
                *p /= renorm;
            }
        }

        let draw = self.next_f32();
        let mut acc = 0.0;
        for &(idx, p) in &probs {
            acc += p;
            if draw <= acc {
                return idx as u32;
            }
        }
        probs.last().map(|&(idx, _)| idx as u32).unwrap_or(0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn same_seed_yields_identical_sequences_and_shuffles() {
        let mut a = Rng::new(42);
        let mut b = Rng::new(42);
        let mut c = Rng::new(43);

        let seq_a = a.normal_vec(16, 0.0, 0.02);
        let seq_b = b.normal_vec(16, 0.0, 0.02);
        let seq_c = c.normal_vec(16, 0.0, 0.02);
        assert_eq!(seq_a, seq_b);
        assert_ne!(seq_a, seq_c);

        let mut s1: Vec<usize> = (0..12).collect();
        let mut s2: Vec<usize> = (0..12).collect();
        a.shuffle(&mut s1);
        b.shuffle(&mut s2);
        assert_eq!(s1, s2);
    }

    #[test]
    fn greedy_and_top_k_sampling_respect_constraints() {
        let mut rng = Rng::new(7);
        let logits = [0.1, 2.5, 4.2, -1.0];
        assert_eq!(rng.sample_logits(&logits, &[], 0.0, 0, 1.0, 1.0), 2);
        // With top_k = 1, only the top logit (index 2) can be drawn regardless of temperature.
        for _ in 0..10 {
            assert_eq!(rng.sample_logits(&logits, &[], 1.2, 1, 1.0, 1.0), 2);
        }
    }
}
