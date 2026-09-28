# tests/test_notifier.py
import unittest
from unittest.mock import patch, MagicMock
from render.notifier import notify, build_push_payload, _dingtalk

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

    # —— 钉钉 ——
    @patch("render.notifier.requests.post")
    def test_dingtalk_primary_success(self, m):
        m.return_value = MagicMock(json=lambda: {"errcode": 0, "errmsg": "ok"})
        out = notify("⚡突发 X", "内容", {"notify": {
            "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=tok",
            "serverchan_sendkey": "SCT123"}})
        self.assertEqual(out, "dingtalk")
        url = m.call_args[0][0]
        self.assertIn("access_token=tok", url)
        body = m.call_args[1]["json"]
        self.assertEqual(body["msgtype"], "markdown")
        self.assertEqual(body["markdown"]["title"], "⚡突发 X")
        self.assertIn("内容", body["markdown"]["text"])

    @patch("render.notifier.requests.post")
    def test_dingtalk_secret_signs_url(self, m):
        m.return_value = MagicMock(json=lambda: {"errcode": 0})
        _dingtalk("https://oapi.dingtalk.com/robot/send?access_token=tok",
                  "SECxxx", "t", "c")
        url = m.call_args[0][0]
        self.assertIn("timestamp=", url)
        self.assertIn("sign=", url)

    @patch("render.notifier._toast", return_value="toast")
    @patch("render.notifier.requests.post")
    def test_dingtalk_fail_falls_back_to_serverchan(self, m_post, m_toast):
        ding_err = MagicMock(json=lambda: {"errcode": 310000, "errmsg": "sign not match"})
        sc_ok = MagicMock(status_code=200, json=lambda: {"code": 0})
        m_post.side_effect = [ding_err, sc_ok]
        out = notify("t", "c", {"notify": {
            "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=tok",
            "serverchan_sendkey": "SCT123"}})
        self.assertEqual(out, "serverchan")
        self.assertEqual(m_post.call_count, 2)


    @patch("render.notifier.requests.post")
    def test_dingtalk_keyword_injected_when_missing(self, m):
        m.return_value = MagicMock(json=lambda: {"errcode": 0, "errmsg": "ok"})
        notify("⚡突发 X", "正文内容", {"notify": {
            "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=tok",
            "dingtalk_secret": "SEC1", "dingtalk_keyword": "热点预判"}})
        text = m.call_args[1]["json"]["markdown"]["text"]
        self.assertIn("【热点预判】", text)
        url = m.call_args[0][0]
        self.assertIn("timestamp=", url)
        self.assertIn("sign=", url)

    @patch("render.notifier.requests.post")
    def test_dingtalk_keyword_not_duplicated_when_present(self, m):
        m.return_value = MagicMock(json=lambda: {"errcode": 0, "errmsg": "ok"})
        notify("热点预判·晚报", "正文", {"notify": {
            "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=tok",
            "dingtalk_keyword": "热点预判"}})
        text = m.call_args[1]["json"]["markdown"]["text"]
        self.assertEqual(text.count("【热点预判】"), 0)
        self.assertEqual(text.count("热点预判"), 1)   # 仅标题里 1 次


if __name__ == "__main__":
    unittest.main()
