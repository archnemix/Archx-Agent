//! Purpose: Defines the restrained graphite palette and native widget styles for the home shell.
use iced::widget::{button, container};
use iced::{Border, Color, Theme};

pub const CANVAS: Color = Color::from_rgb(0.063, 0.067, 0.075);
pub const SURFACE: Color = Color::from_rgb(0.099, 0.104, 0.116);
pub const RAISED: Color = Color::from_rgb(0.137, 0.145, 0.158);
pub const SELECTED: Color = Color::from_rgb(0.188, 0.199, 0.211);
pub const LINE: Color = Color::from_rgb(0.222, 0.231, 0.244);
pub const TEXT: Color = Color::from_rgb(0.953, 0.953, 0.941);
pub const MUTED: Color = Color::from_rgb(0.690, 0.702, 0.716);
pub const FAINT: Color = Color::from_rgb(0.490, 0.506, 0.525);

fn border(radius: f32) -> Border {
    Border {
        color: LINE,
        width: 1.0,
        radius: radius.into(),
    }
}

pub fn canvas(_: &Theme) -> container::Style {
    container::Style::default().background(CANVAS)
}

pub fn sidebar(_: &Theme) -> container::Style {
    container::Style::default().background(SURFACE)
}

pub fn panel(_: &Theme) -> container::Style {
    container::Style::default()
        .background(SURFACE)
        .border(border(16.0))
}

pub fn elevated(_: &Theme) -> container::Style {
    container::Style::default()
        .background(RAISED)
        .border(border(16.0))
}

pub fn selection(_: &Theme) -> container::Style {
    container::Style::default()
        .background(SELECTED)
        .border(border(12.0))
}

pub fn nav(active: bool, _theme: &Theme, status: button::Status) -> button::Style {
    let color = if active { SELECTED } else { SURFACE };
    let background = if matches!(status, button::Status::Hovered) {
        RAISED
    } else {
        color
    };
    button::Style {
        background: Some(background.into()),
        text_color: if active { TEXT } else { MUTED },
        border: Border { radius: 10.0.into(), ..Border::default() },
        ..button::Style::default()
    }
}
