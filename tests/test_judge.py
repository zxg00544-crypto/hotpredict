# tests/test_judge.py
import unittest, json
from unittest.mock import patch
from llm_judge.prompt import build_pack, build_messages, pick_track
from llm_judge.judge import judge_topic, parse_rating

TOPIC = {"key": "k", "title": "大模型发布 Agent 框架", "sources": ["zhihu", "weibo"],
         "n_sources": 2, "score": 72.0, "G": 85.0, "heat": 1200, "age_hours": 3,
         "url": "https://x", "reason": "增速快"}

class TestJudge(unittest.TestCase):
    def test_build_pack_contains_required_fields(self):
        p = build_pack(TOPIC, "快讯档")
        self.assertEqual(p["bucket"], "快讯档")
        self.assertIn("title", p); self.assertIn("sources", p)
        self.assertIn("score", p); self.assertIn("url", p)

    def test_pick_track_matches_genre_words(self):
        self.assertEqual(pick_track("AI 大模型 Agent 框架发布",
                                    {"AI/科技工具": ["AI", "Agent"]}), "AI/科技工具")
        self.assertEqual(pick_track("无关标题", {"AI/科技工具": ["AI"]}), "其他")

    @patch("llm_judge.judge.llm_client_call")
    def test_track_not_in_whitelist_is_dropped(self, mock_call):
        mock_call.return_value = {"content": json.dumps(
            {"rating": "B", "track": "0.0", "hook_reason": "x",
             "genre_score": 7, "fit_score": 6}), "model": "m"}
        cfg = {"tracks": {"财经": ["股市"], "科技": ["AI"]}}
        obj = judge_topic(build_pack(TOPIC, "快讯档"), cfg)
        self.assertNotIn("track", obj)

    @patch("llm_judge.judge.llm_client_call")
    def test_track_in_whitelist_kept(self, mock_call):
        mock_call.return_value = {"content": json.dumps(
            {"rating": "B", "track": "财经", "hook_reason": "x",
             "genre_score": 7, "fit_score": 6}), "model": "m"}
        cfg = {"tracks": {"财经": ["股市"], "科技": ["AI"]}}
        obj = judge_topic(build_pack(TOPIC, "快讯档"), cfg)
        self.assertEqual(obj["track"], "财经")

    def test_build_messages_asks_for_json_schema(self):
        msgs = build_messages(build_pack(TOPIC, "快讯档"))
        joined = msgs[0]["content"]
        for field in ["rating", "track", "hook_reason", "genre_score", "fit_score",
                      "angle", "act_now", "risk", "A", "B", "C"]:
            self.assertIn(field, joined)

    def test_parse_rating_valid(self):
        out = parse_rating('{"rating":"A","track":"AI/科技工具","hook_reason":"r",'
                           '"genre_score":9,"fit_score":8,"angle":"a",'
                           '"act_now":true,"risk":"低"}')
        self.assertEqual(out["rating"], "A")
        self.assertEqual(out["genre_score"], 9)

    def test_parse_rating_rejects_bad_json_and_bad_rating(self):
        self.assertIsNone(parse_rating("not json"))
        self.assertIsNone(parse_rating('{"rating":"D"}'))

    @patch("llm_judge.judge.llm_client_call")
    def test_judge_topic_returns_none_when_client_fails(self, m):
        m.return_value = None
        self.assertIsNone(judge_topic(build_pack(TOPIC, "快讯档"), {}))

    @patch("llm_judge.judge.llm_client_call")
    def test_judge_topic_parses_success(self, m):
        m.return_value = {"content": json.dumps({
            "rating": "A", "track": "AI/科技工具", "hook_reason": "r",
            "genre_score": 9, "fit_score": 8, "angle": "从副业视角切入",
            "act_now": True, "risk": "低"}), "model": "deepseek-chat"}
        out = judge_topic(build_pack(TOPIC, "快讯档"), {})
        self.assertEqual(out["rating"], "A")
        self.assertEqual(out["model"], "deepseek-chat")

if __name__ == "__main__":
    unittest.main()
