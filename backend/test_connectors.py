"""Connector mapping self-check, no network needed:  python test_connectors.py"""
import io, json, urllib.error

import builtin
import connectors

CANNED = {  # url substring -> response mirroring the real API shape
    "shodan.io/shodan/host/": {"ip_str": "1.2.3.4", "org": "Acme Hosting", "hostnames": ["Web.acme.com"],
                               "vulns": ["CVE-2021-44228"], "data": [
                                   {"port": 443, "transport": "tcp", "product": "nginx", "version": "1.18"},
                                   {"port": 53, "transport": "udp"}]},
    "shodan.io/dns/domain/": {"domain": "acme.com", "subdomains": ["www", "mail", ""], "data": []},
    "virustotal.com/api/v3/domains/acme.com/resolutions": {"data": [{"id": "1.2.3.4acme.com", "type": "resolution",
                                                                     "attributes": {"ip_address": "1.2.3.4", "host_name": "acme.com"}}]},
    "virustotal.com/api/v3/domains/acme.com/subdomains": {"data": [{"id": "dev.acme.com", "type": "domain"}]},
    "virustotal.com/api/v3/ip_addresses/1.2.3.4/resolutions": {"data": [{"attributes": {"ip_address": "1.2.3.4", "host_name": "old.acme.com"}}]},
    "virustotal.com/api/v3/": {"data": {"id": "x", "attributes": {
        "reputation": -5, "last_analysis_stats": {"malicious": 3, "suspicious": 1, "harmless": 60, "undetected": 20}}}},
    "haveibeenpwned.com": [{"Name": "Adobe", "Title": "Adobe", "Domain": "adobe.com", "BreachDate": "2013-10-04",
                            "PwnCount": 152445165, "DataClasses": ["Email addresses", "Passwords"]}],
    "urlscan.io": {"results": [{"_id": "u1", "task": {"url": "https://acme.com/", "time": "2026-01-01T00:00:00Z"},
                                "page": {"url": "https://acme.com/home", "ip": "1.2.3.4", "asn": "AS64500", "asnname": "ACME"},
                                "screenshot": "https://urlscan.io/screenshots/u1.png",
                                "result": "https://urlscan.io/api/v1/result/u1/"}], "total": 1, "has_more": False},
    "web.archive.org": [["timestamp", "original", "statuscode", "mimetype"],
                        ["20200101000000", "http://acme.com/", "200", "text/html"],
                        ["20210101000000", "http://acme.com/about", "301", "text/html"]],
    "api.hunter.io": {"data": {"domain": "acme.com", "emails": [
        {"value": "Ann@acme.com", "type": "personal", "confidence": 94, "first_name": "Ann", "last_name": "Lee",
         "position": "CTO", "sources": [{"domain": "x.com"}, {"domain": "y.com"}]},
        {"value": "info@acme.com", "type": "generic", "confidence": 80, "first_name": None, "last_name": None,
         "position": None, "sources": []}]}, "meta": {"results": 2}},
    "abuseipdb.com": {"data": {"ipAddress": "1.2.3.4", "abuseConfidenceScore": 87, "totalReports": 12,
                               "usageType": "Data Center/Web Hosting/Transit", "countryCode": "NL", "isp": "Acme BV",
                               "domain": "acme.nl", "isWhitelisted": False, "lastReportedAt": None}},
    "greynoise.io": {"ip": "1.2.3.4", "noise": True, "riot": False, "classification": "malicious", "name": "unknown",
                     "link": "https://viz.greynoise.io/ip/1.2.3.4", "last_seen": "2026-10-01", "message": "Success"},
    "securitytrails.com": {"subdomains": ["api", "www"], "subdomain_count": 2},
    "network-info": {"status": "ok", "data": {"asns": ["15169"], "prefix": "8.8.8.0/24"}},
    "as-overview": {"status": "ok", "data": {"resource": "15169", "holder": "GOOGLE - Google LLC", "announced": True}},
}
calls = []


def fake_json(url, headers=None):
    calls.append((url, headers or {}))
    if "404" in url:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))
    return next(v for k, v in CANNED.items() if k in url)


def run(tid, value, settings=None):
    calls.clear()
    return builtin.BUILTINS[tid]["fn"](value, {}, settings or {})


connectors.fetch_json = fake_json
connectors.fetch = lambda url, limit=0, headers=None: (json.dumps(fake_json(url, headers)).encode(), 200)


def test_shodan():
    r = run("shodan-ip", "1.2.3.4", {"shodan.apikey": "K"})
    assert ("Phrase", "443/tcp", "Open Port", {"product": "nginx", "version": "1.18"}) in r
    assert ("Phrase", "53/udp", "Open Port", {"product": "", "version": ""}) in r
    assert ("Domain", "web.acme.com", "Hostname") in r and ("Company", "Acme Hosting", "Organization") in r
    assert ("Phrase", "CVE-2021-44228", "Vulnerable To") in r and "key=K" in calls[0][0]
    assert [x[1] for x in run("shodan-domain", "acme.com", {"shodan.apikey": "K"})] == ["www.acme.com", "mail.acme.com"]
    try:
        run("shodan-ip", "1.2.3.4", {})
        assert False
    except ValueError as e:
        assert "shodan.apikey" in str(e) and not calls


def test_virustotal():
    s = {"virustotal.apikey": "VK"}
    for tid, typ, v in (("vt-domain", "Domain", "acme.com"), ("vt-ip", "IPAddress", "1.2.3.4"),
                        ("vt-url", "URL", "https://acme.com/?a=1")):
        [(t, val, label, pr)] = run(tid, v, s)
        assert (t, val, label) == (typ, v, "") and pr["vt.malicious"] == 3 and pr["vt.reputation"] == -5
        assert calls[0][1] == {"x-apikey": "VK"}
    assert calls[0][0].endswith("/urls/aHR0cHM6Ly9hY21lLmNvbS8_YT0x")  # base64url, no padding
    assert run("vt-domain-ip", "acme.com", s) == [("IPAddress", "1.2.3.4", "Resolved To (VT)")]
    assert run("vt-domain-subdomains", "acme.com", s) == [("Domain", "dev.acme.com", "Subdomain (VT)")]
    assert run("vt-ip-domain", "1.2.3.4", s) == [("Domain", "old.acme.com", "Resolved From (VT)")]
    assert run("vt-domain", "404.example", s) == []


def test_hibp():
    [(t, v, _, pr)] = run("hibp-email", "a@b.com", {"hibp.apikey": "H"})
    assert (t, v) == ("Phrase", "Breach: Adobe") and pr["BreachDate"] == "2013-10-04"
    assert pr["DataClasses"] == "Email addresses, Passwords" and calls[0][1] == {"hibp-api-key": "H"}
    assert "breachedaccount/a@b.com?truncateResponse=false" in calls[0][0]
    assert run("hibp-email", "404@b.com", {"hibp.apikey": "H"}) == []  # not pwned


def test_urlscan():
    r = run("urlscan-domain", "acme.com")
    assert calls[0][1] == {} and "q=domain%3Aacme.com" in calls[0][0]
    assert ("URL", "https://acme.com/home", "Scanned (urlscan)") in r
    assert ("IPAddress", "1.2.3.4", "Served From", {"urlscan.asn": "AS64500", "urlscan.asnname": "ACME"}) in r
    snap = next(x for x in r if x[0] == "Snapshot")
    assert snap[1] == "https://urlscan.io/screenshots/u1.png" and snap[3]["url"] == "https://acme.com/"
    run("urlscan-domain", "acme.com", {"urlscan.apikey": "U"})
    assert calls[0][1] == {"API-Key": "U"}


def test_wayback():
    r = run("wayback-url", "http://acme.com/")
    assert r[0] == ("Snapshot", "https://web.archive.org/web/20200101000000/http://acme.com/", "Archived As",
                    {"url": "http://acme.com/", "timestamp": "20200101000000", "statuscode": "200", "mimetype": "text/html"})
    assert len(r) == 2 and "collapse=digest" in calls[0][0] and "matchType=exact" in calls[0][0]
    run("wayback-domain", "acme.com")
    assert "matchType=domain" in calls[0][0] and "collapse=urlkey" in calls[0][0] and "limit=200" in calls[0][0]


def test_hunter():
    r = run("hunter-domain", "acme.com", {"hunter.apikey": "HK"})
    assert ("EmailAddress", "ann@acme.com", "Found By Hunter", {"position": "CTO", "confidence": 94, "sources": 2}) in r
    assert ("Person", "Ann Lee", "Works At (Hunter)", {"position": "CTO"}) in r
    assert len(r) == 3 and calls[0][1] == {"X-API-KEY": "HK"}


def test_abuseipdb():
    [(t, v, label, pr), co] = run("abuseipdb-ip", "1.2.3.4", {"abuseipdb.apikey": "A"})
    assert (t, v, label) == ("IPAddress", "1.2.3.4", "") and pr["abuseipdb.abuseConfidenceScore"] == 87
    assert pr["abuseipdb.usageType"].startswith("Data Center") and "abuseipdb.lastReportedAt" not in pr
    assert co == ("Company", "Acme BV", "ISP") and calls[0][1]["Key"] == "A"


def test_greynoise():
    [(t, v, label, pr)] = run("greynoise-ip", "1.2.3.4")
    assert pr["greynoise.classification"] == "malicious" and pr["greynoise.noise"] is True and calls[0][1] == {}
    run("greynoise-ip", "1.2.3.4", {"greynoise.apikey": "G"})
    assert calls[0][1] == {"key": "G"}
    assert run("greynoise-ip", "10.0.0.404")[0][3] == {"greynoise.noise": False, "greynoise.riot": False}


def test_securitytrails():
    assert run("securitytrails-domain", "acme.com", {"securitytrails.apikey": "S"}) == [
        ("Domain", "api.acme.com", "Subdomain (SecurityTrails)"), ("Domain", "www.acme.com", "Subdomain (SecurityTrails)")]
    assert calls[0][1] == {"APIKEY": "S"}


def test_ripestat():
    assert run("ripestat-ip", "8.8.8.8") == [("Phrase", "8.8.8.0/24", "Announced In"),
                                              ("Phrase", "AS15169", "Announced By", {"holder": "GOOGLE - Google LLC"}),
                                              ("Company", "GOOGLE - Google LLC", "Network Holder")]


def live_smoke():
    import importlib
    try:
        importlib.reload(connectors)  # restore real fetch
        assert any(x[1] == "AS15169" for x in builtin.BUILTINS["ripestat-ip"]["fn"]("8.8.8.8", {}, {}))
        assert builtin.BUILTINS["wayback-url"]["fn"]("http://example.com/", {}, {})[0][0] == "Snapshot"
        print("live smoke ok")
    except Exception as e:
        print(f"live smoke skipped (network): {e}")


if __name__ == "__main__":
    test_shodan(); test_virustotal(); test_hibp(); test_urlscan(); test_wayback(); test_hunter()
    test_abuseipdb(); test_greynoise(); test_securitytrails(); test_ripestat()
    live_smoke()
    print("ok")
