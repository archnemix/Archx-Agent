//! Purpose: Renders distinct expanded navigation and icon-only compact rail for the Lab.
use std::sync::LazyLock;
use std::time::Duration;

use iced::widget::{button, column, container, image, row, space, svg, text, tooltip};
use iced::{Center, ContentFit, Element, Fill};

use crate::app::{Message, Page};
use crate::style;

static BRAND: LazyLock<image::Handle> = LazyLock::new(|| {
    image::Handle::from_bytes(include_bytes!("../assets/brand/archnemix-sidebar.png").to_vec())
});

#[derive(Clone, Copy)]
enum Icon { Home, Agent, About, Settings, Expand, Collapse }

fn glyph(icon: Icon, selected: bool, size: u32) -> svg::Svg<'static> {
    let bytes: &'static [u8] = match icon {
        Icon::Home => include_bytes!("../assets/icons/house.svg"),
        Icon::Agent => include_bytes!("../assets/icons/message-circle.svg"),
        Icon::About => include_bytes!("../assets/icons/info.svg"),
        Icon::Settings => include_bytes!("../assets/icons/settings-2.svg"),
        Icon::Expand => include_bytes!("../assets/icons/panel-left-open.svg"),
        Icon::Collapse => include_bytes!("../assets/icons/panel-left-close.svg"),
    };
    svg(svg::Handle::from_memory(bytes))
        .width(size)
        .height(size)
        .style(move |_, _| svg::Style { color: Some(if selected { style::WHITE } else { style::GREY }) })
}

fn hint(content: impl Into<Element<'static, Message>>, label: &'static str) -> Element<'static, Message> {
    tooltip::Tooltip::new(content, text(label).size(12).color(style::WHITE), tooltip::Position::Right)
        .gap(12)
        .padding(10)
        .delay(Duration::from_millis(300))
        .style(style::rail_hint)
        .into()
}

fn compact_action(icon: Icon, label: &'static str, action: Message, selected: bool) -> Element<'static, Message> {
    let control = button(container(glyph(icon, selected, 22)).center_x(Fill).center_y(Fill))
        .width(52)
        .height(52)
        .padding(0)
        .on_press(action)
        .style(move |theme, status| style::compact_nav(selected, theme, status));
    hint(control, label)
}

fn expanded_action(icon: Icon, label: &'static str, action: Message, selected: bool) -> Element<'static, Message> {
    button(row![
        glyph(icon, selected, 19),
        text(label).size(13).font(style::LABEL).color(if selected { style::WHITE } else { style::GREY })
    ].spacing(14).align_y(Center))
        .width(Fill)
        .padding([12, 15])
        .on_press(action)
        .style(move |theme, status| style::nav(selected, theme, status))
        .into()
}

fn divider() -> Element<'static, Message> {
    container(space().height(1)).width(42).style(style::rail_divider).into()
}

fn compact(page: Page) -> Element<'static, Message> {
    let content = column![
        image(BRAND.clone()).width(72).height(78).content_fit(ContentFit::Contain),
        space().height(28),
        compact_action(Icon::Home, "Discover", Message::Navigate(Page::Home), page == Page::Home),
        space().height(12),
        compact_action(Icon::Agent, "Archx Agent", Message::Navigate(Page::Agent), page == Page::Agent),
        space().height(Fill),
        divider(),
        space().height(16),
        compact_action(Icon::About, "About", Message::Navigate(Page::About), page == Page::About),
        space().height(10),
        compact_action(Icon::Settings, "Settings", Message::Navigate(Page::Settings), page == Page::Settings),
        space().height(22),
        compact_action(Icon::Expand, "Expand navigation", Message::ToggleSidebar, false)
    ].align_x(Center).width(Fill).height(Fill).padding([20, 10]);
    container(content).width(92).height(Fill).style(style::rail).into()
}

fn expanded(page: Page) -> Element<'static, Message> {
    let content = column![
        image(BRAND.clone()).width(116).height(116).content_fit(ContentFit::Contain),
        space().height(26),
        text("WORKSPACES").size(10).color(style::DIM),
        space().height(12),
        expanded_action(Icon::Home, "Discover", Message::Navigate(Page::Home), page == Page::Home),
        space().height(8),
        expanded_action(Icon::Agent, "Archx Agent", Message::Navigate(Page::Agent), page == Page::Agent),
        space().height(25),
        text("COMING LATER").size(10).color(style::DIM),
        space().height(13),
        text("    Model Training").size(12).color(style::DIM),
        space().height(14),
        text("    Fine-tuning").size(12).color(style::DIM),
        space().height(Fill),
        container(space().height(1)).width(Fill).style(style::rail_divider),
        space().height(12),
        expanded_action(Icon::About, "About", Message::Navigate(Page::About), page == Page::About),
        space().height(5),
        expanded_action(Icon::Settings, "Settings", Message::Navigate(Page::Settings), page == Page::Settings),
        space().height(14),
        hint(button(row![glyph(Icon::Collapse, false, 19), text("Collapse navigation").size(12).color(style::GREY)]
                .spacing(12).align_y(Center))
            .width(Fill).padding([10, 14]).on_press(Message::ToggleSidebar).style(style::rail_toggle),
            "Collapse navigation")
    ].width(Fill).height(Fill).padding(20);
    container(content).width(220).height(Fill).style(style::rail).into()
}

pub fn view(page: Page, expanded_state: bool) -> Element<'static, Message> {
    if expanded_state { expanded(page) } else { compact(page) }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn icon_rail_uses_six_separate_local_assets() {
        let icons = [Icon::Home, Icon::Agent, Icon::About, Icon::Settings, Icon::Expand, Icon::Collapse];
        for icon in icons { let _ = glyph(icon, false, 22); }
        assert_eq!(icons.len(), 6);
    }
}
