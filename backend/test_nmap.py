"""Nmap adapter: XML parsing, target validation, scope caps, and the authorization gate (offline)."""
import nmap_scan as N

SAMPLE = b"""<?xml version="1.0"?>
<nmaprun>
 <host><status state="up"/><address addr="93.184.216.34" addrtype="ipv4"/>
  <hostnames><hostname name="example.com" type="PTR"/></hostnames>
  <ports>
   <port protocol="tcp" portid="22"><state state="open"/><service name="ssh" product="OpenSSH" version="8.9"/></port>
   <port protocol="tcp" portid="443"><state state="open"/><service name="https" tunnel="ssl" product="nginx"/></port>
   <port protocol="tcp" portid="81"><state state="closed"/><service name="hosts2-ns"/></port>
  </ports></host>
 <host><status state="down"/><address addr="10.0.0.9" addrtype="ipv4"/></host>
</nmaprun>"""


def test_parse_xml():
    hosts = N.parse_xml(SAMPLE)
    assert len(hosts) == 1                                   # the "down" host is dropped
    h = hosts[0]
    assert h["ip"] == "93.184.216.34" and h["hostnames"] == ["example.com"]
    ports = {s["port"]: s for s in h["services"]}
    assert set(ports) == {"22", "443"}                       # closed port 81 excluded
    assert ports["443"]["url"] == "https://93.184.216.34:443"
    assert "OpenSSH 8.9" in h["ports_summary"] and "443/tcp https" in h["ports_summary"]


def test_doctype_rejected():
    try:
        N.parse_xml(b'<!DOCTYPE x><nmaprun></nmaprun>')
        raise AssertionError("DOCTYPE should be rejected")
    except N.ScanError:
        pass


def test_target_validation_and_scope():
    for ok in ["1.2.3.4", "10.0.0.0/24", "example.com", "a-b.sub.example.co.uk", "::1"]:
        assert N.valid_target(ok), ok
    for bad in ["-sS", "--script=x", "1.2.3.4; rm -rf", "a b", ""]:
        assert not N.valid_target(bad), bad
    assert N.host_count(["10.0.0.0/24"]) == 256
    # a /23 is 512 hosts -> over the cap
    try:
        N.scan(["10.0.0.0/23"], "fast", {})
        raise AssertionError("should reject oversized scope")
    except N.ScanError as e:
        assert "scope too large" in str(e)


def test_unknown_profile_and_missing_tool():
    try:
        N.scan(["1.2.3.4"], "nope", {})
        raise AssertionError("unknown profile")
    except N.ScanError:
        pass
    # bogus explicit path -> not found (deterministic even if nmap is installed)
    try:
        N.scan(["1.2.3.4"], "fast", {"nmap.path": r"C:\no\nmap.exe"})
        raise AssertionError("should refuse without the tool")
    except N.ScanError as e:
        assert "Nmap not found" in str(e)


def test_authorization_gate():
    from fastapi.testclient import TestClient
    import app as A
    c = TestClient(A.app, base_url="http://localhost")
    gid = c.post("/api/graphs", json={"name": "scan-test"}).json()["id"]
    try:
        r = c.post(f"/api/graphs/{gid}/scan", json={"targets": ["1.2.3.4"], "profile": "fast", "authorized": False})
        assert r.status_code == 400 and "uthoriz" in r.text, (r.status_code, r.text)
        profs = {p["id"] for p in c.get("/api/scan/profiles").json()}
        assert {"discovery", "fast", "standard", "service"} <= profs
    finally:
        c.delete(f"/api/graphs/{gid}")


if __name__ == "__main__":
    test_parse_xml(); test_doctype_rejected(); test_target_validation_and_scope()
    test_unknown_profile_and_missing_tool(); test_authorization_gate()
    print("ok")
