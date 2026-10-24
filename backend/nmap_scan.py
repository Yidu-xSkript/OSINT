"""Nmap adapter — authorized network scanning.

Safety model (the reviewer's requirements):
  * Fixed scan PROFILES only — never free-form nmap flags, so a target string can't smuggle dangerous
    options and users can't accidentally launch an intrusive scan.
  * Strict target validation (hostname / IPv4 / IPv6 / CIDR) and a hard scope cap, so one lookup can't
    turn into a sweep. Targets that look like flags ("-…") are rejected.
  * Unprivileged TCP connect scans (-sT), so no admin/Npcap raw-socket requirement on Windows.
  * Authorization + exact-scope confirmation happen at the API/UI layer; discovered IPs never auto-scan.
Execution is an argv array (no shell), scrubbed env, timeout, no window; results parse from nmap's XML.
"""
import ipaddress
import os
import re
import subprocess
import xml.etree.ElementTree as ET

import tools

PROFILES = {
    "discovery": {"label": "Host discovery (ping sweep, no ports)", "args": ["-sn"]},
    "fast": {"label": "Fast — top 100 TCP ports", "args": ["-sT", "-T4", "-F"]},
    "standard": {"label": "Standard — top 1000 TCP ports", "args": ["-sT", "-T4", "--top-ports", "1000"]},
    "service": {"label": "Service & version — top 1000 + -sV", "args": ["-sT", "-T4", "-sV", "--top-ports", "1000"]},
}

MAX_TARGETS = 32
MAX_HOSTS = 256  # one /24 — keeps a scan bounded; narrow further for anything larger
_SAFE_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
             "PROGRAMFILES", "PROGRAMFILES(X86)", "TEMP", "TMP", "PATHEXT")
_HOST_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9_](?:[A-Za-z0-9_-]{0,62}[A-Za-z0-9_])?\.)*"
                      r"[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,62}[A-Za-z0-9_])?$")


class ScanError(Exception):
    pass


def valid_target(t):
    t = t.strip()
    if not t or t.startswith("-"):  # reject flag-looking input outright
        return False
    try:
        ipaddress.ip_network(t, strict=False)  # IP or CIDR
        return True
    except ValueError:
        return bool(_HOST_RE.match(t))


def host_count(targets):
    n = 0
    for t in targets:
        try:
            n += ipaddress.ip_network(t.strip(), strict=False).num_addresses
        except ValueError:
            n += 1
    return n


def parse_xml(xml):
    if b"<!DOCTYPE" in xml:
        raise ScanError("unexpected DOCTYPE in nmap output")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ScanError(f"could not parse nmap output: {e}")
    hosts = []
    for h in root.findall("host"):
        st = h.find("status")
        if st is not None and st.get("state") != "up":
            continue
        ip = next((a.get("addr") for a in h.findall("address") if a.get("addrtype") in ("ipv4", "ipv6")), None)
        if not ip:
            continue
        hostnames = [hn.get("name") for hn in h.findall("hostnames/hostname") if hn.get("name")]
        services = []
        for port in h.findall("ports/port"):
            stt = port.find("state")
            if stt is None or stt.get("state") != "open":
                continue
            svc = port.find("service")
            name = svc.get("name") if svc is not None else None
            tunnel = svc.get("tunnel") if svc is not None else None
            product = svc.get("product") if svc is not None else None
            version = svc.get("version") if svc is not None else None
            url = None
            if name and ("http" in name):
                scheme = "https" if (name == "https" or tunnel == "ssl") else "http"
                url = f"{scheme}://{ip}:{port.get('portid')}"
            services.append({"port": port.get("portid"), "proto": port.get("protocol"),
                             "name": name, "product": product, "version": version, "url": url})
        parts = []
        for s in services:
            lbl = f"{s['port']}/{s['proto']} {s['name'] or 'unknown'}"
            pv = " ".join(x for x in (s["product"], s["version"]) if x)
            parts.append(lbl + (f" ({pv})" if pv else ""))
        hosts.append({"ip": ip, "hostnames": hostnames, "services": services, "ports_summary": "; ".join(parts)})
    return hosts


def preview(targets, profile):
    """The exact argv that will run (minus the resolved nmap path) — shown to the user before confirming."""
    return ["nmap", *PROFILES[profile]["args"], "-oX", "-", *[t.strip() for t in targets if t.strip()]]


def scan(targets, profile, settings, timeout=600):
    """-> (hosts, xml_bytes, messages). Raises ScanError on bad scope / missing tool / failure."""
    if profile not in PROFILES:
        raise ScanError(f"unknown scan profile: {profile}")
    targets = [t.strip() for t in targets if t.strip()]
    if not targets:
        raise ScanError("no targets given")
    if len(targets) > MAX_TARGETS:
        raise ScanError(f"too many targets (max {MAX_TARGETS})")
    bad = [t for t in targets if not valid_target(t)]
    if bad:
        raise ScanError(f"invalid target(s): {', '.join(bad[:5])}")
    hc = host_count(targets)
    if hc > MAX_HOSTS:
        raise ScanError(f"scope too large ({hc} addresses; max {MAX_HOSTS}). Narrow the range.")
    path = tools.resolve_path("nmap", settings)
    if not path:
        raise ScanError("Nmap not found — install it from nmap.org or set nmap.path (see the Tools tab).")
    argv = [path, *PROFILES[profile]["args"], "-oX", "-", *targets]
    env = {k: os.environ[k] for k in _SAFE_ENV if k in os.environ}
    try:
        proc = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise ScanError(f"scan timed out after {timeout}s — narrow the scope or use a faster profile")
    if not proc.stdout:
        raise ScanError((proc.stderr or b"").decode("utf-8", "replace").strip()[:400] or "nmap produced no output")
    hosts = parse_xml(proc.stdout)
    return hosts, proc.stdout, [{"type": "Inform", "text": f"nmap {profile}: {len(hosts)} host(s) up"}]
