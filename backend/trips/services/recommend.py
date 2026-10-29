"""Route summaries and the recommendation ranking.

The brief's preference order, applied lexicographically:

    1. fewest Severe miles  2. fewest High miles  3. lowest average risk  4. shortest travel time

No Travel is worse than Severe, so "No Travel miles" is checked first: a route that drives
through No Travel conditions never beats one that doesn't. Small tolerances stop rounding
noise (e.g. 0.3 mile) from overriding a meaningful travel-time difference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cmp_to_key
from typing import Callable

from .checkpoints import Checkpoint
from .risk import RiskLevel

MILE_TOLERANCE = 1.0
AVG_RISK_TOLERANCE = 0.02


@dataclass
class RouteSummary:
    route_id: str
    label: str
    distance_mi: float
    duration_s: float
    miles_by_level: dict[str, float] = field(default_factory=dict)
    unknown_miles: float = 0.0
    avg_risk: float | None = None
    max_level: int | None = None

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level.get("no_travel", 0.0)

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level.get("severe", 0.0)

    @property
    def high_miles(self) -> float:
        return self.miles_by_level.get("high", 0.0)

    def as_dict(self) -> dict:
        return {
            "distance_mi": round(self.distance_mi, 1),
            "duration_s": round(self.duration_s),
            "miles_by_level": {k: round(v, 1) for k, v in self.miles_by_level.items()},
            "unknown_miles": round(self.unknown_miles, 1),
            "no_travel_miles": round(self.no_travel_miles, 1),
            "severe_miles": round(self.severe_miles, 1),
            "high_miles": round(self.high_miles, 1),
            "avg_risk": None if self.avg_risk is None else round(self.avg_risk, 3),
            "max_level": self.max_level,
        }


def summarize(
    route_id: str,
    label: str,
    checkpoints: list[Checkpoint],
    levels: list[RiskLevel | None],
    distance_mi: float,
    duration_s: float,
) -> RouteSummary:
    """Each checkpoint's level applies to the stretch of road it represents."""
    miles = {lvl.key: 0.0 for lvl in RiskLevel}
    unknown = 0.0
    weighted = 0.0
    for cp, level in zip(checkpoints, levels):
        if level is None:
            unknown += cp.represented_miles
            continue
        miles[level.key] += cp.represented_miles
        weighted += int(level) * cp.represented_miles
    known = distance_mi - unknown
    known_levels = [int(lvl) for lvl in levels if lvl is not None]
    return RouteSummary(
        route_id=route_id,
        label=label,
        distance_mi=distance_mi,
        duration_s=duration_s,
        miles_by_level=miles,
        unknown_miles=unknown,
        avg_risk=(weighted / known) if known > 0 else None,
        max_level=max(known_levels) if known_levels else None,
    )


@dataclass(frozen=True)
class Criterion:
    key: str
    getter: Callable[[RouteSummary], float]
    tolerance: float
    describe: Callable[[RouteSummary, RouteSummary], str]


def _mi(v: float) -> str:
    if v == 0 or v >= 10:
        return f"{v:.0f} mi"
    return f"{v:.1f} mi"


def _duration(seconds: float) -> str:
    minutes = round(abs(seconds) / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "no_travel_miles", lambda s: s.no_travel_miles, MILE_TOLERANCE,
        lambda a, b: f"avoids No Travel conditions ({_mi(a.no_travel_miles)} vs {_mi(b.no_travel_miles)} on {b.label})",
    ),
    Criterion(
        "severe_miles", lambda s: s.severe_miles, MILE_TOLERANCE,
        lambda a, b: f"fewer Severe miles ({_mi(a.severe_miles)} vs {_mi(b.severe_miles)} on {b.label})",
    ),
    Criterion(
        "high_miles", lambda s: s.high_miles, MILE_TOLERANCE,
        lambda a, b: f"fewer High-risk miles ({_mi(a.high_miles)} vs {_mi(b.high_miles)} on {b.label})",
    ),
    Criterion(
        "avg_risk", lambda s: s.avg_risk if s.avg_risk is not None else 99.0, AVG_RISK_TOLERANCE,
        lambda a, b: f"lower average risk ({a.avg_risk:.2f} vs {b.avg_risk:.2f} on {b.label})",
    ),
    Criterion(
        "duration_s", lambda s: s.duration_s, 0.0,
        lambda a, b: f"similar weather exposure to {b.label} but {_duration(b.duration_s - a.duration_s)} faster",
    ),
)


def deciding_criterion(a: RouteSummary, b: RouteSummary) -> tuple[Criterion | None, int]:
    """First criterion separating ``a`` and ``b`` beyond its tolerance, and which side wins (-1 → a)."""
    for crit in CRITERIA:
        diff = crit.getter(a) - crit.getter(b)
        if abs(diff) > crit.tolerance:
            return crit, (-1 if diff < 0 else 1)
    return None, 0


def compare(a: RouteSummary, b: RouteSummary) -> int:
    return deciding_criterion(a, b)[1]


def rank(summaries: list[RouteSummary]) -> list[RouteSummary]:
    """Best route first. Ties keep the router's order (fastest first)."""
    return sorted(summaries, key=cmp_to_key(compare))


def explain(best: RouteSummary, others: list[RouteSummary]) -> list[str]:
    reasons: list[str] = []
    if (best.max_level or 0) <= RiskLevel.MODERATE and best.unknown_miles == 0:
        reasons.append("No High, Severe or No Travel weather along the way.")
    elif best.no_travel_miles > 0:
        reasons.append(
            "Every option crosses No Travel conditions — consider delaying departure. "
            "This is the least-bad option."
        )
    for other in others:
        crit, winner = deciding_criterion(best, other)
        if crit is None:
            reasons.append(f"Equivalent to {other.label} on weather and travel time.")
        elif winner == -1:
            text = crit.describe(best, other)
            reasons.append(text[0].upper() + text[1:] + ".")
    return reasons
