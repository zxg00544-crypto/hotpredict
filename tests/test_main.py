# tests/test_main.py
import unittest, tempfile, os, json
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


    @patch("main._now_hour", return_value=10)
    @patch("main.notify", return_value="ok")
    @patch("main.get_collectors")
    def test_run_round_same_event_pushed_once(self, m_col, m_notify, m_hour):
        """端到端（2026-10-03 事件级去重）：两条同事件、不同标题、不同 key 的
        信号都进快讯档，但只推 1 条 breaking；state.pushed_events 恰 1 项。
        事件聚类走本地降级（use_llm=False），不发起任何 LLM 调用。"""
        import json as _json
        from datetime import datetime as _dt
        from collectors.base import Signal, topic_key
        t1 = "白宫人工智能协议谷歌版签署"
        t2 = "白宫人工智能协议英伟达版签署"
        now = _dt.now().isoformat()
        self.assertNotEqual(topic_key(t1), topic_key(t2))   # 两个独立 key

        def fake_collector(cfg):
            return [
                Signal(topic_key=topic_key(t1), source="sina", title=t1,
                       url="https://example.com/1", heat=250, rank=50,
                       rank_delta=0, engagement=100, author_weight=0.5,
                       fetched_at=now),
                Signal(topic_key=topic_key(t2), source="reuters", title=t2,
                       url="https://example.com/2", heat=250, rank=50,
                       rank_delta=0, engagement=100, author_weight=0.5,
                       fetched_at=now),
            ]
        m_col.return_value = [fake_collector]

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_cfg("config.yaml")
            cfg["db_path"] = os.path.join(tmp, "t.db")
            cfg["out_dir"] = tmp
            cfg["use_llm"] = False
            cfg["dry_run"] = True
            cfg["notify"] = {}
            res = run_round(cfg)
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["fast"], 2)                 # 两条都进快讯档
            kinds = [p["kind"] for p in res["push"]]
            self.assertEqual(kinds.count("breaking"), 1)     # 同事件只推 1 条
            self.assertEqual(kinds.count("a"), 0)            # 未评级 → 无 A 推送
            with open(os.path.join(tmp, "states", "push_state.json"),
                      encoding="utf-8") as fh:
                st = _json.load(fh)
            self.assertEqual(len(st["pushed_events"]), 1)    # 只登记一个事件
            self.assertEqual(len(st["pushed"]), 1)
    @patch("main.notify", return_value="ok")
    @patch("main.judge_topic")
    @patch("main.get_collectors")
    def test_run_round_writes_vv_board_and_pushes(self, m_col, m_judge, m_notify):
        """阶段一（2026-10-05）：大V动向独立板块出文件 + 钉钉推送 1 次。
        2 条同 uid + 1 条异 uid，验证 select_top/plan_vv_push 全链路。"""
        from datetime import datetime as _dt
        from collectors.base import Signal, topic_key
        now = _dt.now().isoformat()
        m_judge.return_value = {"rating": "A", "track": "AI/科技工具", "hook_reason": "r",
                                "genre_score": 9, "fit_score": 8, "angle": "角度",
                                "act_now": True, "risk": "低", "model": "mock"}

        def fake_collector(cfg):
            return [
                Signal(topic_key=topic_key("大V微博甲"), source="weibo_v",
                       title="甲博文一", url="https://weibo.com/111/bA",
                       heat=300, rank=1, rank_delta=0, engagement=100,
                       author_weight=0.9, fetched_at=now),
                Signal(topic_key=topic_key("大V微博甲2"), source="weibo_v",
                       title="甲博文二", url="https://weibo.com/111/bB",
                       heat=200, rank=2, rank_delta=0, engagement=80,
                       author_weight=0.9, fetched_at=now),
                Signal(topic_key=topic_key("大V微博乙"), source="weibo_v",
                       title="乙博文一", url="https://weibo.com/222/bC",
                       heat=150, rank=3, rank_delta=0, engagement=60,
                       author_weight=0.8, fetched_at=now),
            ]
        m_col.return_value = [fake_collector]

        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_cfg("config.yaml")
            cfg["db_path"] = os.path.join(tmp, "t.db")
            cfg["out_dir"] = tmp
            cfg["use_llm"] = False
            cfg["dry_run"] = True
            cfg["notify"] = {}
            res = run_round(cfg)
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["vv_path"])
            self.assertTrue(os.path.exists(res["vv_path"]))
            with open(res["vv_path"], encoding="utf-8") as fh:
                vv = fh.read()
            self.assertIn("大V动向", vv)
            self.assertIn("| 1 |", vv)
            self.assertIn("vv", [p["kind"] for p in res["push"]])
            vv_state = os.path.join(tmp, "states", "vv_push_state.json")
            self.assertTrue(os.path.exists(vv_state))
            with open(vv_state, encoding="utf-8") as fh:
                st = json.load(fh)
            self.assertEqual(st["vv_count"], 1)

    @patch("main.notify", return_value="ok")
    @patch("main.judge_topic")
    @patch("main.get_collectors", return_value=[])
    def test_run_round_empty_vv_writes_placeholder_no_push(self, m_col, m_judge, m_notify):
        """阶段一（2026-10-05）：无大V信号 → 写占位文件、不推 vv。"""
        m_judge.return_value = {"rating": "A", "track": "AI/科技工具", "hook_reason": "r",
                                "genre_score": 9, "fit_score": 8, "angle": "角度",
                                "act_now": True, "risk": "低", "model": "mock"}
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_cfg("config.yaml")
            cfg["db_path"] = os.path.join(tmp, "t.db")
            cfg["out_dir"] = tmp
            cfg["use_llm"] = False
            cfg["dry_run"] = True
            cfg["notify"] = {}
            res = run_round(cfg)
            self.assertEqual(res["status"], "ok")
            self.assertTrue(res["vv_path"])
            self.assertTrue(os.path.exists(res["vv_path"]))
            with open(res["vv_path"], encoding="utf-8") as fh:
                vv = fh.read()
            self.assertIn("今日暂无大V博文", vv)
            self.assertNotIn("vv", [p["kind"] for p in res["push"]])
            vv_state = os.path.join(tmp, "states", "vv_push_state.json")
            if os.path.exists(vv_state):
                with open(vv_state, encoding="utf-8") as fh:
                    st = json.load(fh)
                self.assertEqual(st.get("vv_count", 0), 0)
            else:
                self.assertFalse(os.path.exists(vv_state))

if __name__ == "__main__":
    unittest.main()
