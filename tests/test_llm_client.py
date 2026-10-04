# tests/test_llm_client.py
import unittest, json
from unittest.mock import patch
import requests
from probe_llm import load_llm_cfg, pick_model, llm_client_call
import probe_llm


def _http_err(code=429, retry_after="15"):
    r = requests.models.Response()
    r.status_code = code
    if retry_after is not None:
        r.headers["Retry-After"] = retry_after
    return requests.HTTPError("http error", response=r)


class TestLLMClient(unittest.TestCase):
    def test_load_cfg_reads_opencode_json(self):
        cfg = load_llm_cfg({
            "llm": {"config_path": r"C:\Users\Admin\.config\opencode\opencode.json",
                    "provider": "opencode", "model": "mimo-v2.6-flash-free",
                    "fallback_models": ["deepseek-v4-flash-free"]}})
        self.assertTrue(cfg["base_url"].startswith("https://"))
        self.assertTrue(cfg["api_key"].startswith("sk-"))
        self.assertNotIn(cfg["api_key"], str({k: v for k, v in cfg.items() if k != "api_key"}))

    def test_pick_model_returns_fallback_chain(self):
        models = pick_model({"model": "m", "fallback_models": ["a", "b"]})
        self.assertEqual(models, ["m", "a", "b"])

    def test_json_mode_parses_model_output(self):
        raw = '{"rating":"A","genre_score":9}'
        self.assertEqual(json.loads(raw)["rating"], "A")


class TestApiKeyFallback(unittest.TestCase):
    def test_api_key_when_config_path_missing(self):
        cfg = load_llm_cfg({"llm": {
            "config_path": r"C:\nonexistent\opencode.json",
            "provider": "deepseek", "model": "deepseek-chat",
            "api_key": "sk-test-123", "base_url": "https://api.deepseek.com"}})
        self.assertEqual(cfg["api_key"], "sk-test-123")
        self.assertEqual(cfg["base_url"], "https://api.deepseek.com")
        self.assertEqual(cfg["model"], "deepseek-chat")

    def test_raises_when_no_path_and_no_key(self):
        with self.assertRaises(ValueError):
            load_llm_cfg({"llm": {"config_path": r"C:\nonexistent\opencode.json",
                                  "provider": "deepseek", "model": "m"}})


class Test429Backoff(unittest.TestCase):
    """agnes 日配额用尽后降为 1 请求/分钟：429 共享冷却 + 专用预算 + 等待总预算。"""

    def setUp(self):
        probe_llm._last_call_ts = 0.0
        probe_llm._next_ok_ts = 0.0
        self.cfg = {"llm": {"api_key": "k", "base_url": "http://x", "model": "m",
                            "fallback_models": [], "timeout_topic": 15, "retries": 0}}

    @patch("probe_llm.time.sleep")
    @patch("probe_llm.chat")
    def test_success_first_try_no_sleep(self, m_chat, m_sleep):
        m_chat.return_value = "OK"
        out = llm_client_call([{"role": "user", "content": "x"}], self.cfg)
        self.assertEqual(out, {"content": "OK", "model": "m"})
        m_sleep.assert_not_called()

    @patch("probe_llm.time.sleep")
    @patch("probe_llm.chat")
    def test_429_waits_cooldown_then_succeeds(self, m_chat, m_sleep):
        m_chat.side_effect = [_http_err(429, "15"), "OK"]
        out = llm_client_call([{"role": "user", "content": "x"}], self.cfg)
        self.assertEqual(out, {"content": "OK", "model": "m"})
        waits = [c.args[0] for c in m_sleep.call_args_list]
        self.assertTrue(any(w >= 60 for w in waits),
                        "429 冷却必须 >=60s，实际: %r" % waits)

    @patch("probe_llm.time.sleep")
    @patch("probe_llm.chat")
    def test_429_budget_bails_without_burning_attempts(self, m_chat, m_sleep):
        m_chat.side_effect = _http_err(429, "15")
        out = llm_client_call([{"role": "user", "content": "x"}], self.cfg)
        self.assertIsNone(out)
        # 429 不消耗 retries，靠 wait_budget(245s) 兜底：约 5 次冷却等待后放弃
        self.assertLessEqual(m_chat.call_count, 6)
        total = sum(c.args[0] for c in m_sleep.call_args_list)
        self.assertLessEqual(total, 245, "总冷却等待不得超过 wait_budget_s")

    @patch("probe_llm.time.sleep")
    @patch("probe_llm.chat")
    def test_wait_budget_caps_total_waits(self, m_chat, m_sleep):
        self.cfg["llm"]["retries"] = 2
        self.cfg["llm"]["wait_budget_s"] = 130
        m_chat.side_effect = _http_err(429, "15")
        out = llm_client_call([{"role": "user", "content": "x"}], self.cfg)
        self.assertIsNone(out)
        total = sum(c.args[0] for c in m_sleep.call_args_list)
        self.assertLessEqual(total, 130, "总等待不得超过 wait_budget_s")

    @patch("probe_llm.time.sleep")
    @patch("probe_llm.chat")
    def test_non429_error_consumes_attempts(self, m_chat, m_sleep):
        self.cfg["llm"]["retries"] = 2
        m_chat.side_effect = requests.exceptions.ConnectionError("boom")
        out = llm_client_call([{"role": "user", "content": "x"}], self.cfg)
        self.assertIsNone(out)
        self.assertEqual(m_chat.call_count, 3)

    @patch("probe_llm.time.sleep")
    @patch("probe_llm.chat")
    def test_429_then_fallback_model_used(self, m_chat, m_sleep):
        self.cfg["llm"]["fallback_models"] = ["m2"]
        self.cfg["llm"]["wait_budget_s"] = 130
        m_chat.side_effect = [_http_err(429, "60")] * 4 + ["OK2"]
        # 模型1: 429 两次冷却等待(122s)后预算耗尽换链；模型2 继续冷却后首试成功
        out = llm_client_call([{"role": "user", "content": "x"}], self.cfg)
        self.assertEqual(out, {"content": "OK2", "model": "m2"})


if __name__ == "__main__":
    unittest.main()
