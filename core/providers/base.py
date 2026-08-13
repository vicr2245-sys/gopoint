"""
Abstract interface every routing provider must implement. This is what makes
the "multiple map providers" part pluggable: the route_engine talks only to
this interface and doesn't care whether it's ORS, Mapbox, OSRM, or something
added later (Komoot, Strava segments, GraphHopper, etc).
"""
from abc import ABC, abstractmethod
from typing import Optional

from models.route_request import NormalizedRoute, RouteRequest


class RouteProviderError(Exception):
    """Raised when a provider fails to produce a route (bad key, no route
    found, rate limited, etc). The route_engine catches these per-provider
    so one provider failing doesn't take down the whole request."""


class RouteProvider(ABC):
    name: str = "base"

    @abstractmethod
    def geocode(self, place_name: str) -> tuple[float, float]:
        """Resolve a free-text place name to (lat, lon)."""
        raise NotImplementedError

    @abstractmethod
    def get_route(
        self,
        request: RouteRequest,
        start_coords: tuple[float, float],
        end_coords: Optional[tuple[float, float]] = None,
    ) -> NormalizedRoute:
        """
        Fetch a route matching the request. If end_coords is None and
        request.is_loop is True, the provider should construct a loop route
        (providers differ in how they support this natively — see each
        implementation for its strategy).
        """
        raise NotImplementedError

    def supports_loops_natively(self) -> bool:
        """Whether this provider has a native 'round trip' routing mode."""
        return False
