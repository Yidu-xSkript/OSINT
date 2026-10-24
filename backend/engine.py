"""Transform execution: built-in (in-process), local (sandboxed subprocess), remote (HTTP, Maltego TRX protocol)."""
import os, re, subprocess, time, urllib.error, urllib.parse, urllib.request

import builtin
from builtin import BUILTINS, UA
import connectors  # noqa: F401 -- registers BYO-key data-source transforms into BUILTINS on import
import phone  # noqa: F401 -- registers phone-number OSINT transforms
import geo  # noqa: F401 -- registers geospatial / God's Eye View transforms
import chrono  # noqa: F401 -- registers temporal / chronolocation transforms
import recon  # noqa: F401 -- registers native recon transforms (Quick Username Search)
import harvester  # noqa: F401 -- registers the theHarvester adapter
from maltego_xml import TransformError, build_request, local_args, parse_response

# Local transforms get a scrubbed environment: no server env vars / secrets leak unless declared.
SAFE_ENV = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG")
MAX_OUTPUT = 20_000_000
LOOPBACK = ("localhost", "127.0.0.1", "::1")


def public(t):
    return {k: v for k, v in t.items() if k != "fn"}


def _prop(name, value):
    return {"name": name, "value": value, "displayName": name}


def run(t, entity, all_settings, limit=256):
    """-> (results, messages, evidence); results use parse_response() shape, evidence is the raw responses seen."""
    settings = {k: all_settings[k] for k in t.get("settings", []) if k in all_settings}
    builtin._rec.items = []  # capture every HTTP response fetch() makes during this run
    try:
        if t["kind"] == "builtin":
            results = [{"type": typ, "value": str(val), "icon": None, "notes": None,
                        "properties": {k: _prop(k, v) for k, v in (extra[0] if extra else {}).items()},
                        "link": {"label": label, "reverse": False}}
                       for typ, val, label, *extra in t["fn"](entity["value"], entity["properties"], settings)]
            messages = []
        elif t["kind"] == "local":
            raw = run_local(t, entity, settings)
            results, messages = parse_response(raw)
            _record_raw(f"local:{t['command']}", raw)
        elif t["kind"] == "remote":
            raw = run_remote(t, entity, settings, limit)
            results, messages = parse_response(raw)
            _record_raw(t["url"], raw)
        else:
            raise TransformError(f"unknown transform kind {t['kind']!r}")
        evidence = list(builtin._rec.items)
    finally:
        builtin._rec.items = None
    for r in results:
        r["link"]["label"] = r["link"]["label"] or t.get("linkLabel") or t["name"]
    return results[:limit], messages, evidence


def _record_raw(url, body):
    items = getattr(builtin._rec, "items", None)
    if items is not None:
        items.append({"url": url, "status": None, "body": body, "fetched_at": int(time.time() * 1000)})


def run_local(t, entity, settings):
    # ponytail: process-level isolation only (scrubbed env, no shell, timeout, output cap, no stdin).
    # Run the backend in a container/VM for filesystem + network isolation of untrusted transforms.
    env = {k: os.environ[k] for k in SAFE_ENV if k in os.environ} | {"PYTHONIOENCODING": "utf-8"}
    env |= {"TRX_SETTING_" + re.sub(r"\W", "_", k).upper(): v for k, v in settings.items()}
    argv = [t["command"], *t.get("args", []), *local_args(entity)]
    try:
        p = subprocess.run(argv, cwd=t.get("workingDir") or None, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=t.get("timeout", 60),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise TransformError(f"local transform timed out after {t.get('timeout', 60)}s")
    except (FileNotFoundError, NotADirectoryError) as e:
        raise TransformError(f"cannot start local transform: {e}")
    if len(p.stdout) > MAX_OUTPUT:
        raise TransformError("local transform output too large")
    if b"<MaltegoMessage" not in p.stdout:
        err = p.stderr.decode("utf-8", "replace").strip()[-500:]
        raise TransformError(f"exit code {p.returncode}, no Maltego XML on stdout. stderr: {err}")
    return p.stdout


def run_remote(t, entity, settings, limit):
    url = urllib.parse.urlsplit(t["url"])
    if url.scheme not in ("http", "https"):
        raise TransformError("remote transform URL must be http(s)")
    if settings and url.scheme == "http" and url.hostname not in LOOPBACK:
        raise TransformError("refusing to send transform settings (API keys) over plain http to a remote host")
    req = urllib.request.Request(t["url"], data=build_request(entity, settings, limit),
                                 headers=UA | {"Content-Type": "application/xml"})
    try:
        with urllib.request.urlopen(req, timeout=t.get("timeout", 60)) as r:
            return r.read(MAX_OUTPUT)
    except urllib.error.HTTPError as e:
        raise TransformError(f"remote transform HTTP {e.code}: {e.read(300).decode('utf-8', 'replace')}")


def all_transforms(store):
    return list(BUILTINS.values()) + store.configs()
