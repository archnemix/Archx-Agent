//! Purpose: Starts the native Archx AI Lab GUI without a console in Windows release builds.
#![cfg_attr(all(target_os = "windows", not(debug_assertions)), windows_subsystem = "windows")]

mod app;
mod app_tile;
mod home;
mod style;

use iced::{Font, Theme};

fn main() -> iced::Result {
    iced::application(app::App::new, app::App::update, app::App::view)
        .title("Archx AI Lab")
        .window_size((1280.0, 800.0))
        .subscription(app::App::subscription)
        .theme(|_: &app::App| Theme::Dark)
        .font(include_bytes!("../assets/fonts/Manrope.ttf").as_slice())
        .default_font(Font::with_name("Manrope"))
        .run()
}
