"""Route options from OSRM.

OSRM's ``alternatives`` frequently returns fewer than three routes, so missing options are
filled by routing through a via-point pushed sideways off the fastest route. Candidates that
are near-duplicates, unreasonably long, or contain out-and-back spurs are rejected.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import requests
from django.conf import settings

from . import geo
from .geo import LatLon
from .http import get_session, timeout

logger = logging.getLogger(__name__)


class RoutingError(Exception):
    pass


@dataclass
class Route:
    coords: list[LatLon]
    seg_distance_m: list[float]
    seg_duration_s: list[float]
    summary: str = ""
    source: str = "osrm"
    notes: list[str] = field(default_factory=list)

    @property
    def distance_m(self) -> float:
        return sum(self.seg_distance_m)

    @property
    def duration_s(self) -> float:
        return sum(self.seg_duration_s)


class Router(Protocol):
    def route(self, waypoints: Sequence[LatLon], alternatives: int = 0) -> list[Route]: ...


class OSRMRouter:
    """Client for the OSRM HTTP API (public demo server by default)."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.TRUCK_ROUTING["OSRM_URL"]).rstrip("/")

    def route(self, waypoints: Sequence[LatLon], alternatives: int = 0) -> list[Route]:
        coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
        params = {
            "overview": "full",
            "geometries": "geojson",
            "annotations": "distance,duration",
            "steps": "true",  # required for the human-readable leg summary ("I 40, US 287")
            "alternatives": str(alternatives) if alternatives else "false",
        }
        try:
            resp = get_session().get(f"{self.base_url}/route/v1/driving/{coords}", params=params, timeout=timeout())
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise RoutingError(f"Routing service unavailable: {exc}") from exc
        if data.get("code") != "Ok":
            raise RoutingError(data.get("message") or f"Routing failed ({data.get('code', resp.status_code)}).")
        return [self._parse(r) for r in data.get("routes", [])]

    @staticmethod
    def _parse(raw: dict) -> Route:
        coords = [(lat, lon) for lon, lat in raw["geometry"]["coordinates"]]
        dist: list[float] = []
        dur: list[float] = []
        for leg in raw["legs"]:
            ann = leg.get("annotation") or {}
            dist.extend(ann.get("distance", []))
            dur.extend(ann.get("duration", []))
        if len(dist) != len(coords) - 1 or len(dur) != len(coords) - 1:
            # Fallback: spread the total duration proportionally to geometric distance.
            dist = [geo.haversine_m(coords[i], coords[i + 1]) for i in range(len(coords) - 1)]
            total = sum(dist) or 1.0
            dur = [raw["duration"] * d / total for d in dist]
        summary = ", ".join(dict.fromkeys(s for leg in raw["legs"] for s in leg.get("summary", "").split(", ") if s))
        return Route(coords=coords, seg_distance_m=dist, seg_duration_s=dur, summary=summary)


def _is_distinct(candidate: Route, accepted: list[Route], max_overlap: float = 0.8) -> bool:
    for other in accepted:
        if geo.overlap_ratio(candidate.coords, other.coords) > max_overlap:
            return False
        if geo.overlap_ratio(other.coords, candidate.coords) > max_overlap:
            return False
    return True


def _via_candidates(base: Route, origin: LatLon, destination: LatLon) -> list[LatLon]:
    """Via-points offset perpendicular to the trip, at the middle and the thirds of the route."""
    straight_m = geo.haversine_m(origin, destination)
    heading = geo.initial_bearing_deg(origin, destination)
    cumulative = geo.cumulative_distances_m(base.coords)
    vias = []
    for fraction, offset in ((0.5, 0.12), (0.5, -0.12), (0.5, 0.22), (0.5, -0.22), (0.35, 0.18), (0.65, -0.18)):
        anchor = geo.point_at_distance(base.coords, cumulative, cumulative[-1] * fraction)
        side = heading + (90 if offset > 0 else -90)
        vias.append(geo.destination_point(anchor, side, abs(offset) * straight_m))
    return vias


def get_route_options(
    origin: LatLon,
    destination: LatLon,
    count: int | None = None,
    router: Router | None = None,
    max_attempts: int = 6,
) -> tuple[list[Route], list[str]]:
    """Return up to ``count`` distinct routes (fastest first) and any user-facing warnings."""
    count = count or settings.TRUCK_ROUTING["ROUTE_OPTIONS"]
    max_ratio = settings.TRUCK_ROUTING["MAX_DETOUR_RATIO"]
    router = router or OSRMRouter()
    warnings: list[str] = []

    if geo.haversine_m(origin, destination) < 1000:
        raise RoutingError("Origin and destination are less than 1 km apart.")

    found = router.route([origin, destination], alternatives=count)
    if not found:
        raise RoutingError("No drivable route found between these locations.")
    found.sort(key=lambda r: r.duration_s)
    fastest = found[0]
    fastest.source = "osrm"
    accepted = [fastest]
    for alt in found[1:]:
        if len(accepted) < count and _is_distinct(alt, accepted):
            alt.source = "osrm-alternative"
            accepted.append(alt)

    if len(accepted) < count:
        for via in _via_candidates(fastest, origin, destination)[:max_attempts]:
            try:
                candidates = router.route([origin, via, destination])
            except RoutingError as exc:
                logger.info("Via-route attempt failed: %s", exc)
                continue
            if not candidates:
                continue
            cand = candidates[0]
            if cand.duration_s > fastest.duration_s * max_ratio or cand.distance_m > fastest.distance_m * max_ratio:
                continue
            if geo.has_backtrack(cand.coords) or not _is_distinct(cand, accepted):
                continue
            cand.source = "via-point"
            accepted.append(cand)
            if len(accepted) == count:
                break

    if len(accepted) < count:
        warnings.append(
            f"Only {len(accepted)} distinct practical route(s) exist between these points; "
            "other candidates were near-duplicates or excessive detours."
        )
    return accepted, warnings
