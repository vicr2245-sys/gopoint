"""
Data models shared across the app: the structured request produced from a
natural-language prompt, and the normalized route result returned by any
provider.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Activity(str, Enum):
    CYCLING_ROAD = "cycling-road"
    CYCLING_MOUNTAIN = "cycling-mountain"
    CYCLING_REGULAR = "cycling-regular"
    RUNNING = "foot-running"
    WALKING = "foot-walking"
    HIKING = "foot-hiking"


class ElevationPreference(str, Enum):
    FLAT = "flat"
    HILLY = "hilly"
    NO_PREFERENCE = "no_preference"


@dataclass
class RouteRequest:
    """Structured output of the prompt parser — what the user actually wants."""

    activity: Activity
    start_location: str                     # free-text place name or "lat,lon"
    end_location: Optional[str] = None       # None => loop route back to start
    is_loop: bool = True
    target_distance_km: Optional[float] = None
    min_distance_km: Optional[float] = None
    max_distance_km: Optional[float] = None
    via_points: list[tuple[float, float]] = field(default_factory=list)
    auto_close_loop: bool = True            # editing-only: force via_points to close back to start
    elevation_preference: ElevationPreference = ElevationPreference.NO_PREFERENCE
    target_elevation_gain_m: Optional[float] = None  # explicit numeric target, e.g. "aim for 500m of climbing"
    avoid_main_roads: bool = False
    avoid_highways: bool = True
    avoid_ferries: bool = True               # avoid ferries / water crossings by default
    surface_preference: Optional[str] = None  # e.g. "paved", "gravel", "trail"
    raw_prompt: str = ""

    def planning_distance_km(self) -> Optional[float]:
        if self.target_distance_km:
            return self.target_distance_km
        if self.min_distance_km and self.max_distance_km:
            return (self.min_distance_km + self.max_distance_km) / 2
        return None

    def ors_profile(self) -> str:
        """Map our Activity enum to an OpenRouteService profile string."""
        mapping = {
            Activity.CYCLING_ROAD: "cycling-road",
            Activity.CYCLING_MOUNTAIN: "cycling-mountain",
            Activity.CYCLING_REGULAR: "cycling-regular",
            Activity.RUNNING: "foot-walking",
            Activity.WALKING: "foot-walking",
            Activity.HIKING: "foot-hiking",
        }
        return mapping[self.activity]

    def mapbox_profile(self) -> str:
        """Map our Activity enum to a Mapbox Directions profile string."""
        mapping = {
            Activity.CYCLING_ROAD: "cycling",
            Activity.CYCLING_MOUNTAIN: "cycling",
            Activity.CYCLING_REGULAR: "cycling",
            Activity.RUNNING: "walking",
            Activity.WALKING: "walking",
            Activity.HIKING: "walking",
        }
        return mapping[self.activity]

    def osrm_profile(self) -> str:
        """Map our Activity enum to an OSRM profile string (foot/bike/car)."""
        mapping = {
            Activity.CYCLING_ROAD: "bike",
            Activity.CYCLING_MOUNTAIN: "bike",
            Activity.CYCLING_REGULAR: "bike",
            Activity.RUNNING: "foot",
            Activity.WALKING: "foot",
            Activity.HIKING: "foot",
        }
        return mapping[self.activity]


@dataclass
class RoutePoint:
    lat: float
    lon: float
    elevation_m: Optional[float] = None


@dataclass
class RouteInstruction:
    text: str
    lat: float
    lon: float
    distance_m: Optional[float] = None
    duration_s: Optional[float] = None
    turn_type: Optional[int] = None


@dataclass
class SurfaceSegment:
    start_index: int
    end_index: int
    category: str


@dataclass
class NormalizedRoute:
    """A route result normalized to a common shape regardless of provider."""

    provider: str
    distance_km: float
    duration_min: float
    elevation_gain_m: Optional[float]
    points: list[RoutePoint] = field(default_factory=list)
    instructions: list[RouteInstruction] = field(default_factory=list)
    surface_composition: dict[str, float] = field(default_factory=dict)
    surface_segments: list[SurfaceSegment] = field(default_factory=list)
    geometry_geojson: Optional[dict] = None   # ready to hand to Leaflet
    raw_response: Optional[dict] = None       # kept for debugging / fallback

    def summary(self) -> str:
        gain = f"{self.elevation_gain_m:.0f}m gain" if self.elevation_gain_m else "elevation n/a"
        surface = self.surface_summary()
        suffix = f", {surface}" if surface else ""
        return (f"[{self.provider}] {self.distance_km:.1f} km, "
                f"{self.duration_min:.0f} min, {gain}{suffix}")

    def surface_summary(self) -> str:
        if not self.surface_composition:
            return ""
        ranked = sorted(
            self.surface_composition.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        top = [f"{name.lower()} {percent:.0f}%" for name, percent in ranked[:2] if percent >= 1]
        return " / ".join(top)
