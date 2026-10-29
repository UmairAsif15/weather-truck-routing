"""Deterministic stand-ins for the routing and weather APIs."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Sequence

from trips.services import geo
from trips.services.geo import LatLon
from trips.services.risk import WeatherSample
from trips.services.routing import Route
from trips.services.weather import HourlySeries


def straight_route(points: Sequence[LatLon], speed_mph: float = 60.0, summary: str = "") -> Route:
    """Route along the given vertices driven at a constant speed."""
    dist = [geo.haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1)]
    mps = speed_mph * geo.METERS_PER_MILE / 3600
    return Route(coords=list(points), seg_distance_m=dist, seg_duration_s=[d / mps for d in dist], summary=summary)


def line(start: LatLon, end: LatLon, n: int = 50) -> list[LatLon]:
    return [geo.lerp(start, end, i / n) for i in range(n + 1)]


class FakeRouter:
    def __init__(self, primary: list[Route], via: Callable[[LatLon], Route | None] | None = None):
        self.primary = primary
        self.via = via
        self.calls: list[Sequence[LatLon]] = []

    def route(self, waypoints: Sequence[LatLon], alternatives: int = 0) -> list[Route]:
        self.calls.append(waypoints)
        if len(waypoints) == 2:
            return list(self.primary)
        result = self.via(waypoints[1]) if self.via else None
        return [result] if result else []


class FieldProvider:
    """Weather defined by a function ``(lat, lon, unix_time) -> WeatherSample``."""

    def __init__(self, field: Callable[[float, float, float], WeatherSample]):
        self.field = field
        self.requested_points: list[LatLon] = []

    def hourly(self, points: Sequence[LatLon], start: datetime, end: datetime) -> list[HourlySeries]:
        self.requested_points.extend(points)
        first = int((start - timedelta(hours=1)).timestamp()) // 3600 * 3600
        last = int((end + timedelta(hours=2)).timestamp()) // 3600 * 3600
        hours = list(range(first, last + 1, 3600))
        out = []
        for lat, lon in points:
            samples = [self.field(lat, lon, t) for t in hours]
            out.append(HourlySeries(
                times=hours,
                wind_mph=[s.wind_mph for s in samples],
                gust_mph=[s.gust_mph for s in samples],
                rain_in=[s.rain_in_hr for s in samples],
                snow_in=[s.snow_in_hr for s in samples],
                temp_f=[s.temp_f for s in samples],
            ))
        return out


CALM = WeatherSample(wind_mph=5, gust_mph=8, rain_in_hr=0, snow_in_hr=0, temp_f=60)
