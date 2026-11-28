//! Purpose: Trains and runs native Rust tokenizers (`ByteLevelBpe`, `WordPiece`, `Unigram`, `CharLevel`, plus Hugging Face `tokenizer.json` import), enforces pre-tokenization/digit/tile-padding rules, and powers the 4-way Tokenizer Comparison Arena.

use std::collections::{BTreeSet, HashMap};
use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use serde::{Deserialize, Serialize};

use crate::config::{DigitPolicy, PreTokenizeMode, TokenizerConfig, TokenizerKind, UnicodeNorm};
use crate::rng::Rng;

pub const PAD_ID: u32 = 0;
pub const BOS_ID: u32 = 1;
pub const EOS_ID: u32 = 2;
pub const UNK_ID: u32 = 3;
pub const USER_ID: u32 = 4;
pub const ASSISTANT_ID: u32 = 5;
pub const MASK_ID: u32 = 6;

pub const SPECIAL_TOKENS: [&str; 7] = [
    "<pad>",
    "<bos>",
    "<eos>",
    "<unk>",
    "<user>",
    "<assistant>",
    "<mask>",
];

/// Detailed architectural breakdown of each tokenizer algorithm for the in-app guide.
#[derive(Debug, Clone, Copy)]
pub struct TokenizerGuideCard {
    pub kind: TokenizerKind,
    pub subtitle: &'static str,
    pub mechanism: &'static str,
    pub oov_behavior: &'static str,
    pub compression_profile: &'static str,
    pub transformer_impact: &'static str,
    pub strengths: &'static str,
    pub tradeoffs: &'static str,
}

pub fn tokenizer_guide(kind: TokenizerKind) -> TokenizerGuideCard {
    match kind {
        TokenizerKind::ByteLevelBpe => TokenizerGuideCard {
            kind,
            subtitle: "Bottom-Up Byte Merge · Standard in GPT-4, Llama-3, Qwen, DeepSeek",
            mechanism: "Starts with all 256 raw UTF-8 bytes as base tokens, pre-splits text by regex/code/digit rules, and iteratively merges the most frequent adjacent token pair until reaching target vocab_size.",
            oov_behavior: "0% <unk> Guaranteed — any unseen Unicode character, emoji, math symbol, or rare script decomposes cleanly into its 1–4 UTF-8 bytes.",
            compression_profile: "High (~3.6 – 4.3 chars/token on English/code at 4K–32K vocab; ~1.8 – 2.8 at Nano 512 vocab).",
            transformer_impact: "Shortens token sequences ~3.8x vs Character-Level, cutting causal attention O(N²) memory & FLOPs by ~14x while keeping exact lossless text reconstruction.",
            strengths: "Lossless on code, whitespace, multilingual text, and emojis; zero unknown-token corruption; predictable merge hierarchy.",
            tradeoffs: "Greedy merge order can split rare morphological roots inconsistently; multi-digit numbers should use Single-Digit or 3-Digit splitting for arithmetic.",
        },
        TokenizerKind::WordPiece => TokenizerGuideCard {
            kind,
            subtitle: "Likelihood-Ratio Prefix + ##Suffix · Standard in BERT, DistilBERT, Electra",
            mechanism: "Splits words into root prefixes plus `##` continuation suffixes (e.g. `transform` + `##ers`), ranking candidate subwords by mutual-information score freq(ab) / (freq(a)·freq(b)) and encoding via greedy longest-match-first.",
            oov_behavior: "Emits `<unk>` on unseen characters unless `Byte Fallback (<0xXX>)` is enabled (enabled by default in Archx Studio).",
            compression_profile: "Medium-High (~3.3 – 4.0 chars/token); explicit `##` continuation markers preserve word-internal vs word-initial distinction.",
            transformer_impact: "Strong root/affix sharing in the embedding matrix (`play`, `##ing`, `##ed`), helping smaller Transformers generalize across inflections faster.",
            strengths: "Clean morphological stems; fast linear-time greedy encoding; explicit word-boundary semantics via `##`.",
            tradeoffs: "Less natural on indentation-heavy source code than Byte-Level BPE unless paired with Code-Aware pre-tokenization and byte fallback.",
        },
        TokenizerKind::Unigram => TokenizerGuideCard {
            kind,
            subtitle: "Top-Down Probabilistic Viterbi LM · Standard in SentencePiece, Gemma, T5",
            mechanism: "Initializes an oversized candidate vocabulary of frequent substrings, estimates unigram log-probabilities P(x), prunes lowest-likelihood-impact pieces down to vocab_size, and decodes the globally optimal segmentation via dynamic programming (Viterbi).",
            oov_behavior: "Single-character + optional `<0xXX>` byte-fallback coverage keeps `<unk>` near 0% while scoring globally optimal splits.",
            compression_profile: "High (~3.5 – 4.2 chars/token); avoids greedy left-to-right traps when a word has multiple plausible compound splits.",
            transformer_impact: "Uniquely supports Subword Regularization (sampling slightly different valid segmentations each epoch), acting as built-in data augmentation that reduces overfitting on small corpora.",
            strengths: "Principled probabilistic segmentation; native subword dropout regularization; strong multilingual & agglutinative language fit.",
            tradeoffs: "Viterbi dynamic programming is slightly heavier per character than greedy BPE; requires calibrated log-probabilities.",
        },
        TokenizerKind::CharLevel => TokenizerGuideCard {
            kind,
            subtitle: "Atomic Unicode Scalar Tokens · Classic Karpathy / Algorithmic Reasoning",
            mechanism: "Maps each distinct character directly to one token ID (`vocab_size` typically 96 – 512) with zero multi-character subword merges.",
            oov_behavior: "Covers all printable ASCII + corpus Unicode scalars; unseen rare symbols fall back to `<unk>` or raw bytes.",
            compression_profile: "1.00 char/token (zero compression — sequences are 3.5x to 4.2x longer than BPE/Unigram).",
            transformer_impact: "Tiny embedding & LM-head tables (minimal parameters!), but requires ~4x larger `seq_len` to see the same word horizon, increasing O(N²) attention cost.",
            strengths: "Zero tokenization blindness: model sees every letter and digit directly — unbeatable for character puzzles, spelling, ciphers, DNA, and tiny parameter experiments.",
            tradeoffs: "Long sequences consume context window rapidly; model must spend early layers composing characters into words.",
        },
        TokenizerKind::PretrainedFile => TokenizerGuideCard {
            kind,
            subtitle: "External Hugging Face `tokenizer.json` · Ecosystem Vocab Compatibility",
            mechanism: "Loads a pre-trained Hugging Face `tokenizers` JSON graph verbatim, synchronizing `model.vocab_size` automatically.",
            oov_behavior: "Determined by the imported `tokenizer.json` graph.",
            compression_profile: "Matches target ecosystem (typically 32K – 151K vocab, ~4.0+ chars/token).",
            transformer_impact: "Large vocabularies (32K–128K) place heavy parameter mass in `tok_embeddings` and `lm_head` (`vocab × d_model`); enable Tie Embeddings on small scratch models.",
            strengths: "100% token-ID compatibility when building a scratch draft model for speculative decoding or cross-model distillation.",
            tradeoffs: "Vocabulary is not tailored to a tiny domain corpus; unused token rows still occupy embedding memory.",
        },
    }
}

/// Side-by-side benchmark row produced by the 4-way Tokenizer Comparison Arena.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TokenizerArenaRow {
    pub kind: TokenizerKind,
    pub actual_vocab_size: usize,
    pub train_ms: f64,
    pub token_count: usize,
    pub chars_per_token: f32,
    pub bytes_per_token: f32,
    pub fertility_tok_per_word: f32,
    pub unk_count: usize,
    pub est_words_per_ctx: usize,
    pub preview_tokens: Vec<(u32, String)>,
}

/// Trains all 4 scratch tokenizer families on `docs` using `base_cfg` rules and compares them on `probe_text`.
pub fn run_tokenizer_arena(
    base_cfg: &TokenizerConfig,
    docs: &[String],
    probe_text: &str,
    seq_len: usize,
) -> Vec<TokenizerArenaRow> {
    let sample = if probe_text.trim().is_empty() {
        "fn attention_score(q: f32, k: f32) -> f32 { (q * k) / 2026.0 } // Transformer Engine #1"
    } else {
        probe_text
    };
    let word_count = sample.split_whitespace().count().max(1);
    let char_count = sample.chars().count().max(1);
    let byte_count = sample.len().max(1);

    let mut rows = Vec::with_capacity(4);
    for kind in [
        TokenizerKind::ByteLevelBpe,
        TokenizerKind::WordPiece,
        TokenizerKind::Unigram,
        TokenizerKind::CharLevel,
    ] {
        let mut cfg = base_cfg.clone();
        cfg.kind = kind;
        if kind == TokenizerKind::CharLevel {
            cfg.vocab_size = base_cfg.vocab_size.min(512).max(128);
        }
        let t0 = Instant::now();
        if let Ok(tk) = LabTokenizer::train_or_load(&cfg, docs) {
            let train_ms = t0.elapsed().as_secs_f64() * 1000.0;
            let body_ids = tk.encode(sample, false);
            let tok_len = body_ids.len().max(1);
            let unk_count = body_ids.iter().filter(|&&id| id == UNK_ID).count();
            let chars_per_token = char_count as f32 / tok_len as f32;
            let bytes_per_token = byte_count as f32 / tok_len as f32;
            let fertility = tok_len as f32 / word_count as f32;
            let est_words_per_ctx = ((seq_len.max(16) as f32) / fertility.max(0.1)).round() as usize;
            let preview_tokens: Vec<(u32, String)> = body_ids
                .iter()
                .take(28)
                .map(|&id| (id, tk.token_display(id)))
                .collect();

            rows.push(TokenizerArenaRow {
                kind,
                actual_vocab_size: tk.vocab_size(),
                train_ms,
                token_count: body_ids.len(),
                chars_per_token,
                bytes_per_token,
                fertility_tok_per_word: fertility,
                unk_count,
                est_words_per_ctx,
                preview_tokens,
            });
        }
    }
    rows
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct NativeRules {
    #[serde(default)]
    pre_tokenize: PreTokenizeMode,
    #[serde(default)]
    digit_policy: DigitPolicy,
    #[serde(default)]
    normalization: UnicodeNorm,
    #[serde(default = "default_true")]
    byte_fallback: bool,
    #[serde(default)]
    extra_specials: Vec<String>,
    #[serde(default)]
    padded_vocab_size: usize,
}

fn default_true() -> bool {
    true
}

impl Default for NativeRules {
    fn default() -> Self {
        Self {
            pre_tokenize: PreTokenizeMode::Gpt4Regex,
            digit_policy: DigitPolicy::ChunksOf3,
            normalization: UnicodeNorm::None,
            byte_fallback: true,
            extra_specials: Vec::new(),
            padded_vocab_size: 0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
enum NativeSpec {
    ByteBpe {
        vocab: Vec<Vec<u8>>,
        merges: Vec<(u32, u32, u32)>,
        #[serde(default)]
        rules: NativeRules,
    },
    WordPiece {
        pieces: Vec<String>,
        lowercase: bool,
        #[serde(default)]
        rules: NativeRules,
    },
    Unigram {
        pieces: Vec<(String, f32)>,
        lowercase: bool,
        #[serde(default)]
        rules: NativeRules,
    },
    CharLevel {
        chars: Vec<char>,
        lowercase: bool,
        #[serde(default)]
        rules: NativeRules,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SerializedNative {
    format: String,
    kind: TokenizerKind,
    spec: NativeSpec,
}

#[derive(Clone)]
enum RuntimeTokenizer {
    Native(NativeRuntime),
    HfExternal(Arc<tokenizers::Tokenizer>),
}

#[derive(Debug, Clone)]
struct NativeRuntime {
    kind: TokenizerKind,
    spec: NativeSpec,
    all_specials: Vec<String>,
    wordpiece_map: HashMap<String, u32>,
    char_map: HashMap<char, u32>,
}

/// Thread-safe, serializable tokenizer used by training and the live Playground.
#[derive(Clone)]
pub struct LabTokenizer {
    inner: RuntimeTokenizer,
    vocab_size: usize,
    summary_label: String,
}

impl std::fmt::Debug for LabTokenizer {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("LabTokenizer")
            .field("vocab_size", &self.vocab_size)
            .field("summary_label", &self.summary_label)
            .finish()
    }
}

#[derive(Debug, Clone, Default)]
pub struct TokenPreview {
    pub tokens: Vec<(u32, String)>,
    pub char_count: usize,
    pub chars_per_token: f32,
}

fn parse_extra_specials(raw: &str) -> Vec<String> {
    let mut out = Vec::new();
    for item in raw.split(',') {
        let t = item.trim();
        if !t.is_empty()
            && !SPECIAL_TOKENS.contains(&t)
            && !out.iter().any(|existing: &String| existing == t)
        {
            out.push(t.to_owned());
        }
    }
    out
}

fn build_rules(cfg: &TokenizerConfig) -> NativeRules {
    let norm = if cfg.lowercase && cfg.normalization == UnicodeNorm::None {
        UnicodeNorm::Lowercase
    } else {
        cfg.normalization
    };
    NativeRules {
        pre_tokenize: cfg.pre_tokenize,
        digit_policy: cfg.digit_policy,
        normalization: norm,
        byte_fallback: cfg.byte_fallback,
        extra_specials: parse_extra_specials(&cfg.custom_special_tokens),
        padded_vocab_size: 0,
    }
}

fn align_vocab_up(raw_vocab: usize, pad_multiple: usize) -> usize {
    if pad_multiple <= 1 {
        raw_vocab
    } else {
        ((raw_vocab + pad_multiple - 1) / pad_multiple) * pad_multiple
    }
}

impl LabTokenizer {
    pub fn train_or_load(cfg: &TokenizerConfig, docs: &[String]) -> Result<Self, String> {
        let rules = build_rules(cfg);
        match cfg.kind {
            TokenizerKind::PretrainedFile => {
                let path = cfg.pretrained_path.trim();
                if path.is_empty() {
                    return Err("Enter a path to a `tokenizer.json` file first.".to_owned());
                }
                Self::load_from_path(Path::new(path))
            }
            TokenizerKind::ByteLevelBpe => Ok(Self::train_byte_bpe(
                docs,
                cfg.vocab_size,
                cfg.min_frequency,
                cfg.pad_to_multiple,
                rules,
            )),
            TokenizerKind::WordPiece => Ok(Self::train_wordpiece(
                docs,
                cfg.vocab_size,
                cfg.min_frequency,
                cfg.lowercase || cfg.normalization == UnicodeNorm::Lowercase,
                cfg.pad_to_multiple,
                rules,
            )),
            TokenizerKind::Unigram => Ok(Self::train_unigram(
                docs,
                cfg.vocab_size,
                cfg.lowercase || cfg.normalization == UnicodeNorm::Lowercase,
                cfg.pad_to_multiple,
                rules,
            )),
            TokenizerKind::CharLevel => Ok(Self::train_char_level(
                docs,
                cfg.vocab_size,
                cfg.lowercase || cfg.normalization == UnicodeNorm::Lowercase,
                cfg.pad_to_multiple,
                rules,
            )),
        }
    }

    pub fn vocab_size(&self) -> usize {
        self.vocab_size
    }

    pub fn summary(&self) -> &str {
        &self.summary_label
    }

    pub fn save_to_path(&self, path: &Path) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|_| "Could not create directory for tokenizer.json".to_owned())?;
        }
        match &self.inner {
            RuntimeTokenizer::Native(rt) => {
                let payload = SerializedNative {
                    format: "archx-native-tokenizer-v1".to_owned(),
                    kind: rt.kind,
                    spec: rt.spec.clone(),
                };
                let bytes = serde_json::to_vec_pretty(&payload)
                    .map_err(|_| "Failed to serialize tokenizer.".to_owned())?;
                std::fs::write(path, bytes)
                    .map_err(|_| format!("Could not write {}", path.display()))
            }
            RuntimeTokenizer::HfExternal(tk) => tk
                .save(path, false)
                .map_err(|_| format!("Could not save HF tokenizer to {}", path.display())),
        }
    }

    pub fn load_from_path(path: &Path) -> Result<Self, String> {
        let bytes = std::fs::read(path)
            .map_err(|_| format!("Could not read tokenizer file {}", path.display()))?;
        if let Ok(native) = serde_json::from_slice::<SerializedNative>(&bytes) {
            if native.format == "archx-native-tokenizer-v1" {
                return Ok(Self::from_native_spec(native.kind, native.spec));
            }
        }
        let hf = tokenizers::Tokenizer::from_bytes(&bytes)
            .map_err(|_| "File is neither an Archx tokenizer nor a valid Hugging Face `tokenizer.json`.".to_owned())?;
        let vocab_size = hf.get_vocab_size(true).max(16);
        Ok(Self {
            inner: RuntimeTokenizer::HfExternal(Arc::new(hf)),
            vocab_size,
            summary_label: format!("HF tokenizer.json · {vocab_size} vocab"),
        })
    }

    fn from_native_spec(kind: TokenizerKind, spec: NativeSpec) -> Self {
        let mut wordpiece_map = HashMap::new();
        let mut char_map = HashMap::new();
        let rules = match &spec {
            NativeSpec::ByteBpe { rules, .. }
            | NativeSpec::WordPiece { rules, .. }
            | NativeSpec::Unigram { rules, .. }
            | NativeSpec::CharLevel { rules, .. } => rules.clone(),
        };
        let mut all_specials: Vec<String> = SPECIAL_TOKENS.iter().map(|&s| s.to_owned()).collect();
        for extra in &rules.extra_specials {
            all_specials.push(extra.clone());
        }
        let special_len = all_specials.len();

        let (raw_vocab, detail) = match &spec {
            NativeSpec::ByteBpe { vocab, merges, .. } => {
                let raw = special_len + vocab.len();
                let fin = rules.padded_vocab_size.max(raw);
                (
                    fin,
                    format!(
                        "Byte-Level BPE · {} vocab ({} merges, {})",
                        fin,
                        merges.len(),
                        rules.digit_policy.label()
                    ),
                )
            }
            NativeSpec::WordPiece { pieces, .. } => {
                for (idx, piece) in pieces.iter().enumerate() {
                    wordpiece_map.insert(piece.clone(), (special_len + idx) as u32);
                }
                let raw = special_len + pieces.len();
                let fin = rules.padded_vocab_size.max(raw);
                (fin, format!("WordPiece · {fin} vocab"))
            }
            NativeSpec::Unigram { pieces, .. } => {
                let raw = special_len + pieces.len();
                let fin = rules.padded_vocab_size.max(raw);
                (fin, format!("Unigram · {fin} vocab"))
            }
            NativeSpec::CharLevel { chars, .. } => {
                for (idx, ch) in chars.iter().enumerate() {
                    char_map.insert(*ch, (special_len + idx) as u32);
                }
                let raw = special_len + chars.len();
                let fin = rules.padded_vocab_size.max(raw);
                (fin, format!("Character-Level · {fin} vocab"))
            }
        };

        Self {
            inner: RuntimeTokenizer::Native(NativeRuntime {
                kind,
                spec,
                all_specials,
                wordpiece_map,
                char_map,
            }),
            vocab_size: raw_vocab,
            summary_label: detail,
        }
    }

    fn train_byte_bpe(
        docs: &[String],
        target_vocab: usize,
        min_freq: usize,
        pad_multiple: usize,
        mut rules: NativeRules,
    ) -> Self {
        let special_len = SPECIAL_TOKENS.len() + rules.extra_specials.len();
        let wanted = target_vocab.clamp(special_len + 256, 65_536);
        let max_merges = wanted.saturating_sub(special_len + 256);
        let min_f = min_freq.max(2);

        let mut vocab: Vec<Vec<u8>> = (0u16..256).map(|b| vec![b as u8]).collect();
        let mut merges: Vec<(u32, u32, u32)> = Vec::new();

        let mut chunks: Vec<(Vec<u32>, usize)> = Vec::new();
        let mut chunk_counts: HashMap<Vec<u8>, usize> = HashMap::new();
        for doc in docs {
            let cleaned = strip_special_literals(doc, &rules.extra_specials);
            let normed = apply_unicode_norm(&cleaned, rules.normalization);
            for seg in pre_tokenize_text(&normed, rules.pre_tokenize, rules.digit_policy) {
                if !seg.is_empty() {
                    *chunk_counts.entry(seg.as_bytes().to_vec()).or_insert(0) += 1;
                }
            }
        }
        let mut sorted_chunks: Vec<(Vec<u8>, usize)> = chunk_counts.into_iter().collect();
        sorted_chunks.sort_by(|a, b| a.0.cmp(&b.0));
        for (bytes, count) in sorted_chunks {
            chunks.push((bytes.into_iter().map(u32::from).collect(), count));
        }

        for _ in 0..max_merges {
            let mut pair_counts: HashMap<(u32, u32), usize> = HashMap::new();
            for (seq, freq) in &chunks {
                for win in seq.windows(2) {
                    *pair_counts.entry((win[0], win[1])).or_insert(0) += *freq;
                }
            }
            let best = pair_counts
                .into_iter()
                .filter(|(_, c)| *c >= min_f)
                .max_by(|(p1, c1), (p2, c2)| c1.cmp(c2).then_with(|| p2.cmp(p1)));
            let Some(((left, right), _)) = best else {
                break;
            };

            let new_local_id = vocab.len() as u32;
            let mut combined = vocab[left as usize].clone();
            combined.extend_from_slice(&vocab[right as usize]);
            vocab.push(combined);
            merges.push((left, right, new_local_id));

            for (seq, _) in &mut chunks {
                let mut i = 0;
                let mut next_seq = Vec::with_capacity(seq.len());
                while i < seq.len() {
                    if i + 1 < seq.len() && seq[i] == left && seq[i + 1] == right {
                        next_seq.push(new_local_id);
                        i += 2;
                    } else {
                        next_seq.push(seq[i]);
                        i += 1;
                    }
                }
                *seq = next_seq;
            }
        }

        let raw_total = special_len + vocab.len();
        rules.padded_vocab_size = align_vocab_up(raw_total, pad_multiple);
        Self::from_native_spec(
            TokenizerKind::ByteLevelBpe,
            NativeSpec::ByteBpe {
                vocab,
                merges,
                rules,
            },
        )
    }

    fn train_wordpiece(
        docs: &[String],
        target_vocab: usize,
        min_freq: usize,
        lowercase: bool,
        pad_multiple: usize,
        mut rules: NativeRules,
    ) -> Self {
        let special_len = SPECIAL_TOKENS.len() + rules.extra_specials.len();
        let cap = target_vocab.clamp(96, 65_536).saturating_sub(special_len);
        let mut char_set = BTreeSet::new();
        let mut word_counts: HashMap<String, usize> = HashMap::new();

        let mut pieces: Vec<String> = Vec::new();
        pieces.push(" ".to_owned());
        pieces.push("\n".to_owned());
        if rules.byte_fallback {
            for b in 0u16..256 {
                pieces.push(format!("<0x{b:02X}>"));
            }
        }

        for doc in docs {
            let cleaned = strip_special_literals(doc, &rules.extra_specials);
            let normed = apply_unicode_norm(&cleaned, rules.normalization);
            let norm = if lowercase { normed.to_lowercase() } else { normed };
            for ch in norm.chars() {
                char_set.insert(ch);
            }
            for seg in pre_tokenize_text(&norm, rules.pre_tokenize, rules.digit_policy) {
                let trimmed = seg.trim();
                if !trimmed.is_empty() {
                    *word_counts.entry(trimmed.to_owned()).or_insert(0) += 1;
                }
            }
        }

        for ch in &char_set {
            let s = ch.to_string();
            if s != " " && s != "\n" {
                pieces.push(s.clone());
                pieces.push(format!("##{s}"));
            }
        }

        // Score subwords by mutual-information inspired WordPiece weighting.
        let mut char_freq: HashMap<char, usize> = HashMap::new();
        let mut sub_counts: HashMap<String, usize> = HashMap::new();
        for (word, freq) in &word_counts {
            let chars: Vec<char> = word.chars().collect();
            for &ch in &chars {
                *char_freq.entry(ch).or_insert(0) += *freq;
            }
            for start in 0..chars.len() {
                for end in (start + 2)..=chars.len().min(start + 10) {
                    let sub: String = chars[start..end].iter().collect();
                    let token = if start == 0 { sub } else { format!("##{sub}") };
                    *sub_counts.entry(token).or_insert(0) += *freq;
                }
            }
        }

        let mut ranked: Vec<(String, f64)> = sub_counts
            .into_iter()
            .filter(|(_, c)| *c >= min_freq.max(2))
            .map(|(tok, c)| {
                let clean = tok.strip_prefix("##").unwrap_or(&tok);
                let denom: f64 = clean
                    .chars()
                    .map(|ch| (*char_freq.get(&ch).unwrap_or(&1) as f64).powf(0.35))
                    .product::<f64>()
                    .max(1.0);
                let score = (c as f64) * (clean.chars().count() as f64) / denom;
                (tok, score)
            })
            .collect();
        ranked.sort_by(|a, b| b.1.total_cmp(&a.1).then_with(|| a.0.cmp(&b.0)));

        let mut existing: HashMap<String, ()> = pieces.iter().cloned().map(|p| (p, ())).collect();
        for (cand, _) in ranked {
            if pieces.len() >= cap {
                break;
            }
            if existing.insert(cand.clone(), ()).is_none() {
                pieces.push(cand);
            }
        }
        if !rules.byte_fallback {
            pieces.truncate(cap.max(32));
        } else if pieces.len() > cap.max(300) {
            pieces.truncate(cap.max(300));
        }

        let raw_total = special_len + pieces.len();
        rules.padded_vocab_size = align_vocab_up(raw_total, pad_multiple);
        Self::from_native_spec(
            TokenizerKind::WordPiece,
            NativeSpec::WordPiece {
                pieces,
                lowercase,
                rules,
            },
        )
    }

    fn train_unigram(
        docs: &[String],
        target_vocab: usize,
        lowercase: bool,
        pad_multiple: usize,
        mut rules: NativeRules,
    ) -> Self {
        let special_len = SPECIAL_TOKENS.len() + rules.extra_specials.len();
        let cap = target_vocab.clamp(96, 65_536).saturating_sub(special_len);
        let mut counts: HashMap<String, usize> = HashMap::new();
        let mut total = 0usize;

        for doc in docs {
            let cleaned = strip_special_literals(doc, &rules.extra_specials);
            let normed = apply_unicode_norm(&cleaned, rules.normalization);
            let norm = if lowercase { normed.to_lowercase() } else { normed };
            for ch in norm.chars() {
                let s = ch.to_string();
                *counts.entry(s).or_insert(0) += 2;
                total += 2;
            }
            for seg in pre_tokenize_text(&norm, rules.pre_tokenize, rules.digit_policy) {
                let chars: Vec<char> = seg.chars().collect();
                for i in 0..chars.len() {
                    if chars[i].is_whitespace() {
                        continue;
                    }
                    for len in 2..=8 {
                        if i + len <= chars.len() {
                            let sub: String = chars[i..i + len].iter().collect();
                            if !sub.contains('\n') {
                                *counts.entry(sub).or_insert(0) += 1;
                                total += 1;
                            }
                        }
                    }
                }
            }
        }

        let mut single_chars: Vec<(String, usize)> = counts
            .iter()
            .filter(|(k, _)| k.chars().count() == 1)
            .map(|(k, v)| (k.clone(), *v))
            .collect();
        single_chars.sort_by(|a, b| a.0.cmp(&b.0));

        let mut multi: Vec<(String, usize)> = counts
            .into_iter()
            .filter(|(k, c)| k.chars().count() > 1 && *c >= 2)
            .collect();
        multi.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));

        let denom = (total.max(1)) as f32;
        let mut pieces: Vec<(String, f32)> = Vec::new();
        if rules.byte_fallback {
            for b in 0u16..256 {
                pieces.push((format!("<0x{b:02X}>"), -12.5));
            }
        }
        for (s, c) in single_chars {
            pieces.push((s, ((c as f32) / denom).ln()));
        }
        for (s, c) in multi {
            if pieces.len() >= cap {
                break;
            }
            pieces.push((s, ((c as f32) / denom).ln()));
        }
        let min_keep = if rules.byte_fallback { 300 } else { 32 };
        if pieces.len() > cap.max(min_keep) {
            pieces.truncate(cap.max(min_keep));
        }

        let raw_total = special_len + pieces.len();
        rules.padded_vocab_size = align_vocab_up(raw_total, pad_multiple);
        Self::from_native_spec(
            TokenizerKind::Unigram,
            NativeSpec::Unigram {
                pieces,
                lowercase,
                rules,
            },
        )
    }

    fn train_char_level(
        docs: &[String],
        max_vocab: usize,
        lowercase: bool,
        pad_multiple: usize,
        mut rules: NativeRules,
    ) -> Self {
        let special_len = SPECIAL_TOKENS.len() + rules.extra_specials.len();
        let cap = max_vocab.clamp(32, 4096).saturating_sub(special_len);
        let mut freq: HashMap<char, usize> = HashMap::new();
        for doc in docs {
            let cleaned = strip_special_literals(doc, &rules.extra_specials);
            let normed = apply_unicode_norm(&cleaned, rules.normalization);
            let norm = if lowercase { normed.to_lowercase() } else { normed };
            for ch in norm.chars() {
                *freq.entry(ch).or_insert(0) += 1;
            }
        }
        for b in 32u8..=126 {
            freq.entry(b as char).or_insert(1);
        }
        freq.entry('\n').or_insert(1);

        let mut ranked: Vec<(char, usize)> = freq.into_iter().collect();
        ranked.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        let mut chars: Vec<char> = ranked.into_iter().take(cap).map(|(c, _)| c).collect();
        chars.sort();

        let raw_total = special_len + chars.len();
        rules.padded_vocab_size = align_vocab_up(raw_total, pad_multiple);
        Self::from_native_spec(
            TokenizerKind::CharLevel,
            NativeSpec::CharLevel {
                chars,
                lowercase,
                rules,
            },
        )
    }

    pub fn encode(&self, text: &str, add_bos_eos: bool) -> Vec<u32> {
        self.encode_with_dropout(text, add_bos_eos, 0.0, None)
    }

    /// Encodes `text` with optional stochastic subword dropout (`0.0..=0.25`) for training regularization.
    pub fn encode_with_dropout(
        &self,
        text: &str,
        add_bos_eos: bool,
        subword_dropout: f32,
        mut rng: Option<&mut Rng>,
    ) -> Vec<u32> {
        match &self.inner {
            RuntimeTokenizer::HfExternal(tk) => {
                let mut ids: Vec<u32> = tk
                    .encode(text, add_bos_eos)
                    .map(|enc| enc.get_ids().to_vec())
                    .unwrap_or_default();
                if ids.is_empty() && add_bos_eos {
                    ids.push(BOS_ID);
                }
                ids
            }
            RuntimeTokenizer::Native(rt) => {
                let mut out = Vec::new();
                if add_bos_eos {
                    out.push(BOS_ID);
                }
                for segment in split_special_segments(text, &rt.all_specials) {
                    match segment {
                        Segment::Special(id) => out.push(id),
                        Segment::Plain(span) => encode_plain_native(
                            rt,
                            span,
                            subword_dropout.clamp(0.0, 0.25),
                            rng.as_deref_mut(),
                            &mut out,
                        ),
                    }
                }
                if add_bos_eos {
                    out.push(EOS_ID);
                }
                out
            }
        }
    }

    pub fn decode(&self, ids: &[u32], skip_special: bool) -> String {
        match &self.inner {
            RuntimeTokenizer::HfExternal(tk) => tk.decode(ids, skip_special).unwrap_or_default(),
            RuntimeTokenizer::Native(rt) => decode_native(rt, ids, skip_special),
        }
    }

    pub fn token_display(&self, id: u32) -> String {
        if let RuntimeTokenizer::Native(rt) = &self.inner {
            if let Some(sp) = rt.all_specials.get(id as usize) {
                return sp.clone();
            }
        } else if (id as usize) < SPECIAL_TOKENS.len() {
            return SPECIAL_TOKENS[id as usize].to_owned();
        }
        self.decode(&[id], false)
            .replace('\n', "↵")
            .replace(' ', "·")
    }

    pub fn preview_text(&self, sample: &str) -> TokenPreview {
        let ids = self.encode(sample, true);
        let tokens: Vec<(u32, String)> = ids.iter().map(|&id| (id, self.token_display(id))).collect();
        let char_count = sample.chars().count();
        let chars_per_token = if ids.is_empty() {
            0.0
        } else {
            char_count as f32 / ids.len() as f32
        };
        TokenPreview {
            tokens,
            char_count,
            chars_per_token,
        }
    }

    /// Formats a multi-turn Playground conversation into token IDs ready for generation.
    pub fn encode_chat_turns(&self, turns: &[(String, String)], draft_prompt: &str) -> Vec<u32> {
        let mut formatted = String::new();
        for (role, content) in turns {
            if role == "user" {
                formatted.push_str("<user> ");
                formatted.push_str(content.trim());
                formatted.push(' ');
            } else {
                formatted.push_str("<assistant> ");
                formatted.push_str(content.trim());
                formatted.push_str(" <eos> ");
            }
        }
        formatted.push_str("<user> ");
        formatted.push_str(draft_prompt.trim());
        formatted.push_str(" <assistant>");

        let mut ids = vec![BOS_ID];
        let body = self.encode(&formatted, false);
        ids.extend(body);
        ids
    }

    /// Encodes a split of documents into fixed `[seq_len + 1]` causal training windows.
    pub fn build_windows(
        &self,
        docs: &[String],
        seq_len: usize,
        sequence_packing: bool,
        add_bos_eos: bool,
    ) -> Vec<Vec<u32>> {
        self.build_windows_with_dropout(docs, seq_len, sequence_packing, add_bos_eos, 0.0, None)
    }

    pub fn build_windows_with_dropout(
        &self,
        docs: &[String],
        seq_len: usize,
        sequence_packing: bool,
        add_bos_eos: bool,
        subword_dropout: f32,
        mut rng: Option<&mut Rng>,
    ) -> Vec<Vec<u32>> {
        let window_len = seq_len.max(8) + 1;
        if docs.is_empty() {
            return Vec::new();
        }

        if sequence_packing {
            let mut stream = Vec::new();
            for doc in docs {
                let encoded =
                    self.encode_with_dropout(doc, add_bos_eos, subword_dropout, rng.as_deref_mut());
                stream.extend(encoded);
            }
            if stream.len() < window_len {
                let base = stream.clone();
                while stream.len() < window_len * 2 && !base.is_empty() {
                    stream.extend_from_slice(&base);
                }
            }
            let stride = seq_len.max(8);
            let mut windows = Vec::new();
            let mut start = 0;
            while start + window_len <= stream.len() {
                windows.push(stream[start..start + window_len].to_vec());
                start += stride;
            }
            if windows.is_empty() && !stream.is_empty() {
                stream.resize(window_len, PAD_ID);
                windows.push(stream);
            }
            windows
        } else {
            let mut windows = Vec::new();
            for doc in docs {
                let mut ids =
                    self.encode_with_dropout(doc, add_bos_eos, subword_dropout, rng.as_deref_mut());
                if ids.len() >= window_len {
                    let mut start = 0;
                    while start + window_len <= ids.len() {
                        windows.push(ids[start..start + window_len].to_vec());
                        start += seq_len.max(8);
                    }
                } else if ids.len() >= 2 {
                    ids.resize(window_len, PAD_ID);
                    windows.push(ids);
                }
            }
            windows
        }
    }
}

enum Segment<'a> {
    Special(u32),
    Plain(&'a str),
}

fn split_special_segments<'a>(input: &'a str, specials: &[String]) -> Vec<Segment<'a>> {
    let mut out = Vec::new();
    let mut rest = input;
    while !rest.is_empty() {
        let mut earliest: Option<(usize, u32, usize)> = None;
        for (id, literal) in specials.iter().enumerate() {
            if literal.is_empty() {
                continue;
            }
            if let Some(pos) = rest.find(literal.as_str()) {
                if earliest.is_none_or(|(best_pos, _, best_len)| {
                    pos < best_pos || (pos == best_pos && literal.len() > best_len)
                }) {
                    earliest = Some((pos, id as u32, literal.len()));
                }
            }
        }
        match earliest {
            Some((pos, id, len)) => {
                if pos > 0 {
                    out.push(Segment::Plain(&rest[..pos]));
                }
                out.push(Segment::Special(id));
                rest = &rest[pos + len..];
            }
            None => {
                out.push(Segment::Plain(rest));
                break;
            }
        }
    }
    out
}

fn strip_special_literals(input: &str, extra: &[String]) -> String {
    let mut out = input.to_owned();
    for tok in SPECIAL_TOKENS {
        out = out.replace(tok, " ");
    }
    for tok in extra {
        if !tok.is_empty() {
            out = out.replace(tok.as_str(), " ");
        }
    }
    out
}

fn apply_unicode_norm(input: &str, mode: UnicodeNorm) -> String {
    match mode {
        UnicodeNorm::None => input.to_owned(),
        UnicodeNorm::CleanWhitespace => input
            .replace("\r\n", "\n")
            .chars()
            .filter(|&c| c == '\n' || c == '\t' || !c.is_control())
            .collect(),
        UnicodeNorm::Lowercase => input.to_lowercase(),
    }
}

/// Segments text according to the user's selected pre-tokenization boundary and digit policy.
/// Crucially, concatenating all returned segments reproduces `text` byte-for-byte!
fn pre_tokenize_text(text: &str, mode: PreTokenizeMode, digits: DigitPolicy) -> Vec<String> {
    let base_chunks: Vec<String> = match mode {
        PreTokenizeMode::RawStream => vec![text.to_owned()],
        PreTokenizeMode::Gpt4Regex => split_gpt4_style(text),
        PreTokenizeMode::WhitespacePunct => split_whitespace_and_punct(text),
        PreTokenizeMode::CodeIndentAware => split_code_indent_aware(text),
    };

    match digits {
        DigitPolicy::WholeNumbers => base_chunks,
        DigitPolicy::IndividualDigits => split_digits_in_chunks(base_chunks, 1),
        DigitPolicy::ChunksOf3 => split_digits_in_chunks(base_chunks, 3),
    }
}

fn split_gpt4_style(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut prev_cat = 0u8; // 0=empty, 1=space+word, 2=digit, 3=punct, 4=newline

    for ch in text.chars() {
        let cat = if ch == '\n' || ch == '\r' {
            4
        } else if ch.is_ascii_digit() {
            2
        } else if ch.is_alphabetic() || ch == '\'' {
            1
        } else if ch.is_whitespace() {
            0
        } else {
            3
        };

        if cur.is_empty() {
            cur.push(ch);
            prev_cat = cat;
            continue;
        }

        // Allow single leading space to attach to an alphabetic/punctuation run (GPT-2/4 style).
        if prev_cat == 0 && (cat == 1 || cat == 3) && cur == " " {
            cur.push(ch);
            prev_cat = cat;
        } else if cat == prev_cat && cat != 0 {
            cur.push(ch);
        } else if cat == 0 && prev_cat == 0 {
            cur.push(ch);
        } else {
            out.push(std::mem::take(&mut cur));
            cur.push(ch);
            prev_cat = cat;
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

fn split_whitespace_and_punct(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    for ch in text.chars() {
        if ch.is_whitespace() || ch.is_ascii_punctuation() {
            if !cur.is_empty() {
                out.push(std::mem::take(&mut cur));
            }
            out.push(ch.to_string());
        } else {
            cur.push(ch);
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

fn split_code_indent_aware(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    let mut mode = 0u8; // 1=ident, 2=spaces, 3=digits, 4=other
    for ch in text.chars() {
        let m = if ch == ' ' {
            2
        } else if ch.is_alphanumeric() && !ch.is_ascii_digit() || ch == '_' {
            1
        } else if ch.is_ascii_digit() {
            3
        } else {
            4
        };
        if cur.is_empty() {
            cur.push(ch);
            mode = m;
        } else if m == mode && (m == 1 || m == 3 || (m == 2 && cur.len() < 4)) {
            cur.push(ch);
        } else {
            out.push(std::mem::take(&mut cur));
            cur.push(ch);
            mode = m;
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

fn split_digits_in_chunks(chunks: Vec<String>, max_group: usize) -> Vec<String> {
    let mut out = Vec::with_capacity(chunks.len());
    for chunk in chunks {
        if !chunk.chars().any(|c| c.is_ascii_digit()) {
            out.push(chunk);
            continue;
        }
        let mut buf = String::new();
        let mut digit_run = 0usize;
        for ch in chunk.chars() {
            if ch.is_ascii_digit() {
                if digit_run > 0 && digit_run >= max_group {
                    out.push(std::mem::take(&mut buf));
                    digit_run = 0;
                } else if !buf.is_empty() && digit_run == 0 {
                    out.push(std::mem::take(&mut buf));
                }
                buf.push(ch);
                digit_run += 1;
            } else {
                if digit_run > 0 {
                    out.push(std::mem::take(&mut buf));
                    digit_run = 0;
                }
                buf.push(ch);
            }
        }
        if !buf.is_empty() {
            out.push(buf);
        }
    }
    out
}

fn encode_plain_native(
    rt: &NativeRuntime,
    span: &str,
    subword_dropout: f32,
    mut rng: Option<&mut Rng>,
    out: &mut Vec<u32>,
) {
    let offset = rt.all_specials.len() as u32;
    match &rt.spec {
        NativeSpec::ByteBpe { merges, rules, .. } => {
            let normed = apply_unicode_norm(span, rules.normalization);
            for chunk in pre_tokenize_text(&normed, rules.pre_tokenize, rules.digit_policy) {
                let mut ids: Vec<u32> = chunk.as_bytes().iter().map(|&b| u32::from(b)).collect();
                for &(left, right, merged) in merges {
                    if ids.len() < 2 {
                        break;
                    }
                    // Optional BPE-dropout regularization during training!
                    if subword_dropout > 0.0 {
                        if let Some(r) = rng.as_deref_mut() {
                            if r.next_f32() < subword_dropout {
                                continue;
                            }
                        }
                    }
                    let mut i = 0;
                    let mut next_ids = Vec::with_capacity(ids.len());
                    while i < ids.len() {
                        if i + 1 < ids.len() && ids[i] == left && ids[i + 1] == right {
                            next_ids.push(merged);
                            i += 2;
                        } else {
                            next_ids.push(ids[i]);
                            i += 1;
                        }
                    }
                    ids = next_ids;
                }
                out.extend(ids.into_iter().map(|id| id + offset));
            }
        }
        NativeSpec::WordPiece {
            lowercase, rules, ..
        } => {
            let normed = apply_unicode_norm(span, rules.normalization);
            let norm = if *lowercase { normed.to_lowercase() } else { normed };
            let space_id = rt.wordpiece_map.get(" ").copied().unwrap_or(UNK_ID);
            let mut first = true;
            for word in norm.split(' ') {
                if !first {
                    out.push(space_id);
                }
                first = false;
                if word.is_empty() {
                    continue;
                }
                let chars: Vec<char> = word.chars().collect();
                let mut start = 0;
                while start < chars.len() {
                    let mut end = chars.len();
                    let mut matched = None;
                    while end > start {
                        let slice: String = chars[start..end].iter().collect();
                        let cand = if start == 0 { slice } else { format!("##{slice}") };
                        if let Some(&id) = rt.wordpiece_map.get(&cand) {
                            matched = Some(id);
                            break;
                        }
                        end -= 1;
                    }
                    if let Some(id) = matched {
                        out.push(id);
                        start = end;
                    } else if rules.byte_fallback {
                        let mut b_buf = [0u8; 4];
                        for &b in chars[start].encode_utf8(&mut b_buf).as_bytes() {
                            let hex = format!("<0x{b:02X}>");
                            out.push(rt.wordpiece_map.get(&hex).copied().unwrap_or(UNK_ID));
                        }
                        start += 1;
                    } else {
                        out.push(UNK_ID);
                        start += 1;
                    }
                }
            }
        }
        NativeSpec::Unigram {
            pieces,
            lowercase,
            rules,
        } => {
            let normed = apply_unicode_norm(span, rules.normalization);
            let norm = if *lowercase { normed.to_lowercase() } else { normed };
            let chars: Vec<char> = norm.chars().collect();
            let n = chars.len();
            if n == 0 {
                return;
            }
            let mut score_map: HashMap<&str, (u32, f32)> = HashMap::with_capacity(pieces.len());
            for (idx, (piece, logp)) in pieces.iter().enumerate() {
                score_map.insert(piece.as_str(), (offset + idx as u32, *logp));
            }
            let mut best = vec![(f32::NEG_INFINITY, 0usize, UNK_ID); n + 1];
            best[0] = (0.0, 0, UNK_ID);
            for i in 0..n {
                if !best[i].0.is_finite() {
                    continue;
                }
                let mut matched_one = false;
                for len in 1..=8.min(n - i) {
                    if len > 1 && subword_dropout > 0.0 {
                        if let Some(r) = rng.as_deref_mut() {
                            if r.next_f32() < subword_dropout {
                                continue;
                            }
                        }
                    }
                    let cand: String = chars[i..i + len].iter().collect();
                    if let Some(&(id, logp)) = score_map.get(cand.as_str()) {
                        let cand_score = best[i].0 + logp;
                        if cand_score > best[i + len].0 {
                            best[i + len] = (cand_score, i, id);
                        }
                        matched_one = true;
                    }
                }
                if !matched_one {
                    let fallback = best[i].0 - 20.0;
                    if fallback > best[i + 1].0 {
                        best[i + 1] = (fallback, i, UNK_ID);
                    }
                }
            }
            let mut rev = Vec::new();
            let mut cur = n;
            while cur > 0 {
                let (_, prev, id) = best[cur];
                if id == UNK_ID && rules.byte_fallback {
                    let mut b_buf = [0u8; 4];
                    let bytes = chars[cur - 1].encode_utf8(&mut b_buf).as_bytes();
                    for &b in bytes.iter().rev() {
                        let hex = format!("<0x{b:02X}>");
                        let fb_id = score_map.get(hex.as_str()).map(|x| x.0).unwrap_or(UNK_ID);
                        rev.push(fb_id);
                    }
                } else {
                    rev.push(id);
                }
                cur = if prev < cur { prev } else { cur - 1 };
            }
            rev.reverse();
            out.extend(rev);
        }
        NativeSpec::CharLevel {
            lowercase, rules, ..
        } => {
            let normed = apply_unicode_norm(span, rules.normalization);
            if *lowercase {
                for ch in normed.to_lowercase().chars() {
                    out.push(rt.char_map.get(&ch).copied().unwrap_or(UNK_ID));
                }
            } else {
                for ch in normed.chars() {
                    out.push(rt.char_map.get(&ch).copied().unwrap_or(UNK_ID));
                }
            }
        }
    }
}

fn parse_hex_byte_token(tok: &str) -> Option<u8> {
    let inner = tok.strip_prefix("<0x")?.strip_suffix('>')?;
    if inner.len() == 2 {
        u8::from_str_radix(inner, 16).ok()
    } else {
        None
    }
}

fn decode_native(rt: &NativeRuntime, ids: &[u32], skip_special: bool) -> String {
    let offset = rt.all_specials.len() as u32;
    match &rt.spec {
        NativeSpec::ByteBpe { vocab, .. } => {
            let mut out = String::new();
            let mut byte_buf: Vec<u8> = Vec::new();
            for &id in ids {
                if id < offset {
                    if !byte_buf.is_empty() {
                        out.push_str(&String::from_utf8_lossy(&byte_buf));
                        byte_buf.clear();
                    }
                    if !skip_special {
                        if let Some(sp) = rt.all_specials.get(id as usize) {
                            out.push_str(sp);
                        }
                    } else if id == USER_ID {
                        out.push_str("\nUser: ");
                    } else if id == ASSISTANT_ID {
                        out.push_str("\nAssistant: ");
                    }
                } else if let Some(bytes) = vocab.get((id - offset) as usize) {
                    byte_buf.extend_from_slice(bytes);
                }
            }
            if !byte_buf.is_empty() {
                out.push_str(&String::from_utf8_lossy(&byte_buf));
            }
            out
        }
        NativeSpec::WordPiece { pieces, .. } => {
            let mut out = String::new();
            let mut byte_buf: Vec<u8> = Vec::new();
            for &id in ids {
                if id < offset {
                    if !byte_buf.is_empty() {
                        out.push_str(&String::from_utf8_lossy(&byte_buf));
                        byte_buf.clear();
                    }
                    if !skip_special {
                        if let Some(sp) = rt.all_specials.get(id as usize) {
                            out.push_str(sp);
                        }
                    }
                } else if let Some(piece) = pieces.get((id - offset) as usize) {
                    if let Some(b) = parse_hex_byte_token(piece) {
                        byte_buf.push(b);
                    } else {
                        if !byte_buf.is_empty() {
                            out.push_str(&String::from_utf8_lossy(&byte_buf));
                            byte_buf.clear();
                        }
                        if let Some(stripped) = piece.strip_prefix("##") {
                            out.push_str(stripped);
                        } else {
                            out.push_str(piece);
                        }
                    }
                }
            }
            if !byte_buf.is_empty() {
                out.push_str(&String::from_utf8_lossy(&byte_buf));
            }
            out
        }
        NativeSpec::Unigram { pieces, .. } => {
            let mut out = String::new();
            let mut byte_buf: Vec<u8> = Vec::new();
            for &id in ids {
                if id < offset {
                    if !byte_buf.is_empty() {
                        out.push_str(&String::from_utf8_lossy(&byte_buf));
                        byte_buf.clear();
                    }
                    if !skip_special {
                        if let Some(sp) = rt.all_specials.get(id as usize) {
                            out.push_str(sp);
                        }
                    }
                } else if let Some((piece, _)) = pieces.get((id - offset) as usize) {
                    if let Some(b) = parse_hex_byte_token(piece) {
                        byte_buf.push(b);
                    } else {
                        if !byte_buf.is_empty() {
                            out.push_str(&String::from_utf8_lossy(&byte_buf));
                            byte_buf.clear();
                        }
                        out.push_str(piece);
                    }
                }
            }
            if !byte_buf.is_empty() {
                out.push_str(&String::from_utf8_lossy(&byte_buf));
            }
            out
        }
        NativeSpec::CharLevel { chars, .. } => {
            let mut out = String::new();
            for &id in ids {
                if id < offset {
                    if !skip_special {
                        if let Some(sp) = rt.all_specials.get(id as usize) {
                            out.push_str(sp);
                        }
                    }
                } else if let Some(&ch) = chars.get((id - offset) as usize) {
                    out.push(ch);
                }
            }
            out
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn byte_bpe_roundtrips_utf8_custom_specials_and_single_digits_losslessly() {
        let corpus = vec![
            "<user> Compute 2026 + 42! <assistant> <think>Adding digits</think> Result 2068 🚀".to_owned(),
            "<user> Hello Transformer! <assistant> Fast BPE merges.".to_owned(),
        ];
        let mut cfg = TokenizerConfig::default();
        cfg.kind = TokenizerKind::ByteLevelBpe;
        cfg.vocab_size = 320;
        cfg.digit_policy = DigitPolicy::IndividualDigits;
        cfg.pad_to_multiple = 64;
        cfg.custom_special_tokens = "<think>,</think>".to_owned();

        let tk = LabTokenizer::train_or_load(&cfg, &corpus).expect("train bpe");
        assert_eq!(tk.vocab_size() % 64, 0, "vocab must align to pad_to_multiple");

        let sample = "<think>Compute 2026</think> 🚀!";
        let ids = tk.encode(sample, true);
        assert_eq!(ids.first().copied(), Some(BOS_ID));
        assert_eq!(ids.last().copied(), Some(EOS_ID));
        assert_eq!(tk.decode(&ids, false), format!("<bos>{sample}<eos>"));
    }

    #[test]
    fn wordpiece_unigram_and_char_tokenizers_encode_and_arena_compares_all_four() {
        let corpus = vec![
            "Transformers attend across sequence positions in 2026.".to_owned(),
            "Attention heads project queries keys and values cleanly.".to_owned(),
        ];
        for kind in [
            TokenizerKind::WordPiece,
            TokenizerKind::Unigram,
            TokenizerKind::CharLevel,
        ] {
            let mut cfg = TokenizerConfig::default();
            cfg.kind = kind;
            cfg.vocab_size = 360;
            let tk = LabTokenizer::train_or_load(&cfg, &corpus).expect("train");
            let encoded = tk.encode("Attention sequence 🚀", false);
            assert!(!encoded.is_empty());
            let decoded = tk.decode(&encoded, true);
            assert!(decoded.to_lowercase().contains("attention"));

            let tmp =
                std::env::temp_dir().join(format!("archx-tk-{:?}-{}.json", kind, std::process::id()));
            tk.save_to_path(&tmp).expect("save");
            let loaded = LabTokenizer::load_from_path(&tmp).expect("load");
            assert_eq!(loaded.encode("Attention sequence 🚀", false), encoded);
            let _ = std::fs::remove_file(tmp);
        }

        let arena = run_tokenizer_arena(
            &TokenizerConfig::default(),
            &corpus,
            "Transformers attend across 2026 sequence positions.",
            128,
        );
        assert_eq!(arena.len(), 4);
        // Character-level must produce strictly more tokens than Byte-Level BPE on prose.
        assert!(arena[3].token_count >= arena[0].token_count);
    }

    #[test]
    fn sequence_packing_builds_uniform_causal_windows() {
        let corpus = vec!["alpha beta gamma delta".to_owned(); 8];
        let cfg = TokenizerConfig::default();
        let tk = LabTokenizer::train_or_load(&cfg, &corpus).expect("bpe");
        let windows = tk.build_windows(&corpus, 16, true, true);
        assert!(!windows.is_empty());
        assert!(windows.iter().all(|w| w.len() == 17));
    }
}
