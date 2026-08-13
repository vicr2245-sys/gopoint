"""
Quick standalone test that mocks ORS's HTTP layer to simulate its known
overshoot behavior (requested length != actual returned distance), and
verifies _get_best_round_trip's correction loop actually converges toward
the target instead of just picking the least-bad of several equally-wrong
samples.

Run with: python3 test_loop_correction.py
"""
import random
import sys

sys.path.insert(0, ".")

from core.providers.ors_provider import ORSProvider
from models.route_request import NormalizedRoute


def make_mock_provider(overshoot_ratio: float, seed_noise: float = 0.05):
    """
    overshoot_ratio: how much ORS actually returns vs what was requested
    (e.g. 1.6 means "asked for 15km, actually returns ~24km" — this is the
    reported real-world bug). seed_noise adds small per-seed variance so
    the test also confirms we're not just getting lucky on one seed.
    """
    provider = ORSProvider(api_key="fake-key-for-test")
    call_log = []

    def fake_post_directions(profile, body):
        requested_m = body["options"]["round_trip"]["length"]
        seed = body["options"]["round_trip"]["seed"]
        random.seed(seed)  # deterministic per seed for reproducible test
        noise = 1 + random.uniform(-seed_noise, seed_noise)
        actual_m = requested_m * overshoot_ratio * noise
        call_log.append((requested_m / 1000, actual_m / 1000))
        return {"_mock_actual_km": actual_m / 1000}

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


def run_scenario(target_km: float, overshoot_ratio: float):
    provider, call_log = make_mock_provider(overshoot_ratio)
    base_body = {"coordinates": [[10.75, 59.91]], "elevation": True}

    result = provider._get_best_round_trip("foot-running", base_body, target_km)
    final_error_pct = abs(result.distance_km - target_km) / target_km * 100

    print(f"\n--- Target {target_km}km, simulated ORS overshoot x{overshoot_ratio} ---")
    print(f"API calls made: {len(call_log)}")
    for i, (requested, actual) in enumerate(call_log):
        print(f"  call {i+1}: requested {requested:.2f}km -> ORS returned {actual:.2f}km")
    print(f"Final picked route: {result.distance_km:.2f}km (target {target_km}km, "
          f"{final_error_pct:.1f}% off)")

    return final_error_pct


def test_loop_correction():
    # Scenario matching the bug report: ~15km asked, ~39km returned (2.6x overshoot)
    error1 = run_scenario(target_km=15, overshoot_ratio=2.6)

    # A milder overshoot, more typical of ORS's usual behavior
    error2 = run_scenario(target_km=25, overshoot_ratio=1.4)

    # No overshoot at all — correction loop should just accept round 1 immediately
    error3 = run_scenario(target_km=10, overshoot_ratio=1.0)

    print("\n=== Summary ===")
    for name, err in [("severe overshoot (2.6x)", error1),
                       ("mild overshoot (1.4x)", error2),
                       ("no overshoot", error3)]:
        status = "PASS" if err < 15 else "FAIL"
        print(f"{status}: {name} -> final error {err:.1f}%")
        assert err < 15, f"{name} failed with final error {err:.1f}%"


if __name__ == "__main__":
    test_loop_correction()
