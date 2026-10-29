from datetime import datetime, timezone

from django.test import SimpleTestCase

from trips.services.checkpoints import TruckProfile, sample_checkpoints
from trips.services.geo import METERS_PER_MILE
from trips.services.weather import HourlySeries, parse_open_meteo_location

from .fakes import line, straight_route

DEPARTURE = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)


class TruckProfileTests(SimpleTestCase):
    def test_car_speed_is_capped_to_truck_speed(self):
        route = straight_route(line((35.0, -100.0), (35.0, -98.0)), speed_mph=80)
        profile = TruckProfile.from_route(route, max_speed_mph=65)
        miles = profile.distance_m / METERS_PER_MILE
        self.assertAlmostEqual(profile.duration_s / 3600, miles / 65, places=3)

    def test_slow_segments_are_kept(self):
        route = straight_route(line((35.0, -100.0), (35.0, -99.5)), speed_mph=30)
        profile = TruckProfile.from_route(route, max_speed_mph=65)
        self.assertAlmostEqual(profile.duration_s, route.duration_s, places=3)


class CheckpointTests(SimpleTestCase):
    def setUp(self):
        route = straight_route(line((35.0, -100.0), (35.0, -97.0), n=200), speed_mph=60)
        self.profile = TruckProfile.from_route(route, max_speed_mph=65)
        self.total_mi = self.profile.distance_m / METERS_PER_MILE  # ≈ 169.8 mi

    def test_spacing_includes_origin_and_destination(self):
        for interval in (10, 25, 50):
            cps = sample_checkpoints(self.profile, DEPARTURE, interval)
            miles = [cp.mile for cp in cps]
            self.assertEqual(miles[0], 0)
            self.assertAlmostEqual(miles[-1], self.total_mi, places=6)
            for a, b in zip(miles[1:-1], miles[2:-1]):
                self.assertAlmostEqual(b - a, interval, places=6)

    def test_eta_reflects_drive_time(self):
        cps = sample_checkpoints(self.profile, DEPARTURE, 25)
        hours = (cps[2].eta - DEPARTURE).total_seconds() / 3600
        self.assertAlmostEqual(hours, 50 / 60, places=2)  # mile 50 at 60 mph
        self.assertEqual(cps[-1].eta, DEPARTURE.replace() + (cps[-1].eta - DEPARTURE))
        self.assertAlmostEqual((cps[-1].eta - DEPARTURE).total_seconds(), self.profile.duration_s, places=3)

    def test_represented_miles_cover_the_route_exactly(self):
        cps = sample_checkpoints(self.profile, DEPARTURE, 25)
        self.assertAlmostEqual(sum(cp.represented_miles for cp in cps), self.total_mi, places=6)
        self.assertEqual(cps[0].start_mile, 0)
        self.assertAlmostEqual(cps[1].start_mile, 12.5)

    def test_checkpoint_positions_are_on_route(self):
        cps = sample_checkpoints(self.profile, DEPARTURE, 50)
        for cp in cps:
            self.assertAlmostEqual(cp.lat, 35.0, places=6)


class HourlySeriesTests(SimpleTestCase):
    def setUp(self):
        t0 = int(DEPARTURE.timestamp())
        self.t0 = t0
        self.series = HourlySeries(
            times=[t0, t0 + 3600, t0 + 7200],
            wind_mph=[10.0, 30.0, 50.0],
            gust_mph=[15.0, 40.0, 60.0],
            rain_in=[0.0, 0.2, 0.6],
            snow_in=[0.0, 0.0, 0.0],
            temp_f=[50.0, 52.0, 54.0],
        )

    def test_wind_is_interpolated(self):
        self.assertAlmostEqual(self.series.at(self.t0 + 1800).wind_mph, 20.0)

    def test_precip_uses_the_hour_bucket_containing_eta(self):
        # 08:30 lies in the hour ending 09:00 → the 09:00 value (0.2 in/hr)
        self.assertAlmostEqual(self.series.at(self.t0 + 1800).rain_in_hr, 0.2)
        self.assertAlmostEqual(self.series.at(self.t0 + 3600).rain_in_hr, 0.2)
        self.assertAlmostEqual(self.series.at(self.t0 + 3601).rain_in_hr, 0.6)

    def test_out_of_range_is_unknown(self):
        self.assertIsNone(self.series.at(self.t0 - 1))
        self.assertIsNone(self.series.at(self.t0 + 7201))


class OpenMeteoParsingTests(SimpleTestCase):
    def test_units_are_normalised(self):
        payload = {
            "hourly_units": {"wind_speed_10m": "km/h", "rain": "mm", "showers": "mm", "snowfall": "cm",
                             "temperature_2m": "°C"},
            "hourly": {
                "time": [0, 3600],
                "wind_speed_10m": [100.0, None],
                "wind_gusts_10m": [120.0, 130.0],
                "rain": [25.4, 0.0],
                "showers": [25.4, None],
                "snowfall": [2.54, 0.0],
                "temperature_2m": [0.0, 10.0],
            },
        }
        s = parse_open_meteo_location(payload)
        self.assertAlmostEqual(s.wind_mph[0], 62.1371, places=3)
        self.assertIsNone(s.wind_mph[1])
        self.assertAlmostEqual(s.rain_in[0], 2.0)  # rain + showers
        self.assertAlmostEqual(s.snow_in[0], 1.0)
        self.assertAlmostEqual(s.temp_f[0], 32.0)
