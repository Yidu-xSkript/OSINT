"""Temporal / chronolocation transforms.

- To Sun Position [offline]: sunrise, sunset, solar noon, and the sun's azimuth + elevation at a given
  instant (NOAA solar algorithm, no key, no network) — the azimuth tells you which way shadows fall,
  the core of chronolocation shadow analysis.
- To Historical Weather [Open-Meteo]: temperature, precipitation, cloud cover for a past date (free, no key).

Both read the location's coordinates and a case-wide known timestamp from the `chrono.datetime` setting
(ISO 8601 UTC, e.g. 2022-11-29T18:11). Defaults to now when unset.
"""
import datetime as _dt
import math
import urllib.parse

from builtin import fetch_json, transform
from geo import coords_of


def _parse_dt(s):
    if not s:
        return _dt.datetime.now(_dt.timezone.utc)
    s = s.strip().replace("Z", "+00:00")
    try:
        d = _dt.datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                d = _dt.datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"could not parse chrono.datetime {s!r} (use ISO 8601, e.g. 2022-11-29T18:11)")
    return d.replace(tzinfo=_dt.timezone.utc) if d.tzinfo is None else d.astimezone(_dt.timezone.utc)


def _julian(dt):
    y, m = dt.year, dt.month
    d = dt.day + (dt.hour + dt.minute / 60 + dt.second / 3600) / 24
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def _solar(dt):
    """NOAA intermediate solar values -> (declination deg, equation-of-time min)."""
    jc = (_julian(dt) - 2451545.0) / 36525.0
    L0 = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
    M = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    C = (math.sin(math.radians(M)) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
         + math.sin(math.radians(2 * M)) * (0.019993 - 0.000101 * jc)
         + math.sin(math.radians(3 * M)) * 0.000289)
    true_long = L0 + C
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(125.04 - 1934.136 * jc))
    obliq = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
    obliq_corr = obliq + 0.00256 * math.cos(math.radians(125.04 - 1934.136 * jc))
    decl = math.degrees(math.asin(math.sin(math.radians(obliq_corr)) * math.sin(math.radians(app_long))))
    y = math.tan(math.radians(obliq_corr / 2)) ** 2
    eot = 4 * math.degrees(
        y * math.sin(2 * math.radians(L0)) - 2 * e * math.sin(math.radians(M))
        + 4 * e * y * math.sin(math.radians(M)) * math.cos(2 * math.radians(L0))
        - 0.5 * y * y * math.sin(4 * math.radians(L0)) - 1.25 * e * e * math.sin(2 * math.radians(M)))
    return decl, eot


def sun_position(lat, lon, dt):
    """-> (elevation deg, azimuth deg from N clockwise) of the sun's centre (no refraction)."""
    decl, eot = _solar(dt)
    tst = (dt.hour * 60 + dt.minute + dt.second / 60 + eot + 4 * lon) % 1440
    ha = tst / 4 - 180  # hour angle, degrees
    la, de, h = map(math.radians, (lat, decl, ha))
    zenith = math.acos(max(-1, min(1, math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(h))))
    elev = 90 - math.degrees(zenith)
    # azimuth, clockwise from north
    den = math.cos(la) * math.sin(zenith)
    az = 180.0 if abs(den) < 1e-9 else math.degrees(math.acos(
        max(-1, min(1, (math.sin(la) * math.cos(zenith) - math.sin(de)) / den))))
    az = (az + 180) % 360 if ha > 0 else (180 - az) % 360
    return elev, az


def _times(lat, lon, date):
    """Sunrise / sunset / solar-noon as UTC datetimes (None if the sun never rises/sets that day)."""
    noon = _dt.datetime(date.year, date.month, date.day, 12, tzinfo=_dt.timezone.utc)
    decl, eot = _solar(noon)
    la, de = math.radians(lat), math.radians(decl)
    cos_ha = (math.cos(math.radians(90.833)) - math.sin(la) * math.sin(de)) / (math.cos(la) * math.cos(de))
    solar_noon_min = 720 - 4 * lon - eot
    sn = noon.replace(hour=0, minute=0) + _dt.timedelta(minutes=solar_noon_min)
    if cos_ha < -1 or cos_ha > 1:
        return None, None, sn  # polar day / night
    ha = math.degrees(math.acos(cos_ha))
    return (sn - _dt.timedelta(minutes=4 * ha), sn + _dt.timedelta(minutes=4 * ha), sn)


def _compass(az):
    return ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"][
        round(az / 22.5) % 16]


@transform("chrono-sun", "To Sun Position [offline]", "Location",
           "Sunrise/sunset + sun azimuth & elevation for the case timestamp (shadow analysis, no key)",
           settings=["chrono.datetime"], classification="derived")
def _(v, p, s):
    lat, lon = coords_of(v, p)
    dt = _parse_dt(s.get("chrono.datetime"))
    elev, az = sun_position(lat, lon, dt)
    rise, set_, noon = _times(lat, lon, dt)
    fmt = lambda t: t.strftime("%H:%M UTC") if t else "—"
    above = elev > 0
    shadow_az = (az + 180) % 360  # shadows point opposite the sun
    out = [("Location", v, "", {
        "sun.datetime": dt.strftime("%Y-%m-%d %H:%M UTC"),
        "sun.elevation": f"{elev:.1f}°", "sun.azimuth": f"{az:.1f}° ({_compass(az)})",
        "sun.shadow_direction": f"{shadow_az:.1f}° ({_compass(shadow_az)})" if above else "n/a (sun below horizon)",
        "sun.sunrise": fmt(rise), "sun.sunset": fmt(set_), "sun.solar_noon": fmt(noon)})]
    out.append(("Phrase",
                (f"Sun {elev:.0f}° up, bearing {az:.0f}° {_compass(az)} — shadows fall {_compass(shadow_az)}"
                 if above else f"Sun below horizon ({elev:.0f}°) — nighttime"),
                f"Sun @ {dt.strftime('%Y-%m-%d %H:%M UTC')}"))
    return out


@transform("chrono-weather", "To Historical Weather [Open-Meteo]", "Location",
           "Temperature, precipitation and cloud cover on the case date (Open-Meteo archive, no key)",
           settings=["chrono.datetime"])
def _(v, p, s):
    lat, lon = coords_of(v, p)
    dt = _parse_dt(s.get("chrono.datetime"))
    day = dt.strftime("%Y-%m-%d")
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "start_date": day, "end_date": day, "timezone": "UTC",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
        "hourly": "cloudcover,temperature_2m"})
    j = fetch_json(f"https://archive-api.open-meteo.com/v1/archive?{q}")
    d = j.get("daily", {})
    if not d.get("time"):
        return [("Phrase", f"no weather record for {day}", "Weather")]
    cloud = j.get("hourly", {}).get("cloudcover", [])
    cloud_at = cloud[dt.hour] if len(cloud) > dt.hour else None
    props = {"weather.date": day, "weather.temp_max": f"{d['temperature_2m_max'][0]}°C",
             "weather.temp_min": f"{d['temperature_2m_min'][0]}°C",
             "weather.precipitation": f"{d['precipitation_sum'][0]} mm",
             "weather.condition": _WMO.get(d.get("weathercode", [None])[0], "")}
    if cloud_at is not None:
        props["weather.cloud_cover"] = f"{cloud_at}% at {dt.strftime('%H:%M UTC')}"
    summary = (f"{day}: {d['temperature_2m_min'][0]}–{d['temperature_2m_max'][0]}°C, "
               f"{d['precipitation_sum'][0]} mm rain" + (f", {cloud_at}% cloud" if cloud_at is not None else ""))
    return [("Location", v, "", props), ("Phrase", summary, "Weather")]


_WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
        51: "light drizzle", 53: "drizzle", 55: "dense drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
        71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent showers",
        95: "thunderstorm", 96: "thunderstorm w/ hail", 99: "thunderstorm w/ hail"}
