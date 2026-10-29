from datetime import datetime, timedelta, timezone

from django.conf import settings
from rest_framework import serializers

from .services.weather import StormScenario

WEATHER_SOURCES = ("live", "simulated")


class LocationSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")
    lat = serializers.FloatField(min_value=-90, max_value=90, required=False, allow_null=True)
    lon = serializers.FloatField(min_value=-180, max_value=180, required=False, allow_null=True)

    def validate(self, attrs):
        has_coords = attrs.get("lat") is not None and attrs.get("lon") is not None
        if not has_coords and not attrs.get("query", "").strip():
            raise serializers.ValidationError("Enter a place name or pick a suggestion.")
        return attrs


def _validate_departure(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if value < now - timedelta(hours=1):
        raise serializers.ValidationError("Departure can't be in the past.")
    if value > now + timedelta(days=settings.TRUCK_ROUTING["MAX_DAYS_AHEAD"]):
        raise serializers.ValidationError(
            f"Departure must be within {settings.TRUCK_ROUTING['MAX_DAYS_AHEAD']} days — forecasts don't reach further."
        )
    return value


class PlanRequestSerializer(serializers.Serializer):
    origin = LocationSerializer()
    destination = LocationSerializer()
    departure = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=200_000)
    sample_interval_mi = serializers.ChoiceField(choices=(10, 25, 50), default=25)
    weather_source = serializers.ChoiceField(choices=WEATHER_SOURCES, default="live")

    def validate_departure(self, value):
        return _validate_departure(value)


class LatLonListField(serializers.ListField):
    child = serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=4)


class StormScenarioSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    peak_time = serializers.FloatField()
    radius_km = serializers.FloatField(min_value=1, max_value=500)
    trip_heading_deg = serializers.FloatField()
    speed_kmh = serializers.FloatField(required=False, default=30.0)

    def to_scenario(self) -> StormScenario:
        return StormScenario(**self.validated_data)


class HeatmapRequestSerializer(serializers.Serializer):
    paths = serializers.ListField(child=LatLonListField(min_length=2, max_length=5000), min_length=1, max_length=5)
    departure = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=200_000)
    weather_source = serializers.ChoiceField(choices=WEATHER_SOURCES, default="live")
    simulation = StormScenarioSerializer(required=False, allow_null=True)

    def validate_departure(self, value):
        return _validate_departure(value)

    def validate(self, attrs):
        if attrs["weather_source"] == "simulated" and not attrs.get("simulation"):
            raise serializers.ValidationError({"simulation": "Required for simulated weather."})
        return attrs

    def path_points(self) -> list[list[tuple[float, float]]]:
        return [[(p[0], p[1]) for p in path] for path in self.validated_data["paths"]]

