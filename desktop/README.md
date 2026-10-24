# OSINT Graph desktop (Tauri v2)

A Windows desktop wrapper: a Tauri window plus the Python backend running as a sidecar exe (built with PyInstaller). The backend also serves the React UI.

## Prerequisites
- Rust (stable MSVC) and Visual Studio C++ build tools
- WebView2 runtime (already part of Windows 11)
- Node 20+ and npm
- Python 3.12 on PATH. The build creates its own venv in `build-cache/venv` from `backend/requirements.txt`, so every runtime dependency the backend needs **must be listed there**.

## Build
```powershell
powershell -ExecutionPolicy Bypass -File desktop\build.ps1
```
This runs `npm ci && npm run build` in `frontend/`, then `python desktop/build-backend.py` (which writes the sidecar to `src-tauri/binaries/osint-backend-x86_64-pc-windows-msvc.exe`), then `npx tauri build`. The installers end up in:
- `src-tauri/target/release/bundle/nsis/OSINT Graph_0.1.0_x64-setup.exe`
- `src-tauri/target/release/bundle/msi/OSINT Graph_0.1.0_x64_en-US.msi`

### Temporary shim (remove once backend has the CLI)
`build-backend.py` freezes `backend/app.py` (which has the `--port`/`--data-dir` flags, `/api/health`, and the frozen `_MEIPASS/frontend/dist` UI lookup).
```powershell
powershell -ExecutionPolicy Bypass -File desktop\build.ps1 --entry desktop\backend-entry-shim.py
```
Run `build.ps1` with no extra args to build the installer.

The portable app exe is `src-tauri/target/release/osint-graph.exe`. It expects the sidecar `osint-backend.exe` in the same folder, which the installer puts there.

## Dev
```powershell
cd desktop; npm ci; npx tauri dev
```
Debug builds don't use the sidecar. They run `python ../backend/app.py --port <p> --data-dir <appdata>` with whatever `python` is on PATH, so the backend's deps have to be installed there. `frontend/dist` must already be built because the backend serves it.

## How it works
- On startup the app picks a free 127.0.0.1 port and starts the backend with `--port <p> --data-dir %APPDATA%\com.osintgraph.app`, which puts the DB at `osint.db` in that folder. It shows `splash/index.html` while it polls `GET /api/health`, then navigates to `http://127.0.0.1:<p>/`. If the backend isn't healthy within 30 s, the splash shows the last lines of the backend's output instead.
- The backend is placed in a Windows Job Object with KILL_ON_JOB_CLOSE. It is killed when the app exits, and also if the app crashes.
- Only one instance runs at a time; launching the app again focuses the existing window.
- There are no capability files, so no page gets Tauri IPC permissions. That includes the remote `127.0.0.1` page.
- To change the icon, edit `app-icon.svg` and run `npx tauri icon app-icon.svg -o src-tauri/icons`.
