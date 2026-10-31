import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import SimpleTestCase, override_settings

from trips.services import geo
from trips.services.planner import PlanRequest, plan_trip
from trips.services.geocoding import Place
from trips.services.risk import WeatherSample
from trips.services.routing import RoutingError, get_route_options

from .fakes import CALM, FakeRouter, FieldProvider, line, straight_route

ORIGIN = (35.0, -100.0)
DEST = (35.0, -97.0)


def detour(via):
    return straight_route(line(ORIGIN, via, 40) + line(via, DEST, 40)[1:], speed_mph=60)


class RouteOptionTests(SimpleTestCase):
    def test_fills_missing_alternatives_with_via_points(self):
        router = FakeRouter([straight_route(line(ORIGIN, DEST, 80))], via=detour)
        routes, warnings = get_route_options(ORIGIN, DEST, count=3, router=router)
        self.assertEqual(len(routes), 3)
        self.assertEqual(warnings, [])
        self.assertEqual([r.source for r in routes], ["osrm", "via-point", "via-point"])
        for i in range(3):
            for j in range(i + 1, 3):
                self.assertLess(geo.overlap_ratio(routes[i].coords, routes[j].coords), 0.8)

    def test_rejects_duplicates_and_excessive_detours(self):
        fastest = straight_route(line(ORIGIN, DEST, 80))
        router = FakeRouter([fastest, straight_route(line(ORIGIN, DEST, 60))], via=lambda v: None)
        routes, warnings = get_route_options(ORIGIN, DEST, count=3, router=router)
        self.assertEqual(len(routes), 1)
        self.assertTrue(warnings)

    def test_rejects_slow_detour(self):
        slow = lambda via: straight_route(line(ORIGIN, via, 40) + line(via, DEST, 40)[1:], speed_mph=20)
        router = FakeRouter([straight_route(line(ORIGIN, DEST, 80))], via=slow)
        routes, _ = get_route_options(ORIGIN, DEST, count=3, router=router)
        self.assertEqual(len(routes), 1)

    def test_too_close(self):
        with self.assertRaises(RoutingError):
            get_route_options(ORIGIN, (35.0, -99.9999), router=FakeRouter([]))


class PlannerTests(SimpleTestCase):
    def _plan(self, field, load=20_000):
        router = FakeRouter([straight_route(line(ORIGIN, DEST, 80))], via=detour)
        provider = FieldProvider(field)
        req = PlanRequest(
            origin=Place("Origin", *ORIGIN), destination=Place("Dest", *DEST),
            departure=datetime(2026, 11, 2, 8, tzinfo=timezone.utc), load_lb=load, interval_mi=25,
        )
        return plan_trip(req, router=router, provider_factory=lambda source, scenario: provider), provider

    def test_storm_on_the_direct_route_makes_a_detour_the_pick(self):
        def field(lat, lon, t):  # gale along the straight line (lat 35.0) only
            if abs(lat - 35.0) < 0.05 and -98.9 < lon < -98.1:
                return WeatherSample(wind_mph=48, gust_mph=60, rain_in_hr=0, snow_in_hr=0, temp_f=50)
            return CALM

        result, _ = self._plan(field, load=35_000)
        direct = next(r for r in result["routes"] if r["id"] == "A")
        self.assertGreater(direct["summary"]["no_travel_miles"], 0)  # 45–54 mph + >30k lb
        self.assertNotEqual(result["recommendation"]["route_id"], "A")
        self.assertEqual(result["recommendation"]["ranking"][-1], "A")

    def test_calm_weather_picks_fastest(self):
        result, provider = self._plan(lambda lat, lon, t: CALM)
        self.assertEqual(result["recommendation"]["route_id"], "A")
        self.assertTrue(all(r["summary"]["avg_risk"] == 0 for r in result["routes"]))
        # shared origin/destination checkpoints are fetched once
        self.assertEqual(len(provider.requested_points), len(set(provider.requested_points)))

    def test_eta_drives_the_weather_lookup(self):
        departure = datetime(2026, 11, 2, 8, tzinfo=timezone.utc).timestamp()

        def field(lat, lon, t):  # everything turns stormy two hours after departure
            stormy = t >= departure + 2 * 3600
            return WeatherSample(wind_mph=40 if stormy else 5, gust_mph=None, rain_in_hr=0, snow_in_hr=0, temp_f=None)

        result, _ = self._plan(field)
        cps = result["routes"][0]["checkpoints"]
        early = [cp for cp in cps if cp["elapsed_s"] <= 3600]  # wind ramps linearly between hours 1 and 2
        late = [cp for cp in cps if cp["elapsed_s"] >= 2 * 3600]
        self.assertTrue(all(cp["risk"]["label"] == "Low" for cp in early))
        self.assertTrue(late and all(cp["risk"]["label"] == "High" for cp in late))


@override_settings(ALLOWED_HOSTS=["testserver"])
class ApiTests(SimpleTestCase):
    def setUp(self):
        self.departure = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()

    def _post(self, url, body):
        return self.client.post(url, json.dumps(body), content_type="application/json")

    def _post_rejected(self, url, body):
        # Django logs every 4xx as "Bad Request"; capture it so test output stays clean.
        with self.assertLogs("django.request", level="WARNING"):
            return self._post(url, body)

    def test_validation_errors(self):
        res = self._post_rejected("/api/plan/", {"origin": {}, "destination": {"query": "x"}, "departure": "nope",
                                                 "load_weight_lb": -5, "sample_interval_mi": 7})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.json()), {"origin", "departure", "load_weight_lb", "sample_interval_mi"})

    def test_departure_in_past_rejected(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        res = self._post_rejected("/api/plan/", {"origin": {"lat": 35, "lon": -100}, "destination": {"lat": 35, "lon": -97},
                                                 "departure": past, "load_weight_lb": 1000})
        self.assertEqual(res.status_code, 400)

    def test_plan_and_heatmap_with_simulated_storm(self):
        router = FakeRouter([straight_route(line(ORIGIN, DEST, 80))], via=detour)
        with mock.patch("trips.services.routing.OSRMRouter", return_value=router):
            res = self._post("/api/plan/", {
                "origin": {"query": "A", "lat": ORIGIN[0], "lon": ORIGIN[1]},
                "destination": {"query": "B", "lat": DEST[0], "lon": DEST[1]},
                "departure": self.departure, "load_weight_lb": 42_000,
                "sample_interval_mi": 10, "weather_source": "simulated",
            })
        self.assertEqual(res.status_code, 200, res.content)
        plan = res.json()
        self.assertEqual(len(plan["routes"]), 3)
        self.assertEqual(sum(r["recommended"] for r in plan["routes"]), 1)
        storm_route = plan["routes"][0]
        self.assertGreaterEqual(storm_route["summary"]["max_level"], 3)  # the storm sits on route A

        res = self._post("/api/heatmap/", {
            "paths": [[g[:2] for g in r["geometry"]] for r in plan["routes"]],
            "departure": self.departure, "load_weight_lb": 42_000,
            "weather_source": "simulated", "simulation": plan["simulation"],
        })
        self.assertEqual(res.status_code, 200, res.content)
        heat = res.json()
        self.assertEqual(len(heat["times"]), 49)
        self.assertEqual(len(heat["layers"]["risk"][0]), len(heat["cells"]))
        self.assertTrue(all(0 <= r < heat["rows"] and 0 <= c < heat["cols"] for r, c in heat["cells"]))
        self.assertLessEqual(len(heat["cells"]), 180)
