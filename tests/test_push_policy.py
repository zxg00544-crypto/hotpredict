import unittest, tempfile, os, json
from render.push_policy import plan_push, load_state, save_state


def T(key, rating, title=None, score=50, breaking=False):
    return {"key": key, "rating": rating, "title": title or key, "score": score,
            "track": "科技", "angle": "角度", "hook_reason": "理由", "url": "u",
            "breaking": breaking}


class TestPushPolicy(unittest.TestCase):
    # —— 晚报 21:00 门禁 ——
    def test_daily_gated_until_21(self):
        st = {}
        msgs = plan_push(st, "2026-09-28", [], [], False, [], "b.html", hour=10)
        self.assertEqual(msgs, [])
        self.assertFalse(st["daily_done"])
        plan_push(st, "2026-09-28", [], [], False, [], "b.html", hour=21)
        self.assertTrue(st["daily_done"])

    def test_daily_immediate_when_hour_none(self):
        st = {}
        msgs = plan_push(st, "2026-09-28", [], [], False, [], "b.html")
        self.assertEqual([m[0] for m in msgs], ["daily"])

    # —— ⚡突发即时 ——
    def test_breaking_pushed_immediately_even_if_b(self):
        st = {}
        msgs = plan_push(st, "2026-09-28", [T("b1", "B", breaking=True)],
                         [], False, [], "b.html", hour=10)
        self.assertEqual([m[0] for m in msgs], ["breaking"])
        self.assertTrue(msgs[0][1].startswith("⚡突发"))

    def test_breaking_dedup(self):
        st = {}
        fast = [T("b1", "B", breaking=True)]
        plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=10)
        msgs = plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=11)
        self.assertEqual(msgs, [])

    def test_breaking_daily_cap(self):
        st = {}
        fast = [T(f"b{i}", "B", breaking=True) for i in range(8)]
        msgs = plan_push(st, "2026-09-28", fast, [], False, [], "b.html",
                         hour=10, breaking_cap=6)
        self.assertEqual(len([m for m in msgs if m[0] == "breaking"]), 6)
        self.assertEqual(st["breaking_count"], 6)
        # 同日下一轮不超帽
        msgs2 = plan_push(st, "2026-09-28", fast, [], False, [], "b.html",
                          hour=11, breaking_cap=6)
        self.assertEqual([m for m in msgs2 if m[0] == "breaking"], [])

    def test_breaking_count_resets_next_day(self):
        st = {"date": "2026-09-28", "daily_done": True, "alert_date": "2026-09-28",
              "a_pending": [], "pushed": [], "a_seen": {}, "breaking_count": 6}
        fast = [T("nb1", "B", breaking=True)]
        msgs = plan_push(st, "2026-09-29", fast, [], False, [], "b.html",
                         hour=10, breaking_cap=6)
        self.assertIn("breaking", [m[0] for m in msgs])
        self.assertEqual(st["breaking_count"], 1)

    def test_breaking_topic_not_double_pushed_as_a(self):
        st = {}
        fast = [T("a1", "A", score=90, breaking=True)]
        msgs = plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=10)
        self.assertEqual([m[0] for m in msgs], ["breaking"])
        msgs2 = plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=13)
        self.assertEqual([m[0] for m in msgs2], [])  # 同窗口不再批推

    # —— A 级攒批择优（每 4 小时窗口）——
    def test_a_waits_for_window_boundary(self):
        st = {}
        fast = [T("a1", "A", score=60)]
        msgs = plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=2)
        self.assertEqual(msgs, [])                    # 窗口内不即时
        self.assertEqual(len(st["a_pending"]), 1)
        msgs = plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=5)
        self.assertEqual([m[0] for m in msgs], ["a"])  # 窗口切换推 1 条

    def test_a_batch_picks_highest_score_not_first_arrival(self):
        st = {}
        fast = [T("a1", "A", score=60), T("a2", "A", score=90), T("a3", "A", score=75)]
        plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=2)
        msgs = plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=5)
        self.assertEqual(len(msgs), 1)
        self.assertIn("a2", msgs[0][1])               # 择优：最高分先走
        self.assertEqual(len(st["a_pending"]), 2)      # 其余留存

    def test_a_uncapped_across_batches(self):
        st = {}
        fast = [T(f"a{i}", "A", score=50 + i) for i in range(4)]
        plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=1)
        n = 0
        for h in (5, 9, 13, 17):                      # 4 个窗口 → 4 条，无 2 条上限
            for m in plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=h):
                if m[0] == "a":
                    n += 1
        self.assertEqual(n, 4)

    def test_a_dedup_after_push(self):
        st = {}
        fast = [T("a1", "A", score=60)]
        plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=1)
        plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=5)
        msgs = plan_push(st, "2026-09-28", fast, [], False, [], "b.html", hour=9)
        self.assertEqual(msgs, [])

    def test_pending_survives_date_rollover(self):
        st = {"date": "2026-09-28", "daily_done": True, "alert_date": "2026-09-28",
              "a_pending": [], "pushed": [], "a_seen": {}}
        p = T("a9", "A", score=80)
        p["batch_window"] = 5
        st["a_pending"] = [p]
        msgs = plan_push(st, "2026-09-28", [], [], False, [], "b.html", hour=21)
        self.assertEqual(msgs, [])                     # 同窗口不重复批推
        msgs = plan_push(st, "2026-09-29", [], [], False, [], "b.html", hour=0)
        self.assertEqual([m[0] for m in msgs], ["a"])  # 跨日补推不丢
        self.assertEqual(len(st["a_pending"]), 0)
        self.assertFalse(st["daily_done"])

    # —— B/C 不打扰 / 告警 / 晚报内容 ——
    def test_b_c_no_push(self):
        st = {}
        msgs = plan_push(st, "2026-09-28", [T("b1", "B"), T("c1", "C")],
                         [], False, [], "b.html", hour=10)
        self.assertEqual(msgs, [])

    def test_alert_once_per_day(self):
        st = {}
        plan_push(st, "2026-09-28", [], [], True, ["x"], "b.html", hour=10)
        msgs = plan_push(st, "2026-09-28", [], [], True, ["x"], "b.html", hour=11)
        self.assertEqual([m[0] for m in msgs], [])

    def test_daily_digest_lists_all_a_from_a_seen(self):
        st = {}
        fast = [T("a1", "A", score=60), T("b1", "B", score=70)]
        msgs = plan_push(st, "2026-09-28", fast, [], False, [], "D:\\b.html", hour=21)
        daily = [m for m in msgs if m[0] == "daily"][0]
        self.assertIn("A级优先", daily[2])
        self.assertIn("1. [A] a1", daily[2])
        self.assertIn("b1", daily[2])
        self.assertIn("D:\\b.html", daily[2])

    def test_daily_digest_no_a_lists_top3(self):
        st = {}
        msgs = plan_push(st, "2026-09-28",
                         [T(f"b{i}", "B") for i in range(1, 5)],
                         [], False, [], "D:\\b.html", hour=21)
        daily = [m for m in msgs if m[0] == "daily"][0]
        self.assertIn("暂无A级", daily[2])
        self.assertIn("[B] b1", daily[2])
        self.assertIn("b3", daily[2])
        self.assertNotIn("b4", daily[2])

    def test_next_day_resets_daily_and_alert(self):
        st = {"date": "2026-09-28", "daily_done": True, "alert_date": "2026-09-28",
              "a_pending": [], "pushed": [], "a_seen": {}}
        msgs = plan_push(st, "2026-09-29", [T("a1", "A")], [], True, [], "b.html", hour=21)
        kinds = [m[0] for m in msgs]
        self.assertIn("daily", kinds)
        self.assertIn("alert", kinds)
        self.assertNotIn("a", kinds)                   # 当日新 A 入池等下一窗口
        st2 = {"date": "2026-09-28", "daily_done": True, "alert_date": "2026-09-28",
               "a_pending": [], "pushed": [], "a_seen": {}}
        p = T("aold", "A", score=70)
        p["batch_window"] = 0
        st2["a_pending"] = [p]
        msgs2 = plan_push(st2, "2026-09-29", [], [], True, [], "b.html", hour=21)
        self.assertIn("a", [m[0] for m in msgs2])       # 昨日攒批池跨日补推

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s", "st.json")
            save_state(p, {"date": "2026-09-28"})
            self.assertEqual(load_state(p)["date"], "2026-09-28")
            self.assertEqual(load_state(os.path.join(d, "none.json")), {})

    def test_legacy_state_without_new_fields_upgrades(self):
        st = {"date": "2026-09-28", "daily_done": True, "a_count": 2,
              "pushed_a": ["x"], "alert_date": "2026-09-28"}
        msgs = plan_push(st, "2026-09-28", [T("x", "A")], [], False, [], "b.html", hour=10)
        self.assertEqual([m[0] for m in msgs], [])     # pushed_a 迁移，不重复推


if __name__ == "__main__":
    unittest.main()
