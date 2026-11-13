//! Purpose: Starts the native Archx AI Lab GUI without a console in Windows release builds.
#![cfg_attr(all(target_os = "windows", not(debug_assertions)), windows_subsystem = "windows")]

mod agent;
mod agent_visual;
mod app;
mod app_tile;
mod credentials;
mod home;
mod provider_api;
mod settings;
mod style;

use iced::{window, Font, Theme};

fn brand_icon() -> window::Icon {
    window::icon::from_file_data(
        include_bytes!("../assets/brand/archnemix-icon.png"),
        None,
    )
    .expect("Bundled brand icon must decode")
}

fn main() -> iced::Result {
    let application = iced::application(app::App::new, app::App::update, app::App::view)
        .title("Archx AI Lab")
        .window(window::Settings {
            size: (1280.0, 800.0).into(),
            icon: Some(brand_icon()),
            ..window::Settings::default()
        })
        .subscription(app::App::subscription)
        .theme(|_: &app::App| Theme::Dark)
        .font(include_bytes!("../assets/fonts/Manrope.ttf").as_slice());

    // Registering a second font family distorted glyph advances on the macOS
    // runner. Keep that OS on the already-validated Manrope family until the
    // renderer issue can be isolated without compromising the Agent visual.
    #[cfg(not(target_os = "macos"))]
    let application = application
        .font(include_bytes!("../assets/fonts/SpaceGrotesk-Medium.ttf").as_slice())
        .font(include_bytes!("../assets/fonts/SpaceGrotesk-SemiBold.ttf").as_slice());

    application.default_font(Font::with_name("Manrope")).run()
}
