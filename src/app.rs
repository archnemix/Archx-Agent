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
    Agent,
    AgentSettings,
    AgentDebug,
    /// Launcher-owned settings (display scale, memory scope, storage, apps).
    LabSettings,
}

impl Page {
    /// The page a stored `last_page` id refers to.
    pub fn from_id(id: &str) -> Self {
        match id {
            "agent" => Self::Agent,
            "settings" => Self::AgentSettings,
            "debug" => Self::AgentDebug,
            "lab-settings" => Self::LabSettings,
            "about" => Self::About,
            _ => Self::Home,
        }
    }

    pub fn id(self) -> &'static str {
        match self {
            Self::Home => "home",
            Self::About => "about",
            Self::Agent => "agent",
            Self::AgentSettings => "settings",
            Self::AgentDebug => "debug",
            Self::LabSettings => "lab-settings",
        }
    }

    pub fn is_agent_surface(self) -> bool {
        matches!(self, Self::Agent | Self::AgentSettings | Self::AgentDebug)
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
    match page {
        Page::AgentSettings => "settings",
        Page::AgentDebug => "debug",
        _ => "agent",
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
                Ok("agent") => Page::Agent,
                Ok("settings") => Page::AgentSettings,
                Ok("debug") => Page::AgentDebug,
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

    /// The live app record for an id, if it is openable.
    pub fn launchable(&self, id: &str) -> Option<&apps::App> {
        self.apps.iter().find(|app| app.id == id && app.is_live())
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
                    // The Agent's manifest id is the only in-process app today.
                    if id == "archx-agent" { return self.go(Page::Agent); }
                }
                self.notice = self.apps.iter().find(|app| app.id == id)
                    .map(|app| format!("{} is not available yet ({}). Its folder and docs are in place; its code is not.", app.name, app.status));
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
                            archx_agent::app::Page::Settings => Page::AgentSettings,
                            archx_agent::app::Page::Debug => Page::AgentDebug,
                            _ => Page::Agent,
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

