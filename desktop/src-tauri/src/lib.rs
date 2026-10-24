use std::collections::VecDeque;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, Url};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const STDERR_LINES: usize = 40;

struct Backend(Mutex<Option<CommandChild>>);

fn free_port() -> u16 {
    // ponytail: tiny race between drop and the backend's bind; fine on a single-user desktop.
    TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port()
}

fn healthy(port: u16) -> bool {
    let Ok(mut s) = TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_millis(500)) else {
        return false;
    };
    let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
    let req = format!("GET /api/health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n");
    let mut resp = String::new();
    s.write_all(req.as_bytes()).is_ok()
        && s.read_to_string(&mut resp).is_ok()
        && resp.split_whitespace().nth(1) == Some("200")
}

/// Puts the backend in a kill-on-close job object. The job handle is deliberately leaked, so when this
/// process exits for any reason (including a crash) Windows kills the backend and its children
/// (the PyInstaller one-file bootloader spawns the real python as a grandchild).
#[cfg(windows)]
fn tie_to_our_lifetime(pid: u32) {
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::*;
    use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE};
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const _,
            std::mem::size_of_val(&info) as u32,
        );
        let proc = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
        if !proc.is_null() {
            AssignProcessToJobObject(job, proc);
            CloseHandle(proc);
        }
    }
}

fn show_error(app: &tauri::AppHandle, msg: &str, tail: &str) {
    if let Some(w) = app.get_webview_window("main") {
        let js = format!(
            "document.getElementById('msg').textContent={};var p=document.createElement('pre');p.textContent={};document.getElementById('msg').appendChild(p);",
            serde_json::to_string(msg).unwrap(),
            serde_json::to_string(tail).unwrap()
        );
        let _ = w.eval(&js);
    }
}

fn start_backend(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let port = free_port();
    let data_dir = app.path().app_data_dir()?;
    std::fs::create_dir_all(&data_dir)?;
    let args = [
        "--port".to_string(),
        port.to_string(),
        "--data-dir".to_string(),
        data_dir.to_string_lossy().into_owned(),
    ];

    // Dev runs the backend straight from source so `tauri dev` works without building the sidecar.
    let cmd = if cfg!(debug_assertions) {
        let script = concat!(env!("CARGO_MANIFEST_DIR"), "/../../backend/app.py");
        app.shell().command("python").arg(script).args(args)
    } else {
        app.shell().sidecar("osint-backend")?.args(args)
    };
    let (mut rx, child) = cmd.spawn()?;
    #[cfg(windows)]
    tie_to_our_lifetime(child.pid());
    app.state::<Backend>().0.lock().unwrap().replace(child);

    let tail = Arc::new(Mutex::new(VecDeque::new()));
    let exited = Arc::new(AtomicBool::new(false));
    {
        let (tail, exited) = (tail.clone(), exited.clone());
        tauri::async_runtime::spawn(async move {
            while let Some(ev) = rx.recv().await {
                let line = match ev {
                    CommandEvent::Stderr(b) | CommandEvent::Stdout(b) => String::from_utf8_lossy(&b).trim_end().to_string(),
                    CommandEvent::Error(e) => e,
                    CommandEvent::Terminated(t) => {
                        exited.store(true, Ordering::SeqCst);
                        format!("[backend exited: code {:?}]", t.code)
                    }
                    _ => continue,
                };
                let mut t = tail.lock().unwrap();
                t.push_back(line);
                if t.len() > STDERR_LINES {
                    t.pop_front();
                }
            }
        });
    }

    let app = app.clone();
    std::thread::spawn(move || {
        let start = Instant::now();
        while start.elapsed() < STARTUP_TIMEOUT && !exited.load(Ordering::SeqCst) {
            if healthy(port) {
                let url = Url::parse(&format!("http://127.0.0.1:{port}/")).unwrap();
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.navigate(url);
                }
                return;
            }
            std::thread::sleep(Duration::from_millis(200));
        }
        std::thread::sleep(Duration::from_millis(300)); // let the last stderr lines arrive
        let tail = tail.lock().unwrap().iter().cloned().collect::<Vec<_>>().join("\n");
        show_error(&app, "The OSINT Graph backend failed to start.", &tail);
    });
    Ok(())
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            if let Err(e) = start_backend(app.handle()) {
                show_error(app.handle(), "Could not launch the OSINT Graph backend.", &e.to_string());
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            if let Some(child) = app.state::<Backend>().0.lock().unwrap().take() {
                let _ = child.kill();
            }
        }
    });
}
