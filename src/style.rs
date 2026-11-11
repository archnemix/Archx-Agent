//! Purpose: Provides the black-and-silver palette and restrained launcher widget styles.
use iced::widget::{button, container};
use iced::{Border, Color, Theme};

pub const BLACK: Color = Color::from_rgb8(8, 8, 8);
pub const RAIL: Color = Color::from_rgb8(13, 13, 13);
pub const SURFACE: Color = Color::from_rgb8(20, 20, 20);
pub const RAISED: Color = Color::from_rgb8(32, 32, 32);
pub const LINE: Color = Color::from_rgb8(51, 51, 51);
pub const WHITE: Color = Color::from_rgb8(244, 244, 244);
pub const GREY: Color = Color::from_rgb8(178, 178, 178);
pub const DIM: Color = Color::from_rgb8(117, 117, 117);

pub fn canvas(_: &Theme) -> container::Style {
    container::Style::default().background(BLACK)
}

pub fn rail(_: &Theme) -> container::Style {
    container::Style::default().background(RAIL)
}

pub fn surface(_: &Theme) -> container::Style {
    container::Style::default()
        .background(SURFACE)
        .border(Border {
            color: LINE,
            width: 1.0,
            radius: 15.0.into(),
        })
}

pub fn cover(_: &Theme) -> container::Style {
    container::Style::default()
        .background(RAISED)
        .border(Border {
            color: LINE,
            width: 1.0,
            radius: 10.0.into(),
        })
}

pub fn brand_mark(_: &Theme) -> container::Style {
    container::Style::default().background(WHITE).border(Border {
        color: WHITE,
        width: 0.0,
        radius: 6.0.into(),
    })
}

pub fn badge(_: &Theme) -> container::Style {
    container::Style::default()
        .background(Color::from_rgb8(44, 44, 44))
        .border(Border {
            color: Color::from_rgb8(70, 70, 70),
            width: 1.0,
            radius: 6.0.into(),
        })
}

pub fn nav(active: bool, _theme: &Theme, status: button::Status) -> button::Style {
    let base = if active {
        Color::from_rgba(0.26, 0.26, 0.26, 0.74)
    } else if matches!(status, button::Status::Hovered) {
        Color::from_rgb8(29, 29, 29)
    } else {
        RAIL
    };
    button::Style {
        background: Some(base.into()),
        text_color: if active { WHITE } else { GREY },
        border: Border {
            color: if active { Color::from_rgb8(79, 79, 79) } else { base },
            width: if active { 1.0 } else { 0.0 },
            radius: 9.0.into(),
        },
        ..button::Style::default()
    }
}
