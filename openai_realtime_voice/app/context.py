"""
Live context for each conversation: current date and time and the local weather.

Location and time zone come from Home Assistant itself (Supervisor API, needs
homeassistant_api: true in config.yaml), so no personal data lives in this repo.
Weather comes from Open-Meteo (free, no API key). Everything is best effort:
if something fails, the session simply starts without that part.
"""
import logging
import os
import time
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]

WEATHER_CODES = {
    0: "klar", 1: "überwiegend klar", 2: "teilweise bewölkt", 3: "bedeckt",
    45: "Nebel", 48: "Nebel mit Reif", 51: "leichter Nieselregen", 53: "Nieselregen",
    55: "starker Nieselregen", 56: "gefrierender Nieselregen", 57: "gefrierender Nieselregen",
    61: "leichter Regen", 63: "Regen", 65: "starker Regen", 66: "gefrierender Regen",
    67: "gefrierender Regen", 71: "leichter Schneefall", 73: "Schneefall",
    75: "starker Schneefall", 77: "Schneegriesel", 80: "leichte Regenschauer",
    81: "Regenschauer", 82: "heftige Regenschauer", 85: "Schneeschauer",
    86: "starke Schneeschauer", 95: "Gewitter", 96: "Gewitter mit Hagel",
    99: "Gewitter mit starkem Hagel",
}

_cache: dict = {}
CACHE_S = 20 * 60


def format_datetime(now: datetime) -> str:
    return (f"Heute ist {WEEKDAYS[now.weekday()]}, der {now.day}. {MONTHS[now.month - 1]} "
            f"{now.year}, es ist {now.hour}:{now.minute:02d} Uhr.")


def describe_code(code) -> str:
    try:
        return WEATHER_CODES.get(int(code), "")
    except (TypeError, ValueError):
        return ""


def format_weather(place: str, data: dict) -> str:
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    parts = []
    if "temperature_2m" in cur:
        desc = describe_code(cur.get("weather_code"))
        parts.append(f"jetzt {round(cur['temperature_2m'])} °C" + (f", {desc}" if desc else ""))
    tmax, tmin, codes = (daily.get("temperature_2m_max") or [], daily.get("temperature_2m_min") or [],
                         daily.get("weather_code") or [])
    for i, label in enumerate(["heute", "morgen"]):
        if i < len(tmax) and i < len(tmin):
            desc = describe_code(codes[i]) if i < len(codes) else ""
            parts.append(f"{label} {round(tmin[i])} bis {round(tmax[i])} °C"
                         + (f", {desc}" if desc else ""))
    if not parts:
        return ""
    where = f" in {place}" if place else ""
    return f"Wetter{where}: " + "; ".join(parts) + "."


async def _ha_config(client: httpx.AsyncClient) -> Optional[dict]:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    url = os.environ.get("HA_API_URL", "http://supervisor/core/api") + "/config"
    resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    return resp.json()


INDOOR_TEMP = "sensor.wohnzimmer_wohnzimmer_fernbedienung_temperatur"
INDOOR_HUMIDITY = "sensor.wohnzimmer_wohnzimmer_fernbedienung_luftfeuchtigkeit"


async def _indoor(client: httpx.AsyncClient) -> str:
    """Living room temperature and humidity from the RM4 Pro sensor cable (HTS2)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return ""
    base = os.environ.get("HA_API_URL", "http://supervisor/core/api")
    vals = {}
    for key, ent in (("t", os.environ.get("INDOOR_TEMP_SENSOR") or INDOOR_TEMP),
                     ("h", os.environ.get("INDOOR_HUMIDITY_SENSOR") or INDOOR_HUMIDITY)):
        try:
            resp = await client.get(f"{base}/states/{ent}",
                                    headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                vals[key] = float(resp.json().get("state"))
        except Exception:
            pass
    if "t" not in vals:
        return ""
    text = f"Im Wohnzimmer sind es gerade {vals['t']:.1f} °C".replace(".", ",")
    if "h" in vals:
        text += f" bei {round(vals['h'])} % Luftfeuchtigkeit"
    return text + "."


async def build_context() -> str:
    """Return a short German text block with date, time and weather (or '')."""
    cached = _cache.get("ctx")
    lines: list[str] = []
    tz_name = None
    place = ""
    lat = lon = None
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            cfg = _cache.get("ha") if _cache.get("ha_t", 0) > time.time() - 3600 else None
            if cfg is None:
                cfg = await _ha_config(client)
                if cfg:
                    _cache["ha"], _cache["ha_t"] = cfg, time.time()
            if cfg:
                tz_name = cfg.get("time_zone")
                place = cfg.get("location_name") or ""
                lat, lon = cfg.get("latitude"), cfg.get("longitude")
        except Exception as e:
            logger.info("Home Assistant config not available: %s", e)

        tz_name = tz_name or os.environ.get("TZ") or "Europe/Berlin"
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(tz_name))
        except Exception:
            now = datetime.now()
        lines.append(format_datetime(now))

        if lat is not None and lon is not None:
            weather = None
            if cached and cached[0] > time.time() - CACHE_S:
                weather = cached[1]
            else:
                try:
                    resp = await client.get(
                        os.environ.get("WEATHER_URL", "https://api.open-meteo.com/v1/forecast"),
                        params={
                            "latitude": lat, "longitude": lon,
                            "current": "temperature_2m,weather_code",
                            "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                            "timezone": tz_name, "forecast_days": 2,
                        },
                    )
                    resp.raise_for_status()
                    weather = format_weather(place, resp.json())
                    _cache["ctx"] = (time.time(), weather)
                except Exception as e:
                    logger.info("Weather not available: %s", e)
            if weather:
                lines.append(weather)

        indoor = await _indoor(client)
        if indoor:
            lines.append(indoor)
    return "\n\nAKTUELLE LAGE (nutze es nur, wenn es passt)\n" + "\n".join(lines)
