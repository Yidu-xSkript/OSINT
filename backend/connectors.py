"""Bring-your-own-API-key connectors. Same contract as builtin.py; keys come from <service>.apikey settings."""
import base64, json, urllib.error, urllib.parse

from builtin import fetch, fetch_json, transform

CAP = 200
VT = "https://www.virustotal.com/api/v3"
RIPE = "https://stat.ripe.net/data"


def q(x):
    return urllib.parse.quote(x.strip(), safe=":@")


def need(s, svc):
    if not s.get(f"{svc}.apikey"):
        raise ValueError(f"set {svc}.apikey in Transforms → API Keys")
    return s[f"{svc}.apikey"]


def get(url, headers=None):  # 404 = "nothing known", not an error
    try:
        return fetch_json(url, headers=headers)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def props(prefix, d, keys):
    return {f"{prefix}.{k}": d[k] for k in keys if d.get(k) is not None}


# ---- Shodan ----
@transform("shodan-ip", "To Ports & Services [Shodan]", "IPAddress",
           "Open ports, hostnames, organization and CVEs", settings=["shodan.apikey"])
def _(v, p, s):
    j = get(f"https://api.shodan.io/shodan/host/{q(v)}?key={q(need(s, 'shodan'))}") or {}
    out = [("Phrase", f"{d['port']}/{d.get('transport', 'tcp')}", "Open Port",
            {"product": d.get("product", ""), "version": d.get("version", "")}) for d in j.get("data", [])]
    out += [("Domain", h.lower(), "Hostname") for h in j.get("hostnames", [])]
    out += [("Company", j["org"], "Organization")] if j.get("org") else []
    out += [("Phrase", c, "Vulnerable To") for c in j.get("vulns", [])]  # list, or dict keyed by CVE
    return out[:CAP]


@transform("shodan-domain", "To Subdomains [Shodan]", "Domain", "Subdomains from Shodan DNS", settings=["shodan.apikey"])
def _(v, p, s):
    j = get(f"https://api.shodan.io/dns/domain/{q(v)}?key={q(need(s, 'shodan'))}") or {}
    return [("Domain", f"{x}.{v}".lower(), "Subdomain (Shodan)") for x in j.get("subdomains", []) if x][:CAP]


# ---- VirusTotal v3 ----
def vt(path, s):
    return get(f"{VT}/{path}", {"x-apikey": need(s, "virustotal")}) or {}


def vt_rep(typ, v, path, s):
    a = (vt(path, s).get("data") or {}).get("attributes", {})
    st = a.get("last_analysis_stats", {})
    return [(typ, v, "", props("vt", st, st) | props("vt", a, ["reputation"]))] if a else []


def vt_rel(path, s):
    return vt(f"{path}?limit=40", s).get("data", [])  # ponytail: first page only (40); follow links.next if needed


@transform("vt-domain", "To Reputation [VirusTotal]", "Domain", "Enrich with VT detection stats and reputation",
           settings=["virustotal.apikey"])
def _(v, p, s):
    return vt_rep("Domain", v, f"domains/{q(v)}", s)


@transform("vt-ip", "To Reputation [VirusTotal]", "IPAddress", "Enrich with VT detection stats and reputation",
           settings=["virustotal.apikey"])
def _(v, p, s):
    return vt_rep("IPAddress", v, f"ip_addresses/{q(v)}", s)


@transform("vt-url", "To Reputation [VirusTotal]", "URL", "Enrich with VT detection stats and reputation",
           settings=["virustotal.apikey"])
def _(v, p, s):
    return vt_rep("URL", v, "urls/" + base64.urlsafe_b64encode(v.encode()).decode().rstrip("="), s)


@transform("vt-domain-ip", "To IP Addresses [VirusTotal]", "Domain", "Passive DNS resolutions",
           settings=["virustotal.apikey"])
def _(v, p, s):
    return [("IPAddress", r["attributes"]["ip_address"], "Resolved To (VT)") for r in vt_rel(f"domains/{q(v)}/resolutions", s)]


@transform("vt-domain-subdomains", "To Subdomains [VirusTotal]", "Domain", "Subdomains seen by VirusTotal",
           settings=["virustotal.apikey"])
def _(v, p, s):
    return [("Domain", r["id"], "Subdomain (VT)") for r in vt_rel(f"domains/{q(v)}/subdomains", s)]


@transform("vt-ip-domain", "To Domains [VirusTotal]", "IPAddress", "Passive DNS resolutions",
           settings=["virustotal.apikey"])
def _(v, p, s):
    return [("Domain", r["attributes"]["host_name"], "Resolved From (VT)") for r in vt_rel(f"ip_addresses/{q(v)}/resolutions", s)]


# ---- Have I Been Pwned v3 ----
@transform("hibp-email", "To Breaches [HIBP]", "EmailAddress", "Data breaches containing this address",
           settings=["hibp.apikey"])
def _(v, p, s):
    j = get(f"https://haveibeenpwned.com/api/v3/breachedaccount/{q(v)}?truncateResponse=false",
            {"hibp-api-key": need(s, "hibp")}) or []
    return [("Phrase", f"Breach: {b['Name']}", "Found In Breach",
             {"BreachDate": b.get("BreachDate", ""), "DataClasses": ", ".join(b.get("DataClasses", [])),
              "Domain": b.get("Domain", ""), "PwnCount": b.get("PwnCount", 0)}) for b in j][:CAP]


# ---- urlscan.io ----
@transform("urlscan-domain", "To Scans, URLs & IPs [urlscan]", "Domain", "Recent public urlscan.io scans",
           settings=["urlscan.apikey"])
def _(v, p, s):
    h = {"API-Key": s["urlscan.apikey"]} if s.get("urlscan.apikey") else {}
    j = fetch_json("https://urlscan.io/api/v1/search/?" + urllib.parse.urlencode({"q": f"domain:{v}", "size": 100}), h)
    out = []
    for r in j.get("results", []):
        pg, t = r.get("page", {}), r.get("task", {})
        if pg.get("url"):
            out.append(("URL", pg["url"], "Scanned (urlscan)"))
        if pg.get("ip"):
            out.append(("IPAddress", pg["ip"], "Served From", props("urlscan", pg, ["asn", "asnname", "country"])))
        if r.get("screenshot"):
            out.append(("Snapshot", r["screenshot"], "Screenshot (urlscan)",
                        {"url": t.get("url", ""), "time": t.get("time", ""), "result": r.get("result", "")}))
    return out[:CAP]


# ---- Wayback Machine CDX (no key) ----
def wayback(url, match, collapse):
    qs = urllib.parse.urlencode({"url": url, "matchType": match, "output": "json", "collapse": collapse,
                                 "fl": "timestamp,original,statuscode,mimetype", "limit": CAP})
    rows = json.loads(fetch("https://web.archive.org/cdx/search/cdx?" + qs)[0] or b"[]")
    return [("Snapshot", f"https://web.archive.org/web/{ts}/{u}", "Archived As",
             {"url": u, "timestamp": ts, "statuscode": sc, "mimetype": mt}) for ts, u, sc, mt in rows[1:]]


@transform("wayback-url", "To Archived Snapshots [Wayback]", "URL", "Distinct archived captures of this URL")
def _(v, p, s):
    return wayback(v, "exact", "digest")


@transform("wayback-domain", "To Archived URLs [Wayback]", "Domain", "One archived capture per URL on this domain")
def _(v, p, s):
    return wayback(v, "domain", "urlkey")


# ---- Hunter.io ----
@transform("hunter-domain", "To Emails & People [Hunter]", "Domain", "Email addresses and names from Hunter.io",
           settings=["hunter.apikey"])
def _(v, p, s):
    # ponytail: default page (10 results, the free-plan max); add limit/offset paging for paid keys
    j = fetch_json(f"https://api.hunter.io/v2/domain-search?domain={q(v)}", {"X-API-KEY": need(s, "hunter")})
    out = []
    for e in j["data"]["emails"]:
        out.append(("EmailAddress", e["value"].lower(), "Found By Hunter",
                    {"position": e.get("position") or "", "confidence": e.get("confidence"),
                     "sources": len(e.get("sources") or [])}))
        name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x)
        if name:
            out.append(("Person", name, "Works At (Hunter)", {"position": e.get("position") or ""}))
    return out


# ---- AbuseIPDB v2 ----
@transform("abuseipdb-ip", "To Abuse Reports [AbuseIPDB]", "IPAddress", "Abuse confidence score, reports, ISP",
           settings=["abuseipdb.apikey"])
def _(v, p, s):
    d = fetch_json("https://api.abuseipdb.com/api/v2/check?" + urllib.parse.urlencode({"ipAddress": v, "maxAgeInDays": 90}),
                   {"Key": need(s, "abuseipdb"), "Accept": "application/json"})["data"]
    keys = ["abuseConfidenceScore", "totalReports", "usageType", "countryCode", "isp", "domain", "lastReportedAt"]
    return [("IPAddress", v, "", props("abuseipdb", d, keys))] + ([("Company", d["isp"], "ISP")] if d.get("isp") else [])


# ---- GreyNoise Community ----
@transform("greynoise-ip", "To Noise Classification [GreyNoise]", "IPAddress", "Internet scanner / benign service check",
           settings=["greynoise.apikey"])
def _(v, p, s):
    h = {"key": s["greynoise.apikey"]} if s.get("greynoise.apikey") else {}
    j = get(f"https://api.greynoise.io/v3/community/{q(v)}", h) or {"noise": False, "riot": False}  # 404 = not observed
    return [("IPAddress", v, "", props("greynoise", j, ["classification", "noise", "riot", "name", "last_seen", "link"]))]


# ---- SecurityTrails ----
@transform("securitytrails-domain", "To Subdomains [SecurityTrails]", "Domain", "Subdomains from SecurityTrails",
           settings=["securitytrails.apikey"])
def _(v, p, s):
    j = get(f"https://api.securitytrails.com/v1/domain/{q(v)}/subdomains", {"APIKEY": need(s, "securitytrails")}) or {}
    return [("Domain", f"{x}.{v}".lower(), "Subdomain (SecurityTrails)") for x in j.get("subdomains", []) if x][:CAP]


# ---- RIPEstat (no key) ----
@transform("ripestat-ip", "To Network & ASN [RIPEstat]", "IPAddress", "Announcing prefix, ASN and holder from RIPE RIS")
def _(v, p, s):
    n = fetch_json(f"{RIPE}/network-info/data.json?resource={q(v)}")["data"]
    out = [("Phrase", n["prefix"], "Announced In")] if n.get("prefix") else []
    for asn in n.get("asns", []):
        holder = fetch_json(f"{RIPE}/as-overview/data.json?resource=AS{asn}")["data"].get("holder")
        out.append(("Phrase", f"AS{asn}", "Announced By", {"holder": holder or ""}))
        out += [("Company", holder, "Network Holder")] if holder else []
    return out
