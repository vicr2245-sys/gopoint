"""
Tests core/weather.py by monkeypatching requests.get, so this runs
without hitting the real Open-Meteo API. Covers: successful parsing with
matching precipitation data, an unmapped weather code falling back
gracefully, a malformed/error response raising WeatherError cleanly, and
a network exception being wrapped rather than propagating raw.

Run with: python3 test_weather.py
"""
import sys

sys.path.insert(0, ".")

import requests

import core.weather as weather_module
from core.weather import WeatherError, get_weather_summary


class FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json_data = json_data
        self.text = str(json_data)

    def json(self):
        return self._json_data


def test_successful_parse():
    def fake_get(url, params, timeout):
        return FakeResponse(200, {
            "current": {"time": "2026-07-16T10:00", "temperature_2m": 18.5, "wind_speed_10m": 12.0, "weather_code": 61},
            "hourly": {"time": ["2026-07-16T09:00", "2026-07-16T10:00"], "precipitation_probability": [10, 40]},
        })

    requests.get = fake_get
    summary = get_weather_summary(59.9, 10.7)

    assert summary.temperature_c == 18.5
    assert summary.wind_kmh == 12.0
    assert summary.precipitation_probability == 40  # matched to the 10:00 hourly slot
    assert summary.label == "Light rain"
    assert "18°C" in summary.display_text()
    assert "40% rain chance" in summary.display_text()
    print("test_successful_parse: PASS")


def test_unmapped_weather_code_falls_back_gracefully():
    def fake_get(url, params, timeout):
        return FakeResponse(200, {
            "current": {"time": "2026-07-16T10:00", "temperature_2m": 5.0, "wind_speed_10m": 3.0, "weather_code": 9999},
            "hourly": {"time": [], "precipitation_probability": []},
        })

    requests.get = fake_get
    summary = get_weather_summary(59.9, 10.7)

    assert summary.label == "Conditions"  # default fallback, not a crash
    assert summary.precipitation_probability is None  # no matching hourly slot
    print("test_unmapped_weather_code_falls_back_gracefully: PASS")


def test_bad_status_code_raises_weather_error():
    def fake_get(url, params, timeout):
        return FakeResponse(400, {"error": True, "reason": "bad params"})

    requests.get = fake_get
    try:
        get_weather_summary(999, 999)
        assert False, "expected WeatherError for a non-200 response"
    except WeatherError as e:
        assert "400" in str(e)
        print("test_bad_status_code_raises_weather_error: PASS")


def test_missing_current_data_raises_weather_error():
    def fake_get(url, params, timeout):
        return FakeResponse(200, {"current": {}, "hourly": {}})

    requests.get = fake_get
    try:
        get_weather_summary(59.9, 10.7)
        assert False, "expected WeatherError when current conditions are missing"
    except WeatherError as e:
        assert "missing" in str(e).lower()
        print("test_missing_current_data_raises_weather_error: PASS")


def test_network_exception_is_wrapped():
    def fake_get(url, params, timeout):
        raise requests.ConnectionError("simulated network failure")

    requests.get = fake_get
    try:
        get_weather_summary(59.9, 10.7)
        assert False, "expected WeatherError wrapping the network exception"
    except WeatherError as e:
        assert "simulated network failure" in str(e)
        print("test_network_exception_is_wrapped: PASS")


if __name__ == "__main__":
    original_get = requests.get
    try:
        test_successful_parse()
        test_unmapped_weather_code_falls_back_gracefully()
        test_bad_status_code_raises_weather_error()
        test_missing_current_data_raises_weather_error()
        test_network_exception_is_wrapped()
    finally:
        requests.get = original_get

    print("\nPASS: all weather module tests passed.")
