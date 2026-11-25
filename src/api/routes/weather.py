"""Погода Ташкента для карточки над меню и окна прогноза (Open-Meteo, без ключа).

GET /weather           — сейчас: {temp, code, day}; запрос в Open-Meteo раз в 15 минут на всех.
GET /weather/forecast  — сейчас, 24 часа и 10 дней; запрос раз в 30 минут на всех.

О пользователе в Open-Meteo ничего не отправляется — только координаты города.
Текущая погода открыта и без входа: её берёт и погодный фон сайта (дождь, снег, туман) на странице входа.
"""
import json
import threading
import time
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends

from src.api.deps.auth import current_user

router = APIRouter(prefix="/weather", tags=["Weather"])

LAT, LON = 41.31, 69.28  # Ташкент

WEATHER_URL = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
    "latitude": LAT, "longitude": LON, "timezone": "Asia/Tashkent",
    "current": "temperature_2m,weather_code,is_day",
})
FORECAST_URL = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
    "latitude": LAT, "longitude": LON, "timezone": "Asia/Tashkent", "forecast_days": 10,
    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,wind_direction_10m,"
               "pressure_msl,weather_code,is_day",
    "hourly": "temperature_2m,weather_code,is_day,precipitation_probability",
    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset,"
             "uv_index_max",
})

_weather = {"at": 0.0, "data": None}
_forecast = {"at": 0.0, "data": None}
_weather_lock = threading.Lock()
_forecast_lock = threading.Lock()


def _get_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": "Naturka/4"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _round(value, digits=0):
    return None if value is None else (round(value, digits) if digits else round(value))


def parse_forecast(raw: dict) -> dict:
    """Ответ Open-Meteo → то, что показывает окно прогноза."""
    cur, hourly, daily = raw["current"], raw["hourly"], raw["daily"]
    hour_now = cur["time"][:13]
    start = next((i for i, moment in enumerate(hourly["time"]) if moment[:13] >= hour_now), 0)
    hours = [{
        "time": hourly["time"][i][11:16], "temp": _round(hourly["temperature_2m"][i]),
        "code": hourly["weather_code"][i], "day": bool(hourly["is_day"][i]),
        "rain": hourly["precipitation_probability"][i],
    } for i in range(start, min(start + 24, len(hourly["time"])))]
    days = [{
        "date": moment, "code": daily["weather_code"][i], "max": _round(daily["temperature_2m_max"][i]),
        "min": _round(daily["temperature_2m_min"][i]), "rain": daily["precipitation_probability_max"][i],
        "sunrise": (daily["sunrise"][i] or "")[11:16], "sunset": (daily["sunset"][i] or "")[11:16],
        "uv": _round(daily["uv_index_max"][i], 1),
    } for i, moment in enumerate(daily["time"])]
    return {
        "current": {
            "temp": _round(cur["temperature_2m"]), "feels": _round(cur["apparent_temperature"]),
            "humidity": cur["relative_humidity_2m"], "wind": _round(cur["wind_speed_10m"]),
            "wind_dir": cur["wind_direction_10m"], "pressure": _round(cur["pressure_msl"]),
            "code": cur["weather_code"], "day": bool(cur.get("is_day", 1)), "time": cur["time"][11:16],
        },
        "hours": hours, "days": days,
    }


@router.get("")
def weather():
    """Текущая погода для карточки над меню. Если сервис недоступен — {} (карточка покажет только дату и время)."""
    with _weather_lock:
        now = time.time()
        if now - _weather["at"] > 900:
            _weather["at"] = now
            try:
                current = _get_json(WEATHER_URL, 4)["current"]
                _weather["data"] = {"temp": round(current["temperature_2m"]), "code": int(current["weather_code"]),
                                    "day": bool(current["is_day"])}
            except Exception:  # нет связи или сервис изменился: остаётся прошлое значение, новая попытка через 5 минут
                _weather["at"] = now - 600
        data = _weather["data"]
    return data or {}


@router.get("/forecast", dependencies=[Depends(current_user)])
def weather_forecast():
    """Окно прогноза: сейчас, 24 часа и 10 дней."""
    with _forecast_lock:
        now = time.time()
        if now - _forecast["at"] > 1800:
            _forecast["at"] = now
            try:
                _forecast["data"] = parse_forecast(_get_json(FORECAST_URL, 6))
            except Exception:  # нет связи: остаётся прошлый прогноз, новая попытка через минуту
                _forecast["at"] = now - 1740
        data = _forecast["data"]
    return data or {"current": None, "hours": [], "days": []}
