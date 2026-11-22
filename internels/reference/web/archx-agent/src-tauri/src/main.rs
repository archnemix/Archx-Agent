// Archx Agent desktop shell (Tauri 2).
// The app itself is the local Node server (this npm package). The shell
// spawns `archx-agent webui` and points the webview at it — a real desktop
// window instead of a browser tab. Requires the package installed globally
// (npm i -g archx-agent) so `archx-agent` resolves on PATH.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::Manager;

struct ServerChild(Mutex<Option<Child>>);

fn spawn_server() -> Option<Child> {
    // global install first, then npx fallback
    if let Ok(c) = Command::new("archx-agent").arg("webui").spawn() {
        return Some(c);
    }
    Command::new("npx").args(["archx-agent", "webui"]).spawn().ok()
}

fn main() {
    tauri::Builder::default()
        .manage(ServerChild(Mutex::new(None)))
        .setup(|app| {
            if let Some(child) = spawn_server() {
                *app.state::<ServerChild>().0.lock().unwrap() = Some(child);
            }
            let window = app.get_webview_window("main").unwrap();
            std::thread::spawn(move || {
                // give the node server a moment to bind its port
                for _ in 0..40 {
                    std::thread::sleep(std::time::Duration::from_millis(250));
                    if std::net::TcpStream::connect("127.0.0.1:4173").is_ok() {
                        break;
                    }
                }
                let _ = window.navigate(tauri::Url::parse("http://127.0.0.1:4173").unwrap());
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.try_state::<ServerChild>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
