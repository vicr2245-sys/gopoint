"""
Free, no-key weather summary for the route's start location, via
Open-Meteo (https://open-meteo.com) — gives a quick "what will conditions
be like" read alongside a planned or imported route. No signup, no API
key, no card — consistent with the rest of this app's provider choices.
"""
from dataclasses import dataclass
from typing import Optional

import requests

BASE_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 10

# WMO weather interpretation codes -> (emoji, short label). Not
# exhaustive — covers the cases likely to matter for planning a run/ride;
# anything unmapped falls back to a generic label rather than erroring.
WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("☀️", "Clear"),
    1: ("🌤️", "Mostly clear"),
    2: ("⛅", "Partly cloudy"),
    3: ("☁️", "Overcast"),
    45: ("🌫️", "Fog"),
    48: ("🌫️", "Fog"),
    51: ("🌦️", "Light drizzle"),
    53: ("🌦️", "Drizzle"),
    55: ("🌧️", "Dense drizzle"),
    61: ("🌦️", "Light rain"),
    63: ("🌧️", "Rain"),
    65: ("🌧️", "Heavy rain"),
    71: ("🌨️", "Light snow"),
    73: ("🌨️", "Snow"),
    75: ("❄️", "Heavy snow"),
    80: ("🌦️", "Rain showers"),
    81: ("🌧️", "Rain showers"),
    82: ("⛈️", "Violent rain showers"),
    95: ("⛈️", "Thunderstorm"),
    96: ("⛈️", "Thunderstorm with hail"),
    99: ("⛈️", "Thunderstorm with heavy hail"),
}
DEFAULT_WEATHER_ICON = ("🌡️", "Conditions")


class WeatherError(Exception):
    pass


@dataclass
class WeatherSummary:
    temperature_c: float
    wind_kmh: float
    precipitation_probability: Optional[float]
    emoji: str
    label: str

    def display_text(self) -> str:
        text = f"{self.emoji} {self.temperature_c:.0f}°C · wind {self.wind_kmh:.0f} km/h"
        if self.precipitation_probability is not None:
            text += f" · {self.precipitation_probability:.0f}% rain chance"
        text += f" · {self.label}"
        return text


def get_weather_summary(lat: float, lon: float) -> WeatherSummary:
    try:
        resp = requests.get(
            BASE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,wind_speed_10m,weather_code",
                "hourly": "precipitation_probability",
                "forecast_days": 1,
                "timezone": "auto",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise WeatherError(f"Weather request failed: {e}") from e

    if resp.status_code != 200:
        raise WeatherError(f"Weather request failed: {resp.status_code} {resp.text}")

    data = resp.json()
    current = data.get("current", {})
    if "temperature_2m" not in current:
        raise WeatherError("Weather response missing current conditions")

    emoji, label = WEATHER_CODES.get(current.get("weather_code"), DEFAULT_WEATHER_ICON)

    precip_prob = None
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    probs = hourly.get("precipitation_probability", [])
    current_time = current.get("time")
    if current_time and current_time in times:
        idx = times.index(current_time)
        if idx < len(probs):
            precip_prob = probs[idx]

    return WeatherSummary(
        temperature_c=current["temperature_2m"],
        wind_kmh=current.get("wind_speed_10m", 0.0),
        precipitation_probability=precip_prob,
        emoji=emoji,
        label=label,
    )
