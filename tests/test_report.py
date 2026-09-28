# tests/test_report.py
import unittest
from render.report import render_daily
BS = chr(92)
PIPE = chr(124)

def item(rating="A", key="k1", title="AI大模型发布", **kw):
    base = {"key": key, "title": title, "url": "https://x", "score": 75, "G": 90,
            "heat": 1000, "reason": "增速G=90", "sources": ["zhihu"],
            "age_hours": 2, "rating": rating, "track": "AI/科技工具",
            "hook_reason": "冲突强", "genre_score": 9, "fit_score": 8,
            "angle": "写给副业者看", "act_now": True, "risk": "低",
            "model": "deepseek-chat"}
    base.update(kw); return base

class TestReport(unittest.TestCase):
    def test_renders_header_and_degradation_note(self):
        md = render_daily("2026-09-28", [item()], [item(key="k2", rating="B")],
                          {"llm_model": "deepseek-chat", "llm_fallback_count": 2,
                           "degraded": True, "sources": ["zhihu", "hn"], "db_path": "热点.db"})
        self.assertIn("# 热点预判日报 · 2026-09-28", md)
        self.assertIn("降级", md)
        self.assertIn("deepseek-chat", md)

    def test_renders_two_buckets(self):
        md = render_daily("2026-09-28", [item()], [item(key="k2", rating="B", slope=10)],
                          {"llm_model": "m", "llm_fallback_count": 0, "degraded": False,
                           "sources": [], "db_path": "热点.db"})
        self.assertIn("快讯档", md)
        self.assertIn("趋势推荐", md)

    def test_rating_marks_a_with_now_tag(self):
        md = render_daily("2026-09-28", [item(rating="A")], [],
                          {"llm_model": "m", "llm_fallback_count": 0, "degraded": False,
                           "sources": [], "db_path": "热点.db"})
        self.assertIn("**A**", md)
        self.assertIn("立即行动", md)

    def test_empty_buckets_state_it(self):
        md = render_daily("2026-09-28", [], [], {"llm_model": "m", "llm_fallback_count": 0,
                          "degraded": False, "sources": [], "db_path": "热点.db"})
        self.assertIn("今日暂无热点", md)

class TestPipeEscape(unittest.TestCase):
    @staticmethod
    def _gfm_cells(line):
        out, buf, i = [], [], 0
        while i < len(line):
            ch = line[i]
            if ch == BS and i + 1 < len(line) and line[i + 1] == PIPE:
                buf.append(PIPE); i += 2; continue
            if ch == PIPE:
                out.append("".join(buf).strip()); buf = []; i += 1; continue
            buf.append(ch); i += 1
        out.append("".join(buf).strip())
        return out

    def test_title_pipe_does_not_break_table(self):
        t = {"title": "格力峰会 " + PIPE + " 董明珠真挚表示", "rating": "B",
             "score": 49.8, "G": 0.0, "track": "大咖发言",
             "hook_reason": "金句自带流量", "url": "https://weibo.com/x"}
        md = render_daily("2026-09-28", [t], [], {"sources": ["weibo_v"]})
        row = [l for l in md.splitlines() if l.startswith("| 1 ")][0]
        cells = self._gfm_cells(row)
        self.assertEqual(len(cells), 10)
        self.assertEqual(cells[3], "格力峰会 " + PIPE + " 董明珠真挚表示")
        self.assertEqual(cells[6], "大咖发言")
        self.assertIn(BS + PIPE, row)

    def test_hook_pipe_escaped(self):
        t = {"title": "t", "rating": "A", "score": 80, "G": 50,
             "track": "财经", "hook_reason": "a " + PIPE + " b", "url": "u"}
        md = render_daily("2026-09-28", [t], [], {})
        row = [l for l in md.splitlines() if l.startswith("| 1 ")][0]
        cells = self._gfm_cells(row)
        self.assertEqual(len(cells), 10)
        self.assertEqual(cells[7], "a " + PIPE + " b")

if __name__ == "__main__":
    unittest.main()
