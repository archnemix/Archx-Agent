//! Purpose: The Agent's provider, key-rotation, endpoint, model, catalog, debug and storage message handling.
//!
//! Split out of `app.rs` so the chat state machine stays readable. Every branch
//! here either mutates session state (and persists what should survive) or
//! starts exactly one explicit network request that the user asked for.

use std::collections::HashSet;
use std::time::Duration;

use iced::task::sipper;
use iced::Task;
use zeroize::Zeroizing;

use crate::app::{App, Message, MemoryMode, MemoryScope, Page};
use archx_shared::credentials::{Provider, Vault, VaultError};
use archx_shared::health::{KeyHealthSet, ModelHealthSet};
use crate::custom_endpoint;
use archx_shared::debug_log;
use archx_shared::diagnostics;
use archx_shared::endpoints;
use archx_shared::model_catalog::{self, CatalogModel};
use archx_shared::persist::PersistedSettings;
use archx_shared::provider_api::{self, CallError, Failure, Turn};
use crate::settings::{SecretText, Section};
use archx_shared::storage;
use crate::test_journal;
use archx_shared::transcripts::StoredChat;

impl App {
    pub(super) fn update_provider(&mut self, message: Message) -> Task<Message> {
        match message {
            // ---------- providers -------------------------------------------------
            Message::SelectProvider(provider) if !self.settings.key_busy && !self.settings.probe_busy => {
                self.settings.clear_secret();
                self.settings.custom_approved = false;
                self.settings.discard_catalog_staging();
                self.settings.catalog_modal = false;
                self.settings.provider = provider;
                self.settings.model_entry.clear();
                self.settings.search.clear();
                self.settings.probe_pending = false;
                self.settings.catalog_nonce = self.settings.catalog_nonce.wrapping_add(1);
                self.settings.catalog_busy = false;
                self.settings.key_ids.clear();
                self.settings.status.clear();
                self.settings.provider_picker = false;
                self.bulk_clear();
                self.persist_settings();
                if self.page == Page::Settings { return self.update(Message::RefreshKeys); }
            }
            Message::OpenProviderPicker => {
                // One flag, read by the settings view: the app owns it.
                self.settings.provider_picker = true;
            }
            Message::CloseProviderPicker => {
                self.settings.provider_picker = false;
            }
            Message::RefreshKeys => {
                let provider = self.settings.provider;
                return Task::perform(async move {
                    tokio::task::spawn_blocking(move || Vault::os().list(provider)).await
                        .unwrap_or(Err(VaultError::Unavailable))
                }, move |result| Message::KeysLoaded(provider, result));
            }
            Message::KeysLoaded(provider, result) if self.settings.provider == provider => {
                match result {
                    Ok(ids) => {
                        self.settings.key_ids = ids.clone();
                        self.keys.sync(&ids);
                        self.settings.status.clear();
                        self.persist_settings();
                    }
                    Err(error) => self.settings.status = error.message().into(),
                }
            }
            Message::EditKey(value) if self.settings.section != Section::Lab => {
                if value.0.len() <= 1024 { self.settings.key_entry = value; }
            }
            Message::SaveKey if self.settings.section != Section::Lab
                && !self.settings.key_entry.0.is_empty() && !self.settings.key_busy => {
                self.settings.key_busy = true;
                self.settings.custom_approved = false;
                let provider = self.settings.provider;
                let secret = std::mem::take(&mut self.settings.key_entry).0;
                self.settings.clear_secret();
                self.settings.status = "Saving to the OS vault…".into();
                return Task::perform(async move {
                    tokio::task::spawn_blocking(move || Vault::os().add(provider, secret))
                        .await.unwrap_or(Err(VaultError::Unavailable))
                }, move |result| Message::KeySaved(provider, result));
            }
            Message::KeySaved(provider, result) if self.settings.provider == provider => {
                self.settings.key_busy = false;
                match result {
                    Ok(id) => {
                        self.settings.key_ids.push(id);
                        self.settings.key_ids.sort_unstable();
                        self.keys.sync(&self.settings.key_ids);
                        self.settings.status = format!("Key {id} saved to the OS vault. Rotation will use it on the next request.");
                        self.persist_settings();
                        return self.update(Message::RefreshKeys);
                    }
                    Err(error) => self.settings.status = error.message().into(),
                }
            }
            Message::RemoveKey(id) if !self.settings.key_busy => {
                self.settings.key_busy = true;
                let provider = self.settings.provider;
                return Task::perform(async move {
                    tokio::task::spawn_blocking(move || Vault::os().remove(provider, id)).await
                        .unwrap_or(Err(VaultError::Unavailable))
                }, move |result| Message::KeyRemoved(provider, result));
            }
            Message::KeyRemoved(provider, result) if self.settings.provider == provider => {
                self.settings.key_busy = false;
                match result {
                    Ok(()) => {
                        self.settings.key_ids.retain(|key| self.keys.slot(*key).is_some());
                        let remaining = self.settings.key_ids.clone();
                        self.keys.sync(&remaining);
                        self.settings.status = "Key removed from the OS vault.".into();
                        self.persist_settings();
                        return self.update(Message::RefreshKeys);
                    }
                    Err(error) => self.settings.status = error.message().into(),
                }
            }
            Message::FetchKeyUsage => {
                let provider = self.settings.provider;
                let nonce = self.settings.usage_nonce.wrapping_add(1);
                self.settings.usage_nonce = nonce;
                self.settings.usage_busy = true;
                self.settings.usage = None;
                if !provider.needs_key() {
                    self.settings.usage_busy = false;
                    self.settings.usage = Some(Ok(None));
                    return Task::none();
                }
                let ids = self.settings.key_ids.clone();
                return Task::perform(async move {
                    // Use the first key that is not resting; a resting key is
                    // still readable, so fall back to key 1 and let the provider
                    // decide rather than refusing to ask.
                    let id = ids.first().copied().unwrap_or(1);
                    let secret = tokio::task::spawn_blocking(move || Vault::os().with_key(provider, id, |key| SecretText::new(key.to_owned())))
                        .await.unwrap_or(Err(VaultError::Unavailable));
                    match secret {
                        Ok(secret) => archx_shared::usage::fetch_key_usage(provider, secret.0).await.map(Some),
                        Err(error) => Err(error.message().to_owned()),
                    }
                }, move |result| Message::KeyUsageRead(nonce, result));
            }
            Message::KeyUsageRead(nonce, result) if self.settings.usage_nonce == nonce => {
                self.settings.usage_busy = false;
                self.settings.usage = Some(result);
            }
            Message::RevealKey(id) => {
                let provider = self.settings.provider;
                let nonce = self.settings.reveal_nonce.wrapping_add(1);
                self.settings.reveal_nonce = nonce;
                return Task::perform(async move {
                    tokio::task::spawn_blocking(move || Vault::os().with_key(provider, id, |secret| SecretText::new(secret.to_owned())))
                        .await.unwrap_or(Err(VaultError::Unavailable))
                }, move |result| Message::KeyRevealed(nonce, id, result));
            }
            Message::KeyRevealed(nonce, id, result) if self.settings.reveal_nonce == nonce => {
                match result {
                    Ok(secret) => {
                        self.settings.reveal = Some((id, secret, std::time::Instant::now() + Duration::from_secs(15)));
                        // A revealed key hides itself after 15 s. The deadline is
                        // also checked on render, so a suspended timer can only
                        // hide it later, never keep it visible longer.
                        return iced::Task::perform(
                            async move { tokio::time::sleep(Duration::from_secs(15)).await; nonce },
                            Message::RevealExpired);

                    }
                    Err(error) => self.settings.status = error.message().into(),
                }
            }
            Message::RevealExpired(nonce) if self.settings.reveal_nonce == nonce => {
                self.settings.reveal = None;
            }
            Message::HideKey => self.settings.reveal = None,
            Message::ToggleAutoRotate => {
                self.keys.auto_rotate = !self.keys.auto_rotate;
                self.persist_settings();
            }
            Message::RetryKeyNow(id) => {
                if let Some(slot) = self.keys.slots.iter_mut().find(|slot| slot.id == id) {
                    slot.cooldown_until = 0;
                    slot.failures = 0;
                    slot.reason.clear();
                }
                self.settings.status = format!("Key {id} is available again for the next request.");
                self.persist_settings();
            }

            // ---------- endpoints -------------------------------------------------
            Message::EditEndpoint(kind, value) if value.chars().count() <= 512 => {
                self.endpoint_draft = Some((kind, value));
            }
            Message::SaveEndpoint(kind) => {
                let Some((draft_kind, value)) = self.endpoint_draft.clone() else {
                    // No edit pending: save the value as shown (an explicit revert).
                    let value = self.endpoints.value(self.settings.provider, kind);
                    return self.save_endpoint_value(kind, value);
                };
                if draft_kind != kind { return Task::none(); }
                match self.endpoints.set(self.settings.provider, kind, &value) {
                    Ok(()) => {
                        self.endpoint_draft = None;
                        self.settings.status = format!("{} saved. The next request uses it.", kind.label());
                        self.persist_settings();
                    }
                    Err(error) => self.settings.status = error.into(),
                }
            }
            Message::ResetEndpoint(kind) => {
                let template = endpoints::default_template(self.settings.provider);
                let documented = match kind {
                    endpoints::Kind::Chat => template.chat,
                    endpoints::Kind::Stream => template.stream,
                    endpoints::Kind::Models => template.models,
                };
                self.endpoints.reset_kind(self.settings.provider, kind);
                // Show the documented value and confirm it validates.
                self.endpoint_draft = Some((kind, documented.to_owned()));
                self.settings.status = format!("{} restored to the documented URL.", kind.label());
                self.persist_settings();
            }

            // ---------- models ----------------------------------------------------
            Message::EditModel(value) if value.chars().count() <= 100 => self.settings.model_entry = value,
            Message::AddModel => {
                let provider = self.settings.provider;
                let id = self.settings.model_entry.trim().to_owned();
                let index = self.settings.index();
                if !provider_api::valid_model(provider, &id) || self.settings.models[index].contains(&id) {
                    self.settings.status = "Enter a valid, not-yet-imported model ID.".into();
                } else {
                    if !self.settings.catalog[index].iter().any(|item| item.id == id) {
                        self.settings.catalog[index].push(CatalogModel {
                            id: id.clone(), name: id.clone(), free: false, router: false, reasoning: false,
                        });
                        self.settings.catalog_manual[index].push(id.clone());
                    }
                    self.settings.models[index].push(id.clone());
                    self.model_health.sync(&self.settings.models[index]);
                    self.settings.model_entry.clear();
                    self.settings.search.clear();
                    self.settings.status = "Model added. It is enabled and selectable now; testing is optional.".into();
                    self.persist_settings();
                }
            }
            Message::ChooseModel(slot) if slot < self.settings.models[self.settings.index()].len() => {
                let index = self.settings.index();
                let id = self.settings.models[index][slot].clone();
                if !self.model_health.is_enabled(&id) {
                    self.settings.status = format!("\"{id}\" is disabled. Enable it before selecting it.");
                } else {
                    self.settings.chosen[index] = Some(slot);
                    self.model_menu_open = false;
                    self.persist_settings();
                }
            }
            Message::RemoveModel(slot) if slot < self.settings.models[self.settings.index()].len() => {
                let index = self.settings.index();
                let removed = self.settings.models[index].remove(slot);
                self.settings.chosen[index] = None;
                self.settings.bulk_selected.retain(|id| id != &removed);
                self.model_health.sync(&self.settings.models[index]);
                self.settings.status = format!("Removed \"{removed}\". Vault keys and other models are untouched.");
                self.persist_settings();
            }
            Message::ToggleModelEnabled(id) => {
                if self.model_health.is_enabled(&id) {
                    self.model_health.disable(&id, "disabled by you", storage::now_secs());
                    self.settings.status = format!("\"{id}\" disabled. It stays in the list and can be re-enabled.");
                    if self.settings.selected_model() == Some(id.as_str()) { self.settings.chosen[self.settings.index()] = None; }
                } else {
                    self.model_health.enable(&id);
                    self.settings.status = format!("\"{id}\" enabled again.");
                }
                self.persist_settings();
            }
            Message::EnableAllModels => {
                let ids: Vec<String> = self.model_health.disabled_ids().iter().map(|id| (*id).to_owned()).collect();
                for id in &ids { self.model_health.enable(id); }
                self.settings.status = format!("Re-enabled {} model(s).", ids.len());
                self.persist_settings();
            }
            Message::ToggleAutoDisable => {
                self.model_health.auto_disable = !self.model_health.auto_disable;
                self.settings.status = format!("Automatic model disabling is now {}.",
                    if self.model_health.auto_disable { "on" } else { "off" });
                self.persist_settings();
            }
            Message::BulkSelect(slot, selected) if slot < self.settings.models[self.settings.index()].len() => {
                let model = self.settings.models[self.settings.index()][slot].clone();
                if selected { self.settings.bulk_selected.insert(model); }
                else { self.settings.bulk_selected.remove(&model); }
            }
            Message::BulkSelectMatching => {
                let index = self.settings.index();
                let query = self.settings.search.trim().to_lowercase();
                let models = self.settings.models[index].clone();
                for model in models {
                    if query.is_empty() || model.to_lowercase().contains(&query) {
                        self.settings.bulk_selected.insert(model);
                    }
                }
            }
            Message::BulkClearSelection => self.bulk_clear(),
            Message::BulkRunSelected => {
                let selected: Vec<String> = self.selected_in_order();
                if selected.is_empty() {
                    self.settings.status = "Select at least one model first.".into();
                } else {
                    return self.start_probe(selected);
                }
            }
            Message::BulkRemoveSelected => {
                let selected = self.selected_in_order();
                let index = self.settings.index();
                self.settings.models[index].retain(|model| !selected.contains(model));
                self.settings.chosen[index] = None;
                self.model_health.sync(&self.settings.models[index]);
                self.settings.status = format!("Removed {} selected model(s).", selected.len());
                self.bulk_clear();
                self.persist_settings();
            }
            Message::BulkDisableSelected => {
                let selected = self.selected_in_order();
                let now = storage::now_secs();
                for id in &selected { self.model_health.disable(id, "disabled by you", now); }
                if self.settings.selected_model().is_some_and(|model| selected.iter().any(|id| id == model)) {
                    self.settings.chosen[self.settings.index()] = None;
                }
                self.settings.status = format!("Disabled {} selected model(s).", selected.len());
                self.bulk_clear();
                self.persist_settings();
            }
            Message::BulkEnableSelected => {
                let selected = self.selected_in_order();
                for id in &selected { self.model_health.enable(id); }
                self.settings.status = format!("Enabled {} selected model(s).", selected.len());
                self.bulk_clear();
                self.persist_settings();
            }
            Message::SearchModels(query) if query.chars().count() <= 100 && self.settings.section != Section::Lab => {
                self.settings.search = query;
                self.settings.model_page = 0;
                self.settings.catalog_page = 0;
            }
            Message::ModelPageNext => self.settings.model_page = self.settings.model_page.saturating_add(1),
            Message::ModelPagePrevious => self.settings.model_page = self.settings.model_page.saturating_sub(1),

            // ---------- catalog dialog -------------------------------------------
            Message::OpenCatalogModal if self.settings.section == Section::Models => {
                self.settings.discard_catalog_staging();
                self.settings.catalog_modal = true;
                self.settings.catalog_page = 0;
            }
            Message::CloseCatalogModal => {
                // Item 5: closing the dialog is a view action, never a cancel.
                // A run in flight keeps going, keeps saving each result, and
                // keeps reporting in Settings. Only "Stop testing" cancels, and
                // only a new run overwrites what is stored.
                self.settings.discard_catalog_staging();
                self.settings.catalog_modal = false;
                self.settings.probe_pending = false;
                if self.settings.probe_busy {
                    self.settings.status = "Dialog closed. Testing continues in the background; results are saved as they arrive.".into();
                }
            }
            Message::CatalogNext if self.settings.catalog_modal => {
                self.settings.catalog_page = self.settings.catalog_page.saturating_add(1);
            }
            Message::CatalogPrevious if self.settings.catalog_modal => {
                self.settings.catalog_page = self.settings.catalog_page.saturating_sub(1);
            }
            Message::ToggleCatalogSelection(provider, slot) if self.settings.provider == provider && !self.settings.probe_busy => {
                if let Some(item) = self.settings.catalog[self.settings.index()].get(slot).cloned() {
                    self.settings.catalog_selected[self.settings.index()].retain(|id| id != &item.id);
                    self.bulk_note(&item.id);
                }
            }
            Message::SelectMatchingModels if self.settings.catalog_modal && !self.settings.probe_busy => {
                let index = self.settings.index();
                let query = self.settings.search.trim().to_lowercase();
                let added: HashSet<&str> = self.settings.models[index].iter().map(String::as_str).collect();
                let mut selected: HashSet<String> = self.settings.catalog_selected[index].iter().cloned().collect();
                let matching: Vec<String> = self.settings.catalog[index].iter()
                    .filter(|item| !added.contains(item.id.as_str()))
                    .filter(|item| query.is_empty() || item.id.to_lowercase().contains(&query) || item.name.to_lowercase().contains(&query))
                    .map(|item| item.id.clone()).collect();
                for id in matching {
                    if selected.insert(id.clone()) { self.settings.catalog_selected[index].push(id); }
                }
            }
            Message::ClearCatalogSelection if self.settings.catalog_modal && !self.settings.probe_busy => {
                self.settings.catalog_selected[self.settings.index()].clear();
            }
            Message::ToggleCatalogVerified if self.settings.catalog_modal && !self.settings.probe_busy => {
                self.settings.catalog_only_verified = !self.settings.catalog_only_verified;
            }
            Message::StageCatalogId if !self.settings.probe_busy => {
                let provider = self.settings.provider;
                let id = self.settings.model_entry.trim().to_owned();
                let index = self.settings.index();
                if !provider_api::valid_model(provider, &id) || self.settings.models[index].contains(&id) {
                    self.settings.status = "Enter a valid, not-yet-imported model ID.".into();
                } else {
                    if !self.settings.catalog[index].iter().any(|item| item.id == id) {
                        self.settings.catalog[index].push(CatalogModel {
                            id: id.clone(), name: id.clone(), free: false, router: false, reasoning: false,
                        });
                        self.settings.catalog_manual[index].push(id.clone());
                    }
                    if !self.settings.catalog_selected[index].contains(&id) {
                        self.settings.catalog_selected[index].push(id);
                    }
                    self.settings.model_entry.clear();
                    self.settings.status = "ID staged and checked; it is not imported or tested until you choose those actions.".into();
                }
            }
            Message::ImportSelectedModels if !self.settings.probe_busy => {
                let index = self.settings.index();
                let importable: HashSet<String> = self.settings.importable_catalog_ids().into_iter().collect();
                if importable.is_empty() && self.settings.catalog_only_verified {
                    self.settings.status = "No checked IDs have passed the expected-word probe. Turn off verified-only, or test them.".into();
                    return Task::none();
                }
                let checked = std::mem::take(&mut self.settings.catalog_selected[index]);
                let skipped = checked.iter().filter(|id| !importable.contains(*id)).count();
                for id in checked {
                    if importable.contains(&id) && !self.settings.models[index].contains(&id) {
                        self.settings.models[index].push(id);
                    }
                }
                self.model_health.sync(&self.settings.models[index]);
                self.settings.status = format!("Added {} models · {skipped} skipped.", importable.len());
                self.settings.discard_catalog_staging();
                self.settings.catalog_modal = false;
                self.persist_settings();
            }
            Message::RequestCatalogProbe if !self.settings.probe_busy => {
                let ids = self.settings.catalog_selected[self.settings.index()].clone();
                if ids.is_empty() {
                    self.settings.status = "Select at least one model first.".into();
                } else {
                    self.settings.probe_pending = true;
                }
            }
            Message::CancelCatalogProbe => {
                self.settings.probe_pending = false;
                if self.settings.probe_busy {
                    if let Some(handle) = self.probe_handle.take() { handle.abort(); }
                    self.settings.probe_busy = false;
                    self.settings.probe_nonce = self.settings.probe_nonce.wrapping_add(1);
                    self.settings.status = "Testing stopped. Results already received are saved; no further models will be tested.".into();
                    self.persist_tests();
                }
            }
            Message::ConfirmCatalogProbe if self.settings.probe_pending && !self.settings.probe_busy && self.snapshot.is_none() => {
                self.settings.probe_pending = false;
                let ids = self.settings.catalog_selected[self.settings.index()].clone();
                return self.start_probe(ids);
            }
            Message::CatalogProbeProgress(provider, nonce, id, result) if self.settings.provider == provider
                && self.settings.probe_busy && self.settings.probe_nonce == nonce => {
                let (ok, output) = match result {
                    Ok((text, ms)) => {
                        let received: String = text.0.chars().filter(|c| !c.is_control() || *c == '\n').take(240).collect();
                        let expected = if self.settings.expected_word.is_empty() { "OK" } else { &self.settings.expected_word };
                        let passed = text.0.to_lowercase().contains(&expected.to_lowercase());
                        (passed, format!("{ms} ms · {} · {received}", if passed { "expected word found" } else { "expected word missing" }))
                    }
                    Err(error) => (false, error),
                };
                if !ok { self.probe_failure_seen(&id, &output); }
                // A row that never reached the provider (no usable key, an
                // unapproved endpoint) is filed as "never sent". Only a real
                // answer, success or `HTTP nnn`, is filed as the provider's.
                let source = if ok || output.starts_with("HTTP") {
                    test_journal::Source::Provider
                } else {
                    test_journal::Source::NotSent
                };
                self.settings.probe_results.push((id.clone(), ok, output.clone()));
                test_journal::record(test_journal::Entry {
                    id, ok, output, source, at: storage::now_secs(),
                    request_timeout_secs: diagnostics::REQUEST_TIMEOUT_SECS,
                });
                self.store_probe_result();
            }
            Message::CatalogProbeDone(provider, nonce, result) if self.settings.provider == provider && self.settings.probe_nonce == nonce => {
                self.settings.probe_busy = false;
                self.probe_handle = None;
                let run = test_journal::finish(storage::now_secs());
                let summary = match result {
                    Ok(()) if run.not_sent() > 0 => format!(
                        "Testing finished: {} answered, {} never left this machine. Results are saved with their cause until you re-run them.",
                        run.answered(), run.not_sent()),
                    Ok(()) => "Testing finished. Results are saved until you re-run them.".to_owned(),
                    Err(error) => error,
                };
                self.settings.status = summary.clone();
                self.notice = Some(summary);
                self.settings.saved_run = Some(run);
                self.persist_tests();
            }
            Message::ToggleRuntime(stage, item) => {
                self.memory_budget.toggle(stage, item);
                if !self.memory_budget.keeps(stage, item) { self.release(item); }
                self.memory_budget = self.memory_budget.clone();
                self.settings.status = format!("{} is {} at {}.",
                    item.label(), if self.memory_budget.keeps(stage, item) { "kept" } else { "dropped" }, stage.label());
                self.persist_settings();
            }
            Message::ScaleIn(area) => self.scale(area, true),
            Message::ScaleOut(area) => self.scale(area, false),
            Message::ScaleReset(area) => {
                self.display = match area {
                    crate::app::Area::Chat => archx_shared::persist::DisplaySettings { chat: Default::default(), ..self.display },
                    crate::app::Area::Settings => archx_shared::persist::DisplaySettings { settings: Default::default(), ..self.display },
                    crate::app::Area::Launcher => archx_shared::persist::DisplaySettings { launcher: Default::default(), ..self.display },
                };
                let _ = self.persist_settings();
            }
            Message::MeasureWider => {
                self.display = self.display.measure_wider();
                let _ = self.persist_settings();
            }
            Message::MeasureNarrower => {
                self.display = self.display.measure_narrower();
                let _ = self.persist_settings();
            }
            Message::DismissProbeResults => {
                self.settings.probe_results.clear();
                self.persist_tests();
            }
            Message::FetchModels if self.settings.provider != Provider::Custom
                && self.settings.section != Section::Lab && !self.settings.catalog_busy && self.snapshot.is_none() => {
                let provider = self.settings.provider;
                self.settings.catalog_busy = true;
                self.settings.catalog_nonce = self.settings.catalog_nonce.wrapping_add(1);
                let nonce = self.settings.catalog_nonce;
                let registry = self.endpoints.clone();
                self.settings.status = "Fetching catalog; no generation request is being sent…".into();
                return Task::perform(async move {
                    let key = if matches!(provider, Provider::OpenRouter | Provider::OllamaLocal) { None } else {
                        let result = tokio::task::spawn_blocking(move || {
                            let vault = Vault::os();
                            let id = vault.list(provider)?.first().copied().ok_or(VaultError::MissingKey)?;
                            vault.with_key(provider, id, |secret| Zeroizing::new(secret.to_owned()))
                        }).await.map_err(|_| VaultError::Unavailable).and_then(|result| result)
                            .map_err(|error| error.message().to_owned());
                        match result { Ok(key) => Some(key), Err(error) => return Err(error) }
                    };
                    model_catalog::fetch_via(provider, key, &registry).await.map_err(CallError::message)
                }, move |result| Message::ModelsFetched(provider, nonce, result));
            }
            Message::ModelsFetched(provider, nonce, result) if self.settings.provider == provider && self.settings.catalog_nonce == nonce => {
                self.settings.catalog_busy = false;
                match result {
                    Ok(models) => {
                        let count = models.len();
                        let index = self.settings.index();
                        let staged: Vec<CatalogModel> = self.settings.catalog[index].iter()
                            .filter(|item| self.settings.catalog_manual[index].contains(&item.id)).cloned().collect();
                        let staged_ids: HashSet<&str> = staged.iter().map(|item| item.id.as_str()).collect();
                        self.settings.catalog_selected[index].retain(|id| staged_ids.contains(id.as_str()));
                        self.settings.catalog_page = 0;
                        let mut fresh = models;
                        for item in staged {
                            if !fresh.iter().any(|model| model.id == item.id) { fresh.push(item); }
                        }
                        self.settings.catalog[index] = fresh.clone();
                        // The fetched list survives a restart so Models is not empty.
                        self.store.store_catalog(provider, fresh);
                        self.persist_chats_store();
                        self.settings.status = format!("Fetched {count} models. The list is saved and filtered locally.");
                    }
                    Err(error) => self.settings.status = error,
                }
            }
            Message::FetchModelMeta if self.snapshot.is_none() => {
                self.settings.status = "Fetching model metadata from models.dev…".into();
                return Task::perform(async { archx_shared::model_meta::fetch_models_dev().await.map(|registry| (registry.len(), registry)) },
                    |result| match result {
                        Ok((count, registry)) => {
                            let _ = archx_shared::model_meta::save_cache(&registry);
                            Message::ModelMetaFetched(Ok(count))
                        }
                        Err(error) => Message::ModelMetaFetched(Err(error)),
                    });
            }
            Message::ModelMetaFetched(result) => match result {
                Ok(count) => {
                    self.meta = archx_shared::model_meta::load_cache().map(|(registry, _)| registry);
                    self.meta_checked = Some(storage::now_secs());
                    self.settings.status = format!("Metadata for {count} models updated. Rows now show modality, context and price where known.");
                }
                Err(error) => self.settings.status = error,
            },

            // ---------- sweep models that no longer exist --------------------------
            Message::SweepModels if self.settings.provider != Provider::Custom && self.snapshot.is_none() => {
                let provider = self.settings.provider;
                let added = self.settings.models[self.settings.index()].clone();
                if added.is_empty() {
                    self.settings.status = "No models are added for this provider, so there is nothing to sweep.".into();
                    return Task::none();
                }
                if self.settings.meta.is_none() {
                    self.settings.meta = archx_shared::model_meta::load_cache().map(|(registry, _)| registry);
                }
                let meta_known = self.settings.meta.is_some();
                self.settings.sweep_nonce = self.settings.sweep_nonce.wrapping_add(1);
                let nonce = self.settings.sweep_nonce;
                let registry = self.endpoints.clone();
                self.settings.sweep = None;
                self.settings.sweep_undo.clear();
                self.settings.sweep_busy = true;
                self.settings.status = if meta_known {
                    format!("Checking {} added model(s) against the provider's live list…", added.len())
                } else {
                    format!("Checking {} added model(s) against the provider's live list (no models.dev cache yet)…", added.len())
                };
                // Same rule as FetchModels: OpenRouter's list is public and a
                // local Ollama needs no key. Anything else without a vault key
                // fails quietly into "models.dev only" instead of stopping.
                if matches!(provider, Provider::OpenRouter | Provider::OllamaLocal) {
                    return Task::perform(async move {
                        model_catalog::fetch_via(provider, None, &registry).await
                            .map(|models| models.into_iter().map(|model| model.id).collect::<Vec<_>>())
                            .map_err(CallError::message)
                    }, move |result| Message::SweepChecked(provider, nonce, result));
                }
                return Task::perform(async move {
                    let key = choose_key(provider, 0).await.map(|(_, key)| key).ok();
                    if key.is_none() {
                        return Err("No vault key for this provider, so only models.dev was consulted.".to_owned());
                    }
                    model_catalog::fetch_via(provider, key, &registry).await
                        .map(|models| models.into_iter().map(|model| model.id).collect::<Vec<_>>())
                        .map_err(CallError::message)
                }, move |result| Message::SweepChecked(provider, nonce, result));
            }
            Message::SweepChecked(provider, nonce, result) if provider == self.settings.provider && self.settings.sweep_nonce == nonce => {
                self.settings.sweep_busy = false;
                let index = self.settings.index();
                // `Err` means the live list could not be consulted, which is not
                // the same as an empty list: never treat it as "all gone".
                let live = result;
                let sweep = archx_shared::model_meta::sweep(provider, &self.settings.models[index],
                    live.as_ref().ok().map(Vec::as_slice), self.settings.meta.as_ref());
                self.settings.status = match &live {
                    Err(error) => format!("{error} Showing only what models.dev can prove."),
                    Ok(_) => sweep.summary(),
                };
                self.settings.sweep = Some(sweep);
                self.settings.sweep_undo.clear();
            }
            Message::SweepApply => {
                let Some(sweep) = self.settings.sweep.take() else { return Task::none(); };
                let ids = sweep.ids();
                if ids.is_empty() {
                    self.settings.status = "The sweep found nothing to disable; nothing was changed.".into();
                    return Task::none();
                }
                let now = storage::now_secs();
                let index = self.settings.index();
                self.model_health.sync(&self.settings.models[index]);
                for verdict in &sweep.gone {
                    self.model_health.disable(&verdict.model, verdict.reason.label(), now);
                }
                // Never leave the composer pointing at a model just disabled.
                if self.settings.selected_model().is_some_and(|model| ids.iter().any(|id| id == model)) {
                    self.settings.chosen[index] = None;
                }
                // The durable record is per model: the health slot keeps the
                // reason ("no longer offered by the provider") with a timestamp,
                // so a row explains itself after a restart. `sweep_undo` is the
                // in-session Undo and needs no disk format of its own.
                self.settings.sweep_undo = ids.clone();
                self.settings.status = format!("Disabled {} model(s); Undo puts them back and re-enables them.", ids.len());
                self.bulk_clear();
                let _ = self.persist_settings();
            }
            Message::SweepUndo => {
                let ids = std::mem::take(&mut self.settings.sweep_undo);
                for id in &ids { self.model_health.enable(id); }
                self.settings.sweep = None;
                self.settings.status = if ids.is_empty() {
                    "Nothing to undo.".to_owned()
                } else {
                    format!("Re-enabled {} model(s).", ids.len())
                };
                let _ = self.persist_settings();
            }
            Message::SweepDismiss => {
                self.settings.sweep = None;
                self.settings.sweep_undo.clear();
                self.settings.sweep_busy = false;
            }

            // ---------- provider settings sections --------------------------------
            Message::SettingsSection(section) => {
                self.settings.clear_secret();
                if section != Section::Models && self.settings.probe_busy {
                    if let Some(handle) = self.probe_handle.take() { handle.abort(); }
                    self.settings.probe_busy = false;
                    self.settings.probe_nonce = self.settings.probe_nonce.wrapping_add(1);
                }
                self.settings.probe_pending = false;
                if self.settings.catalog_modal && section != Section::Models {
                    self.settings.discard_catalog_staging();
                    self.settings.catalog_modal = false;
                }
                self.settings.section = section;
            }
            Message::MemoryPreview(memory) => self.memory_preview = memory,
            Message::ToggleAgentPreview if self.memory_preview == MemoryMode::Custom => {
                self.keep_agent_preview = !self.keep_agent_preview;
            }
            Message::LauncherScope(scope) => {
                self.memory_preview = scope.mode();
                self.settings.status = format!("Memory scope set to {}. Stages control what the Agent keeps resident.", scope_label(scope));
            }

            // ---------- custom endpoint -------------------------------------------
            Message::CustomUrl(value) if value.len() <= 2048 => {
                self.settings.custom.url = value;
                self.settings.custom_approved = false;
                self.persist_settings();
            }
            Message::CustomHeaders(value) if value.0.len() <= 8192 => {
                self.settings.custom.headers = value.0;
                self.settings.custom_approved = false;
            }
            Message::CustomBody(value) if value.len() <= 16_384 => {
                self.settings.custom.body = value;
                self.settings.custom_approved = false;
            }
            Message::CustomAnswer(value) if value.len() <= 256 => {
                self.settings.custom.answer_pointer = value;
                self.settings.custom_approved = false;
            }
            Message::CustomDelta(value) if value.len() <= 256 => {
                self.settings.custom.stream_pointer = value;
                self.settings.custom_approved = false;
            }
            Message::CustomStream => {
                self.settings.custom.stream = !self.settings.custom.stream;
                self.settings.custom_approved = false;
            }
            Message::CustomCurl(value) if value.0.len() <= 24_000 => {
                self.settings.custom_curl = value;
                self.settings.custom_approved = false;
            }
            Message::ImportCustomCurl => match custom_endpoint::parse_curl(&self.settings.custom_curl.0) {
                Ok((url, headers, body)) => {
                    self.settings.custom.url = url;
                    self.settings.custom.headers = Zeroizing::new(headers);
                    self.settings.custom.body = body;
                    self.settings.custom_curl = SecretText::default();
                    self.settings.custom_approved = false;
                    self.settings.status = "Parsed literal cURL fields. Review destination, headers and response pointer before approval.".into();
                }
                Err(error) => self.settings.status = error.into(),
            },
            Message::ApproveCustom => {
                if self.settings.custom_approved { self.settings.custom_approved = false; }
                else {
                    match self.settings.custom.check() {
                        Ok(()) => {
                            self.settings.custom_approved = true;
                            self.settings.status = "Destination approved for this session. Add an exact model ID; send when ready.".into();
                            self.persist_settings();
                        }
                        Err(error) => self.settings.status = error.into(),
                    }
                }
            }
            Message::CustomOpenAiPreset => {
                self.settings.custom.headers = Zeroizing::new("Authorization: Bearer {{api_key}}".into());
                self.settings.custom.body = r#"{"model":"{{model}}","messages":"{{messages}}","max_tokens":"{{max_tokens}}","stream":"{{stream}}"}"#.into();
                self.settings.custom.answer_pointer = "/choices/0/message/content".into();
                self.settings.custom.stream_pointer = "/choices/0/delta/content".into();
                self.settings.custom.stream = false;
                self.settings.custom_approved = false;
                self.settings.status = "OpenAI-compatible shape loaded. Enter a URL and review every field before approval.".into();
            }
            Message::CustomAnthropicPreset => {
                self.settings.custom.headers = Zeroizing::new("x-api-key: {{api_key}}|anthropic-version: 2023-06-01".into());
                self.settings.custom.body = r#"{"model":"{{model}}","messages":"{{messages}}","max_tokens":"{{max_tokens}}","stream":"{{stream}}"}"#.into();
                self.settings.custom.answer_pointer = "/content/0/text".into();
                self.settings.custom.stream_pointer = "/delta/text".into();
                self.settings.custom.stream = false;
                self.settings.custom_approved = false;
                self.settings.status = "Anthropic-compatible shape loaded. Enter a URL and review every field before approval.".into();
            }

            // ---------- debug page ------------------------------------------------
            Message::DebugFilter(filter) => self.journal_filter = filter,
            Message::DebugRefresh => {
                self.journal = debug_log::Journal::from_json(&storage::load_body(storage::Area::Debug)
                    .unwrap_or(serde_json::Value::Null));
                self.settings.status = "Debug journal reloaded from disk.".into();
            }
            Message::DebugExport if self.snapshot.is_none() => {
                let export = self.journal.export();
                let path = storage::root().join("debug-export.txt");
                self.notice = Some(match std::fs::write(&path, export) {
                    Ok(()) => format!("Journal exported to {}. It holds no prompt or reply text.", path.display()),
                    Err(_) => "Could not write the export file.".to_owned(),
                });
            }
            Message::DebugWipe => {
                self.journal.clear();
                let _ = storage::wipe(storage::Area::Debug);
                self.notice = Some("Request journal cleared.".into());
            }

            // ---------- storage ---------------------------------------------------
            Message::WipeArea(area) => {
                match area {
                    storage::Area::Settings => {
                        storage::wipe(area);
                        self.settings.models = std::array::from_fn(|_| Vec::new());
                        self.settings.chosen = [None; Provider::COUNT];
                        self.settings.custom.url.clear();
                        self.endpoints.reset_all();
                        self.keys = KeyHealthSet::new();
                        self.model_health = ModelHealthSet::new();
                        self.display = Default::default();
                        self.settings.status = "Provider, model and display settings wiped.".into();
                    }
                    storage::Area::Chats => {
                        storage::wipe(area);
                        self.store = archx_shared::transcripts::ChatStore::new();
                        self.drafts.retain(|draft| draft.busy);
                        if self.drafts.is_empty() {
                            self.drafts.push(crate::app::ChatDraft::new(self.next_chat_id));
                            self.next_chat_id += 1;
                            self.selected_draft = self.drafts[0].id;
                        }
                        self.settings.status = "Chat history wiped. Nothing was sent to a provider.".into();
                    }
                    storage::Area::ModelTests => {
                        storage::wipe(area);
                        test_journal::clear();
                        self.settings.probe_results.clear();
                        self.settings.test_evidence = None;
                        self.settings.status = "Model test results wiped.".into();
                    }
                    storage::Area::Debug => {
                        storage::wipe(area);
                        self.journal.clear();
                        self.settings.status = "Debug journal wiped.".into();
                    }
                }
                self.notice = Some(format!("Wiped: {}", area.label()));
            }
            Message::WipeEverything => {
                let labels = storage::wipe_all();
                self.settings.models = std::array::from_fn(|_| Vec::new());
                self.settings.chosen = [None; Provider::COUNT];
                self.settings.custom.url.clear();
                self.endpoints.reset_all();
                self.keys = KeyHealthSet::new();
                self.model_health = ModelHealthSet::new();
                self.display = Default::default();
                self.store = archx_shared::transcripts::ChatStore::new();
                self.journal.clear();
                self.drafts.retain(|draft| draft.busy);
                if self.drafts.is_empty() {
                    self.drafts.push(crate::app::ChatDraft::new(self.next_chat_id));
                    self.next_chat_id += 1;
                    self.selected_draft = self.drafts[0].id;
                }
                self.notice = Some(if labels.is_empty() { "Nothing was saved yet.".to_owned() }
                    else { format!("Wiped everything: {}.", labels.into_iter().collect::<Vec<_>>().join(", ")) });
            }
            Message::Notice(text) => self.notice = Some(text),
            Message::DismissNotice => self.notice = None,

            // ---------- animation --------------------------------------------------
            Message::AgentPulse if self.snapshot.is_none() => {
                self.agent_phase = (self.agent_phase + 1) % crate::agent_visual::MODE_COUNT;
            }
            Message::Tick => {}
            Message::SnapshotTick => {
                if self.snapshot.is_some() && !self.snapshot_requested {
                    if !self.snapshot_scrolled && self.page == Page::Chat
                        && std::env::var("ARCHX_SNAPSHOT_CHAT_SCROLL").as_deref() == Ok("end") {
                        self.snapshot_scrolled = true;
                        return Task::batch([
                            iced::widget::operation::snap_to_end("chat-log"),
                            Task::perform(async { tokio::time::sleep(Duration::from_millis(500)).await; },
                                |_| Message::SnapshotTick),
                        ]);
                    }
                    self.snapshot_requested = true;
                    return iced::window::latest().and_then(iced::window::screenshot).map(Message::SnapshotReady);
                }
            }
            Message::SnapshotReady(screenshot) => {
                if let Some(path) = &self.snapshot {
                    if let Some(directory) = path.parent() { let _ = std::fs::create_dir_all(directory); }
                    let _ = image::save_buffer(path, &screenshot.rgba, screenshot.size.width, screenshot.size.height,
                        image::ColorType::Rgba8);
                    return iced::window::latest().and_then(iced::window::close);
                }
            }
            _ => {}
        }
        Task::none()
    }

    // ---------------------------------------------------------------- helpers

    /// Writes one endpoint override and reports the outcome in Settings.
    fn save_endpoint_value(&mut self, kind: endpoints::Kind, value: String) -> Task<Message> {
        match self.endpoints.set(self.settings.provider, kind, &value) {
            Ok(()) => {
                self.endpoint_draft = None;
                self.settings.status = format!("{} saved. The next request uses it.", kind.label());
                self.persist_settings();
            }
            Err(error) => self.settings.status = error.into(),
        }
        Task::none()
    }

    pub(super) fn bulk_clear(&mut self) {
        self.settings.bulk_selected.clear();
    }

    pub(super) fn bulk_note(&mut self, id: &str) {
        self.settings.bulk_selected.remove(id);
    }

    /// Selected model ids in list order (stable, so bulk actions are predictable).
    pub(super) fn selected_in_order(&self) -> Vec<String> {
        self.settings.models[self.settings.index()].iter()
            .filter(|model| self.settings.bulk_selected.contains(*model))
            .cloned().collect()
    }

    pub(super) fn store_probe_result(&mut self) {
        self.persist_tests();
    }

    fn probe_failure_seen(&mut self, id: &str, output: &str) {
        let status = output.split(' ').next().and_then(|word| word.strip_prefix("HTTP")).and_then(|code| code.parse::<u16>().ok());
        let diagnosis = match status {
            Some(code) => diagnostics::from_http(code, Some(output)),
            None => diagnostics::from_http(500, Some(output)),
        };
        if let Some(note) = self.model_health.record_failure(id, &diagnosis, storage::now_secs()) {
            self.settings.status = note;
        }
    }

    /// Starts the explicit probe run for the given model ids.
    pub(super) fn start_probe(&mut self, ids: Vec<String>) -> Task<Message> {
        let provider = self.settings.provider;
        if ids.is_empty() { return Task::none(); }
        if provider == Provider::Custom {
            self.settings.status = "Custom IDs use the single-model test after endpoint approval.".into();
            return Task::none();
        }
        test_journal::begin(storage::now_secs(), provider.name(), &ids);
        self.settings.saved_run = None;
        self.settings.probe_busy = true;
        self.settings.probe_nonce = self.settings.probe_nonce.wrapping_add(1);
        let nonce = self.settings.probe_nonce;
        self.bulk_clear();
        let word = if self.settings.expected_word.is_empty() { "OK".to_owned() } else { self.settings.expected_word.clone() };
        let registry = self.endpoints.clone();
        let total = ids.len();
        self.settings.status = format!("Testing {total} model(s). Each may send one request; results are saved as they arrive.");
        let task = Task::sip(sipper(async move |mut sender| {
            for (offset, id) in ids.into_iter().enumerate() {
                let result = match choose_key(provider, offset).await {
                    Ok((_, key)) => probe_catalog_model(provider, id.clone(), key, &word, &registry).await,
                    Err(error) => Err(error),
                };
                sender.send((id, result)).await;
            }
            Ok::<(), String>(())
        }), move |(id, result)| Message::CatalogProbeProgress(provider, nonce, id, result),
            move |result| Message::CatalogProbeDone(provider, nonce, result));
        let (task, handle) = task.abortable();
        self.probe_handle = Some(handle);
        task
    }

    // ------------------------------------------------------------ persistence

    /// Builds the persisted settings document from current state.
    pub(super) fn settings_document(&self) -> PersistedSettings {
        PersistedSettings {
            provider: self.settings.provider,
            models: self.settings.models.clone(),
            chosen: self.settings.chosen,
            custom_url: self.settings.custom.url.clone(),
            endpoints: self.endpoints.clone(),
            keys: self.keys.clone(),
            model_health: self.model_health.clone(),
            display: self.display,
            // The app owns its own matrix; the launcher's is written only by
            // `save_launcher`, which reads the on-disk document first and then
            // overwrites this field. Filling it here with the app's matrix would
            // be a lie the next full save would persist, so it comes from disk.
            budget: self.memory_budget.clone(),
            launcher_budget: archx_shared::persist::PersistedSettings::load()
                .map(|settings| settings.launcher_budget).unwrap_or_default(),
            stream_chat: self.settings.stream_chat,
            dialog_timeout_secs: diagnostics::REQUEST_TIMEOUT_SECS as u16,
            import_page_size: 60,
            last_page: "agent".to_owned(),
        }
    }

    pub(super) fn persist_settings(&mut self) -> Result<(), storage::SaveError> {
        let document = self.settings_document();
        match document.save() {
            Ok(()) => Ok(()),
            Err(error) => {
                self.settings.status = error.message();
                self.notice = Some(error.message());
                Err(error)
            }
        }
    }

    pub(super) fn persist_chat(&mut self, id: u32) {
        let model = self.settings.selected_model().map(str::to_owned);
        let Some(draft) = self.drafts.iter().find(|draft| draft.id == id) else { return; };
        if draft.is_empty() { return; }
        let stored = draft.to_stored(model);
        self.store.upsert(stored);
        self.persist_chats_store();
    }

    pub(super) fn persist_chats(&mut self) {
        let model = self.settings.selected_model().map(str::to_owned);
        let chats: Vec<StoredChat> = self.drafts.iter()
            .filter(|draft| !draft.is_empty())
            .map(|draft| draft.to_stored(model.clone()))
            .collect();
        for chat in chats { self.store.upsert(chat); }
        self.persist_chats_store();
    }

    pub(super) fn persist_chats_store(&mut self) {
        if let Err(error) = self.store.save() {
            self.notice = Some(error.message());
        }
    }

    pub(super) fn persist_tests(&mut self) {
        // `storage::save` adds the envelope; writing one here would nest it.
        let document = serde_json::json!({
            "provider": self.settings.provider.name(),
            "expected_word": self.settings.expected_word,
            "results": self.settings.probe_results.iter().map(|(id, ok, output)| serde_json::json!({
                "id": id, "ok": ok, "output": output, "at": storage::now_secs(),
            })).collect::<Vec<_>>(),
            "evidence": self.settings.test_evidence,
            // The debugging record: run id, per-row provenance and our timeout.
            "run": test_journal::current().map(|run| test_journal::embed(&run)),
        });
        if let Err(error) = storage::save(storage::Area::ModelTests, document) {
            self.notice = Some(error.message());
        }
    }

    /// Reloads probe results saved by a previous run.
    pub(super) fn load_probe_results(&mut self) {
        let Some(body) = storage::load_body(storage::Area::ModelTests) else { return; };
        // The debugging record is provider-independent: a run against another
        // provider is still history worth reading, so it loads before the guard.
        self.settings.saved_run = test_journal::from_document(&body);
        if body.get("provider").and_then(serde_json::Value::as_str) != Some(self.settings.provider.name()) { return; }
        if let Some(word) = body.get("expected_word").and_then(serde_json::Value::as_str) {
            if !word.is_empty() { self.settings.expected_word = word.chars().take(32).collect(); }
        }
        if let Some(results) = body.get("results").and_then(serde_json::Value::as_array) {
            self.settings.probe_results = results.iter().take(4096).filter_map(|entry| {
                Some((
                    entry.get("id").and_then(serde_json::Value::as_str)?.to_owned(),
                    entry.get("ok").and_then(serde_json::Value::as_bool)?,
                    entry.get("output").and_then(serde_json::Value::as_str).unwrap_or("").chars().take(300).collect(),
                ))
            }).collect();
        }
        if let Some(evidence) = body.get("evidence").and_then(serde_json::Value::as_str) {
            self.settings.test_evidence = Some(evidence.chars().take(400).collect());
        }
    }

    pub(super) fn persist_now(&mut self) {
        let _ = self.persist_settings();
        self.persist_chats();
        self.save_journal();
    }

    pub(super) fn save_journal(&mut self) {
        if let Err(error) = storage::save(storage::Area::Debug, self.journal.to_json()) {
            if self.journal.len() > 0 { self.notice = Some(error.message()); }
        }
    }
}

pub(super) fn scope_label(scope: MemoryScope) -> &'static str {
    match scope {
        MemoryScope::Light => "Light",
        MemoryScope::Balanced => "Balanced",
        MemoryScope::Heavy => "Heavy",
        MemoryScope::Custom => "Custom",
    }
}

/// Picks the next vault key via the rotation state. Returns (id, key text).
pub(super) async fn choose_key(provider: Provider, offset: usize) -> Result<(u64, Zeroizing<String>), String> {
    if !provider.needs_key() { return Ok((0, Zeroizing::new(String::new()))); }
    let stored = tokio::task::spawn_blocking(move || {
        let vault = Vault::os();
        let ids = vault.list(provider)?;
        // Round-robin inside the vault list; the health cursor is applied by the
        // caller through `offset` so a probe run spreads across keys.
        let id = ids.get(offset % ids.len().max(1)).copied().ok_or(VaultError::MissingKey)?;
        vault.with_key(provider, id, |secret| (id, Zeroizing::new(secret.to_owned())))
    }).await.map_err(|_| VaultError::Unavailable.message().to_owned())
        .and_then(|result| result.map_err(|error| error.message().to_owned()))?;
    Ok(stored)
}

/// One probe attempt with at most one retry for a *retryable* transport status.
async fn probe_catalog_model(provider: Provider, model: String, key: Zeroizing<String>, word: &str,
    registry: &endpoints::Registry) -> Result<(SecretText, u128), String> {
    let start = std::time::Instant::now();
    let turns = vec![Turn { role: "user", content: format!("Reply with the word {word}.") }];
    match provider_api::send_via(provider, model.clone(), key.clone(), turns.clone(), 256, registry).await {
        Ok((reply, _trace)) => Ok((SecretText::new(reply.content), start.elapsed().as_millis())),
        Err(failure) if failure.diagnosis.http_status.is_some_and(|status| matches!(status, 408 | 429 | 500..=599)) => {
            tokio::time::sleep(Duration::from_millis(250)).await;
            match provider_api::send_via(provider, model, key, turns, 256, registry).await {
                Ok((reply, _)) => Ok((SecretText::new(reply.content), start.elapsed().as_millis())),
                Err(failure) => Err(describe_failure(&failure)),
            }
        }
        Err(failure) => Err(describe_failure(&failure)),
    }
}

fn describe_failure(failure: &Failure) -> String {
    match failure.diagnosis.http_status {
        Some(code) => format!("HTTP {code} · {}", failure.diagnosis.summary),
        None => failure.diagnosis.summary.clone(),
    }
}

