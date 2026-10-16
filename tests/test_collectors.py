# tests/test_collectors.py
import unittest
from unittest import mock
from collectors.zhihu import parse_hot_list
from collectors.hn import parse_item
from collectors.finance_sina import parse_feed as parse_sina
from collectors.weibo_v import parse_feed as parse_vv, fetch as fetch_vv
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

    def test_finance_sina_parse_bracket_title(self):
        payload = {"result": {"data": {"feed": {"list": [
            {"rich_text": "【某公司：业绩预增100%】公告正文", "like_nums": 5,
             "create_time": "2026-09-28 15:00:00", "docurl": "http://x/1", "id": 1}]}}}}
        sigs = parse_sina(payload, fetched_at="2026-09-28T15:01:00")
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].source, "finance_sina")
        self.assertEqual(sigs[0].title, "某公司：业绩预增100%")
        self.assertGreaterEqual(sigs[0].heat, 70.0)

    def test_finance_sina_heat_rank_fallback_when_no_like(self):
        payload = {"result": {"data": {"feed": {"list": [
            {"rich_text": "【快讯一】正文", "create_time": "2026-09-28 15:00:00", "id": i}
            for i in range(30)]}}}}
        sigs = parse_sina(payload, fetched_at="2026-09-28T15:01:00")
        self.assertTrue(all(s.heat >= 70.0 for s in sigs), "30条内rank热度须过heat_min")

    def test_weibo_v_parse_mblog(self):
        payload = {"data": {"cards": [
            {"card_type": 9, "mblog": {
                "id": "123", "bid": "Abc", "created_at": "Wed Sep 23 20:42:01 +0800 2026",
                "text": "今天发布了新品<br />价格惊喜", "attitudes_count": 100,
                "comments_count": 50, "reposts_count": 10,
                "user": {"id": 1749127163, "screen_name": "雷军"}}},
            {"card_type": 10}]}}
        sigs = parse_vv(1749127163, payload, fetched_at="2026-09-28T15:01:00")
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s.source, "weibo_v")
        self.assertEqual(s.title, "今天发布了新品 价格惊喜")
        self.assertEqual(s.url, "https://weibo.com/1749127163/Abc")
        self.assertEqual(s.heat, 100 + 50 * 2 + 10 * 3)
        self.assertEqual(s.author_weight, 1.0)

    def _vv_cfg(self):
        return {"weibo_cookie": "SUB=x",
                "weibo_v_vvs": [{"uid": 1, "name": "a"}, {"uid": 2, "name": "b"}]}

    @mock.patch("collectors.weibo_v.time.sleep")
    @mock.patch("collectors.weibo_v.requests.get")
    def test_weibo_v_all_failed_raises(self, mget, _sleep):
        resp = mock.Mock()
        resp.status_code = 432
        http_err = RuntimeError("432 Client Error")
        http_err.response = resp
        mget.side_effect = http_err
        with self.assertRaises(RuntimeError) as cm:
            fetch_vv(self._vv_cfg())
        msg = str(cm.exception)
        self.assertIn("2/2", msg)
        self.assertIn("432", msg)

    @mock.patch("collectors.weibo_v.time.sleep")
    @mock.patch("collectors.weibo_v.requests.get")
    def test_weibo_v_all_failed_with_response_empty_raises(self, mget, _sleep):
        mget.side_effect = RuntimeError("unexpected")
        with self.assertRaises(RuntimeError) as cm:
            fetch_vv(self._vv_cfg())
        self.assertIn("2/2", str(cm.exception))

    @mock.patch("collectors.weibo_v.time.sleep")
    @mock.patch("collectors.weibo_v.requests.get")
    def test_weibo_v_partial_failure_returns_data(self, mget, _sleep):
        payload = {"ok": 1, "data": {"cards": [
            {"card_type": 9, "mblog": {
                "id": "1", "bid": "B", "created_at": "Wed Sep 23 20:42:01 +0800 2026",
                "text": "正文", "attitudes_count": 5, "comments_count": 1,
                "reposts_count": 0, "user": {"id": 1, "screen_name": "x"}}}]}}
        good = mock.Mock()
        good.raise_for_status.return_value = None
        good.json.return_value = payload
        mget.side_effect = [good, RuntimeError("HTTP 432")]
        sigs = fetch_vv(self._vv_cfg())
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].source, "weibo_v")

    @mock.patch("collectors.weibo_v.requests.get")
    def test_weibo_v_no_cookie_returns_empty(self, mget):
        self.assertEqual(fetch_vv({"weibo_cookie": "", "weibo_v_vvs": [{"uid": 1}]}), [])
        mget.assert_not_called()

    def test_registry_includes_new_sources_and_cookie_gate(self):
        cfg = {"platforms": {"zhihu": False, "weibo": True, "weibo_v": True,
                             "finance_sina": True},
               "weibo_cookie": ""}
        names = [f.__module__.split(".")[-1] for f in get_collectors(cfg)]
        self.assertIn("finance_sina", names)
        self.assertNotIn("weibo_v", names)
        cfg["weibo_cookie"] = "SUB=x"
        names = [f.__module__.split(".")[-1] for f in get_collectors(cfg)]
        self.assertIn("weibo_v", names)

    def test_registry_respects_platform_switch_and_cookie(self):
        cfg = {"platforms": {"zhihu": True, "bilibili": False, "weibo": True,
                             "hn": True, "reddit": False, "github": False},
               "weibo_cookie": ""}
        names = [f.__module__.split(".")[-1] for f in get_collectors(cfg)]
        self.assertIn("zhihu", names)
        self.assertNotIn("bilibili", names)
        self.assertNotIn("weibo", names)
        self.assertIn("hn", names)

if __name__ == "__main__":
    unittest.main()
