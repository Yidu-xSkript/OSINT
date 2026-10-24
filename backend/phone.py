"""Phone-number OSINT transforms (bring-your-own-key). Same contract as builtin.py.

What these legitimately yield: validity, country, carrier, line type (mobile/landline/VoIP), and — via a
CNAM lookup — the *caller name* the carrier publishes. They do NOT return a person's address, accounts, or
location. Deeper "who holds this number" lookups rely on people-search databases whose use is restricted by
law (FCRA/GDPR) and consent; this tool does not scrape them.
"""
import base64, urllib.error, urllib.parse

from builtin import fetch_json, transform


@transform("phone-parse", "To Details [libphonenumber]", "PhoneNumber",
           "Offline, no key: validity, region, carrier, line type, timezone (Google libphonenumber)",
           classification="derived")
def _(v, p, s):
    try:
        import phonenumbers
        from phonenumbers import PhoneNumberType, carrier, geocoder, number_type, timezone
    except ImportError:
        raise ValueError("the 'phonenumbers' package is not installed (pip install phonenumbers)")
    try:
        n = phonenumbers.parse(v, None)  # needs a +country-code; region-less otherwise
    except phonenumbers.NumberParseException as e:
        raise ValueError(f"could not parse '{v}' — include the country code, e.g. +1…: {e}")
    if not phonenumbers.is_valid_number(n):
        return [("Phrase", f"not a valid number: {v}", "Validation")]
    TYPES = {PhoneNumberType.FIXED_LINE: "fixed line", PhoneNumberType.MOBILE: "mobile",
             PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed line or mobile", PhoneNumberType.TOLL_FREE: "toll free",
             PhoneNumberType.PREMIUM_RATE: "premium rate", PhoneNumberType.VOIP: "VoIP",
             PhoneNumberType.SHARED_COST: "shared cost", PhoneNumberType.PERSONAL_NUMBER: "personal",
             PhoneNumberType.PAGER: "pager", PhoneNumberType.UAN: "UAN", PhoneNumberType.VOICEMAIL: "voicemail"}
    region = geocoder.description_for_number(n, "en")
    car = carrier.name_for_number(n, "en")  # empty where number portability hides it (e.g. US)
    tz = ", ".join(timezone.time_zones_for_number(n))
    intl = phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    out = [("PhoneNumber", intl, "Normalized", {
        "valid": True, "line_type": TYPES.get(number_type(n), "unknown"),
        "country_code": f"+{n.country_code}", "region": region, "carrier": car or "(needs a live dip)",
        "timezone": tz, "national": phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.NATIONAL)})]
    if region:
        out.append(("Location", region, "Registered Region"))
    if car:
        out.append(("Company", car, "Carrier (metadata)"))
    return out


def _prop(name, value):
    return {name: value}


@transform("phone-numverify", "To Carrier & Country [numverify]", "PhoneNumber",
           "Validate and enrich: country, carrier, line type (apilayer numverify)", settings=["numverify.apikey"])
def _(v, p, s):
    key = s.get("numverify.apikey")
    if not key:
        raise ValueError("set numverify.apikey in Transforms → API Keys")
    num = urllib.parse.quote(v.strip())
    j = fetch_json(f"https://apilayer.net/api/validate?access_key={urllib.parse.quote(key)}&number={num}")
    if j.get("success") is False:
        raise ValueError(j.get("error", {}).get("info", "numverify error"))
    if not j.get("valid"):
        return [("Phrase", f"invalid number: {v}", "Validation")]
    out = [("PhoneNumber", j.get("international_format") or v, "Normalized",
            {"valid": True, "line_type": j.get("line_type"), "carrier": j.get("carrier"),
             "country": j.get("country_name"), "location": j.get("location")})]
    if j.get("carrier"):
        out.append(("Company", j["carrier"], "Carrier"))
    if j.get("country_name"):
        out.append(("Location", ", ".join(x for x in (j.get("location"), j.get("country_name")) if x), "Registered In"))
    return out


@transform("phone-twilio", "To Caller Name & Line Type [Twilio Lookup]", "PhoneNumber",
           "Carrier, line type, and published caller name (CNAM). Keys: twilio.sid + twilio.token",
           settings=["twilio.sid", "twilio.token"])
def _(v, p, s):
    sid, token = s.get("twilio.sid"), s.get("twilio.token")
    if not (sid and token):
        raise ValueError("set twilio.sid and twilio.token in Transforms → API Keys")
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    num = urllib.parse.quote(v.strip())
    try:
        j = fetch_json(f"https://lookups.twilio.com/v2/PhoneNumbers/{num}?Fields=caller_name,line_type_intelligence",
                       headers={"Authorization": f"Basic {auth}"})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return [("Phrase", f"not found: {v}", "Lookup")]
        raise
    out = []
    cn = (j.get("caller_name") or {}).get("caller_name")
    if cn:
        out.append(("Person", cn, "Caller Name (CNAM)", {"caller_type": (j.get("caller_name") or {}).get("caller_type")}))
    lt = j.get("line_type_intelligence") or {}
    norm = j.get("phone_number") or v
    out.append(("PhoneNumber", norm, "Normalized",
                {"line_type": lt.get("type"), "carrier": lt.get("carrier_name"), "country": j.get("country_code")}))
    if lt.get("carrier_name"):
        out.append(("Company", lt["carrier_name"], "Carrier"))
    return out


@transform("phone-hlr", "To HLR / Live Status [IPQualityScore]", "PhoneNumber",
           "HLR-backed: active status, current carrier, line type, network (MCC/MNC), and name when available",
           settings=["ipqs.apikey"])
def _(v, p, s):
    key = s.get("ipqs.apikey")
    if not key:
        raise ValueError("set ipqs.apikey in Transforms → API Keys (free tier at ipqualityscore.com)")
    num = urllib.parse.quote(v.strip())
    j = fetch_json(f"https://ipqualityscore.com/api/json/phone/{urllib.parse.quote(key)}/{num}")
    if not j.get("success", True):
        raise ValueError(j.get("message", "IPQualityScore error"))
    norm = j.get("formatted") or v
    props = {k: j[k] for k in ("valid", "active", "carrier", "line_type", "country", "region", "city",
                               "timezone", "fraud_score", "recent_abuse", "VOIP", "prepaid", "risky",
                               "leaked", "do_not_call", "mcc", "mnc", "active_status") if j.get(k) not in (None, "")}
    out = [("PhoneNumber", norm, "HLR Lookup", props)]
    # IPQS 'name' is a CNAM-style name when its data has one — the closest to free caller ID
    if j.get("name") and j["name"] not in ("N/A", "Unknown"):
        out.append(("Person", j["name"], "Associated Name (CNAM-style)"))
    if j.get("carrier"):
        out.append(("Company", j["carrier"], "Carrier (HLR)"))
    loc = ", ".join(x for x in (j.get("city"), j.get("region"), j.get("country")) if x)
    if loc:
        out.append(("Location", loc, "Registered In"))
    return out


@transform("phone-reverse-search", "To Reverse-Search [web]", "PhoneNumber",
           "Free CNAM-by-OSINT: number in common formats + ready search links (people post their own numbers)")
def _(v, p, s):
    # Build the formats a number gets published in, then pre-made searches. No key, nothing fetched.
    digits = "".join(c for c in v if c.isdigit())
    formats = {v.strip(), "+" + digits, digits}
    try:
        import phonenumbers
        n = phonenumbers.parse(v, None)
        for fmt in (phonenumbers.PhoneNumberFormat.E164, phonenumbers.PhoneNumberFormat.INTERNATIONAL,
                    phonenumbers.PhoneNumberFormat.NATIONAL):
            formats.add(phonenumbers.format_number(n, fmt))
        nat = "".join(c for c in phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.NATIONAL) if c.isdigit())
        if len(nat) == 10:  # US-style (415) 555-0100 / 415-555-0100 / 415.555.0100
            formats |= {f"({nat[:3]}) {nat[3:6]}-{nat[6:]}", f"{nat[:3]}-{nat[3:6]}-{nat[6:]}",
                        f"{nat[:3]}.{nat[3:6]}.{nat[6:]}"}
    except Exception:
        pass
    formats = sorted(f for f in formats if f)
    out = [("Phrase", f, "Number Format") for f in formats]

    q = urllib.parse.quote(f'"{"+" + digits}"')
    social = urllib.parse.quote(
        f'("{"+" + digits}" OR "{digits}") (site:instagram.com OR site:facebook.com OR site:twitter.com OR site:linkedin.com)')
    out += [
        ("URL", f"https://www.google.com/search?q={q}", "Google (quoted number)"),
        ("URL", f"https://duckduckgo.com/?q={q}", "DuckDuckGo"),
        ("URL", f"https://www.bing.com/search?q={q}", "Bing"),
        ("URL", f"https://www.google.com/search?q={social}", "Google (social profiles)"),
        ("URL", f"https://www.truepeoplesearch.com/results?phoneno={urllib.parse.quote(digits)}", "TruePeopleSearch"),
    ]
    return out


@transform("phone-country", "To Country Code", "PhoneNumber", "Country from the dialing prefix (offline, no key)")
def _(v, p, s):
    # ponytail: tiny prefix table for the common cases; numverify covers the rest accurately
    digits = "".join(c for c in v if c.isdigit())
    table = {"1": "North America (US/Canada)", "44": "United Kingdom", "33": "France", "49": "Germany",
             "61": "Australia", "81": "Japan", "86": "China", "91": "India", "7": "Russia/Kazakhstan",
             "55": "Brazil", "27": "South Africa", "34": "Spain", "39": "Italy", "31": "Netherlands",
             "46": "Sweden", "47": "Norway", "971": "UAE", "972": "Israel", "852": "Hong Kong", "65": "Singapore"}
    if v.strip().startswith("+") or digits.startswith("00"):
        for n in (3, 2, 1):
            pre = digits[:n]
            if pre in table:
                return [("Location", table[pre], "Dialing Prefix", {"country_code": "+" + pre})]
    return [("Phrase", "unknown prefix — run To Carrier & Country [numverify]", "Prefix")]
