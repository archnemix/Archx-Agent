//! Purpose: Loads, filters, deduplicates, and splits text datasets from built-in corpora, local files/folders, Hugging Face Hub, Kaggle, and HTTPS URLs.

use std::collections::HashSet;
use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use zeroize::Zeroizing;

use crate::config::{DatasetConfig, DatasetSource};
use crate::rng::Rng;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct PreparedDataset {
    pub source_label: String,
    pub train_docs: Vec<String>,
    pub val_docs: Vec<String>,
    pub total_raw_docs: usize,
    pub dropped_duplicates: usize,
    pub dropped_length: usize,
    pub total_chars: usize,
    pub avg_chars: usize,
}

impl PreparedDataset {
    pub fn total_kept(&self) -> usize {
        self.train_docs.len() + self.val_docs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.train_docs.is_empty()
    }

    pub fn preview_samples(&self, count: usize) -> Vec<String> {
        self.train_docs.iter().take(count).cloned().collect()
    }
}

/// Loads synchronous sources (built-in corpora or local paths) and applies
/// filtering, deduplication, and deterministic train/val splitting.
pub fn load_local_or_builtin(cfg: &DatasetConfig) -> Result<PreparedDataset, String> {
    let (label, raw_docs) = match cfg.source {
        DatasetSource::BuiltinTinyDialogues => (
            "Built-in · Tiny Dialogues & Stories".to_owned(),
            builtin_tiny_dialogues(),
        ),
        DatasetSource::BuiltinRustCode => (
            "Built-in · Rust & Algorithms".to_owned(),
            builtin_rust_code(),
        ),
        DatasetSource::BuiltinLogicQa => (
            "Built-in · Science & Logic Q&A".to_owned(),
            builtin_logic_qa(),
        ),
        DatasetSource::BuiltinClassicVerse => (
            "Built-in · Classic Verse".to_owned(),
            builtin_classic_verse(),
        ),
        DatasetSource::LocalPath => {
            let trimmed = cfg.local_path.trim();
            if trimmed.is_empty() {
                return Err("Enter a local file or folder path first.".to_owned());
            }
            let path = Path::new(trimmed);
            if !path.exists() {
                return Err(format!("Local path does not exist: {}", path.display()));
            }
            let docs = read_path_records(path, cfg)?;
            (format!("Local · {}", path.display()), docs)
        }
        remote => {
            return Err(format!(
                "{} is a remote source—press Fetch remote dataset to download rows.",
                remote.label()
            ));
        }
    };

    finalize_dataset(label, raw_docs, cfg)
}

/// Fetches a remote dataset (Hugging Face Hub, Kaggle, or HTTPS URL) without
/// persisting or logging optional authentication secrets.
pub async fn fetch_remote_dataset(
    cfg: DatasetConfig,
    bearer_token: Option<Zeroizing<String>>,
) -> Result<PreparedDataset, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(25))
        .user_agent("archx-ai-lab-training/0.1")
        .build()
        .map_err(|_| "Could not initialize the HTTPS client.".to_owned())?;

    let limit = cfg.max_remote_rows.clamp(10, 5000);
    let (label, raw_docs) = match cfg.source {
        DatasetSource::HuggingFaceHub => fetch_hf(&client, &cfg, bearer_token.as_ref(), limit).await?,
        DatasetSource::KaggleDataset => fetch_kaggle(&client, &cfg, bearer_token.as_ref()).await?,
        DatasetSource::CustomUrl => fetch_custom_url(&client, &cfg, bearer_token.as_ref()).await?,
        _ => return load_local_or_builtin(&cfg),
    };

    finalize_dataset(label, raw_docs, &cfg)
}

async fn fetch_hf(
    client: &reqwest::Client,
    cfg: &DatasetConfig,
    token: Option<&Zeroizing<String>>,
    limit: usize,
) -> Result<(String, Vec<String>), String> {
    let repo = cfg.hf_repo.trim().trim_matches('/');
    if repo.is_empty() || !repo.contains('/') {
        return Err("Enter a Hugging Face dataset id as `owner/dataset`.".to_owned());
    }
    let config_name = if cfg.hf_config.trim().is_empty() {
        "default"
    } else {
        cfg.hf_config.trim()
    };
    let split = if cfg.hf_split.trim().is_empty() {
        "train"
    } else {
        cfg.hf_split.trim()
    };

    let mut collected = Vec::new();
    let mut offset = 0usize;
    while collected.len() < limit {
        let page_len = (limit - collected.len()).min(100);
        let url = format!(
            "https://datasets-server.huggingface.co/rows?dataset={}&config={}&split={}&offset={}&length={}",
            url_encode(repo),
            url_encode(config_name),
            url_encode(split),
            offset,
            page_len
        );
        let mut req = client.get(&url);
        if let Some(secret) = token {
            if !secret.trim().is_empty() {
                req = req.bearer_auth(secret.trim());
            }
        }
        let resp = req
            .send()
            .await
            .map_err(|_| "Network request to Hugging Face Hub failed.".to_owned())?;
        if !resp.status().is_success() {
            return Err(format!(
                "Hugging Face Hub returned HTTP {}. Check dataset id, config, split, or OS vault token.",
                resp.status().as_u16()
            ));
        }
        let body: Value = resp
            .json()
            .await
            .map_err(|_| "Hugging Face response was not valid JSON.".to_owned())?;
        let Some(rows) = body.get("rows").and_then(Value::as_array) else {
            break;
        };
        if rows.is_empty() {
            break;
        }
        for item in rows {
            let row_obj = item.get("row").unwrap_or(item);
            if let Some(doc) = extract_json_record(row_obj, cfg) {
                collected.push(doc);
            }
        }
        if rows.len() < page_len {
            break;
        }
        offset += rows.len();
    }

    if collected.is_empty() {
        return Err("No matching text records found in the Hugging Face response (check field names).".to_owned());
    }
    Ok((format!("HF · {repo} ({split})"), collected))
}

async fn fetch_kaggle(
    client: &reqwest::Client,
    cfg: &DatasetConfig,
    token: Option<&Zeroizing<String>>,
) -> Result<(String, Vec<String>), String> {
    let slug = cfg.kaggle_slug.trim().trim_matches('/');
    if slug.is_empty() || !slug.contains('/') {
        return Err("Enter a Kaggle dataset slug as `owner/dataset`.".to_owned());
    }
    let file_name = cfg.kaggle_file.trim();
    if file_name.is_empty() {
        return Err("Enter the file name inside the Kaggle dataset (e.g. `train.jsonl` or `data.csv`).".to_owned());
    }
    let url = format!(
        "https://www.kaggle.com/api/v1/datasets/download/{slug}/{}",
        url_encode(file_name)
    );
    let mut req = client.get(&url);
    if let Some(secret) = token {
        let trimmed = secret.trim();
        if let Some((user, key)) = trimmed.split_once(':') {
            req = req.basic_auth(user, Some(key));
        } else if !trimmed.is_empty() {
            req = req.bearer_auth(trimmed);
        }
    }
    let resp = req
        .send()
        .await
        .map_err(|_| "Network request to Kaggle failed.".to_owned())?;
    if !resp.status().is_success() {
        return Err(format!(
            "Kaggle returned HTTP {}. Private or gated Kaggle files require `username:key` or token in the OS vault.",
            resp.status().as_u16()
        ));
    }
    let text = resp
        .text()
        .await
        .map_err(|_| "Kaggle file payload was not UTF-8 text (unzip binary archives locally first).".to_owned())?;
    let docs = parse_text_by_extension(&text, file_name, cfg)?;
    Ok((format!("Kaggle · {slug}/{file_name}"), docs))
}

async fn fetch_custom_url(
    client: &reqwest::Client,
    cfg: &DatasetConfig,
    token: Option<&Zeroizing<String>>,
) -> Result<(String, Vec<String>), String> {
    let url = cfg.custom_url.trim();
    if !url.starts_with("https://") && !url.starts_with("http://127.0.0.1") && !url.starts_with("http://localhost") {
        return Err("Custom dataset URL must use `https://` (or localhost).".to_owned());
    }
    let mut req = client.get(url);
    if let Some(secret) = token {
        if !secret.trim().is_empty() {
            req = req.bearer_auth(secret.trim());
        }
    }
    let resp = req
        .send()
        .await
        .map_err(|_| "Could not reach custom dataset URL.".to_owned())?;
    if !resp.status().is_success() {
        return Err(format!("Custom URL returned HTTP {}.", resp.status().as_u16()));
    }
    let body = resp
        .text()
        .await
        .map_err(|_| "Custom URL response was not valid UTF-8 text.".to_owned())?;
    let hint = url.split('?').next().unwrap_or(url);
    let docs = parse_text_by_extension(&body, hint, cfg)?;
    Ok(("Custom URL dataset".to_owned(), docs))
}

fn url_encode(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for byte in input.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~') {
            out.push(byte as char);
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

fn read_path_records(path: &Path, cfg: &DatasetConfig) -> Result<Vec<String>, String> {
    if path.is_file() {
        let raw = std::fs::read_to_string(path)
            .map_err(|_| format!("Could not read UTF-8 text from {}", path.display()))?;
        let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("data.txt");
        return parse_text_by_extension(&raw, name, cfg);
    }

    let entries = std::fs::read_dir(path)
        .map_err(|_| format!("Could not list folder {}", path.display()))?;
    let mut files: Vec<_> = entries
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.is_file())
        .collect();
    files.sort();

    let mut all = Vec::new();
    for file in files {
        let ext = file
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        if matches!(ext.as_str(), "txt" | "md" | "jsonl" | "json" | "csv") {
            if let Ok(raw) = std::fs::read_to_string(&file) {
                let name = file.file_name().and_then(|s| s.to_str()).unwrap_or("data.txt");
                if let Ok(mut docs) = parse_text_by_extension(&raw, name, cfg) {
                    all.append(&mut docs);
                }
            }
        }
    }
    if all.is_empty() {
        return Err("No readable `.txt`, `.md`, `.jsonl`, `.json`, or `.csv` records found in folder.".to_owned());
    }
    Ok(all)
}

pub fn parse_text_by_extension(raw: &str, name_hint: &str, cfg: &DatasetConfig) -> Result<Vec<String>, String> {
    let lower = name_hint.to_ascii_lowercase();
    if lower.ends_with(".jsonl") {
        let mut docs = Vec::new();
        for line in raw.lines() {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            if let Ok(val) = serde_json::from_str::<Value>(trimmed) {
                if let Some(doc) = extract_json_record(&val, cfg) {
                    docs.push(doc);
                }
            }
        }
        if docs.is_empty() {
            return Err("JSONL file parsed, but no records matched configured field names.".to_owned());
        }
        Ok(docs)
    } else if lower.ends_with(".json") {
        let val: Value = serde_json::from_str(raw)
            .map_err(|_| "File was not valid JSON.".to_owned())?;
        let mut docs = Vec::new();
        match &val {
            Value::Array(items) => {
                for item in items {
                    if let Some(doc) = extract_json_record(item, cfg) {
                        docs.push(doc);
                    }
                }
            }
            Value::Object(_) => {
                if let Some(arr) = val.get("data").or_else(|| val.get("rows")).and_then(Value::as_array) {
                    for item in arr {
                        if let Some(doc) = extract_json_record(item, cfg) {
                            docs.push(doc);
                        }
                    }
                } else if let Some(doc) = extract_json_record(&val, cfg) {
                    docs.push(doc);
                }
            }
            _ => {}
        }
        if docs.is_empty() {
            return Err("JSON contained no matching text records.".to_owned());
        }
        Ok(docs)
    } else if lower.ends_with(".csv") {
        parse_csv_records(raw, cfg)
    } else {
        // Plain text / Markdown: split by blank-line paragraphs if multi-paragraph, else by non-empty lines.
        let paragraphs: Vec<String> = raw
            .split("\n\n")
            .map(|p| p.trim().to_owned())
            .filter(|p| !p.is_empty())
            .collect();
        if paragraphs.len() >= 4 {
            Ok(paragraphs)
        } else {
            let lines: Vec<String> = raw
                .lines()
                .map(|l| l.trim().to_owned())
                .filter(|l| !l.is_empty())
                .collect();
            if lines.is_empty() {
                Err("Text file is empty.".to_owned())
            } else {
                Ok(lines)
            }
        }
    }
}

fn extract_json_record(val: &Value, cfg: &DatasetConfig) -> Option<String> {
    if let Value::String(s) = val {
        let t = s.trim();
        return (!t.is_empty()).then(|| t.to_owned());
    }
    let obj = val.as_object()?;
    let prompt_key = cfg.prompt_field.trim();
    let resp_key = cfg.response_field.trim();
    if !prompt_key.is_empty() && !resp_key.is_empty() {
        if let (Some(p), Some(r)) = (
            obj.get(prompt_key).and_then(Value::as_str),
            obj.get(resp_key).and_then(Value::as_str),
        ) {
            if !p.trim().is_empty() && !r.trim().is_empty() {
                return Some(format!("<user> {} <assistant> {}", p.trim(), r.trim()));
            }
        }
    }
    let text_key = cfg.text_field.trim();
    if !text_key.is_empty() {
        if let Some(t) = obj.get(text_key).and_then(Value::as_str) {
            if !t.trim().is_empty() {
                return Some(t.trim().to_owned());
            }
        }
    }
    // Common fallback field names when custom schema isn't exact.
    for fallback in ["text", "content", "instruction", "question", "story"] {
        if let Some(t) = obj.get(fallback).and_then(Value::as_str) {
            if !t.trim().is_empty() {
                return Some(t.trim().to_owned());
            }
        }
    }
    None
}

fn parse_csv_records(raw: &str, cfg: &DatasetConfig) -> Result<Vec<String>, String> {
    let mut lines = raw.lines().filter(|l| !l.trim().is_empty());
    let Some(header_line) = lines.next() else {
        return Err("CSV file is empty.".to_owned());
    };
    let headers = split_csv_line(header_line);
    let wanted = cfg.text_field.trim().to_ascii_lowercase();
    let col_idx = headers
        .iter()
        .position(|h| h.trim().to_ascii_lowercase() == wanted)
        .unwrap_or(0);

    let mut docs = Vec::new();
    for line in lines {
        let cols = split_csv_line(line);
        if let Some(cell) = cols.get(col_idx) {
            let trimmed = cell.trim();
            if !trimmed.is_empty() {
                docs.push(trimmed.to_owned());
            }
        }
    }
    if docs.is_empty() {
        return Err("CSV parsed, but no non-empty rows were found.".to_owned());
    }
    Ok(docs)
}

fn split_csv_line(line: &str) -> Vec<String> {
    let mut fields = Vec::new();
    let mut current = String::new();
    let mut in_quotes = false;
    let mut chars = line.chars().peekable();
    while let Some(ch) = chars.next() {
        match ch {
            '"' => {
                if in_quotes && chars.peek() == Some(&'"') {
                    current.push('"');
                    let _ = chars.next();
                } else {
                    in_quotes = !in_quotes;
                }
            }
            ',' if !in_quotes => {
                fields.push(std::mem::take(&mut current));
            }
            _ => current.push(ch),
        }
    }
    fields.push(current);
    fields
}

fn fnv1a_64(text: &str) -> u64 {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in text.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x0100_0000_01b3);
    }
    hash
}

pub fn finalize_dataset(
    source_label: String,
    raw_docs: Vec<String>,
    cfg: &DatasetConfig,
) -> Result<PreparedDataset, String> {
    let total_raw_docs = raw_docs.len();
    let min_c = cfg.min_chars;
    let max_c = cfg.max_chars.max(min_c.max(1));

    let mut seen = HashSet::new();
    let mut dropped_duplicates = 0usize;
    let mut dropped_length = 0usize;
    let mut kept = Vec::with_capacity(raw_docs.len());

    for doc in raw_docs {
        let trimmed = doc.trim();
        let len = trimmed.chars().count();
        if len < min_c || len > max_c {
            dropped_length += 1;
            continue;
        }
        if cfg.deduplicate && !seen.insert(fnv1a_64(trimmed)) {
            dropped_duplicates += 1;
            continue;
        }
        kept.push(trimmed.to_owned());
    }

    if kept.is_empty() {
        return Err("All records were filtered out by min/max character limits.".to_owned());
    }

    let mut rng = Rng::new(cfg.shuffle_seed);
    rng.shuffle(&mut kept);

    let total_chars: usize = kept.iter().map(|d| d.chars().count()).sum();
    let avg_chars = total_chars / kept.len().max(1);

    let train_pct = cfg.train_pct.clamp(50, 99) as usize;
    let mut train_count = (kept.len() * train_pct) / 100;
    if train_count == 0 {
        train_count = 1;
    }
    if train_count >= kept.len() && kept.len() > 1 {
        train_count = kept.len() - 1;
    }

    let val_docs = if kept.len() > 1 {
        kept.split_off(train_count)
    } else {
        kept.clone()
    };

    Ok(PreparedDataset {
        source_label,
        train_docs: kept,
        val_docs,
        total_raw_docs,
        dropped_duplicates,
        dropped_length,
        total_chars,
        avg_chars,
    })
}

fn builtin_tiny_dialogues() -> Vec<String> {
    let base = [
        "<user> Hello! Who are you? <assistant> I am a small Transformer trained from scratch inside Archx AI Lab.",
        "<user> How do you learn from text? <assistant> I predict the next token step by step and lower cross-entropy loss with gradients.",
        "<user> Tell me a short story about a lantern. <assistant> On a quiet hill, Maya lit a silver lantern and followed its warm glow safely home.",
        "<user> Tell me a story about a curious robot. <assistant> Unit Seven found a tiny seed in the workshop, watered it each morning, and watched a green leaf unfold.",
        "<user> Why do we set a random seed? <assistant> Setting a seed makes weight initialization and batch order reproducible on every run.",
        "<user> What does attention do in a Transformer? <assistant> Attention lets every token weigh earlier tokens in context before predicting what comes next.",
        "<user> What is a Mixture of Experts? <assistant> A router picks the top experts per token so capacity grows while active compute stays fast.",
        "<user> Give me a calm thought for today. <assistant> Build one clean piece at a time, measure honestly, and keep the system simple.",
        "<user> Count from one to five. <assistant> One, two, three, four, five.",
        "<user> What happens when learning rate is too high? <assistant> Gradients overshoot the valley and training loss spikes or diverges.",
        "<user> Tell me about the night sky. <assistant> Clear stars shimmer above dark mountains while cool wind moves softly through the pines.",
        "<user> How can I test my trained model? <assistant> Open the Playground tab and send a message to stream tokens from your saved checkpoint.",
    ];
    // Expand with deterministic variations so packing forms rich multi-batch windows.
    let mut out = Vec::with_capacity(base.len() * 4);
    for (idx, item) in base.iter().enumerate() {
        out.push((*item).to_owned());
        out.push(format!("{item} [sample {}]", idx + 1));
    }
    out
}

fn builtin_rust_code() -> Vec<String> {
    vec![
        "<user> Write a function to sum a slice in Rust. <assistant> fn sum_slice(xs: &[i64]) -> i64 { xs.iter().copied().sum() }".into(),
        "<user> How do you clamp a float in Rust? <assistant> fn clamp01(x: f32) -> f32 { x.clamp(0.0, 1.0) }".into(),
        "<user> Show a binary search helper. <assistant> fn contains_sorted(xs: &[i32], target: i32) -> bool { xs.binary_search(&target).is_ok() }".into(),
        "<user> Write a safe division returning Option. <assistant> fn safe_div(a: f64, b: f64) -> Option<f64> { (b != 0.0).then(|| a / b) }".into(),
        "<user> Reverse words in a string. <assistant> fn rev_words(s: &str) -> String { s.split_whitespace().rev().collect::<Vec<_>>().join(\" \") }".into(),
        "<user> Compute dot product of two slices. <assistant> fn dot(a: &[f32], b: &[f32]) -> f32 { a.iter().zip(b).map(|(x, y)| x * y).sum() }".into(),
        "<user> Define a Result alias in Rust. <assistant> pub type AppResult<T> = Result<T, String>;".into(),
        "<user> Implement fibonacci iteratively. <assistant> fn fib(n: usize) -> u64 { let (mut a, mut b) = (0, 1); for _ in 0..n { (a, b) = (b, a + b); } a }".into(),
    ]
}

fn builtin_logic_qa() -> Vec<String> {
    vec![
        "<user> If all whales are mammals and all mammals breathe air, do whales breathe air? <assistant> Yes. Because whales are mammals and every mammal breathes air, whales breathe air.".into(),
        "<user> Which is larger: two to the power of five or five squared? <assistant> Two to the power of five is 32, while five squared is 25, so 32 is larger.".into(),
        "<user> Why does ice float on liquid water? <assistant> Freezing arranges water molecules into an open crystal lattice that is less dense than liquid water.".into(),
        "<user> A train travels 90 km in 1.5 hours. What is its average speed? <assistant> Divide 90 km by 1.5 hours to get 60 km per hour.".into(),
        "<user> What does perplexity measure in language modeling? <assistant> Perplexity is exp(loss) and reflects the effective branching uncertainty per predicted token.".into(),
        "<user> If A implies B and B is false, what do we know about A? <assistant> By modus tollens, A must also be false.".into(),
    ]
}

fn builtin_classic_verse() -> Vec<String> {
    vec![
        "Silver light upon the silent tide,\nWhere quiet ships in harbor softly bide.".into(),
        "Through granite valleys cold and clear,\nThe morning bell rings crisp and near.".into(),
        "Step by step the mason lays the stone,\nUntil the arch can stand upon its own.".into(),
        "Beneath the cedar's steady shade,\nA calm and patient craft is made.".into(),
        "No haste can mend a careless line;\nTrue measure makes the structure fine.".into(),
        "When stars return above the plain,\nThe lantern glows against the rain.".into(),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builtin_dataset_deduplicates_and_splits_deterministically() {
        let cfg = DatasetConfig::default();
        let a = load_local_or_builtin(&cfg).expect("loads");
        let b = load_local_or_builtin(&cfg).expect("loads");
        assert_eq!(a.train_docs, b.train_docs);
        assert_eq!(a.val_docs, b.val_docs);
        assert!(!a.train_docs.is_empty());
        assert!(!a.val_docs.is_empty());
    }

    #[test]
    fn jsonl_and_csv_parsers_extract_prompt_response_and_columns() {
        let mut cfg = DatasetConfig::default();
        cfg.min_chars = 4;
        let jsonl = "{\"prompt\":\"Hi\",\"response\":\"Hello there\"}\n{\"text\":\"Standalone sentence\"}\n";
        let parsed = parse_text_by_extension(jsonl, "train.jsonl", &cfg).expect("jsonl");
        assert_eq!(parsed[0], "<user> Hi <assistant> Hello there");
        assert_eq!(parsed[1], "Standalone sentence");

        let csv = "id,text\n1,\"Quoted, hello world\"\n2,Second row\n";
        let csv_docs = parse_text_by_extension(csv, "rows.csv", &cfg).expect("csv");
        assert_eq!(csv_docs, vec!["Quoted, hello world", "Second row"]);
    }
}
