"""theHarvester adapter: report parsing + needs-setup path (offline — no tool run)."""
import harvester
from builtin import BUILTINS

SAMPLE = {
    "emails": ["ceo@example.com", "Info@Example.com"],
    "hosts": ["www.example.com:93.184.216.34", "mail.example.com", "dup.example.com:1.2.3.4"],
    "ips": ["93.184.216.34", "8.8.8.8"],            # 93.184… duplicates a host IP
    "interesting_urls": ["https://example.com/admin"],
    "urls": ["not-a-url"],                           # skipped — not http
}


def test_parse_report():
    rows = harvester.parse_report("example.com", SAMPLE)
    by = {}
    for typ, val, label, props in rows:
        by.setdefault(typ, []).append(val)
    assert sorted(by["EmailAddress"]) == ["ceo@example.com", "info@example.com"]       # lowercased
    assert "www.example.com" in by["Domain"] and "mail.example.com" in by["Domain"]
    assert "93.184.216.34" in by["IPAddress"] and "8.8.8.8" in by["IPAddress"]
    assert by["IPAddress"].count("93.184.216.34") == 1                                  # deduped across hosts+ips
    assert by["URL"] == ["https://example.com/admin"]                                   # non-http dropped
    # no stray values
    assert len(rows) == len(set((t, v) for t, v, _, _ in rows))


def test_needs_setup_when_not_installed():
    fn = BUILTINS["theharvester"]["fn"]
    try:
        fn("example.com", {}, {"theharvester.path": r"C:\does\not\exist\theHarvester.exe"})
        raise AssertionError("should refuse when the executable is missing")
    except ValueError as e:
        assert "theHarvester" in str(e)


if __name__ == "__main__":
    test_parse_report()
    test_needs_setup_when_not_installed()
    print("ok")
