"""Tests for date, time and weather context."""
import json
import os
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import context  # noqa: E402


def test_format_datetime():
    assert context.format_datetime(datetime(2026, 11, 1, 4, 5)) == \
        "Heute ist Sonntag, der 1. November 2026, es ist 4:05 Uhr."


def test_format_weather():
    data = {"current": {"temperature_2m": 6.6, "weather_code": 3},
            "daily": {"temperature_2m_max": [10.2, 12], "temperature_2m_min": [3.9, 5],
                      "weather_code": [61, 0]}}
    text = context.format_weather("Zuhause", data)
    assert text == ("Wetter in Zuhause: jetzt 7 °C, bedeckt; heute 4 bis 10 °C, leichter Regen; "
                    "morgen 5 bis 12 °C, klar.")


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/core/api/config"):
            assert self.headers["Authorization"] == "Bearer tok"
            body = {"time_zone": "Europe/Berlin", "location_name": "Zuhause",
                    "latitude": 50.8, "longitude": 7.0}
        else:
            body = {"current": {"temperature_2m": 5, "weather_code": 0},
                    "daily": {"temperature_2m_max": [9, 11], "temperature_2m_min": [2, 3],
                              "weather_code": [0, 3]}}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


async def test_build_context_with_ha_and_weather():
    server = HTTPServer(("127.0.0.1", 19994), _H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {"SUPERVISOR_TOKEN": "tok", "HA_API_URL": "http://127.0.0.1:19994/core/api",
           "WEATHER_URL": "http://127.0.0.1:19994/v1/forecast"}
    os.environ.update(env)
    context._cache.clear()
    try:
        text = await context.build_context()
        assert "Heute ist" in text
        assert "Wetter in Zuhause: jetzt 5 °C, klar" in text
    finally:
        server.shutdown()
        for k in env:
            os.environ.pop(k, None)
        context._cache.clear()


async def test_build_context_without_ha():
    context._cache.clear()
    text = await context.build_context()
    assert "Heute ist" in text and "Wetter" not in text
