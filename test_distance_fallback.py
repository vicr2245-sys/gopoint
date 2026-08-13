"""
Reproduces the exact reported bug: a single provider (ORS) returns a route
that misses the distance tolerance (14.6km vs a 20km target — the
Fredrikstad screenshot case), and confirms the engine now falls back to
that closest match with a warning instead of raising RouteProviderError
and showing zero routes.

Run with: python3 test_distance_fallback.py
"""
import sys

sys.path.insert(0, ".")

from core.providers.base import RouteProvider, RouteProviderError
from core.route_engine import RouteEngine
from models.route_request import Activity, ElevationPreference, NormalizedRoute, RouteRequest


class FakeSingleRouteProvider(RouteProvider):
    """Always returns one fixed route, regardless of request — enough to
    drive the distance-filtering logic under test without needing a real
    HTTP call or API key."""

    name = "OpenRouteService"

    def __init__(self, distance_km: float):
        self.distance_km = distance_km

    def geocode(self, place_name):
        return (59.2181, 10.9298)  # roughly Fredrikstad

    def supports_loops_natively(self) -> bool:
        return True

    def get_route(self, request, start_coords, end_coords=None) -> NormalizedRoute:
        return NormalizedRoute(
            provider=self.name,
            distance_km=self.distance_km,
            duration_min=self.distance_km * 4,
            elevation_gain_m=None,
            points=[],
            geometry_geojson={"type": "LineString", "coordinates": [[10.93, 59.22], [10.94, 59.22]]},
        )


def build_request(target_km: float) -> RouteRequest:
    return RouteRequest(
        activity=Activity.CYCLING_REGULAR,
        start_location="Fredrikstad",
        is_loop=True,
        target_distance_km=target_km,
        elevation_preference=ElevationPreference.NO_PREFERENCE,
        raw_prompt=f"A {target_km}km bike ride in fredrikstad",
    )


def test_distance_fallback():
    provider = FakeSingleRouteProvider(distance_km=14.6)
    engine = RouteEngine(providers=[provider])
    request = build_request(target_km=20.0)

    try:
        routes, best, warnings = engine.plan(request)
    except RouteProviderError as e:
        print("FAIL: engine.plan() raised instead of falling back:", e)
        sys.exit(1)

    print(f"routes returned: {len(routes)}")
    print(f"best route: {best.provider}, {best.distance_km}km")
    print(f"warnings: {warnings}")

    assert len(routes) == 1, "expected exactly one fallback route"
    assert best.distance_km == 14.6
    assert warnings, "expected a warning explaining the mismatch"
    assert "14.6" in warnings[0] and "20.0" in warnings[0]

    print("\nPASS: closest-match fallback returned with a clear warning, no hard failure.")


if __name__ == "__main__":
    test_distance_fallback()
