"""Truck timing along a route and checkpoint sampling every N miles."""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import geo
from .geo import METERS_PER_MILE, LatLon
from .routing import Route


@dataclass
class TruckProfile:
    """Cumulative distance and drive time at every vertex of the route geometry.

    The router's per-segment durations are for passenger cars, so each segment is slowed to
    the truck's governed top speed where the car would be faster.
    """

    coords: list[LatLon]
    cum_m: list[float]
    cum_s: list[float]

    @classmethod
    def from_route(cls, route: Route, max_speed_mph: float) -> "TruckProfile":
        max_mps = max_speed_mph * METERS_PER_MILE / 3600.0
        cum_m, cum_s = [0.0], [0.0]
        for dist, dur in zip(route.seg_distance_m, route.seg_duration_s):
            truck_dur = max(dur, dist / max_mps) if max_mps > 0 else dur
            cum_m.append(cum_m[-1] + dist)
            cum_s.append(cum_s[-1] + truck_dur)
        return cls(coords=list(route.coords), cum_m=cum_m, cum_s=cum_s)

    @property
    def distance_m(self) -> float:
        return self.cum_m[-1]

    @property
    def duration_s(self) -> float:
        return self.cum_s[-1]

    def locate(self, target_m: float) -> tuple[LatLon, float]:
        """Position and elapsed drive seconds at ``target_m`` metres along the route."""
        target_m = min(max(target_m, 0.0), self.distance_m)
        i = bisect.bisect_right(self.cum_m, target_m) - 1
        i = min(max(i, 0), len(self.cum_m) - 2)
        span = self.cum_m[i + 1] - self.cum_m[i]
        f = 0.0 if span == 0 else (target_m - self.cum_m[i]) / span
        point = geo.lerp(self.coords[i], self.coords[i + 1], f)
        elapsed = self.cum_s[i] + f * (self.cum_s[i + 1] - self.cum_s[i])
        return point, elapsed


@dataclass
class Checkpoint:
    index: int
    mile: float
    lat: float
    lon: float
    eta: datetime
    elapsed_s: float
    # Stretch of road this checkpoint represents (midpoint to midpoint with its neighbours).
    start_mile: float
    end_mile: float

    @property
    def represented_miles(self) -> float:
        return self.end_mile - self.start_mile


def sample_checkpoints(profile: TruckProfile, departure: datetime, interval_mi: float) -> list[Checkpoint]:
    """Checkpoints at mile 0, every ``interval_mi`` miles, and at the destination.

    Each checkpoint carries the truck's ETA there, and owns the road from halfway back to the
    previous checkpoint to halfway on to the next, so represented miles sum to the trip length.
    """
    if interval_mi <= 0:
        raise ValueError("interval_mi must be positive")
    total_mi = profile.distance_m / METERS_PER_MILE
    miles = [0.0]
    m = interval_mi
    while m < total_mi - 1e-6:
        miles.append(m)
        m += interval_mi
    if total_mi - miles[-1] > 1e-6:
        miles.append(total_mi)

    checkpoints: list[Checkpoint] = []
    for i, mile in enumerate(miles):
        (lat, lon), elapsed = profile.locate(mile * METERS_PER_MILE)
        start = 0.0 if i == 0 else (miles[i - 1] + mile) / 2
        end = total_mi if i == len(miles) - 1 else (mile + miles[i + 1]) / 2
        checkpoints.append(
            Checkpoint(
                index=i,
                mile=mile,
                lat=lat,
                lon=lon,
                eta=departure + timedelta(seconds=elapsed),
                elapsed_s=elapsed,
                start_mile=start,
                end_mile=end,
            )
        )
    return checkpoints
