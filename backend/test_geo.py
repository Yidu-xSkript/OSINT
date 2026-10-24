"""Offline self-check for geo.py (GEV bridge):  python test_geo.py"""
import builtin, geo


def test_coords_of():
    assert geo.coords_of("x", {"location.coordinates": {"value": "37.77,-122.41"}}) == (37.77, -122.41)
    assert geo.coords_of("51.5,-0.12", {}) == (51.5, -0.12)
    assert geo.coords_of("x", {"latitude": {"value": "1.5"}, "longitude": {"value": "2.5"}}) == (1.5, 2.5)
    try:
        geo.coords_of("London", {})
        assert False
    except ValueError:
        pass


def test_globe_offline():
    out = builtin.BUILTINS["geo-globe"]["fn"]("Here", {"location.coordinates": {"value": "37.7793,-122.4193"}},
                                              {"gev.url": "http://localhost:4173"})
    assert out[0][0] == "URL"
    url = out[0][1]
    assert url.startswith("http://localhost:4173/#") and "lat=37.77930" in url and "lon=-122.41930" in url
    # default base when unset
    d = builtin.BUILTINS["geo-globe"]["fn"]("Here", {"location.coordinates": {"value": "1,2"}}, {})
    assert d[0][1].startswith("http://localhost:4173/#")


def test_aircraft_mocked():
    geo.fetch_json = lambda url, headers=None: {"ac": [  # type: ignore
        {"hex": "ada227", "flight": "UAL123 ", "t": "A321", "alt_baro": 35000, "gs": 450.0, "r": "N123UA",
         "lat": 37.6, "lon": -122.3, "squawk": "1200"}]}
    out = builtin.BUILTINS["geo-aircraft"]["fn"]("x", {"location.coordinates": {"value": "37.77,-122.41"}},
                                                 {"geo.radius_nm": "30"})
    assert out[0][0] == "Phrase" and "UAL123" in out[0][1] and "A321" in out[0][1]
    assert out[0][3]["altitude"] == 35000 and out[0][3]["icao24"] == "ada227"
    # empty result
    geo.fetch_json = lambda url, headers=None: {"ac": []}  # type: ignore
    assert "no aircraft" in builtin.BUILTINS["geo-aircraft"]["fn"]("x", {"location.coordinates": {"value": "1,2"}}, {})[0][1]


def test_geocode_mocked():
    geo.fetch_json = lambda url, headers=None: [{"lat": "53.7974", "lon": "-1.5438",  # type: ignore
                                                 "display_name": "Leeds, West Yorkshire, UK"}]
    out = builtin.BUILTINS["geo-geocode"]["fn"]("Leeds, UK", {}, {})
    assert out[0][0] == "Location" and out[0][3]["location.coordinates"] == "53.7974,-1.5438"


def test_venues_mocked():
    geo._overpass = lambda q: {"elements": [  # type: ignore
        {"type": "node", "id": 1, "lat": 37.78, "lon": -122.42,
         "tags": {"name": "Smoke Lounge", "amenity": "bar", "addr:street": "Main St", "website": "https://x.test"}}]}
    out = builtin.BUILTINS["geo-venues"]["fn"]("x", {"location.coordinates": {"value": "37.77,-122.41"}},
                                               {"geo.venue_type": "bar", "geo.radius_m": "800"})
    kinds = {t: v for t, v, *_ in out}
    assert kinds["Location"] == "Smoke Lounge" and kinds["URL"] == "https://x.test"
    props = next(e[3] for e in out if e[0] == "Location")
    assert props["category"] == "bar" and props["coordinates"] == "37.78,-122.42"


if __name__ == "__main__":
    test_coords_of(); test_globe_offline(); test_aircraft_mocked(); test_geocode_mocked(); test_venues_mocked()
    print("ok")
