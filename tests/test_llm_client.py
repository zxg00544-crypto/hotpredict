# tests/test_llm_client.py
import unittest, json
from probe_llm import load_llm_cfg, pick_model


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


if __name__ == "__main__":
    unittest.main()
