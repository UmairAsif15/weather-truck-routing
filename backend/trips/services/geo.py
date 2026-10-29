"""Small, dependency-free geodesy helpers.

All coordinates are ``(lat, lon)`` tuples in decimal degrees.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

EARTH_RADIUS_M = 6_371_008.8
METERS_PER_MILE = 1609.344
METERS_PER_KM = 1000.0

LatLon = tuple[float, float]


def haversine_m(a: LatLon, b: LatLon) -> float:
    """Great-circle distance between two points, in metres."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def lerp(a: LatLon, b: LatLon, fraction: float) -> LatLon:
    """Linear interpolation; accurate enough for road-segment-sized spans."""
    return (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)


def initial_bearing_deg(a: LatLon, b: LatLon) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination_point(origin: LatLon, bearing_deg: float, distance_m: float) -> LatLon:
    """Point reached by travelling ``distance_m`` from ``origin`` on ``bearing_deg``."""
    lat1, lon1 = map(math.radians, origin)
    brng = math.radians(bearing_deg)
    delta = distance_m / EARTH_RADIUS_M
    lat2 = math.asin(
        math.sin(lat1) * math.cos(delta) + math.cos(lat1) * math.sin(delta) * math.cos(brng)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(delta) * math.cos(lat1),
        math.cos(delta) - math.sin(lat1) * math.sin(lat2),
    )
    return (math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180)


def cumulative_distances_m(points: Sequence[LatLon]) -> list[float]:
    out = [0.0]
    for i in range(1, len(points)):
        out.append(out[-1] + haversine_m(points[i - 1], points[i]))
    return out


def point_at_distance(points: Sequence[LatLon], cumulative: Sequence[float], target_m: float) -> LatLon:
    """Interpolated point ``target_m`` metres along a polyline (clamped to its ends)."""
    if target_m <= 0:
        return points[0]
    if target_m >= cumulative[-1]:
        return points[-1]
    lo, hi = 0, len(cumulative) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if cumulative[mid] <= target_m:
            lo = mid
        else:
            hi = mid
    span = cumulative[hi] - cumulative[lo]
    fraction = 0.0 if span == 0 else (target_m - cumulative[lo]) / span
    return lerp(points[lo], points[hi], fraction)


def resample(points: Sequence[LatLon], step_m: float) -> list[LatLon]:
    """Evenly spaced points along a polyline, always including both ends."""
    if len(points) < 2:
        return list(points)
    cumulative = cumulative_distances_m(points)
    total = cumulative[-1]
    if total == 0:
        return [points[0]]
    count = max(1, int(total // step_m))
    out = [point_at_distance(points, cumulative, i * step_m) for i in range(count + 1)]
    if cumulative[-1] - count * step_m > 1:
        out.append(points[-1])
    return out


def simplify(points: Sequence[LatLon], tolerance_deg: float) -> list[int]:
    """Ramer–Douglas–Peucker simplification. Returns the indices of kept points."""
    n = len(points)
    if n <= 2:
        return list(range(n))
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    tol2 = tolerance_deg * tolerance_deg
    while stack:
        start, end = stack.pop()
        ax, ay = points[start][1], points[start][0]
        bx, by = points[end][1], points[end][0]
        dx, dy = bx - ax, by - ay
        seg_len2 = dx * dx + dy * dy
        max_d2, index = -1.0, -1
        for i in range(start + 1, end):
            px, py = points[i][1], points[i][0]
            if seg_len2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
                d2 = (px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2
            if d2 > max_d2:
                max_d2, index = d2, i
        if max_d2 > tol2 and index > 0:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return [i for i, k in enumerate(keep) if k]


def bbox(points: Iterable[LatLon]) -> tuple[float, float, float, float]:
    """Return ``(south, west, north, east)``."""
    lats, lons = zip(*points)
    return min(lats), min(lons), max(lats), max(lons)


# --- Web Mercator ---------------------------------------------------------------------------
# The heatmap grid is regular in Web Mercator so it aligns exactly with a Leaflet image overlay.

def lat_to_mercator_y(lat: float) -> float:
    lat = max(-85.0511, min(85.0511, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def mercator_y_to_lat(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


class SpatialIndex:
    """Uniform-grid hash for fast "is any point within r metres" queries."""

    def __init__(self, points: Sequence[LatLon], cell_deg: float):
        self.cell = cell_deg
        self.buckets: dict[tuple[int, int], list[LatLon]] = {}
        for p in points:
            self.buckets.setdefault(self._key(p), []).append(p)

    def _key(self, p: LatLon) -> tuple[int, int]:
        return int(math.floor(p[0] / self.cell)), int(math.floor(p[1] / self.cell))

    def nearest_m(self, p: LatLon, rings: int = 1) -> float:
        """Distance to the nearest indexed point within ``rings`` neighbouring cells (inf if none)."""
        ky, kx = self._key(p)
        best = math.inf
        for dy in range(-rings, rings + 1):
            for dx in range(-rings, rings + 1):
                for q in self.buckets.get((ky + dy, kx + dx), ()):
                    d = haversine_m(p, q)
                    if d < best:
                        best = d
        return best


def overlap_ratio(a: Sequence[LatLon], b: Sequence[LatLon], within_m: float = 400.0) -> float:
    """Share of polyline ``a`` (by length) that lies within ``within_m`` of polyline ``b``."""
    sa = resample(a, 1000.0)
    sb = resample(b, 250.0)
    if not sa or not sb:
        return 0.0
    index = SpatialIndex(sb, cell_deg=0.01)
    close = sum(1 for p in sa if index.nearest_m(p) <= within_m)
    return close / len(sa)


def has_backtrack(points: Sequence[LatLon], revisit_after_m: float = 3000.0) -> bool:
    """Detect out-and-back spurs: the path returns to a spot it left kilometres earlier."""
    samples = resample(points, 250.0)
    cell = 0.002  # ~200 m
    first_seen: dict[tuple[int, int], int] = {}
    step_index_gap = int(revisit_after_m / 250.0)
    for i, (lat, lon) in enumerate(samples):
        key = (int(math.floor(lat / cell)), int(math.floor(lon / cell)))
        seen = first_seen.get(key)
        if seen is None:
            first_seen[key] = i
        elif i - seen > step_index_gap:
            return True
    return False
