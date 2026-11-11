//! Purpose: Provides the black-and-silver palette and restrained launcher widget styles.
use iced::widget::{button, container};
use iced::{gradient, Border, Color, Radians, Shadow, Theme, Vector};

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
    if active {
        let glass = gradient::Linear::new(Radians::PI)
            .add_stop(0.0, Color::from_rgb8(21, 21, 22))
            .add_stop(0.58, Color::from_rgb8(31, 31, 33))
            .add_stop(1.0, Color::from_rgb8(70, 70, 74));

        button::Style {
            background: Some(glass.into()),
            text_color: WHITE,
            border: Border {
                color: Color::from_rgb8(94, 94, 98),
                width: 1.0,
                radius: 17.0.into(),
            },
            shadow: Shadow {
                color: Color::from_rgba(0.65, 0.65, 0.7, 0.14),
                offset: Vector::new(0.0, 2.0),
                blur_radius: 8.0,
            },
            ..button::Style::default()
        }
    } else {
        button::Style {
            background: Some(if matches!(status, button::Status::Hovered) {
                Color::from_rgb8(30, 30, 32)
            } else {
                RAIL
            }.into()),
            text_color: GREY,
            border: Border { radius: 17.0.into(), ..Border::default() },
            ..button::Style::default()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use iced::Background;

    #[test]
    fn selected_navigation_uses_glass_gradient() {
        let selected = nav(true, &Theme::Dark, button::Status::Active);
        assert!(matches!(selected.background, Some(Background::Gradient(_))));
        assert!(selected.shadow.blur_radius > 0.0);
    }
}
