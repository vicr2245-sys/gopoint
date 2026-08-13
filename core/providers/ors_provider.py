"""
OpenRouteService (https://openrouteservice.org) provider.

This is the primary provider because it natively supports:
- Activity-specific profiles (cycling-road, cycling-mountain, foot-hiking, etc)
- "Round trip" routing (loops) via the `round_trip` options block
- Elevation data (`elevation=true`)
- Avoiding features like highways/steps via `options.avoid_features`

Free tier: ~2000 requests/day, get a key at https://openrouteservice.org/dev/#/signup
"""
import os
from math import asin, atan2, cos, degrees, pi, radians, sin
from typing import Optional

import requests
from requests import RequestException


def destination_point(lat: float, lon: float, distance_km: float, bearing_deg: float) -> tuple[float, float]:
    """Calculates (lat, lon) given a starting (lat, lon), distance in km, and bearing in degrees."""
    R = 6371.0  # Earth radius in km
    d = distance_km / R
    brng = radians(bearing_deg)
    lat1 = radians(lat)
    lon1 = radians(lon)

    lat2 = asin(sin(lat1) * cos(d) + cos(lat1) * sin(d) * cos(brng))
    lon2 = lon1 + atan2(sin(brng) * sin(d) * cos(lat1), cos(d) - sin(lat1) * sin(lat2))
    return (degrees(lat2), degrees(lon2))

from core.geo import trim_overlapping_spurs
from core.providers.base import RouteProvider, RouteProviderError
from core.surfaces import surface_label_for_ors_code
from models.route_request import (
    NormalizedRoute,
    RouteInstruction,
    RoutePoint,
    RouteRequest,
    SurfaceSegment,
)

BASE_URL = "https://api.openrouteservice.org"
LOOP_SEEDS_FIRST_ROUND = (1, 2, 3, 4)
LOOP_SEEDS_CORRECTION_ROUND = (1, 2)
LOOP_POINTS_PRIMARY = 4
# Tried only if the primary 4-waypoint shape can't converge within
# tolerance — a different waypoint count produces a genuinely different
# candidate loop shape, which can succeed where the primary shape is
# blocked by real road-network constraints (a single bridge/crossing, a
# dead end, sparse rural roads, etc) that no amount of seed or length
# tweaking within the SAME shape would fix.
LOOP_POINTS_FALLBACK = (3, 5, 6, 2)
LOOP_SEEDS_FALLBACK_FIRST_ROUND = (1, 2, 3)
LOOP_SEEDS_FALLBACK_CORRECTION_ROUND = (1, 2)
MAX_LENGTH_CORRECTION_ROUNDS = 5
MAX_LENGTH_CORRECTION_ROUNDS_FALLBACK = 2
LENGTH_CORRECTION_TOLERANCE = 0.03  # stop once within 3% of target distance
REQUEST_TIMEOUT_SECONDS = 12

# Elevation-gain targeting: ORS's round_trip has no native "aim for X
# meters of climbing" option — length/points/seed only shape distance, not
# elevation. So when a numeric target_elevation_gain_m is given, we treat
# every candidate route already gathered while converging on distance as a
# free sample of that area's elevation variety (each seed produces a
# different physical path, and therefore a different elevation profile,
# at roughly the same distance) and pick whichever candidate's elevation
# gain is closest to the target. If none of those are close enough, we pay
# for a modest extra round of seeds at the same (already distance-
# converged) length, purely to search for a better elevation match.
ELEVATION_CANDIDATE_DISTANCE_TOLERANCE = 0.15  # "close enough" distance to be usable as an elevation candidate
ELEVATION_TARGET_TOLERANCE = 0.20  # accept once within 20% of the requested elevation gain
ELEVATION_EXTRA_SEEDS = (11, 12, 13, 14, 15, 16)  # distinct from the distance-search seeds, for fresh shapes


class ORSProvider(RouteProvider):
    name = "OpenRouteService"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ORS_API_KEY")
        if not self.api_key:
            raise RouteProviderError("ORS_API_KEY not set")

    def _headers(self):
        return {"Authorization": self.api_key, "Content-Type": "application/json"}

    def geocode(self, place_name: str) -> tuple[float, float]:
        resp = requests.get(
            f"{BASE_URL}/geocode/search",
            params={"api_key": self.api_key, "text": place_name, "size": 1},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RouteProviderError(f"ORS geocode failed: {resp.status_code} {resp.text}")
        features = resp.json().get("features", [])
        if not features:
            raise RouteProviderError(f"ORS geocode found no results for '{place_name}'")
        lon, lat = features[0]["geometry"]["coordinates"]
        return (lat, lon)

    def supports_loops_natively(self) -> bool:
        return True

    def get_route(
        self,
        request: RouteRequest,
        start_coords: tuple[float, float],
        end_coords: Optional[tuple[float, float]] = None,
    ) -> NormalizedRoute:
        profile = request.ors_profile()
        lat, lon = start_coords

        avoid_features = []
        if request.avoid_ferries:
            avoid_features.append("ferries")
        if request.avoid_highways and profile.startswith("driving"):
            avoid_features.append("highways")

        coordinates = [[lon, lat]]
        coordinates.extend([[point_lon, point_lat] for point_lat, point_lon in request.via_points])
        if request.is_loop and request.via_points:
            coordinates.append([lon, lat])
        elif not request.is_loop and end_coords:
            coordinates.append([end_coords[1], end_coords[0]])
        if not request.is_loop and len(coordinates) < 2:
            raise RouteProviderError("Routing requires at least two points (start and destination or waypoint)")

        body = {
            "coordinates": coordinates,
            "elevation": True,
            "extra_info": ["surface"],
            "instructions": True,
        }

        if avoid_features:
            body["options"] = {"avoid_features": avoid_features}

        if request.is_loop and not request.via_points:
            planning_distance_km = request.planning_distance_km()
            if not planning_distance_km:
                raise RouteProviderError("ORS round-trip routing requires a target distance or distance range")
            raw_route = self._get_best_round_trip(
                profile, body, planning_distance_km, request.target_elevation_gain_m
            )
            return trim_overlapping_spurs(raw_route)

        data = self._post_directions(profile, body)
        route = self._normalize(data)

        target_end = None
        if request.is_loop:
            target_end = (lat, lon)
        elif request.via_points:
            target_end = (request.via_points[-1][0], request.via_points[-1][1])
        elif end_coords:
            target_end = (end_coords[0], end_coords[1])

        if target_end:
            from core.geo import cumulative_distances_km, trim_trailing_overshoot
            trimmed_points = trim_trailing_overshoot(route.points, target_end[0], target_end[1])
            cum_dist = cumulative_distances_km(trimmed_points)
            route = NormalizedRoute(
                provider=route.provider,
                distance_km=cum_dist[-1] if cum_dist else 0.0,
                duration_min=route.duration_min,
                elevation_gain_m=route.elevation_gain_m,
                points=trimmed_points,
                instructions=route.instructions,
                surface_composition=route.surface_composition,
                surface_segments=route.surface_segments,
                geometry_geojson={
                    "type": "LineString",
                    "coordinates": [[p.lon, p.lat] for p in trimmed_points],
                },
            )

        return trim_overlapping_spurs(route)

    def _get_best_round_trip(
        self,
        profile: str,
        base_body: dict,
        target_distance_km: float,
        target_elevation_gain_m: Optional[float] = None,
    ) -> NormalizedRoute:
        # ORS's native round_trip options block has a server-side ceiling
        # of 100,000 meters (100km). For routes > 95km, bypass native
        # round_trip and synthesize a multi-waypoint polygon loop instead!
        if target_distance_km > 95.0:
            return self._search_synthesized_waypoint_loop(
                profile, base_body, target_distance_km, target_elevation_gain_m
            )

        errors: list[str] = []
        all_candidates: list[NormalizedRoute] = []

        best, best_error = self._search_round_trip_shape(
            profile,
            base_body,
            target_distance_km,
            points=LOOP_POINTS_PRIMARY,
            first_round_seeds=LOOP_SEEDS_FIRST_ROUND,
            correction_seeds=LOOP_SEEDS_CORRECTION_ROUND,
            max_rounds=MAX_LENGTH_CORRECTION_ROUNDS,
            errors=errors,
            candidates_out=all_candidates,
        )

        if not (best is not None and best_error <= LENGTH_CORRECTION_TOLERANCE):
            for alt_points in LOOP_POINTS_FALLBACK:
                alt_best, alt_error = self._search_round_trip_shape(
                    profile,
                    base_body,
                    target_distance_km,
                    points=alt_points,
                    first_round_seeds=LOOP_SEEDS_FALLBACK_FIRST_ROUND,
                    correction_seeds=LOOP_SEEDS_FALLBACK_CORRECTION_ROUND,
                    max_rounds=MAX_LENGTH_CORRECTION_ROUNDS_FALLBACK,
                    errors=errors,
                    candidates_out=all_candidates,
                )
                if alt_best is not None and alt_error < best_error:
                    best, best_error = alt_best, alt_error
                if best_error <= LENGTH_CORRECTION_TOLERANCE:
                    break  # good enough, stop searching further shapes

        if best is None:
            # If native round_trip failed because of ORS server configuration limit (code 2004),
            # fall back to synthesized polygon loop!
            if any("100000" in err or "exceed the server configuration limits" in err for err in errors):
                return self._search_synthesized_waypoint_loop(
                    profile, base_body, target_distance_km, target_elevation_gain_m
                )
            detail = "; ".join(errors[-3:]) if errors else "no routes returned"
            raise RouteProviderError(f"ORS round-trip routing failed: {detail}")

        if target_elevation_gain_m:
            return self._pick_for_elevation_target(
                profile, base_body, target_distance_km, target_elevation_gain_m,
                distance_best=best, all_candidates=all_candidates, errors=errors,
            )

        return best

    def _search_synthesized_waypoint_loop(
        self,
        profile: str,
        base_body: dict,
        target_distance_km: float,
        target_elevation_gain_m: Optional[float] = None,
    ) -> NormalizedRoute:
        """
        Synthesizes a multi-waypoint polygon loop around start_coords to
        bypass ORS's 100,000m (100km) round_trip ceiling. Sends a standard
        multi-waypoint coordinates request to ORS (which supports routes
        up to 6,000km).
        """
        start_lon, start_lat = base_body["coordinates"][0]

        candidate_setups = [
            (4, 45.0),    # 4 waypoints, initial heading 45deg
            (4, 0.0),     # 4 waypoints, initial heading 0deg
            (4, 90.0),    # 4 waypoints, initial heading 90deg
            (4, 135.0),   # 4 waypoints, initial heading 135deg
            (3, 30.0),    # 3 waypoints, initial heading 30deg
            (3, 90.0),    # 3 waypoints, initial heading 90deg
            (3, 300.0),   # 3 waypoints, initial heading 300deg
            (5, 15.0),    # 5 waypoints, initial heading 15deg
            (5, 60.0),    # 5 waypoints, initial heading 60deg
        ]

        best_route: Optional[NormalizedRoute] = None
        best_error = float("inf")
        errors: list[str] = []

        for num_points, initial_heading in candidate_setups:
            # Initial radius estimate for road loop: road winding factor ~ 0.70 of circle radius
            r_km = (target_distance_km / (2 * pi)) * 0.70

            for iteration in range(4):
                waypoints = []
                for i in range(num_points):
                    angle = initial_heading + (360.0 / num_points) * i
                    wp_lat, wp_lon = destination_point(start_lat, start_lon, r_km, angle)
                    waypoints.append([wp_lon, wp_lat])

                coords = [[start_lon, start_lat]] + waypoints + [[start_lon, start_lat]]
                radiuses = [-1] + [2500] * len(waypoints) + [-1]
                body = {
                    "coordinates": coords,
                    "radiuses": radiuses,
                    "elevation": True,
                    "extra_info": ["surface"],
                    "instructions": True,
                }
                if "options" in base_body and "avoid_features" in base_body["options"]:
                    body["options"] = {"avoid_features": base_body["options"]["avoid_features"]}

                try:
                    data = self._post_directions(profile, body)
                    route = self._normalize(data)
                except RouteProviderError as e:
                    errors.append(str(e))
                    r_km *= 0.85  # shrink radius slightly to pull waypoints closer to land
                    continue

                error = abs(route.distance_km - target_distance_km) / target_distance_km
                if error < best_error:
                    best_route = route
                    best_error = error

                if best_error <= LENGTH_CORRECTION_TOLERANCE:
                    return best_route

                # Rescale radius proportionally to close distance gap
                ratio = target_distance_km / max(route.distance_km, 1.0)
                r_km *= max(0.5, min(1.8, ratio))

        if best_route is not None:
            return best_route

        detail = "; ".join(errors[-3:]) if errors else "Could not generate long-distance loop"
        raise RouteProviderError(f"ORS long-distance loop routing failed: {detail}")

    def _pick_for_elevation_target(
        self,
        profile: str,
        base_body: dict,
        target_distance_km: float,
        target_elevation_gain_m: float,
        distance_best: NormalizedRoute,
        all_candidates: list[NormalizedRoute],
        errors: list[str],
    ) -> NormalizedRoute:
        """
        Chooses (or, if needed, searches harder for) whichever candidate
        route best matches target_elevation_gain_m while staying a
        plausible distance match. See _get_best_round_trip's docstring for
        why this works off already-fetched candidates rather than asking
        ORS for elevation directly — it can't.
        """
        def elevation_error(route: NormalizedRoute) -> float:
            gain = route.elevation_gain_m or 0.0
            return abs(gain - target_elevation_gain_m) / max(target_elevation_gain_m, 1.0)

        def distance_ok(route: NormalizedRoute) -> bool:
            return abs(route.distance_km - target_distance_km) / target_distance_km <= ELEVATION_CANDIDATE_DISTANCE_TOLERANCE

        viable = [r for r in all_candidates if distance_ok(r) and r.elevation_gain_m is not None]

        if viable:
            best_so_far = min(viable, key=elevation_error)
            if elevation_error(best_so_far) <= ELEVATION_TARGET_TOLERANCE:
                return best_so_far
        else:
            best_so_far = distance_best

        # Nothing gathered so far is a good elevation match — pay for a
        # small extra round of seeds at the length that already gave a
        # good distance match, purely hunting for a better elevation
        # profile at roughly the same distance.
        points = LOOP_POINTS_PRIMARY
        for seed in ELEVATION_EXTRA_SEEDS:
            body = {
                **base_body,
                "options": {
                    **base_body.get("options", {}),
                    "round_trip": {
                        "length": target_distance_km * 1000,
                        "points": points,
                        "seed": seed,
                    },
                },
            }
            try:
                route = self._normalize(self._post_directions(profile, body))
            except RouteProviderError as e:
                errors.append(str(e))
                continue

            if distance_ok(route) and route.elevation_gain_m is not None:
                if elevation_error(route) < elevation_error(best_so_far):
                    best_so_far = route
                if elevation_error(best_so_far) <= ELEVATION_TARGET_TOLERANCE:
                    break

        return best_so_far

    def _search_round_trip_shape(
        self,
        profile: str,
        base_body: dict,
        target_distance_km: float,
        points: int,
        first_round_seeds: tuple[int, ...],
        correction_seeds: tuple[int, ...],
        max_rounds: int,
        errors: list[str],
        candidates_out: Optional[list[NormalizedRoute]] = None,
    ) -> tuple[Optional[NormalizedRoute], float]:
        """
        Searches for the closest-matching loop using a FIXED waypoint
        count, sampling seeds each round and correcting the requested
        length toward the target based on actual returned distances.
        Returns (best_route_found, best_error_ratio) — best_error_ratio is
        float('inf') if nothing came back at all for this shape. Every
        successfully-fetched route is appended to candidates_out (if
        given), regardless of whether it was that round's winner.
        """
        requested_length_km = target_distance_km
        best: Optional[NormalizedRoute] = None
        best_error = float("inf")

        for round_num in range(max_rounds):
            seeds = first_round_seeds if round_num == 0 else correction_seeds
            round_best: Optional[NormalizedRoute] = None
            round_best_error = float("inf")

            for seed in seeds:
                body = {
                    **base_body,
                    "options": {
                        **base_body.get("options", {}),
                        "round_trip": {
                            "length": requested_length_km * 1000,
                            "points": points,
                            "seed": seed,
                        },
                    },
                }
                try:
                    route = self._normalize(self._post_directions(profile, body))
                except RouteProviderError as e:
                    errors.append(str(e))
                    continue

                if candidates_out is not None:
                    candidates_out.append(route)

                error = abs(route.distance_km - target_distance_km) / target_distance_km
                if error < best_error:
                    best = route
                    best_error = error
                if error < round_best_error:
                    round_best = route
                    round_best_error = error

            if round_best is None:
                break  # every request this round failed — nothing to correct from

            if best_error <= LENGTH_CORRECTION_TOLERANCE:
                break  # close enough to target, stop early

            # Rescale the length we ask ORS for, proportional to how far
            # off this round's closest result was. E.g. if we asked for
            # 15km and got 22km back, next round asks for roughly
            # 15 * (15/22) =~ 10.2km, nudging the actual output toward 15km.
            requested_length_km *= target_distance_km / max(round_best.distance_km, 0.1)

        return best, best_error

    def _post_directions(self, profile: str, body: dict) -> dict:
        try:
            resp = requests.post(
                f"{BASE_URL}/v2/directions/{profile}/geojson",
                headers=self._headers(),
                json=body,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
        except RequestException as e:
            response = getattr(e, "response", None)
            status = response.status_code if response is not None else "network"
            body_text = response.text if response is not None else str(e)
            raise RouteProviderError(f"ORS directions failed: {status} {body_text}") from e
        return resp.json()

    def _normalize(self, data: dict) -> NormalizedRoute:
        feature = data["features"][0]
        props = feature["properties"]["summary"]
        coords = feature["geometry"]["coordinates"]  # [lon, lat, elev]

        points = [
            RoutePoint(lat=c[1], lon=c[0], elevation_m=c[2] if len(c) > 2 else None)
            for c in coords
        ]
        instructions = self._extract_instructions(feature, coords)
        surface_composition = self._extract_surface_composition(feature, coords)
        surface_segments = self._extract_surface_segments(feature, coords)

        elevation_gain = None
        if points and points[0].elevation_m is not None:
            gains = [
                max(0, points[i + 1].elevation_m - points[i].elevation_m)
                for i in range(len(points) - 1)
            ]
            elevation_gain = sum(gains)

        return NormalizedRoute(
            provider=self.name,
            distance_km=props["distance"] / 1000,
            duration_min=props["duration"] / 60,
            elevation_gain_m=elevation_gain,
            points=points,
            instructions=instructions,
            surface_composition=surface_composition,
            surface_segments=surface_segments,
            geometry_geojson=feature["geometry"],
            raw_response=data,
        )

    def _extract_instructions(self, feature: dict, coords: list) -> list[RouteInstruction]:
        instructions = []
        segments = feature.get("properties", {}).get("segments", [])

        for segment in segments:
            for step in segment.get("steps", []):
                way_points = step.get("way_points") or []
                if not way_points:
                    continue

                coord_index = min(max(int(way_points[0]), 0), len(coords) - 1)
                coord = coords[coord_index]
                if len(coord) < 2:
                    continue

                text = step.get("instruction") or step.get("name") or "Continue"
                instructions.append(RouteInstruction(
                    text=text,
                    lat=coord[1],
                    lon=coord[0],
                    distance_m=step.get("distance"),
                    duration_s=step.get("duration"),
                    turn_type=step.get("type"),
                ))

        return instructions

    def _extract_surface_composition(self, feature: dict, coords: list) -> dict[str, float]:
        surface = feature.get("properties", {}).get("extras", {}).get("surface", {})

        grouped_distances: dict[str, float] = {}
        for item in surface.get("summary", []):
            label = surface_label_for_ors_code(item.get("value"))
            grouped_distances[label] = grouped_distances.get(label, 0.0) + float(item.get("distance", 0))

        if not grouped_distances:
            for start_idx, end_idx, value in surface.get("values", []):
                label = surface_label_for_ors_code(value)
                distance = self._coords_distance(coords, int(start_idx), int(end_idx))
                grouped_distances[label] = grouped_distances.get(label, 0.0) + distance

        total = sum(grouped_distances.values())
        if total <= 0:
            return {}

        composition = {
            category: (distance / total) * 100
            for category, distance in grouped_distances.items()
            if distance > 0
        }
        return dict(sorted(composition.items(), key=lambda item: item[1], reverse=True))

    def _extract_surface_segments(self, feature: dict, coords: list) -> list[SurfaceSegment]:
        if len(coords) < 2:
            return []

        surface = feature.get("properties", {}).get("extras", {}).get("surface", {})
        segments = []

        for item in surface.get("values", []):
            if len(item) < 3:
                continue
            start_idx, end_idx, value = item[:3]
            start_idx = max(0, min(int(start_idx), len(coords) - 1))
            end_idx = max(start_idx + 1, min(int(end_idx), len(coords) - 1))
            if end_idx <= start_idx:
                continue
            segments.append(SurfaceSegment(
                start_index=start_idx,
                end_index=end_idx,
                category=surface_label_for_ors_code(value),
            ))

        return segments

    def _coords_distance(self, coords: list, start_idx: int, end_idx: int) -> float:
        from math import atan2, cos, radians, sin, sqrt

        start_idx = max(0, min(start_idx, len(coords) - 1))
        end_idx = max(start_idx, min(end_idx, len(coords) - 1))
        distance = 0.0

        for i in range(start_idx, end_idx):
            a = coords[i]
            b = coords[i + 1]
            if len(a) < 2 or len(b) < 2:
                continue
            lat1 = radians(a[1])
            lat2 = radians(b[1])
            dlat = lat2 - lat1
            dlon = radians(b[0] - a[0])
            h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
            distance += 6371000 * 2 * atan2(sqrt(h), sqrt(1 - h))

        return distance
