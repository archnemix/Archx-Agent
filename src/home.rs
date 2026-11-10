//! Purpose: Renders the Archx AI Lab launcher and its available home/about navigation.
use iced::widget::{button, column, container, row, scrollable, space, text};
use iced::{Center, Element, Fill, FillPortion};

use crate::app::{Message, Page};
use crate::style;

pub fn view(page: Page) -> Element<'static, Message> {
    let content = row![sidebar(page), main_content(page)]
        .width(Fill)
        .height(Fill);

    container(content)
        .width(Fill)
        .height(Fill)
        .style(style::canvas)
        .into()
}

fn sidebar(page: Page) -> Element<'static, Message> {
    let brand = column![
        text("A  /  ARCHNEMIX").size(17).color(style::TEXT),
        text("AI WORKSPACE").size(11).color(style::FAINT)
    ]
    .spacing(5);

    let home = button(text("⌂    Home").size(15))
        .width(Fill)
        .padding([13, 16])
        .on_press(Message::Navigate(Page::Home))
        .style(move |theme, status| style::nav(page == Page::Home, theme, status));
    let about = button(text("◌    About the Lab").size(15))
        .width(Fill)
        .padding([13, 16])
        .on_press(Message::Navigate(Page::About))
        .style(move |theme, status| style::nav(page == Page::About, theme, status));

    let rail = column![
        brand,
        space().height(48),
        text("WORKSPACE").size(11).color(style::FAINT),
        space().height(12),
        home,
        about,
        space().height(32),
        text("DESTINATIONS").size(11).color(style::FAINT),
        space().height(16),
        text("    Archx Agent").size(14).color(style::MUTED),
        space().height(20),
        text("    Model Studio").size(14).color(style::FAINT),
        space().height(20),
        text("    Fine-tuning").size(14).color(style::FAINT),
        space().height(20),
        text("    Model Monitor").size(14).color(style::FAINT),
        space().height(Fill),
        text("ARCHX AI LAB   ·   EARLY BUILD").size(10).color(style::FAINT),
    ]
    .width(Fill)
    .height(Fill)
    .padding(24);

    container(rail)
        .width(236)
        .height(Fill)
        .style(style::sidebar)
        .into()
}

fn main_content(page: Page) -> Element<'static, Message> {
    let content = match page {
        Page::Home => home(),
        Page::About => about(),
    };

    scrollable(content)
        .width(Fill)
        .height(Fill)
        .into()
}

fn home() -> Element<'static, Message> {
    let heading = row![
        column![
            text("YOUR WORKSPACE").size(11).color(style::MUTED),
            space().height(14),
            text("Archx AI Lab").size(40).color(style::TEXT),
            space().height(7),
            text("One place to explore, build, and work with AI.")
                .size(16)
                .color(style::MUTED)
        ]
        .width(FillPortion(3)),
        container(text("DESKTOP  /  PREVIEW 01").size(11).color(style::FAINT))
            .width(FillPortion(1))
            .align_x(iced::alignment::Horizontal::Right)
    ]
    .align_y(Center);

    let hero = container(
        row![
            column![
                text("01  /  CONVERSATION & AGENTS")
                    .size(11)
                    .color(style::MUTED),
                space().height(22),
                text("Start with an idea.\nTake it further.")
                    .size(32)
                    .color(style::TEXT),
                space().height(15),
                text("The home for conversations, research, coding, learning,\nand everything your agents will help you make.")
                    .size(14)
                    .color(style::MUTED),
                space().height(34),
                container(text("ARCHX AGENT   ·   COMING NEXT").size(12).color(style::TEXT))
                    .padding([12, 17])
                    .style(style::selection)
            ]
            .spacing(0)
            .width(FillPortion(3)),
            container(
                column![
                    text("A").size(114).color(style::TEXT),
                    text("AN OPEN SPACE FOR INTELLIGENCE")
                        .size(10)
                        .color(style::MUTED)
                ]
                .spacing(0)
                .align_x(Center)
            )
            .width(FillPortion(1))
            .align_y(iced::alignment::Vertical::Center)
        ]
        .align_y(Center)
    )
    .width(Fill)
    .padding(32)
    .style(style::elevated);

    let categories = column![
        row![
            text("Explore the Lab").size(22).color(style::TEXT).width(Fill),
            text("MORE WORKSPACES AHEAD").size(11).color(style::FAINT)
        ]
        .align_y(Center),
        space().height(17),
        row![
            destination("02", "Model Studio", "Train and manage your own models.", "COMING LATER"),
            destination("03", "Fine-tuning", "Shape a model around your work.", "COMING LATER"),
            destination("04", "Model Monitor", "See what your models are doing.", "COMING LATER")
        ]
        .spacing(14)
    ];

    let footer = row![
        text("BUILT FOR THE CURIOUS").size(11).color(style::FAINT).width(Fill),
        text("ARCHNEMIX  /  AI LAB").size(11).color(style::FAINT)
    ];

    column![heading, space().height(32), hero, space().height(38), categories, space().height(48), footer]
        .spacing(0)
        .padding(40)
        .width(Fill)
        .into()
}

fn destination(
    number: &'static str,
    title: &'static str,
    description: &'static str,
    status: &'static str,
) -> Element<'static, Message> {
    container(
        column![
            text(number).size(12).color(style::FAINT),
            space().height(24),
            text(title).size(19).color(style::TEXT),
            space().height(9),
            text(description).size(13).color(style::MUTED),
            space().height(33),
            text(status).size(10).color(style::FAINT)
        ]
        .width(Fill)
    )
    .padding(22)
    .width(FillPortion(1))
    .style(style::panel)
    .into()
}

fn about() -> Element<'static, Message> {
    column![
        text("ABOUT THE LAB").size(11).color(style::MUTED),
        space().height(20),
        text("A home for what's next.").size(38).color(style::TEXT),
        space().height(20),
        text("Archx AI Lab is an Archnemix workspace for AI tools and experiences.")
            .size(16)
            .color(style::MUTED),
        space().height(48),
        container(
            column![
                text("THIS IS THE BEGINNING").size(11).color(style::FAINT),
                space().height(18),
                text("The launcher is here first. Archx Agent, model training, fine-tuning, and observation will arrive as each area is built and tested.")
                    .size(17)
                    .color(style::TEXT)
            ]
            .width(Fill)
        )
        .padding(30)
        .width(Fill)
        .style(style::panel)
    ]
    .padding(40)
    .width(Fill)
    .into()
}
