//! Purpose: Starts the native Archx AI Lab launcher, which discovers apps from `apps/*/app.toml`, without a console on Windows release builds.
#![cfg_attr(all(target_os = "windows", not(debug_assertions)), windows_subsystem = "windows")]

mod app;
mod navigation;
mod transition;

/// Which apps this build publishes.
///
/// This line is the release switch. An app whose crate is listed here is compiled
/// into the binary and appears on Discover; an app whose crate is missing is held
/// out of this release — its folder can be worked on, and it is reported in
/// launcher settings, but it gets no tile. Adding an app is one `register` line
/// plus one workspace member; holding one is deleting the line. See
/// `apps/archx-agent/docs/Plan/Adding_An_App.md` §7.
pub fn release() -> archx_shared::apps::Builder {
    archx_shared::apps::Builder::new()
        .register("archx-agent")
}

/// The harness projection, for `ARCHX_SNAPSHOT_APPS=<id>` runs only.
///
/// It marks one app as present in *this run* so it can be rendered and judged
/// while it is still held out of the release. It is never persisted, never
/// written to a manifest, and does nothing at all unless the environment says so
/// — the release boundary stays exactly where `release()` puts it.
pub fn projection(apps: &mut [archx_shared::apps::App]) {
    let Ok(id) = std::env::var("ARCHX_SNAPSHOT_APPS") else { return };
    let id = id.trim();
    if id.is_empty() { return; }
    for app in apps.iter_mut() {
        if app.id == id { app.built = true; }
    }
}

use iced::{Font, Theme, window};

fn brand_icon() -> window::Icon {
    window::icon::from_file_data(
        include_bytes!("../shared/assets/brand/archnemix-icon.png"),
        None,
    )
    .expect("Bundled brand icon must decode")
}

fn main() -> iced::Result {
    let application = iced::application(app::App::new, app::App::update, app::App::view)
        .title("Archx AI Lab")
        .window(window::Settings {
            size: if std::env::var_os("ARCHX_SNAPSHOT").is_some()
                && std::env::var("ARCHX_SNAPSHOT_SIZE").as_deref() == Ok("wide") {
                (1568.0, 856.0).into()
            } else { (1280.0, 800.0).into() },
            icon: Some(brand_icon()),
            ..window::Settings::default()
        })
        .subscription(app::App::subscription)
        .theme(|_: &app::App| Theme::Dark)
        .font(include_bytes!("../shared/assets/fonts/Manrope.ttf").as_slice());

    // Registering a second font family distorted glyph advances on the macOS
    // runner. Keep that OS on the already-validated Manrope family until the
    // renderer issue can be isolated without compromising the Agent visual.
    #[cfg(not(target_os = "macos"))]
    let application = application
        .font(include_bytes!("../shared/assets/fonts/SpaceGrotesk-Medium.ttf").as_slice())
        .font(include_bytes!("../shared/assets/fonts/SpaceGrotesk-SemiBold.ttf").as_slice());

    application.default_font(Font::with_name("Manrope")).run()
}
