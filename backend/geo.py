"""Geospatial transforms — the God's Eye View bridge.

Two halves:
  - Data: call the same public upstreams GEV uses (adsb.lol aircraft, OSM Overpass venues, Nominatim
    geocoding) directly, so this tool stays self-contained (no GEV server to run).
  - Visualization: "Show on God's Eye View" emits a URL that opens GEV centered on the coordinates
    (GEV camera hash: #lat=..&lon=..&alt=..&pitch=..). Set gev.url (default http://localhost:5173).

Input is a Location that has coordinates — from ip-geo, from To Coordinates [Nominatim], or a value
literally "lat,lon". Attribution: aircraft © adsb.lol · map data © OpenStreetMap contributors · globe © God's Eye View (Bilawal Sidhu).
"""
import json, re, urllib.error, urllib.parse

from builtin import fetch, fetch_json, transform

OVERPASS_MIRRORS = [  # GEV rotates these too; the public one is often "too busy"
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]
# OSM selectors per venue category (ChronoSight venue types map straight onto these).
VENUE_TAGS = {
    "hookah": '["leisure"="hookah_lounge"],["amenity"="hookah_lounge"],["smoking"="dedicated"]',
    "bar": '["amenity"="bar"],["amenity"="pub"]',
    "nightclub": '["amenity"="nightclub"]',
    "cafe": '["amenity"="cafe"],["amenity"="coffee_shop"]',
    "restaurant": '["amenity"="restaurant"]',
    "hotel": '["tourism"="hotel"]',
    "any": '["amenity"],["shop"],["tourism"],["leisure"]',
}
LATLON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def coords_of(value, props):
    """(lat, lon) from a Location entity: a coord property, lat+lon props, or a 'lat,lon' value."""
    for key in ("location.coordinates", "coordinates", "gps.coordinate", "latitude,longitude"):
        pv = props.get(key)
        raw = pv.get("value") if isinstance(pv, dict) else pv
        if isinstance(raw, str) and LATLON.match(raw):
            m = LATLON.match(raw)
            return float(m.group(1)), float(m.group(2))
    lat = props.get("latitude") or props.get("lat")
    lon = props.get("longitude") or props.get("lon") or props.get("lng")
    lat = lat.get("value") if isinstance(lat, dict) else lat
    lon = lon.get("value") if isinstance(lon, dict) else lon
    try:
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and LATLON.match(value):
        m = LATLON.match(value)
        return float(m.group(1)), float(m.group(2))
    raise ValueError("this Location has no coordinates — run To Coordinates [Nominatim] first")


@transform("geo-geocode", "To Coordinates [Nominatim]", "Location",
           "Geocode a place name to lat/lon (OpenStreetMap Nominatim, no key)")
def _(v, p, s):
    j = fetch_json(f"https://nominatim.openstreetmap.org/search?{urllib.parse.urlencode({'q': v, 'format': 'json', 'limit': 1})}",
                   headers={"User-Agent": "osint-graph/1.0"})
    if not j:
        return [("Phrase", f"no geocoding result for: {v}", "Geocode")]
    r = j[0]
    lat, lon = r["lat"], r["lon"]
    # enrich the Location itself so the other geo transforms can use it
    return [("Location", v, "", {"location.coordinates": f"{lat},{lon}", "latitude": lat, "longitude": lon,
                                 "osm.display_name": r.get("display_name", "")})]


@transform("geo-aircraft", "To Aircraft Overhead [ADS-B]", "Location",
           "Live aircraft within a radius (adsb.lol, no key)", settings=["geo.radius_nm"])
def _(v, p, s):
    lat, lon = coords_of(v, p)
    nm = _int(s.get("geo.radius_nm"), 25, 1, 250)
    j = fetch_json(f"https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{nm}")
    out = []
    for a in (j.get("ac") or [])[:200]:
        call = (a.get("flight") or a.get("r") or a.get("hex") or "?").strip()
        label = f"{call} ({a.get('t', '?')})"
        out.append(("Phrase", label, "Aircraft Overhead",
                    {"callsign": call, "type": a.get("t"), "registration": a.get("r"),
                     "altitude": a.get("alt_baro"), "ground_speed": a.get("gs"), "squawk": a.get("squawk"),
                     "icao24": a.get("hex"), "lat": a.get("lat"), "lon": a.get("lon")}))
    return out or [("Phrase", f"no aircraft within {nm} nm", "Aircraft Overhead")]


@transform("geo-venues", "To Nearby Venues [OSM]", "Location",
           "Venues around the point (OpenStreetMap Overpass). geo.venue_type: hookah/bar/nightclub/cafe/restaurant/hotel/any",
           settings=["geo.venue_type", "geo.radius_m"])
def _(v, p, s):
    lat, lon = coords_of(v, p)
    kind = (s.get("geo.venue_type") or "any").lower()
    tags = VENUE_TAGS.get(kind, VENUE_TAGS["any"])
    radius = _int(s.get("geo.radius_m"), 1000, 50, 20000)
    parts = "".join(f"nwr(around:{radius},{lat},{lon}){t};" for t in tags.split(","))
    query = f"[out:json][timeout:25];({parts});out center 200;"
    data = _overpass(query)
    out = []
    for e in data.get("elements", [])[:200]:
        tg = e.get("tags", {})
        name = tg.get("name")
        if not name:
            continue
        c = e.get("center") or {}
        plat, plon = e.get("lat") or c.get("lat"), e.get("lon") or c.get("lon")
        addr = ", ".join(x for x in (tg.get("addr:housenumber", "") + " " + tg.get("addr:street", "").strip(),
                                     tg.get("addr:city"), tg.get("addr:postcode")) if x and x.strip())
        props = {"category": tg.get("amenity") or tg.get("leisure") or tg.get("shop") or tg.get("tourism"),
                 "address": addr, "coordinates": f"{plat},{plon}" if plat else "",
                 "website": tg.get("website") or tg.get("contact:website"),
                 "phone": tg.get("phone") or tg.get("contact:phone"),
                 "instagram": tg.get("contact:instagram"), "osm": f"{e.get('type')}/{e.get('id')}",
                 "candidate.status": "Unreviewed"}  # auto-adds venues to the candidate funnel
        out.append(("Location", name, "Nearby Venue", {k: val for k, val in props.items() if val}))
        if props.get("website"):
            out.append(("URL", props["website"], "Venue Website"))
    return out or [("Phrase", f"no {kind} venues within {radius} m", "Nearby Venue")]


@transform("geo-globe", "Show on God's Eye View", "Location",
           "Open the 3D globe (God's Eye View) centered on this location", settings=["gev.url"])
def _(v, p, s):
    lat, lon = coords_of(v, p)
    base = (s.get("gev.url") or "http://localhost:4173").rstrip("/")
    frag = urllib.parse.urlencode({"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "alt": 1200, "pitch": -35,
                                   "heading": 0, "map": "photoreal"})
    return [("URL", f"{base}/#{frag}", "View on God's Eye View")]


def _overpass(query):
    # fetch() is GET-only; Overpass accepts the query as ?data=. Rotate mirrors — the public one is often busy.
    err = None
    url_q = urllib.parse.urlencode({"data": query})
    for base in OVERPASS_MIRRORS:
        try:
            data, _ = fetch(f"{base}?{url_q}", limit=50_000_000, headers={"User-Agent": "osint-graph/1.0"})
            return json.loads(data)
        except (urllib.error.HTTPError, json.JSONDecodeError, urllib.error.URLError) as e:
            err = e
    raise ValueError(f"all Overpass mirrors failed (they are often busy — retry): {err}")


def _int(v, default, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default
