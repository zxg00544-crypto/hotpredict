# tests/test_notifier.py
import unittest
from unittest.mock import patch, MagicMock
from render.notifier import notify, build_push_payload

class TestNotifier(unittest.TestCase):
    def test_skipped_when_no_key_and_no_fallback(self):
        out = notify("t", "c", {"notify": {"serverchan_sendkey": ""},
                                "notify_fallback": False})
        self.assertEqual(out, "skipped")

    @patch("render.notifier.requests.post")
    def test_serverchan_success(self, m):
        m.return_value = MagicMock(status_code=200,
                                   json=lambda: {"code": 0, "data": {"pushid": "1"}})
        out = notify("测试", "内容", {"notify": {"serverchan_sendkey": "SCT123"}})
        self.assertEqual(out, "serverchan")
        self.assertIn("SCT123", m.call_args[0][0])

    @patch("render.notifier._toast", return_value="toast")
    @patch("render.notifier.requests.post")
    def test_serverchan_failure_falls_back_to_toast(self, m_post, m_toast):
        m_post.return_value = MagicMock(status_code=500,
                                        json=lambda: (_ for _ in ()).throw(Exception("500")))
        out = notify("t", "c", {"notify": {"serverchan_sendkey": "SCT123"}})
        self.assertEqual(out, "toast")

    def test_build_push_payload_truncates_long_content(self):
        p = build_push_payload("标题", "x" * 3000)
        self.assertLessEqual(len(p["desp"]), 2600)
        self.assertTrue(p["title"].startswith("标题"))

if __name__ == "__main__":
    unittest.main()
