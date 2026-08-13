"""
The orchestrator: takes a RouteRequest, geocodes locations, queries all
configured providers concurrently, and returns every route it could get
plus a ranked "best pick" based on the user's stated preferences.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from core.providers.base import RouteProvider, RouteProviderError
from core.surfaces import surface_preference_bonus
from models.route_request import ElevationPreference, NormalizedRoute, RouteRequest

logger = logging.getLogger(__name__)

MAX_DISTANCE_MISS_RATIO = 0.08
MAX_DISTANCE_MISS_KM = 1.5
ELEVATION_TARGET_WARNING_RATIO = 0.20  # warn if the picked route misses the elevation target by more than this


class RouteEngine:
    def __init__(self, providers: list[RouteProvider], geocode_providers: Optional[list[RouteProvider]] = None):
        """
        providers:          routing providers (get_route is called on each of these)
        geocode_providers:  extra geocoding-only providers (e.g. Nominatim) tried
                            FIRST when resolving a place name, before falling back
                            to the routing providers' own geocoders. Keeping these
                            separate means we never waste a routing call on a
                            provider — like Nominatim — that can't route at all.
        """
        if not providers:
            raise ValueError("RouteEngine needs at least one routing provider")
        self.providers = providers
        self.geocode_providers = geocode_providers or []

    def _resolve_coords(self, location: str) -> tuple[float, float]:
        """Try each geocoder (extra geocode-only ones first, then routing
        providers' built-in geocoders) in order until one succeeds."""
        if location == "current_location":
            raise RouteProviderError(
                "start_location was 'current_location' but no device location was supplied — "
                "wire up OS geolocation or ask the user for a location"
            )
        # Already coordinates?
        if "," in location:
            parts = location.split(",")
            try:
                return (float(parts[0]), float(parts[1]))
            except ValueError:
                pass

        last_error = None
        for provider in (*self.geocode_providers, *self.providers):
            try:
                return provider.geocode(location)
            except RouteProviderError as e:
                last_error = e
                continue
        raise RouteProviderError(f"No provider could geocode '{location}': {last_error}")

    def plan(
        self, request: RouteRequest
    ) -> tuple[list[NormalizedRoute], Optional[NormalizedRoute], list[str]]:
        """
        Returns (all_successful_routes, best_route, warnings).
        best_route is None only if every provider failed outright (network
        error, no route found at all, etc). Routes that came back but
        missed the requested distance are NOT dropped to None — geography
        (sparse roads, coastlines, islands) sometimes makes hitting an
        exact target impossible, so those are kept as a best-effort result
        with a warning explaining the mismatch, rather than failing the
        whole request over an imperfect-but-usable route.
        """
        start_coords = self._resolve_coords(request.start_location)
        end_coords = None
        if not request.is_loop and request.end_location:
            end_coords = self._resolve_coords(request.end_location)

        results: list[NormalizedRoute] = []
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=len(self.providers)) as executor:
            futures = {
                executor.submit(p.get_route, request, start_coords, end_coords): p
                for p in self.providers
                if self._should_query_provider(p, request)
            }
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    results.append(future.result())
                except RouteProviderError as e:
                    logger.warning("%s failed: %s", provider.name, e)
                    errors.append(f"{provider.name}: {e}")
                except Exception as e:  # provider bugs shouldn't kill the whole request
                    logger.exception("%s raised unexpectedly", provider.name)
                    errors.append(f"{provider.name}: unexpected error: {e}")

        if not results:
            raise RouteProviderError(f"All providers failed: {'; '.join(errors)}")

        if request.via_points:
            # During waypoint edits, keep ORS (primary rich-data engine) as the selected route.
            # If ORS failed during an edit, raise explicitly rather than silently dropping overlays
            # with an elevation-less / surface-less fallback provider.
            ors_errors = [e for e in errors if "openrouteservice" in e.lower()]
            ors_success = any("openrouteservice" in r.provider.lower() for r in results)
            if ors_errors and not ors_success:
                raise RouteProviderError(
                    f"Route edit failed: OpenRouteService (primary engine for surface & elevation data) failed: {ors_errors[0]}"
                )

        warnings: list[str] = []
        results = self._filter_distance_outliers(results, request, errors, warnings)

        if not results:
            # Every candidate route missed tolerance AND the fallback
            # below still came up empty — genuinely nothing usable.
            raise RouteProviderError(f"All providers failed: {'; '.join(errors)}")

        best = self._rank(results, request)
        self._warn_if_elevation_target_missed(best, request, warnings)
        return results, best, warnings

    def _warn_if_elevation_target_missed(
        self, best: NormalizedRoute, request: RouteRequest, warnings: list[str]
    ) -> None:
        """
        Unlike distance, ORS has no native way to target a specific
        elevation-gain figure — the provider does its best by sampling
        several candidate shapes and picking whichever's gain is closest
        (see ors_provider._pick_for_elevation_target), but real terrain
        near a given start point may simply not offer a loop with the
        requested amount of climbing. Surface that honestly rather than
        silently returning a route that doesn't match what was asked for.
        """
        if not request.target_elevation_gain_m or best.elevation_gain_m is None:
            return

        target = request.target_elevation_gain_m
        actual = best.elevation_gain_m
        error_ratio = abs(actual - target) / max(target, 1.0)
        if error_ratio <= ELEVATION_TARGET_WARNING_RATIO:
            return

        direction = "short of" if actual < target else "over"
        warnings.append(
            f"Requested ~{target:.0f}m of climbing, closest achievable nearby was "
            f"{actual:.0f}m ({abs(actual - target):.0f}m {direction} target). "
            f"Elevation gain depends on real terrain near the start point, so it's "
            f"more of a target than a guarantee — try a different start location "
            f"or a longer distance for more climbing to work with."
        )

    def _should_query_provider(self, provider: RouteProvider, request: RouteRequest) -> bool:
        """
        For a FRESH loop request (no via_points yet), only use providers
        with native round-trip support — ORS's round_trip algorithm
        searches for a loop of the right shape/length; Mapbox/OSRM's old
        synthetic waypoint-circle heuristic was unreliable and could miss
        short targets by tens of kilometers.

        Once via_points exist (the route is being edited, or was built
        from explicit waypoints), the "loop-ness" is no longer a search
        problem — it's just an ordinary sequence of waypoints that
        happens to end back near the start. Any provider can route
        through an explicit waypoint list, so the native-loop-only
        restriction applies solely to the initial, unconstrained
        round-trip search.
        """
        if request.is_loop and not request.via_points:
            return provider.supports_loops_natively()
        return True

    def _filter_distance_outliers(
        self,
        routes: list[NormalizedRoute],
        request: RouteRequest,
        errors: list[str],
        warnings: list[str],
    ) -> list[NormalizedRoute]:
        if request.via_points:
            return routes

        if not request.target_distance_km:
            if not request.min_distance_km or not request.max_distance_km:
                return routes

            accepted = [
                route for route in routes
                if request.min_distance_km <= route.distance_km <= request.max_distance_km
            ]
            rejected = [route for route in routes if route not in accepted]
            for route in rejected:
                errors.append(
                    f"{route.provider}: rejected {route.distance_km:.1f}km route "
                    f"outside {request.min_distance_km:.1f}-{request.max_distance_km:.1f}km range"
                )
            if accepted:
                return accepted
            return self._closest_distance_fallback(routes, request, warnings)

        tolerance_km = max(MAX_DISTANCE_MISS_KM, request.target_distance_km * MAX_DISTANCE_MISS_RATIO)
        accepted = [
            route for route in routes
            if abs(route.distance_km - request.target_distance_km) <= tolerance_km
        ]
        rejected = [route for route in routes if route not in accepted]

        for route in rejected:
            errors.append(
                f"{route.provider}: rejected {route.distance_km:.1f}km route "
                f"for {request.target_distance_km:.1f}km target"
            )

        if accepted:
            return accepted
        return self._closest_distance_fallback(routes, request, warnings)

    def _closest_distance_fallback(
        self,
        routes: list[NormalizedRoute],
        request: RouteRequest,
        warnings: list[str],
    ) -> list[NormalizedRoute]:
        """
        Every candidate route missed the distance tolerance — rather than
        failing the whole request, fall back to whichever route came
        closest. This matters most for loop requests: ORS's round-trip
        algorithm is doing its best against real road geometry (sparse
        coastal roads, islands, dead ends), and sometimes the closest it
        can physically get to a target is still outside our tolerance
        band. That's a usable route with a caveat, not a dead end — the
        UI surfaces `warnings` so the user knows it's an approximate
        match rather than silently showing (or silently refusing to show)
        something that doesn't match what they asked for.
        """
        if not routes:
            return []

        target = request.planning_distance_km()
        if not target:
            # Nothing to measure closeness against (shouldn't normally
            # happen here since both callers already checked for a target/
            # range) — just keep everything rather than guessing.
            return routes

        closest = min(routes, key=lambda r: abs(r.distance_km - target))
        miss_km = closest.distance_km - target
        direction = "short of" if miss_km < 0 else "over"
        warnings.append(
            f"No route matched your {target:.1f}km target closely enough — "
            f"showing the closest option found ({closest.provider}: "
            f"{closest.distance_km:.1f}km, {abs(miss_km):.1f}km {direction} target). "
            f"This can happen near coastlines, islands, or sparse road networks "
            f"where a loop of the exact requested length isn't physically possible."
        )
        return [closest]

    def _rank(self, routes: list[NormalizedRoute], request: RouteRequest) -> NormalizedRoute:
        """
        Score each route against the user's stated preferences and return
        the best one. Scoring is intentionally simple/explainable rather
        than a black box — easy to tune later.
        """
        candidates = routes
        if request.via_points:
            # During waypoint edits, restrict selection to providers supplying elevation and surface data (ORS)
            # so Mapbox/OSRM fallbacks without elevation/surface metadata cannot displace the primary route.
            rich_candidates = [
                r for r in routes
                if r.elevation_gain_m is not None and bool(r.surface_composition)
            ]
            if rich_candidates:
                candidates = rich_candidates
            else:
                elevation_candidates = [r for r in routes if r.elevation_gain_m is not None]
                if elevation_candidates:
                    candidates = elevation_candidates

        def score(route: NormalizedRoute) -> float:
            s = 0.0

            # Distance match (closer to target = better)
            planning_distance_km = request.planning_distance_km()
            if planning_distance_km:
                s -= abs(route.distance_km - planning_distance_km) * 2

            # Elevation: a numeric target (e.g. "aim for 500m of climbing")
            # is more specific than the coarse hilly/flat preference, so it
            # takes priority when both are present — the prompt parser
            # already sets elevation_preference=HILLY alongside any numeric
            # target, so this just refines that into an actual number match.
            if route.elevation_gain_m is not None:
                if request.target_elevation_gain_m:
                    error_ratio = abs(route.elevation_gain_m - request.target_elevation_gain_m) / max(
                        request.target_elevation_gain_m, 1.0
                    )
                    s -= error_ratio * 5  # dominant term when a specific target was requested
                else:
                    gain_per_km = route.elevation_gain_m / max(route.distance_km, 0.1)
                    if request.elevation_preference == ElevationPreference.HILLY:
                        s += gain_per_km  # more gain per km = better match
                    elif request.elevation_preference == ElevationPreference.FLAT:
                        s -= gain_per_km * 2  # penalize gain heavily

            # Providers with elevation data are more informative for
            # activity routing — nudge them ahead when scores are close
            if route.elevation_gain_m is not None:
                s += 0.5

            # Surface preference — only providers that returned surface
            # composition data (currently just ORS) can be scored on this;
            # routes with no data are neither rewarded nor punished.
            if request.surface_preference and route.surface_composition:
                s += self._surface_preference_score(route, request.surface_preference)

            return s

        return max(candidates, key=score)

    def _surface_preference_score(self, route: NormalizedRoute, preference: str) -> float:
        return surface_preference_bonus(route.surface_composition, preference)
