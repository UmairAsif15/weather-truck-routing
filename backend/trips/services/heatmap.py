"""Weather heatmap over the trip corridor for every hour from departure to +48 h.

The grid is square in Web Mercator, so the client can draw each hour as a tiny image that a
Leaflet ImageOverlay stretches over the exact bounds with no distortion. Only cells within the
corridor (``corridor_km`` of any route) are forecast; the rest stay transparent.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Sequence

from django.conf import settings

from . import geo
from .geo import LatLon
from .risk import WeatherSample, continuous_score
from .weather import WeatherProvider

EARTH_RADIUS_KM = 6371.0088


def _corridor_cells(paths: Sequence[Sequence[LatLon]], corridor_km: float, max_points: int):
    samples = [p for path in paths for p in geo.resample(path, 3000.0)]
    index = geo.SpatialIndex(samples, cell_deg=max(0.05, corridor_km / 100.0))
    south, west, north, east = geo.bbox(samples)
    mid_lat = (south + north) / 2
    pad_km = corridor_km + 10  # a little beyond the corridor so its edge fades out instead of being clipped
    pad_lat = pad_km / 110.57
    pad_lon = pad_km / (111.32 * max(0.2, math.cos(math.radians(mid_lat))))
    south, north = south - pad_lat, north + pad_lat
    west, east = west - pad_lon, east + pad_lon
    y_south, y_north = geo.lat_to_mercator_y(south), geo.lat_to_mercator_y(north)
    x_west, x_east = math.radians(west), math.radians(east)

    cell_km = max(6.0, corridor_km / 3)
    while True:
        step = cell_km / (EARTH_RADIUS_KM * math.cos(math.radians(mid_lat)))  # radians in mercator space
        cols = max(2, math.ceil((x_east - x_west) / step) + 1)
        rows = max(2, math.ceil((y_north - y_south) / step) + 1)
        cells: list[tuple[int, int, LatLon]] = []
        for r in range(rows):
            lat = geo.mercator_y_to_lat(y_north - r * step)
            for c in range(cols):
                lon = math.degrees(x_west + c * step)
                if index.nearest_m((lat, lon), rings=2) <= corridor_km * 1000:
                    cells.append((r, c, (lat, lon)))
        if len(cells) <= max_points:
            break
        cell_km *= 1.15

    half = step / 2
    bounds = {
        "north": geo.mercator_y_to_lat(y_north + half),
        "south": geo.mercator_y_to_lat(y_north - (rows - 1) * step - half),
        "west": math.degrees(x_west - half),
        "east": math.degrees(x_west + (cols - 1) * step + half),
    }
    return cells, rows, cols, bounds, cell_km


def build_heatmap(
    paths: Sequence[Sequence[LatLon]],
    departure: datetime,
    load_lb: float,
    provider: WeatherProvider,
    hours: int | None = None,
) -> dict:
    cfg = settings.TRUCK_ROUTING
    hours = hours if hours is not None else cfg["HEATMAP_HOURS"]
    corridor_km = cfg["HEATMAP_CORRIDOR_KM"]
    cells, rows, cols, bounds, cell_km = _corridor_cells(paths, corridor_km, cfg["HEATMAP_MAX_POINTS"])

    points = [p for _, _, p in cells]
    end = departure + timedelta(hours=hours)
    series_list = provider.hourly(points, departure, end) if points else []

    times, risk, wind, rain, snow = [], [], [], [], []
    for h in range(hours + 1):
        t = departure + timedelta(hours=h)
        times.append(t.isoformat(timespec="seconds"))
        frame_risk, frame_wind, frame_rain, frame_snow = [], [], [], []
        for series in series_list:
            sample: WeatherSample | None = series.at(t.timestamp()) if series else None
            if sample is None:
                for frame in (frame_risk, frame_wind, frame_rain, frame_snow):
                    frame.append(None)
                continue
            frame_risk.append(continuous_score(sample, load_lb))
            frame_wind.append(round(sample.wind_mph, 1))
            frame_rain.append(round(sample.rain_in_hr, 3))
            frame_snow.append(round(sample.snow_in_hr, 3))
        risk.append(frame_risk)
        wind.append(frame_wind)
        rain.append(frame_rain)
        snow.append(frame_snow)

    return {
        "bounds": {k: round(v, 5) for k, v in bounds.items()},
        "rows": rows,
        "cols": cols,
        "cells": [[r, c] for r, c, _ in cells],
        "cell_km": round(cell_km, 1),
        "corridor_km": corridor_km,
        "departure": departure.isoformat(timespec="seconds"),
        "times": times,
        "layers": {"risk": risk, "wind": wind, "rain": rain, "snow": snow},
    }
