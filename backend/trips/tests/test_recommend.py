from django.test import SimpleTestCase

from trips.services.recommend import RouteSummary, explain, rank


def summary(rid, no_travel=0.0, severe=0.0, high=0.0, avg=0.5, hours=3.0, max_level=None) -> RouteSummary:
    miles = {"low": 100.0, "moderate": 0.0, "high": high, "severe": severe, "no_travel": no_travel}
    if max_level is None:
        max_level = 4 if no_travel else 3 if severe else 2 if high else 0
    return RouteSummary(route_id=rid, label=f"Route {rid}", distance_mi=200, duration_s=hours * 3600,
                        miles_by_level=miles, avg_risk=avg, max_level=max_level)


def ids(summaries):
    return [s.route_id for s in summaries]


class RankingTests(SimpleTestCase):
    def test_fewest_severe_miles_wins_over_speed(self):
        a = summary("A", severe=25, hours=3)
        b = summary("B", severe=0, high=50, hours=5)
        self.assertEqual(ids(rank([a, b])), ["B", "A"])

    def test_high_miles_break_severe_ties(self):
        a = summary("A", severe=10, high=40)
        b = summary("B", severe=10, high=15, hours=4)
        self.assertEqual(ids(rank([a, b])), ["B", "A"])

    def test_average_risk_breaks_high_ties(self):
        a = summary("A", high=10, avg=0.9)
        b = summary("B", high=10, avg=0.4, hours=6)
        self.assertEqual(ids(rank([a, b])), ["B", "A"])

    def test_travel_time_is_the_final_tiebreak(self):
        a = summary("A", hours=4)
        b = summary("B", hours=3)
        self.assertEqual(ids(rank([a, b])), ["B", "A"])

    def test_no_travel_is_worse_than_severe(self):
        a = summary("A", no_travel=12.5)
        b = summary("B", severe=50)
        self.assertEqual(ids(rank([a, b])), ["B", "A"])

    def test_tolerance_ignores_rounding_noise(self):
        a = summary("A", severe=10.4, hours=3)
        b = summary("B", severe=10.0, hours=5)
        self.assertEqual(ids(rank([a, b])), ["A", "B"])

    def test_three_way_ranking(self):
        a = summary("A", severe=25, hours=3)
        b = summary("B", high=25, hours=4)
        c = summary("C", hours=5)
        self.assertEqual(ids(rank([a, b, c])), ["C", "B", "A"])


class ExplainTests(SimpleTestCase):
    def test_reasons_name_the_deciding_criterion(self):
        best = summary("C", hours=5)
        reasons = explain(best, [summary("B", high=25), summary("A", severe=25)])
        self.assertTrue(any("High-risk miles" in r and "Route B" in r for r in reasons))
        self.assertTrue(any("Severe miles" in r and "Route A" in r for r in reasons))

    def test_time_reason(self):
        reasons = explain(summary("B", hours=3), [summary("A", hours=3.5)])
        self.assertIn("30 min faster", reasons[-1])

    def test_all_routes_blocked_warning(self):
        reasons = explain(summary("A", no_travel=10), [summary("B", no_travel=20)])
        self.assertIn("No Travel", reasons[0])
