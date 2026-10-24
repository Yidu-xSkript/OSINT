"""God's Eye View live-layer proxies.

The bundled GEV is static; its live layers fetch /api/* which GEV's own Node server normally proxies.
We serve the keyless, high-value ones here so the embedded globe lights up with no extra server:
  - /api/adsblol/mil      military aircraft (adsb.lol, ODbL, keyless)
  - /api/celestrak/{grp}  satellite TLEs (celestrak.org, keyless)
  - /api/overpass         OSM map features (Overpass, mirror-rotated)
Layers that need API keys (FIRMS fires, Google, TomTom) or auth (OpenSky) are left to a full GEV server
via the gev.url setting. Each proxy degrades gracefully (serve-stale / empty) so a layer never breaks GEV.
"""
import time, urllib.error, urllib.parse, urllib.request

from fastapi import APIRouter, Request, Response

router = APIRouter()
UA = {"User-Agent": "osint-graph-gev-proxy/1.0"}
OVERPASS = ["https://overpass.private.coffee/api/interpreter", "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter", "https://lz4.overpass-api.de/api/interpreter"]
_cache = {}  # url -> (ts, body)


def _get(url, timeout=12):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _cached(url, ttl, media, timeout=12):
    """GET with a short cache; serve stale on upstream failure so a layer never goes dark."""
    now = time.time()
    hit = _cache.get(url)
    if hit and now - hit[0] < ttl:
        return Response(hit[1], media_type=media)
    try:
        body = _get(url, timeout)
        _cache[url] = (now, body)
        return Response(body, media_type=media)
    except Exception:
        if hit:  # serve-stale
            return Response(hit[1], media_type=media, headers={"X-Proxy": "stale"})
        return Response(b'{"ac":[]}' if "json" in media else b"", media_type=media, status_code=200)


@router.get("/api/adsblol/mil")
def adsblol_mil():
    return _cached("https://api.adsb.lol/v2/mil", 12, "application/json")


@router.get("/api/celestrak/{group}")
def celestrak(group: str):
    # /api/celestrak/active -> GROUP=active&FORMAT=tle; GEV passes the group as the path segment
    url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={urllib.parse.quote(group)}&FORMAT=tle"
    return _cached(url, 3600, "text/plain; charset=utf-8", timeout=15)


@router.post("/api/overpass")
async def overpass(request: Request):
    body = await request.body()
    ctype = request.headers.get("content-type", "application/x-www-form-urlencoded")
    err = None
    for base in OVERPASS:
        try:
            req = urllib.request.Request(base, data=body, headers=UA | {"Content-Type": ctype})
            with urllib.request.urlopen(req, timeout=40) as r:
                return Response(r.read(), media_type="application/json")
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            err = e
    return Response(b'{"elements":[]}', media_type="application/json", status_code=200,
                    headers={"X-Proxy-Error": str(err)[:100]})
