"""
Test that during waypoint edits, rich-data providers (ORS with elevation & surface data)
are strictly preserved as the selected route and never displaced by elevation-less fallbacks.
"""
from core.providers.base import RouteProvider, RouteProviderError
from core.route_engine import RouteEngine
from models.route_request import Activity, NormalizedRoute, RoutePoint, RouteRequest


class DummyRichProvider(RouteProvider):
    name = "OpenRouteService"

    def get_route(self, request, start_coords, end_coords=None):
        return NormalizedRoute(
            provider="OpenRouteService",
            distance_km=10.5,
            duration_min=30.0,
            elevation_gain_m=150.0,
            points=[RoutePoint(59.91, 10.75, 20.0), RoutePoint(59.92, 10.76, 30.0)],
            instructions=[],
            surface_composition={"Asphalt": 100.0},
            surface_segments=[],
            geometry_geojson={"type": "LineString", "coordinates": [[10.75, 59.91], [10.76, 59.92]]},
        )

    def geocode(self, place_name):
        return (59.91, 10.75)


class DummyFlatProvider(RouteProvider):
    name = "Mapbox"

    def get_route(self, request, start_coords, end_coords=None):
        # Returns exact 10.0km match, but NO elevation and NO surface composition
        return NormalizedRoute(
            provider="Mapbox",
            distance_km=10.0,
            duration_min=28.0,
            elevation_gain_m=None,
            points=[RoutePoint(59.91, 10.75, None), RoutePoint(59.92, 10.76, None)],
            instructions=[],
            surface_composition={},
            surface_segments=[],
            geometry_geojson={"type": "LineString", "coordinates": [[10.75, 59.91], [10.76, 59.92]]},
        )

    def geocode(self, place_name):
        return (59.91, 10.75)


def test_edit_ranking_preserves_rich_provider():
    rich = DummyRichProvider()
    flat = DummyFlatProvider()
    engine = RouteEngine(providers=[rich, flat])

    req = RouteRequest(
        activity=Activity.CYCLING_ROAD,
        start_location="59.91,10.75",
        target_distance_km=10.0,
        is_loop=True,
        via_points=[(59.92, 10.76)],
    )

    all_routes, best, warnings = engine.plan(req)

    # Verify that best is ORS (DummyRichProvider) even though Mapbox hit the exact 10.0km target
    assert best.provider == "OpenRouteService"
    assert best.elevation_gain_m is not None
    assert bool(best.surface_composition)
    print("test_edit_ranking_preserves_rich_provider: PASS")


if __name__ == "__main__":
    test_edit_ranking_preserves_rich_provider()
