# tests/test_probe_parsing.py
import unittest
from probe import normalize_title, probe_zhihu_parse, build_payload_md


class TestProbeParsing(unittest.TestCase):
    def test_normalize_title_strips_punct_and_space(self):
        self.assertEqual(normalize_title("  AI 大模型！？ "), "ai大模型")

    def test_zhihu_parse_reads_hot_list(self):
        payload = {"data": [{"target": {"title": "测试热榜", "id": 1},
                             "detail_text": "1234 万热度"}]}
        sig = probe_zhihu_parse(payload)
        self.assertEqual(sig[0].title, "测试热榜")
        self.assertEqual(sig[0].rank, 1)
        self.assertEqual(sig[0].source, "zhihu")
        self.assertGreater(sig[0].heat, 0)

    def test_build_payload_md_contains_total(self):
        md = build_payload_md({"zhihu": {"status": "PASS", "n": 20, "sample": "x"}})
        self.assertIn("TOTAL PASS=1/1", md)
        self.assertIn("zhihu", md)


if __name__ == "__main__":
    unittest.main()
