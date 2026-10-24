"""Freeze backend/app.py (plus frontend/dist) into the Tauri sidecar exe.

    python desktop/build-backend.py [--entry path/to/entry.py]

Uses an isolated venv in desktop/build-cache/venv built from backend/requirements.txt, so only
declared backend deps are bundled. Output: desktop/src-tauri/binaries/osint-backend-x86_64-pc-windows-msvc.exe
"""
import argparse, os, shutil, subprocess, sys, venv
from pathlib import Path

DESKTOP = Path(__file__).resolve().parent
ROOT = DESKTOP.parent
BACKEND = ROOT / "backend"
DIST = ROOT / "frontend" / "dist"
GEV = ROOT / "gev"  # bundled God's Eye View static build, served at /gev
CACHE = DESKTOP / "build-cache"
VENV = CACHE / "venv"
PY = VENV / "Scripts" / "python.exe"
NAME = "osint-backend-x86_64-pc-windows-msvc"  # Tauri externalBin naming: <name>-<target triple>
PYINSTALLER = "pyinstaller==6.22.3"


def run(*cmd):
    print(">", *cmd, flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", type=Path, default=BACKEND / "app.py")
    entry = ap.parse_args().entry.resolve()

    if not (DIST / "index.html").is_file():
        sys.exit(f"{DIST} missing: build the frontend first (cd frontend && npm run build)")

    if not PY.exists():
        venv.create(VENV, with_pip=True)
    # pip retries: PyPI can be slow here.
    run(PY, "-m", "pip", "install", "--retries", "10", "--timeout", "60", "-q",
        "-r", BACKEND / "requirements.txt", PYINSTALLER)

    work = CACHE / "pyinstaller"
    shutil.rmtree(work, ignore_errors=True)
    mods = sorted(p.stem for p in BACKEND.glob("*.py") if not p.stem.startswith("test_"))
    run(PY, "-m", "PyInstaller", entry,
        "--name", NAME, "--onefile", "--noconsole", "--noupx", "--clean", "--noconfirm",
        "--distpath", DESKTOP / "src-tauri" / "binaries",
        "--workpath", work, "--specpath", work,
        "--paths", BACKEND,
        "--add-data", f"{DIST}{os.pathsep}frontend/dist",
        *(["--add-data", f"{GEV}{os.pathsep}gev"] if (GEV / "index.html").is_file() else []),
        "--collect-submodules", "uvicorn",  # uvicorn picks loops/protocols/lifespan by string at runtime
        *[a for m in mods for a in ("--hidden-import", m)],
        "--exclude-module", "tkinter")
    out = DESKTOP / "src-tauri" / "binaries" / f"{NAME}.exe"
    print(f"sidecar: {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
