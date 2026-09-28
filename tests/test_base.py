# tests/test_base.py
import unittest
from dataclasses import fields
from collectors.base import Signal, topic_key


class TestBase(unittest.TestCase):
    def test_topic_key_merges_same_event_spellings(self):
        self.assertEqual(topic_key("AI 大模型发布！"), topic_key("ai大模型发布"))
        self.assertEqual(topic_key("  微博 热搜 话题"), topic_key("微博热搜话题"))

    def test_topic_key_differs_for_different_titles(self):
        self.assertNotEqual(topic_key("苹果发布会"), topic_key("谷歌发布会"))

    def test_topic_key_long_title_is_stable_and_bounded(self):
        long_t = "这是一条很长很长的标题" * 8
        k1, k2 = topic_key(long_t), topic_key(long_t + "!")
        self.assertEqual(k1, k2)
        self.assertLessEqual(len(k1), 40)

    def test_signal_has_all_contract_fields(self):
        names = {f.name for f in fields(Signal)}
        self.assertEqual(names, {"topic_key", "source", "title", "url", "heat",
                                 "rank", "rank_delta", "engagement", "author_weight",
                                 "published_at", "fetched_at", "raw"})


if __name__ == "__main__":
    unittest.main()
