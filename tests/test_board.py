# tests/test_board.py
import unittest
from render.board import render_board

class TestBoard(unittest.TestCase):
    def test_single_html_file_with_two_tables(self):
        html = render_board({"date": "2026-09-28",
                             "fast": [{"title": "AI大模型", "rating": "A", "score": 75,
                                       "G": 90, "track": "AI/科技工具", "url": "https://x",
                                       "reason": "增速快", "act_now": True}],
                             "trend": [], "meta": {"llm_model": "mimo", "degraded": False,
                                                   "sources": ["zhihu"]}})
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("AI大模型", html)
        self.assertIn("快讯档", html)
        self.assertIn("趋势推荐", html)
        self.assertIn("https://x", html)
        self.assertNotIn("undefined", html)

if __name__ == "__main__":
    unittest.main()
