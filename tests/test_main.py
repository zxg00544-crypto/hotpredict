# tests/test_main.py
import unittest, tempfile, os
from unittest.mock import patch
from main import run_round, load_cfg

class TestMain(unittest.TestCase):
    def test_load_cfg_reads_yaml(self):
        cfg = load_cfg("config.yaml")
        for k in ["platforms", "llm", "notify", "weights", "thresholds", "score_params"]:
            self.assertIn(k, cfg)

    @patch("main._now_hour", return_value=21)
    @patch("main.notify", return_value="skipped")
    @patch("main.judge_topic")
    @patch("main.get_collectors", return_value=[])
    def test_run_round_dry_produces_report_and_board(self, m_col, m_judge, m_notify,
                                                     m_hour):
        m_judge.return_value = {"rating": "A", "track": "AI/科技工具", "hook_reason": "r",
                                "genre_score": 9, "fit_score": 8, "angle": "角度",
                                "act_now": True, "risk": "低", "model": "mock"}
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"db_path": os.path.join(tmp, "t.db"), "out_dir": tmp,
                   "dry_run": True, "use_llm": False, "notify_fallback": False,
                   "thresholds": {"fast": {"g_min": 80, "max_age_h": 6, "rank_delta_min": 10,
                                           "heat_min": 70, "top_n": 10},
                                  "trend": {"min_days": 3, "slope_min": 0.0, "score_min": 50,
                                            "min_sources": 2, "top_n": 15, "window_days": 7}},
                   "weights": {}, "score_params": {}, "llm": {"model": "x"},
                   "tracks": {}, "platforms": {}}
            res = run_round(cfg)
            self.assertEqual(res["status"], "ok")
            self.assertTrue(os.path.exists(res["report_path"]))
            self.assertTrue(os.path.exists(res["board_path"]))
            # use_llm=False -> degraded: daily + alert = 2 calls
            self.assertEqual(m_notify.call_count, 2)
            self.assertEqual([p["kind"] for p in res["push"]], ["daily", "alert"])

    @patch("main.notify", return_value="skipped")
    @patch("main.judge_topic")
    @patch("main.get_collectors", return_value=[])
    def test_run_round_marks_degraded_when_llm_fails(self, m_col, m_judge, m_notify):
        m_judge.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"db_path": os.path.join(tmp, "t.db"), "out_dir": tmp,
                   "dry_run": False, "use_llm": True, "notify_fallback": False,
                   "thresholds": {"fast": {"g_min": 80, "max_age_h": 6, "rank_delta_min": 10,
                                           "heat_min": 70, "top_n": 10},
                                  "trend": {"min_days": 3, "slope_min": 0.0, "score_min": 50,
                                            "min_sources": 2, "top_n": 15, "window_days": 7}},
                   "weights": {}, "score_params": {}, "llm": {"model": "x"},
                   "tracks": {}, "platforms": {}, "notify": {"serverchan_sendkey": ""}}
            res = run_round(cfg)
            self.assertEqual(res["status"], "ok")
            with open(res["report_path"], encoding="utf-8") as fh:
                md = fh.read()
            self.assertIn("快讯", md)

if __name__ == "__main__":
    unittest.main()
