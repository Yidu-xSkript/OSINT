"""Offline self-check for chrono.py:  python test_chrono.py"""
import datetime as dt

import builtin, chrono


def test_sun_math():
    # Greenwich summer-solstice noon: sun ~62° up, due south (~180°)
    e, a = chrono.sun_position(51.48, 0.0, dt.datetime(2023, 6, 21, 12, 0, tzinfo=dt.timezone.utc))
    assert 59 < e < 64 and 175 < a < 185
    # night: below horizon
    e2, _ = chrono.sun_position(51.48, 0.0, dt.datetime(2023, 6, 21, 0, 0, tzinfo=dt.timezone.utc))
    assert e2 < 0
    # morning sun in the east, afternoon in the west
    _, am = chrono.sun_position(51.48, 0.0, dt.datetime(2023, 6, 21, 8, 0, tzinfo=dt.timezone.utc))
    _, pm = chrono.sun_position(51.48, 0.0, dt.datetime(2023, 6, 21, 16, 0, tzinfo=dt.timezone.utc))
    assert am < 180 < pm
    # sunrise matches the published Leeds value (07:57 UTC)
    r, s, _ = chrono._times(53.8, -1.55, dt.datetime(2022, 11, 29, tzinfo=dt.timezone.utc))
    assert r.strftime("%H:%M") == "07:57" and s > r


def test_parse_dt():
    assert chrono._parse_dt("2022-11-29T18:11").hour == 18
    assert chrono._parse_dt("2022-11-29 18:11:30").minute == 11
    assert chrono._parse_dt("2022-11-29").hour == 0
    try:
        chrono._parse_dt("not a date")
        assert False
    except ValueError:
        pass


def test_sun_transform():
    props = {"location.coordinates": {"name": "location.coordinates", "value": "51.48,0.0",
                                      "displayName": "Coords"}}
    out = builtin.BUILTINS["chrono-sun"]["fn"]("Greenwich", props, {"chrono.datetime": "2023-06-21T12:00"})
    loc = out[0][3]
    assert "°" in loc["sun.elevation"] and "sunrise" not in loc or loc.get("sun.sunrise")
    assert loc["sun.shadow_direction"] != "n/a (sun below horizon)"  # daytime
    assert out[1][0] == "Phrase" and "shadows fall" in out[1][1]
    # no coordinates -> clear error
    try:
        builtin.BUILTINS["chrono-sun"]["fn"]("Nowhere", {}, {})
        assert False
    except ValueError:
        pass


def test_weather_transform():
    chrono.fetch_json = lambda url, headers=None: {  # type: ignore
        "daily": {"time": ["2022-11-29"], "temperature_2m_max": [4.6], "temperature_2m_min": [1.2],
                  "precipitation_sum": [0.0], "weathercode": [3]},
        "hourly": {"cloudcover": [100] * 24, "temperature_2m": [3] * 24}}
    props = {"location.coordinates": {"name": "location.coordinates", "value": "53.8,-1.55", "displayName": "C"}}
    out = builtin.BUILTINS["chrono-weather"]["fn"]("Leeds", props, {"chrono.datetime": "2022-11-29T12:00"})
    w = out[0][3]
    assert w["weather.temp_max"] == "4.6°C" and w["weather.condition"] == "overcast"
    assert "100% at 12:00" in w["weather.cloud_cover"]
    assert "2022-11-29" in out[1][1] and "cloud" in out[1][1]


if __name__ == "__main__":
    test_sun_math(); test_parse_dt(); test_sun_transform(); test_weather_transform()
    print("ok")
