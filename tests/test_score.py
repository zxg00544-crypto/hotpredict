# tests/test_score.py
import unittest
from collectors.base import Signal
from scoring.score import aggregate_topics, composite

CFG = {"weights": {"growth": 0.35, "engagement": 0.25, "author": 0.15,
                   "resonance": 0.15, "rank": 0.10},
       "score_params": {"growth_scale": 200, "new_topic_rank_delta_per_10": 60,
                        "resonance_map": {1: 0, 2: 40, 3: 70, 4: 100},
                        "rank_bonus_on_rise": 15,
                        "speed_bonus_per_rank": 0.5, "speed_cap_ranks": 20}}

def sg(key, src, eng, rank=1, aw=0.5, ts="2026-09-28T10:00:00", heat=100.0, delta=0):
    return Signal(topic_key=key, source=src, title=key, url="u", heat=heat,
                  rank=rank, rank_delta=delta, engagement=eng, author_weight=aw,
                  fetched_at=ts)

class TestScore(unittest.TestCase):
    def test_aggregate_groups_by_key_across_sources(self):
        topics = aggregate_topics([sg("k1", "zhihu", 100), sg("k1", "weibo", 50, rank=3),
                                   sg("k2", "zhihu", 10)])
        self.assertEqual(len(topics), 2)
        t1 = next(t for t in topics if t["key"] == "k1")
        self.assertEqual(t1["n_sources"], 2)
        self.assertEqual(t1["engagement"], 150)
        self.assertEqual(t1["rank"], 1)

    def test_growth_uses_second_round_growth(self):
        t = aggregate_topics([sg("k", "zhihu", 100)])
        hist = [{"fetched_at": "a", "engagement": 100, "heat": 100, "rank": 5},
                {"fetched_at": "b", "engagement": 200, "heat": 100, "rank": 2}]
        r = composite(t[0], hist, CFG)
        self.assertAlmostEqual(r["G"], 100.0)   # +100% 增速封顶
        self.assertGreaterEqual(r["score"], 50)

    def test_new_topic_without_history_uses_rank_delta(self):
        t = aggregate_topics([sg("new", "zhihu", 10, delta=10)])
        r = composite(t[0], [], CFG)
        self.assertAlmostEqual(r["G"], 60.0)

    def test_resonance_map(self):
        t = aggregate_topics([sg("k", "a", 10), sg("k", "b", 10), sg("k", "c", 10)])
        r = composite(t[0], [], CFG)
        self.assertAlmostEqual(r["R"], 70.0)

    def test_score_is_weighted_sum_capped_100(self):
        t = aggregate_topics([sg("k", "zhihu", 500, aw=1.0, rank=1)])
        hist = [{"fetched_at": "a", "engagement": 100, "heat": 100, "rank": 1},
                {"fetched_at": "b", "engagement": 500, "heat": 100, "rank": 1}]
        r = composite(t[0], hist, CFG)
        self.assertLessEqual(r["score"], 100)
        self.assertGreater(r["score"], 60)

class TestSpeedBonus(unittest.TestCase):
    def _base(self, delta):
        t = aggregate_topics([sg("k", "zhihu", 100, delta=delta)])
        hist = [{"fetched_at": "a", "engagement": 100, "heat": 100, "rank": 5},
                {"fetched_at": "b", "engagement": 100, "heat": 100, "rank": 5}]
        return composite(t[0], hist, CFG)

    def test_speed_zero_without_delta(self):
        self.assertEqual(self._base(0)["speed"], 0.0)

    def test_speed_scales_with_rank_jump(self):
        self.assertEqual(self._base(10)["speed"], 5.0)   # 10位 × 0.5

    def test_speed_capped_at_20_ranks(self):
        self.assertEqual(self._base(100)["speed"], 10.0) # 封顶 20×0.5

    def test_speed_raises_total_score(self):
        self.assertGreater(self._base(10)["score"], self._base(0)["score"])

if __name__ == "__main__":
    unittest.main()
