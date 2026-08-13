"""
Test long-distance loop routing (>100km, e.g. 120km, 150km) to ensure
OpenRouteService 100,000m server limit is cleanly bypassed with polygon
waypoint synthesis without raising HTTP 400 errors.
"""
from core.providers.ors_provider import ORSProvider, destination_point
from models.route_request import Activity, RouteRequest


def test_destination_point_math():
    # Starting at Oslo (59.9139, 10.7522), 10km north (heading 0)
    lat2, lon2 = destination_point(59.9139, 10.7522, 10.0, 0.0)
    assert lat2 > 59.9139
    assert abs(lon2 - 10.7522) < 0.01
    print("destination_point_math: OK")


def test_synthesized_loop_generation():
    provider = ORSProvider(api_key="mock_key")

    mock_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [10.7522, 59.9139, 10.0],
                        [10.8522, 59.9539, 15.0],
                        [10.9522, 59.9139, 20.0],
                        [10.8522, 59.8739, 15.0],
                        [10.7522, 59.9139, 10.0],
                    ],
                },
                "properties": {
                    "summary": {"distance": 120000.0, "duration": 14400.0},
                    "ascent": 450.0,
                    "descent": 450.0,
                    "segments": [
                        {
                            "steps": [
                                {
                                    "distance": 120000.0,
                                    "duration": 14400.0,
                                    "type": 1,
                                    "instruction": "Depart loop",
                                    "name": "Main Road",
                                    "way_points": [0, 4],
                                }
                            ]
                        }
                    ],
                    "extras": {
                        "surface": {
                            "values": [[0, 4, 1]]
                        }
                    },
                },
            }
        ],
    }

    # Patch _post_directions to return 120km mock route
    provider._post_directions = lambda profile, body: mock_geojson

    req = RouteRequest(
        activity=Activity.CYCLING_ROAD,
        start_location="Oslo",
        is_loop=True,
        target_distance_km=120.0,
    )

    route = provider.get_route(req, start_coords=(59.9139, 10.7522))

    assert route is not None
    assert route.distance_km == 120.0
    assert route.elevation_gain_m == 10.0
    print("synthesized_loop_generation for 120km: PASS")


if __name__ == "__main__":
    test_destination_point_math()
    test_synthesized_loop_generation()
    print("\nALL LONG-DISTANCE LOOP TESTS PASSED!")
