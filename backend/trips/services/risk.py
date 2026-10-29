"""Weather risk classification — a direct encoding of the assessment's risk and load rules.

Levels are ordered integers so "worst of" is simply ``max``:

    0 Low · 1 Moderate · 2 High · 3 Severe · 4 No Travel

Boundary handling (the brief's ranges share their edges, e.g. rain "0.10–0.25" and "0.25–0.50"):
each band includes its lower edge and excludes its upper edge, except where the brief uses
an explicit strict ``>`` for No Travel (rain > 1.00, snow > 3.0), in which case the Severe band
includes 1.00 / 3.0. Wind uses the brief's integer bands, so 34.9 mph is Moderate and 35.0 is High.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return RISK_LABELS[self]

    @property
    def key(self) -> str:
        return self.name.lower()


RISK_LABELS = {
    RiskLevel.LOW: "Low",
    RiskLevel.MODERATE: "Moderate",
    RiskLevel.HIGH: "High",
    RiskLevel.SEVERE: "Severe",
    RiskLevel.NO_TRAVEL: "No Travel",
}

# Lower edges of Moderate, High, Severe and No Travel.
WIND_MPH_THRESHOLDS = (25.0, 35.0, 45.0, 55.0)
RAIN_IN_HR_THRESHOLDS = (0.10, 0.25, 0.50, 1.00)
SNOW_IN_HR_THRESHOLDS = (0.5, 1.0, 2.0, 3.0)

# Load rules (lb). Strictly greater than, as written in the brief.
HEAVY_LOAD_NO_TRAVEL_LB = 30_000  # 45–54 mph + >30,000 lb → No Travel
HEAVY_LOAD_SEVERE_LB = 40_000  # 35–44 mph + >40,000 lb → Severe


def _band(value: float, thresholds: tuple[float, float, float, float], strict_top: bool) -> RiskLevel:
    moderate, high, severe, no_travel = thresholds
    if value < moderate:
        return RiskLevel.LOW
    if value < high:
        return RiskLevel.MODERATE
    if value < severe:
        return RiskLevel.HIGH
    if value < no_travel or (strict_top and value == no_travel):
        return RiskLevel.SEVERE
    return RiskLevel.NO_TRAVEL


def classify_wind(mph: float) -> RiskLevel:
    return _band(mph, WIND_MPH_THRESHOLDS, strict_top=False)  # ≥55 mph is No Travel


def classify_rain(in_per_hr: float) -> RiskLevel:
    return _band(in_per_hr, RAIN_IN_HR_THRESHOLDS, strict_top=True)  # >1.00 is No Travel


def classify_snow(in_per_hr: float) -> RiskLevel:
    return _band(in_per_hr, SNOW_IN_HR_THRESHOLDS, strict_top=True)  # >3.0 is No Travel


def apply_load_rules(wind_mph: float, load_lb: float) -> tuple[RiskLevel, str | None]:
    """Wind level after load rules, plus a human-readable note when a load rule escalated it."""
    base = classify_wind(wind_mph)
    if wind_mph >= WIND_MPH_THRESHOLDS[3]:
        return RiskLevel.NO_TRAVEL, None  # No Travel for any load
    if wind_mph >= WIND_MPH_THRESHOLDS[2] and load_lb > HEAVY_LOAD_NO_TRAVEL_LB:
        return RiskLevel.NO_TRAVEL, "45–54 mph wind with load over 30,000 lb → No Travel"
    if wind_mph >= WIND_MPH_THRESHOLDS[1] and load_lb > HEAVY_LOAD_SEVERE_LB:
        return RiskLevel.SEVERE, "35–44 mph wind with load over 40,000 lb → Severe"
    return base, None


@dataclass(frozen=True)
class WeatherSample:
    wind_mph: float
    gust_mph: float | None
    rain_in_hr: float
    snow_in_hr: float
    temp_f: float | None = None


@dataclass
class RiskAssessment:
    level: RiskLevel
    wind: RiskLevel
    rain: RiskLevel
    snow: RiskLevel
    load_rule: str | None = None
    drivers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "level": int(self.level),
            "label": self.level.label,
            "factors": {"wind": int(self.wind), "rain": int(self.rain), "snow": int(self.snow)},
            "drivers": self.drivers,
            "load_rule": self.load_rule,
        }


def assess(sample: WeatherSample, load_lb: float) -> RiskAssessment:
    """Overall checkpoint risk = worst of wind (with load rules), rain and snow."""
    wind, load_rule = apply_load_rules(sample.wind_mph, load_lb)
    rain = classify_rain(sample.rain_in_hr)
    snow = classify_snow(sample.snow_in_hr)
    level = max(wind, rain, snow)
    drivers = []
    if level > RiskLevel.LOW:
        drivers = [name for name, lvl in (("wind", wind), ("rain", rain), ("snow", snow)) if lvl == level]
    return RiskAssessment(level=level, wind=wind, rain=rain, snow=snow, load_rule=load_rule, drivers=drivers)


def _continuous(value: float, thresholds: tuple[float, float, float, float]) -> float:
    """Map a raw value onto a smooth 0–4 scale that agrees with the discrete bands at their edges."""
    edges = (0.0, *thresholds)
    for i in range(1, len(edges)):
        if value < edges[i]:
            return (i - 1) + (value - edges[i - 1]) / (edges[i] - edges[i - 1])
    return 4.0


def continuous_score(sample: WeatherSample, load_lb: float) -> float:
    """Smooth 0–4 risk used only for heatmap shading; never lower than the discrete level."""
    level = assess(sample, load_lb).level
    smooth = max(
        _continuous(sample.wind_mph, WIND_MPH_THRESHOLDS),
        _continuous(sample.rain_in_hr, RAIN_IN_HR_THRESHOLDS),
        _continuous(sample.snow_in_hr, SNOW_IN_HR_THRESHOLDS),
    )
    return round(min(4.0, max(smooth, float(level))), 2)
