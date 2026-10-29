"""Place search: Photon (OSM, autocomplete-friendly) with Open-Meteo's city geocoder as fallback."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from .http import get_session, timeout

logger = logging.getLogger(__name__)


class GeocodingError(Exception):
    pass


@dataclass(frozen=True)
class Place:
    label: str
    lat: float
    lon: float

    def as_dict(self) -> dict:
        return asdict(self)


def _photon(query: str, limit: int) -> list[Place]:
    url = settings.TRUCK_ROUTING["PHOTON_URL"].rstrip("/") + "/api/"
    resp = get_session().get(url, params={"q": query, "limit": limit, "lang": "en"}, timeout=timeout())
    resp.raise_for_status()
    places = []
    for feature in resp.json().get("features", []):
        props = feature.get("properties", {})
        lon, lat = feature["geometry"]["coordinates"][:2]
        street = " ".join(filter(None, [props.get("housenumber"), props.get("street")]))
        parts = [props.get("name") or street, props.get("city"), props.get("state"), props.get("country")]
        label = ", ".join(dict.fromkeys(p for p in parts if p))  # dedupe, keep order
        places.append(Place(label=label or query, lat=float(lat), lon=float(lon)))
    return places


def _open_meteo(query: str, limit: int) -> list[Place]:
    url = settings.TRUCK_ROUTING["OPEN_METEO_GEOCODING_URL"].rstrip("/") + "/v1/search"
    resp = get_session().get(url, params={"name": query, "count": limit, "language": "en"}, timeout=timeout())
    resp.raise_for_status()
    places = []
    for r in resp.json().get("results", []) or []:
        parts = [r.get("name"), r.get("admin1"), r.get("country")]
        places.append(Place(label=", ".join(p for p in parts if p), lat=r["latitude"], lon=r["longitude"]))
    return places


def search(query: str, limit: int = 5) -> list[Place]:
    query = query.strip()
    if len(query) < 2:
        return []
    cache_key = f"geocode:v1:{limit}:{query.lower()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return [Place(**p) for p in cached]

    places: list[Place] = []
    for provider in (_photon, _open_meteo):
        try:
            places = provider(query, limit)
        except (requests.RequestException, KeyError, ValueError) as exc:
            logger.warning("Geocoder %s failed for %r: %s", provider.__name__, query, exc)
            continue
        if places:
            break
    cache.set(cache_key, [p.as_dict() for p in places], 60 * 60 * 24)
    return places


def resolve(query: str, lat: float | None = None, lon: float | None = None) -> Place:
    """Use client-provided coordinates when present, otherwise geocode the free text."""
    if lat is not None and lon is not None:
        return Place(label=query.strip() or f"{lat:.4f}, {lon:.4f}", lat=lat, lon=lon)
    results = search(query, limit=1)
    if not results:
        raise GeocodingError(f'Could not find a location for "{query}".')
    return results[0]
