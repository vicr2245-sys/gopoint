"""
Test detection and trimming of dead-end U-turn spurs and overlapping backtrack segments.
"""
from core.geo import trim_overlapping_spurs
from models.route_request import NormalizedRoute, RoutePoint


def test_trim_dead_end_spur():
    # Build a route: Start (0,0) -> Main1 (0.01, 0.01) -> Main2 (0.02, 0.02)
    # -> DetourStart (0.03, 0.03) -> DeadEnd (0.04, 0.04) -> DetourBack (0.03, 0.03)
    # -> Main3 (0.04, 0.02) -> End (0.05, 0.01)
    
    pts = [
        RoutePoint(lat=59.90, lon=10.70, elevation_m=10.0),
        RoutePoint(lat=59.91, lon=10.71, elevation_m=12.0),
        RoutePoint(lat=59.92, lon=10.72, elevation_m=15.0),
        # Spur out-and-back starts at (59.93, 10.73)
        RoutePoint(lat=59.93, lon=10.73, elevation_m=18.0),
        RoutePoint(lat=59.94, lon=10.74, elevation_m=22.0),  # Dead end tip
        RoutePoint(lat=59.93, lon=10.73, elevation_m=18.0),  # Backtrack return point
        # Route continues along loop
        RoutePoint(lat=59.94, lon=10.72, elevation_m=16.0),
        RoutePoint(lat=59.95, lon=10.71, elevation_m=14.0),
        RoutePoint(lat=59.90, lon=10.70, elevation_m=10.0),
    ]

    original_route = NormalizedRoute(
        provider="OpenRouteService",
        distance_km=25.0,
        duration_min=60.0,
        elevation_gain_m=100.0,
        points=pts,
        instructions=[],
        surface_composition={},
        surface_segments=[],
        geometry_geojson={},
        raw_response={},
    )

    trimmed_route = trim_overlapping_spurs(original_route)

    # Check that points length is reduced (dead end point at (59.94, 10.74) removed)
    assert len(trimmed_route.points) < len(original_route.points)
    # Verify the dead end point is not in trimmed_route
    dead_end_present = any(p.lat == 59.94 and p.lon == 10.74 for p in trimmed_route.points)
    assert not dead_end_present
    print("test_trim_dead_end_spur: PASS")


def test_trim_trailing_overshoot():
    from core.geo import trim_trailing_overshoot
    
    # Route passes through target (59.93, 10.73) then continues past it to (59.95, 10.75)
    pts = [
        RoutePoint(lat=59.90, lon=10.70, elevation_m=10.0),
        RoutePoint(lat=59.91, lon=10.71, elevation_m=12.0),
        RoutePoint(lat=59.92, lon=10.72, elevation_m=15.0),
        RoutePoint(lat=59.93, lon=10.73, elevation_m=18.0),  # Target location!
        RoutePoint(lat=59.94, lon=10.74, elevation_m=22.0),  # Trailing overshoot
        RoutePoint(lat=59.95, lon=10.75, elevation_m=25.0),  # Trailing overshoot end
    ]

    target_lat, target_lon = 59.93, 10.73
    trimmed_pts = trim_trailing_overshoot(pts, target_lat, target_lon)

    # Verify that trailing points past (59.93, 10.73) were trimmed
    assert len(trimmed_pts) == 4
    assert trimmed_pts[-1].lat == target_lat
    assert trimmed_pts[-1].lon == target_lon
    print("test_trim_trailing_overshoot: PASS")


if __name__ == "__main__":
    test_trim_dead_end_spur()
    test_trim_trailing_overshoot()
    print("ALL SPUR TRIMMING TESTS PASSED!")
