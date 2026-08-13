"""
Parses a .gpx file (exported from Strava, Garmin, Komoot, or our own GPX
export) into the same (RouteRequest, NormalizedRoute) shape used
everywhere else in the app — so an imported route can be viewed, edited,
exported, and saved through the exact same pipeline as a planned one.

Uses only the stdlib XML parser, matching gpx_export.py's approach — no
new dependency for something this simple.

Known scope limits, worth knowing:
- No surface composition (plain GPX doesn't carry that data).
- No turn-by-turn instructions.
- Editing an imported route re-routes through ORS from scratch using
  whatever waypoints you add — it does NOT preserve the original file's
  exact path as a base to tweak. Good for viewing/analyzing an existing
  route or as a rough starting point, not for surgically editing one
  street at a time while keeping the rest identical.
- Duration is only real if the GPX has timestamps (recorded tracks
  usually do; hand-drawn/planned-route GPX files usually don't) —
  otherwise it's a rough estimate from a generic pace for the guessed
  activity, clearly not precise.
"""
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from core.geo import cumulative_distances_km, haversine_distance_m
from models.route_request import (
    Activity,
    ElevationPreference,
    NormalizedRoute,
    RoutePoint,
    RouteRequest,
)

# GPX 1.1 is standard; some older exporters use 1.0, and a few omit the
# namespace entirely. Try each in turn rather than assuming one.
GPX_NS_ALTERNATES = [
    "{http://www.topografix.com/GPX/1/1}",
    "{http://www.topografix.com/GPX/1/0}",
    "",
]

LOOP_THRESHOLD_M = 150  # start/end within this distance counts as a loop

# Fallback pace used ONLY when the file has no timestamps to compute real
# elapsed time from — just enough to show a plausible duration, not a
# precise one. Real GPX exports from activity trackers almost always have
# timestamps; this mainly covers hand-planned route files.
FALLBACK_PACE_KMH = {
    Activity.RUNNING: 10.0,
    Activity.WALKING: 5.0,
    Activity.HIKING: 4.5,
    Activity.CYCLING_ROAD: 25.0,
    Activity.CYCLING_MOUNTAIN: 16.0,
    Activity.CYCLING_REGULAR: 18.0,
}


class GPXImportError(Exception):
    pass


def _find_all(root: ET.Element, tag: str) -> tuple[list[ET.Element], str]:
    for ns in GPX_NS_ALTERNATES:
        found = root.findall(f".//{ns}{tag}")
        if found:
            return found, ns
    return [], GPX_NS_ALTERNATES[0]


def _guess_activity(root: ET.Element, ns: str) -> Activity:
    type_el = root.find(f".//{ns}trk/{ns}type")
    text = (type_el.text or "").lower() if type_el is not None and type_el.text else ""
    if "run" in text:
        return Activity.RUNNING
    if "hik" in text:
        return Activity.HIKING
    if "walk" in text:
        return Activity.WALKING
    if "mountain" in text or "mtb" in text:
        return Activity.CYCLING_MOUNTAIN
    if "bike" in text or "cycl" in text or "ride" in text:
        return Activity.CYCLING_REGULAR
    return Activity.CYCLING_REGULAR  # reasonable generic default when unspecified


def _parse_gpx_time(text: str) -> datetime:
    # GPX timestamps are ISO 8601, usually with a trailing 'Z'. Python's
    # fromisoformat only accepts that suffix from 3.11 on, so normalize it
    # ourselves for compatibility with earlier versions too.
    normalized = text.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def import_gpx(file_path: str) -> tuple[RouteRequest, NormalizedRoute]:
    path = Path(file_path)
    if not path.exists():
        raise GPXImportError(f"File not found: {file_path}")

    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise GPXImportError(f"Not a valid GPX/XML file: {e}") from e

    root = tree.getroot()

    trkpts, ns = _find_all(root, "trkpt")
    if not trkpts:
        # Some GPX files describe a planned route via <rte>/<rtept> rather
        # than a recorded track via <trk>/<trkseg>/<trkpt> — support both.
        trkpts, ns = _find_all(root, "rtept")
    if not trkpts:
        raise GPXImportError("No track points found in this GPX file (expected <trkpt> or <rtept>)")

    points: list[RoutePoint] = []
    timestamps: list[datetime] = []

    for pt in trkpts:
        try:
            lat = float(pt.attrib["lat"])
            lon = float(pt.attrib["lon"])
        except (KeyError, ValueError):
            continue  # skip malformed points rather than failing the whole import

        ele_el = pt.find(f"{ns}ele")
        elevation_m = None
        if ele_el is not None and ele_el.text:
            try:
                elevation_m = float(ele_el.text)
            except ValueError:
                pass

        points.append(RoutePoint(lat=lat, lon=lon, elevation_m=elevation_m))

        time_el = pt.find(f"{ns}time")
        if time_el is not None and time_el.text:
            try:
                timestamps.append(_parse_gpx_time(time_el.text))
            except ValueError:
                pass

    if len(points) < 2:
        raise GPXImportError("GPX file has fewer than 2 usable track points")

    distances_km = cumulative_distances_km(points)
    total_distance_km = distances_km[-1]

    elevations = [p.elevation_m for p in points]
    has_elevation = all(e is not None for e in elevations)
    elevation_gain_m = None
    if has_elevation:
        elevation_gain_m = sum(max(0.0, b - a) for a, b in zip(elevations, elevations[1:]))

    activity = _guess_activity(root, ns)

    if len(timestamps) == len(points) and len(timestamps) >= 2:
        elapsed_s = (timestamps[-1] - timestamps[0]).total_seconds()
        duration_min = max(elapsed_s / 60, 0.1)
    else:
        pace_kmh = FALLBACK_PACE_KMH.get(activity, 15.0)
        duration_min = (total_distance_km / pace_kmh) * 60

    loop_distance_m = haversine_distance_m(points[0].lat, points[0].lon, points[-1].lat, points[-1].lon)
    is_loop = loop_distance_m <= LOOP_THRESHOLD_M

    start = points[0]
    end = points[-1]

    # "lat,lon" as start_location fast-paths through RouteEngine's own
    # coordinate parsing (it checks for a comma before trying to geocode),
    # so re-planning/editing this imported route later works with zero
    # extra geocoding calls or reverse-geocoding infrastructure needed.
    request = RouteRequest(
        activity=activity,
        start_location=f"{start.lat},{start.lon}",
        end_location=None if is_loop else f"{end.lat},{end.lon}",
        is_loop=is_loop,
        target_distance_km=round(total_distance_km, 1),
        elevation_preference=ElevationPreference.NO_PREFERENCE,
        raw_prompt=f"Imported from {path.name}",
    )

    route = NormalizedRoute(
        provider="GPX Import",
        distance_km=total_distance_km,
        duration_min=duration_min,
        elevation_gain_m=elevation_gain_m,
        points=points,
        geometry_geojson={
            "type": "LineString",
            "coordinates": [[p.lon, p.lat] for p in points],
        },
    )

    return request, route
