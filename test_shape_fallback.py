"""
Simulates a case where the default 4-waypoint loop shape is structurally
capped well below the target distance (e.g. blocked by a bridge crossing,
dead-end roads, etc — no amount of length/seed correction within that
shape will ever reach the target), but a DIFFERENT waypoint count (5) can
actually reach it. Confirms the fallback shape-sweep finds that route
instead of giving up on the capped 4-point shape's best effort.

Run with: python3 test_shape_fallback.py
"""
import sys

sys.path.insert(0, ".")

from core.providers.ors_provider import ORSProvider
from models.route_request import NormalizedRoute

# Simulated max achievable distance per waypoint-count shape, regardless of
# how much "length" is requested — models a shape being geometrically
# capped (e.g. points=4 can never exceed ~14.6km here no matter what).
SHAPE_CAPS_KM = {
    4: 14.6,   # the default shape — capped, can't reach the target
    3: 13.0,   # also capped, tried first in the fallback sweep
    5: 999.0,  # uncapped — CAN reach the target with the right length
    6: 999.0,
    2: 8.0,
}

# For uncapped shapes, simulate a mild, consistent overshoot so the
# correction loop still has to do real work to converge, rather than
# hitting the target on the first guess.
OVERSHOOT_RATIO = 1.15


def make_mock_provider():
    provider = ORSProvider(api_key="fake-key-for-test")
    call_log = []

    def fake_post_directions(profile, body):
        requested_m = body["options"]["round_trip"]["length"]
        points = body["options"]["round_trip"]["points"]
        requested_km = requested_m / 1000

        cap = SHAPE_CAPS_KM.get(points, 999.0)
        actual_km = min(requested_km * OVERSHOOT_RATIO, cap)

        call_log.append((points, requested_km, actual_km))
        return {"_mock_actual_km": actual_km}

    def fake_normalize(data):
        return NormalizedRoute(
            provider="OpenRouteService",
            distance_km=data["_mock_actual_km"],
            duration_min=data["_mock_actual_km"] * 5,
            elevation_gain_m=None,
            points=[],
            geometry_geojson=None,
        )

    provider._post_directions = fake_post_directions
    provider._normalize = fake_normalize
    return provider, call_log


def test_shape_fallback():
    provider, call_log = make_mock_provider()
    base_body = {"coordinates": [[10.75, 59.91]], "elevation": True}
    target_km = 20.0

    result = provider._get_best_round_trip("cycling-regular", base_body, target_km)
    final_error_pct = abs(result.distance_km - target_km) / target_km * 100

    shapes_tried = sorted(set(c[0] for c in call_log))
    print(f"Shapes tried (waypoint counts): {shapes_tried}")
    print(f"Total API calls: {len(call_log)}")
    print(f"Final route: {result.distance_km:.2f}km (target {target_km}km, {final_error_pct:.1f}% off)")

    assert result.distance_km > 18.0, (
        f"expected the fallback sweep to find a route near {target_km}km via an "
        f"uncapped shape, got {result.distance_km:.2f}km instead"
    )
    assert final_error_pct <= 5.0, "expected convergence within tolerance via the fallback shape"
    assert 4 in shapes_tried, "expected the primary 4-point shape to be tried first"
    assert 5 in shapes_tried or 6 in shapes_tried, (
        "expected an uncapped alternate shape to actually be tried"
    )

    print("\nPASS: fallback shape sweep found a converging route the capped default shape couldn't.")


if __name__ == "__main__":
    test_shape_fallback()
