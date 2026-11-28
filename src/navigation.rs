//! Purpose: Renders the launcher rail, Discover screen, app tiles from manifests, About and launcher settings.
//!
//! The launcher's rail and tile shelf are generated from `apps/*/app.toml`
//! (`archx_shared::apps`). Nothing here names a specific app: a new manifest appears as
//! a tile. Only `ready = true` folders are passed in here at all; among those, a
//! manifest with `status = "live"` becomes openable.

use std::sync::LazyLock;
use std::time::Duration;

use iced::widget::{button, column, container, image, mouse_area, row, scrollable, space, svg, text, tooltip};
use iced::{Center, ContentFit, Element, Fill, FillPortion, Length};

use crate::app::{App as Launcher, Area, Message, Page, Scope};
use archx_shared::apps::App;
use archx_shared::persist::TextScale;
use archx_shared::style;

static BRAND: LazyLock<image::Handle> = LazyLock::new(|| {
    image::Handle::from_bytes(include_bytes!("../shared/assets/brand/archnemix-sidebar.png").to_vec())
});

#[derive(Clone, Copy)]
enum Icon {
    Home, Agent, About, Settings, Expand, Collapse, Info,
    /// A workbench app (its manifest says `art = "workbench"`); the launcher
    /// draws its own icon rather than borrowing the Agent's chat glyph.
    Workspace,
}

fn glyph(icon: Icon, selected: bool, size: u32) -> svg::Svg<'static> {
    let bytes: &'static [u8] = match icon {
        Icon::Home => include_bytes!("../shared/assets/icons/house.svg"),
        Icon::Agent => include_bytes!("../shared/assets/icons/message-circle.svg"),
        Icon::About => include_bytes!("../shared/assets/icons/info.svg"),
        Icon::Settings => include_bytes!("../shared/assets/icons/settings-2.svg"),
        Icon::Expand => include_bytes!("../shared/assets/icons/panel-left-open.svg"),
        Icon::Collapse => include_bytes!("../shared/assets/icons/panel-left-close.svg"),
        Icon::Info => include_bytes!("../shared/assets/icons/info.svg"),
        Icon::Workspace => include_bytes!("../shared/assets/icons/monitor.svg"),
    };
    svg(svg::Handle::from_memory(bytes))
        .width(size).height(size)
        .style(move |_, _| svg::Style { color: Some(if selected { style::WHITE } else { style::GREY }) })
}

fn hint(content: impl Into<Element<'static, Message>>, label: &'static str) -> Element<'static, Message> {
    tooltip::Tooltip::new(content, text(label).size(12).color(style::WHITE), tooltip::Position::Right)
        .gap(12).padding(10).delay(Duration::from_millis(300))
        .style(style::rail_hint).into()
}

fn compact_action(icon: Icon, label: &'static str, action: Message, selected: bool) -> Element<'static, Message> {
    let control = button(container(glyph(icon, selected, 22)).center_x(Fill).center_y(Fill))
        .width(52).height(52).padding(0).on_press(action)
        .style(move |theme, status| style::compact_nav(selected, theme, status));
    hint(control, label)
}

/// The label is owned, not `&'static str`: an app's rail entry names it from its
/// manifest, and forcing a static string would mean the launcher could only ever
/// list apps whose names were compiled into it.
fn expanded_action(icon: Icon, label: impl Into<String>, action: Message, selected: bool) -> Element<'static, Message> {
    button(row![
        glyph(icon, selected, 19),
        text(label.into()).size(13).font(style::LABEL).color(if selected { style::WHITE } else { style::GREY })
    ].spacing(14).align_y(Center))
        .width(Fill).padding([12, 15]).on_press(action)
        .style(move |theme, status| style::nav(selected, theme, status))
        .into()
}

fn divider() -> Element<'static, Message> {
    container(space().height(1)).width(42).style(style::rail_divider).into()
}

fn rail(state: &Launcher) -> Element<'static, Message> {
    let scale = state.display.launcher.factor();
    let page = state.page;
    if !state.sidebar_expanded {
        let content = column![
            image(BRAND.clone()).width(72).height(78).content_fit(ContentFit::Contain),
            space().height(28),
            compact_action(Icon::Home, "Discover", Message::Navigate(Page::Home), page == Page::Home),
            space().height(12),
            compact_action(Icon::Agent, "Archx Agent", Message::Navigate(Page::app("archx-agent")), page.is_agent_surface()),
            space().height(12),
            compact_action(Icon::Settings, "Lab settings", Message::Navigate(Page::LabSettings), page == Page::LabSettings),
            space().height(Fill),
            divider(),
            space().height(16),
            compact_action(Icon::Expand, "Expand navigation", Message::ToggleSidebar, false)
        ].align_x(Center).width(Fill).height(Fill).padding([20, 10]);
        return container(content).width(92).height(Fill).style(style::rail).into();
    }
    let mut content = column![
        image(BRAND.clone()).width(116).height(116).content_fit(ContentFit::Contain),
        space().height(24),
        text("WORKSPACES").size(10.0 * scale).color(style::DIM),
        space().height(10),
        expanded_action(Icon::Home, "Discover", Message::Navigate(Page::Home), page == Page::Home),
        space().height(8)
    ];
    // One rail entry per discoverable app, from its manifest.
    for app in &state.apps {
        // Hosting is asked of the launcher's own table, not of a hard-coded id:
        // an app that is ready but not linked into this binary stays held, and
        // held is shown, never silently dropped.
        let hosted = crate::app::Hosted::find(&app.id);
        let openable = app.is_registered() && hosted.is_some();
        let label = app.name.clone();
        let active = page.hosted_app().is_some_and(|(id, _)| id == app.id);
        if openable {
            let Some(hosted) = hosted else { continue };
            let id = hosted.id;
            // The glyph follows the app's artwork style from its manifest, so a
            // workbench app is not drawn with the Agent's icon.
            let icon = if app.art == "agent" { Icon::Agent } else { Icon::Workspace };
            content = content.push(expanded_action(icon, label,
                Message::Navigate(Page::App { id, surface: hosted.surfaces[0] }), active));
        } else {
            // Why it is not openable matters: a held app and an unbuilt one look
            // identical on screen otherwise, and the owner needs to know which.
            let reason = if !app.ready { "building" }
                else if hosted.is_none() { "held · not in this build" }
                else { app.status.as_str() };
            content = content.push(container(
                row![
                    text(format!("    {}", app.name)).size(12.0 * scale).color(style::DIM).width(Fill),
                    text(reason).size(10.0).color(style::DIM)
                ].spacing(8)
            ).padding([10, 15]).width(Fill));
        }
        content = content.push(space().height(6));
    }
    content = content.push(space().height(10));
    content = content.push(expanded_action(Icon::Settings, "Lab settings", Message::Navigate(Page::LabSettings), page == Page::LabSettings));
    content = content.push(space().height(Fill));
    content = content.push(container(space().height(1)).width(Fill).style(style::rail_divider));
    content = content.push(space().height(10));
    content = content.push(expanded_action(Icon::Info, "About", Message::Navigate(Page::About), page == Page::About));
    content = content.push(space().height(6));
    content = content.push(hint(button(row![glyph(Icon::Collapse, false, 19),
            text("Collapse navigation").size(12).color(style::GREY)].spacing(12).align_y(Center))
            .width(Fill).padding([10, 14]).on_press(Message::ToggleSidebar).style(style::rail_toggle),
        "Collapse navigation"));
    container(content.width(Fill).height(Fill).padding(20))
        .width(220).height(Fill).style(style::rail).into()
}

/// A discovered app's card. Art comes from the manifest's `art` field and the
/// frame index from the Discover cycle (a scripted screenshot pins both).
fn tile(app: &App, phase: u8, hovered: Option<&str>) -> Element<'static, Message> {
    let lit = hovered == Some(app.id.as_str()) || hovered == Some(app.art.as_str());
    let accent = app.is_live();
    let artwork: Element<'static, Message> = if app.art == "agent" {
        container(column![
            text("ARCHX  /  SIX MODES").size(10).color(style::GREY),
            space().height(5),
            text("AGENT").size(39).color(style::WHITE),
            space().height(Fill),
            row![
                text(format!("{:02} / {:02}", phase % app.mode_count() + 1, app.mode_count())).size(10).color(style::DIM).width(Fill),
                text(app.modes.get(usize::from(phase % app.mode_count())).cloned().unwrap_or_default()).size(12).color(style::WHITE)
            ],
            space().height(8)
        ].width(Fill).height(Fill).padding(18))
            .width(Fill).height(140).clip(true)
            .style(move |theme| style::agent_surface(theme, lit)).into()
    } else {
        let words = app.stage_words();
        let current = words.get(usize::from(phase) % words.len().max(1)).cloned().unwrap_or_default();
        let panel = container(column![
            text(app.category.clone()).size(style::TYPE_LABEL).font(style::LABEL).color(style::GREY),
            space().height(style::SPACE_1),
            text(current).size(35).font(style::DISPLAY_BOLD).color(style::WHITE),
            space().height(Fill),
            row![
                text(app.status_label()).size(10).font(style::LABEL).color(style::DIM).width(Fill),
                text(format!("{:02} / {:02}", phase % app.mode_count() + 1, app.mode_count())).size(10).color(style::GREY)
            ]
        ].width(Fill).height(Fill).padding(style::SPACE_2))
            .width(Fill).height(140).clip(true).style(move |theme| style::workbench_surface(theme, lit));
        panel.into()
    };
    let id = app.id.clone();
    let card = column![
        artwork,
        space().height(style::SPACE_2),
        text(app.category.clone()).size(style::TYPE_LABEL).font(style::LABEL).color(style::DIM),
        space().height(4),
        text(app.name.clone()).size(17).font(style::DISPLAY).color(style::WHITE),
        // The summary is what tells a user what the app does; a tile that only
        // prints its own name and status says nothing.
        space().height(6),
        text(fit_words(&app.summary, 130)).size(12).color(style::GREY),
        space().height(4),
        text(app.status_label()).size(style::TYPE_LABEL).color(if accent { style::WHITE } else { style::GREY })
    ].width(FillPortion(1));
    let control = button(card).padding(0).width(Fill)
        .style(|_, _| iced::widget::button::Style { background: None, ..Default::default() });
    mouse_area(control)
        .on_press(Message::LaunchApp(id))
        .into()
}

/// Shortens `text` to at most `limit` characters without cutting a word in half.
fn fit_words(text: &str, limit: usize) -> String {
    if text.chars().count() <= limit { return text.to_owned(); }
    let mut out = String::new();
    for word in text.split_whitespace() {
        let extra = word.chars().count() + usize::from(!out.is_empty());
        if out.chars().count() + extra > limit.saturating_sub(1) { break; }
        if !out.is_empty() { out.push(' '); }
        out.push_str(word);
    }
    out.push('…');
    out
}

fn discover(state: &Launcher) -> Element<'static, Message> {
    let scale = state.display.launcher.factor();
    // The featured tile follows registration, not the "live" label, for the
    // same reason `launchable` does.
    let featured = state.apps.iter().find(|app| app.is_registered());
    let hero: Element<'static, Message> = match featured {
        Some(app) => {
            let id = app.id.clone();
            container(row![
                column![
                    text(format!("FEATURED APP     /     {:02}", state.apps.len().max(1))).size(11).color(style::GREY),
                    space().height(18),
                    text(app.name.clone()).size(34).color(style::WHITE),
                    space().height(8),
                    text(app.summary.clone()).size(14).color(style::GREY),
                    space().height(18),
                    // The button names the app it opens. It used to say "OPEN
                    // AGENT UI" for whatever app happened to be featured, which
                    // would have been wrong the moment a second app went live.
                    button(text(format!("OPEN {}  →", app.name.to_uppercase())).size(11).color(style::WHITE))
                        .padding([10, 14]).on_press(Message::LaunchApp(id))
                        .style(style::quiet_button)
                ].spacing(0).width(FillPortion(1)).padding(iced::Padding::new(22.0).right(0).left(30)),
                container(column![
                    text(if app.art == "agent" {
                        "SIX MODES  /  ONE AGENT"
                    } else {
                        "ONE WORKBENCH  /  ITS OWN STAGES"
                    }).size(11).color(style::GREY),
                    space().height(25),
                    text("ARCHX").size(32).color(style::GREY),
                    // A non-Agent app must not wear the Agent's wordmark.
                    text(if app.art == "agent" { "AGENT" } else { "LAB" }).size(52).color(style::WHITE),
                    space().height(Fill),
                    // Trimmed at a word boundary: a hard character cut ended the
                    // front page on a half-word like "never ac".
                    text(fit_words(&app.summary, 90)).size(11).color(style::DIM)
                ].width(Fill).padding([23, 30]))
                    .width(FillPortion(1)).height(248).style(|theme| style::agent_surface(theme, false))
            ].height(248).align_y(Center)).width(Fill).style(style::surface).into()
        }
        None => space().height(0).into(),
    };
    // Three per line, as many lines as the manifests need.
    let mut cards = column![].spacing(17).width(Fill);
    let mut line = row![].spacing(17).width(Fill);
    let mut per_line = 0;
    for app in &state.apps {
        let cycle = if app.art == "agent" { state.agent_phase } else { state.phase };
        line = line.push(tile(app, cycle, state.hovered.as_deref()));
        per_line += 1;
        if per_line == 3 { cards = cards.push(line); line = row![].spacing(17).width(Fill); per_line = 0; }
    }
    if per_line > 0 { cards = cards.push(line); }
    let count = state.apps.len();
    column![
        row![
            text("DISCOVER").size(11).color(style::GREY).width(Fill),
            text("ARCHX AI LAB    /    ARCHNEMIX").size(11).color(style::DIM)
        ].align_y(Center),
        space().height(24),
        text("The Lab").size(style::TYPE_PAGE * scale).font(style::DISPLAY).color(style::WHITE),
        space().height(style::SPACE_1),
        text("One place for the AI apps you make your own.").size(15.0 * scale).color(style::GREY),
        space().height(style::SPACE_3),
        hero,
        space().height(style::SPACE_4),
        row![
            column![
                text("EXPLORE").size(style::TYPE_LABEL).font(style::LABEL).color(style::DIM),
                space().height(style::SPACE_1),
                text("AI workspaces").size(style::TYPE_SECTION * scale).font(style::DISPLAY).color(style::WHITE)
            ].width(Fill),
            text(format!("{count:02} APPS   /   DISCOVERED FROM apps/")).size(11).color(style::DIM)
        ].align_y(Center),
        space().height(style::SPACE_2),
        cards,
        space().height(46),
        row![
            text("A SPACE FOR WHAT COMES NEXT").size(10).color(style::DIM).width(Fill),
            text("ARCHX  /  ARCHNEMIX").size(10).color(style::DIM)
        ]
    ].padding(36).width(Fill).into()
}

fn about(state: &Launcher) -> Element<'static, Message> {
    let scale = state.display.launcher.factor();
    let names: Vec<String> = state.apps.iter().map(|app| format!("{} ({})", app.name, app.status)).collect();
    column![
        text("ARCHX  /  ABOUT").size(11).color(style::DIM),
        space().height(31),
        text("More than a chat window.").size(35.0 * scale).font(style::DISPLAY).color(style::WHITE),
        space().height(16),
        text("Archx AI Lab is the Archnemix launcher for AI tools and experiences.").size(16.0 * scale).color(style::GREY),
        space().height(40),
        container(column![
            text("THIS IS THE BEGINNING").size(11).color(style::DIM),
            space().height(18),
            text("The Lab hosts every app it finds in apps/. Each folder owns its code, docs and manifest; the launcher only reads the manifest.")
                .size(17.0 * scale).color(style::WHITE),
            space().height(12),
            text(format!("Installed here: {}.", names.join(", "))).size(13.0 * scale).color(style::GREY)
        ].width(Fill)).padding(30).width(Fill).style(style::surface)
    ].padding(36).width(Fill).into()
}

fn scale_row(label: &'static str, area: Area, scale: TextScale, note: &'static str) -> Element<'static, Message> {
    row![
        column![
            text(label).size(12.5).font(style::STRONG).color(style::WHITE),
            text(note).size(10.5).color(style::GREY)
        ].spacing(2).width(Fill),
        button(text("A−").size(11)).on_press(Message::ScaleOut(area)).style(style::tiny_button),
        text(scale.label()).size(11).color(style::GREY).width(46),
        button(text("A+").size(11)).on_press(Message::ScaleIn(area)).style(style::tiny_button),
        button(text("Reset").size(10.5)).on_press(Message::ScaleReset(area)).style(style::tiny_button)
    ].spacing(6).align_y(Center).into()
}

/// Launcher-owned settings: the display scale for every area, the memory scope
/// handed to the Agent, the app folder, and wiping. App-specific options stay in
/// the app's own Settings so the two never collide.
fn lab_settings(state: &Launcher) -> Element<'static, Message> {
    let scale = state.display.launcher.factor();
    let mut scopes = row![].spacing(8);
    for scope in Scope::ALL {
        let active = state.agent_scope == scope;
        scopes = scopes.push(button(text(scope.label()).size(12.5)).padding([8, 14])
            .on_press(Message::AgentScope(scope))
            .style(move |theme, status| style::side_nav(active, theme, status)));
    }
    let notice: Element<'static, Message> = match &state.notice {
        Some(notice) => container(row![
            text(notice.clone()).size(11.5).color(style::WHITE).width(Fill),
            button(text("Dismiss").size(10.5)).on_press(Message::DismissNotice).style(style::tiny_button)
        ].spacing(8).align_y(Center)).padding([8, 12]).width(Fill).style(style::card).into(),
        None => space().height(0).into(),
    };
    let mut apps: Vec<String> = state.apps.iter()
        .map(|app| format!("{} · {} · {} · released", app.name, app.status, app.id)).collect();
    // A hold must never be silent: the user has to be able to see that an app is
    // finished and deliberately out of this build.
    for app in &state.held_apps {
        apps.push(format!("{} · {} · {} · held out of this build", app.name, app.status, app.id));
    }
    column![
        text("LAB SETTINGS").size(11).color(style::DIM),
        space().height(20),
        text("Launcher").size(28.0 * scale).font(style::DISPLAY).color(style::WHITE),
        space().height(6),
        text("Options that belong to the launcher itself: how the Lab looks, how much the Agent may keep resident, where apps live, and wiping. App settings stay inside each app.")
            .size(12.5).color(style::GREY),
        space().height(20),
        notice,
        space().height(14),
        container(column![
            text("DISPLAY  /  PER AREA").size(11).color(style::WHITE),
            space().height(10),
            scale_row("Launcher text", Area::Launcher, state.display.launcher, "Discover, About and this page"),
            space().height(6),
            scale_row("Chat text", Area::Chat, state.display.chat, "Archx Agent conversation"),
            space().height(6),
            scale_row("Settings text", Area::Settings, state.display.settings, "Archx Agent settings")
        ].width(Fill)).padding(20).width(Fill).style(style::card),
        space().height(14),
        container(column![
            text("MEMORY SCOPE  /  HANDED TO THE AGENT").size(11).color(style::WHITE),
            space().height(10),
            scopes,
            space().height(10),
            text("A scope is a starting point, not a RAM cap. The Agent's Runtime memory page shows what is measured and lets you release it per stage.")
                .size(11).color(style::GREY),
            space().height(10),
            row![
                text(format!("Launcher scope: {} (its own data is a few KB)", state.launcher_scope.label())).size(11).color(style::GREY).width(Fill),
                button(text("Light").size(10.5)).on_press(Message::LauncherScope(Scope::Light)).style(style::tiny_button)
            ].spacing(8).align_y(Center)
        ].width(Fill)).padding(20).width(Fill).style(style::card),
        space().height(14),
        container(column![
            text("LAUNCHER RAM  /  PER STAGE").size(11).color(style::WHITE),
            space().height(8),
            text("What the launcher itself keeps at each stage. This is launcher state only — a few KB — so it records your decision and never caps another process. Each app configures its own matrix inside that app's Runtime page.")
                .size(11).color(style::GREY),
            space().height(12),
            launcher_budget_table(&state.launcher_budget)
        ].width(Fill)).padding(20).width(Fill).style(style::card),
        space().height(14),
        container(column![
            text("APPS  /  DISCOVERED").size(11).color(style::WHITE),
            space().height(8),
            column(apps.into_iter().map(|line| text(line).size(11.5).color(style::GREY).into()).collect::<Vec<Element<'static, Message>>>()).spacing(4),
            space().height(10),
            row![
                button(text("Rescan apps").size(11)).on_press(Message::RefreshApps).style(style::control_button),
                text("Add a folder with app.toml, then release it here. A held app keeps its tile out of this build until you publish it.").size(10.5).color(style::DIM).width(Fill)
            ].spacing(8).align_y(Center)
        ].width(Fill)).padding(20).width(Fill).style(style::card),
        space().height(14),
        container(column![
            text("DATA  /  WIPE").size(11).color(style::WHITE),
            space().height(8),
            text(format!("Location: {}", state.storage_path)).size(11).color(style::GREY),
            space().height(10),
            row![
                button(text("Wipe chat history").size(11)).on_press(Message::Wipe(Area::Chat)).style(style::control_button),
                button(text("Wipe provider settings").size(11)).on_press(Message::Wipe(Area::Settings)).style(style::control_button),
                button(text("Wipe everything").size(11)).on_press(Message::WipeAll).padding([8, 12]).style(style::control_button)
            ].spacing(8),
            space().height(8),
            text("Vault keys are never deleted by a wipe; remove them in the Agent's Providers page.").size(10.5).color(style::DIM)
        ].width(Fill)).padding(20).width(Fill).style(style::card)
    ].padding(36).width(Fill).into()
}

/// The launcher's per-stage matrix: one row per launcher cache, one column per
/// stage, a single small toggle per cell. Deliberately plain — it answers
/// "what stays resident when" and nothing else.
fn launcher_budget_table(budget: &archx_shared::memory::Budget) -> Element<'static, Message> {
    use archx_shared::memory::{Item, Stage};
    let mut head = row![text("").width(190)].spacing(6);
    for stage in Stage::ALL {
        head = head.push(text(stage.label()).size(10.5).color(style::DIM).width(Length::Fixed(104.0)));
    }
    let mut grid = column![head].spacing(6);
    for item in Item::ALL {
        let mut line = row![
            column![
                text(item.label()).size(11.5).color(style::WHITE),
                text(item.detail()).size(10).color(style::DIM).width(Length::Fixed(190.0))
            ].spacing(2).width(190)
        ].spacing(6).align_y(Center);
        for stage in Stage::ALL {
            let kept = budget.keeps(stage, item);
            line = line.push(button(
                    container(text(if kept { "keep" } else { "drop" }).size(10.5)
                        .color(if kept { style::WHITE } else { style::DIM }))
                        .padding([4, 10])
                )
                .on_press(Message::LauncherBudget(stage, item))
                .style(move |theme, status| style::side_nav(kept, theme, status))
                .width(Length::Fixed(104.0)));
        }
        grid = grid.push(line);
    }
    grid.into()
}

pub fn view(state: &Launcher) -> Element<'_, Message> {
    let body: Element<'_, Message> = match state.page {
        Page::Home => scrollable(discover(state)).width(Fill).height(Fill).style(style::quiet_scroll).into(),
        Page::About => scrollable(about(state)).width(Fill).height(Fill).style(style::quiet_scroll).into(),
        Page::LabSettings => scrollable(lab_settings(state)).width(Fill).height(Fill).style(style::quiet_scroll).into(),
        page if page.is_app_surface() => {
            // Only the Agent has a crate in this binary today. A second app's
            // page is reachable only once it is hosted, so this arm is the
            // honest fallback rather than a second app's UI borrowed from the
            // Agent: it says what is missing instead of showing the wrong tool.
            let content: Element<'_, Message> = match page.hosted_app() {
                Some(("archx-agent", _)) => state.agent.view().map(Message::Agent),
                Some((id, _)) => {
                    let name = state.apps.iter().find(|app| app.id == id)
                        .map(|app| app.name.clone()).unwrap_or_else(|| id.to_owned());
                    column![
                        text(name).size(28).color(style::WHITE),
                        space().height(10),
                        text("This app is not linked into this build of the launcher yet. Its folder and manifest exist; the launcher owner adds its crate to the hosted table and the release list.")
                            .size(13).color(style::GREY)
                    ].spacing(0).padding(40).into()
                }
                None => text("No app here.").size(13).color(style::GREY).into(),
            };
            // The arriving app surface fades/slides in; the launcher rail is not
            // in the Agent view (the Agent has its own).
            match state.transition {
                Some(transition) if !transition.is_complete() => {
                    // Iced 0.14 has no per-widget opacity, so the arriving app
                    // moves instead of fading: it starts slightly below its final
                    // place and settles within 220 ms (ease-out cubic). The
                    // measured offset is the slide; nothing is hidden from the
                    // user while it runs. See Plan/Architecture.md.
                    let offset = transition.offset().clamp(0.0, 28.0);
                    container(column![space().height(offset), content])
                        .width(Fill).height(Fill).style(style::canvas).into()
                }
                _ => content,
            }
        }
    };
    // An app surface draws its own navigation, so the launcher rail is not
    // stacked beside it; the launcher shell draws the rail.
    let shell = if state.page.is_app_surface() {
        body
    } else {
        row![rail(state), body].width(Fill).height(Fill).into()
    };
    container(shell).width(Fill).height(Fill).style(style::canvas).into()
}
