"""Maltego transform wire protocol, as implemented by maltego-trx 1.7.0 (see docs/REA-FINDINGS.md).

Remote:  POST <MaltegoMessage><MaltegoTransformRequestMessage>... -> <MaltegoTransformResponseMessage> XML.
Local:   argv = [command, *params, value, "k=v#k2=v2"]  -> same response XML on stdout.
"""
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import SubElement as sub

# Our canonical EntityType -> Maltego entity type id.
TO_MALTEGO = {
    "Phrase": "maltego.Phrase", "Person": "maltego.Person", "Website": "maltego.Website",
    "URL": "maltego.URL", "EmailAddress": "maltego.EmailAddress", "PhoneNumber": "maltego.PhoneNumber",
    "Location": "maltego.Location", "Company": "maltego.Company", "Affiliation": "maltego.Affiliation",
    "Snapshot": "maltego.Snapshot", "Domain": "maltego.Domain", "IPAddress": "maltego.IPv4Address",
    "Image": "maltego.Image",
}
FROM_MALTEGO = {v.lower(): k for k, v in TO_MALTEGO.items()} | {
    "maltego.organization": "Company", "maltego.ipv6address": "IPAddress", "maltego.dnsname": "Domain",
    "maltego.mxrecord": "Domain", "maltego.nsrecord": "Domain", "maltego.document": "Snapshot",
}


class TransformError(Exception):
    pass


def to_our_type(maltego_type):
    t = maltego_type.lower()
    return FROM_MALTEGO.get(t) or ("Affiliation" if "affiliation" in t else None)


def build_request(entity, settings, limit=256):
    msg = ET.Element("MaltegoMessage")
    req = sub(msg, "MaltegoTransformRequestMessage")
    mtype = TO_MALTEGO.get(entity["type"], "maltego.Phrase")
    e = sub(sub(req, "Entities"), "Entity", Type=mtype)
    sub(sub(e, "Genealogy"), "Type", Name=mtype)
    sub(e, "Value").text = entity["value"]
    sub(e, "Weight").text = "100"
    fields = sub(e, "AdditionalFields")
    for p in entity.get("properties", {}).values():
        sub(fields, "Field", Name=p["name"], DisplayName=p.get("displayName") or p["name"]).text = str(p["value"])
    tf = sub(req, "TransformFields")
    for k, v in settings.items():
        sub(tf, "Field", Name=k).text = v
    sub(req, "Limits", SoftLimit=str(limit), HardLimit=str(limit))
    return ET.tostring(msg, encoding="utf-8")


def _esc(s):  # inverse of maltego_trx MaltegoMsg.buildProperties
    return str(s).replace("\\", "\\\\").replace("#", "\\#").replace("=", "\\=")


def local_args(entity):
    props = entity.get("properties", {}).values()
    # trx crashes on an empty property arg, so omit it when there are none
    return [entity["value"]] + (["#".join(f"{_esc(p['name'])}={_esc(p['value'])}" for p in props)] if props else [])


def parse_response(data):
    """-> (results, messages). Each result: {type, value, properties, icon, notes, link: {label, reverse}}."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    start, end = data.find("<MaltegoMessage"), data.rfind("</MaltegoMessage>")
    if start < 0 or end < 0:
        raise TransformError(f"no MaltegoMessage in output: {data[:300]!r}")
    root = ET.fromstring(data[start:end + len("</MaltegoMessage>")])  # expat: no external entities

    exc = [x.text or "" for x in root.iter("Exception")]
    if exc:
        raise TransformError("; ".join(exc))

    results = []
    for e in root.iter("Entity"):
        mtype = e.get("Type", "maltego.Phrase")
        ours = to_our_type(mtype)
        r = {"type": ours or "Phrase", "value": (e.findtext("Value") or "").strip(), "properties": {},
             "icon": e.findtext("IconURL"), "notes": None, "link": {"label": None, "reverse": False}}
        if not ours:
            r["properties"]["maltego.type"] = {"name": "maltego.type", "value": mtype,
                                               "displayName": "Maltego Type", "isReadOnly": True}
        for f in e.iter("Field"):
            name, val = f.get("Name", ""), f.text or ""
            if name == "link#maltego.link.label":
                r["link"]["label"] = val
            elif name == "link#maltego.link.direction":
                r["link"]["reverse"] = val == "output-to-input"
            elif name == "notes#":
                r["notes"] = val
            elif not name.startswith("link#"):  # ponytail: link color/style/thickness dropped
                r["properties"][name] = {"name": name, "value": val, "displayName": f.get("DisplayName") or name}
        for lbl in e.iter("Label"):
            n = f"display.{lbl.get('Name', 'Info')}"
            r["properties"][n] = {"name": n, "value": lbl.text or "", "displayName": lbl.get("Name", "Info"),
                                  "isReadOnly": True}
        if r["value"]:
            results.append(r)
    messages = [{"type": m.get("MessageType", "Inform"), "text": m.text or ""} for m in root.iter("UIMessage")]
    return results, messages
