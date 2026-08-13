"""
Shared geo-distance helpers. Kept separate from any one provider/feature
since both GPX export and the elevation profile chart need "distance along
a sequence of lat/lon points" — a single haversine implementation here
avoids each caller reimplementing (and potentially disagreeing on) the
same formula.
"""
from math import atan2, cos, radians, sin, sqrt

from models.route_request import RoutePoint


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_lat1, r_lat2 = radians(lat1), radians(lat2)
    dlat = r_lat2 - r_lat1
    dlon = radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(r_lat1) * cos(r_lat2) * sin(dlon / 2) ** 2
    return 6371000 * 2 * atan2(sqrt(h), sqrt(1 - h))


def cumulative_distances_km(points: list[RoutePoint]) -> list[float]:
    """Cumulative distance (km) from the first point, one value per point,
    same length as `points`. Returns an empty list for fewer than 2 points."""
    if len(points) < 2:
        return [0.0] * len(points)
    cumulative = [0.0]
    for prev, curr in zip(points, points[1:]):
        step_m = haversine_distance_m(prev.lat, prev.lon, curr.lat, curr.lon)
        cumulative.append(cumulative[-1] + step_m / 1000)
    return cumulative


def trim_trailing_overshoot(points: list[RoutePoint], end_lat: float, end_lon: float) -> list[RoutePoint]:
    """
    Ensures a route terminates precisely at (end_lat, end_lon) by finding the
    earliest point near the end of the route that reaches (end_lat, end_lon)
    and trimming any trailing overshoot nodes returned by routing engines.
    """
    if not points or len(points) < 3:
        return points

    # Search near the tail of the route (last 30% of points or last 100 points)
    search_start = max(1, len(points) - max(100, int(len(points) * 0.3)))
    tail_dists = [
        (idx, haversine_distance_m(points[idx].lat, points[idx].lon, end_lat, end_lon))
        for idx in range(search_start, len(points))
    ]
    if not tail_dists:
        return points

    min_dist = min(d for _, d in tail_dists)

    # Pick the FIRST point in the tail that comes within max(35m, min_dist + 15m) of the target.
    # This prevents the route from overshooting past the target to a distant node/turnaround
    # before returning or terminating.
    threshold_m = max(35.0, min_dist + 15.0)
    best_idx = tail_dists[-1][0]
    for idx, d in tail_dists:
        if d <= threshold_m:
            best_idx = idx
            break

    if best_idx < len(points) - 1:
        points = points[: max(2, best_idx + 1)]

    # Snap the final point precisely to (end_lat, end_lon)
    last_elev = points[-1].elevation_m
    if last_elev is None and len(points) >= 2:
        last_elev = points[-2].elevation_m
    points[-1] = RoutePoint(lat=end_lat, lon=end_lon, elevation_m=last_elev)
    return points


def trim_overlapping_spurs(route, max_spur_length_km: float = 12.0):
    """
    Detects and trims dead-end out-and-back spurs where a route travels
    down a road/dead-end to a turnaround point and backtracks over the exact
    same path/road (forming an overlapping stub/U-turn loop).
    """
    points = route.points
    if not points or len(points) < 6:
        return route

    modified = False
    new_points = list(points)

    i = 0
    while i < len(new_points) - 2:
        best_j = -1
        
        for j in range(i + 2, min(i + 400, len(new_points))):
            dist_ij_m = haversine_distance_m(
                new_points[i].lat, new_points[i].lon,
                new_points[j].lat, new_points[j].lon
            )
            if dist_ij_m < 45.0:
                mid_idx = (i + j) // 2
                out_dist = sum(
                    haversine_distance_m(new_points[idx].lat, new_points[idx].lon, new_points[idx+1].lat, new_points[idx+1].lon)
                    for idx in range(i, mid_idx)
                ) / 1000.0
                back_dist = sum(
                    haversine_distance_m(new_points[idx].lat, new_points[idx].lon, new_points[idx+1].lat, new_points[idx+1].lon)
                    for idx in range(mid_idx, j)
                ) / 1000.0
                
                total_spur_km = out_dist + back_dist
                if 0.01 <= total_spur_km <= max_spur_length_km:
                    if abs(out_dist - back_dist) / max(out_dist, 0.001) < 0.40:
                        sample_ok = True
                        step = max(1, (mid_idx - i) // 4)
                        for sample_i in range(i + 1, mid_idx, step):
                            min_dist_to_back = min(
                                haversine_distance_m(
                                    new_points[sample_i].lat, new_points[sample_i].lon,
                                    new_points[sample_j].lat, new_points[sample_j].lon
                                )
                                for sample_j in range(mid_idx, j)
                            )
                            if min_dist_to_back > 75.0:
                                sample_ok = False
                                break
                        
                        if sample_ok:
                            best_j = j
                            break

        if best_j != -1:
            new_points = new_points[:i+1] + new_points[best_j:]
            modified = True
        else:
            i += 1

    if not modified:
        return route

    new_cumulative = cumulative_distances_km(new_points)
    total_dist_km = new_cumulative[-1] if new_cumulative else 0.0
    
    elevation_gain = None
    if any(p.elevation_m is not None for p in new_points):
        gain = 0.0
        for k in range(len(new_points) - 1):
            e1 = new_points[k].elevation_m
            e2 = new_points[k + 1].elevation_m
            if e1 is not None and e2 is not None and e2 > e1:
                gain += e2 - e1
        elevation_gain = gain

    # Import type for constructor return
    from models.route_request import NormalizedRoute

    return NormalizedRoute(
        provider=route.provider,
        distance_km=total_dist_km,
        duration_min=(total_dist_km / route.distance_km) * route.duration_min if route.distance_km > 0 else route.duration_min,
        elevation_gain_m=elevation_gain,
        points=new_points,
        instructions=route.instructions,
        surface_composition=route.surface_composition,
        surface_segments=route.surface_segments,
        geometry_geojson={
            "type": "LineString",
            "coordinates": [[p.lon, p.lat] for p in new_points],
        },
        raw_response=route.raw_response,
    )
