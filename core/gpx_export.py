"""
Small GPX/TCX writers for exporting the selected route to watches, bike
computers, and route services.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from xml.sax.saxutils import escape

from models.route_request import NormalizedRoute


def route_to_gpx(route: NormalizedRoute, name: str = "GoPoint Route") -> str:
    track_points = _track_points(route)
    if not track_points:
        raise ValueError("Route has no points to export")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="GoPoint" xmlns="http://www.topografix.com/GPX/1/1">',
        "  <trk>",
        f"    <name>{escape(name)}</name>",
        "    <trkseg>",
    ]

    for point in track_points:
        lines.append(f'      <trkpt lat="{point["lat"]:.7f}" lon="{point["lon"]:.7f}">')
        if point.get("ele") is not None:
            lines.append(f'        <ele>{point["ele"]:.1f}</ele>')
        lines.append("      </trkpt>")

    lines.extend([
        "    </trkseg>",
        "  </trk>",
        "</gpx>",
        "",
    ])
    return "\n".join(lines)


def route_to_tcx(route: NormalizedRoute, name: str = "GoPoint Route") -> str:
    track_points = _track_points(route)
    if not track_points:
        raise ValueError("Route has no points to export")

    start_time = datetime.now(timezone.utc).replace(microsecond=0)
    duration_s = max(route.duration_min * 60, len(track_points) - 1)
    distance_m = max(route.distance_km * 1000, 1)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"',
        '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '  xsi:schemaLocation="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 '
        'http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd">',
        "  <Courses>",
        "    <Course>",
        f"      <Name>{escape(_short_name(name))}</Name>",
        "      <Track>",
    ]

    cumulative_m = 0.0
    for index, point in enumerate(track_points):
        if index > 0:
            cumulative_m += _distance_m(track_points[index - 1], point)

        elapsed_s = (cumulative_m / distance_m) * duration_s
        timestamp = _tcx_time(start_time + timedelta(seconds=elapsed_s))

        lines.extend([
            "        <Trackpoint>",
            f"          <Time>{timestamp}</Time>",
            "          <Position>",
            f"            <LatitudeDegrees>{point['lat']:.7f}</LatitudeDegrees>",
            f"            <LongitudeDegrees>{point['lon']:.7f}</LongitudeDegrees>",
            "          </Position>",
            f"          <DistanceMeters>{cumulative_m:.1f}</DistanceMeters>",
        ])
        if point.get("ele") is not None:
            lines.append(f"          <AltitudeMeters>{point['ele']:.1f}</AltitudeMeters>")
        lines.append("        </Trackpoint>")

    lines.append("      </Track>")
    lines.extend(_course_point_lines(route, start_time))
    lines.extend([
        "    </Course>",
        "  </Courses>",
        "</TrainingCenterDatabase>",
        "",
    ])
    return "\n".join(lines)


def _track_points(route: NormalizedRoute) -> list[dict]:
    if route.points:
        return [
            {"lat": point.lat, "lon": point.lon, "ele": point.elevation_m}
            for point in route.points
        ]

    geometry = route.geometry_geojson or {}
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "MultiLineString":
        coords = [coord for segment in coords for coord in segment]

    points = []
    for coord in coords:
        if len(coord) < 2:
            continue
        points.append({
            "lat": coord[1],
            "lon": coord[0],
            "ele": coord[2] if len(coord) > 2 else None,
        })
    return points


def _course_point_lines(route: NormalizedRoute, start_time: datetime) -> list[str]:
    points = []
    instructions = route.instructions

    if not instructions and route.points:
        first = route.points[0]
        last = route.points[-1]
        instructions = [
            type("Instruction", (), {
                "text": "Start",
                "lat": first.lat,
                "lon": first.lon,
                "turn_type": None,
            })(),
            type("Instruction", (), {
                "text": "Finish",
                "lat": last.lat,
                "lon": last.lon,
                "turn_type": None,
            })(),
        ]

    for index, instruction in enumerate(instructions):
        timestamp = _tcx_time(start_time + timedelta(seconds=index))
        point_type = _tcx_point_type(instruction.turn_type, instruction.text)
        points.extend([
            "      <CoursePoint>",
            f"        <Name>{escape(_short_name(instruction.text))}</Name>",
            f"        <Time>{timestamp}</Time>",
            "        <Position>",
            f"          <LatitudeDegrees>{instruction.lat:.7f}</LatitudeDegrees>",
            f"          <LongitudeDegrees>{instruction.lon:.7f}</LongitudeDegrees>",
            "        </Position>",
            f"        <PointType>{point_type}</PointType>",
            f"        <Notes>{escape(instruction.text)}</Notes>",
            "      </CoursePoint>",
        ])

    return points


def _tcx_point_type(turn_type: Optional[int], text: str) -> str:
    text_lower = text.lower()
    if turn_type in {0, 1, 2} or "left" in text_lower:
        return "Left"
    if turn_type in {3, 4, 5} or "right" in text_lower:
        return "Right"
    if "straight" in text_lower or "continue" in text_lower:
        return "Straight"
    if "finish" in text_lower:
        return "Generic"
    return "Generic"


def _distance_m(a: dict, b: dict) -> float:
    from math import atan2, cos, radians, sin, sqrt

    lat1 = radians(a["lat"])
    lat2 = radians(b["lat"])
    dlat = lat2 - lat1
    dlon = radians(b["lon"] - a["lon"])
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371000 * 2 * atan2(sqrt(h), sqrt(1 - h))


def _tcx_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _short_name(value: str, limit: int = 48) -> str:
    value = value.strip() or "Route"
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "..."
