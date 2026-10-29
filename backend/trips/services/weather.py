"""Hourly forecasts for many points: Open-Meteo (live) or a deterministic simulated storm (demo).

Both providers return :class:`HourlySeries` objects, and ``HourlySeries.at(t)`` reads the
weather the truck will meet at its ETA ``t``:

* wind / gusts / temperature are instantaneous values → linearly interpolated between hours;
* rain / snowfall are hourly totals for the *preceding* hour (Open-Meteo convention) → the
  bucket covering ``t`` is used, which is directly a rate in in/hr.
"""
from __future__ import annotations

import bisect
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, Sequence

import requests
from django.conf import settings
from django.core.cache import cache

from .geo import LatLon
from .http import get_session, timeout
from .risk import WeatherSample

logger = logging.getLogger(__name__)

HOURLY_VARIABLES = ("temperature_2m", "wind_speed_10m", "wind_gusts_10m", "rain", "showers", "snowfall")
CHUNK_SIZE = 50
MAX_WORKERS = 4


class WeatherUnavailable(Exception):
    pass


@dataclass
class HourlySeries:
    times: list[int]  # unix seconds, hour aligned, ascending
    wind_mph: list[float | None]
    gust_mph: list[float | None]
    rain_in: list[float | None]  # liquid rain (rain + showers) during the preceding hour
    snow_in: list[float | None]  # snowfall depth during the preceding hour
    temp_f: list[float | None]

    def at(self, t: float) -> WeatherSample | None:
        if not self.times or t < self.times[0] or t > self.times[-1]:
            return None
        i = bisect.bisect_right(self.times, t) - 1
        if self.times[i] == t or i == len(self.times) - 1:
            j, f = i, 0.0
        else:
            j = i + 1
            f = (t - self.times[i]) / (self.times[j] - self.times[i])

        def interp(values: list[float | None]) -> float | None:
            a, b = values[i], values[j]
            if a is None or b is None:
                return a if b is None else b
            return a + (b - a) * f

        wind = interp(self.wind_mph)
        if wind is None:
            return None
        bucket = j if f > 0 else i
        return WeatherSample(
            wind_mph=round(wind, 1),
            gust_mph=None if (g := interp(self.gust_mph)) is None else round(g, 1),
            rain_in_hr=round(self.rain_in[bucket] or 0.0, 3),
            snow_in_hr=round(self.snow_in[bucket] or 0.0, 3),
            temp_f=None if (tf := interp(self.temp_f)) is None else round(tf, 1),
        )


class WeatherProvider(Protocol):
    def hourly(self, points: Sequence[LatLon], start: datetime, end: datetime) -> list[HourlySeries | None]: ...


def forecast_window(start: datetime, end: datetime) -> tuple[str, str]:
    """Whole UTC days covering ``[start-1h, end+2h]`` — one stable cache key per trip window."""
    first = (start - timedelta(hours=1)).astimezone(timezone.utc).date()
    last = (end + timedelta(hours=2)).astimezone(timezone.utc).date()
    return first.isoformat(), last.isoformat()


# --- Open-Meteo ------------------------------------------------------------------------------

_LENGTH_TO_INCH = {"inch": 1.0, "in": 1.0, "mm": 1 / 25.4, "cm": 1 / 2.54}
_SPEED_TO_MPH = {"mp/h": 1.0, "mph": 1.0, "km/h": 0.621371, "m/s": 2.236936, "kn": 1.150779}


def _scaled(values: list, factor: float) -> list[float | None]:
    return [None if v is None else v * factor for v in values]


def parse_open_meteo_location(payload: dict) -> HourlySeries:
    hourly, units = payload["hourly"], payload.get("hourly_units", {})
    speed = _SPEED_TO_MPH.get(units.get("wind_speed_10m", "mp/h"), 1.0)
    rain_f = _LENGTH_TO_INCH.get(units.get("rain", "inch"), 1.0)
    showers_f = _LENGTH_TO_INCH.get(units.get("showers", "inch"), 1.0)
    snow_f = _LENGTH_TO_INCH.get(units.get("snowfall", "inch"), 1.0)
    rain = [
        None if (r is None and s is None) else (r or 0.0) * rain_f + (s or 0.0) * showers_f
        for r, s in zip(hourly["rain"], hourly.get("showers") or [None] * len(hourly["rain"]))
    ]
    temp = hourly.get("temperature_2m") or [None] * len(hourly["time"])
    if units.get("temperature_2m", "°F") == "°C":
        temp = [None if v is None else v * 9 / 5 + 32 for v in temp]
    return HourlySeries(
        times=[int(t) for t in hourly["time"]],
        wind_mph=_scaled(hourly["wind_speed_10m"], speed),
        gust_mph=_scaled(hourly.get("wind_gusts_10m") or [None] * len(hourly["time"]), speed),
        rain_in=rain,
        snow_in=_scaled(hourly["snowfall"], snow_f),
        temp_f=temp,
    )


class OpenMeteoProvider:
    def __init__(self) -> None:
        cfg = settings.TRUCK_ROUTING
        self.api_key = cfg["OPEN_METEO_API_KEY"]
        base = cfg["OPEN_METEO_URL"]
        if self.api_key and "customer-" not in base:
            base = base.replace("://api.", "://customer-api.")
        self.url = base.rstrip("/") + "/v1/forecast"
        self.cache_s = cfg["WEATHER_CACHE_S"]

    @staticmethod
    def _key(point: LatLon, window: tuple[str, str]) -> str:
        return f"wx:om:v2:{point[0]:.3f}:{point[1]:.3f}:{window[0]}:{window[1]}"

    def _fetch_chunk(self, points: Sequence[LatLon], window: tuple[str, str]) -> list[HourlySeries]:
        params = {
            "latitude": ",".join(f"{p[0]:.3f}" for p in points),
            "longitude": ",".join(f"{p[1]:.3f}" for p in points),
            "hourly": ",".join(HOURLY_VARIABLES),
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "temperature_unit": "fahrenheit",
            "timezone": "GMT",
            "timeformat": "unixtime",
            "start_date": window[0],
            "end_date": window[1],
        }
        if self.api_key:
            params["apikey"] = self.api_key
        try:
            resp = get_session().get(self.url, params=params, timeout=timeout())
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise WeatherUnavailable(f"Weather service unavailable: {exc}") from exc
        if resp.status_code != 200 or (isinstance(data, dict) and data.get("error")):
            reason = data.get("reason") if isinstance(data, dict) else resp.text[:200]
            raise WeatherUnavailable(f"Weather service error ({resp.status_code}): {reason}")
        payloads = data if isinstance(data, list) else [data]
        if len(payloads) != len(points):
            raise WeatherUnavailable("Weather service returned an unexpected number of locations.")
        return [parse_open_meteo_location(p) for p in payloads]

    def hourly(self, points: Sequence[LatLon], start: datetime, end: datetime) -> list[HourlySeries | None]:
        window = forecast_window(start, end)
        horizon = (datetime.now(timezone.utc) + timedelta(days=15)).date().isoformat()
        if window[1] > horizon:
            window = (window[0], horizon)  # Open-Meteo forecasts 16 days ahead; later ETAs get no data

        keys = [self._key(p, window) for p in points]
        cached = cache.get_many(keys)
        results: dict[str, HourlySeries] = {k: HourlySeries(**v) for k, v in cached.items()}
        missing = list(dict.fromkeys(k for k in keys if k not in results))
        point_by_key = dict(zip(keys, points))
        chunks = [missing[i : i + CHUNK_SIZE] for i in range(0, len(missing), CHUNK_SIZE)]

        if chunks:
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(chunks))) as pool:
                fetched = pool.map(lambda ks: (ks, self._fetch_chunk([point_by_key[k] for k in ks], window)), chunks)
                fresh = {}
                for chunk_keys, series_list in fetched:
                    for k, s in zip(chunk_keys, series_list):
                        results[k] = s
                        fresh[k] = asdict(s)
            cache.set_many(fresh, self.cache_s)
        return [results.get(k) for k in keys]


# --- Simulated storm (demo mode) -------------------------------------------------------------

@dataclass(frozen=True)
class StormScenario:
    """A deterministic storm system that drifts east and reaches its peak on the anchor point
    exactly when the truck on the fastest route would arrive there."""

    lat: float
    lon: float
    peak_time: float  # unix seconds
    radius_km: float
    trip_heading_deg: float
    speed_kmh: float = 30.0

    def as_dict(self) -> dict:
        return asdict(self)


def _local_km(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    return (lon - lon0) * 111.32 * math.cos(math.radians(lat0)), (lat - lat0) * 110.57


class SimulatedStormProvider:
    """Two cells: a wind + rain thunderstorm core, and a smaller snow squall to its side."""

    def __init__(self, scenario: StormScenario):
        self.s = scenario

    def _cells(self, t: float) -> list[tuple[float, float, float]]:
        s = self.s
        drift_km = s.speed_kmh * (t - s.peak_time) / 3600.0  # eastward motion
        side = math.radians(s.trip_heading_deg + 90)
        offset = 1.6 * s.radius_km
        return [
            (drift_km, 0.0, s.radius_km),
            (drift_km + offset * math.sin(side), offset * math.cos(side), 0.7 * s.radius_km),
        ]

    def sample(self, point: LatLon, t: float) -> tuple[float, float, float, float]:
        x, y = _local_km(point[0], point[1], self.s.lat, self.s.lon)
        (cx1, cy1, r1), (cx2, cy2, r2) = self._cells(t)
        g1 = math.exp(-(((x - cx1) ** 2 + (y - cy1) ** 2) / (r1 * r1)))
        g2 = math.exp(-(((x - cx2) ** 2 + (y - cy2) ** 2) / (r2 * r2)))
        breeze = 8 + 3 * math.sin(t / 3600.0 * math.pi / 12)
        wind = breeze + 54 * g1 + 30 * g2
        rain = 1.25 * g1**1.3
        snow = 2.6 * g2**1.2
        temp = 52 - 22 * g2
        return wind, rain, snow, temp

    def hourly(self, points: Sequence[LatLon], start: datetime, end: datetime) -> list[HourlySeries | None]:
        first = int((start - timedelta(hours=1)).timestamp()) // 3600 * 3600
        last = int((end + timedelta(hours=2)).timestamp()) // 3600 * 3600
        hours = list(range(first, last + 1, 3600))
        out: list[HourlySeries | None] = []
        for p in points:
            rows = [self.sample(p, t) for t in hours]
            out.append(
                HourlySeries(
                    times=hours,
                    wind_mph=[round(r[0], 1) for r in rows],
                    gust_mph=[round(r[0] * 1.4, 1) for r in rows],
                    rain_in=[round(r[1], 3) for r in rows],
                    snow_in=[round(r[2], 3) for r in rows],
                    temp_f=[round(r[3], 1) for r in rows],
                )
            )
        return out


def get_provider(source: str, scenario: StormScenario | None = None) -> WeatherProvider:
    if source == "simulated":
        if scenario is None:
            raise ValueError("A storm scenario is required for simulated weather.")
        return SimulatedStormProvider(scenario)
    return OpenMeteoProvider()
