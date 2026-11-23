//! Purpose: Provides the black-and-silver palette and restrained launcher widget styles.
use iced::widget::{button, container, text_editor, text_input};
use iced::{font, gradient, Background, Border, Color, Font, Radians, Shadow, Theme, Vector};

pub const BLACK: Color = Color::from_rgb8(0, 0, 0);
pub const RAIL: Color = Color::from_rgb8(11, 11, 11);
pub const SURFACE: Color = Color::from_rgb8(20, 20, 20);
pub const LINE: Color = Color::from_rgb8(51, 51, 51);
pub const WHITE: Color = Color::from_rgb8(244, 244, 244);
pub const GREY: Color = Color::from_rgb8(178, 178, 178);
pub const DIM: Color = Color::from_rgb8(145, 145, 145);
pub const SUCCESS: Color = Color::from_rgb8(126, 207, 150);
pub const FAILURE: Color = Color::from_rgb8(226, 139, 139);
// Measured 1.9.0 dark-theme tokens (public/css/base.css) for the Agent chat
// chrome: surfaces lift one step above pure black so panel edges stay readable.
pub const PANEL: Color = Color::from_rgb8(0x10, 0x10, 0x10);
pub const PANEL_2: Color = Color::from_rgb8(0x1a, 0x1a, 0x1a);
pub const PANEL_3: Color = Color::from_rgb8(0x23, 0x23, 0x23);
pub const BORDER: Color = Color::from_rgb8(0x2c, 0x2c, 0x2c);
pub const BORDER_2: Color = Color::from_rgb8(0x40, 0x40, 0x40);
pub const USER_BUBBLE: Color = Color::from_rgb8(0x16, 0x16, 0x16);
pub const MUTED_2: Color = Color::from_rgb8(0x5c, 0x5c, 0x5c);
pub const OK: Color = Color::from_rgb8(0x22, 0xc5, 0x5e);

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
#[cfg(not(target_os = "macos"))]
pub const STRONG: Font = Font {
    family: font::Family::Name("Manrope"),
    weight: font::Weight::Bold,
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
#[cfg(target_os = "macos")]
pub const STRONG: Font = Font::with_name("Manrope");
// Agent reference's 4px-based layout rhythm (UI-RULES §2). Keep semantic
// steps centralized: closely related controls 8/12, groups 16/20/24.
pub const AGENT_GAP_TIGHT: f32 = 4.0;
pub const AGENT_GAP_CONTROL: f32 = 8.0;
pub const AGENT_GAP_GROUP: f32 = 16.0;
pub const AGENT_GAP_SECTION: f32 = 24.0;
pub const AGENT_BODY_SIZE: f32 = 15.0;
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

pub fn rail_divider(_: &Theme) -> container::Style {
    container::Style::default().background(LINE)
}

pub fn settings_panel(_: &Theme) -> container::Style {
    container::Style::default().background(Color::from_rgb8(15, 15, 16))
        .border(Border { color: LINE, width: 1.0, radius: 0.0.into() })
}

pub fn rail_hint(_: &Theme) -> container::Style {
    container::Style::default().background(Color::from_rgb8(34, 34, 36))
        .border(Border { color: Color::from_rgb8(82, 82, 86), width: 1.0, radius: 8.0.into() })
}

// Compact buttons are fixed 52px squares: silver selection, no full-width pill.
pub fn compact_nav(selected: bool, _: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if selected { Color::from_rgb8(47, 47, 50) }
            else if matches!(status, button::Status::Hovered | button::Status::Pressed) { Color::from_rgb8(31, 31, 33) }
            else { RAIL }.into()),
        text_color: if selected { WHITE } else { GREY },
        border: Border {
            color: Color::from_rgba(0.0, 0.0, 0.0, 0.0),
            width: 1.0,
            radius: 14.0.into(),
        },
        shadow: if selected { Shadow { color: Color::from_rgba(0.75, 0.75, 0.82, 0.12), offset: Vector::new(0.0, 2.0), blur_radius: 8.0 } }
            else { Shadow::default() },
        ..button::Style::default()
    }
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

pub fn composer_input(_: &Theme, status: text_input::Status) -> text_input::Style {
    text_input::Style {
        background: Background::Color(Color::from_rgb8(28, 28, 30)),
        border: Border {
            color: if matches!(status, text_input::Status::Focused { .. }) {
                Color::from_rgb8(130, 130, 135)
            } else {
                Color::from_rgb8(65, 65, 68)
            },
            width: 1.0,
            radius: 8.0.into(),
        },
        icon: GREY,
        placeholder: GREY,
        value: WHITE,
        selection: LINE,
    }
}

pub fn quiet_button(_: &Theme, status: button::Status) -> button::Style {
    let disabled = matches!(status, button::Status::Disabled);
    button::Style {
        background: Some(if disabled {
            Color::from_rgb8(22, 22, 23)
        } else if matches!(status, button::Status::Hovered) {
            Color::from_rgb8(56, 56, 59)
        } else {
            Color::from_rgb8(36, 36, 38)
        }.into()),
        text_color: if disabled { DIM } else { WHITE },
        border: Border {
            color: if disabled { LINE } else { Color::from_rgb8(76, 76, 80) },
            width: 1.0,
            radius: 8.0.into(),
        },
        ..button::Style::default()
    }
}

// Rail affordance is deliberately quieter than navigation selection and stays
// at the same bottom edge in both widths.
pub fn rail_toggle(_: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            Color::from_rgb8(33, 33, 35)
        } else {
            RAIL
        }.into()),
        text_color: GREY,
        border: Border { color: LINE, width: 1.0, radius: 8.0.into() },
        ..button::Style::default()
    }
}

pub fn nav(active: bool, _theme: &Theme, status: button::Status) -> button::Style {
    if active {
        let glass = gradient::Linear::new(Radians::PI)
            .add_stop(0.0, Color::from_rgb8(20, 20, 22))
            .add_stop(0.60, Color::from_rgb8(31, 31, 33))
            .add_stop(1.0, Color::from_rgb8(85, 85, 91));

        button::Style {
            background: Some(glass.into()),
            text_color: WHITE,
            border: Border {
                color: Color::from_rgba(0.0, 0.0, 0.0, 0.0),
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
    fn compact_selection_is_a_bounded_silver_tile_not_an_expanded_pill() {
        let active = compact_nav(true, &Theme::Dark, button::Status::Active);
        let inactive = compact_nav(false, &Theme::Dark, button::Status::Active);
        assert!(matches!(active.background, Some(Background::Color(_))));
        assert_eq!(active.border.radius, 14.0.into());
        assert_eq!(active.border.color.a, inactive.border.color.a);
    }

    #[test]
    fn chat_canvas_is_true_black() {
        assert_eq!(BLACK, Color::from_rgb8(0, 0, 0));
        assert_eq!(canvas(&Theme::Dark).background, Some(Background::Color(BLACK)));
    }

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

// Chat uses the restrained website reference's flat black, one modest user
// bubble, and a single raised model menu/composer rather than card-per-turn UI.
pub fn chat_panel(_: &Theme) -> container::Style {
    container::Style::default().background(Color::from_rgb8(16, 16, 16))
        .border(Border { color: Color::from_rgb8(64, 64, 64), width: 1.0, radius: 16.0.into() })
}
pub fn chat_user(_: &Theme) -> container::Style {
    // 1.9.0 chat.css .msg.user .msg-content: bubble with a tighter top-left
    // corner (4px) and 12px elsewhere, #161616 fill on a #2c2c2c hairline.
    container::Style::default().background(USER_BUBBLE)
        .border(Border {
            color: BORDER,
            width: 1.0,
            radius: iced::border::Radius { top_left: 4.0, top_right: 12.0, bottom_right: 12.0, bottom_left: 12.0 },
        })
}
pub fn chat_thinking(_: &Theme) -> container::Style {
    let mut style = container::Style::default().background(Color::from_rgb8(12, 12, 12))
        .border(Border { color: Color::from_rgb8(43, 43, 43), width: 1.0, radius: 9.0.into() });
    style.text_color = Some(GREY);
    style
}
pub fn chat_avatar(assistant: bool, _: &Theme) -> container::Style {
    container::Style::default().background(if assistant { WHITE } else { Color::from_rgb8(26, 26, 26) })
        .border(Border { color: if assistant { WHITE } else { LINE }, width: 1.0, radius: 8.0.into() })
}
pub fn settings_header(_: &Theme) -> container::Style {
    container::Style::default().background(BLACK)
        .border(Border { color: LINE, width: 1.0, radius: 0.0.into() })
}

// Iced's default TextEditor paints a solid gray rectangle; the reference
// composer is a single #101010 surface with an unboxed typing region.
pub fn chat_editor(_: &Theme, _: text_editor::Status) -> text_editor::Style {
    text_editor::Style {
        background: Background::Color(Color::from_rgb8(16, 16, 16)),
        border: Border::default(),
        placeholder: GREY,
        value: WHITE,
        selection: LINE,
    }
}

pub fn chat_error(_: &Theme) -> container::Style {
    container::Style::default().background(Color::from_rgb8(37, 17, 18))
        .border(Border { color: Color::from_rgb8(108, 46, 46), width: 1.0, radius: 9.0.into() })
}

pub fn chat_code_header(_: &Theme) -> container::Style {
    container::Style::default().background(Color::from_rgb8(23, 23, 23))
        .border(Border { color: Color::from_rgb8(44, 44, 44), width: 1.0, radius: 0.0.into() })
}

// Provider choices must read as controls, not loose gray words in a wide grid.
pub fn provider_choice(active: bool, _: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if active { Color::from_rgb8(43, 43, 43) }
            else if matches!(status, button::Status::Hovered | button::Status::Pressed) { Color::from_rgb8(27, 27, 27) }
            else { Color::from_rgb8(17, 17, 17) }.into()),
        text_color: if active { WHITE } else { GREY },
        border: Border { color: if active { Color::from_rgb8(71, 71, 71) } else { Color::from_rgb8(35, 35, 35) },
            width: 1.0, radius: 8.0.into() },
        ..button::Style::default()
    }
}

/// Dim the inactive settings page behind the Agent's model-import dialog.
pub fn catalog_scrim(_: &Theme, _: button::Status) -> button::Style {
    button::Style {
        background: Some(Color::from_rgba(0.0, 0.0, 0.0, 0.78).into()),
        ..button::Style::default()
    }
}

/// White, compact send affordance from the supplied 1.9.0 Chat compositor.
pub fn chat_send(_: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if matches!(status, button::Status::Disabled) {
            Color::from_rgba(0.96, 0.96, 0.96, 0.4)
        } else { WHITE }.into()),
        text_color: BLACK,
        border: Border { radius: 11.0.into(), ..Border::default() },
        ..button::Style::default()
    }
}

// ── 1.9.0 component tokens (components.css / pages.css / chat.css) ─────────
// Buttons follow .btn: 12px radius, #2c2c2c hairline, #101010 fill; the single
// primary action per view is white (`.btn.primary`) with black ink.

/// `.btn` default: quiet bordered control on the panel surface.
pub fn control_button(_: &Theme, status: button::Status) -> button::Style {
    let disabled = matches!(status, button::Status::Disabled);
    button::Style {
        background: Some(if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            PANEL_2
        } else {
            PANEL
        }.into()),
        text_color: if disabled { DIM } else { WHITE },
        border: Border {
            color: if matches!(status, button::Status::Hovered | button::Status::Pressed) { BORDER_2 } else { BORDER },
            width: 1.0,
            radius: 12.0.into(),
        },
        ..button::Style::default()
    }
}

/// `.btn.primary`: exactly one per view — white fill, black ink.
pub fn primary_button(_: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if matches!(status, button::Status::Disabled) {
            Color::from_rgba(0.96, 0.96, 0.96, 0.45)
        } else if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            Color::from_rgb8(0xd9, 0xd9, 0xd9)
        } else {
            WHITE
        }.into()),
        text_color: BLACK,
        border: Border { color: WHITE, width: 1.0, radius: 12.0.into() },
        ..button::Style::default()
    }
}

/// `.btn.ghost`: transparent until hover, used for secondary actions.
pub fn ghost_button(_: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            PANEL_2
        } else {
            Color::TRANSPARENT
        }.into()),
        text_color: if matches!(status, button::Status::Disabled) { DIM } else { GREY },
        border: Border { color: Color::TRANSPARENT, width: 1.0, radius: 12.0.into() },
        ..button::Style::default()
    }
}

/// `.btn.tiny`: 7px radius row action from the reference toolbars.
pub fn tiny_button(_: &Theme, status: button::Status) -> button::Style {
    let disabled = matches!(status, button::Status::Disabled);
    button::Style {
        background: Some(if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            PANEL_2
        } else {
            Color::TRANSPARENT
        }.into()),
        text_color: if disabled { DIM } else { GREY },
        border: Border {
            color: if matches!(status, button::Status::Hovered | button::Status::Pressed) { BORDER_2 } else { BORDER },
            width: 1.0,
            radius: 7.0.into(),
        },
        ..button::Style::default()
    }
}

/// `.page-nav-btn` / `.set-nav-btn`: compact rows with a quiet active state.
pub fn side_nav(active: bool, _: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if active {
            PANEL
        } else if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            PANEL
        } else {
            Color::TRANSPARENT
        }.into()),
        text_color: if active { WHITE } else if matches!(status, button::Status::Hovered | button::Status::Pressed) { WHITE } else { GREY },
        border: Border {
            color: if active { BORDER } else { Color::TRANSPARENT },
            width: 1.0,
            radius: 12.0.into(),
        },
        ..button::Style::default()
    }
}

/// `.model-btn` / topbar selectors: bordered pills on the panel surface.
pub fn topbar_pill(_: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if matches!(status, button::Status::Hovered | button::Status::Pressed) { PANEL_2 } else { PANEL }.into()),
        text_color: WHITE,
        border: Border {
            color: if matches!(status, button::Status::Hovered | button::Status::Pressed) { BORDER_2 } else { BORDER },
            width: 1.0,
            radius: 12.0.into(),
        },
        ..button::Style::default()
    }
}

/// `.mini-toggle`: pill switch — outlined when off, white when on.
pub fn mini_toggle(on: bool, _: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if on {
            WHITE
        } else if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            PANEL_2
        } else {
            Color::TRANSPARENT
        }.into()),
        text_color: if on { BLACK } else if matches!(status, button::Status::Hovered) { WHITE } else { GREY },
        border: Border {
            color: if on { WHITE } else if matches!(status, button::Status::Hovered) { BORDER_2 } else { BORDER },
            width: 1.0,
            radius: 20.0.into(),
        },
        ..button::Style::default()
    }
}

/// `.chat-item` / `.model-import-row`: transparent list rows, 8px radius.
pub fn list_row(selected: bool, _: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if selected {
            PANEL
        } else if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            PANEL_2
        } else {
            Color::TRANSPARENT
        }.into()),
        text_color: if selected { WHITE } else { GREY },
        border: Border {
            color: if selected { BORDER } else { Color::TRANSPARENT },
            width: 1.0,
            radius: 8.0.into(),
        },
        ..button::Style::default()
    }
}

/// `.modal-card`: panel surface, lifted hairline, soft drop shadow.
pub fn modal_card(_: &Theme) -> container::Style {
    container::Style::default()
        .background(PANEL)
        .border(Border { color: BORDER_2, width: 1.0, radius: 18.0.into() })
        .shadow(Shadow {
            color: Color::from_rgba(0.0, 0.0, 0.0, 0.6),
            offset: Vector::new(0.0, 12.0),
            blur_radius: 40.0,
        })
}

/// `.jump-latest` pill: raised rounded control above the composer.
pub fn jump_pill(_: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(PANEL.into()),
        text_color: WHITE,
        border: Border {
            color: if matches!(status, button::Status::Hovered | button::Status::Pressed) { WHITE } else { BORDER_2 },
            width: 1.0,
            radius: 16.0.into(),
        },
        shadow: Shadow {
            color: Color::from_rgba(0.0, 0.0, 0.0, 0.4),
            offset: Vector::new(0.0, 4.0),
            blur_radius: 14.0,
        },
        ..button::Style::default()
    }
}

/// `.endpoint-badge`: quiet status chip with a colored dot in the rail footer.
pub fn endpoint_badge(_: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(Color::TRANSPARENT.into()),
        text_color: if matches!(status, button::Status::Hovered | button::Status::Pressed) { WHITE } else { GREY },
        border: Border {
            color: if matches!(status, button::Status::Hovered | button::Status::Pressed) { BORDER_2 } else { BORDER },
            width: 1.0,
            radius: 12.0.into(),
        },
        ..button::Style::default()
    }
}

/// 7px `.conn-state` dot: muted until a model is actually selected.
pub fn status_dot(connected: bool, _: &Theme) -> container::Style {
    container::Style::default()
        .background(if connected { OK } else { MUTED_2 })
        .border(Border { radius: 6.0.into(), ..Border::default() })
}

/// Import-dialog checkbox (17px): white fill when checked, hairline when not.
pub fn checkbox(checked: bool, _: &Theme) -> container::Style {
    container::Style::default()
        .background(if checked { WHITE } else { Color::TRANSPARENT })
        .border(Border {
            color: if checked { WHITE } else { BORDER_2 },
            width: 1.0,
            radius: 4.0.into(),
        })
}

/// Small outlined status pill (`.free`, `✓ works`, `✗ HTTP 429`) on list rows.
pub fn tag_badge(ok: Option<bool>, _: &Theme) -> container::Style {
    let color = match ok {
        Some(true) => OK,
        Some(false) => FAILURE,
        None => BORDER_2,
    };
    container::Style::default()
        .background(Color::TRANSPARENT)
        .border(Border { color, width: 1.0, radius: 999.0.into() })
}

/// `.panel`-filled card with the softer `--border` hairline (settings pages).
pub fn card(_: &Theme) -> container::Style {
    container::Style::default()
        .background(PANEL)
        .border(Border { color: BORDER, width: 1.0, radius: 16.0.into() })
}

/// Import-row status dot: muted before a probe, green/red after one.
pub fn probe_dot(ok: Option<bool>, _: &Theme) -> container::Style {
    let color = match ok {
        Some(true) => OK,
        Some(false) => FAILURE,
        None => MUTED_2,
    };
    container::Style::default()
        .background(color)
        .border(Border { radius: 6.0.into(), ..Border::default() })
}

#[cfg(test)]
mod reference_token_tests {
    use super::*;
    use iced::Background;

    #[test]
    fn chat_tokens_match_the_190_dark_theme() {
        assert_eq!(PANEL, Color::from_rgb8(0x10, 0x10, 0x10));
        assert_eq!(BORDER, Color::from_rgb8(0x2c, 0x2c, 0x2c));
        assert_eq!(BORDER_2, Color::from_rgb8(0x40, 0x40, 0x40));
        assert_eq!(USER_BUBBLE, Color::from_rgb8(0x16, 0x16, 0x16));
    }

    #[test]
    fn user_bubble_keeps_the_asymmetric_reference_corners() {
        let style = chat_user(&Theme::Dark);
        assert_eq!(style.background, Some(Background::Color(USER_BUBBLE)));
        assert_eq!(style.border.color, BORDER);
        assert_eq!(style.border.radius.top_left, 4.0);
        assert_eq!(style.border.radius.top_right, 12.0);
        assert_eq!(style.border.radius.bottom_right, 12.0);
        assert_eq!(style.border.radius.bottom_left, 12.0);
    }

    #[test]
    fn one_primary_action_is_white_with_black_ink() {
        let primary = primary_button(&Theme::Dark, button::Status::Active);
        assert_eq!(primary.background, Some(Background::Color(WHITE)));
        assert_eq!(primary.text_color, BLACK);
        let disabled = primary_button(&Theme::Dark, button::Status::Disabled);
        assert!(disabled.background.is_some());
        assert_ne!(disabled.background, primary.background);
    }

    #[test]
    fn ghost_and_default_controls_stay_quieter_than_primary() {
        let ghost = ghost_button(&Theme::Dark, button::Status::Active);
        assert_eq!(ghost.background, Some(Background::Color(Color::TRANSPARENT)));
        let control = control_button(&Theme::Dark, button::Status::Active);
        assert_eq!(control.background, Some(Background::Color(PANEL)));
        assert_ne!(control.text_color, BLACK);
    }

    #[test]
    fn mini_toggle_is_white_only_while_on() {
        let on = mini_toggle(true, &Theme::Dark, button::Status::Active);
        let off = mini_toggle(false, &Theme::Dark, button::Status::Active);
        assert_eq!(on.background, Some(Background::Color(WHITE)));
        assert_eq!(on.text_color, BLACK);
        assert_eq!(off.background, Some(Background::Color(Color::TRANSPARENT)));
    }

    #[test]
    fn checkbox_and_status_dot_track_their_state() {
        assert_eq!(checkbox(true, &Theme::Dark).background, Some(Background::Color(WHITE)));
        assert_eq!(checkbox(false, &Theme::Dark).background, Some(Background::Color(Color::TRANSPARENT)));
        assert_eq!(status_dot(true, &Theme::Dark).background, Some(Background::Color(OK)));
        assert_eq!(status_dot(false, &Theme::Dark).background, Some(Background::Color(MUTED_2)));
        assert_eq!(probe_dot(Some(true), &Theme::Dark).background, Some(Background::Color(OK)));
        assert_eq!(probe_dot(Some(false), &Theme::Dark).background, Some(Background::Color(FAILURE)));
        assert_eq!(probe_dot(None, &Theme::Dark).background, Some(Background::Color(MUTED_2)));
    }

    #[test]
    fn settings_cards_use_the_softer_border_step() {
        let card = card(&Theme::Dark);
        assert_eq!(card.background, Some(Background::Color(PANEL)));
        assert_eq!(card.border.color, BORDER);
        assert_eq!(card.border.radius.top_left, 16.0);
    }

    #[test]
    fn modal_card_lifts_the_surface_like_the_reference_shadow() {
        let card = modal_card(&Theme::Dark);
        assert_eq!(card.background, Some(Background::Color(PANEL)));
        assert_eq!(card.border.color, BORDER_2);
        assert_eq!(card.border.radius.top_left, 18.0);
        assert!(card.shadow.blur_radius >= 30.0);
    }
}
