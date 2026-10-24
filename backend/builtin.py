"""Built-in transforms. Each fn(value, props, settings) -> [(type, value, link_label, {prop: value}?), ...]"""
import hashlib, ipaddress, json, re, socket, time, urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (osint-graph)"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", re.I)
HREF_RE = re.compile(r"""href=["']((?:https?|tel|mailto):[^"'#\s>]+)""", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
DOH = ["https://dns.google/resolve", "https://cloudflare-dns.com/dns-query"]
DNS_TYPES = {"NS": 2, "PTR": 12, "MX": 15, "TXT": 16}

BUILTINS = {}


def transform(tid, name, input_type, description, settings=(), classification="source-asserted",
              optional_settings=()):
    # classification = how a result from this transform should be read on the graph:
    #   "source-asserted" a provider/page claims it (default) · "observed" directly present in collected
    #   material · "derived" computed from inputs by a documented method · "hypothesis" a lead to verify.
    # optional_settings = credential-looking settings the transform works WITHOUT (e.g. a key that only
    #   raises rate limits) — these don't mark the transform "needs setup".
    def deco(fn):
        BUILTINS[tid] = {"id": tid, "name": name, "kind": "builtin", "inputType": input_type,
                         "description": description, "settings": list(settings),
                         "optionalSettings": list(optional_settings),
                         "classification": classification, "fn": fn}
        return fn
    return deco


import threading, time as _time
_rec = threading.local()  # engine sets _rec.items = [] around a transform run to capture evidence


def _record(url, status, body):
    items = getattr(_rec, "items", None)
    if items is not None:
        items.append({"url": url, "status": status, "body": body, "fetched_at": int(_time.time() * 1000)})


# --- SSRF guard -----------------------------------------------------------
# User-supplied URLs (url-intel, url-snapshot, domain-website, website-url…) must not reach the
# loopback FastAPI sidecar, cloud metadata (169.254.169.254), or other internal hosts. Public API
# connectors are unaffected: their hosts resolve to global addresses.
def _assert_public_url(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"blocked non-web URL scheme: {p.scheme or '(none)'}")
    if not p.hostname:
        raise ValueError("blocked URL with no host")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve host: {p.hostname}") from e
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            raise ValueError(f"blocked internal/reserved address for {p.hostname}: {ip}")


class _NoRedirectToPrivate(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_url(newurl)  # re-check each hop so a public URL can't bounce to a private IP
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_NoRedirectToPrivate())


def fetch(url, limit=2_000_000, headers=None):
    _assert_public_url(url)
    req = urllib.request.Request(url, headers=UA | (headers or {}))
    # ponytail: getaddrinfo check is TOCTOU vs DNS rebinding; fine for a local tool. Pin the
    # resolved IP into the socket if that narrow threat ever matters.
    with _opener.open(req, timeout=25) as r:
        body = r.read(limit)
    _record(url, r.status, body)
    return body, r.status


def fetch_json(url, headers=None):
    return json.loads(fetch(url, headers=headers)[0])


def dns(name, rtype):
    q = urllib.parse.urlencode({"name": name, "type": rtype})
    err = None
    for base in DOH:  # some networks sinkhole one resolver; try the next
        try:
            ans = fetch_json(f"{base}?{q}", {"accept": "application/dns-json"}).get("Answer", [])
            return [a["data"] for a in ans if a["type"] == DNS_TYPES[rtype]]
        except Exception as e:
            err = e
    raise err


def host(s):  # "10 mx.example.com." -> "mx.example.com"
    return s.split()[-1].rstrip(".").lower()


def vcard_walk(rdap):
    """Yield (roles, field, value) from every nested RDAP entity vCard."""
    for ent in rdap.get("entities", []):
        roles = ",".join(ent.get("roles", []))
        for f in (ent.get("vcardArray") or [None, []])[1]:
            if f[0] in ("fn", "org", "email") and isinstance(f[3], str) and f[3].strip():
                yield roles, f[0], f[3].strip()
        yield from vcard_walk(ent)


def page_intel(html, base_host):
    out = [("EmailAddress", e.lower(), "Found On Page") for e in EMAIL_RE.findall(html)]
    for link in HREF_RE.findall(html):
        scheme, _, rest = link.partition(":")
        if scheme.lower() == "mailto":
            out.append(("EmailAddress", rest.split("?")[0].lower(), "Found On Page"))
        elif scheme.lower() == "tel":
            out.append(("PhoneNumber", urllib.parse.unquote(rest).strip(), "Found On Page"))
        else:
            h = (urllib.parse.urlsplit(link).hostname or "").lower()
            if h and h != base_host:
                out.append(("Website", h, "Links To"))
    return out


# ---- Domain ----
@transform("dns-a", "To IP Address [DNS]", "Domain", "Resolve A/AAAA via the system resolver")
def _(v, p, s):
    return [("IPAddress", a[4][0], "Resolves To") for a in socket.getaddrinfo(v, None)]


@transform("dns-mx", "To Mail Servers [MX]", "Domain", "MX records via DNS-over-HTTPS")
def _(v, p, s):
    return [("Domain", host(x), "MX Record", {"dns.type": "MX"}) for x in dns(v, "MX")]


@transform("dns-ns", "To Name Servers [NS]", "Domain", "NS records via DNS-over-HTTPS")
def _(v, p, s):
    return [("Domain", host(x), "NS Record", {"dns.type": "NS"}) for x in dns(v, "NS")]


@transform("dns-txt", "To TXT Records", "Domain", "TXT records (SPF, verification tokens)")
def _(v, p, s):
    return [("Phrase", x.strip('"'), "TXT Record") for x in dns(v, "TXT")]


@transform("crtsh", "To Subdomains [crt.sh]", "Domain", "Certificate Transparency log search")
def _(v, p, s):
    rows = json.loads(fetch(f"https://crt.sh/?q=%25.{v}&output=json", limit=50_000_000)[0])
    names = {n.strip().lower() for r in rows for n in r["name_value"].split("\n")}
    return [("Domain", n, "Subdomain (CT log)") for n in sorted(names) if n.endswith(v) and "*" not in n and n != v]


@transform("rdap", "To WHOIS Contacts [RDAP]", "Domain", "Registrar and registrant contacts from RDAP")
def _(v, p, s):
    out = []
    for roles, field, val in vcard_walk(fetch_json(f"https://rdap.org/domain/{v}")):
        if field == "email":
            out.append(("EmailAddress", val.lower(), f"WHOIS {roles or 'Contact'}"))
        elif "registrar" in roles or field == "org":
            out.append(("Company", val, f"WHOIS {roles or 'Organization'}"))
        elif "redacted" not in val.lower():
            out.append(("Person", val, f"WHOIS {roles or 'Contact'}"))
    return out


@transform("domain-website", "To Website", "Domain", "The website served on this domain")
def _(v, p, s):
    return [("Website", v, "Hosts Website")]


# ---- Website ----
@transform("website-url", "To Homepage URL", "Website", "https:// URL of the site")
def _(v, p, s):
    return [("URL", f"https://{v}/", "Homepage")]


@transform("website-domain", "To Domain", "Website", "The hostname as a Domain")
def _(v, p, s):
    return [("Domain", v.lower(), "Served From")]


# ---- URL ----
@transform("url-domain", "To Domain", "URL", "Hostname of the URL")
def _(v, p, s):
    return [("Domain", urllib.parse.urlsplit(v).hostname.lower(), "Hosted On")]


@transform("url-intel", "To Emails, Phones & Linked Sites", "URL", "Scrape the page for contacts and outbound links",
           classification="observed")
def _(v, p, s):
    return page_intel(fetch(v)[0].decode("utf-8", "replace"), (urllib.parse.urlsplit(v).hostname or "").lower())


@transform("url-snapshot", "To Snapshot", "URL", "Capture the page: status, title, size, SHA-256")
def _(v, p, s):
    body, status = fetch(v, limit=10_000_000)
    title = TITLE_RE.search(body.decode("utf-8", "replace"))
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return [("Snapshot", f"{v} @ {ts}", "Captured As", {
        "url": v, "http.status": status, "title": title.group(1).strip()[:300] if title else "",
        "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "fetchedAt": ts})]


# ---- IPAddress ----
@transform("ip-ptr", "To Reverse DNS [PTR]", "IPAddress", "PTR record")
def _(v, p, s):
    return [("Domain", host(x), "Reverse DNS") for x in dns(ipaddress.ip_address(v).reverse_pointer, "PTR")]


@transform("ip-geo", "To Location / ASN [ipinfo]", "IPAddress", "Geolocation and announcing network",
           settings=["ipinfo.token"], optional_settings=["ipinfo.token"])
def _(v, p, s):
    tok = f"?token={urllib.parse.quote(s['ipinfo.token'])}" if s.get("ipinfo.token") else ""
    j = fetch_json(f"https://ipinfo.io/{v}/json{tok}")
    if "bogon" in j or "error" in j:
        raise ValueError(j.get("error", {}).get("message", "bogon/private IP"))
    out = []
    loc = ", ".join(x for x in (j.get("city"), j.get("region"), j.get("country")) if x)
    if loc:
        out.append(("Location", loc, "Geolocated In", {"location.coordinates": j.get("loc", "")}))
    asn, _, org = (j.get("org") or "").partition(" ")  # "AS15169 Google LLC"
    if org:
        out.append(("Company", org, "Announced By", {"asn": asn}))
    if j.get("hostname"):
        out.append(("Domain", j["hostname"], "Reverse DNS"))
    return out


# ---- EmailAddress ----
@transform("email-domain", "To Domain", "EmailAddress", "Mail domain")
def _(v, p, s):
    return [("Domain", v.rsplit("@", 1)[1].lower(), "Email Domain")]


# ---- Phrase / Affiliation (usernames) ----
def github(username):
    return fetch_json(f"https://api.github.com/users/{urllib.parse.quote(username)}")


@transform("phrase-github", "To GitHub Account", "Phrase", "Treat the phrase as a username and look it up on GitHub")
def _(v, p, s):
    j = github(v)
    return [("Affiliation", f"github:{j['login']}", "Username Match",
             {"affiliation.network": "GitHub", "affiliation.uid": j["login"],
              "affiliation.profile-url": j["html_url"]})]


@transform("affiliation-github", "To GitHub Profile Details", "Affiliation", "Name, company, location, email, blog")
def _(v, p, s):
    uid = (p.get("affiliation.uid") or {}).get("value") or v.removeprefix("github:")
    j = github(uid)
    out = [("URL", j["html_url"], "Profile Page")]
    for key, typ, label in (("name", "Person", "Owned By"), ("company", "Company", "Works At"),
                            ("location", "Location", "Located In"), ("email", "EmailAddress", "Public Email"),
                            ("blog", "URL", "Links To")):
        if j.get(key):
            out.append((typ, j[key].lstrip("@") if key == "company" else j[key], label))
    return out
