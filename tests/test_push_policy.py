import unittest, tempfile, os, json
from render.push_policy import plan_push, load_state, save_state


def T(key, rating, title=None, score=50, breaking=False):
    return {"key": key, "rating": rating, "title": title or key, "score": score,
            "track": "科技", "angle": "角度", "hook_reason": "理由", "url": "u",
            "breaking": breaking}


class Signal:
    """模拟 collectors 的 Signal 对象：非 JSON 可序列化（复现 2026-09-29 崩溃源）。"""
    def __init__(self, topic_key, url="u"):
        self.topic_key = topic_key
        self.url = url

    def __repr__(self):
        return "Signal(%r)" % self.topic_key


PROJ_FIELDS = {"key", "title", "rating", "score", "angle", "hook_reason",
               "url", "track", "breaking", "batch_window"}


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

    def test_a_only_one_per_window_with_backlog(self):
        """回归（2026-09-30 洪水 bug）：上窗口遗留多条时，切换后每窗口只放行 1 条，
        同窗口第 2 轮不再放行。"""
        st = {}
        fast = [T(f"a{i}", "A", score=50 + i) for i in range(3)]
        plan_push(st, "2026-09-30", fast, [], False, [], "b.html", hour=1)  # 窗口0入池3条
        m1 = plan_push(st, "2026-09-30", fast, [], False, [], "b.html", hour=5)  # 切窗口1
        self.assertEqual(len([m for m in m1 if m[0] == "a"]), 1)
        m2 = plan_push(st, "2026-09-30", fast, [], False, [], "b.html", hour=6)  # 同窗口1第2轮
        self.assertEqual([m for m in m2 if m[0] == "a"], [])               # 不再放行
        m3 = plan_push(st, "2026-09-30", fast, [], False, [], "b.html", hour=7)  # 同窗口仍挡
        self.assertEqual([m for m in m3 if m[0] == "a"], [])
        m4 = plan_push(st, "2026-09-30", fast, [], False, [], "b.html", hour=9)  # 切窗口2
        self.assertEqual(len([m for m in m4 if m[0] == "a"]), 1)
        self.assertEqual(len(st["a_pending"]), 1)                        # 只消耗 2 条

    def test_a_pushed_window_resets_across_days(self):
        """跨日 reset 后 a_pushed_window 清空，新一天首窗口可推。"""
        st = {"date": "2026-09-29", "daily_done": True, "alert_date": "2026-09-29",
              "a_pending": [T("old1", "A", score=70)], "pushed": [], "a_seen": {},
              "a_pushed_window": 1}
        st["a_pending"][0]["batch_window"] = 4  # 昨天窗口遗留，今天 w=0 不同
        msgs = plan_push(st, "2026-09-30", [], [], False, [], "b.html", hour=1)
        self.assertEqual([m[0] for m in msgs if m[0] == "a"], ["a"])

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

    # —— 2026-09-29 崩溃回归：Signal 对象不得进 state + 原子写 ——
    def test_signal_topic_roundtrip_no_crash(self):
        """完整 plan_push → save_state → load_state 往返：不抛错、落盘合法 JSON、
        重新加载的 a_pending 每项只含投影字段、无 Signal。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "st.json")
            topic = T("a1", "A", score=60)
            topic["signals"] = [Signal("a1", url="https://x/%E4%B8%AD")]
            topic["sources"] = ["zhihu"]
            topic["n_sources"] = 1
            st = load_state(p)                       # 空状态
            plan_push(st, "2026-09-29", [topic], [], False, [], "b.html", hour=2)
            self.assertEqual(len(st["a_pending"]), 1)
            save_state(p, st)                        # 修复前：此处抛 TypeError（Signal 不可序列化）
            with open(p, encoding="utf-8") as f:
                reloaded = json.load(f)              # 落盘必须是合法 JSON
            self.assertEqual(reloaded["date"], "2026-09-29")
            self.assertEqual(len(reloaded["a_pending"]), 1)
            item = reloaded["a_pending"][0]
            self.assertEqual(set(item.keys()), PROJ_FIELDS)
            self.assertNotIn("signals", item)
            self.assertIsInstance(item["key"], str)
            self.assertEqual(item["batch_window"], 0)   # hour=2 → 窗口 0

    def test_save_state_atomic_on_unserializable(self):
        """直接对含不可序列化对象的 state 调 save_state：异常必须抛出、
        目标文件逐字节不变、同目录无临时文件残留。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "st.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write('{"date": "2026-09-29"}')
            with open(p, "rb") as f:
                before = f.read()
            with self.assertRaises(TypeError):
                save_state(p, {"date": "2026-09-29", "bad": Signal("x")})
            with open(p, "rb") as f:
                self.assertEqual(f.read(), before)            # 原文件逐字节一致
            leftovers = [n for n in os.listdir(d) if ".tmp." in n]
            self.assertEqual(leftovers, [])                   # 无临时文件残留

    def test_save_state_atomic_replaces_existing_on_success(self):
        """原子写成功路径：旧内容被完整新内容覆盖，无临时残留。"""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "st.json")
            save_state(p, {"date": "2026-09-28", "pushed": ["a"]})
            save_state(p, {"date": "2026-09-29", "pushed": ["a", "b"]})
            with open(p, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["pushed"], ["a", "b"])
            self.assertEqual([n for n in os.listdir(d) if ".tmp." in n], [])

    def test_legacy_state_without_new_fields_upgrades(self):
        st = {"date": "2026-09-28", "daily_done": True, "a_count": 2,
              "pushed_a": ["x"], "alert_date": "2026-09-28"}
        msgs = plan_push(st, "2026-09-28", [T("x", "A")], [], False, [], "b.html", hour=10)
        self.assertEqual([m[0] for m in msgs], [])     # pushed_a 迁移，不重复推


if __name__ == "__main__":
    unittest.main()
