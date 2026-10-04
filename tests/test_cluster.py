# tests/test_cluster.py —— 事件级聚类（2026-10-03，保守合并不漏推）
import json
import unittest
from unittest.mock import patch

from llm_judge.cluster import (
    assign_event_ids, local_cluster, _share_any, _similar, _parse_groups)

GPT = ["openai将于未来数日推出gpt61sol超快版",
       "gpt61sol",
       "gpt61solnearastraintelligenceforafifthoftheprice",
       "如何评价openai发布的gpt61sol"]
OPENAI_6 = ["openai将于未来数日推出gpt61sol超快版",
            "openai推出dots全天候自主智能体面向全部付费套餐开放",
            "openai计划在2027年前完成总额3000亿美元的融资",
            "如何评价openai发布的gpt61sol",
            "openaidevday2026大更新浏览器操作系统模型",
            "chatgptproapi额度减半"]
MORTGAGE = ["居民房贷贴息政策10月1日起实施年化贴息1最长补贴5年限定房价150万以内",
            "房贷贴息1个百分点", "购房贴息最高规模100万", "李大霄谈房贷贴息节前落地"]


def C(titles, scores=None):
    return [{"key": t, "title": t,
             "score": (scores or {}).get(t, 50)} for t in titles]


def n_events(mapping):
    return len(set(mapping.values()))


class TestLocalCluster(unittest.TestCase):
    def test_merges_near_identical_titles(self):
        m = local_cluster(C(GPT))
        self.assertEqual(n_events(m), 1)

    def test_does_not_merge_distinct_events_of_same_company(self):
        """同公司不同事件必须分开，否则等于漏推。"""
        self.assertEqual(n_events(local_cluster(C(OPENAI_6))), 6)

    def test_covers_every_key(self):
        m = local_cluster(C(OPENAI_6))
        self.assertEqual(set(m.keys()), set(OPENAI_6))

    def test_similar_thresholds(self):
        self.assertTrue(_similar("美国30年期国债收益率升至5.59",
                                 "美国30年期国债收益率触及5.5977"))
        self.assertFalse(_similar("房贷贴息1个百分点", "李大霄谈房贷贴息节前落地"))

    def test_share_any_is_loose_but_requires_common_token(self):
        self.assertTrue(_share_any("房贷贴息1个百分点", "李大霄谈房贷贴息节前落地"))
        self.assertFalse(_share_any("房贷贴息1个百分点", "GLM-5.3 cyber capabilities"))


class TestParseGroups(unittest.TestCase):
    def _map(self, payload, titles, anchors=None):
        return _parse_groups(json.dumps(payload), C(titles), anchors or {})

    def test_high_confidence_with_shared_token_merges(self):
        """房贷贴息 4 条字面不像（local 抓不住），LLM 判 high 才合。"""
        out = self._map({"groups": [{"members": ["c0", "c1", "c2", "c3"],
                                     "confidence": "high"}]}, MORTGAGE)
        self.assertIsNotNone(out)
        self.assertEqual(n_events(out), 1)

    def test_low_confidence_never_merges(self):
        """保守闸1：low 一律拆开。"""
        out = self._map({"groups": [{"members": ["c0", "c1", "c2", "c3"],
                                     "confidence": "low"}]}, MORTGAGE)
        self.assertEqual(n_events(out), 4)

    def test_group_without_shared_token_is_split(self):
        """保守闸2：组内任一成对无共享实词 → 整组不合并（宁可重复、不漏推）。"""
        out = self._map({"groups": [{"members": ["c0", "c1", "c2", "c3"],
                                     "confidence": "high"}]},
                        ["房贷贴息1个百分点",
                         "GLM-5.3 and the spread of advanced cyber capabilities",
                         "DraftKings Q3 earnings beat",
                         "李大霄谈房贷贴息节前落地"])
        self.assertEqual(n_events(out), 4)   # 四条各自独立，一条也不并

    def test_anchor_match_with_shared_token_uses_existing_event_id(self):
        out = self._map({"groups": [{"members": ["c0", "e0"],
                                     "confidence": "high"}]}, MORTGAGE,
                        {"e:old": "居民房贷贴息政策10月1日起实施"})
        self.assertEqual(out[MORTGAGE[0]], "e:old")

    def test_anchor_match_without_shared_token_rejected(self):
        """保守闸3：与锚点无共享实词不许归入，否则把没推过的当成推过的 = 漏推。"""
        out = self._map({"groups": [{"members": ["c0", "e0"],
                                     "confidence": "high"}]}, MORTGAGE,
                        {"e:old": "GPT-6.1 Sol超快版发布"})
        self.assertNotEqual(out[MORTGAGE[0]], "e:old")

    def test_garbage_or_empty_returns_none(self):
        self.assertIsNone(_parse_groups("not json", C(GPT), {}))
        self.assertIsNone(_parse_groups("", C(GPT), {}))
        self.assertIsNone(_parse_groups('{"groups": []}', C(GPT), {}))


class TestAssignEventIds(unittest.TestCase):
    def test_disabled_uses_local(self):
        out = assign_event_ids(C(MORTGAGE), {}, {}, enabled=False)
        self.assertEqual(n_events(out), 4)

    def test_empty_candidates(self):
        self.assertEqual(assign_event_ids([], {}, {}, enabled=True), {})

    @patch("llm_judge.cluster.llm_client_call")
    def test_llm_failure_falls_back_to_local(self, m):
        m.return_value = None
        out = assign_event_ids(C(GPT), {}, {}, enabled=True)
        self.assertEqual(n_events(out), 1)
        self.assertEqual(set(out.keys()), set(GPT))

    @patch("llm_judge.cluster.llm_client_call")
    def test_llm_success_merges_what_local_cannot(self, m):
        m.return_value = {"content": json.dumps(
            {"groups": [{"members": ["c0", "c1", "c2", "c3"],
                         "confidence": "high"}]}), "model": "m"}
        out = assign_event_ids(C(MORTGAGE), {}, {}, enabled=True)
        self.assertEqual(n_events(out), 1)

    @patch("llm_judge.cluster.llm_client_call")
    def test_result_always_covers_all_candidates(self, m):
        """无论 LLM 回什么，每个 key 都必须有 event_id（缺 = 推送时无法去重）。"""
        for content in ("totally broken", '{"groups": []}',
                        '{"groups": [{"members": ["c0"], "confidence": "low"}]}'):
            m.return_value = {"content": content, "model": "m"}
            out = assign_event_ids(C(OPENAI_6), {}, {}, enabled=True)
            self.assertEqual(set(out.keys()), set(OPENAI_6))

    @patch("llm_judge.cluster.llm_client_call")
    def test_request_is_single_call_with_anchors(self, m):
        m.return_value = {"content": '{"groups": []}', "model": "m"}
        assign_event_ids(C(GPT), {"e:old": "白宫人工智能协议"}, {}, enabled=True)
        self.assertEqual(m.call_count, 1)
        payload = m.call_args[0][0][1]["content"]
        self.assertIn("e0", payload)
        self.assertIn("白宫人工智能协议", payload)


if __name__ == "__main__":
    unittest.main()
