"""Collinear sightline resection (Gary Riddell / Bellingcat technique).

Two landmarks that line up vertically in a photo (a near one in front of a far one) fix the camera on
the ray through them. Given the two landmarks and the candidate camera building, this computes:
  - the azimuth the window faces (toward the landmarks),
  - which facade / corner that is,
  - the camera height and estimated floor (from the two landmark heights and distances),
  - a collinearity check (how well the two landmarks' bearings agree from the camera).

Pure geodesy, no external data. Heights are metres above the camera's ground; distances are horizontal.
"""
import math

FLOOR_M = 3.5  # typical floor-to-floor; a tunable knob for the floor estimate
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
R = 6371008.8  # mean Earth radius (m)


def _rad(d):
    return math.radians(d)


def haversine_m(a, b):
    la1, la2 = _rad(a["lat"]), _rad(b["lat"])
    dla, dlo = _rad(b["lat"] - a["lat"]), _rad(b["lon"] - a["lon"])
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(h)))


def bearing_deg(a, b):
    """Initial compass bearing from a to b (0=N, clockwise)."""
    la1, la2 = _rad(a["lat"]), _rad(b["lat"])
    dlo = _rad(b["lon"] - a["lon"])
    y = math.sin(dlo) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlo)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(az):
    return COMPASS[round(az / 22.5) % 16]


def _ang_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def resection(far, near, camera):
    """far/near: landmarks {lat, lon, height}. camera: candidate building {lat, lon}. Heights optional->0."""
    hf, hn = far.get("height", 0) or 0, near.get("height", 0) or 0
    d_far = haversine_m(camera, far)
    d_near = haversine_m(camera, near)
    az_near = bearing_deg(camera, near)
    az_far = bearing_deg(camera, far)
    # the window looks toward the landmarks; near & far should share that bearing when truly collinear
    facing = az_near
    collinearity_err = round(_ang_diff(az_near, az_far), 2)  # degrees; small = good resection
    # camera height from the two tops being collinear with the eye:
    #   (hf - H)/d_far = (hn - H)/d_near  ->  H = (d_far*hn - d_near*hf)/(d_far - d_near)
    height = None
    floor = None
    if (hf or hn) and abs(d_far - d_near) > 1e-6:
        height = (d_far * hn - d_near * hf) / (d_far - d_near)
        floor = max(0, round(height / FLOOR_M))
    return {
        "facing_azimuth": round(facing, 1),
        "facing_compass": compass(facing),
        "collinearity_error_deg": collinearity_err,
        "distance_to_near_m": round(d_near),
        "distance_to_far_m": round(d_far),
        "bearing_to_near": round(az_near, 1),
        "bearing_to_far": round(az_far, 1),
        "camera_height_m": None if height is None else round(height, 1),
        "estimated_floor": floor,
    }
