//! Purpose: Cross-platform deterministic PRNG engines (`SplitMix64`, `PCG64-DXSM`, `Xoroshiro128++`, `ChaCha8`), subsystem seed hierarchy, parameter initializers, and token sampling.

use std::f32::consts::TAU;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

/// Selectable cross-hardware deterministic pseudo-random number generator algorithms.
///
/// Every algorithm here is implemented in pure portable integer arithmetic so
/// identical seeds + algorithm produce bit-for-bit identical initial weight
/// tensors on Windows, Linux, and macOS regardless of CPU/GPU vendor RNGs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum PrngAlgorithm {
    #[default]
    SplitMix64,
    Pcg64Dxsm,
    Xoroshiro128PlusPlus,
    ChaCha8Stream,
}

impl PrngAlgorithm {
    pub const ALL: [Self; 4] = [
        Self::SplitMix64,
        Self::Pcg64Dxsm,
        Self::Xoroshiro128PlusPlus,
        Self::ChaCha8Stream,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::SplitMix64 => "SplitMix64 (Fast Bijective)",
            Self::Pcg64Dxsm => "PCG64-DXSM (NumPy 2 Standard)",
            Self::Xoroshiro128PlusPlus => "Xoroshiro128++ (Equidistributed)",
            Self::ChaCha8Stream => "ChaCha8 CSPRNG (Crypto Stream)",
        }
    }

    pub fn description(self) -> &'static str {
        match self {
            Self::SplitMix64 => {
                "64-bit Weyl-sequence Stafford-13 mixer. Ultra-low overhead, passes BigCrush, ideal default for rapid iteration."
            }
            Self::Pcg64Dxsm => {
                "128-bit Permuted Congruential Generator with Double-Xorshift-Multiply output function (adopted by NumPy 2.x for scientific reproducibility)."
            }
            Self::Xoroshiro128PlusPlus => {
                "Blackman & Vigna 128-bit state linear engine with ++ scrambler. High throughput and strong 2D equidistribution."
            }
            Self::ChaCha8Stream => {
                "8-round counter-based cryptographic stream cipher (RFC-7539 core). Guarantees zero linear or spectral correlation across 100M+ weights."
            }
        }
    }
}

/// Hierarchical seed configuration separating master seed from subsystem streams
/// and controlling optional Genesis (`step = 0`) random weight state export/import.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SeedHierarchy {
    #[serde(default)]
    pub algorithm: PrngAlgorithm,
    pub master_seed: u64,
    pub lock_subsystems_to_master: bool,
    pub weight_init_seed: u64,
    pub data_order_seed: u64,
    pub stochastic_seed: u64,
    pub sampling_seed: u64,
    /// When enabled, writes `genesis_step0.safetensors` + `genesis_manifest.json`
    /// containing the exact random-filled weights before gradient step 1 runs.
    pub auto_export_genesis_init: bool,
    /// Optional path to a previously saved `genesis_step0.safetensors` to load
    /// as the exact initial tensor state instead of freshly sampling random numbers.
    #[serde(default)]
    pub genesis_reload_path: String,
}

impl Default for SeedHierarchy {
    fn default() -> Self {
        let mut base = Self {
            algorithm: PrngAlgorithm::SplitMix64,
            master_seed: 42,
            lock_subsystems_to_master: true,
            weight_init_seed: 0,
            data_order_seed: 0,
            stochastic_seed: 0,
            sampling_seed: 42,
            auto_export_genesis_init: true,
            genesis_reload_path: String::new(),
        };
        base.sync_from_master();
        base
    }
}

impl SeedHierarchy {
    pub fn derive_domain_seed(master: u64, domain_tag: u64) -> u64 {
        splitmix64_once(master ^ domain_tag)
    }

    pub fn sync_from_master(&mut self) {
        if self.lock_subsystems_to_master {
            self.weight_init_seed = Self::derive_domain_seed(self.master_seed, 0x5745_4947_4854_5321);
            self.data_order_seed = Self::derive_domain_seed(self.master_seed, 0x4441_5441_4F52_4421);
            self.stochastic_seed = Self::derive_domain_seed(self.master_seed, 0x4452_4F50_4A49_5421);
            self.sampling_seed = Self::derive_domain_seed(self.master_seed, 0x5341_4D50_4C45_5221);
        }
    }

    pub fn effective_weight_seed(&self) -> u64 {
        if self.lock_subsystems_to_master {
            Self::derive_domain_seed(self.master_seed, 0x5745_4947_4854_5321)
        } else {
            self.weight_init_seed
        }
    }

    pub fn effective_data_seed(&self) -> u64 {
        if self.lock_subsystems_to_master {
            Self::derive_domain_seed(self.master_seed, 0x4441_5441_4F52_4421)
        } else {
            self.data_order_seed
        }
    }

    pub fn effective_stochastic_seed(&self) -> u64 {
        if self.lock_subsystems_to_master {
            Self::derive_domain_seed(self.master_seed, 0x4452_4F50_4A49_5421)
        } else {
            self.stochastic_seed
        }
    }

    pub fn effective_sampling_seed(&self) -> u64 {
        if self.lock_subsystems_to_master {
            Self::derive_domain_seed(self.master_seed, 0x5341_4D50_4C45_5221)
        } else {
            self.sampling_seed
        }
    }
}

/// Generates a fresh non-deterministic 64-bit seed when the user clicks "Roll Entropy Seed".
pub fn roll_os_entropy_seed() -> u64 {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0xCAFE_BABE_DEAD_BEEF);
    let stack_addr = (&nanos as *const u64 as usize) as u64;
    splitmix64_once(nanos ^ stack_addr.rotate_left(17)) % 10_000_000_000
}

#[inline]
fn splitmix64_once(x: u64) -> u64 {
    let mut z = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum RngCore {
    SplitMix {
        state: u64,
    },
    Pcg64Dxsm {
        state: u128,
        inc: u128,
    },
    Xoroshiro128PlusPlus {
        s0: u64,
        s1: u64,
    },
    ChaCha8 {
        key: [u32; 8],
        counter: u64,
        buf: [u64; 8],
        idx: usize,
    },
}

/// Deterministic portable pseudo-random generator supporting 4 selectable state engines.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Rng {
    algo: PrngAlgorithm,
    core: RngCore,
}

impl Rng {
    pub fn new(seed: u64) -> Self {
        Self::with_algorithm(seed, PrngAlgorithm::SplitMix64)
    }

    pub fn with_algorithm(seed: u64, algo: PrngAlgorithm) -> Self {
        match algo {
            PrngAlgorithm::SplitMix64 => Self {
                algo,
                core: RngCore::SplitMix {
                    state: seed ^ 0x9E37_79B9_7F4A_7C15,
                },
            },
            PrngAlgorithm::Pcg64Dxsm => {
                let s0 = splitmix64_once(seed);
                let s1 = splitmix64_once(s0 ^ 0xD1B5_4A32_D192_ED03);
                let i0 = splitmix64_once(s1 ^ 0x94D0_49BB_1331_11EB);
                let i1 = splitmix64_once(i0 ^ 0xBF58_476D_1CE4_E5B9) | 1;
                let inc = ((u128::from(i0)) << 64) | u128::from(i1);
                let init_state = ((u128::from(s0)) << 64) | u128::from(s1);
                let mut rng = Self {
                    algo,
                    core: RngCore::Pcg64Dxsm {
                        state: 0,
                        inc,
                    },
                };
                let _ = rng.next_u64();
                if let RngCore::Pcg64Dxsm { state, .. } = &mut rng.core {
                    *state = state.wrapping_add(init_state);
                }
                let _ = rng.next_u64();
                rng
            }
            PrngAlgorithm::Xoroshiro128PlusPlus => {
                let mut s0 = splitmix64_once(seed);
                let mut s1 = splitmix64_once(s0 ^ 0x6A09_E667_F3BC_C908);
                if s0 == 0 && s1 == 0 {
                    s0 = 0x9E37_79B9_7F4A_7C15;
                    s1 = 0xBF58_476D_1CE4_E5B9;
                }
                Self {
                    algo,
                    core: RngCore::Xoroshiro128PlusPlus { s0, s1 },
                }
            }
            PrngAlgorithm::ChaCha8Stream => {
                let mut key = [0u32; 8];
                let mut cur = seed ^ 0x4348_4143_4841_3821;
                for pair in key.chunks_exact_mut(2) {
                    cur = splitmix64_once(cur);
                    pair[0] = cur as u32;
                    pair[1] = (cur >> 32) as u32;
                }
                let mut out = Self {
                    algo,
                    core: RngCore::ChaCha8 {
                        key,
                        counter: 0,
                        buf: [0u64; 8],
                        idx: 8,
                    },
                };
                let _ = out.next_u64();
                out
            }
        }
    }

    pub fn algorithm(&self) -> PrngAlgorithm {
        self.algo
    }

    /// Forks an independent child stream keyed by `salt`, preserving the active algorithm.
    pub fn fork(&self, salt: u64) -> Self {
        let mut copy = self.clone();
        let base = copy.next_u64();
        Self::with_algorithm(base ^ salt.wrapping_mul(0xBF58_476D_1CE4_E5B9), self.algo)
    }

    pub fn next_u64(&mut self) -> u64 {
        match &mut self.core {
            RngCore::SplitMix { state } => {
                *state = state.wrapping_add(0x9E37_79B9_7F4A_7C15);
                let mut z = *state;
                z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
                z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
                z ^ (z >> 31)
            }
            RngCore::Pcg64Dxsm { state, inc } => {
                const MUL: u64 = 15_750_249_268_501_108_917;
                let old = *state;
                *state = old
                    .wrapping_mul(u128::from(MUL))
                    .wrapping_add(*inc | 1);
                let mut hi = (old >> 64) as u64;
                let lo = (old as u64) | 1;
                hi ^= hi >> 32;
                hi = hi.wrapping_mul(MUL);
                hi ^= hi >> 48;
                hi = hi.wrapping_mul(lo);
                hi
            }
            RngCore::Xoroshiro128PlusPlus { s0, s1 } => {
                let result = s0.wrapping_add(*s1).rotate_left(17).wrapping_add(*s0);
                let t = *s1 ^ *s0;
                *s0 = s0.rotate_left(49) ^ t ^ (t << 21);
                *s1 = t.rotate_left(28);
                result
            }
            RngCore::ChaCha8 {
                key,
                counter,
                buf,
                idx,
            } => {
                if *idx >= 8 {
                    *buf = chacha8_block(key, *counter);
                    *counter = counter.wrapping_add(1);
                    *idx = 0;
                }
                let val = buf[*idx];
                *idx += 1;
                val
            }
        }
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

    /// Truncated Gaussian initializer rejecting draws outside `[-clip_sigma * std, +clip_sigma * std]`.
    pub fn truncated_normal_vec(
        &mut self,
        count: usize,
        mean: f32,
        std: f32,
        clip_sigma: f32,
    ) -> Vec<f32> {
        let bound = clip_sigma.clamp(1.0, 5.0);
        let mut out = Vec::with_capacity(count);
        while out.len() < count {
            let z = self.standard_normal();
            if z.abs() <= bound {
                out.push(mean + std * z);
            }
        }
        out
    }

    pub fn xavier_uniform_vec(
        &mut self,
        fan_in: usize,
        fan_out: usize,
        count: usize,
        scale: f32,
    ) -> Vec<f32> {
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

#[inline]
fn quarter_round(state: &mut [u32; 16], a: usize, b: usize, c: usize, d: usize) {
    state[a] = state[a].wrapping_add(state[b]);
    state[d] = (state[d] ^ state[a]).rotate_left(16);
    state[c] = state[c].wrapping_add(state[d]);
    state[b] = (state[b] ^ state[c]).rotate_left(12);
    state[a] = state[a].wrapping_add(state[b]);
    state[d] = (state[d] ^ state[a]).rotate_left(8);
    state[c] = state[c].wrapping_add(state[d]);
    state[b] = (state[b] ^ state[c]).rotate_left(7);
}

fn chacha8_block(key: &[u32; 8], counter: u64) -> [u64; 8] {
    let initial: [u32; 16] = [
        0x6170_7865,
        0x3320_646E,
        0x7962_2D32,
        0x6B20_6574,
        key[0],
        key[1],
        key[2],
        key[3],
        key[4],
        key[5],
        key[6],
        key[7],
        counter as u32,
        (counter >> 32) as u32,
        0x4152_4348,
        0x5852_4E47,
    ];
    let mut working = initial;
    for _ in 0..4 {
        // Column rounds
        quarter_round(&mut working, 0, 4, 8, 12);
        quarter_round(&mut working, 1, 5, 9, 13);
        quarter_round(&mut working, 2, 6, 10, 14);
        quarter_round(&mut working, 3, 7, 11, 15);
        // Diagonal rounds
        quarter_round(&mut working, 0, 5, 10, 15);
        quarter_round(&mut working, 1, 6, 11, 12);
        quarter_round(&mut working, 2, 7, 8, 13);
        quarter_round(&mut working, 3, 4, 9, 14);
    }
    for (w, &init) in working.iter_mut().zip(&initial) {
        *w = w.wrapping_add(init);
    }
    let mut out = [0u64; 8];
    for (i, slot) in out.iter_mut().enumerate() {
        *slot = u64::from(working[2 * i]) | (u64::from(working[2 * i + 1]) << 32);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn same_seed_yields_identical_sequences_across_all_four_prng_engines() {
        for algo in PrngAlgorithm::ALL {
            let mut a = Rng::with_algorithm(42, algo);
            let mut b = Rng::with_algorithm(42, algo);
            let mut c = Rng::with_algorithm(43, algo);

            let seq_a = a.normal_vec(32, 0.0, 0.02);
            let seq_b = b.normal_vec(32, 0.0, 0.02);
            let seq_c = c.normal_vec(32, 0.0, 0.02);
            assert_eq!(seq_a, seq_b, "determinism failed for {:?}", algo);
            assert_ne!(seq_a, seq_c, "seed sensitivity failed for {:?}", algo);
        }

        // Distinct PRNG engines must produce distinct streams even for seed = 42.
        let sm = Rng::with_algorithm(42, PrngAlgorithm::SplitMix64).normal_vec(8, 0.0, 1.0);
        let pcg = Rng::with_algorithm(42, PrngAlgorithm::Pcg64Dxsm).normal_vec(8, 0.0, 1.0);
        let xoro = Rng::with_algorithm(42, PrngAlgorithm::Xoroshiro128PlusPlus).normal_vec(8, 0.0, 1.0);
        let cc8 = Rng::with_algorithm(42, PrngAlgorithm::ChaCha8Stream).normal_vec(8, 0.0, 1.0);
        assert_ne!(sm, pcg);
        assert_ne!(pcg, xoro);
        assert_ne!(xoro, cc8);
    }

    #[test]
    fn truncated_normal_respects_sigma_clip_and_seed_hierarchy_separates_domains() {
        let mut rng = Rng::with_algorithm(99, PrngAlgorithm::ChaCha8Stream);
        let vals = rng.truncated_normal_vec(512, 0.0, 0.02, 2.0);
        assert!(vals.iter().all(|v| v.abs() <= 0.04 + 1e-6));

        let seeds = SeedHierarchy::default();
        assert_ne!(seeds.effective_weight_seed(), seeds.effective_data_seed());
        assert_ne!(seeds.effective_weight_seed(), seeds.effective_stochastic_seed());
        assert_ne!(seeds.effective_data_seed(), seeds.effective_sampling_seed());
    }

    #[test]
    fn greedy_and_top_k_sampling_respect_constraints() {
        let mut rng = Rng::new(7);
        let logits = [0.1, 2.5, 4.2, -1.0];
        assert_eq!(rng.sample_logits(&logits, &[], 0.0, 0, 1.0, 1.0), 2);
        for _ in 0..10 {
            assert_eq!(rng.sample_logits(&logits, &[], 1.2, 1, 1.0, 1.0), 2);
        }
    }
}
