# tests/test_vv_board.py — 阶段一：大V动向独立板块
import os
import tempfile
import unittest
import datetime

from collectors.base import Signal
from db import init_db, save_signals
from render.vv_board import (
    DEFAULTS, vv_cfg, fetch_rows, select_top, render_vv, plan_vv_push)


def sig(url, heat, ts=None, title="t", key=None, src="weibo_v", pub=""):
    return Signal(topic_key=key or ("k" + url), source=src, title=title,
                  url=url, heat=heat, rank=1, rank_delta=0,
                  engagement=heat, author_weight=1.0,
                  published_at=pub,
                  fetched_at=ts or datetime.datetime.now().isoformat(),
                  raw={})


def rfc822(dt):
    """把 aware datetime 转成微博发布时间的 RFC822 风格串（无逗号）。"""
    return dt.strftime("%a %b %d %H:%M:%S %z %Y")


def uid_url(uid, bid="Ab1Cd2", https="https"):
    return f"{https}://weibo.com/{uid}/{bid}"


class TestVVConfig(unittest.TestCase):
    def test_defaults_when_absent(self):
        self.assertEqual(vv_cfg({}), DEFAULTS)

    def test_defaults_when_empty_block(self):
        self.assertEqual(vv_cfg({"vv": {}}), DEFAULTS)

    def test_override_keeps_other_defaults(self):
        c = vv_cfg({"vv": {"file_top": 5}})
        self.assertEqual(c["file_top"], 5)
        self.assertEqual(c["window_hours"], 24)
        self.assertEqual(c["per_author"], 3)
        self.assertEqual(c["push_top"], 10)
        self.assertEqual(c["max_push_per_day"], 3)


class TestSelectTop(unittest.TestCase):
    def rows(self):
        return [
            {"title": "low", "url": uid_url(1, "b1"), "heat": 10.0,
             "fetched_at": "2026-10-05T01:00:00", "published_at": ""},
            {"title": "mid", "url": uid_url(2, "b2"), "heat": 50.0,
             "fetched_at": "2026-10-05T02:00:00", "published_at": ""},
            {"title": "high", "url": uid_url(3, "b3"), "heat": 90.0,
             "fetched_at": "2026-10-05T03:00:00", "published_at": ""},
        ]

    def test_orders_by_heat_desc(self):
        out = select_top(self.rows(), vv_cfg({}))
        self.assertEqual([r["title"] for r in out], ["high", "mid", "low"])

    def test_per_author_limit_three(self):
        rows = [{"title": f"p{i}", "url": uid_url(7, f"b{i}"),
                 "heat": float(100 - i), "fetched_at": "2026-10-05T01:00:00",
                 "published_at": ""} for i in range(5)]
        out = select_top(rows, vv_cfg({}))
        self.assertEqual(len(out), 3)
        self.assertEqual([r["title"] for r in out], ["p0", "p1", "p2"])

    def test_same_author_cap_not_crossed_by_extra_author(self):
        rows = [{"title": f"a{i}", "url": uid_url(1, f"x{i}"),
                 "heat": float(50 - i), "fetched_at": "2026-10-05T01:00:00"}
                for i in range(3)]
        rows += [{"title": f"b{i}", "url": uid_url(2, f"y{i}"),
                  "heat": float(40 - i), "fetched_at": "2026-10-05T01:00:00"}
                 for i in range(3)]
        out = select_top(rows, vv_cfg({}))
        self.assertEqual(len(out), 6)
        self.assertEqual(sum(1 for r in out if r["title"].startswith("a")), 3)
        self.assertEqual(sum(1 for r in out if r["title"].startswith("b")), 3)

    def test_url_dedup(self):
        u = uid_url(9, "same")
        rows = [{"title": "one", "url": u, "heat": 5.0,
                 "fetched_at": "2026-10-05T01:00:00"},
                {"title": "two", "url": u, "heat": 4.0,
                 "fetched_at": "2026-10-05T02:00:00"}]
        out = select_top(rows, vv_cfg({}))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "one")

    def test_file_top_cap(self):
        rows = [{"title": f"n{i}", "url": uid_url(100 + i, f"z{i}"),
                 "heat": float(1000 - i), "fetched_at": "2026-10-05T01:00:00"}
                for i in range(15)]
        out = select_top(rows, vv_cfg({"vv": {"file_top": 10}}))
        self.assertEqual(len(out), 10)

    def test_empty_url_dropped(self):
        rows = [{"title": "nourl", "url": "", "heat": 99.0,
                 "fetched_at": "2026-10-05T01:00:00"},
                {"title": "ok", "url": uid_url(3, "ok"), "heat": 1.0,
                 "fetched_at": "2026-10-05T01:00:00"}]
        out = select_top(rows, vv_cfg({}))
        self.assertEqual([r["title"] for r in out], ["ok"])


class TestRenderVV(unittest.TestCase):
    def item(self, i):
        return {"title": f"标题{i}", "url": uid_url(i, f"b{i}"), "heat": float(i),
                "fetched_at": "2026-10-05T01:00:00",
                "published_at": "Sat Oct 04 16:20:00 +0800 2026"}

    def test_renders_table_with_top10(self):
        md = render_vv([self.item(i) for i in range(1, 6)], "2026-10-05",
                       {"window_hours": 24, "per_author": 3, "file_top": 10,
                        "sources": ["weibo_v"]})
        self.assertIn("大V动向", md)
        self.assertIn("2026-10-05", md)
        self.assertIn("| 1 |", md)
        self.assertIn("标题1", md)
        self.assertIn("weibo_v", md)
        self.assertIn("24", md)

    def test_empty_items_message(self):
        md = render_vv([], "2026-10-05", {"window_hours": 24})
        self.assertIn("今日暂无大V博文", md)
        self.assertNotIn("| 1 |", md)


class TestPlanVvPush(unittest.TestCase):
    def items(self, n=3, tag="A"):
        return [{"title": f"{tag}{i}", "url": uid_url(10 + i, f"{tag}{i}"),
                 "heat": float(100 - i), "fetched_at": "2026-10-05T01:00:00",
                 "published_at": ""} for i in range(n)]

    def test_first_push_allowed(self):
        st = {}
        ok, title, content = plan_vv_push(self.items(), st, "2026-10-05",
                                          vv_cfg({}))
        self.assertTrue(ok)
        self.assertEqual(title, "大V动向 Top3")
        for i in range(3):
            self.assertIn(f"A{i}", content)
        self.assertEqual(st["vv_date"], "2026-10-05")
        self.assertEqual(st["vv_count"], 1)
        self.assertTrue(st["vv_sig"])

    def test_same_signature_skipped(self):
        st = {}
        plan_vv_push(self.items(), st, "2026-10-05", vv_cfg({}))
        ok, title, content = plan_vv_push(self.items(), st, "2026-10-05",
                                          vv_cfg({}))
        self.assertFalse(ok)
        self.assertEqual(title, "")
        self.assertEqual(content, "")
        self.assertEqual(st["vv_count"], 1)

    def test_changed_signature_pushed(self):
        st = {}
        plan_vv_push(self.items(tag="A"), st, "2026-10-05", vv_cfg({}))
        ok, title, content = plan_vv_push(self.items(tag="B"), st,
                                          "2026-10-05", vv_cfg({}))
        self.assertTrue(ok)
        self.assertIn("B0", content)
        self.assertEqual(st["vv_count"], 2)

    def test_daily_cap_blocks_push(self):
        st = {"vv_date": "2026-10-05", "vv_count": 3, "vv_sig": "old"}
        ok, _, _ = plan_vv_push(self.items(tag="C"), st, "2026-10-05",
                                vv_cfg({}))
        self.assertFalse(ok)
        self.assertEqual(st["vv_count"], 3)

    def test_new_date_resets_cap_and_sig(self):
        st = {"vv_date": "2026-10-04", "vv_count": 3, "vv_sig": "old"}
        ok, _, _ = plan_vv_push(self.items(tag="D"), st, "2026-10-05",
                                vv_cfg({}))
        self.assertTrue(ok)
        self.assertEqual(st["vv_date"], "2026-10-05")
        self.assertEqual(st["vv_count"], 1)

    def test_empty_items_no_push(self):
        st = {}
        ok, title, content = plan_vv_push([], st, "2026-10-05", vv_cfg({}))
        self.assertFalse(ok)
        self.assertEqual(st, {})


class TestFetchRows(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db")
        self.conn = init_db(self.path)

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_window_and_source_filter(self):
        now = datetime.datetime.now()
        fresh = (now - datetime.timedelta(hours=1)).isoformat()
        stale = (now - datetime.timedelta(hours=30)).isoformat()
        save_signals(self.conn, [
            sig(uid_url(1, "f1"), 10.0, ts=fresh, key="fresh"),
            sig(uid_url(1, "f2"), 20.0, ts=stale, key="stale"),
            sig("https://example.com/x", 30.0, ts=fresh, key="other",
                src="weibo"),
        ])
        rows = fetch_rows(self.conn, 24)
        self.assertEqual([r["title"] for r in rows], ["t"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], uid_url(1, "f1"))

    def test_ordered_by_heat_desc(self):
        now = datetime.datetime.now().isoformat()
        save_signals(self.conn, [
            sig(uid_url(1, "l"), 5.0, ts=now, key="l"),
            sig(uid_url(2, "h"), 95.0, ts=now, key="h"),
        ])
        rows = fetch_rows(self.conn, 24)
        self.assertEqual(rows[0]["heat"], 95.0)
        self.assertEqual(rows[1]["heat"], 5.0)

    def test_empty_db_returns_no_rows(self):
        self.assertEqual(fetch_rows(self.conn, 24), [])

    def test_published_at_inside_window_kept(self):
        now = datetime.datetime.now().astimezone()
        fresh = (now - datetime.timedelta(hours=1)).isoformat()
        pub = rfc822(now - datetime.timedelta(hours=2))
        save_signals(self.conn, [
            sig(uid_url(1, "in"), 10.0, ts=fresh, key="in", pub=pub),
        ])
        rows = fetch_rows(self.conn, 24)
        self.assertEqual([r["title"] for r in rows], ["t"])

    def test_old_published_at_filtered_by_publish_window(self):
        now = datetime.datetime.now().astimezone()
        fresh = (now - datetime.timedelta(hours=1)).isoformat()
        old_pub = rfc822(now - datetime.timedelta(days=40))
        save_signals(self.conn, [
            sig(uid_url(1, "old"), 999.0, ts=fresh, key="old", pub=old_pub),
        ])
        rows = fetch_rows(self.conn, 24)
        self.assertEqual(rows, [])

    def test_unparseable_published_at_kept(self):
        now = datetime.datetime.now().astimezone()
        fresh = (now - datetime.timedelta(hours=1)).isoformat()
        save_signals(self.conn, [
            sig(uid_url(1, "empty"), 10.0, ts=fresh, key="empty", pub=""),
            sig(uid_url(2, "bad"), 20.0, ts=fresh, key="bad", pub="not-a-date"),
        ])
        rows = fetch_rows(self.conn, 24)
        self.assertEqual(sorted(r["url"] for r in rows),
                         sorted([uid_url(1, "empty"), uid_url(2, "bad")]))


if __name__ == "__main__":
    unittest.main()
