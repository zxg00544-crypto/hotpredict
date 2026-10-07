# tests/test_db.py
import unittest, tempfile, os, datetime
from db import init_db, save_signals, history, prune
from collectors.base import Signal

def mk(key="ai模型", src="zhihu", eng=100.0, ts="2026-09-28T10:00:00"):
    return Signal(topic_key=key, source=src, title="t", url="u", heat=10.0,
                  rank=1, rank_delta=0, engagement=eng, author_weight=0.5,
                  fetched_at=ts, raw={})

class TestDB(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db")
        self.conn = init_db(self.path)

    def tearDown(self):
        self.conn.close(); os.unlink(self.path)

    def test_save_dedupes_same_key_source_ts(self):
        self.assertEqual(save_signals(self.conn, [mk(), mk()]), 1)
        self.assertEqual(save_signals(self.conn, [mk(src="weibo")]), 1)

    def test_history_groups_by_round_summing_engagement(self):
        # 防flake：默认窗口168h，写死绝对日期会在 7 天后滚出窗口（2026-10-05 复现）；改用相对时间，语义不变
        base = datetime.datetime.now() - datetime.timedelta(hours=6)
        t1 = base.isoformat()
        t2 = (base + datetime.timedelta(hours=2)).isoformat()
        save_signals(self.conn, [mk(eng=100, ts=t1),
                                 mk(src="weibo", eng=50, ts=t1),
                                 mk(eng=300, ts=t2)])
        h = history(self.conn, "ai模型")
        self.assertEqual(len(h), 2)
        self.assertEqual(h[0]["engagement"], 150)
        self.assertEqual(h[1]["engagement"], 300)
        self.assertEqual(h[0]["rank"], 1)

    def test_history_respects_hours_window(self):
        # 防flake：本机 datetime.now() 时钟分辨率可致 hours=0 的 cutoff==ts，前移1秒避开 >= 边界（2026-09-29 全量复检定位）
        ts = (datetime.datetime.now() - datetime.timedelta(seconds=1)).isoformat()
        save_signals(self.conn, [mk(ts=ts)])
        self.assertEqual(len(history(self.conn, "ai模型", hours=6)), 1)
        self.assertEqual(history(self.conn, "ai模型", hours=0), [])

class TestPrune(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db")
        self.conn = init_db(self.path)

    def tearDown(self):
        self.conn.close(); os.unlink(self.path)

    def test_prune_drops_older_than_8d_keeps_recent(self):
        old_ts = (datetime.datetime.now() - datetime.timedelta(days=9)).isoformat()
        new_ts = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        save_signals(self.conn, [mk(ts=old_ts), mk(src="weibo", ts=new_ts)])
        self.assertEqual(prune(self.conn, days=8), 1)
        left = self.conn.execute("select count(*) from signals").fetchone()[0]
        self.assertEqual(left, 1)

    def test_prune_noop_when_all_recent(self):
        save_signals(self.conn, [mk(ts=datetime.datetime.now().isoformat())])
        self.assertEqual(prune(self.conn, days=8), 0)

if __name__ == "__main__":
    unittest.main()
