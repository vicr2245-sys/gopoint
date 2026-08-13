"""
Tests core/gpx_import.py against synthetic GPX files covering: a closed
loop with timestamps and elevation, an open point-to-point route with no
timestamps (forcing the pace-estimate fallback), a file with no elevation
data at all (must not crash, must leave elevation_gain_m as None), and
malformed/empty files (must raise GPXImportError, not crash).

Run with: python3 test_gpx_import.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from core.gpx_import import GPXImportError, import_gpx
from models.route_request import Activity


def write_gpx(path: Path, points: list[tuple], with_time: bool = False, gpx_type: str = None):
    """points: list of (lat, lon, ele_or_None)"""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<gpx version="1.1" creator="test">', "<trk>"]
    if gpx_type:
        lines.append(f"<type>{gpx_type}</type>")
    lines.append("<trkseg>")
    for i, (lat, lon, ele) in enumerate(points):
        lines.append(f'<trkpt lat="{lat}" lon="{lon}">')
        if ele is not None:
            lines.append(f"<ele>{ele}</ele>")
        if with_time:
            lines.append(f"<time>2026-07-16T10:{i:02d}:00Z</time>")
        lines.append("</trkpt>")
    lines.append("</trkseg></trk></gpx>")
    path.write_text("\n".join(lines))


def test_loop_with_timestamps_and_elevation():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "loop.gpx"
        # A small square loop back to (near) the start, with rising then
        # falling elevation — gain should be the sum of the rises only.
        points = [
            (59.900, 10.700, 10),
            (59.901, 10.700, 20),  # +10
            (59.901, 10.701, 15),  # -5
            (59.900, 10.701, 25),  # +10
            (59.900, 10.700, 10),  # -15, back near start -> loop
        ]
        write_gpx(path, points, with_time=True, gpx_type="running")

        request, route = import_gpx(str(path))

        assert request.activity == Activity.RUNNING
        assert request.is_loop is True
        assert request.end_location is None
        assert "," in request.start_location  # lat,lon fast-path format

        assert route.elevation_gain_m == 20.0  # 10 + 10, ignoring the two descents
        assert route.duration_min == 4.0  # 4 minutes of timestamps (00:00 to 00:04)
        assert len(route.points) == 5
        assert route.distance_km > 0

        print("test_loop_with_timestamps_and_elevation: PASS")


def test_open_route_no_timestamps():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "open.gpx"
        # Start and end far apart -> not a loop. No <time> tags -> duration
        # must fall back to a pace estimate instead of crashing.
        points = [
            (59.900, 10.700, 5),
            (59.950, 10.750, 8),
            (60.000, 10.800, 12),
        ]
        write_gpx(path, points, with_time=False, gpx_type="cycling")

        request, route = import_gpx(str(path))

        assert request.is_loop is False
        assert request.end_location is not None
        assert request.activity == Activity.CYCLING_REGULAR
        assert route.duration_min > 0  # estimated, but must be a sane positive number

        print("test_open_route_no_timestamps: PASS")


def test_no_elevation_data():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "flat_data.gpx"
        points = [(59.900, 10.700, None), (59.901, 10.701, None), (59.902, 10.702, None)]
        write_gpx(path, points)

        request, route = import_gpx(str(path))

        assert route.elevation_gain_m is None, "should not fabricate a gain figure with no elevation data"
        assert all(p.elevation_m is None for p in route.points)

        print("test_no_elevation_data: PASS")


def test_malformed_file_raises_clean_error():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "broken.gpx"
        path.write_text("this is not xml at all { } <<<")

        try:
            import_gpx(str(path))
            assert False, "expected GPXImportError for malformed XML"
        except GPXImportError as e:
            assert "valid GPX" in str(e) or "XML" in str(e)
            print("test_malformed_file_raises_clean_error: PASS")


def test_empty_track_raises_clean_error():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "empty.gpx"
        path.write_text('<?xml version="1.0"?><gpx version="1.1"><trk><trkseg></trkseg></trk></gpx>')

        try:
            import_gpx(str(path))
            assert False, "expected GPXImportError for a track with no points"
        except GPXImportError as e:
            assert "track points" in str(e)
            print("test_empty_track_raises_clean_error: PASS")


def test_missing_file_raises_clean_error():
    try:
        import_gpx("/tmp/definitely_does_not_exist_12345.gpx")
        assert False, "expected GPXImportError for a missing file"
    except GPXImportError as e:
        assert "not found" in str(e).lower()
        print("test_missing_file_raises_clean_error: PASS")


if __name__ == "__main__":
    test_loop_with_timestamps_and_elevation()
    test_open_route_no_timestamps()
    test_no_elevation_data()
    test_malformed_file_raises_clean_error()
    test_empty_track_raises_clean_error()
    test_missing_file_raises_clean_error()
    print("\nPASS: all GPX import tests passed.")
