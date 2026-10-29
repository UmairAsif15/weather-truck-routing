from django.test import SimpleTestCase

from trips.services.risk import (
    RiskLevel,
    WeatherSample,
    apply_load_rules,
    assess,
    classify_rain,
    classify_snow,
    classify_wind,
    continuous_score,
)

L, M, H, S, N = (RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.SEVERE, RiskLevel.NO_TRAVEL)


def sample(wind=0.0, rain=0.0, snow=0.0) -> WeatherSample:
    return WeatherSample(wind_mph=wind, gust_mph=None, rain_in_hr=rain, snow_in_hr=snow)


class ThresholdTests(SimpleTestCase):
    def test_wind_bands(self):
        cases = [(0, L), (24.9, L), (25, M), (34.9, M), (35, H), (44.9, H), (45, S), (54.9, S), (55, N), (80, N)]
        for mph, expected in cases:
            with self.subTest(mph=mph):
                self.assertEqual(classify_wind(mph), expected)

    def test_rain_bands(self):
        cases = [(0, L), (0.099, L), (0.10, M), (0.249, M), (0.25, H), (0.49, H), (0.50, S), (1.00, S), (1.01, N)]
        for rate, expected in cases:
            with self.subTest(rate=rate):
                self.assertEqual(classify_rain(rate), expected)

    def test_snow_bands(self):
        cases = [(0, L), (0.49, L), (0.5, M), (0.99, M), (1.0, H), (1.99, H), (2.0, S), (3.0, S), (3.01, N)]
        for rate, expected in cases:
            with self.subTest(rate=rate):
                self.assertEqual(classify_snow(rate), expected)


class LoadRuleTests(SimpleTestCase):
    def test_55_mph_is_no_travel_for_any_load(self):
        for load in (0, 10_000, 80_000):
            self.assertEqual(apply_load_rules(55, load)[0], N)

    def test_45_to_54_mph_over_30k_is_no_travel(self):
        self.assertEqual(apply_load_rules(45, 30_001)[0], N)
        self.assertEqual(apply_load_rules(54.9, 45_000)[0], N)
        self.assertEqual(apply_load_rules(50, 30_000)[0], S)  # exactly 30,000 is not "> 30,000"
        self.assertEqual(apply_load_rules(50, 10_000)[0], S)

    def test_35_to_44_mph_over_40k_is_severe(self):
        self.assertEqual(apply_load_rules(35, 40_001)[0], S)
        self.assertEqual(apply_load_rules(44.9, 80_000)[0], S)
        self.assertEqual(apply_load_rules(40, 40_000)[0], H)
        self.assertEqual(apply_load_rules(40, 35_000)[0], H)  # 30k–40k only matters at 45+ mph

    def test_load_rules_do_not_affect_light_winds(self):
        self.assertEqual(apply_load_rules(34, 80_000)[0], M)

    def test_load_rule_note_is_reported(self):
        level, note = apply_load_rules(40, 42_000)
        self.assertEqual(level, S)
        self.assertIn("40,000", note)


class AssessTests(SimpleTestCase):
    def test_overall_is_worst_factor(self):
        result = assess(sample(wind=30, rain=0.3, snow=0.1), load_lb=10_000)
        self.assertEqual(result.level, H)
        self.assertEqual(result.drivers, ["rain"])

    def test_multiple_drivers(self):
        result = assess(sample(wind=36, rain=0.3), load_lb=0)
        self.assertEqual(result.level, H)
        self.assertEqual(result.drivers, ["wind", "rain"])

    def test_heavy_load_escalates_wind(self):
        light = assess(sample(wind=40), load_lb=20_000)
        heavy = assess(sample(wind=40), load_lb=45_000)
        self.assertEqual((light.level, heavy.level), (H, S))
        self.assertIsNotNone(heavy.load_rule)

    def test_calm_has_no_drivers(self):
        self.assertEqual(assess(sample(wind=5), 0).drivers, [])

    def test_continuous_score_matches_level(self):
        for wind, rain, snow, load in [(30, 0, 0, 0), (40, 0.1, 0, 45_000), (60, 0, 0, 0), (10, 0.6, 2.5, 0)]:
            s = sample(wind, rain, snow)
            score = continuous_score(s, load)
            self.assertEqual(int(score), int(assess(s, load).level), (wind, rain, snow, load))
