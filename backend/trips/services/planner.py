"""Orchestrates a trip plan: routes → checkpoints with ETAs → weather → risk → recommendation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from django.conf import settings

from . import geo
from .checkpoints import Checkpoint, TruckProfile, sample_checkpoints
from .geocoding import Place
from .geo import METERS_PER_MILE
from .recommend import RouteSummary, explain, rank, summarize
from .risk import RiskLevel, assess
from .routing import Route, Router, get_route_options
from .weather import StormScenario, WeatherProvider, get_provider

ROUTE_IDS = "ABCDE"
GEOMETRY_TOLERANCE_DEG = 0.0003  # ~30 m; keeps the payload small without visible change


@dataclass
class PlanRequest:
    origin: Place
    destination: Place
    departure: datetime
    load_lb: float
    interval_mi: int
    weather_source: str = "live"


ProviderFactory = Callable[[str, StormScenario | None], WeatherProvider]


def storm_scenario_for(profile: TruckProfile, departure: datetime, origin: Place, destination: Place) -> StormScenario:
    """Place the demo storm so it peaks on the fastest route's midpoint as the truck gets there."""
    (lat, lon), elapsed = profile.locate(profile.distance_m / 2)
    radius = min(110.0, max(30.0, 0.10 * profile.distance_m / 1000))
    return StormScenario(
        lat=round(lat, 4),
        lon=round(lon, 4),
        peak_time=departure.timestamp() + elapsed,
        radius_km=round(radius, 1),
        trip_heading_deg=round(geo.initial_bearing_deg((origin.lat, origin.lon), (destination.lat, destination.lon)), 1),
    )


def _geometry(profile: TruckProfile) -> list[list[float]]:
    """Simplified polyline as ``[lat, lon, mile, elapsed_s]`` rows (for drawing and truck playback)."""
    keep = geo.simplify(profile.coords, GEOMETRY_TOLERANCE_DEG)
    return [
        [round(profile.coords[i][0], 5), round(profile.coords[i][1], 5),
         round(profile.cum_m[i] / METERS_PER_MILE, 2), round(profile.cum_s[i])]
        for i in keep
    ]


def _risk_segments(profile: TruckProfile, geometry: list[list[float]], checkpoints: list[Checkpoint],
                   levels: list[RiskLevel | None]) -> list[dict]:
    """Route split into consecutive stretches of equal risk, for colouring the selected route."""
    segments: list[dict] = []
    for cp, level in zip(checkpoints, levels):
        start, _ = profile.locate(cp.start_mile * METERS_PER_MILE)
        end, _ = profile.locate(cp.end_mile * METERS_PER_MILE)
        inner = [[g[0], g[1]] for g in geometry if cp.start_mile < g[2] < cp.end_mile]
        path = [[round(start[0], 5), round(start[1], 5)], *inner, [round(end[0], 5), round(end[1], 5)]]
        key = None if level is None else int(level)
        if segments and segments[-1]["level"] == key:
            segments[-1]["path"].extend(path[1:])
        else:
            segments.append({"level": key, "path": path})
    return segments


def plan_trip(
    req: PlanRequest,
    router: Router | None = None,
    provider_factory: ProviderFactory = get_provider,
) -> dict:
    cfg = settings.TRUCK_ROUTING
    origin_ll = (req.origin.lat, req.origin.lon)
    dest_ll = (req.destination.lat, req.destination.lon)
    routes, warnings = get_route_options(origin_ll, dest_ll, router=router)

    profiles = [TruckProfile.from_route(r, cfg["TRUCK_MAX_SPEED_MPH"]) for r in routes]
    checkpoint_sets = [sample_checkpoints(p, req.departure, req.interval_mi) for p in profiles]

    scenario = None
    if req.weather_source == "simulated":
        scenario = storm_scenario_for(profiles[0], req.departure, req.origin, req.destination)
    provider = provider_factory(req.weather_source, scenario)

    # One weather lookup per distinct location (routes share their first and last miles).
    def key(cp: Checkpoint) -> tuple[float, float]:
        return round(cp.lat, 3), round(cp.lon, 3)

    unique = list(dict.fromkeys(key(cp) for cps in checkpoint_sets for cp in cps))
    latest_eta = max(cps[-1].eta for cps in checkpoint_sets)
    series_list = provider.hourly(unique, req.departure, latest_eta)
    series_by_key = dict(zip(unique, series_list))

    route_payloads: list[dict] = []
    summaries: list[RouteSummary] = []
    unknown_count = 0
    for idx, (route, profile, cps) in enumerate(zip(routes, profiles, checkpoint_sets)):
        route_id = ROUTE_IDS[idx]
        label = f"Route {route_id}"
        levels: list[RiskLevel | None] = []
        cp_payloads = []
        for cp in cps:
            series = series_by_key.get(key(cp))
            sample = series.at(cp.eta.timestamp()) if series else None
            risk = assess(sample, req.load_lb) if sample else None
            levels.append(risk.level if risk else None)
            unknown_count += risk is None
            cp_payloads.append({
                "index": cp.index,
                "mile": round(cp.mile, 1),
                "lat": round(cp.lat, 5),
                "lon": round(cp.lon, 5),
                "eta": cp.eta.isoformat(timespec="seconds"),
                "elapsed_s": round(cp.elapsed_s),
                "represents": [round(cp.start_mile, 1), round(cp.end_mile, 1)],
                "weather": None if sample is None else {
                    "wind_mph": sample.wind_mph,
                    "gust_mph": sample.gust_mph,
                    "rain_in_hr": sample.rain_in_hr,
                    "snow_in_hr": sample.snow_in_hr,
                    "temp_f": sample.temp_f,
                },
                "risk": None if risk is None else risk.as_dict(),
            })
        distance_mi = profile.distance_m / METERS_PER_MILE
        summary = summarize(route_id, label, cps, levels, distance_mi, profile.duration_s)
        summaries.append(summary)
        geometry = _geometry(profile)
        route_payloads.append({
            "id": route_id,
            "label": label,
            "via": route.summary,
            "source": route.source,
            "departure": req.departure.isoformat(timespec="seconds"),
            "arrival": cps[-1].eta.isoformat(timespec="seconds"),
            "geometry": geometry,
            "risk_segments": _risk_segments(profile, geometry, cps, levels),
            "checkpoints": cp_payloads,
            "summary": summary.as_dict(),
        })

    ranked = rank(summaries)
    best = ranked[0]
    order = {s.route_id: i + 1 for i, s in enumerate(ranked)}
    for payload in route_payloads:
        payload["rank"] = order[payload["id"]]
        payload["recommended"] = payload["id"] == best.route_id

    if unknown_count:
        warnings.append(
            f"{unknown_count} checkpoint(s) fall outside the available forecast and are shown as unknown."
        )

    return {
        "origin": req.origin.as_dict(),
        "destination": req.destination.as_dict(),
        "departure": req.departure.isoformat(timespec="seconds"),
        "load_weight_lb": req.load_lb,
        "sample_interval_mi": req.interval_mi,
        "weather_source": req.weather_source,
        "simulation": scenario.as_dict() if scenario else None,
        "truck_max_speed_mph": cfg["TRUCK_MAX_SPEED_MPH"],
        "routes": route_payloads,
        "recommendation": {
            "route_id": best.route_id,
            "ranking": [s.route_id for s in ranked],
            "reasons": explain(best, [s for s in ranked if s is not best]),
        },
        "warnings": warnings,
    }
