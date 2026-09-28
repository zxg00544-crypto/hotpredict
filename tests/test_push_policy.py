import unittest, tempfile, os, json
from render.push_policy import plan_push, load_state, save_state


def T(key, rating, title=None):
    return {"key": key, "rating": rating, "title": title or key,
            "track": "科技", "angle": "角度", "hook_reason": "理由", "url": "u"}


class TestPushPolicy(unittest.TestCase):
    def test_first_run_daily_and_alert(self):
        st, fast = {}, [T("a1", "A")]
        msgs = plan_push(st, "2026-09-28", fast, [], True, [], "b.html")
        kinds = [m[0] for m in msgs]
        self.assertIn("daily", kinds)
        self.assertIn("alert", kinds)
        self.assertTrue(st["daily_done"])
        self.assertEqual(st["alert_date"], "2026-09-28")

    def test_same_day_no_repeat_daily_or_alert(self):
        st = {"date": "2026-09-28", "daily_done": True, "a_count": 0,
              "pushed_a": [], "alert_date": "2026-09-28"}
        msgs = plan_push(st, "2026-09-28", [T("a1", "A")], [], True, ["x"], "b.html")
        self.assertEqual([m[0] for m in msgs], ["a"])

    def test_a_dedup(self):
        st = {"date": "2026-09-28", "daily_done": True, "a_count": 0,
              "pushed_a": [], "alert_date": ""}
        plan_push(st, "2026-09-28", [T("a1", "A")], [], False, [], "b.html")
        msgs = plan_push(st, "2026-09-28", [T("a1", "A")], [], False, [], "b.html")
        self.assertEqual(msgs, [])

    def test_a_cap_two(self):
        st = {"date": "2026-09-28", "daily_done": True, "a_count": 0,
              "pushed_a": [], "alert_date": ""}
        fast = [T(f"a{i}", "A") for i in range(5)]
        msgs = plan_push(st, "2026-09-28", fast, [], False, [], "b.html")
        self.assertEqual([m[0] for m in msgs], ["a", "a"])
        msgs2 = plan_push(st, "2026-09-28", fast, [], False, [], "b.html")
        self.assertEqual(msgs2, [])

    def test_b_c_no_push(self):
        st = {"date": "2026-09-28", "daily_done": True, "a_count": 0,
              "pushed_a": [], "alert_date": ""}
        msgs = plan_push(st, "2026-09-28", [T("b1", "B"), T("c1", "C")], [],
                         False, [], "b.html")
        self.assertEqual(msgs, [])

    def test_next_day_reset(self):
        st = {"date": "2026-09-28", "daily_done": True, "a_count": 2,
              "pushed_a": ["x"], "alert_date": "2026-09-28"}
        msgs = plan_push(st, "2026-09-29", [T("a1", "A")], [], True, [], "b.html")
        kinds = [m[0] for m in msgs]
        self.assertIn("daily", kinds)
        self.assertIn("a", kinds)
        self.assertIn("alert", kinds)

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s", "st.json")
            save_state(p, {"date": "2026-09-28"})
            self.assertEqual(load_state(p)["date"], "2026-09-28")
            self.assertEqual(load_state(os.path.join(d, "none.json")), {})

    def test_daily_digest_a_first_then_fill(self):
        st = {}
        msgs = plan_push(st, "2026-09-28", [T("a1", "A"), T("b1", "B")],
                         [], False, [], "D:\\b.html")
        daily = [m for m in msgs if m[0] == "daily"][0]
        self.assertIn("A级优先", daily[2])
        self.assertIn("1. [A] a1", daily[2])
        self.assertIn("b1", daily[2])
        self.assertIn("D:\\b.html", daily[2])

    def test_daily_digest_no_a_still_lists_top3(self):
        st = {}
        msgs = plan_push(st, "2026-09-28",
                         [T(f"b{i}", "B") for i in range(1, 5)],
                         [], False, [], "D:\\b.html")
        daily = [m for m in msgs if m[0] == "daily"][0]
        self.assertIn("暂无A级", daily[2])
        self.assertIn("[B] b1", daily[2])
        self.assertIn("b3", daily[2])
        self.assertNotIn("b4", daily[2])


if __name__ == "__main__":
    unittest.main()
