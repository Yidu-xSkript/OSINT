"""Security bundle: evidence-URL redaction, secret at-rest sealing, import hardening."""
import os
import tempfile

import maltego_import as M
import secretstore
from store import Store, _redact_url


def test_url_redaction():
    assert "REDACTED" in _redact_url("https://ipinfo.io/1.1.1.1/json?token=SECRET")
    assert "SECRET" not in _redact_url("https://ipinfo.io/1.1.1.1/json?token=SECRET")
    assert "REDACTED" in _redact_url("https://x/?apikey=a&q=b")
    assert _redact_url("https://crt.sh/?q=example.com") == "https://crt.sh/?q=example.com"  # no secret, untouched


def test_secret_not_plaintext_at_rest():
    s = Store(os.path.join(tempfile.mkdtemp(), "x.db"))
    s.set_setting("hibp.apikey", "sk-live-DEADBEEF", True)
    raw = {r["name"]: r["value"] for r in s.q("select * from settings")}
    if secretstore.available():
        assert "DEADBEEF" not in raw["hibp.apikey"]        # sealed on Windows
        assert raw["hibp.apikey"].startswith("dpapi:")
    assert s.settings()["hibp.apikey"] == "sk-live-DEADBEEF"  # transforms still get plaintext
    assert {d["name"]: d["value"] for d in s.settings_public()}["hibp.apikey"] is None  # masked to the UI


def test_import_rejects_doctype():
    bomb = b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "A">]><graphml>&a;</graphml>'
    try:
        M._xml(bomb)
        raise AssertionError("DOCTYPE should be rejected")
    except ValueError:
        pass
    assert M._xml(b"<graphml><graph></graph></graphml>") is not None  # normal XML still parses


if __name__ == "__main__":
    test_url_redaction()
    test_secret_not_plaintext_at_rest()
    test_import_rejects_doctype()
    print("ok")
