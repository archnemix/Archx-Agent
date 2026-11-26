//! Purpose: Verifies the Agent's user-visible rules: empty-chat handling, key rotation, model health, persistence and wiping.

use super::*;
use archx_shared::health::KeyHealthSet;

/// A per-test storage directory.
///
/// It is **thread-local** (see `archx_shared::storage::set_thread_directory`),
/// so parallel tests cannot delete each other's files. The old version pointed
/// the process-wide `ARCHX_CONFIG_DIR` at a shared path and serialised tests
/// with a mutex; a single test that forgot the guard then wrote into, or wiped,
/// whatever directory a neighbour had just set. That is why the empty-chat and
/// text-size tests failed one at a time and never together.
struct ConfigDir {
    path: std::path::PathBuf,
    previous: Option<std::path::PathBuf>,
}

impl ConfigDir {
    fn new(tag: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
        let unique = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let path = std::env::temp_dir()
            .join(format!("archx-{tag}-{}-{unique}", std::process::id()));
        let _ = std::fs::remove_dir_all(&path);
        let previous = archx_shared::storage::set_thread_directory(Some(path.clone()));
        Self { path, previous }
    }
}

impl Drop for ConfigDir {
    fn drop(&mut self) {
        archx_shared::storage::set_thread_directory(self.previous.take());
        let _ = std::fs::remove_dir_all(&self.path);
    }
}

fn app() -> App {
    App::new(None)
}

/// A configured, offline app: one provider, two models, no network.
///
/// Any test that saves or wipes storage starts with `ConfigDir::new(..)`, which
/// gives the test its own thread-local directory. A test that forgets is now
/// isolated rather than dangerous, because it can only reach its own thread.
fn configured() -> App {
    let mut app = app();
    app.settings.provider = Provider::OpenRouter;
    app.settings.models[Provider::OpenRouter.index()] = vec!["vendor/one".into(), "vendor/two".into()];
    app.settings.chosen[Provider::OpenRouter.index()] = Some(0);
    app.model_health.sync(&app.settings.models[Provider::OpenRouter.index()]);
    app
}

#[test]
fn new_chat_does_not_pile_up_empty_drafts() {
    let mut app = app();
    assert_eq!(app.drafts.len(), 1);
    // Clicking New chat on an empty draft must not create a second one.
    for _ in 0..5 {
        let _ = app.update(Message::NewChat);
        assert_eq!(app.drafts.len(), 1, "an empty chat must not spawn another");
    }
    // Give the first chat content; only then does a new one appear.
    app.drafts[0].turns.push(Turn { role: "user", content: "hello".into() });
    let _ = app.update(Message::NewChat);
    assert_eq!(app.drafts.len(), 2);
    assert_eq!(app.selected_draft, app.drafts[1].id);
    // And empty chats are never listed as history.
    assert_eq!(app.saved_drafts().count(), 1);
}

#[test]
fn an_empty_chat_is_never_written_to_disk() {
    let _dir = ConfigDir::new("empty");
    let mut app = configured();
    app.drafts[0].turns.push(Turn { role: "user", content: "persisted".into() });
    app.persist_chat(app.drafts[0].id);
    // A second, empty draft is added and persisted: it must be ignored.
    let _ = app.update(Message::NewChat);
    let empty_id = app.selected_draft;
    app.persist_chat(empty_id);
    let store = archx_shared::transcripts::ChatStore::load().expect("store written");
    assert_eq!(store.chats.len(), 1);
    assert!(store.get(empty_id).is_none());
}

#[test]
fn transcripts_survive_a_restart_with_reasoning() {
    let _dir = ConfigDir::new("restart");
    let mut app = configured();
    app.drafts[0].turns = vec![
        Turn { role: "user", content: "explain".into() },
        Turn { role: "assistant", content: "answer".into() },
    ];
    app.drafts[0].reasoning = vec![None, Some("because".into())];
    app.drafts[0].model = Some("vendor/one".into());
    let saved = app.settings_document();
    saved.save().expect("settings");
    app.persist_chat(app.drafts[0].id);

    let restored = App::new(archx_shared::persist::PersistedSettings::load());
    assert_eq!(restored.drafts.len(), 1);
    assert_eq!(restored.drafts[0].turns.len(), 2);
    assert_eq!(restored.drafts[0].turns[1].content, "answer");
    assert_eq!(restored.drafts[0].reasoning[1].as_deref(), Some("because"));
    assert_eq!(restored.drafts[0].model.as_deref(), Some("vendor/one"));
    assert_eq!(restored.settings.chosen[Provider::OpenRouter.index()], Some(0));
}

#[test]
fn wiping_chats_keeps_provider_settings_and_vault_keys() {
    let _dir = ConfigDir::new("wipe-chats");
    let mut app = configured();
    app.settings.key_ids = vec![1, 2];
    app.drafts[0].turns.push(Turn { role: "user", content: "keep me out of the wipe".into() });
    let _ = app.update(Message::WipeArea(storage::Area::Chats));
    assert_eq!(app.drafts.len(), 1);
    assert!(app.drafts[0].turns.is_empty(), "the transcript text is gone");
    assert_eq!(app.settings.key_ids, vec![1, 2], "vault keys are untouched");
    assert_eq!(app.settings.models[Provider::OpenRouter.index()].len(), 2);
    assert!(app.notice.is_some());
}

#[test]
fn wiping_settings_clears_configuration_but_not_chats() {
    let _dir = ConfigDir::new("wipe-settings");
    let mut app = configured();
    app.drafts[0].turns.push(Turn { role: "user", content: "chat survives".into() });
    let _ = app.update(Message::WipeArea(storage::Area::Settings));
    assert!(app.settings.models[Provider::OpenRouter.index()].is_empty());
    assert_eq!(app.settings.chosen, [None; Provider::COUNT]);
    assert_eq!(app.drafts[0].turns.len(), 1);
}

#[test]
fn a_resting_key_is_skipped_and_another_key_is_tried_once() {
    let mut app = configured();
    app.settings.key_ids = vec![1, 2];
    app.keys.sync(&app.settings.key_ids);
    app.keys.auto_rotate = true;
    // Key 1 is resting after a quota failure.
    let now = storage::now_secs();
    app.keys.record_failure(1, &archx_shared::diagnostics::from_http(429, Some("quota exceeded")), now);
    let plan = app.key_plan(now);
    assert_eq!(plan.first(), Some(&2), "the healthy key is chosen first");
    assert_eq!(plan.len(), 1, "only one healthy key remains");
    // With both healthy, the plan has a primary and exactly one fallback.
    let mut fresh = KeyHealthSet::new();
    fresh.sync(&[1, 2, 3]);
    app.keys = fresh;
    let plan = app.key_plan(now);
    assert_eq!(plan.len(), 2, "one primary plus one fallback");
    assert_ne!(plan[0], plan[1]);
    // Consecutive turns must actually move through the keys: an advanced cursor
    // is the difference between rotation and using the first key forever.
    let mut used = Vec::new();
    for _ in 0..3 { used.push(app.key_plan(now)[0]); }
    let mut distinct = used.clone();
    distinct.sort_unstable();
    distinct.dedup();
    assert_eq!(distinct.len(), 3, "three turns used three different keys: {used:?}");
}

#[test]
fn rotation_can_be_switched_off() {
    let mut app = configured();
    app.settings.key_ids = vec![1, 2];
    app.keys.sync(&app.settings.key_ids);
    app.keys.auto_rotate = false;
    assert_eq!(app.key_plan(storage::now_secs()).len(), 1);
    let _ = app.update(Message::ToggleAutoRotate);
    assert!(app.keys.auto_rotate);
}

#[test]
fn a_retired_model_is_disabled_and_cannot_stay_selected() {
    let mut app = configured();
    app.settings.chosen[Provider::OpenRouter.index()] = Some(0);
    let diagnosis = archx_shared::diagnostics::from_http(404, Some("this model has been decommissioned"));
    let note = app.model_health.record_failure("vendor/one", &diagnosis, storage::now_secs());
    assert!(note.is_some());
    assert!(!app.model_health.is_enabled("vendor/one"));
    // The model menu cannot select a disabled id.
    let before = app.settings.chosen[Provider::OpenRouter.index()];
    let _ = app.update(Message::ChooseModel(0));
    assert_eq!(app.settings.chosen[Provider::OpenRouter.index()], before);
    // Re-enabling brings it back.
    let _ = app.update(Message::ToggleModelEnabled("vendor/one".into()));
    assert!(app.model_health.is_enabled("vendor/one"));
}

#[test]
fn bulk_actions_only_touch_ticked_models_in_list_order() {
    let mut app = configured();
    app.settings.models[Provider::OpenRouter.index()].push("vendor/three".into());
    app.model_health.sync(&app.settings.models[Provider::OpenRouter.index()]);
    let _ = app.update(Message::BulkSelect(0, true));
    let _ = app.update(Message::BulkSelect(2, true));
    assert_eq!(app.selected_in_order(), vec!["vendor/one".to_owned(), "vendor/three".to_owned()]);
    let _ = app.update(Message::BulkDisableSelected);
    assert!(!app.model_health.is_enabled("vendor/one"));
    assert!(app.model_health.is_enabled("vendor/two"), "untouched model stays enabled");
    assert!(app.settings.bulk_selected.is_empty(), "selection clears after the action");
    // Removing the ticked models leaves the middle one.
    let _ = app.update(Message::BulkSelectMatching);
    let _ = app.update(Message::BulkSelect(1, false));
    let _ = app.update(Message::BulkRemoveSelected);
    assert_eq!(app.settings.models[Provider::OpenRouter.index()], vec!["vendor/two".to_owned()]);
}

#[test]
fn model_pages_are_bounded_and_never_render_the_whole_list() {
    let mut app = configured();
    let models: Vec<String> = (0..120).map(|n| format!("vendor/model-{n}")).collect();
    app.settings.models[Provider::OpenRouter.index()] = models;
    app.model_health.sync(&app.settings.models[Provider::OpenRouter.index()]);
    assert_eq!(app.settings.model_page_size, 25);
    let _ = app.update(Message::ModelPageNext);
    assert_eq!(app.settings.model_page, 1);
    let _ = app.update(Message::ModelPagePrevious);
    assert_eq!(app.settings.model_page, 0);
    // A filter reset returns to the first page.
    app.settings.model_page = 3;
    let _ = app.update(Message::SearchModels("model-1".into()));
    assert_eq!(app.settings.model_page, 0);
}

#[test]
fn endpoints_are_editable_validated_and_resettable() {
    let mut app = configured();
    let _ = app.update(Message::EditEndpoint(archx_shared::endpoints::Kind::Chat, "https://gateway.example/v1/{model}".into()));
    let _ = app.update(Message::SaveEndpoint(archx_shared::endpoints::Kind::Chat));
    assert_eq!(app.endpoints.value(Provider::OpenRouter, archx_shared::endpoints::Kind::Chat), "https://gateway.example/v1/{model}");
    // A plain-HTTP remote URL is refused and the previous value stays.
    let _ = app.update(Message::EditEndpoint(archx_shared::endpoints::Kind::Chat, "http://evil.example/v1".into()));
    let _ = app.update(Message::SaveEndpoint(archx_shared::endpoints::Kind::Chat));
    assert_eq!(app.endpoints.value(Provider::OpenRouter, archx_shared::endpoints::Kind::Chat), "https://gateway.example/v1/{model}");
    let _ = app.update(Message::ResetEndpoint(archx_shared::endpoints::Kind::Chat));
    assert_eq!(app.endpoints.value(Provider::OpenRouter, archx_shared::endpoints::Kind::Chat),
        archx_shared::endpoints::default_value(Provider::OpenRouter, archx_shared::endpoints::Kind::Chat));
}

#[test]
fn the_provider_picker_opens_and_closes() {
    let mut app = app();
    assert!(!app.settings.provider_picker);
    let _ = app.update(Message::OpenProviderPicker);
    assert!(app.settings.provider_picker);
    let _ = app.update(Message::SelectProvider(Provider::Groq));
    assert_eq!(app.settings.provider, Provider::Groq);
    assert!(!app.settings.provider_picker, "choosing a provider closes the list");
}

#[test]
fn probe_results_are_saved_and_reloaded_until_overwritten() {
    let _dir = ConfigDir::new("probes");
    let mut app = configured();
    app.settings.probe_results.push(("vendor/one".into(), true, "42 ms · expected word found · OK".into()));
    app.persist_tests();
    // A fresh start for the same provider reads them back.
    let mut restored = configured();
    restored.load_probe_results();
    assert_eq!(restored.settings.probe_results.len(), 1);
    assert_eq!(restored.settings.probe_results[0].0, "vendor/one");
    // Re-running replaces rather than appending.
    restored.settings.probe_results = vec![("vendor/two".into(), false, "HTTP 404".into())];
    restored.persist_tests();
    let mut again = configured();
    again.load_probe_results();
    assert_eq!(again.settings.probe_results.len(), 1);
    assert_eq!(again.settings.probe_results[0].0, "vendor/two");
}

#[test]
fn the_journal_records_attempts_and_never_prompt_text() {
    let mut app = configured();
    let id = app.journal.begin("OpenRouter", "vendor/one".into(), 1, true, 900);
    app.journal.finish_ok(id, 1_200, 400, 30, 2_000);
    let entry = &app.journal.entries()[0];
    assert_eq!(entry.id, id);
    assert!(entry.is_success());
    let export = app.journal.export();
    assert!(export.contains("no prompt or reply text"));
    assert!(!export.contains("vendor/one is a prompt"));
}

#[test]
fn runtime_matrix_releases_what_it_says_it_releases() {
    let mut app = configured();
    app.store.store_catalog(Provider::OpenRouter, vec![CatalogModel {
        id: "vendor/one".into(), name: "One".into(), free: true, router: false, reasoning: false,
    }]);
    app.refresh_usage();
    let before = app.memory_usage.iter().find(|usage| usage.item == archx_shared::memory::Item::ModelCatalog)
        .map(|usage| usage.entries).unwrap_or(0);
    assert!(before > 0, "a fetched catalog is measured");
    app.release(archx_shared::memory::Item::ModelCatalog);
    let after = app.memory_usage.iter().find(|usage| usage.item == archx_shared::memory::Item::ModelCatalog)
        .map(|usage| usage.entries).unwrap_or(0);
    assert_eq!(after, 0, "releasing actually empties the measured cache");
    // The configured model list is not a cache and must survive.
    assert_eq!(app.settings.models[Provider::OpenRouter.index()].len(), 2);
}

#[test]
fn display_scale_is_per_area_and_saved() {
    let _dir = ConfigDir::new("scale");
    let mut app = configured();
    let _ = app.update(Message::ScaleIn(Area::Chat));
    let _ = app.update(Message::ScaleIn(Area::Chat));
    assert_eq!(app.display.chat.percent(), 110);
    assert_eq!(app.display.settings.percent(), 100, "only chat changed");
    app.settings_document().save().expect("save");
    let restored = App::new(archx_shared::persist::PersistedSettings::load());
    assert_eq!(restored.display.chat.percent(), 110);
    assert_eq!(restored.display.settings.percent(), 100);
}

#[test]
fn other_modes_cannot_send_and_send_without_a_model_says_so() {
    let mut app = configured();
    let _ = app.update(Message::SelectMode(3));
    app.drafts[0].text = "private unsent".into();
    let _ = app.update(Message::SendChat);
    assert!(app.drafts[0].turns.is_empty(), "preview modes never send");
    let _ = app.update(Message::SelectMode(0));
    app.settings.chosen[Provider::OpenRouter.index()] = None;
    let _ = app.update(Message::SendChat);
    assert!(app.drafts[0].turns.is_empty());
    assert!(app.drafts[0].error.is_some(), "the user is told why nothing was sent");
}

#[test]
fn deleting_a_chat_leaves_a_usable_blank_one() {
    let mut app = configured();
    app.drafts[0].turns.push(Turn { role: "user", content: "old".into() });
    let id = app.drafts[0].id;
    let _ = app.update(Message::DeleteChat(id));
    assert_eq!(app.drafts.len(), 1);
    assert!(app.drafts[0].turns.is_empty());
    assert_ne!(app.drafts[0].id, id, "a fresh id, so a stale save cannot resurrect it");
}
