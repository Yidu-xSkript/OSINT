"""Tool registry — the one place that reports which investigative tools are usable, under a single contract.

States:
  built-in            ships with the app, always ready (native adapters)
  available           an external tool was detected and is a compatible version
  needs-setup         an external tool is not installed / not found
  unsupported-version detected, but older than the minimum this adapter supports
  error               detected, but its health check failed

Each external tool may be pointed at an explicit executable via a setting (e.g. nmap.path), which wins over
PATH discovery. Detection shells out only with an argument array, a timeout, and no window — never a shell
string. Nmap is marked `scoped`: callers must gather an explicit target scope + authorization before running
it (enforced by the scan adapter, not here).
"""
import os
import re
import shutil
import subprocess

# Native adapters that ship in the app.
NATIVE = [
    {"id": "quick-username", "label": "Quick Username Search", "transforms": ["username-search"],
     "detail": "Bundled check across ~20 public sites. Candidates only — install Sherlock for full coverage."},
]

# External tools we detect and drive (never bundle, for size/licensing reasons).
EXTERNAL = [
    {"id": "sherlock", "label": "Sherlock — full username search", "cmd": "sherlock",
     "path_setting": "sherlock.path", "version_args": ["--version"], "version_re": r"(\d+\.\d+(?:\.\d+)?)",
     "install": "pip install sherlock-project",
     "detail": "400+ sites. Optional — Quick Username Search already works without it."},
    {"id": "theharvester", "label": "theHarvester — domain intelligence", "cmd": "theHarvester",
     "alt_cmds": ["theharvester", "theHarvester.py"], "path_setting": "theharvester.path",
     "version_args": ["--version"], "version_re": r"(\d+\.\d+(?:\.\d+)?)", "min_version": (4, 0),
     "install": "pipx install theHarvester (needs a recent Python 3)",
     "detail": "Emails, subdomains, IPs and hosts for a domain, from public sources."},
    {"id": "nmap", "label": "Nmap — authorized scanning", "cmd": "nmap",
     "path_setting": "nmap.path", "version_args": ["--version"], "version_re": r"version (\d+\.\d+)",
     "min_version": (7, 0), "scoped": True,
     "install": "Install from nmap.org (not bundled — Npcap/redistribution licensing)",
     "detail": "Port/service discovery. Requires an explicit target scope + authorization; never auto-scans."},
]


def _resolve(tool, settings):
    override = settings.get(tool.get("path_setting", ""))
    if override:
        return override if os.path.isfile(override) else None
    for name in [tool["cmd"], *tool.get("alt_cmds", [])]:
        found = shutil.which(name)
        if found:
            return found
    return None


def _detect_version(path, tool):
    try:
        out = subprocess.run([path, *tool.get("version_args", ["--version"])], capture_output=True, text=True,
                             timeout=12, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return None, "error"
    m = re.search(tool.get("version_re", r"(\d+\.\d+(?:\.\d+)?)"), (out.stdout or "") + (out.stderr or ""))
    return (m.group(1) if m else None), None


def _ge(version, minimum):
    try:
        parts = tuple(int(x) for x in version.split(".")[: len(minimum)])
        return parts >= minimum
    except Exception:
        return True  # unknown format → don't block


def _external_health(tool, settings):
    path = _resolve(tool, settings)
    if not path:
        return {"state": "needs-setup", "version": None, "path": None}
    version, err = _detect_version(path, tool)
    if err == "error":
        return {"state": "error", "version": None, "path": path}
    minimum = tool.get("min_version")
    if minimum and version and not _ge(version, minimum):
        return {"state": "unsupported-version", "version": version, "path": path}
    return {"state": "available", "version": version, "path": path}


def resolve_path(tool_id, settings):
    """The executable path for an external tool (explicit setting or PATH), or None if not found."""
    t = next((x for x in EXTERNAL if x["id"] == tool_id), None)
    return _resolve(t, settings) if t else None


def registry(settings):
    """Health of every tool, for GET /api/tools. Settings supplies optional explicit executable paths."""
    out = []
    for t in NATIVE:
        out.append({"id": t["id"], "label": t["label"], "kind": "native", "state": "built-in",
                    "version": None, "transforms": t.get("transforms", []), "scoped": False,
                    "detail": t["detail"], "install": None})
    for t in EXTERNAL:
        h = _external_health(t, settings)
        out.append({"id": t["id"], "label": t["label"], "kind": "external", "state": h["state"],
                    "version": h["version"], "transforms": [], "scoped": bool(t.get("scoped")),
                    "detail": t["detail"], "install": t.get("install")})
    return out
