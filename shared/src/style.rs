//! Purpose: Provides the black-and-silver palette and restrained launcher widget styles.
use iced::widget::{button, container, scrollable, text_editor, text_input};
use iced::{font, gradient, Background, Border, Color, Font, Radians, Shadow, Theme, Vector};

// Colors are copied verbatim from the 1.9.0 reference `base.css` dark theme —
// same screen, same values, no invented shades. `ACCENT` (#ffffff) is for
// fills; `TEXT` (#f4f4f4) is for type.
pub const BLACK: Color = Color::from_rgb8(0, 0, 0);
pub const BG_2: Color = Color::from_rgb8(0x0b, 0x0b, 0x0b);
pub const CODE_BG: Color = Color::from_rgb8(0x0c, 0x0c, 0x0c);
pub const RAIL: Color = BG_2;
pub const SURFACE: Color = Color::from_rgb8(0x10, 0x10, 0x10);
pub const LINE: Color = Color::from_rgb8(0x2c, 0x2c, 0x2c);
pub const WHITE: Color = Color::from_rgb8(0xf4, 0xf4, 0xf4);
pub const ACCENT: Color = Color::from_rgb8(0xff, 0xff, 0xff);
pub const TEXT_2: Color = Color::from_rgb8(0xd4, 0xd4, 0xd4);
pub const GREY: Color = Color::from_rgb8(0x8a, 0x8a, 0x8a);
pub const DIM: Color = GREY;
pub const SUCCESS: Color = Color::from_rgb8(0x22, 0xc5, 0x5e);
pub const FAILURE: Color = Color::from_rgb8(0xef, 0x44, 0x44);
// Measured 1.9.0 dark-theme tokens (public/css/base.css) for the Agent chat
// chrome: surfaces lift one step above pure black so panel edges stay readable.
pub const PANEL: Color = Color::from_rgb8(0x10, 0x10, 0x10);
pub const PANEL_2: Color = Color::from_rgb8(0x1a, 0x1a, 0x1a);
pub const PANEL_3: Color = Color::from_rgb8(0x23, 0x23, 0x23);
pub const BORDER: Color = Color::from_rgb8(0x2c, 0x2c, 0x2c);
pub const BORDER_2: Color = Color::from_rgb8(0x40, 0x40, 0x40);
pub const USER_BUBBLE: Color = Color::from_rgb8(0x16, 0x16, 0x16);
pub const MUTED: Color = Color::from_rgb8(0x8a, 0x8a, 0x8a);
pub const MUTED_2: Color = Color::from_rgb8(0x5c, 0x5c, 0x5c);
pub const OK: Color = Color::from_rgb8(0x22, 0xc5, 0x5e);
pub const DANGER: Color = Color::from_rgb8(0xef, 0x44, 0x44);
pub const WARN: Color = Color::from_rgb8(0xea, 0xb3, 0x08);

/// `--danger-soft: rgba(239, 68, 68, .12)` from the reference token table.
pub fn danger_soft() -> Color {
    Color::from_rgba(239.0 / 255.0, 68.0 / 255.0, 68.0 / 255.0, 0.12)
}

/// `color-mix(in srgb, var(--danger) 45%, transparent)` border tint.
pub fn danger_border() -> Color {
    Color::from_rgba(239.0 / 255.0, 68.0 / 255.0, 68.0 / 255.0, 0.45)
}

/// `color-mix(in srgb, var(--accent) 10%, transparent)` selection fill.
pub fn accent_wash() -> Color {
    Color::from_rgba(1.0, 1.0, 1.0, 0.10)
}

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
    container::Style::default().background(BG_2)
        .border(Border { color: LINE, width: 1.0, radius: 0.0.into() })
}

pub fn rail_hint(_: &Theme) -> container::Style {
    container::Style::default().background(PANEL_2)
        .border(Border { color: BORDER_2, width: 1.0, radius: 8.0.into() })
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
    // Reference `.system-prompt-glyph`: transparent 19px tile on a border-2
    // hairline with 6px corners.
    container::Style::default()
        .background(Color::TRANSPARENT)
        .border(Border {
            color: BORDER_2,
            width: 1.0,
            radius: 6.0.into(),
        })
}

pub fn composer_input(_: &Theme, status: text_input::Status) -> text_input::Style {
    // Reference inputs: `--bg-2` field on a `--border` hairline; focus turns
    // the hairline `--accent`.
    text_input::Style {
        background: Background::Color(BG_2),
        border: Border {
            color: if matches!(status, text_input::Status::Focused { .. }) {
                ACCENT
            } else {
                BORDER
            },
            width: 1.0,
            radius: 12.0.into(),
        },
        icon: GREY,
        placeholder: GREY,
        value: WHITE,
        selection: BORDER,
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
    // chat.css `.thinking`: dashed --border-2 hairline over `accent 3%` wash
    // (Iced has no dashed borders; the solid hairline is the closest match).
    let mut style = container::Style::default()
        .background(Color::from_rgba(1.0, 1.0, 1.0, 0.03))
        .border(Border { color: BORDER_2, width: 1.0, radius: 12.0.into() });
    style.text_color = Some(GREY);
    style
}
/// `.thinking-body`'s `border-top: 1px dashed`. Iced draws no dashed borders,
/// so the divider is a single hairline on the body's top edge only; the body
/// itself stays transparent inside the panel's rounded frame.
pub fn chat_thinking_body(_: &Theme) -> container::Style {
    container::Style::default()
        .background(Color::TRANSPARENT)
        .border(Border { color: BORDER_2, width: 1.0, radius: 0.0.into() })
}

/// `reference_token_tests` pins the values above to `public/css/chat.css`.
#[cfg(test)]
mod thinking_tests {
    use super::*;

    #[test]
    fn reasoning_panel_matches_the_reference_frame_and_wash() {
        let panel = chat_thinking(&iced::Theme::Dark);
        // `.thinking { border: 1px dashed var(--border-2); background: accent 3% }`
        assert_eq!(panel.border.width, 1.0);
        assert_eq!(panel.border.color, BORDER_2);
        assert_eq!(panel.background, Some(iced::Background::Color(Color::from_rgba(1.0, 1.0, 1.0, 0.03))));
    }

    #[test]
    fn reasoning_body_is_a_top_hairline_only() {
        let body = chat_thinking_body(&iced::Theme::Dark);
        assert_eq!(body.border.width, 1.0);
        assert_eq!(body.border.color, BORDER_2);
        assert_eq!(body.border.radius, 0.0.into());
        assert_eq!(body.background, Some(iced::Background::Color(Color::TRANSPARENT)));
    }
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
    container::Style::default().background(danger_soft())
        .border(Border { color: danger_border(), width: 1.0, radius: 12.0.into() })
}

pub fn chat_code_header(_: &Theme) -> container::Style {
    container::Style::default().background(PANEL)
        .border(Border { color: BORDER, width: 1.0, radius: 0.0.into() })
}

// Provider choices follow `.model-opt`: quiet rows; the selected row takes the
// reference's `accent 10%` wash — never a solid white fill.
pub fn provider_choice(active: bool, _: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if active { accent_wash() }
            else if matches!(status, button::Status::Hovered | button::Status::Pressed) { PANEL_2 }
            else { Color::TRANSPARENT }.into()),
        text_color: if active { WHITE } else { GREY },
        border: Border { color: if active { BORDER_2 } else { Color::TRANSPARENT },
            width: 1.0, radius: 8.0.into() },
        ..button::Style::default()
    }
}

/// Dim the inactive settings page behind the Agent's model-import dialog
/// (`.modal` overlay: `rgba(0, 0, 0, .55)`).
pub fn catalog_scrim(_: &Theme, _: button::Status) -> button::Style {
    button::Style {
        background: Some(Color::from_rgba(0.0, 0.0, 0.0, 0.55).into()),
        ..button::Style::default()
    }
}

/// White, compact send affordance from the supplied 1.9.0 Chat compositor.
/// The web app never disables this button — it always paints `--accent`.
pub fn chat_send(_: &Theme, _status: button::Status) -> button::Style {
    button::Style {
        background: Some(ACCENT.into()),
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

/// `.btn.primary`: exactly one per view — `--accent` fill, black ink.
pub fn primary_button(_: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if matches!(status, button::Status::Disabled) {
            Color::from_rgba(1.0, 1.0, 1.0, 0.5)
        } else if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            // `.btn.primary:hover { filter: brightness(.92) }`
            Color::from_rgb8(0xeb, 0xeb, 0xeb)
        } else {
            ACCENT
        }.into()),
        text_color: BLACK,
        border: Border { color: ACCENT, width: 1.0, radius: 12.0.into() },
        ..button::Style::default()
    }
}

/// `.btn.ghost`: transparent until hover, used for secondary actions.
/// Reference button text is `--text` (#f4f4f4) even on ghosts.
pub fn ghost_button(_: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            PANEL_2
        } else {
            Color::TRANSPARENT
        }.into()),
        text_color: if matches!(status, button::Status::Disabled) { GREY } else { WHITE },
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
        text_color: if disabled { GREY } else { WHITE },
        border: Border {
            color: if matches!(status, button::Status::Hovered | button::Status::Pressed) { BORDER_2 } else { BORDER },
            width: 1.0,
            radius: 7.0.into(),
        },
        ..button::Style::default()
    }
}

/// `.set-nav-btn`: transparent rows; active takes the panel fill plus the
/// reference's inset 2px `--accent` left bar (drawn by the widget row).
pub fn sub_nav(active: bool, _: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if active
            || matches!(status, button::Status::Hovered | button::Status::Pressed) {
            PANEL
        } else {
            Color::TRANSPARENT
        }.into()),
        text_color: if active { WHITE } else if matches!(status, button::Status::Hovered | button::Status::Pressed) { WHITE } else { GREY },
        border: Border { color: Color::TRANSPARENT, width: 1.0, radius: 12.0.into() },
        ..button::Style::default()
    }
}

/// Reference switch track (import dialog's "Add only verified models"):
/// `--accent` when on, `--muted-2` when off.
pub fn switch_track(on: bool, _: &Theme, _: button::Status) -> button::Style {
    button::Style {
        background: Some((if on { ACCENT } else { MUTED_2 }).into()),
        text_color: BLACK,
        border: Border { radius: 999.0.into(), ..Border::default() },
        ..button::Style::default()
    }
}

/// Switch knob: black on the accent track, text-white on the muted track.
pub fn switch_knob(on: bool, _: &Theme) -> container::Style {
    container::Style::default()
        .background(if on { BLACK } else { WHITE })
        .border(Border { radius: 999.0.into(), ..Border::default() })
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

/// `.mini-toggle`: pill switch — outlined when off, `--accent` when on.
pub fn mini_toggle(on: bool, _: &Theme, status: button::Status) -> button::Style {
    button::Style {
        background: Some(if on {
            ACCENT
        } else if matches!(status, button::Status::Hovered | button::Status::Pressed) {
            PANEL_2
        } else {
            Color::TRANSPARENT
        }.into()),
        text_color: if on { BLACK } else if matches!(status, button::Status::Hovered) { TEXT_2 } else { GREY },
        border: Border {
            color: if on { ACCENT } else if matches!(status, button::Status::Hovered) { BORDER_2 } else { BORDER },
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

/// Import-dialog checkbox (17px): `--accent` fill when checked, hairline when not.
pub fn checkbox(checked: bool, _: &Theme) -> container::Style {
    container::Style::default()
        .background(if checked { ACCENT } else { Color::TRANSPARENT })
        .border(Border {
            color: if checked { ACCENT } else { BORDER_2 },
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

/// Import-row status dot. The reference only greens passing dots
/// (`.model-import-row.passed .model-row-dot`); failed and unprobed rows keep
/// the quiet `--muted-2` dot, and the failure detail lives in the red pill.
pub fn probe_dot(ok: Option<bool>, _: &Theme) -> container::Style {
    let color = match ok {
        Some(true) => OK,
        Some(false) | None => MUTED_2,
    };
    container::Style::default()
        .background(color)
        .border(Border { radius: 6.0.into(), ..Border::default() })
}

/// Scrollbars: the reference browser paints overlay-thin dark bars; Iced's
/// default theme scrollbar (#5d626d grey column) must never appear.
pub fn quiet_scroll(_: &Theme, _: scrollable::Status) -> scrollable::Style {
    let rail = scrollable::Rail {
        background: None,
        border: Border::default(),
        scroller: scrollable::Scroller {
            background: Background::Color(BORDER),
            border: Border { radius: 4.0.into(), ..Border::default() },
        },
    };
    scrollable::Style {
        container: container::Style::default(),
        vertical_rail: rail,
        horizontal_rail: rail,
        gap: None,
        auto_scroll: scrollable::AutoScroll {
            background: Background::Color(PANEL),
            border: Border { radius: 8.0.into(), ..Border::default() },
            shadow: Shadow::default(),
            icon: WHITE,
        },
    }
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
        assert_eq!(primary.background, Some(Background::Color(ACCENT)));
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
        assert_eq!(on.background, Some(Background::Color(ACCENT)));
        assert_eq!(on.text_color, BLACK);
        assert_eq!(off.background, Some(Background::Color(Color::TRANSPARENT)));
    }

    #[test]
    fn checkbox_and_status_dot_track_their_state() {
        assert_eq!(checkbox(true, &Theme::Dark).background, Some(Background::Color(ACCENT)));
        assert_eq!(checkbox(false, &Theme::Dark).background, Some(Background::Color(Color::TRANSPARENT)));
        assert_eq!(status_dot(true, &Theme::Dark).background, Some(Background::Color(OK)));
        assert_eq!(status_dot(false, &Theme::Dark).background, Some(Background::Color(MUTED_2)));
        assert_eq!(probe_dot(Some(true), &Theme::Dark).background, Some(Background::Color(OK)));
        // Failed rows keep the quiet dot; the red pill carries the failure.
        assert_eq!(probe_dot(Some(false), &Theme::Dark).background, Some(Background::Color(MUTED_2)));
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
    fn palette_is_the_reference_table_with_no_invented_greys() {
        assert_eq!(LINE, Color::from_rgb8(0x2c, 0x2c, 0x2c));
        assert_eq!(GREY, Color::from_rgb8(0x8a, 0x8a, 0x8a));
        assert_eq!(DIM, GREY);
        assert_eq!(SURFACE, PANEL);
        assert_eq!(RAIL, BG_2);
        assert_eq!(FAILURE, DANGER);
        assert_eq!(SUCCESS, OK);
    }

    #[test]
    fn modal_scrim_matches_the_reference_overlay() {
        let scrim = catalog_scrim(&Theme::Dark, button::Status::Active);
        assert_eq!(scrim.background, Some(Background::Color(Color::from_rgba(0.0, 0.0, 0.0, 0.55))));
    }

    #[test]
    fn ghost_buttons_use_reference_text_and_send_stays_accent() {
        let ghost = ghost_button(&Theme::Dark, button::Status::Active);
        assert_eq!(ghost.text_color, WHITE);
        let send = chat_send(&Theme::Dark, button::Status::Disabled);
        assert_eq!(send.background, Some(Background::Color(ACCENT)));
    }

    #[test]
    fn model_selection_is_an_accent_wash_not_a_white_fill() {
        let sel = provider_choice(true, &Theme::Dark, button::Status::Active);
        assert_eq!(sel.background, Some(Background::Color(accent_wash())));
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
