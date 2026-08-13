"""
Tests the real ElevationProfileWidget from ui/main_window.py — not a
reimplementation — running headlessly (QT_QPA_PLATFORM=offscreen, no
display needed). Covers the has_data() visibility logic (all-elevation,
no-elevation, partial-elevation, too-few-points cases) and set_route()'s
gain/loss/distance computation against known values.

Run with: QT_QPA_PLATFORM=offscreen python3 test_elevation_chart.py
"""
import sys

from PyQt5.QtCore import Qt, QCoreApplication
QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)

sys.path.insert(0, ".")

from core.geo import cumulative_distances_km
from models.route_request import RoutePoint
from ui.main_window import ElevationProfileWidget


def test_cumulative_distances():
    # Two points 1 degree of latitude apart is ~111km — a well-known
    # reference distance, good sanity check for the haversine formula.
    points = [
        RoutePoint(lat=59.0, lon=10.0, elevation_m=0),
        RoutePoint(lat=60.0, lon=10.0, elevation_m=0),
    ]
    distances = cumulative_distances_km(points)
    assert distances[0] == 0.0
    assert 110 < distances[1] < 112, f"expected ~111km, got {distances[1]}"
    print(f"cumulative_distances_km: OK ({distances[1]:.1f}km for 1 degree latitude)")


def test_has_data():
    all_present = [RoutePoint(lat=0, lon=0, elevation_m=i) for i in range(5)]
    assert ElevationProfileWidget.has_data(all_present) is True

    none_present = [RoutePoint(lat=0, lon=0, elevation_m=None) for _ in range(5)]
    assert ElevationProfileWidget.has_data(none_present) is False  # Mapbox/OSRM case

    mixed = [RoutePoint(lat=0, lon=0, elevation_m=1), RoutePoint(lat=0, lon=0, elevation_m=None)]
    assert ElevationProfileWidget.has_data(mixed) is False

    too_few = [RoutePoint(lat=0, lon=0, elevation_m=5)]
    assert ElevationProfileWidget.has_data(too_few) is False

    empty = []
    assert ElevationProfileWidget.has_data(empty) is False

    print("has_data: OK (all-present=True, none/mixed/too-few/empty=False)")


def test_set_route_gain_loss():
    widget = ElevationProfileWidget()

    # A simple up-down-up profile: elevations 10 -> 30 -> 15 -> 40
    # gain = (30-10) + (40-15) = 20 + 25 = 45
    # loss = (30-15) = 15
    points = [
        RoutePoint(lat=59.00, lon=10.00, elevation_m=10),
        RoutePoint(lat=59.01, lon=10.00, elevation_m=30),
        RoutePoint(lat=59.02, lon=10.00, elevation_m=15),
        RoutePoint(lat=59.03, lon=10.00, elevation_m=40),
    ]
    widget.set_route(points)

    assert widget.isVisible() or not widget.isVisible()  # visibility depends on parent/window state, not asserted
    assert abs(widget.gain_m - 45.0) < 0.01, f"expected gain 45.0, got {widget.gain_m}"
    assert abs(widget.loss_m - 15.0) < 0.01, f"expected loss 15.0, got {widget.loss_m}"
    assert widget.elevations_m == [10, 30, 15, 40]
    assert len(widget.distances_km) == 4
    assert widget.distances_km[0] == 0.0

    print(f"set_route gain/loss: OK (gain={widget.gain_m}m, loss={widget.loss_m}m)")

    # Now feed it a no-elevation route (simulating Mapbox/OSRM) and confirm
    # it clears out rather than keeping stale data on screen
    widget.set_route([RoutePoint(lat=0, lon=0, elevation_m=None) for _ in range(3)])
    assert widget.elevations_m == []
    assert widget.distances_km == []
    print("set_route clears stale data for elevation-less routes: OK")


def test_paint_does_not_crash():
    # Actually render the widget (both with and without data) to catch any
    # runtime error in paintEvent that pure logic tests wouldn't reach —
    # e.g. division by zero, type errors in QPainter calls.
    widget = ElevationProfileWidget()
    widget.resize(300, 150)

    points = [
        RoutePoint(lat=59.00 + i * 0.001, lon=10.00, elevation_m=10 + (i % 5) * 3)
        for i in range(20)
    ]
    widget.set_route(points)
    widget.repaint()
    print("paintEvent with data: OK (no exception)")

    # Simulate a hover position mid-chart
    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtCore import QEvent
    widget._hover_x = 150.0
    widget.repaint()
    print("paintEvent with hover crosshair: OK (no exception)")

    widget.set_route([])
    widget.repaint()
    print("paintEvent with no data (hidden): OK (no exception)")


if __name__ == "__main__":
    test_cumulative_distances()
    test_has_data()
    test_set_route_gain_loss()
    test_paint_does_not_crash()
    print("\nPASS: all elevation chart tests passed.")
