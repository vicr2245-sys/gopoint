"""
Nominatim — OpenStreetMap's free geocoder. No signup, no API key, no card
required anywhere. This is geocoding-only (it doesn't do routing), so it's
used purely as an extra fallback for resolving place names to coordinates
alongside ORS.

Usage policy requires a descriptive User-Agent and caps requests at ~1/sec
for the public endpoint (https://operations.osmfoundation.org/policies/nominatim/).
Fine for interactive desktop-app use; self-host Nominatim if you need higher volume.
"""
import os

import requests

from core.providers.base import RouteProvider, RouteProviderError
from models.route_request import NormalizedRoute, RouteRequest
from typing import Optional

BASE_URL = "https://nominatim.openstreetmap.org"
USER_AGENT = os.environ.get("NOMINATIM_USER_AGENT", "route-planner-desktop-app/1.0")


class NominatimProvider(RouteProvider):
    name = "Nominatim"

    def geocode(self, place_name: str) -> tuple[float, float]:
        # Try with countrycode bias (Norway) first for local searches
        try:
            resp = requests.get(
                f"{BASE_URL}/search",
                params={"q": place_name, "format": "json", "limit": 1, "countrycodes": "no"},
                headers={"User-Agent": USER_AGENT},
                timeout=10,
            )
            if resp.status_code == 200:
                results = resp.json()
                if results:
                    return (float(results[0]["lat"]), float(results[0]["lon"]))
        except Exception:
            pass

        # Fallback to global search if no Norwegian match found
        resp = requests.get(
            f"{BASE_URL}/search",
            params={"q": place_name, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RouteProviderError(f"Nominatim geocode failed: {resp.status_code} {resp.text}")
        results = resp.json()
        if not results:
            raise RouteProviderError(f"Nominatim found no results for '{place_name}'")
        return (float(results[0]["lat"]), float(results[0]["lon"]))

    def get_route(
        self,
        request: RouteRequest,
        start_coords: tuple[float, float],
        end_coords: Optional[tuple[float, float]] = None,
    ) -> NormalizedRoute:
        raise RouteProviderError("Nominatim is geocoding-only and does not provide routing")
