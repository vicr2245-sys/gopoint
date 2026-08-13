"""
Verifies the full save -> list -> load -> delete round-trip for saved
routes, using a temp DB file so it doesn't touch the real
~/.route_planner/routes.db. This is the part most likely to have subtle
bugs: JSON doesn't know about Python enums or tuples, so reconstruction
has to explicitly rebuild Activity/ElevationPreference enums and via_points
tuples, and every nested dataclass (RoutePoint, RouteInstruction,
SurfaceSegment) needs to come back as a real dataclass instance, not a
plain dict, since the rest of the app accesses them via attributes.

Run with: python3 test_route_storage.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

import core.route_storage as route_storage
from models.route_request import (
    Activity,
    ElevationPreference,
    NormalizedRoute,
    RouteInstruction,
    RoutePoint,
    RouteRequest,
    SurfaceSegment,
)


def test_route_storage():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_db = Path(tmp_dir) / "routes.db"
        route_storage.DB_PATH = tmp_db

        request = RouteRequest(
            activity=Activity.CYCLING_ROAD,
            start_location="Fredrikstad",
            is_loop=True,
            target_distance_km=20.0,
            via_points=[(59.22, 10.93), (59.23, 10.95)],
            auto_close_loop=False,
            elevation_preference=ElevationPreference.HILLY,
            avoid_main_roads=True,
            surface_preference="gravel",
            raw_prompt="Fredrikstad 20km gravel ride",
        )

        route = NormalizedRoute(
            provider="OpenRouteService",
            distance_km=19.8,
            duration_min=52.0,
            elevation_gain_m=180.0,
            points=[
                RoutePoint(lat=59.22, lon=10.93, elevation_m=12.0),
                RoutePoint(lat=59.23, lon=10.94, elevation_m=18.0),
            ],
            instructions=[
                RouteInstruction(
                    text="Turn left onto Nygaardsgata",
                    lat=59.22,
                    lon=10.93,
                    distance_m=450.0,
                    duration_s=60.0,
                    turn_type=1,
                )
            ],
            surface_composition={"Gravel": 60.0, "Asphalt": 40.0},
            surface_segments=[
                SurfaceSegment(start_index=0, end_index=10, category="Gravel"),
                SurfaceSegment(start_index=10, end_index=20, category="Asphalt"),
            ],
            geometry_geojson={"type": "LineString", "coordinates": [[10.93, 59.22], [10.94, 59.23]]},
        )

        # --- save ---
        route_id = route_storage.save_route("Fredrikstad gravel loop", request, route)
        assert isinstance(route_id, int) and route_id > 0
        print(f"Saved with id={route_id}")

        # --- list ---
        summaries = route_storage.list_routes()
        assert len(summaries) == 1
        summary = summaries[0]
        assert summary.name == "Fredrikstad gravel loop"
        assert summary.activity == "cycling-road"
        assert abs(summary.distance_km - 19.8) < 0.001
        print(f"Listed: {summary.label()}")

        # --- load ---
        loaded_request, loaded_route = route_storage.load_route(route_id)

        # Enum reconstruction (not just string equality — must be the actual enum type)
        assert isinstance(loaded_request.activity, Activity)
        assert loaded_request.activity == Activity.CYCLING_ROAD
        assert isinstance(loaded_request.elevation_preference, ElevationPreference)
        assert loaded_request.elevation_preference == ElevationPreference.HILLY

        # Tuple reconstruction for via_points (JSON gives lists, must come back as tuples)
        assert loaded_request.via_points == [(59.22, 10.93), (59.23, 10.95)]
        assert isinstance(loaded_request.via_points[0], tuple)

        assert loaded_request.auto_close_loop is False
        assert loaded_request.surface_preference == "gravel"
        assert loaded_request.target_distance_km == 20.0

        # Nested dataclass reconstruction — must be real objects with
        # attribute access, not plain dicts left over from JSON
        assert isinstance(loaded_route.points[0], RoutePoint)
        assert loaded_route.points[0].lat == 59.22
        assert isinstance(loaded_route.instructions[0], RouteInstruction)
        assert loaded_route.instructions[0].text == "Turn left onto Nygaardsgata"
        assert isinstance(loaded_route.surface_segments[0], SurfaceSegment)
        assert loaded_route.surface_segments[0].category == "Gravel"
        assert loaded_route.surface_composition == {"Gravel": 60.0, "Asphalt": 40.0}
        assert loaded_route.geometry_geojson["type"] == "LineString"
        assert loaded_route.raw_response is None  # deliberately not persisted

        # Methods on the reconstructed objects should still work (proves
        # these are real instances, not dicts pretending to be them)
        assert loaded_request.ors_profile() == "cycling-road"
        assert "gravel" in loaded_route.surface_summary() or "asphalt" in loaded_route.surface_summary()

        print("Loaded route matches saved route in every field checked.")

        # --- delete ---
        route_storage.delete_route(route_id)
        assert route_storage.list_routes() == []
        print("Deleted successfully, list is now empty.")

    print("\nPASS: full save/list/load/delete round-trip verified.")


if __name__ == "__main__":
    test_route_storage()
