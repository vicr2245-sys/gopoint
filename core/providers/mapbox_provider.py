"""
Mapbox Directions provider. Used as a secondary source for comparison/
alternates, and as a geocoding fallback since Mapbox's geocoder is very
reliable for addresses and landmarks.

Mapbox has no native "loop" mode, so a FRESH loop request (no via_points
yet) uses a synthetic waypoint-circle guess (see _build_loop_waypoints).
Once via_points exist — i.e. the route came from editing, or was built
from explicit waypoints — this provider routes through exactly those
points instead, same as any other provider; no synthetic guessing needed
once the shape is already spelled out.
Free tier: 100k requests/month for Directions.
"""
import math
import os
from typing import Optional

import requests

from core.providers.base import RouteProvider, RouteProviderError
from models.route_request import NormalizedRoute, RoutePoint, RouteRequest

BASE_URL = "https://api.mapbox.com"


class MapboxProvider(RouteProvider):
    name = "Mapbox"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("MAPBOX_API_KEY")
        if not self.api_key:
            raise RouteProviderError("MAPBOX_API_KEY not set")

    def geocode(self, place_name: str) -> tuple[float, float]:
        resp = requests.get(
            f"{BASE_URL}/geocoding/v5/mapbox.places/{requests.utils.quote(place_name)}.json",
            params={"access_token": self.api_key, "limit": 1},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RouteProviderError(f"Mapbox geocode failed: {resp.status_code} {resp.text}")
        features = resp.json().get("features", [])
        if not features:
            raise RouteProviderError(f"Mapbox geocode found no results for '{place_name}'")
        lon, lat = features[0]["center"]
        return (lat, lon)

    def supports_loops_natively(self) -> bool:
        return False

    def _build_loop_waypoints(
        self, start: tuple[float, float], distance_km: float
    ) -> list[tuple[float, float]]:
        """
        Mapbox has no round-trip mode, so we approximate a loop by placing
        3 synthetic waypoints on a circle around the start point, sized so
        the total path roughly matches the target distance. This is a rough
        heuristic — ORS's native round_trip is more reliable for loops, this
        exists mainly so Mapbox can still contribute an alternate.
        """
        radius_km = distance_km / (2 * math.pi) * 1.15  # rough circle-to-route fudge factor
        lat0, lon0 = start
        waypoints = []
        for bearing_deg in (60, 180, 300):
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
        profile = request.mapbox_profile()
        lat, lon = start_coords

        if request.is_loop:
            if request.via_points:
                coord_list = [(lat, lon), *request.via_points, (lat, lon)]
            else:
                if not request.target_distance_km:
                    raise RouteProviderError("Mapbox loop routing requires a target distance")
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

        coord_str = ";".join(f"{c[1]},{c[0]}" for c in coord_list)  # lon,lat order

        excludes = []
        if request.avoid_highways:
            excludes.append("motorway")
        if request.avoid_ferries:
            excludes.append("ferry")

        params = {
            "access_token": self.api_key,
            "geometries": "geojson",
            "overview": "full",
        }
        if excludes:
            params["exclude"] = ",".join(excludes)

        resp = requests.get(
            f"{BASE_URL}/directions/v5/mapbox/{profile}/{coord_str}",
            params=params,
            timeout=20,
        )
        if resp.status_code != 200:
            raise RouteProviderError(f"Mapbox directions failed: {resp.status_code} {resp.text}")

        data = resp.json()
        routes = data.get("routes", [])
        if not routes:
            raise RouteProviderError("Mapbox returned no routes")

        route = routes[0]
        coords = route["geometry"]["coordinates"]  # [lon, lat]
        points = [RoutePoint(lat=c[1], lon=c[0]) for c in coords]

        return NormalizedRoute(
            provider=self.name,
            distance_km=route["distance"] / 1000,
            duration_min=route["duration"] / 60,
            elevation_gain_m=None,  # Mapbox Directions doesn't return elevation
            points=points,
            geometry_geojson=route["geometry"],
            raw_response=data,
        )
