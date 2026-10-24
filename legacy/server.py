"""Mini-Maltego: local OSINT link-analysis graph. Stdlib only.
Run: python server.py  ->  http://127.0.0.1:8765   |  Self-check: python server.py test
"""
import ipaddress, json, re, socket, sys, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (mini-maltego OSINT)"}
DNS_TYPES = {"A": 1, "NS": 2, "CNAME": 5, "PTR": 12, "MX": 15, "TXT": 16, "AAAA": 28}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", re.I)
HREF_RE = re.compile(r"""href=["'](https?://[^"'#\s>]+)""", re.I)


def fetch(url, limit=2_000_000):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
        return r.read(limit).decode("utf-8", "replace")


def dns(name, rtype):
    q = urllib.parse.urlencode({"name": name, "type": rtype})
    ans = json.loads(fetch(f"https://dns.google/resolve?{q}")).get("Answer", [])
    return [a["data"] for a in ans if a["type"] == DNS_TYPES[rtype]]


def host(s):  # "10 mx.example.com." -> "mx.example.com"
    return s.split()[-1].rstrip(".").lower()


def vcard_walk(rdap):
    """Yield (role, field, value) from every nested RDAP entity vCard."""
    for ent in rdap.get("entities", []):
        roles = ",".join(ent.get("roles", []))
        for f in (ent.get("vcardArray") or [None, []])[1]:
            if f[0] in ("fn", "org", "email") and isinstance(f[3], str) and f[3].strip():
                yield roles, f[0], f[3].strip()
        yield from vcard_walk(ent)


def page_intel(html, base_domain):
    out = [("Email", e.lower()) for e in EMAIL_RE.findall(html)]
    for link in HREF_RE.findall(html):
        d = (urllib.parse.urlsplit(link).hostname or "").lower()
        if d and d != base_domain:
            out.append(("Domain", d))
    return out


# ---- transforms: each takes the entity value, returns [(type, value), ...] ----

def domain_rdap(d):
    out = []
    for roles, field, val in vcard_walk(json.loads(fetch(f"https://rdap.org/domain/{d}"))):
        if field == "email":
            out.append(("Email", val.lower()))
        elif "registrar" in roles or field == "org":
            out.append(("Organization", val))
        elif "redacted" not in val.lower():
            out.append(("Person", val))
    return out


def domain_subdomains(d):
    rows = json.loads(fetch(f"https://crt.sh/?q=%25.{d}&output=json"))
    names = {n.strip().lower() for r in rows for n in r["name_value"].split("\n")}
    # ponytail: capped at 300 so huge domains don't bury the graph; add paging if needed
    return [("Domain", n) for n in sorted(names) if n.endswith(d) and "*" not in n and n != d][:300]


def ip_geo(ip):
    j = json.loads(fetch(f"https://ipinfo.io/{ip}/json"))
    if "bogon" in j or "error" in j:
        raise ValueError(j.get("error", {}).get("message", "bogon/private IP"))
    out = [("Location", ", ".join(x for x in (j.get("city"), j.get("region"), j.get("country")) if x))]
    asn, _, org = (j.get("org") or "").partition(" ")  # "AS15169 Google LLC"
    out += [("Organization", org)] if org else []
    out += [("AS", asn)] if asn else []
    return out + ([("Domain", j["hostname"])] if j.get("hostname") else [])


def url_intel(u):
    return page_intel(fetch(u), (urllib.parse.urlsplit(u).hostname or "").lower())


def github_user(u):
    j = json.loads(fetch(f"https://api.github.com/users/{urllib.parse.quote(u)}"))
    out = [("URL", j["html_url"])]
    for key, typ in (("name", "Person"), ("company", "Organization"), ("location", "Location"),
                     ("email", "Email"), ("blog", "URL")):
        if j.get(key):
            out.append((typ, j[key].lstrip("@") if key == "company" else j[key]))
    return out


TRANSFORMS = {
    "Domain": {
        "To IP Address [DNS]": lambda d: [("IP", a[4][0]) for a in socket.getaddrinfo(d, None)],  # system resolver
        "To Mail Servers [MX]": lambda d: [("Domain", host(x)) for x in dns(d, "MX")],
        "To Name Servers [NS]": lambda d: [("Domain", host(x)) for x in dns(d, "NS")],
        "To TXT Records": lambda d: [("Phrase", x.strip('"')) for x in dns(d, "TXT")],
        "To Subdomains [crt.sh]": domain_subdomains,
        "To Whois Contacts [RDAP]": domain_rdap,
        "To Website": lambda d: [("URL", f"https://{d}")],
    },
    "IP": {
        "To Reverse DNS [PTR]": lambda ip: [("Domain", host(x)) for x in
                                            dns(ipaddress.ip_address(ip).reverse_pointer, "PTR")],
        "To Location / ISP / AS": ip_geo,
    },
    "URL": {
        "To Domain": lambda u: [("Domain", urllib.parse.urlsplit(u).hostname.lower())],
        "To Emails & Linked Domains": url_intel,
    },
    "Email": {"To Domain": lambda e: [("Domain", e.rsplit("@", 1)[1].lower())]},
    "Username": {"To GitHub Profile": github_user},
}


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/transforms":
            return self.send(200, {t: list(fns) for t, fns in TRANSFORMS.items()})
        self.send(200, (Path(__file__).parent / "index.html").read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            fn = TRANSFORMS[req["type"]][req["transform"]]
            seen, results = set(), []
            for typ, val in fn(req["value"].strip()):
                if (typ, val) not in seen:
                    seen.add((typ, val))
                    results.append({"type": typ, "value": val})
            self.send(200, {"results": results})
        except Exception as e:
            self.send(200, {"error": f"{type(e).__name__}: {e}"})


def test():
    assert host("10 aspmx.L.google.com.") == "aspmx.l.google.com"
    rdap = {"entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", "Acme Reg"]]],
                          "entities": [{"roles": ["abuse"], "vcardArray": ["vcard", [["email", {}, "text", "a@b.com"]]]}]}]}
    assert list(vcard_walk(rdap)) == [("registrar", "fn", "Acme Reg"), ("abuse", "email", "a@b.com")]
    html = '<a href="https://other.org/x">x</a> <a href="https://me.com/">me</a> mail: Bob@Me.com'
    assert page_intel(html, "me.com") == [("Email", "bob@me.com"), ("Domain", "other.org")]
    assert ipaddress.ip_address("8.8.8.8").reverse_pointer == "8.8.8.8.in-addr.arpa"
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        test()
    else:
        print("Mini-Maltego on http://127.0.0.1:8765")
        ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
