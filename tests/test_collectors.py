# tests/test_collectors.py
import unittest
from collectors.zhihu import parse_hot_list
from collectors.hn import parse_item
from collectors.registry import get_collectors

class TestCollectors(unittest.TestCase):
    def test_zhihu_parse_builds_signals(self):
        payload = {"data": [{"target": {"title": "AI 新模型发布", "id": 99},
                             "detail_text": "1234 万热度"}]}
        sigs = parse_hot_list(payload, fetched_at="2026-09-28T10:00:00")
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].rank, 1)
        self.assertEqual(sigs[0].source, "zhihu")
        self.assertEqual(sigs[0].topic_key, "ai新模型发布")
        self.assertEqual(sigs[0].heat, 1234.0)

    def test_hn_parse_item(self):
        item = {"id": 1, "title": "Show HN: a tool", "score": 250,
                "descendants": 80, "time": 1758970000, "url": "http://x"}
        s = parse_item(item, fetched_at="2026-09-28T10:00:00")
        self.assertEqual(s.engagement, 330)
        self.assertEqual(s.source, "hn")

    def test_registry_respects_platform_switch_and_cookie(self):
        cfg = {"platforms": {"zhihu": True, "bilibili": False, "weibo": True,
                             "hn": True, "reddit": False, "github": False},
               "weibo_cookie": ""}
        names = [f.__module__.split(".")[-1] for f in get_collectors(cfg)]
        self.assertIn("zhihu", names)
        self.assertNotIn("bilibili", names)
        self.assertNotIn("weibo", names)     # 无 Cookie 不注册
        self.assertIn("hn", names)

if __name__ == "__main__":
    unittest.main()
