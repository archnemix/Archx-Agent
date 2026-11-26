// Purpose: Embed the Archnemix icon and truthful company metadata in Windows executables.
//
// The icon lives in `shared/assets/` with the rest of the brand files; pointing at
// the old root `assets/` folder is what broke the Windows build.
#[cfg(windows)]
fn main() {
    tauri_winres::WindowsResource::new()
        .set_icon("shared/assets/brand/archnemix.ico")
        .set("CompanyName", "Archnemix")
        .set("ProductName", "Archx AI Lab")
        .set("FileDescription", "Archx AI Lab desktop launcher")
        .compile()
        .expect("Embed Windows icon and product metadata");
}

#[cfg(not(windows))]
fn main() {}
