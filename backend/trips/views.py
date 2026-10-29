import logging

from django.conf import settings
from django.http import FileResponse, HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .serializers import HeatmapRequestSerializer, PlanRequestSerializer
from .services import geocoding
from .services.geocoding import GeocodingError
from .services.heatmap import build_heatmap
from .services.planner import PlanRequest, plan_trip
from .services.routing import RoutingError
from .services.weather import StormScenario, WeatherUnavailable, get_provider

logger = logging.getLogger(__name__)


def _error(message: str, code: int) -> Response:
    return Response({"error": message}, status=code)


@api_view(["GET"])
def health(_request: Request) -> Response:
    return Response({"status": "ok"})


@api_view(["GET"])
def geocode(request: Request) -> Response:
    query = request.query_params.get("q", "")
    return Response({"results": [p.as_dict() for p in geocoding.search(query, limit=6)]})


@api_view(["POST"])
def plan(request: Request) -> Response:
    serializer = PlanRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        origin = geocoding.resolve(data["origin"]["query"], data["origin"].get("lat"), data["origin"].get("lon"))
        destination = geocoding.resolve(
            data["destination"]["query"], data["destination"].get("lat"), data["destination"].get("lon")
        )
        result = plan_trip(
            PlanRequest(
                origin=origin,
                destination=destination,
                departure=data["departure"],
                load_lb=data["load_weight_lb"],
                interval_mi=int(data["sample_interval_mi"]),
                weather_source=data["weather_source"],
            )
        )
    except GeocodingError as exc:
        return _error(str(exc), status.HTTP_400_BAD_REQUEST)
    except RoutingError as exc:
        return _error(str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY)
    except WeatherUnavailable as exc:
        logger.warning("Weather unavailable: %s", exc)
        return _error(f"{exc} Try again shortly, or use the simulated storm to explore the app.",
                      status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(result)


@api_view(["POST"])
def heatmap(request: Request) -> Response:
    serializer = HeatmapRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    scenario = StormScenario(**data["simulation"]) if data.get("simulation") else None
    try:
        result = build_heatmap(
            serializer.path_points(),
            data["departure"],
            data["load_weight_lb"],
            get_provider(data["weather_source"], scenario),
        )
    except WeatherUnavailable as exc:
        return _error(str(exc), status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(result)


def spa_index(_request):
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        return HttpResponse(
            "Frontend not built. Run `npm run build` in /frontend, or use the Vite dev server on :5173.",
            content_type="text/plain",
            status=404,
        )
    return FileResponse(index.open("rb"), content_type="text/html")
