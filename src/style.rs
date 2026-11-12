//! Purpose: Provides the black-and-silver palette and restrained launcher widget styles.
use iced::widget::{button, container, text_input};
use iced::{font, gradient, Background, Border, Color, Font, Radians, Shadow, Theme, Vector};

pub const BLACK: Color = Color::from_rgb8(8, 8, 8);
pub const RAIL: Color = Color::from_rgb8(13, 13, 13);
pub const SURFACE: Color = Color::from_rgb8(20, 20, 20);
pub const LINE: Color = Color::from_rgb8(51, 51, 51);
pub const WHITE: Color = Color::from_rgb8(244, 244, 244);
pub const GREY: Color = Color::from_rgb8(178, 178, 178);
pub const DIM: Color = Color::from_rgb8(145, 145, 145);

// Type roles and spacing are specified once in Docs/design.md and reused by views.
#[cfg(not(target_os = "macos"))]
pub const DISPLAY: Font = Font {
    family: font::Family::Name("Space Grotesk"),
    weight: font::Weight::Medium,
    ..Font::DEFAULT
};
#[cfg(not(target_os = "macos"))]
pub const DISPLAY_BOLD: Font = Font {
    family: font::Family::Name("Space Grotesk"),
    weight: font::Weight::Semibold,
    ..Font::DEFAULT
};
#[cfg(not(target_os = "macos"))]
pub const LABEL: Font = Font {
    family: font::Family::Name("Manrope"),
    weight: font::Weight::Medium,
    ..Font::DEFAULT
};

// Explicit non-Normal weights for the variable Manrope caused macOS glyph
// advances to overlap across the entire window, even for unmodified Agent.
// Keep its existing default font while retaining the size-based hierarchy.
#[cfg(target_os = "macos")]
pub const DISPLAY: Font = Font::with_name("Manrope");
#[cfg(target_os = "macos")]
pub const DISPLAY_BOLD: Font = Font::with_name("Manrope");
#[cfg(target_os = "macos")]
pub const LABEL: Font = Font::with_name("Manrope");
pub const TYPE_LABEL: f32 = 11.0;
pub const TYPE_BODY: f32 = 14.0;
pub const TYPE_SECTION: f32 = 24.0;
pub const TYPE_PAGE: f32 = 38.0;
pub const SPACE_1: f32 = 8.0;
pub const SPACE_2: f32 = 16.0;
pub const SPACE_3: f32 = 24.0;
pub const SPACE_4: f32 = 36.0;

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

pub fn agent_surface(_: &Theme) -> container::Style {
    container::Style::default()
        .background(
            gradient::Linear::new(Radians::PI)
                .add_stop(0.0, Color::from_rgb8(25, 25, 27))
                .add_stop(1.0, Color::from_rgb8(11, 11, 12)),
        )
        .border(Border {
            color: LINE,
            width: 1.0,
            radius: 10.0.into(),
        })
}

pub fn mode_marker(_: &Theme, active: bool) -> container::Style {
    container::Style::default().background(if active { WHITE } else { LINE })
}

pub fn workbench_surface(_: &Theme, tuning: bool) -> container::Style {
    let start = if tuning { Color::from_rgb8(26, 26, 28) } else { Color::from_rgb8(24, 27, 29) };
    container::Style::default()
        .background(
            gradient::Linear::new(Radians::PI)
                .add_stop(0.0, start)
                .add_stop(1.0, Color::from_rgb8(12, 12, 13)),
        )
        .border(Border {
            color: LINE,
            width: 1.0,
            radius: 10.0.into(),
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

pub fn disabled_composer(_: &Theme, _: text_input::Status) -> text_input::Style {
    text_input::Style {
        background: Background::Color(Color::from_rgb8(28, 28, 30)),
        border: Border {
            color: Color::from_rgb8(65, 65, 68),
            width: 1.0,
            radius: 8.0.into(),
        },
        icon: GREY,
        placeholder: GREY,
        value: GREY,
        selection: LINE,
    }
}

pub fn quiet_button(_: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if matches!(status, button::Status::Hovered) {
            Color::from_rgb8(56, 56, 59)
        } else {
            Color::from_rgb8(36, 36, 38)
        }.into()),
        text_color: WHITE,
        border: Border {
            color: Color::from_rgb8(76, 76, 80),
            width: 1.0,
            radius: 8.0.into(),
        },
        ..button::Style::default()
    }
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

    #[test]
    fn model_labs_use_native_gradient_and_selective_display_weight() {
        assert!(matches!(workbench_surface(&Theme::Dark, false).background, Some(Background::Gradient(_))));
        assert!(matches!(workbench_surface(&Theme::Dark, true).background, Some(Background::Gradient(_))));
        #[cfg(not(target_os = "macos"))]
        {
            assert_eq!(DISPLAY.weight, font::Weight::Medium);
            assert_eq!(DISPLAY_BOLD.weight, font::Weight::Semibold);
        }
        #[cfg(target_os = "macos")]
        {
            assert_eq!(DISPLAY.weight, font::Weight::Normal);
            assert_eq!(DISPLAY_BOLD.weight, font::Weight::Normal);
            assert_eq!(LABEL.weight, font::Weight::Normal);
        }
    }
}
