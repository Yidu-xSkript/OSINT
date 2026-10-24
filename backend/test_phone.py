"""Offline self-check for phone.py:  python test_phone.py"""
import builtin, phone


def test_numverify():
    phone.fetch_json = lambda url, headers=None: {  # type: ignore
        "valid": True, "international_format": "+14155550100", "country_name": "United States",
        "location": "Novato", "carrier": "AT&T Mobility", "line_type": "mobile"}
    out = builtin.BUILTINS["phone-numverify"]["fn"]("+1 415 555 0100", {}, {"numverify.apikey": "k"})
    kinds = {t: v for t, v, *_ in out}
    assert kinds["PhoneNumber"] == "+14155550100"
    assert kinds["Company"] == "AT&T Mobility" and "United States" in kinds["Location"]
    props = next(e[3] for e in out if e[0] == "PhoneNumber")
    assert props["line_type"] == "mobile"
    try:
        builtin.BUILTINS["phone-numverify"]["fn"]("x", {}, {})
        assert False
    except ValueError:
        pass


def test_twilio():
    phone.fetch_json = lambda url, headers=None: {  # type: ignore
        "phone_number": "+14155550100", "country_code": "US",
        "caller_name": {"caller_name": "JANE DOE", "caller_type": "CONSUMER"},
        "line_type_intelligence": {"type": "mobile", "carrier_name": "Verizon"}}
    out = builtin.BUILTINS["phone-twilio"]["fn"]("+14155550100", {}, {"twilio.sid": "s", "twilio.token": "t"})
    kinds = {t: v for t, v, *_ in out}
    assert kinds["Person"] == "JANE DOE" and kinds["Company"] == "Verizon"
    try:
        builtin.BUILTINS["phone-twilio"]["fn"]("x", {}, {"twilio.sid": "s"})
        assert False
    except ValueError:
        pass


def test_parse_offline():
    # real libphonenumber, no mock, no network
    out = builtin.BUILTINS["phone-parse"]["fn"]("+1 415 555 0100", {}, {})
    norm = next(e for e in out if e[0] == "PhoneNumber")
    assert norm[3]["country_code"] == "+1" and "San Francisco" in norm[3]["region"]
    assert norm[3]["line_type"] in ("fixed line", "mobile", "fixed line or mobile")
    uk = builtin.BUILTINS["phone-parse"]["fn"]("+447911123456", {}, {})
    assert next(e for e in uk if e[0] == "PhoneNumber")[3]["line_type"] == "mobile"
    assert builtin.BUILTINS["phone-parse"]["fn"]("+1 000", {}, {})[0][1].startswith("not a valid")
    try:
        builtin.BUILTINS["phone-parse"]["fn"]("garbage", {}, {})
        assert False
    except ValueError:
        pass


def test_hlr():
    phone.fetch_json = lambda url, headers=None: {  # type: ignore
        "success": True, "formatted": "+14155550100", "valid": True, "active": True,
        "carrier": "T-Mobile USA", "line_type": "Wireless", "country": "US", "region": "California",
        "city": "San Francisco", "fraud_score": 25, "name": "JANE DOE", "mcc": "310", "mnc": "260"}
    out = builtin.BUILTINS["phone-hlr"]["fn"]("+14155550100", {}, {"ipqs.apikey": "k"})
    kinds = {t: v for t, v, *_ in out}
    assert kinds["Person"] == "JANE DOE" and kinds["Company"] == "T-Mobile USA"
    props = next(e[3] for e in out if e[0] == "PhoneNumber")
    assert props["active"] is True and props["mcc"] == "310"
    try:
        builtin.BUILTINS["phone-hlr"]["fn"]("x", {}, {})
        assert False
    except ValueError:
        pass


def test_reverse_search():
    out = builtin.BUILTINS["phone-reverse-search"]["fn"]("+1 415 555 0100", {}, {})
    fmts = {v for t, v, *_ in out if t == "Phrase"}
    urls = {lbl: v for t, v, lbl, *_ in out if t == "URL"}
    assert "+14155550100" in fmts and "(415) 555-0100" in fmts  # E.164 + US national
    assert any("google.com/search" in u for u in urls.values()) and "TruePeopleSearch" in urls
    assert all(u.startswith("http") for u in urls.values())


def test_country_offline():
    out = builtin.BUILTINS["phone-country"]["fn"]("+44 20 7946 0958", {}, {})
    assert out[0][0] == "Location" and "United Kingdom" in out[0][1]
    assert builtin.BUILTINS["phone-country"]["fn"]("12345", {}, {})[0][0] == "Phrase"  # no + prefix


if __name__ == "__main__":
    test_parse_offline()
    test_numverify()
    test_twilio()
    test_hlr()
    test_reverse_search()
    test_country_offline()
    print("ok")
