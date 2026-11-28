//! Fetches and parses the public awesome-free-llm-apis list as untrusted data.
use reqwest::{Client, redirect};

pub const SOURCE: &str = "https://github.com/mnfst/awesome-free-llm-apis";
pub const RAW: &str = "https://raw.githubusercontent.com/mnfst/awesome-free-llm-apis/main/README.md";
pub const REFRESH_SECS: u64 = 7200;
const MAX_BYTES: usize = 1_000_000;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Row {
    pub provider: String,
    pub model: String,
    pub details: String,
}

/// Extract only provider headings and model table rows; links and HTML are never executed.
pub fn parse(markdown: &str) -> Vec<Row> {
    let mut provider = String::new();
    let mut rows = Vec::new();
    for line in markdown.lines() {
        if let Some(heading) = line.strip_prefix("### [") {
            provider = heading.split(']').next().unwrap_or("").chars().take(100).collect();
        } else if !provider.is_empty() && line.starts_with('|') && line.contains('`') {
            let cells: Vec<_> = line.trim_matches('|').split('|').map(str::trim).collect();
            if let Some(first) = cells.first() {
                if !first.starts_with('`') { continue; }
                let model = first.trim_matches('`').chars().take(200).collect::<String>();
                if model.is_empty() { continue; }
                let details = cells.iter().skip(1).map(|s| s.replace('`', "")).collect::<Vec<_>>().join(" · ");
                rows.push(Row { provider: provider.clone(), model, details: details.chars().take(400).collect() });
                if rows.len() >= 5000 { break; }
            }
        }
    }
    rows
}

pub async fn fetch() -> Result<String, String> {
    let client = Client::builder().https_only(true).no_proxy().redirect(redirect::Policy::none())
        .timeout(std::time::Duration::from_secs(30)).build().map_err(|_| "Unable to create HTTPS client".to_string())?;
    let mut response = client.get(RAW).send().await.map_err(|_| "Free-tier list could not be fetched".to_string())?;
    if !response.status().is_success() { return Err(format!("Free-tier list HTTP {}", response.status())); }
    let mut data = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "Free-tier list download interrupted".to_string())? {
        if data.len() + chunk.len() > MAX_BYTES { return Err("Free-tier list is too large".to_string()); }
        data.extend_from_slice(&chunk);
    }
    let text = String::from_utf8(data).map_err(|_| "Free-tier list was not UTF-8".to_string())?;
    if parse(&text).is_empty() { return Err("No model rows found in the free-tier list".to_string()); }
    Ok(text)
}

pub fn save(text: &str) -> std::io::Result<()> {
    let dir = crate::storage::root();
    std::fs::create_dir_all(&dir)?;
    std::fs::write(dir.join("free-tier-list.md"), text)
}

pub fn load() -> Option<(Vec<Row>, u64)> {
    let path = crate::storage::root().join("free-tier-list.md");
    let metadata = std::fs::metadata(&path).ok()?;
    if metadata.len() > MAX_BYTES as u64 { return None; }
    let at = metadata.modified().ok()?.duration_since(std::time::UNIX_EPOCH).ok()?.as_secs();
    let rows = parse(&std::fs::read_to_string(path).ok()?);
    (!rows.is_empty()).then_some((rows, at))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn parser_preserves_provider_and_rate_fields_without_executing_links() {
        let rows = parse("### [Groq](https://example.test)\n| Model | Context | Rate |\n| `llama` | 128K | 30 RPM |\n");
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].provider, "Groq");
        assert_eq!(rows[0].model, "llama");
        assert_eq!(rows[0].details, "128K · 30 RPM");
    }
}
