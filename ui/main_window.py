"""
Main application window. Layout:
  left panel  -> prompt input + "Plan Route" button + route summaries list
  right panel -> the Leaflet map showing all providers' routes overlaid

Flow when the user clicks "Plan Route":
  1. prompt_parser.parse_prompt() -> RouteRequest        (Claude API call)
  2. route_engine.plan(request)   -> (all_routes, best, warnings) (provider calls, threaded)
  3. map_view.show_routes(...)    -> renders every route with a distinct color,
                                     best route drawn last/thicker so it's on top
"""
import logging
from copy import deepcopy
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, QThread, QTimer, Qt, pyqtProperty, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetricsF, QIcon, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import diagnose_env_setup, get_app_theme, get_configured_providers, save_env_values


class AnimatedThemeToggle(QPushButton):
    """
    Custom animated theme toggle switch where Sun (☀️) and Moon (🌙) rotate and
    slide up and down like setting/rising celestial bodies on theme switch.
    """
    def __init__(self, current_theme: str = "light", parent=None):
        super().__init__(parent)
        self.setFixedSize(84, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Toggle Dark / Light Theme")
        self.setStyleSheet("border: none; background: transparent; padding: 0px; margin: 0px;")

        self._progress = 0.0 if current_theme == "dark" else 1.0
        self._theme = current_theme

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(600)  # Smooth, unhurried 600ms celestial movement
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

    @pyqtProperty(float)
    def progress(self) -> float:
        return self._progress

    @progress.setter
    def progress(self, val: float):
        self._progress = val
        self.update()

    def set_theme(self, theme: str, animate: bool = True):
        self._theme = theme
        target = 1.0 if theme == "light" else 0.0
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._progress)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._progress = target
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        p = self._progress  # 0.0 = Dark (Moon), 1.0 = Light (Sun)

        # 1. Background Pill Track Path
        track_path = QPainterPath()
        track_path.addRoundedRect(QRectF(1.5, 1.5, w - 3.0, h - 3.0), (h - 3.0) / 2.0, (h - 3.0) / 2.0)

        bg_dark = QColor("#1e293b")
        bg_light = QColor("#cbd5e1")
        bg_r = int(bg_dark.red() + p * (bg_light.red() - bg_dark.red()))
        bg_g = int(bg_dark.green() + p * (bg_light.green() - bg_dark.green()))
        bg_b = int(bg_dark.blue() + p * (bg_light.blue() - bg_dark.blue()))

        bd_dark = QColor("#475569")
        bd_light = QColor("#94a3b8")
        bd_r = int(bd_dark.red() + p * (bd_light.red() - bd_dark.red()))
        bd_g = int(bd_dark.green() + p * (bd_light.green() - bd_dark.green()))
        bd_b = int(bd_dark.blue() + p * (bd_light.blue() - bd_dark.blue()))

        painter.setPen(QPen(QColor(bd_r, bd_g, bd_b), 1.5))
        painter.setBrush(QBrush(QColor(bg_r, bg_g, bg_b)))
        painter.drawPath(track_path)

        # Clip celestial animations cleanly inside the pill track boundary
        painter.setClipPath(track_path)

        # 2. Sliding White/Dark Knob (Pill Circle)
        knob_dia = h - 8.0
        knob_x = 4.0 + p * (w - 8.0 - knob_dia)
        knob_y = 4.0
        knob_color = QColor("#0f172a") if p < 0.5 else QColor("#ffffff")
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(knob_color))
        painter.drawEllipse(QRectF(knob_x, knob_y, knob_dia, knob_dia))

        # 3. Animated Moon 🌙 (Visible at p=0, rotates & sets down at p=1)
        font = QFont("Segoe UI Emoji", 11)
        font.setBold(True)
        painter.setFont(font)

        moon_alpha = max(0, min(255, int((1.0 - p) * 255)))
        if moon_alpha > 0:
            painter.save()
            moon_x = 17.0 + (p * 14.0)
            moon_y = 17.0 + (p * 22.0)
            angle = p * 120.0
            painter.translate(moon_x, moon_y)
            painter.rotate(angle)
            painter.setPen(QColor(248, 250, 252, moon_alpha))
            painter.drawText(QRectF(-12.5, -13.5, 25, 25), Qt.AlignCenter, "🌙")
            painter.restore()

        # 4. Animated Sun ☀️ (Visible at p=1, rises up & rotates in at p=1)
        sun_alpha = max(0, min(255, int(p * 255)))
        if sun_alpha > 0:
            painter.save()
            sun_x = 67.0 - ((1.0 - p) * 14.0)
            sun_y = 17.0 - ((1.0 - p) * 22.0)
            angle = (1.0 - p) * -120.0
            painter.translate(sun_x, sun_y)
            painter.rotate(angle)
            painter.setPen(QColor(234, 88, 12, sun_alpha))
            painter.drawText(QRectF(-12.5, -13.5, 25, 25), Qt.AlignCenter, "☀️")
            painter.restore()
from core.difficulty import compute_difficulty
from core.geo import cumulative_distances_km
from core.gpx_export import route_to_gpx, route_to_tcx
from core.gpx_import import GPXImportError, import_gpx
from core.prompt_parser import PromptParsingError, parse_prompt
from core.providers.base import RouteProviderError
from core.route_engine import RouteEngine
from core.route_storage import load_route
from core.route_storage import save_route as persist_route
from core.surfaces import surface_color
from core.weather import WeatherError, WeatherSummary, get_weather_summary
from models.route_request import Activity, NormalizedRoute, RoutePoint, RouteRequest, SurfaceSegment
from ui.map_view import MapView
from ui.saved_routes_dialog import SavedRoutesDialog
from ui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

PROVIDER_COLORS = {
    "OpenRouteService": "#2563eb",  # blue
    "Mapbox": "#f97316",            # orange
    "OSRM": "#16a34a",              # green
}

DARK_APP_STYLESHEET = """
QMainWindow {
    background: #0f172a;
}
QWidget {
    color: #f8fafc;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}
QLabel#appTitle {
    color: #f8fafc;
    font-size: 24px;
    font-weight: 700;
}
QLabel#appSubtitle {
    color: #94a3b8;
    font-size: 12px;
}
QLabel#sectionLabel {
    color: #cbd5e1;
    font-size: 12px;
    font-weight: 700;
    border-bottom: 1px solid #334155;
    padding-bottom: 4px;
    margin-top: 2px;
}
QWidget#leftPanel {
    background: #1e293b;
}
QTextEdit {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 8px;
    color: #f8fafc;
    padding: 10px;
    selection-background-color: #2563eb;
}
QTextEdit:focus {
    border: 1px solid #3b82f6;
    background: #0f172a;
}
QPushButton {
    background: #334155;
    border: 0;
    border-radius: 8px;
    color: #f8fafc;
    font-weight: 700;
    min-height: 34px;
    padding: 8px 12px;
}
QPushButton:hover {
    background: #475569;
}
QPushButton:pressed {
    background: #64748b;
}
QPushButton:disabled {
    background: #1e293b;
    color: #64748b;
}
QPushButton#primaryButton {
    background: #2563eb;
    color: #ffffff;
}
QPushButton#primaryButton:hover {
    background: #3b82f6;
}
QPushButton#primaryButton:pressed {
    background: #1d4ed8;
}
QPushButton:checkable:checked {
    background: #1e3a8a;
    border: 1px solid #3b82f6;
    color: #93c5fd;
}
QPushButton:checkable:checked:hover {
    background: #1d4ed8;
}
QCheckBox {
    spacing: 8px;
    padding: 4px 2px;
    color: #f8fafc;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #475569;
    border-radius: 4px;
    background: #0f172a;
}
QCheckBox::indicator:hover {
    border: 1px solid #64748b;
}
QCheckBox::indicator:checked {
    background: #2563eb;
    border: 1px solid #2563eb;
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxNiAxNiI+PHBhdGggZD0iTTMgOEw2LjUgMTEuNUwxMyA1IiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIGZpbGw9Im5vbmUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPjwvc3ZnPg==);
}
QCheckBox::indicator:disabled {
    background: #1e293b;
    border: 1px solid #334155;
}
QLabel#statusLabel {
    background: #1e293b;
    border: 1px solid #1e40af;
    border-radius: 8px;
    color: #93c5fd;
    padding: 9px;
}
QLabel#weatherLabel {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    color: #f8fafc;
    padding: 8px 9px;
    font-weight: 600;
}
QLabel#difficultyLabel {
    border-radius: 8px;
    padding: 8px 9px;
    font-weight: 600;
}
QListWidget {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 8px;
    outline: none;
    padding: 4px;
    color: #f8fafc;
}
QListWidget::item {
    border-radius: 6px;
    margin: 2px;
    padding: 8px;
}
QListWidget::item:selected {
    background: #1e3a8a;
    color: #ffffff;
}
QSplitter::handle {
    background: #334155;
}
QScrollArea#leftScrollArea {
    background: #1e293b;
    border-right: 1px solid #334155;
}
QScrollArea#leftScrollArea QScrollBar:vertical {
    background: #1e293b;
    width: 10px;
    margin: 0px;
}
QScrollArea#leftScrollArea QScrollBar::handle:vertical {
    background: #334155;
    border-radius: 5px;
    min-height: 24px;
}
QScrollArea#leftScrollArea QScrollBar::handle:vertical:hover {
    background: #475569;
}
QScrollArea#leftScrollArea QScrollBar::add-line:vertical,
QScrollArea#leftScrollArea QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollArea#leftScrollArea QScrollBar::add-page:vertical,
QScrollArea#leftScrollArea QScrollBar::sub-page:vertical {
    background: #1e293b;
}
QDialog {
    background: #0f172a;
    color: #f8fafc;
}
QLineEdit {
    background: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #f8fafc;
    padding: 6px;
}
QLineEdit:focus {
    border: 1px solid #3b82f6;
    background: #0f172a;
}
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: #334155;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #2563eb;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #f8fafc;
    border: 2px solid #2563eb;
    width: 16px;
    height: 16px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #ffffff;
    border-color: #3b82f6;
}
"""

LIGHT_APP_STYLESHEET = """
QMainWindow {
    background: #f4f6f8;
}
QWidget {
    color: #172033;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}
QLabel#appTitle {
    color: #0f172a;
    font-size: 24px;
    font-weight: 700;
}
QLabel#appSubtitle {
    color: #64748b;
    font-size: 12px;
}
QLabel#sectionLabel {
    color: #334155;
    font-size: 12px;
    font-weight: 700;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 4px;
    margin-top: 2px;
}
QWidget#leftPanel {
    background: #ffffff;
}
QTextEdit {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    color: #0f172a;
    padding: 10px;
    selection-background-color: #2563eb;
}
QTextEdit:focus {
    border: 1px solid #2563eb;
    background: #ffffff;
}
QPushButton {
    background: #e2e8f0;
    border: 0;
    border-radius: 8px;
    color: #0f172a;
    font-weight: 700;
    min-height: 34px;
    padding: 8px 12px;
}
QPushButton:hover {
    background: #cbd5e1;
}
QPushButton:pressed {
    background: #b6c2d1;
}
QPushButton:disabled {
    background: #edf2f7;
    color: #94a3b8;
}
QPushButton#primaryButton {
    background: #2563eb;
    color: #ffffff;
}
QPushButton#primaryButton:hover {
    background: #1d4ed8;
}
QPushButton#primaryButton:pressed {
    background: #1a45b8;
}
QPushButton:checkable:checked {
    background: #dbeafe;
    border: 1px solid #93c5fd;
    color: #1d4ed8;
}
QPushButton:checkable:checked:hover {
    background: #cbe0fd;
}
QCheckBox {
    spacing: 8px;
    padding: 4px 2px;
    color: #172033;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:hover {
    border: 1px solid #94a3b8;
}
QCheckBox::indicator:checked {
    background: #2563eb;
    border: 1px solid #2563eb;
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxNiAxNiI+PHBhdGggZD0iTTMgOEw2LjUgMTEuNUwxMyA1IiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIGZpbGw9Im5vbmUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPjwvc3ZnPg==);
}
QCheckBox::indicator:disabled {
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
}
QLabel#statusLabel {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    color: #1e3a8a;
    padding: 9px;
}
QLabel#weatherLabel {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    color: #0f172a;
    padding: 8px 9px;
    font-weight: 600;
}
QLabel#difficultyLabel {
    border-radius: 8px;
    padding: 8px 9px;
    font-weight: 600;
}
QListWidget {
    background: #f8fafc;
    border: 1px solid #dbe3ec;
    border-radius: 8px;
    outline: none;
    padding: 4px;
    color: #172033;
}
QListWidget::item {
    border-radius: 6px;
    margin: 2px;
    padding: 8px;
}
QListWidget::item:selected {
    background: #dbeafe;
    color: #0f172a;
}
QSplitter::handle {
    background: #d9e0e8;
}
QScrollArea#leftScrollArea {
    background: #ffffff;
    border-right: 1px solid #d9e0e8;
}
QScrollArea#leftScrollArea QScrollBar:vertical {
    background: #ffffff;
    width: 10px;
    margin: 0px;
}
QScrollArea#leftScrollArea QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 5px;
    min-height: 24px;
}
QScrollArea#leftScrollArea QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollArea#leftScrollArea QScrollBar::add-line:vertical,
QScrollArea#leftScrollArea QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollArea#leftScrollArea QScrollBar::add-page:vertical,
QScrollArea#leftScrollArea QScrollBar::sub-page:vertical {
    background: #ffffff;
}
QDialog {
    background: #ffffff;
    color: #172033;
}
QLineEdit {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    color: #0f172a;
    padding: 6px;
}
QLineEdit:focus {
    border: 1px solid #2563eb;
}
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: #cbd5e1;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #2563eb;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid #2563eb;
    width: 16px;
    height: 16px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #f8fafc;
    border-color: #1d4ed8;
}
"""

APP_STYLESHEET = DARK_APP_STYLESHEET


def _draw_card_background(painter: QPainter, rect: QRectF, theme: str = "dark"):
    """Draws the rounded-rect 'card' background shared by the
    elevation and surface composition widgets."""
    if theme == "dark":
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.setBrush(QColor("#1e293b"))
    else:
        painter.setPen(QPen(QColor("#e2e8f0"), 1))
        painter.setBrush(QColor("#f8fafc"))
    painter.drawRoundedRect(rect, 10, 10)


class SurfaceCompositionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.composition: dict[str, float] = {}
        self.theme = "dark"
        self.setMinimumHeight(92)
        self.setVisible(False)

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    def set_composition(self, composition: dict[str, float]):
        self.composition = {
            name: percent
            for name, percent in composition.items()
            if percent >= 0.5
        }
        rows = max(1, (len(self.composition) + 1) // 2)
        self.setMinimumHeight(60 + rows * 22 + 10)
        self.setVisible(bool(self.composition))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.composition:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        _draw_card_background(painter, QRectF(0, 0, self.width(), self.height()), theme=self.theme)

        margin = 12
        bar_height = 16
        bar_y = 18
        bar_width = max(1, self.width() - margin * 2)
        x = margin

        for name, percent in self.composition.items():
            width = bar_width * (percent / 100)
            painter.setBrush(QColor(surface_color(name)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(int(x), bar_y, int(max(width, 2)), bar_height, 5, 5)
            x += width

        text_color = QColor("#e2e8f0") if self.theme == "dark" else QColor("#334155")
        painter.setPen(text_color)
        legend_metrics = painter.fontMetrics()
        y = bar_y + bar_height + 26
        x = margin
        for name, percent in self.composition.items():
            color = QColor(surface_color(name))
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(int(x), y - 9, 10, 10, 3, 3)
            painter.setPen(text_color)
            label = f"{name} {percent:.0f}%"
            painter.drawText(int(x + 16), y, label)
            x += legend_metrics.horizontalAdvance(label) + 28
            if x > self.width() - margin - 60:
                x = margin
                y += 22


class ElevationProfileWidget(QWidget):
    hover_distance_changed = pyqtSignal(object)
    elevation_clicked = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.distances_km: list[float] = []
        self.elevations_m: list[float] = []
        self.waypoints: list[tuple[str, float]] = []
        self.gain_m = 0.0
        self.loss_m = 0.0
        self.theme = "dark"
        self.setMinimumHeight(160)
        self.setVisible(False)
        self.setMouseTracking(True)
        self._hover_x: Optional[float] = None

    def set_theme(self, theme: str):
        self.theme = theme
        self.update()

    @staticmethod
    def has_data(points: list[RoutePoint]) -> bool:
        if not points or len(points) < 2:
            return False
        usable = [p for p in points if p.elevation_m is not None]
        return len(usable) >= 2 and (len(usable) / len(points)) >= 0.5

    def set_route(self, points: list[RoutePoint], waypoints: Optional[list[tuple[str, float]]] = None):
        if not self.has_data(points):
            self.distances_km = []
            self.elevations_m = []
            self.waypoints = []
            self._hover_x = None
            self.setVisible(False)
            self.update()
            return

        self.waypoints = waypoints or []
        self.distances_km = cumulative_distances_km(points)
        raw_elevs = [p.elevation_m for p in points]
        filled_elevs: list[float] = []
        last_val = next((e for e in raw_elevs if e is not None), 0.0)
        for i, e in enumerate(raw_elevs):
            if e is not None:
                last_val = float(e)
                filled_elevs.append(last_val)
            else:
                next_val = next((raw_elevs[j] for j in range(i + 1, len(raw_elevs)) if raw_elevs[j] is not None), last_val)
                filled_elevs.append(float(next_val))

        self.elevations_m = filled_elevs
        self.gain_m = sum(max(0.0, b - a) for a, b in zip(self.elevations_m, self.elevations_m[1:]))
        self.loss_m = sum(max(0.0, a - b) for a, b in zip(self.elevations_m, self.elevations_m[1:]))
        self._hover_x = None
        self.setVisible(True)
        self.update()

    CARD_PADDING = 8  # keeps chart content clear of the card's rounded border

    def _layout_metrics(self, painter: QPainter):
        header_font = QFont(painter.font())
        header_font.setBold(True)
        header_font.setPointSize(9)

        axis_font = QFont(painter.font())
        axis_font.setBold(False)
        axis_font.setPointSize(8)

        return header_font, QFontMetricsF(header_font), axis_font, QFontMetricsF(axis_font)

    def _chart_rect(self, header_height: float, axis_label_height: float, left_axis_width: float) -> QRectF:
        pad = self.CARD_PADDING
        margin_right = 12
        header_gap = 6
        top = pad + header_height + header_gap
        bottom_margin = axis_label_height + 4
        return QRectF(
            pad + left_axis_width + 6,
            top,
            max(1.0, self.width() - pad - left_axis_width - 6 - margin_right - pad),
            max(1.0, self.height() - top - bottom_margin - pad),
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.elevations_m:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        _draw_card_background(painter, QRectF(0, 0, self.width(), self.height()), theme=self.theme)

        pad = self.CARD_PADDING
        min_elev = min(self.elevations_m)
        max_elev = max(self.elevations_m)
        total_km = self.distances_km[-1] if self.distances_km else 0.0
        stats_text = f"↑ {self.gain_m:.0f}m   ↓ {self.loss_m:.0f}m   min {min_elev:.0f}m   max {max_elev:.0f}m"
        max_label = f"{max_elev:.0f}m"
        min_label = f"{min_elev:.0f}m"

        header_font, header_metrics, axis_font, axis_metrics = self._layout_metrics(painter)
        header_height = header_metrics.height() + 4
        axis_label_height = axis_metrics.height() + 4
        left_axis_width = max(
            axis_metrics.horizontalAdvance(max_label), axis_metrics.horizontalAdvance(min_label)
        ) + 4

        rect = self._chart_rect(header_height, axis_label_height, left_axis_width)

        span = max(max_elev - min_elev, 5.0)
        y_pad = span * 0.12
        y_min, y_max = min_elev - y_pad, max_elev + y_pad

        def to_point(dist_km: float, elev_m: float) -> QPointF:
            x = rect.left() + (dist_km / total_km) * rect.width() if total_km > 0 else rect.left()
            y = rect.bottom() - ((elev_m - y_min) / (y_max - y_min)) * rect.height()
            return QPointF(x, y)

        is_dark = self.theme == "dark"
        fill_color = QColor(59, 130, 246, 50) if is_dark else QColor(37, 99, 235, 40)
        stroke_color = QColor("#3b82f6") if is_dark else QColor("#2563eb")
        header_color = QColor("#f8fafc") if is_dark else QColor("#0f172a")
        axis_color = QColor("#94a3b8") if is_dark else QColor("#334155")

        # Filled area under the elevation curve
        path = QPainterPath()
        path.moveTo(QPointF(rect.left(), rect.bottom()))
        for dist_km, elev_m in zip(self.distances_km, self.elevations_m):
            path.lineTo(to_point(dist_km, elev_m))
        path.lineTo(QPointF(rect.right(), rect.bottom()))
        path.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill_color)
        painter.drawPath(path)

        # The elevation line itself, drawn on top of the fill
        painter.setPen(QPen(stroke_color, 2))
        prev_point = None
        for dist_km, elev_m in zip(self.distances_km, self.elevations_m):
            point = to_point(dist_km, elev_m)
            if prev_point is not None:
                painter.drawLine(prev_point, point)
            prev_point = point

        # Header (top stats line)
        painter.setFont(header_font)
        painter.setPen(header_color)
        header_rect = QRectF(pad, pad, max(1.0, self.width() - 2 * pad), header_height)
        painter.drawText(header_rect, Qt.AlignLeft | Qt.AlignVCenter, stats_text)

        # Y-axis labels
        painter.setFont(axis_font)
        painter.setPen(axis_color)
        max_label_rect = QRectF(pad, rect.top() - axis_label_height / 2, left_axis_width, axis_label_height)
        min_label_rect = QRectF(pad, rect.bottom() - axis_label_height / 2, left_axis_width, axis_label_height)
        painter.drawText(max_label_rect, Qt.AlignRight | Qt.AlignVCenter, max_label)
        painter.drawText(min_label_rect, Qt.AlignRight | Qt.AlignVCenter, min_label)
        max_label_rect = QRectF(pad, rect.top() - axis_label_height / 2, left_axis_width, axis_label_height)
        min_label_rect = QRectF(pad, rect.bottom() - axis_label_height / 2, left_axis_width, axis_label_height)
        painter.drawText(max_label_rect, Qt.AlignRight | Qt.AlignVCenter, max_label)
        painter.drawText(min_label_rect, Qt.AlignRight | Qt.AlignVCenter, min_label)

        # Intermediate X-axis kilometer ticks
        if total_km > 0:
            step_km = 10.0 if total_km > 30 else (5.0 if total_km > 10 else 2.0)
            curr_tick = step_km
            while curr_tick < total_km - 0.5:
                tick_x = rect.left() + (curr_tick / total_km) * rect.width()
                tick_rect = QRectF(tick_x - 30, rect.bottom() + 2, 60, axis_label_height)
                painter.drawText(tick_rect, Qt.AlignCenter, f"{curr_tick:.0f}km")
                curr_tick += step_km

        bottom_left_rect = QRectF(rect.left(), rect.bottom() + 2, 60, axis_label_height)
        bottom_right_rect = QRectF(rect.right() - 60, rect.bottom() + 2, 60, axis_label_height)
        painter.drawText(bottom_left_rect, Qt.AlignLeft | Qt.AlignVCenter, "0km")
        painter.drawText(bottom_right_rect, Qt.AlignRight | Qt.AlignVCenter, f"{total_km:.1f}km")

        # Numbered Waypoint Badges (Komoot-style red pin icons on the elevation profile)
        if self.waypoints and total_km > 0:
            badge_font = QFont(painter.font())
            badge_font.setBold(True)
            badge_font.setPointSize(8)
            painter.setFont(badge_font)

            for label, dist_km in self.waypoints:
                idx = min(range(len(self.distances_km)), key=lambda i: abs(self.distances_km[i] - dist_km))
                pt = to_point(self.distances_km[idx], self.elevations_m[idx])

                # Position badge slightly above elevation curve
                badge_center = QPointF(pt.x(), max(rect.top() + 10, pt.y() - 14))

                # Stem line down to curve
                painter.setPen(QPen(QColor("#ef4444"), 1, Qt.SolidLine))
                painter.drawLine(badge_center, pt)

                # Red circular badge
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#ef4444"))
                painter.drawEllipse(badge_center, 9, 9)

                # Label text (S, 1, 2, 3, F)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(QRectF(badge_center.x() - 9, badge_center.y() - 9, 18, 18), Qt.AlignCenter, label)

        # Hover crosshair + distance/elevation readout
        if self._hover_x is not None and total_km > 0 and rect.width() > 0:
            hover_dist_km = max(0.0, min(total_km, (self._hover_x - rect.left()) / rect.width() * total_km))
            idx = min(range(len(self.distances_km)), key=lambda i: abs(self.distances_km[i] - hover_dist_km))
            hover_point = to_point(self.distances_km[idx], self.elevations_m[idx])

            painter.setPen(QPen(QColor("#94a3b8"), 1, Qt.DashLine))
            painter.drawLine(QPointF(hover_point.x(), rect.top()), QPointF(hover_point.x(), rect.bottom()))

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#2563eb"))
            painter.drawEllipse(hover_point, 4, 4)

            label = f"{self.distances_km[idx]:.1f}km · {self.elevations_m[idx]:.0f}m"
            label_metrics = QFontMetricsF(axis_font)
            label_width = label_metrics.horizontalAdvance(label) + 10
            label_height = label_metrics.height() + 6
            box_x = min(max(hover_point.x() - label_width / 2, rect.left()), rect.right() - label_width)
            box_y = max(rect.top() - label_height - 4, pad)  # keep the tooltip on-screen near the very top
            box_rect = QRectF(box_x, box_y, label_width, label_height)

            painter.setFont(axis_font)
            painter.setBrush(QColor(15, 23, 42, 220))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(box_rect, 4, 4)
            painter.setPen(QColor("white"))
            painter.drawText(box_rect, Qt.AlignCenter, label)

    def mouseMoveEvent(self, event):
        if not self.elevations_m:
            self.hover_distance_changed.emit(None)
            return
        self._hover_x = event.pos().x()
        self.update()

        total_km = self.distances_km[-1] if self.distances_km else 0.0
        if total_km > 0 and self.width() > 0:
            left_axis_width = 40.0
            rect_left = self.CARD_PADDING + left_axis_width + 6
            rect_width = max(1.0, self.width() - rect_left - 20)
            hover_dist_km = max(0.0, min(total_km, (self._hover_x - rect_left) / rect_width * total_km))
            self.hover_distance_changed.emit(hover_dist_km)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.elevations_m and self.distances_km:
            total_km = self.distances_km[-1] if self.distances_km else 0.0
            if total_km > 0 and self.width() > 0:
                left_axis_width = 40.0
                rect_left = self.CARD_PADDING + left_axis_width + 6
                rect_width = max(1.0, self.width() - rect_left - 20)
                click_dist_km = max(0.0, min(total_km, (event.pos().x() - rect_left) / rect_width * total_km))
                self.elevation_clicked.emit(click_dist_km)

    def leaveEvent(self, event):
        self._hover_x = None
        self.hover_distance_changed.emit(None)
        self.update()


class SpinnerWidget(QWidget):
    """
    Small rotating-arc loading spinner shown while a plan/edit request is
    in flight. Self-contained: start()/stop() control an internal QTimer
    that advances rotation and triggers repaints — no external animation
    wiring needed beyond calling those two methods.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self.setVisible(False)

    def start(self):
        self._angle = 0
        self.setVisible(True)
        self._timer.start(16)  # ~60fps

    def stop(self):
        self._timer.stop()
        self.setVisible(False)

    def _advance(self):
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#2563eb"))
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        rect = self.rect().adjusted(2, 2, -2, -2)
        span_angle = 270 * 16  # Qt angles are in 1/16th-degree units
        start_angle = -self._angle * 16
        painter.drawArc(rect, start_angle, span_angle)


class PlanningWorker(QThread):
    """Runs the parse + provider calls off the GUI thread so the UI stays responsive."""

    succeeded = pyqtSignal(list, object, object, list)  # all_routes, best_route, request, warnings
    failed = pyqtSignal(str)

    def __init__(self, engine: RouteEngine, prompt: str, fallback_min_km: float, fallback_max_km: float):
        super().__init__()
        self.engine = engine
        self.prompt = prompt
        self.fallback_min_km = fallback_min_km
        self.fallback_max_km = fallback_max_km

    def run(self):
        try:
            request: RouteRequest = parse_prompt(self.prompt)
        except PromptParsingError as e:
            self.failed.emit(f"Couldn't understand that request: {e}")
            return

        if request.is_loop and not request.target_distance_km:
            request.min_distance_km = self.fallback_min_km
            request.max_distance_km = self.fallback_max_km

        try:
            all_routes, best, warnings = self.engine.plan(request)
        except RouteProviderError as e:
            self.failed.emit(f"Routing failed: {e}")
            return

        self.succeeded.emit(all_routes, best, request, warnings)


class RouteEditWorker(QThread):
    succeeded = pyqtSignal(list, object, object, list)
    failed = pyqtSignal(str)

    def __init__(self, engine: RouteEngine, request: RouteRequest, via_points: list[tuple[float, float]]):
        super().__init__()
        self.engine = engine
        self.request = deepcopy(request)
        self.via_points = via_points

    def run(self):
        self.request.via_points = self.via_points
        try:
            all_routes, best, warnings = self.engine.plan(self.request)
        except RouteProviderError as e:
            self.failed.emit(f"Route edit failed: {e}")
            return
        self.succeeded.emit(all_routes, best, self.request, warnings)


class WeatherWorker(QThread):
    """
    Fetches a quick weather summary for the route's start location.
    Weather is a nice-to-have, not a core function — failures are caught
    by the caller and handled by simply not showing anything, never an
    error popup.
    """

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, lat: float, lon: float):
        super().__init__()
        self.lat = lat
        self.lon = lon

    def run(self):
        try:
            summary = get_weather_summary(self.lat, self.lon)
        except WeatherError as e:
            self.failed.emit(str(e))
            return
        self.succeeded.emit(summary)


class MainWindow(QMainWindow):
    def __init__(self, engine: RouteEngine, startup_notice: Optional[str] = None):
        super().__init__()
        self.engine = engine
        self.worker: PlanningWorker | None = None
        self.edit_worker: RouteEditWorker | None = None
        self.best_route: NormalizedRoute | None = None
        self.current_request: RouteRequest | None = None
        self.current_routes: list[NormalizedRoute] = []
        self.undo_stack: list[tuple[list[NormalizedRoute], NormalizedRoute, RouteRequest]] = []
        self._last_weather_coords: Optional[tuple[float, float]] = None
        self.weather_worker: Optional[WeatherWorker] = None
        self.current_theme = get_app_theme()
        self._build_ui()
        self.set_app_theme(self.current_theme)

        if startup_notice:
            self.status_label.setText(startup_notice)
            self.status_label.setVisible(True)

    def _build_ui(self):
        self.setWindowTitle("GoPoint — AI Route Planner")
        self.setWindowIcon(QIcon("gopoint_icon.png"))
        self.resize(1200, 800)
        self.setStyleSheet(DARK_APP_STYLESHEET if self.current_theme == "dark" else LIGHT_APP_STYLESHEET)

        title_label = QLabel("GoPoint")
        title_label.setObjectName("appTitle")

        self.theme_button = AnimatedThemeToggle(current_theme=self.current_theme)
        self.theme_button.clicked.connect(self._on_theme_toggle_clicked)

        self.settings_button = QPushButton("Settings")
        self.settings_button.setFixedWidth(75)
        self.settings_button.clicked.connect(self._on_settings_clicked)

        subtitle_label = QLabel("Plan ride, run, walk, and hike routes from natural language.")
        subtitle_label.setObjectName("appSubtitle")

        prompt_label = QLabel("Describe your route")
        prompt_label.setObjectName("sectionLabel")

        self.prompt_box = QTextEdit()
        self.prompt_box.setPlaceholderText(
            'e.g. "30km hilly road bike loop from Frogner park, avoid busy streets"'
        )
        self.prompt_box.setFixedHeight(96)

        distance_label = QLabel("Fallback distance range")
        distance_label.setObjectName("sectionLabel")
        self.distance_range_label = QLabel("")
        self.distance_range_label.setObjectName("appSubtitle")

        self.min_distance_slider = QSlider(Qt.Horizontal)
        self.min_distance_slider.setRange(2, 200)
        self.min_distance_slider.setValue(10)
        self.min_distance_slider.valueChanged.connect(self._on_distance_range_changed)

        self.max_distance_slider = QSlider(Qt.Horizontal)
        self.max_distance_slider.setRange(2, 200)
        self.max_distance_slider.setValue(30)
        self.max_distance_slider.valueChanged.connect(self._on_distance_range_changed)

        self.plan_button = QPushButton("Plan Route")
        self.plan_button.setObjectName("primaryButton")
        self.plan_button.clicked.connect(self._on_plan_clicked)

        self.export_button = QPushButton("Export Route")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._on_export_clicked)

        self.save_button = QPushButton("Save Route")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save_clicked)

        self.my_routes_button = QPushButton("My Routes")
        self.my_routes_button.clicked.connect(self._on_my_routes_clicked)

        self.import_gpx_button = QPushButton("Import GPX")
        self.import_gpx_button.clicked.connect(self._on_import_gpx_clicked)

        self.create_button = QPushButton("Create Route")
        self.create_button.clicked.connect(self._on_create_clicked)

        self.edit_button = QPushButton("Edit Route")
        self.edit_button.setCheckable(True)
        self.edit_button.setEnabled(False)
        self.edit_button.toggled.connect(self._on_edit_toggled)

        self.undo_button = QPushButton("Undo Edit")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._on_undo_clicked)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)

        self.loading_spinner = SpinnerWidget()

        status_row = QWidget()
        status_row_layout = QHBoxLayout(status_row)
        status_row_layout.setContentsMargins(0, 0, 0, 0)
        status_row_layout.setSpacing(8)
        status_row_layout.addWidget(self.loading_spinner)
        status_row_layout.addWidget(self.status_label, 1)

        self.weather_label = QLabel("")
        self.weather_label.setObjectName("weatherLabel")
        self.weather_label.setVisible(False)
        self.weather_label.setWordWrap(True)

        self.difficulty_label = QLabel("")
        self.difficulty_label.setObjectName("difficultyLabel")
        self.difficulty_label.setVisible(False)
        self.difficulty_label.setWordWrap(True)

        self.elevation_label = QLabel("Elevation profile")
        self.elevation_label.setObjectName("sectionLabel")
        self.elevation_label.setVisible(False)
        self.elevation_chart = ElevationProfileWidget()

        self.surface_label = QLabel("WAYTYPES / Surface composition")
        self.surface_label.setObjectName("sectionLabel")
        self.surface_label.setVisible(False)
        self.surface_chart = SurfaceCompositionWidget()

        self.results_list = QListWidget()
        self.results_list.currentRowChanged.connect(self._on_route_selection_changed)

        self.remove_route_button = QPushButton("Remove Route")
        self.remove_route_button.setEnabled(False)
        self.remove_route_button.clicked.connect(self._on_remove_route_clicked)

        left_panel = QWidget()
        left_panel.setObjectName("leftPanel")
        header_row = QWidget()
        header_row_layout = QHBoxLayout(header_row)
        header_row_layout.setContentsMargins(0, 2, 0, 2)
        header_row_layout.setAlignment(Qt.AlignVCenter)
        header_row_layout.addWidget(title_label)
        header_row_layout.addStretch()
        header_row_layout.addWidget(self.theme_button)
        header_row_layout.addWidget(self.settings_button)

        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)
        left_layout.addWidget(header_row)
        left_layout.addWidget(subtitle_label)
        left_layout.addSpacing(8)
        left_layout.addWidget(prompt_label)
        left_layout.addWidget(self.prompt_box)
        left_layout.addWidget(distance_label)
        left_layout.addWidget(self.distance_range_label)
        left_layout.addWidget(self.min_distance_slider)
        left_layout.addWidget(self.max_distance_slider)
        left_layout.addWidget(self.plan_button)
        left_layout.addWidget(self.export_button)
        left_layout.addWidget(self.save_button)
        left_layout.addWidget(self.my_routes_button)
        left_layout.addWidget(self.import_gpx_button)
        left_layout.addWidget(self.create_button)
        left_layout.addWidget(self.edit_button)
        left_layout.addWidget(self.undo_button)
        left_layout.addWidget(status_row)
        left_layout.addWidget(self.weather_label)
        left_layout.addWidget(self.difficulty_label)
        left_layout.addWidget(self.surface_label)
        left_layout.addWidget(self.surface_chart)
        results_label = QLabel("Routes found")
        results_label.setObjectName("sectionLabel")
        left_layout.addWidget(results_label)
        left_layout.addWidget(self.results_list)
        left_layout.addWidget(self.remove_route_button)
        left_layout.addStretch()

        left_scroll_area = QScrollArea()
        left_scroll_area.setObjectName("leftScrollArea")
        left_scroll_area.setWidget(left_panel)
        left_scroll_area.setWidgetResizable(True)
        left_scroll_area.setFrameShape(QFrame.NoFrame)
        left_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.map_view = MapView()
        self.map_view.waypoint_added.connect(self._on_waypoint_added)
        self.map_view.waypoint_moved.connect(self._on_waypoint_moved)
        self.map_view.waypoint_removed.connect(self._on_waypoint_removed)
        self.map_view.manual_start_selected.connect(self._on_manual_start_selected)
        self.map_view.manual_finish_selected.connect(self._on_manual_finish_selected)
        self.map_view.fuse_start_finish_requested.connect(self._on_fuse_start_finish)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.map_view, 1)

        self.elevation_container = QWidget()
        self.elevation_container.setContentsMargins(8, 4, 8, 8)
        self.elevation_container.setVisible(False)
        elev_container_layout = QVBoxLayout(self.elevation_container)
        elev_container_layout.setContentsMargins(0, 0, 0, 0)
        elev_container_layout.setSpacing(0)
        elev_container_layout.addWidget(self.elevation_chart)

        right_layout.addWidget(self.elevation_container, 0)

        splitter = QSplitter()
        splitter.addWidget(left_scroll_area)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self.setCentralWidget(splitter)
        self.elevation_chart.hover_distance_changed.connect(self._on_elevation_hover)
        self.elevation_chart.elevation_clicked.connect(self._on_elevation_clicked)
        self.map_view.playback_progress.connect(self._on_playback_progress)
        self._on_distance_range_changed()

    def _on_distance_range_changed(self):
        min_km = self.min_distance_slider.value()
        max_km = self.max_distance_slider.value()

        sender = self.sender()
        if min_km > max_km:
            if sender is self.min_distance_slider:
                self.max_distance_slider.setValue(min_km)
                max_km = min_km
            else:
                self.min_distance_slider.setValue(max_km)
                min_km = max_km

        self.distance_range_label.setText(
            f"Used only when the prompt has no distance: {min_km}-{max_km} km"
        )

    def _on_plan_clicked(self):
        prompt = self.prompt_box.toPlainText().strip()
        if not prompt:
            return

        self.map_view.set_create_mode(False)
        self.plan_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.edit_button.setEnabled(False)
        self.edit_button.setChecked(False)
        self.undo_button.setEnabled(False)
        self.best_route = None
        self.current_request = None
        self.current_routes = []
        self.undo_stack.clear()
        self.surface_label.setVisible(False)
        self.surface_chart.set_composition({})
        self.elevation_container.setVisible(False)
        self.elevation_chart.set_route([])
        self.weather_label.setVisible(False)
        self.difficulty_label.setVisible(False)
        self.status_label.setText("Thinking, then checking providers...")
        self.status_label.setVisible(True)
        self.loading_spinner.start()
        self.results_list.clear()

        self.worker = PlanningWorker(
            self.engine,
            prompt,
            self.min_distance_slider.value(),
            self.max_distance_slider.value(),
        )
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.finished.connect(lambda: self.plan_button.setEnabled(True))
        self.worker.start()

    def _on_success(
        self,
        all_routes: list[NormalizedRoute],
        best: NormalizedRoute,
        request: RouteRequest,
        warnings: list[str],
    ):
        self._apply_route_state(all_routes, best, request, warnings)

    def _fade_in(self, widget: QWidget, duration: int = 220):
        """
        Quick opacity fade (0 -> 1) used whenever a status message updates
        or a section (elevation/surface) newly appears. Automatically clears
        the graphics effect when finished so Qt scroll area repaints don't
        suffer from detached opacity clipping artifact bugs.
        """
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(duration)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.finished.connect(lambda: widget.setGraphicsEffect(None))
        animation.start(QPropertyAnimation.DeleteWhenStopped)

    def _maybe_fetch_weather(self, best: NormalizedRoute):
        """
        Weather only depends on the route's start point, which doesn't
        change across edits/undo within the same session — so this skips
        the network call entirely if we already fetched for essentially
        the same coordinates, rather than re-fetching on every waypoint
        drag.
        """
        if not best.points:
            return
        lat, lon = best.points[0].lat, best.points[0].lon
        coords_key = (round(lat, 3), round(lon, 3))
        if coords_key == self._last_weather_coords:
            return
        self._last_weather_coords = coords_key
        self._fetch_weather(lat, lon)

    def _fetch_weather(self, lat: float, lon: float):
        self.weather_worker = WeatherWorker(lat, lon)
        self.weather_worker.succeeded.connect(self._on_weather_success)
        self.weather_worker.failed.connect(self._on_weather_failure)
        self.weather_worker.start()

    def _on_weather_success(self, summary: WeatherSummary):
        self.weather_label.setText(summary.display_text())
        self.weather_label.setVisible(True)
        self._fade_in(self.weather_label)

    def _on_weather_failure(self, message: str):
        # Weather is a nice-to-have, not a core function — fail silently
        # rather than interrupting the person with a popup over something
        # this minor. Just leave the label hidden.
        logger.info("Weather fetch failed (non-critical): %s", message)
        self.weather_label.setVisible(False)

    _DIFFICULTY_COLORS_DARK = {
        "Easy": ("#064e3b", "#059669", "#a7f3d0"),
        "Moderate": ("#1e3a8a", "#2563eb", "#bfdbfe"),
        "Hard": ("#7c2d12", "#ea580c", "#ffedd5"),
        "Very Hard": ("#7f1d1d", "#dc2626", "#fecaca"),
    }
    _DIFFICULTY_COLORS_LIGHT = {
        "Easy": ("#f0fdf4", "#86efac", "#166534"),
        "Moderate": ("#eff6ff", "#93c5fd", "#1e3a8a"),
        "Hard": ("#fff7ed", "#fdba74", "#9a3412"),
        "Very Hard": ("#fef2f2", "#fca5a5", "#991b1b"),
    }

    def set_app_theme(self, theme: str):
        theme = theme if theme in ("dark", "light") else "dark"
        self.current_theme = theme
        save_env_values({"APP_THEME": theme})

        stylesheet = DARK_APP_STYLESHEET if theme == "dark" else LIGHT_APP_STYLESHEET
        self.setStyleSheet(stylesheet)

        if hasattr(self, "theme_button") and isinstance(self.theme_button, AnimatedThemeToggle):
            self.theme_button.set_theme(theme, animate=True)

        self.surface_chart.set_theme(theme)
        self.elevation_chart.set_theme(theme)

        if self.current_request and self.best_route:
            self._update_difficulty_badge(self.current_request, self.best_route)

        self.map_view.set_theme(theme)

    def _on_theme_toggle_clicked(self):
        new_theme = "light" if self.current_theme == "dark" else "dark"
        self.set_app_theme(new_theme)

    def _update_difficulty_badge(self, request: RouteRequest, best: NormalizedRoute):
        rating = compute_difficulty(request.activity, best)
        colors_dict = self._DIFFICULTY_COLORS_DARK if self.current_theme == "dark" else self._DIFFICULTY_COLORS_LIGHT
        fallback = ("#1e293b", "#334155", "#f8fafc") if self.current_theme == "dark" else ("#f8fafc", "#e2e8f0", "#0f172a")
        background, border, text_color = colors_dict.get(rating.label, fallback)
        self.difficulty_label.setStyleSheet(
            f"QLabel#difficultyLabel {{"
            f"background: {background}; border: 1px solid {border}; color: {text_color};"
            f"border-radius: 8px; padding: 8px 9px; font-weight: 600;"
            f"}}"
        )
        self.difficulty_label.setText(f"Difficulty: {rating.label} — {rating.explanation}")
        if not self.difficulty_label.isVisible():
            self._fade_in(self.difficulty_label)
        self.difficulty_label.setVisible(True)

    def _apply_route_state(
        self,
        all_routes: list[NormalizedRoute],
        best: NormalizedRoute,
        request: RouteRequest,
        warnings: Optional[list[str]] = None,
        fit_bounds: bool = True,
    ):
        self.current_routes = all_routes
        self.best_route = best
        self.current_request = request
        self.loading_spinner.stop()
        self.export_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.edit_button.setEnabled(True)
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.map_view.set_edit_mode(self.edit_button.isChecked())
        self._maybe_fetch_weather(best)
        self._update_difficulty_badge(request, best)

        show_surface = bool(best.surface_composition)
        self.surface_chart.set_composition(best.surface_composition)
        if show_surface and not self.surface_label.isVisible():
            self._fade_in(self.surface_label)
            self._fade_in(self.surface_chart)
        self.surface_label.setVisible(show_surface)

        show_elevation = ElevationProfileWidget.has_data(best.points)
        cum_dists = cumulative_distances_km(best.points)
        waypoint_list = []
        if request and best.points and cum_dists:
            waypoint_list.append(("S", 0.0))
            if request.via_points:
                for idx, (vlat, vlon) in enumerate(request.via_points, 1):
                    closest_idx = min(
                        range(len(best.points)),
                        key=lambda i: (best.points[i].lat - vlat)**2 + (best.points[i].lon - vlon)**2
                    )
                    dist_km = cum_dists[closest_idx] if closest_idx < len(cum_dists) else 0.0
                    waypoint_list.append((str(idx), dist_km))
            if not request.is_loop and len(cum_dists) > 0:
                waypoint_list.append(("F", cum_dists[-1]))

        self.elevation_chart.set_route(best.points, waypoints=waypoint_list)
        self.elevation_container.setVisible(show_elevation)

        if warnings:
            self.status_label.setText("⚠ " + " ".join(warnings))
            self._fade_in(self.status_label)
            self.status_label.setVisible(True)
        else:
            self.status_label.setText("")
            self.status_label.setVisible(False)

        self.results_list.blockSignals(True)
        self.results_list.clear()
        for i, route in enumerate(all_routes):
            marker = " ★ BEST" if route is best else ""
            self.results_list.addItem(route.summary() + marker)
            if route == best:
                self.results_list.setCurrentRow(i)
        self.results_list.blockSignals(False)

        self.remove_route_button.setEnabled(bool(all_routes))

        routes_with_style = []
        # When editing or when waypoints exist, show ONLY the single primary route being edited
        routes_to_display = [best] if (self.edit_button.isChecked() or (request and request.via_points)) else all_routes
        for route in routes_to_display:
            if not route.geometry_geojson:
                continue
            is_best = self._is_best_route(route, best)
            routes_with_style.append({
                "geojson": route.geometry_geojson,
                "color": "#2563eb" if (is_best or self.edit_button.isChecked()) else PROVIDER_COLORS.get(route.provider, "#6b7280"),
                "label": route.summary(),
                "opacity": 0.95 if is_best else 0.5,
                "showDistanceMarkers": is_best or len(routes_to_display) == 1,
                "surfaceSegments": [
                    {
                        "start": segment.start_index,
                        "end": segment.end_index,
                        "category": segment.category,
                    }
                    for segment in route.surface_segments
                ] if is_best else [],
                "viaPoints": [
                    {"lat": lat, "lon": lon}
                    for lat, lon in request.via_points
                ] if is_best else [],
            })
        should_animate = not self.edit_button.isChecked() and not (request and request.via_points)
        should_fit = fit_bounds and not self.edit_button.isChecked()
        self.map_view.show_routes(routes_with_style, animate=should_animate, fit_bounds=should_fit)

    def _is_best_route(self, route: NormalizedRoute, best: NormalizedRoute) -> bool:
        if route is best:
            return True
        return (
            route.provider == best.provider
            and abs(route.distance_km - best.distance_km) < 0.001
            and route.geometry_geojson == best.geometry_geojson
        )

    def _on_failure(self, message: str):
        self.loading_spinner.stop()
        self.status_label.setText("")
        self.status_label.setVisible(False)
        self.export_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.edit_button.setEnabled(False)
        self.edit_button.setChecked(False)
        self.undo_button.setEnabled(False)
        self.best_route = None
        self.current_request = None
        self.current_routes = []
        self.undo_stack.clear()
        self.surface_label.setVisible(False)
        self.surface_chart.set_composition({})
        self.elevation_container.setVisible(False)
        self.elevation_chart.set_route([])
        self.weather_label.setVisible(False)
        self.difficulty_label.setVisible(False)
        QMessageBox.warning(self, "Route planning failed", message)

    def _on_route_selection_changed(self, row: int):
        if row < 0 or row >= len(self.current_routes):
            return
        selected_route = self.current_routes[row]
        if selected_route != self.best_route:
            self.best_route = selected_route
            self._apply_route_state(self.current_routes, self.best_route, self.current_request, fit_bounds=True)

    def _on_remove_route_clicked(self):
        current_row = self.results_list.currentRow()
        if current_row < 0 or current_row >= len(self.current_routes):
            return

        removed_route = self.current_routes.pop(current_row)

        if not self.current_routes:
            self.best_route = None
            self.current_routes = []
            self.undo_stack.clear()
            self.surface_label.setVisible(False)
            self.surface_chart.set_composition({})
            self.elevation_container.setVisible(False)
            self.elevation_chart.set_route([])
            self.weather_label.setVisible(False)
            self.difficulty_label.setVisible(False)
            self.export_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.edit_button.setEnabled(False)
            self.edit_button.setChecked(False)
            self.undo_button.setEnabled(False)
            self.remove_route_button.setEnabled(False)
            self.map_view.show_routes([], animate=False, fit_bounds=False)
            self.map_view.set_start_point(None, None)
            self.results_list.clear()
            self.status_label.setText("All routes removed.")
            self.status_label.setVisible(True)
        else:
            if removed_route == self.best_route:
                self.best_route = self.current_routes[0]
            self._apply_route_state(self.current_routes, self.best_route, self.current_request)

    def _on_create_clicked(self):
        self.best_route = None
        self.current_routes = []
        self.undo_stack.clear()
        self.surface_label.setVisible(False)
        self.surface_chart.set_composition({})
        self.elevation_container.setVisible(False)
        self.elevation_chart.set_route([])
        self.weather_label.setVisible(False)
        self.difficulty_label.setVisible(False)
        self.map_view.show_routes([], animate=False, fit_bounds=False)
        self.map_view.set_start_point(None, None)
        self.map_view.set_finish_point(None, None)

        self.current_request = RouteRequest(
            activity=Activity.CYCLING_REGULAR,
            start_location="Manual Start",
            is_loop=False,
            via_points=[],
            auto_close_loop=False,
            raw_prompt="Manual route creation",
        )
        self.edit_button.setEnabled(True)
        self.edit_button.setChecked(True)
        self.map_view.set_edit_mode(True)
        self.map_view.set_create_mode(True)
        self.export_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.undo_button.setEnabled(False)
        self.status_label.setText("Click anywhere on the map to set your starting point.")
        self.status_label.setVisible(True)

    def _on_manual_start_selected(self, lat: float, lon: float):
        """Accept the first map click for a manually-created route."""
        if not self.current_request or self.current_request.start_location != "Manual Start":
            return
        self.current_request.start_location = f"{lat:.6f},{lon:.6f}"
        self.map_view.set_start_point(lat, lon)
        self.map_view.set_create_mode(False)
        self.status_label.setText(
            f"Start set at ({lat:.4f}, {lon:.4f}). Click map to chart your route or drag to Start to fuse (S/F)."
        )
        self.status_label.setVisible(True)

    def _on_manual_finish_selected(self, lat: float, lon: float):
        """Accept setting a finish location (via right-click context menu, finish handle drag, or cut route)."""
        if not self.current_request:
            return

        import copy
        self.undo_stack.append((list(self.current_routes), self.best_route, copy.deepcopy(self.current_request)))
        self.undo_button.setEnabled(True)

        self.current_request.end_location = f"{lat:.6f},{lon:.6f}"
        self.current_request.is_loop = False
        self.current_request.auto_close_loop = False

        if self.best_route and self.best_route.points:
            from core.geo import haversine_distance_m
            pts = self.best_route.points
            # Find the index of the point on the route closest to the cut click
            click_idx = min(range(len(pts)), key=lambda i: haversine_distance_m(pts[i].lat, pts[i].lon, lat, lon))
            click_idx = max(1, click_idx)

            cut_pts = pts[:click_idx + 1]

            # Calculate total distance along cut points
            cut_dist_m = sum(
                haversine_distance_m(cut_pts[i-1].lat, cut_pts[i-1].lon, cut_pts[i].lat, cut_pts[i].lon)
                for i in range(1, len(cut_pts))
            )

            # Calculate elevation gain along cut points
            cut_ele_gain = sum(
                max(0, cut_pts[i].elevation_m - cut_pts[i-1].elevation_m)
                for i in range(1, len(cut_pts))
                if cut_pts[i].elevation_m is not None and cut_pts[i-1].elevation_m is not None
            )

            # Trim surface segments to fit within the cut point index
            cut_surfaces = []
            for seg in getattr(self.best_route, "surface_segments", []):
                if seg.start_index < click_idx:
                    cut_surfaces.append(SurfaceSegment(
                        start_index=seg.start_index,
                        end_index=min(seg.end_index, click_idx),
                        category=seg.category
                    ))

            # Build GeoJSON geometry so Leaflet can render the cut route
            cut_geojson = {
                "type": "LineString",
                "coordinates": [[pt.lon, pt.lat] for pt in cut_pts]
            }

            orig_dist = max(0.001, self.best_route.distance_km)
            ratio = (cut_dist_m / 1000.0) / orig_dist

            cut_route = NormalizedRoute(
                provider=self.best_route.provider,
                distance_km=cut_dist_m / 1000.0,
                duration_min=self.best_route.duration_min * ratio,
                elevation_gain_m=cut_ele_gain,
                points=cut_pts,
                surface_segments=cut_surfaces,
                geometry_geojson=cut_geojson,
                surface_composition=getattr(self.best_route, "surface_composition", {}),
            )

            # Extract via_points that sit before the cut location
            new_via = []
            for vlat, vlon in self.current_request.via_points:
                v_idx = min(range(len(pts)), key=lambda i: haversine_distance_m(pts[i].lat, pts[i].lon, vlat, vlon))
                if v_idx < click_idx:
                    new_via.append((vlat, vlon))
            self.current_request.via_points = new_via

            # Update application state with cut route
            self.best_route = cut_route
            self.current_routes = [cut_route]
            self._apply_route_state([cut_route], cut_route, self.current_request, fit_bounds=False)
            self.status_label.setText(f"Route cut to new finish. New length: {cut_route.distance_km:.1f} km.")
            self.status_label.setVisible(True)
            return

        if self.current_request.start_location and self.current_request.start_location != "Manual Start":
            self._start_route_edit(self.current_request.via_points, "Cutting route to new finish point...")

        self.status_label.setText(f"Route cut to new finish at ({lat:.4f}, {lon:.4f}).")
        self.status_label.setVisible(True)

    def _on_fuse_start_finish(self):
        """Fuse the start and finish into a loop (S/F)."""
        if not self.current_request:
            return

        self.current_request.is_loop = True
        self.current_request.auto_close_loop = True
        self.current_request.end_location = None
        self.map_view.set_finish_point(None, None)

        if self.current_request.start_location and self.current_request.start_location != "Manual Start":
            parts = self.current_request.start_location.split(",")
            try:
                slat, slon = float(parts[0]), float(parts[1])
                self.map_view.set_start_point(slat, slon, "S/F")
            except Exception:
                pass
            self._start_route_edit(self.current_request.via_points, "Fusing start and finish into a loop (S/F)...")

        self.status_label.setText("Start and Finish fused into a loop (S/F).")
        self.status_label.setVisible(True)

    def _on_elevation_hover(self, dist_km: Optional[float]):
        if dist_km is None or not self.best_route or not self.best_route.points:
            self.map_view.set_hover_point(None, None)
            return

        cum_dists = cumulative_distances_km(self.best_route.points)
        if not cum_dists:
            self.map_view.set_hover_point(None, None)
            return

        idx = min(range(len(cum_dists)), key=lambda i: abs(cum_dists[i] - dist_km))
        pt = self.best_route.points[idx]
        self.map_view.set_hover_point(pt.lat, pt.lon)

    def _on_playback_progress(self, dist_km: float):
        if self.elevation_chart.isVisible():
            self.elevation_chart._hover_x = dist_km
            self.elevation_chart.update()

    def _on_elevation_clicked(self, dist_km: float):
        if not self.best_route or not self.best_route.points:
            return
        cum_dists = cumulative_distances_km(self.best_route.points)
        if not cum_dists:
            return
        idx = min(range(len(cum_dists)), key=lambda i: abs(cum_dists[i] - dist_km))
        pt = self.best_route.points[idx]
        self.map_view.pan_to_point(pt.lat, pt.lon)

    def _on_edit_toggled(self, checked: bool):
        if self.current_routes and self.best_route and self.current_request:
            self._apply_route_state(self.current_routes, self.best_route, self.current_request, fit_bounds=False)
        self.map_view.set_edit_mode(checked)



    def _ensure_via_points_seeded(self):
        """
        If the current request is a generated loop (is_loop=True with empty via_points)
        and we have a valid best_route, extract key shape waypoints from best_route.points
        so that editing/adding a waypoint doesn't collapse the generated loop.
        """
        if not self.current_request or not self.best_route or not self.best_route.points:
            return
        if self.current_request.via_points:
            return

        pts = self.best_route.points
        n = len(pts)
        if n < 10:
            return

        indices = [int(n * 0.25), int(n * 0.50), int(n * 0.75)]
        seeded = [(pts[i].lat, pts[i].lon) for i in indices]
        self.current_request.via_points = seeded

    def _find_best_waypoint_insert_index(self, lat: float, lon: float, via_points: list[tuple[float, float]]) -> int:
        if not self.best_route or not self.best_route.points or not via_points:
            return len(via_points)

        pts = self.best_route.points
        from core.geo import haversine_distance_m

        click_idx = min(range(len(pts)), key=lambda i: haversine_distance_m(pts[i].lat, pts[i].lon, lat, lon))

        for idx, (vlat, vlon) in enumerate(via_points):
            v_idx = min(range(len(pts)), key=lambda i: haversine_distance_m(pts[i].lat, pts[i].lon, vlat, vlon))
            if v_idx > click_idx:
                return idx

        return len(via_points)

    def _on_waypoint_added(self, lat: float, lon: float, index: int):
        if not self.current_request:
            return
        if self.current_request.start_location == "Manual Start":
            # A delayed generic bridge event must never turn a waypoint into
            # a start point after a new manual-create session begins.
            return

        self._ensure_via_points_seeded()
        via_points = list(self.current_request.via_points)

        # If index is at or beyond the end of via_points (extending the route), append to the end
        if index >= len(via_points):
            via_points.append((lat, lon))
        elif self.best_route and self.best_route.points and len(via_points) > 0:
            insert_idx = self._find_best_waypoint_insert_index(lat, lon, via_points)
            via_points.insert(insert_idx, (lat, lon))
        else:
            insert_idx = max(0, min(index, len(via_points)))
            via_points.insert(insert_idx, (lat, lon))
        self._start_route_edit(via_points, "Replanning through the new waypoint...")

    def _on_waypoint_moved(self, old_index: int, new_index: int, lat: float, lon: float):
        if not self.current_request or old_index < 0 or old_index >= len(self.current_request.via_points):
            return
        via_points = list(self.current_request.via_points)
        via_points.pop(old_index)
        new_index = max(0, min(new_index, len(via_points)))
        via_points.insert(new_index, (lat, lon))
        self._start_route_edit(via_points, "Replanning with the moved waypoint...")

    def _on_waypoint_removed(self, index: int):
        if not self.current_request or index < 0 or index >= len(self.current_request.via_points):
            return
        via_points = list(self.current_request.via_points)
        via_points.pop(index)
        self._start_route_edit(via_points, "Replanning after removing the waypoint...")

    def _start_route_edit(self, via_points: list[tuple[float, float]], status: str):
        if not self.current_request:
            return
        if self.best_route and self.current_routes:
            self.undo_stack.append((
                deepcopy(self.current_routes),
                deepcopy(self.best_route),
                deepcopy(self.current_request),
            ))
            self.undo_button.setEnabled(True)
        self.plan_button.setEnabled(False)
        self.status_label.setText(status)
        self.status_label.setVisible(True)
        self.loading_spinner.start()

        self.edit_worker = RouteEditWorker(self.engine, self.current_request, via_points)
        self.edit_worker.succeeded.connect(self._on_success)
        self.edit_worker.failed.connect(self._on_edit_failure)
        self.edit_worker.finished.connect(lambda: self.plan_button.setEnabled(True))
        self.edit_worker.start()

    def _on_edit_failure(self, message: str):
        self.loading_spinner.stop()
        if self.undo_stack:
            self.undo_stack.pop()
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.edit_button.setEnabled(True)
        QMessageBox.warning(self, "Route edit failed", message)

    def _on_undo_clicked(self):
        if not self.undo_stack:
            return

        all_routes, best, request = self.undo_stack.pop()
        self.undo_button.setEnabled(bool(self.undo_stack))
        self._apply_route_state(all_routes, best, request, fit_bounds=False)
        if self.edit_button.isChecked():
            self.map_view.set_edit_mode(True)
        self.status_label.setText("Undid the last route edit.")
        self.status_label.setVisible(True)

    def _on_export_clicked(self):
        if not self.best_route:
            return

        default_name = "route_planner_route.tcx"
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Route",
            default_name,
            "TCX course with turn cues (*.tcx);;GPX track (*.gpx)",
        )
        if not path:
            return

        use_tcx = selected_filter.startswith("TCX") or path.lower().endswith(".tcx")
        extension = ".tcx" if use_tcx else ".gpx"
        if not path.lower().endswith((".gpx", ".tcx")):
            path += extension

        try:
            route_export = (
                route_to_tcx(self.best_route, self.best_route.summary())
                if use_tcx
                else route_to_gpx(self.best_route, self.best_route.summary())
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(route_export)
        except Exception as e:
            QMessageBox.warning(self, "Route export failed", str(e))
            return

        QMessageBox.information(self, "Route exported", f"Saved route to:\n{path}")

    def _on_save_clicked(self):
        if not self.best_route or not self.current_request:
            return

        distance_label = f"{self.best_route.distance_km:.1f}km"
        activity_label = self.current_request.activity.value.replace("-", " ").replace("foot ", "").title()
        default_name = f"{activity_label} {distance_label}"

        name, ok = QInputDialog.getText(self, "Save Route", "Name this route:", text=default_name)
        if not ok or not name.strip():
            return

        try:
            persist_route(name.strip(), self.current_request, self.best_route)
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return

        self.status_label.setText(f"Saved as \"{name.strip()}\".")
        self.status_label.setVisible(True)

    def _on_my_routes_clicked(self):
        dialog = SavedRoutesDialog(self)
        if dialog.exec_() != QDialog.Accepted or dialog.selected_route_id is None:
            return

        try:
            request, route = load_route(dialog.selected_route_id)
        except Exception as e:
            QMessageBox.warning(self, "Load failed", str(e))
            return

        self.undo_stack.clear()
        self._apply_route_state([route], route, request, warnings=[])
        self.status_label.setText("Loaded saved route. Edit or export it like any planned route.")
        self.status_label.setVisible(True)

    def _on_settings_clicked(self):
        dialog = SettingsDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        new_theme = get_app_theme()
        if new_theme != self.current_theme:
            self.set_app_theme(new_theme)

        # Rebuild the provider list from the freshly-saved keys and swap
        # it into the existing engine in place — RouteEngine.providers/
        # geocode_providers are plain mutable attributes, so this takes
        # effect immediately for the next route planned, no restart needed.
        providers, geocode_providers = get_configured_providers()
        self.engine.providers = providers
        self.engine.geocode_providers = geocode_providers

        notice = diagnose_env_setup()
        self.status_label.setText(notice or "Settings saved.")
        self.status_label.setVisible(True)
        self._fade_in(self.status_label)

    def _on_import_gpx_clicked(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, "Import GPX", "", "GPX files (*.gpx);;All files (*)"
        )
        if not path:
            return

        try:
            request, route = import_gpx(path)
        except GPXImportError as e:
            QMessageBox.warning(self, "Import failed", str(e))
            return
        except Exception as e:
            QMessageBox.warning(self, "Import failed", f"Unexpected error reading this file: {e}")
            return

        self.undo_stack.clear()
        self._apply_route_state([route], route, request, warnings=[])

        note = ""
        if route.elevation_gain_m is None:
            note = " (no elevation data in this file)"
        self.status_label.setText(
            f"Imported {route.distance_km:.1f}km from {Path(path).name}{note}. "
            f"Edit or export it like any planned route."
        )
        self.status_label.setVisible(True)
