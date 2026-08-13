"""
Local persistence for saved routes.

Lets the user save a planned/edited route by name and reload it later
without re-querying any provider or the Claude API — the full geometry,
surface data, and instructions are stored as-is, so loading a saved route
is instant and works offline.

Stored as SQLite at ~/.route_planner/routes.db. This works identically on
Windows/Mac/Linux with zero setup (no server, no extra dependency beyond
the stdlib), consistent with this being a single-user desktop app.
"""
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from models.route_request import (
    Activity,
    ElevationPreference,
    NormalizedRoute,
    RouteInstruction,
    RoutePoint,
    RouteRequest,
    SurfaceSegment,
)

DB_PATH = Path.home() / ".route_planner" / "routes.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            activity TEXT NOT NULL,
            distance_km REAL NOT NULL,
            request_json TEXT NOT NULL,
            route_json TEXT NOT NULL
        )
        """
    )
    return conn


class SavedRouteSummary:
    """Lightweight row for listing saved routes without deserializing the
    full request/route payload for every entry."""

    def __init__(self, id: int, name: str, created_at: str, activity: str, distance_km: float):
        self.id = id
        self.name = name
        self.created_at = created_at
        self.activity = activity
        self.distance_km = distance_km

    def label(self) -> str:
        created_date = self.created_at.split("T")[0]
        activity_label = self.activity.replace("-", " ").replace("foot ", "").title()
        return f"{self.name}  —  {activity_label}, {self.distance_km:.1f}km  ({created_date})"


def save_route(name: str, request: RouteRequest, route: NormalizedRoute) -> int:
    request_dict = asdict(request)
    route_dict = asdict(route)
    route_dict["raw_response"] = None  # don't persist the full raw provider payload — not needed to redisplay

    conn = _connect()
    try:
        cursor = conn.execute(
            "INSERT INTO saved_routes (name, created_at, activity, distance_km, request_json, route_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                name,
                datetime.now(timezone.utc).isoformat(),
                request.activity.value,
                route.distance_km,
                json.dumps(request_dict),
                json.dumps(route_dict),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def list_routes() -> list[SavedRouteSummary]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, name, created_at, activity, distance_km FROM saved_routes ORDER BY created_at DESC"
        ).fetchall()
        return [SavedRouteSummary(*row) for row in rows]
    finally:
        conn.close()


def load_route(route_id: int) -> tuple[RouteRequest, NormalizedRoute]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT request_json, route_json FROM saved_routes WHERE id = ?",
            (route_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise ValueError(f"No saved route with id {route_id}")

    request = _request_from_dict(json.loads(row[0]))
    route = _route_from_dict(json.loads(row[1]))
    return request, route


def delete_route(route_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM saved_routes WHERE id = ?", (route_id,))
        conn.commit()
    finally:
        conn.close()


def _request_from_dict(data: dict) -> RouteRequest:
    data = dict(data)
    data["activity"] = Activity(data["activity"])
    data["elevation_preference"] = ElevationPreference(data["elevation_preference"])
    data["via_points"] = [tuple(point) for point in data.get("via_points", [])]
    return RouteRequest(**data)


def _route_from_dict(data: dict) -> NormalizedRoute:
    data = dict(data)
    data["points"] = [RoutePoint(**p) for p in data.get("points", [])]
    data["instructions"] = [RouteInstruction(**i) for i in data.get("instructions", [])]
    data["surface_segments"] = [SurfaceSegment(**s) for s in data.get("surface_segments", [])]
    return NormalizedRoute(**data)
