"""theHarvester adapter — domain OSINT (emails, subdomains, IPs, URLs) via the external theHarvester tool.

The tool is detected, not bundled (size/deps). The analyst controls scope: `theharvester.sources` (which
public providers), `theharvester.limit` (results per source — a rate guard), and `theharvester.path` (an
explicit executable). A single domain lookup only queries the chosen sources, never an uncontrolled sweep.
Execution is an argv array (no shell), a scrubbed env, a timeout, and no window; output is parsed from the
tool's JSON report and every finding is source-asserted and evidence-backed.
"""
import json
import os
import subprocess
import tempfile

import builtin
import tools
from builtin import transform

# Keyless, generally well-behaved providers. Users can override with the theharvester.sources setting.
KEYLESS_SOURCES = "crtsh,bing,duckduckgo,otx,rapiddns,hackertarget,threatminer,anubis,certspotter"
_SAFE_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
             "PROGRAMFILES", "PROGRAMFILES(X86)", "TEMP", "TMP", "PATHEXT")


def parse_report(domain, data):
    """theHarvester JSON report -> [(type, value, link_label, props)], deduped."""
    out = []
    for e in data.get("emails", []) or []:
        if isinstance(e, str) and "@" in e:
            out.append(("EmailAddress", e.strip().lower(), "Email [theHarvester]", {}))
    for h in data.get("hosts", []) or []:
        if not isinstance(h, str):
            continue
        host, _, ip = h.partition(":")
        host = host.strip().lower().rstrip(".")
        if host:
            out.append(("Domain", host, "Subdomain [theHarvester]", {}))
        ip = ip.strip()
        if ip:
            out.append(("IPAddress", ip, "Resolves To [theHarvester]", {}))
    for ip in data.get("ips", []) or []:
        if isinstance(ip, str) and ip.strip():
            out.append(("IPAddress", ip.strip(), "IP [theHarvester]", {}))
    for key in ("interesting_urls", "urls", "trello_urls"):
        for u in data.get(key, []) or []:
            if isinstance(u, str) and u.startswith("http"):
                out.append(("URL", u.strip(), "URL [theHarvester]", {}))
    seen, uniq = set(), []
    for row in out:
        k = (row[0], row[1])
        if k not in seen:
            seen.add(k)
            uniq.append(row)
    return uniq


@transform("theharvester", "To Emails, Subdomains & IPs [theHarvester]", "Domain",
           "Run the external theHarvester against this domain. Needs theHarvester installed (see the Tools "
           "tab). Scope it with theharvester.sources / theharvester.limit.",
           settings=["theharvester.path", "theharvester.sources", "theharvester.limit"],
           classification="source-asserted")
def _(v, p, s):
    path = tools.resolve_path("theharvester", s)
    if not path:
        raise ValueError("theHarvester not found — install it (pipx install theHarvester) or set "
                         "theharvester.path to its executable (see the Tools tab).")
    domain = v.strip().lower()
    sources = (s.get("theharvester.sources") or KEYLESS_SOURCES).strip()
    limit = (s.get("theharvester.limit") or "200").strip()
    if not limit.isdigit():
        raise ValueError("theharvester.limit must be a number")
    env = {k: os.environ[k] for k in _SAFE_ENV if k in os.environ} | {"PYTHONIOENCODING": "utf-8"}
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, "report")
        argv = [path, "-d", domain, "-b", sources, "-l", limit, "-f", base]
        try:
            proc = subprocess.run(argv, cwd=d, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                  timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise ValueError("theHarvester timed out after 300s — reduce theharvester.sources or .limit")
        jpath = base + ".json"
        if not os.path.isfile(jpath):
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-400:]
            raise ValueError(f"theHarvester produced no report: {tail or 'unknown error'}")
        raw = open(jpath, "rb").read()
    builtin._record(f"theharvester:{domain}:{sources}", 200, raw)
    return parse_report(domain, json.loads(raw.decode("utf-8", "replace") or "{}"))
