"""
Computes a rough difficulty rating (Easy / Moderate / Hard / Very Hard)
for a planned route, purely from data already available on the route and
request — no new API calls, no new dependencies.

This is deliberately a simple, explainable heuristic rather than a
black-box score: the goal is a quick gut-check ("is this route a big
ask?"), not a precise fitness metric. Every rating comes with a short
explanation string naming what actually drove the score, consistent with
how the rest of this app treats computed judgments (surface preference
scoring, elevation-target warnings, etc.) — never a bare number with no
justification.
"""
from dataclasses import dataclass
from typing import Optional

from models.route_request import Activity, NormalizedRoute

# (easy_km, hard_km): distance at/below easy_km scores 0 on the distance
# component, at/above hard_km scores 1, linear in between. Rough,
# activity-appropriate reference points, not precise thresholds — a 20km
# run and a 20km ride are very different asks, so each activity gets its
# own scale rather than one shared one.
DISTANCE_SCALE_KM: dict[Activity, tuple[float, float]] = {
    Activity.RUNNING: (5.0, 25.0),
    Activity.WALKING: (5.0, 20.0),
    Activity.HIKING: (8.0, 28.0),
    Activity.CYCLING_ROAD: (20.0, 90.0),
    Activity.CYCLING_MOUNTAIN: (15.0, 60.0),
    Activity.CYCLING_REGULAR: (15.0, 70.0),
}
DEFAULT_DISTANCE_SCALE_KM = (10.0, 50.0)  # fallback if activity is somehow unrecognized

# Elevation gain per km (m/km) — a standard "climbing intensity" measure.
# Shared across activities rather than activity-specific: steep is steep,
# and how much that actually costs a given activity is already partly
# reflected in the activity-specific distance scale above.
ELEVATION_FLAT_M_PER_KM = 8.0
ELEVATION_STEEP_M_PER_KM = 40.0

# Per-surface-category difficulty weight (0 = no penalty, 1 = maximum
# penalty), blended by the route's actual surface_composition percentages.
# Categories match core/surfaces.py's canonical labels.
SURFACE_DIFFICULTY: dict[str, float] = {
    "Asphalt": 0.0,
    "Concrete": 0.0,
    "Paving Stones": 0.05,
    "Paved (unspecified)": 0.05,
    "Metal": 0.15,
    "Wood": 0.15,
    "Cobblestone": 0.25,
    "Grass Paver": 0.3,
    "Compacted Gravel": 0.3,
    "Unpaved (unspecified)": 0.4,
    "Fine Gravel": 0.35,
    "Grass": 0.45,
    "Gravel": 0.45,
    "Woodchips": 0.45,
    "Ground": 0.5,
    "Dirt": 0.55,
    "Sand": 0.85,
    "Ice": 1.0,
    "Unknown": 0.0,  # no data — don't penalize for what we don't actually know
}
DEFAULT_SURFACE_DIFFICULTY = 0.2  # any category not in the table above
SURFACE_NOTABLE_THRESHOLD = 0.3   # only name a surface in the explanation if it's at least this taxing

DISTANCE_WEIGHT = 0.40
ELEVATION_WEIGHT = 0.35
SURFACE_WEIGHT = 0.25

# (upper_bound_exclusive, label) — first match wins, so ordered ascending.
LABEL_THRESHOLDS: list[tuple[float, str]] = [
    (25.0, "Easy"),
    (50.0, "Moderate"),
    (75.0, "Hard"),
    (101.0, "Very Hard"),  # 101 so a perfect 100.0 still matches this bucket
]


@dataclass
class DifficultyRating:
    score: float       # 0-100
    label: str         # "Easy" / "Moderate" / "Hard" / "Very Hard"
    explanation: str   # short human-readable justification, e.g. "12.4km, 180m climbing (15 m/km)"


def _distance_component(activity: Activity, distance_km: float) -> float:
    easy_km, hard_km = DISTANCE_SCALE_KM.get(activity, DEFAULT_DISTANCE_SCALE_KM)
    if distance_km <= easy_km:
        return 0.0
    if distance_km >= hard_km:
        return 1.0
    return (distance_km - easy_km) / (hard_km - easy_km)


def _elevation_component(elevation_gain_m: Optional[float], distance_km: float) -> tuple[float, Optional[float]]:
    """Returns (component 0-1, gain_per_km or None if no elevation data)."""
    if elevation_gain_m is None or distance_km <= 0:
        return 0.0, None
    gain_per_km = elevation_gain_m / distance_km
    span = ELEVATION_STEEP_M_PER_KM - ELEVATION_FLAT_M_PER_KM
    component = (gain_per_km - ELEVATION_FLAT_M_PER_KM) / span
    return max(0.0, min(1.0, component)), gain_per_km


def _surface_component(surface_composition: dict[str, float]) -> tuple[float, Optional[str]]:
    """Returns (component 0-1, name of the most notable difficult surface or None)."""
    if not surface_composition:
        return 0.0, None

    total_percent = sum(surface_composition.values()) or 1.0
    weighted = sum(
        SURFACE_DIFFICULTY.get(category, DEFAULT_SURFACE_DIFFICULTY) * percent
        for category, percent in surface_composition.items()
    ) / total_percent

    notable = max(
        (
            (category, percent)
            for category, percent in surface_composition.items()
            if SURFACE_DIFFICULTY.get(category, DEFAULT_SURFACE_DIFFICULTY) >= SURFACE_NOTABLE_THRESHOLD
        ),
        key=lambda item: item[1],
        default=(None, None),
    )
    return max(0.0, min(1.0, weighted)), notable[0]


def _label_for_score(score: float) -> str:
    for upper_bound, label in LABEL_THRESHOLDS:
        if score < upper_bound:
            return label
    return LABEL_THRESHOLDS[-1][1]


def compute_difficulty(activity: Activity, route: NormalizedRoute) -> DifficultyRating:
    distance_km = route.distance_km

    distance_comp = _distance_component(activity, distance_km)
    elevation_comp, gain_per_km = _elevation_component(route.elevation_gain_m, distance_km)
    surface_comp, notable_surface = _surface_component(route.surface_composition)

    raw_score = 100 * (
        DISTANCE_WEIGHT * distance_comp
        + ELEVATION_WEIGHT * elevation_comp
        + SURFACE_WEIGHT * surface_comp
    )
    score = max(0.0, min(100.0, raw_score))
    label = _label_for_score(score)

    parts = [f"{distance_km:.1f}km"]
    if gain_per_km is not None:
        parts.append(f"{route.elevation_gain_m:.0f}m climbing ({gain_per_km:.0f} m/km)")
    if notable_surface:
        parts.append(f"{notable_surface.lower()} sections")
    explanation = ", ".join(parts)

    return DifficultyRating(score=round(score, 1), label=label, explanation=explanation)
