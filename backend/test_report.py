"""Offline self-check for report.py:  python test_report.py"""
import report


def _graph():
    ents = [
        {"id": "a", "type": "Domain", "value": "python.org", "label": None,
         "properties": {"whois": {"name": "whois", "value": "Gandi", "displayName": "WHOIS"}},
         "metadata": {"createdAt": 1, "discoveredByTransform": None, "notes": "primary target"}},
        {"id": "b", "type": "IPAddress", "value": "1.2.3.4", "label": None,
         "properties": {"location.coordinates": {"name": "location.coordinates", "value": "37.7,-122.4", "displayName": "Coords"}},
         "metadata": {"createdAt": 2, "discoveredByTransform": "To IP [DNS]", "notes": None}},
        {"id": "c", "type": "Image", "value": "evidence.jpg", "label": None,
         "properties": {"image.id": {"name": "image.id", "value": "img123", "displayName": "Image", "isReadOnly": True}},
         "metadata": {"createdAt": 3, "discoveredByTransform": None, "notes": "street view"}},
    ]
    links = [{"id": "l", "sourceId": "a", "targetId": "b", "label": "Resolves To", "direction": "source-to-target"}]
    return {"entities": ents, "links": links}


EV = {"b": [{"id": "e1", "transform": "To IP [DNS]", "url": "https://dns/x", "fetchedAt": 1_700_000_000_000,
             "status": 200, "sha256": "deadbeef" * 8, "size": 7937}]}


def test_markdown():
    md = report.build_markdown("Operation Nightfall", _graph(), EV)
    assert "# Case Report: Operation Nightfall" in md
    assert "python.org" in md and "**Domain**: 1" in md
    assert "## Evidence Trail" in md and "deadbeef" * 8 in md and "https://dns/x" in md
    assert "## Verified Coordinates" in md and "37.7,-122.4" in md
    assert "Resolves To" in md and "primary target" in md


def test_html():
    h = report.build_html("Op <Night>", _graph(), EV)  # name has a < to test escaping
    assert "<title>Case Report: Op &lt;Night&gt;</title>" in h
    assert '/api/images/img123' in h  # evidence image embedded
    assert "Evidence Trail" in h and "deadbeef" * 8 in h
    assert "37.7,-122.4" in h and "window.print()" in h
    # no raw unescaped angle brackets from the name leaked
    assert "Op <Night>" not in h.replace("Op &lt;Night&gt;", "")


def test_empty():
    md = report.build_markdown("Empty", {"entities": [], "links": []}, {})
    assert "# Case Report: Empty" in md and "0 entities" in md


if __name__ == "__main__":
    test_markdown(); test_html(); test_empty()
    print("ok")
