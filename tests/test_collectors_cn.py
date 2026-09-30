# -*- coding: utf-8 -*-
"""新源解析测试：头条热榜 JSON + 百度热搜 s-data HTML（2026-09-30 补突发源）。"""
import json, unittest
from collectors.toutiao import parse_board
from collectors.baidu import parse_page

TOUTIAO_SAMPLE = {"data": [
    {"ClusterId": 111, "Title": "南部战区位黄岩岛领海领空战备警巡",
     "Url": "https://www.toutiao.com/trending/1/", "HotValue": 25452081,
     "Label": "热"},
    {"ClusterId": 112, "Title": "某地通报一起事件调查进展",
     "Url": "https://www.toutiao.com/trending/2/", "HotValue": 9000000},
    {"ClusterId": 113, "Title": "", "Url": "x", "HotValue": 1},  # 空标题丢弃
]}

BAIDU_HTML = (
    "<html><body><script>"
    "<!--s-data:"
    + json.dumps({"data": {"cards": [{
        "content": [
            {"word": "习近平出席向人民英雄敬献花篮仪式", "hotScore": 7903986,
             "url": "https://www.baidu.com/s?wd=1", "index": 0, "desc": "描述"},
            {"word": "社会热点话题二", "hotScore": 5000000,
             "url": "https://www.baidu.com/s?wd=2", "index": 1},
        ]}]}} , ensure_ascii=False)
    + "--></script></body></html>"
)


class TestToutiao(unittest.TestCase):
    def test_parse_basic(self):
        out = parse_board(TOUTIAO_SAMPLE, "2026-09-30T13:00:00")
        self.assertEqual(len(out), 2)                      # 空标题丢弃
        s = out[0]
        self.assertEqual(s.source, "toutiao")
        self.assertEqual(s.rank, 1)
        self.assertEqual(s.heat, 196.0)                    # 200-4*1，不撞 200
        self.assertTrue(s.heat < 200)                      # 不凭绝对热度进 breaking
        self.assertEqual(s.title, "南部战区位黄岩岛领海领空战备警巡")
        self.assertTrue(s.url.startswith("https://"))
        self.assertEqual(s.raw["hot"], 25452081)           # 原始热度留档

    def test_rank_heat_monotonic(self):
        out = parse_board(TOUTIAO_SAMPLE, "2026-09-30T13:00:00")
        self.assertGreater(out[0].heat, out[1].heat)


class TestBaidu(unittest.TestCase):
    def test_parse_sdata(self):
        out = parse_page(BAIDU_HTML, "2026-09-30T13:00:00")
        self.assertEqual(len(out), 2)
        s = out[0]
        self.assertEqual(s.source, "baidu")
        self.assertEqual(s.rank, 1)
        self.assertEqual(s.heat, 196.0)
        self.assertEqual(s.title, "习近平出席向人民英雄敬献花篮仪式")
        self.assertEqual(s.raw["hot"], 7903986)

    def test_no_sdata_returns_empty(self):
        self.assertEqual(parse_page("<html>no data</html>", "t"), [])

    def test_bad_json_returns_empty(self):
        self.assertEqual(parse_page("<!--s-data:{broken-->", "t"), [])

    def test_topic_key_shared(self):
        out = parse_page(BAIDU_HTML, "t")
        self.assertTrue(out[0].topic_key)
        self.assertNotEqual(out[0].topic_key, "empty")


if __name__ == "__main__":
    unittest.main()
