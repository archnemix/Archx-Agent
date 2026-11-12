//! Purpose: Renders the Archx AI Lab app-launcher home and available About page.
use std::sync::LazyLock;

use iced::widget::{button, column, container, image, row, scrollable, space, text};
use iced::{Center, ContentFit, Element, Fill, FillPortion};

use crate::agent;
use crate::agent_visual;
use crate::app::{ChatDraft, MemoryMode, Message, Page};
use crate::app_tile::{self, Art, APPS};
use crate::settings;
use crate::style;

static BRAND: LazyLock<image::Handle> = LazyLock::new(|| {
    image::Handle::from_bytes(include_bytes!("../assets/brand/archnemix-sidebar.png").to_vec())
});

pub fn view(page: Page, hovered: Option<Art>, phase: u8, agent_phase: u8, drafts: &[ChatDraft], selected: u32, memory: MemoryMode, keep_agent: bool) -> Element<'static, Message> {
    container(
        row![sidebar(page), main_content(page, hovered, phase, agent_phase, drafts, selected, memory, keep_agent)]
            .width(Fill)
            .height(Fill),
    )
    .width(Fill)
    .height(Fill)
    .style(style::canvas)
    .into()
}

fn sidebar(page: Page) -> Element<'static, Message> {
    let identity = image(BRAND.clone())
        .width(116)
        .height(116)
        .content_fit(ContentFit::Contain);

    let discover = button(text("Discover").size(style::TYPE_BODY).font(style::LABEL))
        .width(Fill)
        .padding([12, 15])
        .on_press(Message::Navigate(Page::Home))
        .style(move |theme, status| style::nav(page == Page::Home, theme, status));
    let settings = button(text("Settings").size(style::TYPE_BODY).font(style::LABEL))
        .width(Fill)
        .padding([12, 15])
        .on_press(Message::Navigate(Page::Settings))
        .style(move |theme, status| style::nav(page == Page::Settings, theme, status));
    let about = button(text("About").size(style::TYPE_BODY).font(style::LABEL))
        .width(Fill)
        .padding([12, 15])
        .on_press(Message::Navigate(Page::About))
        .style(move |theme, status| style::nav(page == Page::About, theme, status));

    let navigation = column![
        identity,
        space().height(18),
        text("BROWSE").size(10).color(style::DIM),
        space().height(16),
        discover,
        space().height(7),
        container(row![
            text("Library").size(14).color(style::DIM).width(Fill),
            text("SOON").size(10).color(style::DIM)
        ])
            .padding([12, 15]),
        space().height(7),
        about,
        space().height(7),
        settings,
        space().height(34),
        text("YOUR APPS").size(10).color(style::DIM),
        space().height(16),
        button(text("Archx Agent").size(13).color(style::WHITE))
            .width(Fill).padding([10, 14])
            .on_press(Message::Navigate(Page::Agent))
            .style(move |theme, status| style::nav(page == Page::Agent, theme, status)),
        space().height(15),
        text("    Model Training").size(13).color(style::DIM),
        space().height(15),
        text("    Fine-tuning").size(13).color(style::DIM),
        space().height(Fill),
        text("ARCHNEMIX").size(10).color(style::DIM)
    ]
    .width(Fill)
    .height(Fill)
    .padding(23);

    container(navigation)
        .width(220)
        .height(Fill)
        .style(style::rail)
        .into()
}

fn main_content(page: Page, hovered: Option<Art>, phase: u8, agent_phase: u8, drafts: &[ChatDraft], selected: u32, memory: MemoryMode, keep_agent: bool) -> Element<'static, Message> {
    match page {
        Page::Agent => agent::view(drafts, selected),
        Page::Settings => settings::view(memory, keep_agent),
        Page::Home | Page::About => scrollable(match page {
            Page::Home => home(hovered, phase, agent_phase),
            _ => about(),
        }).width(Fill).height(Fill).into(),
    }
}

fn home(hovered: Option<Art>, phase: u8, agent_phase: u8) -> Element<'static, Message> {
    let topbar = row![
        text("DISCOVER").size(11).color(style::GREY).width(Fill),
        text("ARCHX AI LAB    /    ARCHNEMIX").size(11).color(style::DIM)
    ]
    .align_y(Center);

    let hero = container(
        row![
            column![
                text("FEATURED APP     /     01").size(11).color(style::GREY),
                space().height(18),
                text("Archx Agent").size(34).color(style::WHITE),
                space().height(8),
                text("Chat, research, build and learn with an agent\ndesigned to work on your terms.")
                    .size(14)
                    .color(style::GREY),
                space().height(18),
                button(text("OPEN AGENT UI  →").size(11).color(style::WHITE))
                    .padding([10, 14])
                    .on_press(Message::Navigate(Page::Agent))
                    .style(style::quiet_button)
            ]
            .spacing(0)
            .width(FillPortion(1))
            .padding(iced::Padding::new(22.0).right(0).left(30)),
            agent_visual::hero(agent_phase)
        ]
        .height(248)
        .align_y(Center),
    )
    .width(Fill)
    .style(style::surface);

    let shelf_heading = row![
        column![
            text("EXPLORE").size(style::TYPE_LABEL).font(style::LABEL).color(style::DIM),
            space().height(style::SPACE_1),
            text("AI workspaces").size(style::TYPE_SECTION).font(style::DISPLAY).color(style::WHITE)
        ]
        .width(Fill),
        text("03 APPS   /   MORE TO COME").size(11).color(style::DIM)
    ]
    .align_y(Center);

    let apps = row![
        app_tile::view(&APPS[0], 0, agent_phase),
        app_tile::view(&APPS[1], if hovered == Some(Art::Training) { phase } else { 0 }, agent_phase),
        app_tile::view(&APPS[2], if hovered == Some(Art::Tuning) { phase } else { 0 }, agent_phase)
    ]
    .spacing(17);

    let footer = row![
        text("A SPACE FOR WHAT COMES NEXT").size(10).color(style::DIM).width(Fill),
        text("ARCHX  /  ARCHNEMIX").size(10).color(style::DIM)
    ];

    column![
        topbar,
        space().height(24),
        text("The Lab").size(style::TYPE_PAGE).font(style::DISPLAY).color(style::WHITE),
        space().height(style::SPACE_1),
        text("One place for the AI apps you make your own.").size(15).color(style::GREY),
        space().height(style::SPACE_3),
        hero,
        space().height(style::SPACE_4),
        shelf_heading,
        space().height(style::SPACE_2),
        apps,
        space().height(46),
        footer
    ]
    .padding(36)
    .width(Fill)
    .into()
}

fn about() -> Element<'static, Message> {
    column![
        text("ARCHX  /  ABOUT").size(11).color(style::DIM),
        space().height(31),
        text("More than a chat window.").size(35).font(style::DISPLAY).color(style::WHITE),
        space().height(16),
        text("Archx AI Lab is the Archnemix launcher for AI tools and experiences.")
            .size(16)
            .color(style::GREY),
        space().height(40),
        container(
            column![
                text("THIS IS THE BEGINNING").size(11).color(style::DIM),
                space().height(18),
                text("The Lab starts with its launcher. Archx Agent, model training and fine-tuning will become available as each app is built and tested.")
                    .size(17)
                    .color(style::WHITE)
            ]
            .width(Fill)
        )
        .padding(30)
        .width(Fill)
        .style(style::surface)
    ]
    .padding(36)
    .width(Fill)
    .into()
}
