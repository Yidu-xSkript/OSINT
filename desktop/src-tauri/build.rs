fn main() {
    // Dev builds run the backend with python (see lib.rs), but tauri-build still insists the
    // externalBin exists. Drop an empty placeholder in debug only; release must have the real one.
    let sidecar = "binaries/osint-backend-x86_64-pc-windows-msvc.exe";
    if std::env::var("PROFILE").as_deref() == Ok("debug") && !std::path::Path::new(sidecar).exists() {
        std::fs::create_dir_all("binaries").unwrap();
        std::fs::write(sidecar, b"").unwrap();
    }
    tauri_build::build()
}
