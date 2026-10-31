"""
Django settings for the Weather-Aware Truck Routing API.

Everything deployment-specific is read from environment variables so the same
image runs locally, in Docker and on Render without code changes.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
# Hosting platforms that publish the service's public hostname: Render, Hugging Face Spaces.
for platform_host in (os.environ.get("RENDER_EXTERNAL_HOSTNAME"), os.environ.get("SPACE_HOST")):
    if platform_host:
        ALLOWED_HOSTS.append(platform_host)
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host not in {"localhost", "127.0.0.1", "*"}]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "trips",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

# The API is stateless; a database is not required. SQLite keeps Django happy.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Shared on-disk cache so every gunicorn worker reuses geocoding/weather responses.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": os.environ.get("CACHE_DIR", "/tmp/truck-routing-cache"),
        "TIMEOUT": 60 * 30,
        "OPTIONS": {"MAX_ENTRIES": 20000},
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

# --- Static files / single-page app -------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))
# WhiteNoise serves the built React app (index.html, /assets/*) from the site root.
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None
WHITENOISE_MAX_AGE = 60 * 60

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- API ------------------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")

# --- Third-party providers & domain tuning ----------------------------------------------------
TRUCK_ROUTING = {
    "OSRM_URL": os.environ.get("OSRM_URL", "https://router.project-osrm.org"),
    "PHOTON_URL": os.environ.get("PHOTON_URL", "https://photon.komoot.io"),
    "OPEN_METEO_GEOCODING_URL": os.environ.get(
        "OPEN_METEO_GEOCODING_URL", "https://geocoding-api.open-meteo.com"
    ),
    "OPEN_METEO_URL": os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com"),
    "OPEN_METEO_API_KEY": os.environ.get("OPEN_METEO_API_KEY", ""),
    "USER_AGENT": os.environ.get(
        "HTTP_USER_AGENT", "WeatherAwareTruckRouting/1.0 (+https://github.com/)"
    ),
    "HTTP_TIMEOUT_S": float(os.environ.get("HTTP_TIMEOUT_S", "20")),
    # OSRM's public server routes for cars; trucks are governed to a lower top speed.
    "TRUCK_MAX_SPEED_MPH": float(os.environ.get("TRUCK_MAX_SPEED_MPH", "65")),
    "ROUTE_OPTIONS": 3,
    # Alternative routes longer than this multiple of the fastest one are rejected.
    "MAX_DETOUR_RATIO": float(os.environ.get("MAX_DETOUR_RATIO", "1.6")),
    "HEATMAP_HOURS": 48,
    "HEATMAP_MAX_POINTS": int(os.environ.get("HEATMAP_MAX_POINTS", "180")),
    "HEATMAP_CORRIDOR_KM": float(os.environ.get("HEATMAP_CORRIDOR_KM", "60")),
    "WEATHER_CACHE_S": int(os.environ.get("WEATHER_CACHE_S", str(30 * 60))),
    "MAX_DAYS_AHEAD": 14,
}

# Django's default ("same-origin") strips the Referer from cross-origin requests, and the
# OSM tile servers block tile requests without one. Send just the origin instead.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True
