# tests/test_db.py
import unittest, tempfile, os, datetime
from db import init_db, save_signals, history
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
        save_signals(self.conn, [mk(eng=100, ts="2026-09-28T10:00:00"),
                                 mk(src="weibo", eng=50, ts="2026-09-28T10:00:00"),
                                 mk(eng=300, ts="2026-09-28T12:00:00")])
        h = history(self.conn, "ai模型")
        self.assertEqual(len(h), 2)
        self.assertEqual(h[0]["engagement"], 150)
        self.assertEqual(h[1]["engagement"], 300)
        self.assertEqual(h[0]["rank"], 1)

    def test_history_respects_hours_window(self):
        ts = datetime.datetime.now().isoformat()
        save_signals(self.conn, [mk(ts=ts)])
        self.assertEqual(len(history(self.conn, "ai模型", hours=6)), 1)
        self.assertEqual(history(self.conn, "ai模型", hours=0), [])

if __name__ == "__main__":
    unittest.main()
