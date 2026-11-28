//! Purpose: Launches Archx Training Studio as a standalone native Windows/Linux/macOS desktop GUI executable (`archx-training.exe` / `archx-training`), without any terminal console window on Windows release builds.
#![cfg_attr(all(target_os = "windows", not(debug_assertions)), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::time::Duration;

use iced::{Element, Font, Subscription, Task, Theme, time, window};

use archx_training::app::{App as TrainingApp, Message as TrainingMessage};

#[derive(Debug, Clone)]
enum ShellMsg {
    Training(TrainingMessage),
    SnapshotTick,
    SnapshotReady(window::Screenshot),
}

struct StandaloneShell {
    inner: TrainingApp,
    snapshot_path: Option<PathBuf>,
    snapshot_requested: bool,
}

impl StandaloneShell {
    fn boot() -> (Self, Task<ShellMsg>) {
        let snapshot_path = std::env::var_os("ARCHX_SNAPSHOT").map(PathBuf::from);
        let mut inner = TrainingApp::new(None);

        if snapshot_path.is_some() {
            let surface = std::env::var("ARCHX_TRAINING_SURFACE")
                .unwrap_or_else(|_| "pipeline".to_owned());
            inner.prepare_snapshot(&surface);
        }

        (
            Self {
                inner,
                snapshot_path,
                snapshot_requested: false,
            },
            Task::none(),
        )
    }

    fn update(&mut self, msg: ShellMsg) -> Task<ShellMsg> {
        match msg {
            ShellMsg::Training(tmsg) => {
                let task = self.inner.update(tmsg).map(ShellMsg::Training);
                if self.inner.left_for_launcher {
                    self.inner.left_for_launcher = false;
                    self.inner.banner = Some((
                        true,
                        "Running standalone Archx Training Studio desktop build.".to_owned(),
                    ));
                }
                task
            }
            ShellMsg::SnapshotTick => {
                if !self.snapshot_requested {
                    self.snapshot_requested = true;
                    return window::latest()
                        .and_then(window::screenshot)
                        .map(ShellMsg::SnapshotReady);
                }
                Task::none()
            }
            ShellMsg::SnapshotReady(screenshot) => {
                if let Some(path) = &self.snapshot_path {
                    if let Some(parent) = path.parent() {
                        let _ = std::fs::create_dir_all(parent);
                    }
                    let _ = image::save_buffer(
                        path,
                        &screenshot.rgba,
                        screenshot.size.width,
                        screenshot.size.height,
                        image::ColorType::Rgba8,
                    );
                    return window::latest().and_then(window::close);
                }
                Task::none()
            }
        }
    }

    fn view(&self) -> Element<'_, ShellMsg> {
        self.inner.view().map(ShellMsg::Training)
    }

    fn subscription(&self) -> Subscription<ShellMsg> {
        let inner_sub = self.inner.subscription().map(ShellMsg::Training);
        let snap_sub = if self.snapshot_path.is_some() {
            time::every(Duration::from_millis(750)).map(|_| ShellMsg::SnapshotTick)
        } else {
            Subscription::none()
        };
        Subscription::batch([inner_sub, snap_sub])
    }
}

fn brand_icon() -> window::Icon {
    window::icon::from_file_data(
        include_bytes!("../../../../shared/assets/brand/archnemix-icon.png"),
        None,
    )
    .expect("Bundled Archnemix brand icon must decode")
}

fn main() -> iced::Result {
    let wide = std::env::var_os("ARCHX_SNAPSHOT").is_some()
        && std::env::var("ARCHX_SNAPSHOT_SIZE").as_deref() == Ok("wide");

    let application = iced::application(
        StandaloneShell::boot,
        StandaloneShell::update,
        StandaloneShell::view,
    )
    .title("Archx Training Studio")
    .window(window::Settings {
        size: if wide {
            (1568.0, 856.0).into()
        } else {
            (1360.0, 840.0).into()
        },
        icon: Some(brand_icon()),
        ..window::Settings::default()
    })
    .subscription(StandaloneShell::subscription)
    .theme(|_: &StandaloneShell| Theme::Dark)
    .font(include_bytes!("../../../../shared/assets/fonts/Manrope.ttf").as_slice());

    #[cfg(not(target_os = "macos"))]
    let application = application
        .font(include_bytes!("../../../../shared/assets/fonts/SpaceGrotesk-Medium.ttf").as_slice())
        .font(include_bytes!("../../../../shared/assets/fonts/SpaceGrotesk-SemiBold.ttf").as_slice());

    application.default_font(Font::with_name("Manrope")).run()
}
