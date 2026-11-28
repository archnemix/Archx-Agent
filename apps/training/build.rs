// Purpose: Embeds the Archnemix icon and product metadata into the standalone Windows `archx-training.exe` binary.

#[cfg(windows)]
fn main() {
    let manifest_dir = std::path::PathBuf::from(
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR set by Cargo"),
    );
    let icon_path = manifest_dir.join("../../shared/assets/brand/archnemix.ico");
    println!("cargo:rerun-if-changed={}", icon_path.display());

    tauri_winres::WindowsResource::new()
        .set_icon(icon_path.to_str().expect("valid UTF-8 icon path"))
        .set("CompanyName", "Archnemix")
        .set("ProductName", "Archx AI Lab - Model Training")
        .set(
            "FileDescription",
            "Archx Model Training standalone native studio",
        )
        .compile()
        .expect("Embed Windows icon and product metadata for archx-training");
}

#[cfg(not(windows))]
fn main() {}
