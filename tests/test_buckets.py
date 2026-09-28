# tests/test_buckets.py
import unittest
from scoring.buckets import pick_fast, pick_trend

CFG = {"thresholds": {
    "fast":  {"g_min": 80, "max_age_h": 6, "rank_delta_min": 10, "heat_min": 70, "top_n": 10},
    "trend": {"min_days": 3, "slope_min": 0.0, "score_min": 50, "min_sources": 2,
              "top_n": 15, "window_days": 7}}}

CFG_BRK = {"thresholds": {
    "fast":  {"g_min": 80, "max_age_h": 6, "rank_delta_min": 10, "heat_min": 70, "top_n": 10,
              "breaking": {"max_age_h": 2, "min_sources": 2, "top_rank": 5,
                           "heat_high": 200, "max_push_per_day": 6}},
    "trend": {"min_days": 3, "slope_min": 0.0, "score_min": 50, "min_sources": 2,
              "top_n": 15, "window_days": 7}}}

def tp(key="k", score=60, G=50, rank_delta=0, heat=80, age_h=1, n_sources=1,
       is_new=False, rank=999):
    return {"key": key, "title": key, "score": score, "G": G, "rank_delta": rank_delta,
            "heat": heat, "age_hours": age_h, "n_sources": n_sources,
            "is_new": is_new, "rank": rank,
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

class TestBreaking(unittest.TestCase):
    """⚡突发=铁信号三选一：跨源共振/登顶前5/真热度≥200。
    rank_delta 不参与：榜位抖动实测 10/10 全>=15，是噪声。"""

    def test_breaking_by_top_rank(self):
        r = pick_fast([tp(G=0, heat=50, rank=3, age_h=1, is_new=True)], CFG_BRK)
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["breaking"])
        self.assertTrue(r[0]["reason"].startswith("⚡突发"))
        self.assertIn("登顶", r[0]["reason"])

    def test_breaking_by_true_heat(self):
        r = pick_fast([tp(G=0, heat=250, age_h=1, is_new=True)], CFG_BRK)
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["breaking"])
        self.assertIn("真热度", r[0]["reason"])

    def test_breaking_by_two_sources_same_round(self):
        r = pick_fast([tp(G=0, heat=60, age_h=1, n_sources=2, is_new=True)], CFG_BRK)
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["breaking"])
        self.assertIn("2源共振", r[0]["reason"])

    def test_rank_delta_noise_is_not_breaking(self):
        # 真实数据：榜位抖动使 delta 普遍 17~32，单凭 delta 不算突发
        r = pick_fast([tp(G=0, heat=50, rank=41, rank_delta=30,
                          age_h=1, is_new=True)], CFG_BRK)
        self.assertEqual(len(r), 1)                     # N2 仍入快讯桶
        self.assertFalse(r[0].get("breaking", False))   # 但不算突发

    def test_mid_list_rank_not_breaking(self):
        r = pick_fast([tp(G=0, heat=80, rank=48, age_h=1, is_new=True)], CFG_BRK)
        self.assertEqual(len(r), 1)
        self.assertFalse(r[0].get("breaking", False))

    def test_breaking_age_gate_over_2h(self):
        r = pick_fast([tp(G=0, heat=250, age_h=3, is_new=True)], CFG_BRK)
        self.assertEqual(len(r), 1)                     # N3 仍入桶
        self.assertFalse(r[0].get("breaking", False))   # 但不算突发

    def test_breaking_requires_is_new(self):
        r = pick_fast([tp(G=0, heat=250, age_h=1, is_new=False)], CFG_BRK)
        self.assertEqual(r, [])

    def test_breaking_sorts_first_despite_low_score(self):
        r = pick_fast([tp(key="hot", score=95, G=90, heat=80, age_h=1),
                       tp(key="brk", score=50, G=0, heat=60, rank=2,
                          age_h=1, is_new=True)],
                      CFG_BRK)
        self.assertEqual(r[0]["key"], "brk")
        self.assertTrue(r[0]["breaking"])

    def test_no_breaking_key_without_config(self):
        r = pick_fast([tp(G=0, heat=250, age_h=1, is_new=True)], CFG)
        self.assertTrue(all(not x.get("breaking") for x in r))

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
