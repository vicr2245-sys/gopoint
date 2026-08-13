"""
Simulates a case with several viable loop shapes at ~roughly the target
distance, each with a DIFFERENT elevation profile (since real terrain
varies by which streets a given seed's shape happens to use) — some flat,
some close to the 500m climbing target the user asked for. Confirms the
elevation-aware search actually finds and picks the close match instead of
just returning whatever the distance-correction loop happened to land on
first (which is what the original bug did: 242m instead of 500m).

Run with: python3 test_elevation_targeting.py
"""
import random
import sys

sys.path.insert(0, ".")

from core.providers.ors_provider import ORSProvider
from models.route_request import NormalizedRoute

# Simulated elevation gain per seed, roughly modeling "different shapes
# happen to pass through different terrain". Seed 3 is deliberately the
# best match for a 500m target; others are mostly flatter, mirroring a
# real scenario where most nearby loop shapes are modest but at least one
# genuinely hilly option exists if you look for it.
SEED_ELEVATION_GAIN_M = {
    1: 180, 2: 220, 3: 490, 4: 150,       # primary search round 1
    11: 510, 12: 90, 13: 340, 14: 470, 15: 610, 16: 200,  # elevation extra-search seeds
}
OVERSHOOT_RATIO = 1.02  # mild, easily-converged distance overshoot


def make_mock_provider():
    provider = ORSProvider(api_key="fake-key-for-test")
    call_log = []

    def fake_post_directions(profile, body):
        requested_m = body["options"]["round_trip"]["length"]
        seed = body["options"]["round_trip"]["seed"]
        actual_km = (requested_m / 1000) * OVERSHOOT_RATIO
        gain_m = SEED_ELEVATION_GAIN_M.get(seed, 200)  # default flat-ish for any untested seed
        call_log.append((seed, actual_km, gain_m))
        return {"_mock_actual_km": actual_km, "_mock_gain_m": gain_m}

    def fake_normalize(data):
        return NormalizedRoute(
            provider="OpenRouteService",
            distance_km=data["_mock_actual_km"],
            duration_min=data["_mock_actual_km"] * 5,
            elevation_gain_m=data["_mock_gain_m"],
            points=[],
            geometry_geojson=None,
        )

    provider._post_directions = fake_post_directions
    provider._normalize = fake_normalize
    return provider, call_log


def test_elevation_targeting():
    provider, call_log = make_mock_provider()
    base_body = {"coordinates": [[10.75, 59.91]], "elevation": True}
    target_km = 20.0
    target_elevation_m = 500.0

    result = provider._get_best_round_trip(
        "cycling-regular", base_body, target_km, target_elevation_gain_m=target_elevation_m
    )

    print(f"Total API calls: {len(call_log)}")
    print(f"Seeds tried: {[c[0] for c in call_log]}")
    print(f"Picked route: {result.distance_km:.2f}km, {result.elevation_gain_m:.0f}m gain "
          f"(target: {target_km}km, {target_elevation_m:.0f}m)")

    elevation_error_pct = abs(result.elevation_gain_m - target_elevation_m) / target_elevation_m * 100
    print(f"Elevation error: {elevation_error_pct:.1f}%")

    # The OLD behavior (distance-only selection) would have picked seed 1's
    # route: first seed tried, distance converges immediately, 180m gain —
    # a 64% miss on the elevation target. Confirm we did much better.
    assert result.elevation_gain_m >= 400, (
        f"expected a close elevation match (~500m), got {result.elevation_gain_m}m — "
        f"looks like elevation targeting isn't actually influencing selection"
    )
    assert elevation_error_pct <= 20, f"expected within 20% of target, got {elevation_error_pct:.1f}%"
    assert abs(result.distance_km - target_km) / target_km <= 0.15, "distance should still be a reasonable match"

    print("\nPASS: elevation-aware search found a route close to the requested climbing target.")


def test_elevation_targeting_hard_case():
    """
    Here, EVERY seed used during normal distance convergence (1-4, plus
    fallback shapes' 1-3) is a poor elevation match — only one of the
    dedicated elevation-search seeds (11-16) is close to the 500m target.
    This forces the code down the "pay for extra seeds" path rather than
    getting lucky on a free candidate from the distance search.
    """
    poor_matches = {1: 150, 2: 170, 3: 140, 4: 160}  # primary round 1 — all poor
    extra_seeds = {11: 130, 12: 140, 13: 495, 14: 120, 15: 110, 16: 100}  # only 13 is close
    gains = {**poor_matches, **extra_seeds}

    provider = ORSProvider(api_key="fake-key-for-test")
    call_log = []

    def fake_post_directions(profile, body):
        requested_m = body["options"]["round_trip"]["length"]
        seed = body["options"]["round_trip"]["seed"]
        actual_km = (requested_m / 1000) * 1.02
        gain_m = gains.get(seed, 150)
        call_log.append((seed, actual_km, gain_m))
        return {"_mock_actual_km": actual_km, "_mock_gain_m": gain_m}

    def fake_normalize(data):
        return NormalizedRoute(
            provider="OpenRouteService", distance_km=data["_mock_actual_km"],
            duration_min=data["_mock_actual_km"] * 5, elevation_gain_m=data["_mock_gain_m"],
            points=[], geometry_geojson=None,
        )

    provider._post_directions = fake_post_directions
    provider._normalize = fake_normalize

    base_body = {"coordinates": [[10.75, 59.91]], "elevation": True}
    result = provider._get_best_round_trip(
        "cycling-regular", base_body, 20.0, target_elevation_gain_m=500.0
    )

    print(f"\n--- Hard case: no easy elevation match in the normal search ---")
    print(f"Total API calls: {len(call_log)}")
    print(f"Seeds tried: {[c[0] for c in call_log]}")
    print(f"Picked route: {result.distance_km:.2f}km, {result.elevation_gain_m:.0f}m gain")

    assert 13 in [c[0] for c in call_log], "expected the dedicated elevation-search seed 13 to actually be tried"
    assert result.elevation_gain_m == 495, f"expected the search to find and pick seed 13's 495m route, got {result.elevation_gain_m}m"
    print("PASS: dedicated elevation-search seeds were used and the good match was found.")


if __name__ == "__main__":
    test_elevation_targeting()
    test_elevation_targeting_hard_case()
