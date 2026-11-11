//! Purpose: Renders the Archx AI Lab app-launcher home and available About page.
use std::sync::LazyLock;

use iced::widget::{button, column, container, image, row, scrollable, space, text};
use iced::{Center, ContentFit, Element, Fill, FillPortion};

use crate::app::{Message, Page};
use crate::app_tile::{self, APPS};
use crate::style;

static AGENT_COVER: LazyLock<image::Handle> = LazyLock::new(|| {
    image::Handle::from_bytes(include_bytes!("../assets/agent-cover.png").to_vec())
});

pub fn view(page: Page) -> Element<'static, Message> {
    container(
        row![sidebar(page), main_content(page)]
            .width(Fill)
            .height(Fill),
    )
    .width(Fill)
    .height(Fill)
    .style(style::canvas)
    .into()
}

fn sidebar(page: Page) -> Element<'static, Message> {
    let identity = row![
        container(text("A").size(19).color(style::BLACK))
            .padding([5, 11])
            .style(style::brand_mark),
        column![
            text("ARCHX").size(15).color(style::WHITE),
            text("AI LAB").size(10).color(style::GREY)
        ]
        .spacing(2)
    ]
    .spacing(12)
    .align_y(Center);

    let discover = button(text("Discover").size(14))
        .width(Fill)
        .padding([12, 15])
        .on_press(Message::Navigate(Page::Home))
        .style(move |theme, status| style::nav(page == Page::Home, theme, status));
    let about = button(text("About").size(14))
        .width(Fill)
        .padding([12, 15])
        .on_press(Message::Navigate(Page::About))
        .style(move |theme, status| style::nav(page == Page::About, theme, status));

    let navigation = column![
        identity,
        space().height(56),
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
        space().height(34),
        text("YOUR APPS").size(10).color(style::DIM),
        space().height(16),
        text("    Archx Agent").size(13).color(style::GREY),
        space().height(15),
        text("    Model Training").size(13).color(style::DIM),
        space().height(15),
        text("    Fine-tuning").size(13).color(style::DIM),
        space().height(15),
        text("    Model Monitor").size(13).color(style::DIM),
        space().height(Fill),
        text("ARCHNEMIX   /   LOCAL PREVIEW").size(10).color(style::DIM)
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

fn main_content(page: Page) -> Element<'static, Message> {
    scrollable(match page {
        Page::Home => home(),
        Page::About => about(),
    })
    .width(Fill)
    .height(Fill)
    .into()
}

fn home() -> Element<'static, Message> {
    let topbar = row![
        text("DISCOVER").size(11).color(style::GREY).width(Fill),
        text("ARCHX AI LAB    /    PREVIEW 01").size(11).color(style::DIM)
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
                container(text("IN DEVELOPMENT").size(11).color(style::WHITE))
                    .padding([10, 14])
                    .style(style::badge)
            ]
            .spacing(0)
            .width(FillPortion(1))
            .padding(iced::Padding::new(22.0).right(0).left(30)),
            image(AGENT_COVER.clone())
                .width(FillPortion(1))
                .height(248)
                .content_fit(ContentFit::Contain)
        ]
        .height(248)
        .align_y(Center),
    )
    .width(Fill)
    .style(style::surface);

    let shelf_heading = row![
        column![
            text("THE COLLECTION").size(10).color(style::DIM),
            space().height(7),
            text("Your AI apps").size(24).color(style::WHITE)
        ]
        .width(Fill),
        text("04 APPS   /   MORE TO COME").size(11).color(style::DIM)
    ]
    .align_y(Center);

    let apps = row![
        app_tile::view(&APPS[0]),
        app_tile::view(&APPS[1]),
        app_tile::view(&APPS[2]),
        app_tile::view(&APPS[3])
    ]
    .spacing(17);

    let footer = row![
        text("A SPACE FOR WHAT COMES NEXT").size(10).color(style::DIM).width(Fill),
        text("ARCHX  /  ARCHNEMIX").size(10).color(style::DIM)
    ];

    column![
        topbar,
        space().height(24),
        text("The Lab").size(38).color(style::WHITE),
        space().height(8),
        text("One place for the AI apps you make your own.").size(15).color(style::GREY),
        space().height(22),
        hero,
        space().height(30),
        shelf_heading,
        space().height(20),
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
        text("More than a chat window.").size(35).color(style::WHITE),
        space().height(16),
        text("Archx AI Lab is the Archnemix launcher for AI tools and experiences.")
            .size(16)
            .color(style::GREY),
        space().height(40),
        container(
            column![
                text("THIS IS THE BEGINNING").size(11).color(style::DIM),
                space().height(18),
                text("The Lab starts with its launcher. Archx Agent, model training, fine-tuning and observation will become available as each app is built and tested.")
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
