"""
OSRM provider — uses the free public demo server (router.project-osrm.org).
No API key needed, which makes it a good zero-config fallback, but:
- The public demo server has no SLA and rate-limits aggressively; for real
  production use you'd self-host OSRM or point OSRM_BASE_URL at your own.
- Only "foot", "bike", "car" profiles exist — no distinction between road
  bike / mountain bike / running / hiking. We map onto the closest fit.
- No native loop support and no elevation data. A FRESH loop request (no
  via_points yet) uses a synthetic waypoint-circle guess; once via_points
  exist (editing, or a route built from explicit waypoints), this
  provider routes through exactly those points instead — no guessing
  needed once the shape is already spelled out.
"""
import math
import os
from typing import Optional

import requests

from core.providers.base import RouteProvider, RouteProviderError
from models.route_request import NormalizedRoute, RoutePoint, RouteRequest

DEFAULT_BASE_URL = "https://router.project-osrm.org"


class OSRMProvider(RouteProvider):
    name = "OSRM"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.environ.get("OSRM_BASE_URL", DEFAULT_BASE_URL)

    def geocode(self, place_name: str) -> tuple[float, float]:
        # OSRM has no geocoder — this provider relies on another provider
        # (or Nominatim directly) having already resolved coordinates.
        raise RouteProviderError(
            "OSRM has no geocoding endpoint; resolve coordinates via ORS/Mapbox/Nominatim first"
        )

    def supports_loops_natively(self) -> bool:
        return False

    def _build_loop_waypoints(
        self, start: tuple[float, float], distance_km: float
    ) -> list[tuple[float, float]]:
        radius_km = distance_km / (2 * math.pi) * 1.15
        lat0, lon0 = start
        waypoints = []
        for bearing_deg in (90, 210, 330):
            bearing = math.radians(bearing_deg)
            dlat = (radius_km / 111.0) * math.cos(bearing)
            dlon = (radius_km / (111.0 * math.cos(math.radians(lat0)))) * math.sin(bearing)
            waypoints.append((lat0 + dlat, lon0 + dlon))
        return waypoints

    def get_route(
        self,
        request: RouteRequest,
        start_coords: tuple[float, float],
        end_coords: Optional[tuple[float, float]] = None,
    ) -> NormalizedRoute:
        profile = request.osrm_profile()
        lat, lon = start_coords

        if request.is_loop:
            if request.via_points:
                coord_list = [(lat, lon), *request.via_points, (lat, lon)]
            else:
                if not request.target_distance_km:
                    raise RouteProviderError("OSRM loop routing requires a target distance")
                waypoints = self._build_loop_waypoints(start_coords, request.target_distance_km)
                coord_list = [(lat, lon), *waypoints, (lat, lon)]
        else:
            if request.via_points:
                coord_list = [(lat, lon), *request.via_points]
                if end_coords:
                    coord_list.append(end_coords)
            elif end_coords:
                coord_list = [(lat, lon), end_coords]
            else:
                coord_list = [(lat, lon)]
        if len(coord_list) < 2:
            raise RouteProviderError("Routing requires at least two points (start and destination or waypoint)")

        coord_str = ";".join(f"{c[1]},{c[0]}" for c in coord_list)

        resp = requests.get(
            f"{self.base_url}/route/v1/{profile}/{coord_str}",
            params={"overview": "full", "geometries": "geojson"},
            timeout=20,
        )
        if resp.status_code != 200:
            raise RouteProviderError(f"OSRM route failed: {resp.status_code} {resp.text}")

        data = resp.json()
        routes = data.get("routes", [])
        if not routes:
            raise RouteProviderError("OSRM returned no routes")

        route = routes[0]
        coords = route["geometry"]["coordinates"]
        points = [RoutePoint(lat=c[1], lon=c[0]) for c in coords]

        return NormalizedRoute(
            provider=self.name,
            distance_km=route["distance"] / 1000,
            duration_min=route["duration"] / 60,
            elevation_gain_m=None,
            points=points,
            geometry_geojson=route["geometry"],
            raw_response=data,
        )
