//! Purpose: Owns launcher navigation, app discovery, the launcher↔app transition and launcher-only settings.
//!
//! The launcher knows nothing about any individual app's features. It reads
//! `apps/*/app.toml` at start-up (`archx_shared::apps`), renders a tile per
//! manifest, and hands the Agent its own state when the Agent surface is open.
//! Launcher-only preferences (display scale, memory scope, data location) live
//! here; app preferences live inside the app that owns them.

use std::collections::BTreeSet;
use std::path::PathBuf;
use std::time::Duration;

use iced::time;
use iced::window;
use iced::{Element, Subscription, Task};

use archx_agent::app::{App as AgentApp, MemoryMode, Message as AgentMessage};
use archx_shared::apps;
use archx_shared::storage::Area as StorageArea;
use archx_shared::persist::DisplaySettings;
use archx_shared::{storage, style};
use crate::navigation;
use crate::transition::Transition;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Page {
    Home,
    About,
    /// An app hosted in this process: its id plus which of its surfaces is open.
    ///
    /// This used to be one variant per Agent surface (`Agent`, `AgentSettings`,
    /// `AgentDebug`), which meant a second app could not exist without editing
    /// the launcher's own enum, its rail, its transition rules and its view. An
    /// app page is data now: the app id comes from its manifest, and the surface
    /// id is whatever that app calls it. Adding an app is one row in
    /// [`HOSTED`], never a new variant.
    App { id: &'static str, surface: &'static str },
    /// Launcher-owned settings (display scale, memory scope, storage, apps).
    LabSettings,
}

/// The apps this binary hosts, and the surfaces each one offers.
///
/// This is the build-time half of "may this app appear": a manifest can say
/// `ready = true` and still be held out of the release, because hosting means
/// linking the crate. `surface` names are the app's own; the launcher only
/// passes them through to `enter_surface`.
#[derive(Debug, Clone, Copy)]
pub struct Hosted {
    pub id: &'static str,
    pub surfaces: &'static [&'static str],
}

pub const HOSTED: &[Hosted] = &[
    Hosted { id: "archx-agent", surfaces: &["agent", "settings", "debug"] },
];

impl Hosted {
    pub fn find(id: &str) -> Option<&'static Hosted> {
        HOSTED.iter().find(|hosted| hosted.id == id)
    }
    /// Falls back to the first surface, which every app must have.
    pub fn surface(self, wanted: &str) -> &'static str {
        self.surfaces.iter().copied().find(|surface| *surface == wanted)
            .unwrap_or_else(|| self.surfaces.first().copied().unwrap_or("agent"))
    }
}

impl Page {
    /// The page a stored `last_page` id refers to.
    pub fn from_id(id: &str) -> Self {
        match id {
            "lab-settings" => Self::LabSettings,
            "about" => Self::About,
            "home" | "" => Self::Home,
            // The Agent keeps its old bare ids readable, so a `last_page` saved
            // before app pages became data still restores where it was.
            "agent" | "settings" | "debug" => {
                let surface = match id { "settings" => "settings", "debug" => "debug", _ => "agent" };
                Self::App { id: "archx-agent", surface }
            }
            // `"<app>/<surface>"` for any hosted app.
            other => match other.split_once('/') {
                Some((app, surface)) => match Hosted::find(app) {
                    Some(hosted) => Self::App { id: hosted.id, surface: hosted.surface(surface) },
                    None => Self::Home,
                },
                None => Self::Home,
            },
        }
    }

    /// The Agent keeps its historical bare ids ("agent"/"settings"/"debug")
    /// because a stored `last_page` and the screenshot environment both use
    /// them; every other app is `"<id>/<surface>"`.
    pub fn id(self) -> String {
        match self {
            Self::Home => "home".to_owned(),
            Self::About => "about".to_owned(),
            Self::LabSettings => "lab-settings".to_owned(),
            Self::App { id: "archx-agent", surface } => match surface {
                "settings" => "settings".to_owned(),
                "debug" => "debug".to_owned(),
                _ => "agent".to_owned(),
            },
            Self::App { id, surface } => format!("{id}/{surface}"),
        }
    }

    /// The app page for a hosted app's first surface.
    pub fn app(id: &'static str) -> Self {
        let surface = Hosted::find(id)
            .and_then(|hosted| hosted.surfaces.first().copied())
            .unwrap_or("agent");
        Self::App { id, surface }
    }

    /// Which hosted app this page belongs to, if any.
    pub fn hosted_app(self) -> Option<(&'static str, &'static str)> {
        match self {
            Self::App { id, surface } => Some((id, surface)),
            _ => None,
        }
    }

    /// Any app's surface, not only the Agent's. The launcher's rail, shell and
    /// transition all key on this, which is what lets a second app behave
    /// exactly like the first without a new variant anywhere.
    pub fn is_app_surface(self) -> bool {
        self.hosted_app().is_some()
    }

    pub fn is_agent_surface(self) -> bool {
        matches!(self.hosted_app(), Some(("archx-agent", _)))
    }
}

#[derive(Debug, Clone)]
pub enum Message {
    Agent(AgentMessage),
    Navigate(Page),
    ToggleSidebar,
    Tick,
    Animate,
    LaunchApp(String),
    /// A transition finished (or arrived late); used by tests and the ticker.
    TransitionTick(u64),
    /// Launcher display scale, per area.
    ScaleIn(Area),
    ScaleOut(Area),
    ScaleReset(Area),
    /// Launcher memory scope for its own resident data.
    LauncherScope(Scope),
    /// Launcher memory scope for the Agent app, handed to it as a message.
    AgentScope(Scope),
    /// Flip one cell of the launcher's own stage matrix.
    LauncherBudget(archx_shared::memory::Stage, archx_shared::memory::Item),
    Wipe(Area),
    WipeAll,
    StorageReport(String),
    RefreshApps,
    DismissNotice,
    /// The Agent asked to return to the launcher rail.
    BackToLauncher,
    /// Screenshot support.
    SnapshotTick,
    SnapshotReady(window::screenshot::Screenshot),
    SnapshotSetPage(String),
    SnapshotSetApp(String),
}

/// Which area of the interface a scale control affects.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Area {
    Chat,
    Settings,
    Launcher,
}

/// How much of an app's data may stay resident. Handed to the app as a message.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Scope {
    Light,
    Balanced,
    Heavy,
    Custom,
}

impl Scope {
    pub const ALL: [Self; 4] = [Self::Light, Self::Balanced, Self::Heavy, Self::Custom];

    pub fn label(self) -> &'static str {
        match self {
            Self::Light => "Light",
            Self::Balanced => "Balanced",
            Self::Heavy => "Heavy",
            Self::Custom => "Custom",
        }
    }

    /// The Agent's own memory-mode equivalent.
    pub fn memory_mode(self) -> MemoryMode {
        match self {
            Self::Light => MemoryMode::Light,
            Self::Heavy | Self::Balanced => MemoryMode::Heavy,
            Self::Custom => MemoryMode::Custom,
        }
    }
}

/// The id the Agent understands for a launcher surface.
pub fn surface_id(page: Page) -> &'static str {
    match page.hosted_app() {
        Some((_, surface)) => surface,
        None => "agent",
    }
}

pub struct App {
    pub page: Page,
    pub sidebar_expanded: bool,
    pub apps: Vec<apps::App>,
    /// Ready apps this build does not publish. Reported, never shown as tiles.
    pub held_apps: Vec<apps::App>,
    pub transition: Option<Transition>,
    pub display: DisplaySettings,
    pub agent: AgentApp,
    pub agent_scope: Scope,
    pub launcher_scope: Scope,
    /// The launcher's OWN per-stage keep/drop matrix. Separate from the Agent's
    /// (which lives in the app): this page configures launcher state only, and
    /// the app's Runtime page configures the app's. Neither writes the other.
    pub launcher_budget: archx_shared::memory::Budget,
    pub notice: Option<String>,
    pub storage_path: String,
    pub memory_usage: Vec<archx_shared::memory::Usage>,
    /// Tile artwork cycle for Discover.
    pub(crate) phase: u8,
    /// Agent word-mark cycle (the Agent's own mode count).
    pub(crate) agent_phase: u8,
    /// Which tile art is lit for a scripted screenshot (`training`/`tuning`).
    pub(crate) hovered: Option<String>,
    snapshot: Option<PathBuf>,
    snapshot_requested: bool,
    snapshot_page: Option<String>,
    snapshot_app: Option<String>,
    ticker: bool,
}

impl App {
    pub fn new() -> Self {
        let snapshot = std::env::var_os("ARCHX_SNAPSHOT").map(PathBuf::from);
        // Only released apps are registered: ready, and compiled in by
        // `crate::release()`. A folder still being built stays dark.
        let mut all = crate::release().discover();
        // Harness only: mark one held app as present so it can be rendered and
        // judged. No effect unless ARCHX_SNAPSHOT_APPS names it.
        crate::projection(&mut all);
        let discovered: Vec<apps::App> = all.iter().filter(|app| app.is_registered()).cloned().collect();
        let held = all.iter()
            .filter(|app| app.ready && app.release() == apps::Release::Held).cloned()
            .collect();
        let persisted = archx_shared::persist::PersistedSettings::load();
        let display = persisted.as_ref().map(|settings| settings.display).unwrap_or_default();
        let page = if snapshot.is_some() {
            match std::env::var("ARCHX_SNAPSHOT_PAGE").as_deref() {
                Ok("agent") => Page::app("archx-agent"),
                Ok("settings") => Page::App { id: "archx-agent", surface: "settings" },
                Ok("debug") => Page::App { id: "archx-agent", surface: "debug" },
                Ok("about") => Page::About,
                Ok("lab-settings") => Page::LabSettings,
                _ => Page::Home,
            }
        } else { Page::Home };
        // Read before `agent` takes ownership of the document: the launcher's
        // matrix is its own and is never the app's.
        let launcher_budget = persisted.as_ref().map(|settings| settings.launcher_budget.clone())
            .unwrap_or_default();
        let mut agent = AgentApp::new(persisted);
        // A screenshot run must never need the app's own launch path.
        if snapshot.is_some() { agent.prepare_snapshot(surface_id(page)); }
        Self {
            page,
            sidebar_expanded: !(snapshot.is_some()
                && std::env::var("ARCHX_SNAPSHOT_SIDEBAR").as_deref() == Ok("collapsed")),
            apps: discovered,
            held_apps: held,
            // Screenshots are deterministic: no in-flight animation.
            transition: None,
            display,
            agent,
            agent_scope: Scope::Balanced,
            launcher_scope: Scope::Light,
            launcher_budget,
            notice: None,
            storage_path: storage::display_path(),
            memory_usage: Vec::new(),
            // Two independent fixtures, as the CI captures expect: the Discover
            // shelf cycle (`_PHASE`, 0..=2) and the Agent word-mark cycle
            // (`_AGENT_PHASE`, 0..MODE_COUNT).
            phase: std::env::var("ARCHX_SNAPSHOT_PHASE").ok()
                .and_then(|value| value.parse::<u8>().ok()).filter(|phase| *phase <= 2).unwrap_or(0),
            agent_phase: std::env::var("ARCHX_SNAPSHOT_AGENT_PHASE").ok()
                .and_then(|value| value.parse::<u8>().ok())
                .filter(|phase| *phase < archx_agent::agent_visual::MODE_COUNT).unwrap_or(0),
            hovered: std::env::var("ARCHX_SNAPSHOT_HOVER").ok(),
            snapshot,
            snapshot_requested: false,
            snapshot_page: std::env::var("ARCHX_SNAPSHOT_CHAT").ok(),
            snapshot_app: None,
            ticker: false,
        }
    }

    /// Why pressing an app that will not open did nothing, said truthfully.
    ///
    /// There are three different reasons, and they used to share one sentence
    /// that was wrong for two of them: a reserved folder has no code, a held app
    /// has code this binary does not link, and a registered app can still be
    /// unready. "Its code is not [in place]" told a held app's author their work
    /// did not exist.
    fn unopenable_reason(app: &apps::App) -> &'static str {
        if !app.has_code() {
            "its folder and docs are in place; its code is not"
        } else if Hosted::find(&app.id).is_none() {
            "its code exists, but this build does not host it"
        } else {
            "it is registered, but not ready to open yet"
        }
    }

    /// The app record for an id, if it is registered and openable.
    ///
    /// `is_live` alone was the bug: an app can be registered in this release
    /// with `status = "preview"` (openable, labelled) while `preview != live`,
    /// so its tile looked clickable and did nothing. Registration is the
    /// question that decides "may it open at all"; the status only labels it.
    pub fn launchable(&self, id: &str) -> Option<&apps::App> {
        self.apps.iter().find(|app| app.id == id && app.is_registered())
    }

    fn go(&mut self, page: Page) -> Task<Message> {
        if page == self.page { return Task::none(); }
        // Leaving the Agent is an explicit exit: it aborts in-flight work there.
        if !page.is_agent_surface() && self.page.is_agent_surface() {
            self.agent.leave_app();
        }
        if self.snapshot.is_none() {
            self.transition = Some(Transition::between(self.page, page));
        }
        self.page = page;
        if page.is_agent_surface() { self.agent.enter_surface(surface_id(page)); }
        self.ticker = self.snapshot.is_none();
        Task::none()
    }

    pub fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::Navigate(page) => return self.go(page),
            Message::LaunchApp(id) => {
                if self.launchable(&id).is_some() {
                    // Hosting is a build-time fact: an app that is ready but not
                    // compiled in stays held, and its tile is not openable.
                    if let Some(hosted) = Hosted::find(&id) {
                        return self.go(Page::App { id: hosted.id, surface: hosted.surfaces[0] });
                    }
                }
                // Why it would not open is not one fact: a reserved folder has
                // no code, a held app has code this binary does not link, and a
                // preview app is registered but not ready. The wording lives in
                // `unopenable_reason` so it can be tested rather than hoped at.
                self.notice = self.apps.iter().find(|app| app.id == id)
                    .map(|app| format!("{} is not available yet ({}): {}.",
                        app.name, app.status, unopenable_reason(app)));
            }
            Message::ToggleSidebar => self.sidebar_expanded = !self.sidebar_expanded,
            Message::BackToLauncher => return self.go(Page::Home),
            Message::RefreshApps => {
                let released = crate::release();
                let held = released.discover().into_iter()
                    .filter(|app| app.ready && app.release() == apps::Release::Held).count();
                self.apps = crate::release().registered();
                self.held_apps = crate::release().discover().into_iter()
                    .filter(|app| app.ready && app.release() == apps::Release::Held).collect();
                let count = self.apps.len();
                self.notice = Some(if held == 0 {
                    format!("Rescanned apps: {count} released app(s).")
                } else {
                    format!("Rescanned apps: {count} released; {held} finished app(s) are held out of this build.")
                });
            }
            Message::Tick | Message::Animate => {
                if let Some(transition) = self.transition {
                    let advanced = transition.advance(crate::transition::FRAME_MS);
                    self.transition = (!advanced.is_complete()).then_some(advanced);
                }
                if self.page == Page::Home {
                    self.phase = self.phase.wrapping_add(1);
                    return Task::none();
                }
            }
            Message::TransitionTick(elapsed) => {
                if let Some(transition) = self.transition {
                    let advanced = transition.advance(elapsed);
                    self.transition = (!advanced.is_complete()).then_some(advanced);
                }
            }
            Message::ScaleIn(area) => self.scale(area, true),
            Message::ScaleOut(area) => self.scale(area, false),
            Message::ScaleReset(area) => {
                self.display = match area {
                    Area::Chat => DisplaySettings { chat: Default::default(), ..self.display },
                    Area::Settings => DisplaySettings { settings: Default::default(), ..self.display },
                    Area::Launcher => DisplaySettings { launcher: Default::default(), ..self.display },
                };
                self.save();
            }
            Message::LauncherScope(scope) => {
                self.launcher_scope = scope;
                // The launcher's own resident data is tiny; recording the choice
                // is what makes the stage matrix honest about intent.
                self.notice = Some(format!("Launcher memory scope: {}. Launcher data is a few KB; this never caps another process."
                    , scope.label()));
            }
            Message::LauncherBudget(stage, item) => {
                self.launcher_budget.toggle(stage, item);
                let kept = self.launcher_budget.keeps(stage, item);
                self.notice = Some(format!("Launcher · {} at {}: {}. Launcher data is a few KB; this records the decision and never caps another process.",
                    item.label(), stage.label(), if kept { "kept" } else { "released" }));
                self.save();
            }
            Message::AgentScope(scope) => {
                self.agent_scope = scope;
                return Task::batch([self.update(Message::Agent(AgentMessage::MemoryPreview(scope.memory_mode())))]);
            }
            Message::Wipe(area) => {
                let removed = match area {
                    Area::Chat => storage::wipe(StorageArea::Chats),
                    Area::Settings => storage::wipe(StorageArea::Settings),
                    Area::Launcher => false,
                };
                self.notice = Some(if removed { "Wiped.".into() } else { "Nothing to wipe.".into() });
            }
            Message::WipeAll => {
                let labels: BTreeSet<&'static str> = storage::wipe_all();
                self.notice = Some(if labels.is_empty() {
                    "No saved data found.".to_owned()
                } else {
                    format!("Wiped: {}.", labels.into_iter().collect::<Vec<_>>().join(", "))
                });
            }
            Message::DismissNotice => self.notice = None,
            Message::StorageReport(path) => self.storage_path = path,
            Message::Agent(agent_message) => {
                // Agent messages map straight through; a "Back to launcher"
                // request is translated so the app never needs to know the
                // launcher's page enum.
                if matches!(agent_message, AgentMessage::Open(_)) {
                    if let AgentMessage::Open(page) = agent_message {
                        return self.go(match page {
                            archx_agent::app::Page::Settings => Page::App { id: "archx-agent", surface: "settings" },
                            archx_agent::app::Page::Debug => Page::App { id: "archx-agent", surface: "debug" },
                            _ => Page::app("archx-agent"),
                        });
                    }
                }
                let task = self.agent.update(agent_message).map(Message::Agent);
                if self.agent.left_for_launcher {
                    return Task::batch([task, self.go(Page::Home)]);
                }
                return task;
            }
            Message::SnapshotTick => {
                if !self.snapshot_requested {
                    self.snapshot_requested = true;
                    return window::latest().and_then(window::screenshot).map(Message::SnapshotReady);
                }
            }
            Message::SnapshotReady(screenshot) => {
                if let Some(path) = &self.snapshot {
                    if let Some(directory) = path.parent() {
                        let _ = std::fs::create_dir_all(directory);
                    }
                    let _ = image::save_buffer(path, &screenshot.rgba, screenshot.size.width, screenshot.size.height,
                        image::ColorType::Rgba8);
                    return window::latest().and_then(window::close);
                }
            }
            Message::SnapshotSetPage(_) | Message::SnapshotSetApp(_) => {}
        }
        Task::none()
    }

    fn scale(&mut self, area: Area, larger: bool) {
        self.display = match (area, larger) {
            (Area::Chat, true) => DisplaySettings { chat: self.display.chat.larger(), ..self.display },
            (Area::Chat, false) => DisplaySettings { chat: self.display.chat.smaller(), ..self.display },
            (Area::Settings, true) => DisplaySettings { settings: self.display.settings.larger(), ..self.display },
            (Area::Settings, false) => DisplaySettings { settings: self.display.settings.smaller(), ..self.display },
            (Area::Launcher, true) => DisplaySettings { launcher: self.display.launcher.larger(), ..self.display },
            (Area::Launcher, false) => DisplaySettings { launcher: self.display.launcher.smaller(), ..self.display },
        };
        self.save();
    }

    /// Persists the launcher's own two fields (per-area text scale and its stage
    /// matrix) through the one writer that owns `settings.json`. The Agent keeps
    /// writing its own page; both read the same file, so neither loses the other.
    fn save(&mut self) {
        if let Some(error) = self.agent.save_launcher(self.display, self.launcher_budget.clone()) {
            self.notice = Some(error);
        }
    }

    pub fn view(&self) -> Element<'_, Message> {
        navigation::view(self).map(|message| message)
    }

    pub fn subscription(&self) -> Subscription<Message> {
        let snapshot = if self.snapshot.is_some() {
            time::every(Duration::from_millis(700)).map(|_| Message::SnapshotTick)
        } else { Subscription::none() };
        let ticker = if self.ticker && self.transition.is_some_and(|transition| !transition.is_complete()) {
            time::every(Duration::from_millis(crate::transition::FRAME_MS)).map(|_| Message::Tick)
        } else { Subscription::none() };
        Subscription::batch([snapshot, ticker])
    }

}

/// The launcher's own guarantees about hosting a second app.
///
/// These are what let `apps/training` and `apps/surgery` exist without editing
/// the launcher's page enum, rail or transition rules again.
#[cfg(test)]
mod hosting_tests {
    use super::*;
    use archx_shared::apps;

    #[test]
    fn a_hosted_app_page_is_data_not_an_enum_variant() {
        // The Agent's historical ids still resolve, so a saved `last_page`
        // restores exactly where it was before app pages became data.
        assert_eq!(Page::from_id("agent"), Page::app("archx-agent"));
        assert_eq!(Page::from_id("settings"), Page::App { id: "archx-agent", surface: "settings" });
        assert_eq!(Page::from_id("debug"), Page::App { id: "archx-agent", surface: "debug" });
        assert_eq!(Page::from_id("home"), Page::Home);
        assert_eq!(Page::from_id("lab-settings"), Page::LabSettings);
    }

    #[test]
    fn an_app_that_is_not_hosted_cannot_be_reached_by_a_page_id() {
        // This is the release boundary. `training` has a folder and a manifest,
        // but until its crate is in `HOSTED` a crafted page id must fall back to
        // the launcher rather than render an app that is not in this binary.
        assert!(Hosted::find("training").is_none());
        assert_eq!(Page::from_id("training/design"), Page::Home);
        assert_eq!(Page::from_id("something/there"), Page::Home);
        assert_eq!(Page::from_id("trailing/"), Page::Home);
    }

    #[test]
    fn a_surface_that_an_app_does_not_offer_falls_back_to_its_first() {
        let agent = Hosted::find("archx-agent").expect("the Agent is hosted");
        assert_eq!(agent.surface("debug"), "debug");
        // An unknown surface must not become a blank app: it opens the app's
        // first surface, which every app is required to have.
        assert_eq!(agent.surface("nonsense"), "agent");
        assert_eq!(agent.surfaces[0], "agent");
    }

    #[test]
    fn every_hosted_app_declares_at_least_one_surface() {
        for hosted in HOSTED {
            assert!(!hosted.surfaces.is_empty(), "{} has no surface to open", hosted.id);
            // A surface name is passed to the app's `enter_surface`, so it must
            // be a bare identifier: no slashes, which would make a page id
            // ambiguous when it is split back apart.
            for surface in hosted.surfaces {
                assert!(!surface.contains('/'), "{} surface {surface} contains a slash", hosted.id);
                assert!(!surface.is_empty());
            }
        }
    }

    #[test]
    fn a_page_id_round_trips_through_the_string_form() {
        for page in [Page::Home, Page::About, Page::LabSettings, Page::app("archx-agent"),
            Page::App { id: "archx-agent", surface: "settings" },
            Page::App { id: "archx-agent", surface: "debug" }] {
            assert_eq!(Page::from_id(&page.id()), page, "{:?}", page.id());
        }
    }

    fn manifest(status: &str, ready: bool, built: bool) -> apps::App {
        apps::App {
            id: "x".to_owned(), name: "X".to_owned(), category: String::new(),
            summary: String::new(), status: status.to_owned(), ready,
            modes: Vec::new(), art: "workbench".to_owned(),
            // `has_code` requires both, so a fixture without `entry` would be
            // judged "reserved" and the test would prove nothing.
            krate: Some("archx-x".to_owned()), entry: Some("src/lib.rs".to_owned()),
            view: Some("home::view".to_owned()), docs: None,
            requires: Vec::new(), built, origin: apps::Origin::Disk,
        }
    }

    #[test]
    fn an_app_that_will_not_open_says_the_true_reason() {
        // A reserved folder: manifest only, no crate.
        let mut reserved = manifest("building", false, false);
        reserved.krate = None;
        reserved.entry = None;
        assert!(!reserved.has_code());
        assert_eq!(unopenable_reason(&reserved), "its folder and docs are in place; its code is not");

        // Code exists but this binary does not link it. The old wording claimed
        // the code was missing, which is the lie this test exists to prevent.
        let held = manifest("live", true, false);
        assert!(held.has_code());
        assert!(Hosted::find(&held.id).is_none());
        assert_eq!(unopenable_reason(&held), "its code exists, but this build does not host it");

        // Registered and hosted, but the manifest is not ready yet. Built from
        // the real Agent row so the hosted branch is genuinely exercised.
        let mut unready = manifest("preview", false, true);
        unready.id = "archx-agent".to_owned();
        assert!(Hosted::find(&unready.id).is_some());
        assert_eq!(unopenable_reason(&unready), "it is registered, but not ready to open yet");
    }

    #[test]
    fn hosting_is_what_makes_an_app_openable_not_its_status_label() {
        // `is_live` alone used to decide this, so a registered app whose status
        // was "preview" looked clickable and did nothing.
        let preview = manifest("preview", true, true);
        assert!(!preview.is_live(), "the label is not live");
        assert!(preview.is_registered(), "but it is registered, so it may open");
        let held = manifest("live", true, false);
        assert!(!held.is_registered(), "a live label cannot publish an unbuilt crate");
        let unbuilt = manifest("building", false, false);
        assert!(!unbuilt.is_registered(), "a folder still being built stays out");
    }
}
