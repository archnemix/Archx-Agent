//! Purpose: Trains and runs native Rust tokenizers (`ByteLevelBpe`, `WordPiece`, `Unigram`, `CharLevel`, plus Hugging Face `tokenizer.json` import) and packs token windows.

use std::collections::{BTreeSet, HashMap};
use std::path::Path;
use std::sync::Arc;

use serde::{Deserialize, Serialize};

use crate::config::{TokenizerConfig, TokenizerKind};

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

#[derive(Debug, Clone, Serialize, Deserialize)]
enum NativeSpec {
    ByteBpe {
        vocab: Vec<Vec<u8>>,
        merges: Vec<(u32, u32, u32)>,
    },
    WordPiece {
        pieces: Vec<String>,
        lowercase: bool,
    },
    Unigram {
        pieces: Vec<(String, f32)>,
        lowercase: bool,
    },
    CharLevel {
        chars: Vec<char>,
        lowercase: bool,
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

impl LabTokenizer {
    pub fn train_or_load(cfg: &TokenizerConfig, docs: &[String]) -> Result<Self, String> {
        match cfg.kind {
            TokenizerKind::PretrainedFile => {
                let path = cfg.pretrained_path.trim();
                if path.is_empty() {
                    return Err("Enter a path to a `tokenizer.json` file first.".to_owned());
                }
                Self::load_from_path(Path::new(path))
            }
            TokenizerKind::ByteLevelBpe => Ok(Self::train_byte_bpe(docs, cfg.vocab_size, cfg.min_frequency)),
            TokenizerKind::WordPiece => Ok(Self::train_wordpiece(docs, cfg.vocab_size, cfg.min_frequency, cfg.lowercase)),
            TokenizerKind::Unigram => Ok(Self::train_unigram(docs, cfg.vocab_size, cfg.lowercase)),
            TokenizerKind::CharLevel => Ok(Self::train_char_level(docs, cfg.vocab_size, cfg.lowercase)),
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
        let (vocab_size, detail) = match &spec {
            NativeSpec::ByteBpe { vocab, merges } => (
                SPECIAL_TOKENS.len() + vocab.len(),
                format!("Byte-Level BPE · {} vocab ({} merges)", SPECIAL_TOKENS.len() + vocab.len(), merges.len()),
            ),
            NativeSpec::WordPiece { pieces, .. } => {
                for (idx, piece) in pieces.iter().enumerate() {
                    wordpiece_map.insert(piece.clone(), (SPECIAL_TOKENS.len() + idx) as u32);
                }
                (
                    SPECIAL_TOKENS.len() + pieces.len(),
                    format!("WordPiece · {} vocab", SPECIAL_TOKENS.len() + pieces.len()),
                )
            }
            NativeSpec::Unigram { pieces, .. } => (
                SPECIAL_TOKENS.len() + pieces.len(),
                format!("Unigram · {} vocab", SPECIAL_TOKENS.len() + pieces.len()),
            ),
            NativeSpec::CharLevel { chars, .. } => {
                for (idx, ch) in chars.iter().enumerate() {
                    char_map.insert(*ch, (SPECIAL_TOKENS.len() + idx) as u32);
                }
                (
                    SPECIAL_TOKENS.len() + chars.len(),
                    format!("Character-Level · {} vocab", SPECIAL_TOKENS.len() + chars.len()),
                )
            }
        };
        Self {
            inner: RuntimeTokenizer::Native(NativeRuntime {
                kind,
                spec,
                wordpiece_map,
                char_map,
            }),
            vocab_size,
            summary_label: detail,
        }
    }

    fn train_byte_bpe(docs: &[String], target_vocab: usize, min_freq: usize) -> Self {
        let base_offset = SPECIAL_TOKENS.len();
        let wanted = target_vocab.clamp(base_offset + 256, 32_768);
        let max_merges = wanted.saturating_sub(base_offset + 256);
        let min_f = min_freq.max(2);

        let mut vocab: Vec<Vec<u8>> = (0u16..256).map(|b| vec![b as u8]).collect();
        let mut merges: Vec<(u32, u32, u32)> = Vec::new();

        // Pre-split on special tokens and whitespace boundaries so merges never cross words awkwardly.
        let mut chunks: Vec<(Vec<u32>, usize)> = Vec::new();
        let mut chunk_counts: HashMap<Vec<u8>, usize> = HashMap::new();
        for doc in docs {
            for seg in split_preserving_whitespace(strip_special_literals(doc).as_str()) {
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

        Self::from_native_spec(TokenizerKind::ByteLevelBpe, NativeSpec::ByteBpe { vocab, merges })
    }

    fn train_wordpiece(docs: &[String], target_vocab: usize, min_freq: usize, lowercase: bool) -> Self {
        let cap = target_vocab.clamp(64, 32_768).saturating_sub(SPECIAL_TOKENS.len());
        let mut char_set = BTreeSet::new();
        let mut word_counts: HashMap<String, usize> = HashMap::new();

        for doc in docs {
            let cleaned = strip_special_literals(doc);
            let norm = if lowercase { cleaned.to_lowercase() } else { cleaned };
            for ch in norm.chars() {
                char_set.insert(ch);
            }
            for word in norm.split_whitespace() {
                *word_counts.entry(word.to_owned()).or_insert(0) += 1;
            }
        }

        let mut pieces: Vec<String> = Vec::new();
        pieces.push(" ".to_owned());
        for ch in &char_set {
            let s = ch.to_string();
            if s != " " {
                pieces.push(s.clone());
                pieces.push(format!("##{s}"));
            }
        }

        let mut sub_counts: HashMap<String, usize> = HashMap::new();
        for (word, freq) in &word_counts {
            let chars: Vec<char> = word.chars().collect();
            for start in 0..chars.len() {
                for end in (start + 2)..=chars.len().min(start + 10) {
                    let sub: String = chars[start..end].iter().collect();
                    let token = if start == 0 { sub } else { format!("##{sub}") };
                    *sub_counts.entry(token).or_insert(0) += *freq;
                }
            }
        }

        let mut ranked: Vec<(String, usize)> = sub_counts
            .into_iter()
            .filter(|(_, c)| *c >= min_freq.max(2))
            .collect();
        ranked.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));

        let mut existing: HashMap<String, ()> = pieces.iter().cloned().map(|p| (p, ())).collect();
        for (cand, _) in ranked {
            if pieces.len() >= cap {
                break;
            }
            if existing.insert(cand.clone(), ()).is_none() {
                pieces.push(cand);
            }
        }
        pieces.truncate(cap.max(16));
        Self::from_native_spec(TokenizerKind::WordPiece, NativeSpec::WordPiece { pieces, lowercase })
    }

    fn train_unigram(docs: &[String], target_vocab: usize, lowercase: bool) -> Self {
        let cap = target_vocab.clamp(64, 32_768).saturating_sub(SPECIAL_TOKENS.len());
        let mut counts: HashMap<String, usize> = HashMap::new();
        let mut total = 0usize;

        for doc in docs {
            let cleaned = strip_special_literals(doc);
            let norm = if lowercase { cleaned.to_lowercase() } else { cleaned };
            for ch in norm.chars() {
                let s = ch.to_string();
                *counts.entry(s).or_insert(0) += 2;
                total += 2;
            }
            let chars: Vec<char> = norm.chars().collect();
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
        for (s, c) in single_chars {
            pieces.push((s, ((c as f32) / denom).ln()));
        }
        for (s, c) in multi {
            if pieces.len() >= cap {
                break;
            }
            pieces.push((s, ((c as f32) / denom).ln()));
        }
        pieces.truncate(cap.max(16));
        Self::from_native_spec(TokenizerKind::Unigram, NativeSpec::Unigram { pieces, lowercase })
    }

    fn train_char_level(docs: &[String], max_vocab: usize, lowercase: bool) -> Self {
        let cap = max_vocab.clamp(32, 4096).saturating_sub(SPECIAL_TOKENS.len());
        let mut freq: HashMap<char, usize> = HashMap::new();
        for doc in docs {
            let cleaned = strip_special_literals(doc);
            let norm = if lowercase { cleaned.to_lowercase() } else { cleaned };
            for ch in norm.chars() {
                *freq.entry(ch).or_insert(0) += 1;
            }
        }
        // Guarantee printable ASCII so interactive chat prompts never hit <unk> on basic punctuation.
        for b in 32u8..=126 {
            freq.entry(b as char).or_insert(1);
        }
        freq.entry('\n').or_insert(1);

        let mut ranked: Vec<(char, usize)> = freq.into_iter().collect();
        ranked.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        let mut chars: Vec<char> = ranked.into_iter().take(cap).map(|(c, _)| c).collect();
        chars.sort();
        Self::from_native_spec(TokenizerKind::CharLevel, NativeSpec::CharLevel { chars, lowercase })
    }

    pub fn encode(&self, text: &str, add_bos_eos: bool) -> Vec<u32> {
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
                for segment in split_special_segments(text) {
                    match segment {
                        Segment::Special(id) => out.push(id),
                        Segment::Plain(span) => encode_plain_native(rt, span, &mut out),
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
        if (id as usize) < SPECIAL_TOKENS.len() {
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
    ///
    /// When `sequence_packing` is enabled, documents are concatenated end-to-end
    /// with `<bos>...<eos>` boundaries so zero compute is wasted on `<pad>`.
    pub fn build_windows(
        &self,
        docs: &[String],
        seq_len: usize,
        sequence_packing: bool,
        add_bos_eos: bool,
    ) -> Vec<Vec<u32>> {
        let window_len = seq_len.max(8) + 1;
        if docs.is_empty() {
            return Vec::new();
        }

        if sequence_packing {
            let mut stream = Vec::new();
            for doc in docs {
                let encoded = self.encode(doc, add_bos_eos);
                stream.extend(encoded);
            }
            if stream.len() < window_len {
                // Repeat short streams so small starter datasets always yield full windows.
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
                let mut ids = self.encode(doc, add_bos_eos);
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

fn split_special_segments(input: &str) -> Vec<Segment<'_>> {
    let mut out = Vec::new();
    let mut rest = input;
    while !rest.is_empty() {
        let mut earliest: Option<(usize, u32, usize)> = None;
        for (id, literal) in SPECIAL_TOKENS.iter().enumerate() {
            if let Some(pos) = rest.find(literal) {
                if earliest.is_none_or(|(best_pos, _, _)| pos < best_pos) {
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

fn strip_special_literals(input: &str) -> String {
    let mut out = input.to_owned();
    for tok in SPECIAL_TOKENS {
        out = out.replace(tok, " ");
    }
    out
}

fn split_preserving_whitespace(text: &str) -> Vec<String> {
    let mut segments = Vec::new();
    let mut current = String::new();
    for ch in text.chars() {
        if ch.is_whitespace() && !current.is_empty() && !current.chars().all(char::is_whitespace) {
            segments.push(std::mem::take(&mut current));
        }
        current.push(ch);
    }
    if !current.is_empty() {
        segments.push(current);
    }
    segments
}

fn encode_plain_native(rt: &NativeRuntime, span: &str, out: &mut Vec<u32>) {
    let offset = SPECIAL_TOKENS.len() as u32;
    match &rt.spec {
        NativeSpec::ByteBpe { merges, .. } => {
            for chunk in split_preserving_whitespace(span) {
                let mut ids: Vec<u32> = chunk.as_bytes().iter().map(|&b| u32::from(b)).collect();
                for &(left, right, merged) in merges {
                    if ids.len() < 2 {
                        break;
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
        NativeSpec::WordPiece { lowercase, .. } => {
            let norm = if *lowercase { span.to_lowercase() } else { span.to_owned() };
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
                    } else {
                        out.push(UNK_ID);
                        start += 1;
                    }
                }
            }
        }
        NativeSpec::Unigram { pieces, lowercase } => {
            let norm = if *lowercase { span.to_lowercase() } else { span.to_owned() };
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
                rev.push(id);
                cur = if prev < cur { prev } else { cur - 1 };
            }
            rev.reverse();
            out.extend(rev);
        }
        NativeSpec::CharLevel { lowercase, .. } => {
            if *lowercase {
                for ch in span.to_lowercase().chars() {
                    out.push(rt.char_map.get(&ch).copied().unwrap_or(UNK_ID));
                }
            } else {
                for ch in span.chars() {
                    out.push(rt.char_map.get(&ch).copied().unwrap_or(UNK_ID));
                }
            }
        }
    }
}

fn decode_native(rt: &NativeRuntime, ids: &[u32], skip_special: bool) -> String {
    let offset = SPECIAL_TOKENS.len() as u32;
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
                        out.push_str(SPECIAL_TOKENS[id as usize]);
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
            for &id in ids {
                if id < offset {
                    if !skip_special {
                        out.push_str(SPECIAL_TOKENS[id as usize]);
                    }
                } else if let Some(piece) = pieces.get((id - offset) as usize) {
                    if let Some(stripped) = piece.strip_prefix("##") {
                        out.push_str(stripped);
                    } else {
                        out.push_str(piece);
                    }
                }
            }
            out
        }
        NativeSpec::Unigram { pieces, .. } => {
            let mut out = String::new();
            for &id in ids {
                if id < offset {
                    if !skip_special {
                        out.push_str(SPECIAL_TOKENS[id as usize]);
                    }
                } else if let Some((piece, _)) = pieces.get((id - offset) as usize) {
                    out.push_str(piece);
                }
            }
            out
        }
        NativeSpec::CharLevel { chars, .. } => {
            let mut out = String::new();
            for &id in ids {
                if id < offset {
                    if !skip_special {
                        out.push_str(SPECIAL_TOKENS[id as usize]);
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
    fn byte_bpe_roundtrips_utf8_and_special_tokens_losslessly() {
        let corpus = vec![
            "<user> Hello Transformer world! <assistant> Hello world from Rust 🚀".to_owned(),
            "<user> Hello Transformer! <assistant> Fast BPE merges.".to_owned(),
        ];
        let mut cfg = TokenizerConfig::default();
        cfg.kind = TokenizerKind::ByteLevelBpe;
        cfg.vocab_size = 300;
        let tk = LabTokenizer::train_or_load(&cfg, &corpus).expect("train bpe");
        assert!(tk.vocab_size() > 263);

        let sample = "Hello Transformer world 🚀!";
        let ids = tk.encode(sample, true);
        assert_eq!(ids.first().copied(), Some(BOS_ID));
        assert_eq!(ids.last().copied(), Some(EOS_ID));
        assert_eq!(tk.decode(&ids, true), sample);
    }

    #[test]
    fn wordpiece_unigram_and_char_tokenizers_encode_and_save() {
        let corpus = vec![
            "Transformers attend across sequence positions.".to_owned(),
            "Attention heads project queries keys and values.".to_owned(),
        ];
        for kind in [TokenizerKind::WordPiece, TokenizerKind::Unigram, TokenizerKind::CharLevel] {
            let mut cfg = TokenizerConfig::default();
            cfg.kind = kind;
            cfg.vocab_size = 180;
            let tk = LabTokenizer::train_or_load(&cfg, &corpus).expect("train");
            let encoded = tk.encode("Attention sequence", false);
            assert!(!encoded.is_empty());
            let decoded = tk.decode(&encoded, true);
            assert!(decoded.to_lowercase().contains("attention"));

            let tmp = std::env::temp_dir().join(format!("archx-tk-{:?}-{}.json", kind, std::process::id()));
            tk.save_to_path(&tmp).expect("save");
            let loaded = LabTokenizer::load_from_path(&tmp).expect("load");
            assert_eq!(loaded.encode("Attention sequence", false), encoded);
            let _ = std::fs::remove_file(tmp);
        }
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
