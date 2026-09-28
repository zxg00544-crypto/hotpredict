# tests/test_buckets.py
import unittest
from scoring.buckets import pick_fast, pick_trend

CFG = {"thresholds": {
    "fast":  {"g_min": 80, "max_age_h": 6, "rank_delta_min": 10, "heat_min": 70, "top_n": 10},
    "trend": {"min_days": 3, "slope_min": 0.0, "score_min": 50, "min_sources": 2,
              "top_n": 15, "window_days": 7}}}

def tp(key="k", score=60, G=50, rank_delta=0, heat=80, age_h=1, n_sources=1):
    return {"key": key, "title": key, "score": score, "G": G, "rank_delta": rank_delta,
            "heat": heat, "age_hours": age_h, "n_sources": n_sources,
            "hist": [{"fetched_at": "d", "engagement": 1, "heat": 1, "rank": 1}]}

class TestFast(unittest.TestCase):
    def test_growth_rule_hits(self):
        r = pick_fast([tp(G=85, heat=70, age_h=2)], CFG)
        self.assertEqual(len(r), 1)
        self.assertIn("增速G", r[0]["reason"])

    def test_rank_delta_rule_hits_without_growth(self):
        r = pick_fast([tp(G=0, rank_delta=12, age_h=3)], CFG)
        self.assertEqual(len(r), 1)
        self.assertIn("位次", r[0]["reason"])

    def test_excludes_stale_topic_out_of_6h_bucket(self):
        r = pick_fast([tp(G=99, age_h=9)], CFG)
        self.assertEqual(r, [])

    def test_excludes_low_heat_new_topic(self):
        r = pick_fast([tp(G=0, rank_delta=5, heat=30, age_h=1)], CFG)
        self.assertEqual(r, [])

    def test_top_n_cap(self):
        r = pick_fast([tp(key=f"k{i}", G=90, age_h=1) for i in range(15)], CFG)
        self.assertEqual(len(r), 10)

class TestTrend(unittest.TestCase):
    def test_three_day_positive_trend_with_resonance_hits(self):
        r = pick_trend([tp(score=70, n_sources=2)],
                       CFG, {"k": [10, 20, 40]})
        self.assertEqual(len(r), 1)

    def test_excludes_below_score(self):
        r = pick_trend([tp(score=40, n_sources=2)], CFG, {"k": [10, 20, 40]})
        self.assertEqual(r, [])

    def test_excludes_single_day_history(self):
        r = pick_trend([tp(score=80, n_sources=2)], CFG, {"k": [30]})
        self.assertEqual(r, [])

    def test_excludes_negative_slope(self):
        r = pick_trend([tp(score=80, n_sources=2)], CFG, {"k": [40, 30, 20]})
        self.assertEqual(r, [])

if __name__ == "__main__":
    unittest.main()
