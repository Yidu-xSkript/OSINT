"""Self-check for sightline.py:  python test_sightline.py"""
import sightline as s


def test_geodesy():
    sf = {"lat": 37.7749, "lon": -122.4194}
    la = {"lat": 34.0522, "lon": -118.2437}
    d = s.haversine_m(sf, la)
    assert 550_000 < d < 570_000  # SF->LA ~559 km
    assert 120 < s.bearing_deg(sf, la) < 150  # roughly SE
    assert s.compass(270) == "W" and s.compass(0) == "N" and s.compass(135) == "SE"


def test_resection_recovers_height():
    # camera at (40.70, -73.99); two landmarks due WEST, collinear, chosen so a 50 m eye aligns their tops.
    # 1 deg lon at lat 40.7 ~ 84.3 km -> 1000 m ~ 0.011862 deg, 3000 m ~ 0.035586 deg
    cam = {"lat": 40.70, "lon": -73.99}
    near = {"lat": 40.70, "lon": -73.99 - 0.011862, "height": 84}
    far = {"lat": 40.70, "lon": -73.99 - 0.035586, "height": 152}  # tuned so H=50
    r = s.resection(far, near, cam)
    assert abs(r["facing_azimuth"] - 270) < 1.5 and r["facing_compass"] == "W"
    assert r["collinearity_error_deg"] < 0.5          # near & far share a bearing -> good resection
    assert abs(r["camera_height_m"] - 50) < 2 and r["estimated_floor"] in (14, 15)  # 50/3.5 ~ 14.3
    assert 950 < r["distance_to_near_m"] < 1050 and 2900 < r["distance_to_far_m"] < 3100


def test_real_case_dumbo():
    # Jonny Lee Miller case (approx coords): camera at 1 Main St, DUMBO; near = Brooklyn Bridge tower;
    # far = Woolworth Building spire, both across the river to the W/SW. Sanity: window faces W/SW.
    cam = {"lat": 40.7036, "lon": -73.9906}
    near = {"lat": 40.7061, "lon": -73.9969, "height": 84}      # Brooklyn Bridge Manhattan-side tower
    far = {"lat": 40.7123, "lon": -74.0083, "height": 241}      # Woolworth Building
    r = s.resection(far, near, cam)
    assert r["facing_compass"] in ("W", "WNW", "NW", "WSW")     # looks across the river toward Manhattan
    assert r["distance_to_far_m"] > r["distance_to_near_m"]     # Woolworth is farther than the bridge
    assert r["camera_height_m"] is not None


if __name__ == "__main__":
    test_geodesy(); test_resection_recovers_height(); test_real_case_dumbo()
    print("ok")
