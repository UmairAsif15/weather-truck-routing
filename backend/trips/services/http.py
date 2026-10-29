"""Shared HTTP session with sane retries and timeouts for third-party APIs."""
from __future__ import annotations

from functools import lru_cache

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@lru_cache(maxsize=1)
def get_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = settings.TRUCK_ROUTING["USER_AGENT"]
    return session


def timeout() -> float:
    return settings.TRUCK_ROUTING["HTTP_TIMEOUT_S"]
