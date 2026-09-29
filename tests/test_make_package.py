# -*- coding: utf-8 -*-
"""tools/make_package.py 的单元测试（双版本打包器）。"""
import json
import os
import sys
import tempfile
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_package as mp  # noqa: E402


class TestSanitizeYaml(unittest.TestCase):
    def test_secret_key_replaced(self):
        text = ("platforms:\n"
                "  zhihu: true\n"
                "notify:\n"
                "  dingtalk_webhook: https://oapi.dingtalk.com/robot/send?access_token=FAKETOKEN9\n"
                "weights:\n"
                "  growth: 1.5\n")
        out = mp.sanitize_yaml(text)
        self.assertNotIn("FAKETOKEN9", out)
        self.assertIn("<填写:钉钉webhook>", out)
        self.assertIn("  zhihu: true", out)
        self.assertIn("  growth: 1.5", out)

    def test_indent_and_structure_preserved(self):
        text = ("llm:\n"
                "  api_key: FAKEKEY123456\n"
                "  provider: deepseek\n")
        out = mp.sanitize_yaml(text)
        self.assertIn("\n  api_key: <填写:LLM api_key>\n", out)
        self.assertIn("  provider: deepseek", out)
        self.assertNotIn("FAKEKEY123456", out)
        self.assertEqual(yaml.safe_load(out)["llm"]["provider"], "deepseek")

    def test_multiline_scalar_continuation_dropped(self):
        """多行 YAML 标量：键行替换后，缩进续行必须一并丢弃。"""
        text = ("weibo_cookie: SUB=_2FAKEfirst\n"
                "  SUBP=0033FAKEsecond\n"
                "  ALF=1234567890; SSOLoginState=1234567890; WBPSESS=FAKEthird==\n"
                "llm:\n"
                "  provider: deepseek\n")
        out = mp.sanitize_yaml(text)
        for frag in ("SUB=_2FAKEfirst", "SUBP=0033FAKEsecond", "ALF=1234567890",
                     "SSOLoginState=1234567890", "WBPSESS=FAKEthird=="):
            self.assertNotIn(frag, out, "片段泄漏: %s" % frag)
        self.assertIn("weibo_cookie: <填写:微博cookie>", out)
        self.assertIn("  provider: deepseek", out)
        self.assertEqual(yaml.safe_load(out)["llm"]["provider"], "deepseek")


class TestSanitizeSecretsJson(unittest.TestCase):
    def test_json_replaced_and_valid(self):
        text = json.dumps({"SecretId": "AKIDFAKE000111222", "SecretKey": "FAKESECRET000999"})
        out = mp.sanitize_secrets_json(text)
        self.assertNotIn("AKIDFAKE000111222", out)
        self.assertNotIn("FAKESECRET000999", out)
        data = json.loads(out)
        self.assertTrue(data["SecretId"].startswith("<填写"))
        self.assertTrue(data["SecretKey"].startswith("<填写"))


class TestFileList(unittest.TestCase):
    def test_local_includes_data_and_schedule(self):
        rels = list(mp._iter_files("local"))
        self.assertIn("热点.db", rels)
        self.assertIn("run_once.ps1", rels)
        self.assertIn("README-本地版.md", rels)
        self.assertTrue(any(r.startswith("日报/") for r in rels))
        self.assertTrue(any(r.startswith("看板/") for r in rels))
        self.assertTrue(any(r.startswith("states/") for r in rels))

    def test_cloud_includes_deploy_not_data(self):
        rels = list(mp._iter_files("cloud"))
        self.assertIn("deploy/deploy_scf.py", rels)
        self.assertIn("README-云端版.md", rels)
        self.assertNotIn("热点.db", rels)
        self.assertNotIn("install_schedule.ps1", rels)
        self.assertNotIn("run_once.ps1", rels)
        self.assertFalse(any(r.startswith("日报/") for r in rels))
        self.assertFalse(any(r.startswith("states/") for r in rels))

    def test_both_exclude_real_secrets_and_junk(self):
        for version in ("local", "cloud"):
            rels = list(mp._iter_files(version))
            self.assertNotIn("config.yaml", rels, version)
            self.assertNotIn("secrets_tencent.json", rels, version)
            self.assertNotIn("README-云端版.md" if version == "local" else "README-本地版.md", rels, version)
            self.assertFalse(any(r.endswith(".pyc") for r in rels), version)
            self.assertFalse(any("/build/" in "/" + r for r in rels), version)
            self.assertFalse(any(r.endswith("fn.zip") for r in rels), version)
            self.assertFalse(any("__pycache__" in r for r in rels), version)
            self.assertIn("requirements.txt", rels, version)


class TestSecretFragments(unittest.TestCase):
    def test_cookie_split_into_pairs(self):
        cookie = "SUB=0123456789abcdef; SUBP=0033WrSXpairs; ALF=1234567890; WBPSESS=TOKENVALUEHERE=="
        frags = mp._secret_fragments([cookie])
        self.assertIn("SUBP=0033WrSXpairs", frags)
        self.assertIn("WBPSESS=TOKENVALUEHERE==", frags)
        self.assertIn("ALF=1234567890", frags)
        self.assertNotIn("1793169190", frags)  # 纯数字子串不单独成片段，防误报

    def test_short_values_ignored(self):
        frags = mp._secret_fragments(["short", "1234567890ab"])
        self.assertEqual(frags, ["1234567890ab"])


class TestSecretScan(unittest.TestCase):
    def test_hit_detected_and_clean_passes(self):
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "a.txt")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("nothing sensitive here")
            self.assertEqual(mp.secret_scan(td, real_values=["SUPERSECRETVALUE123456"]), [])
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("x SUPERSECRETVALUE123456 y")
            hits = mp.secret_scan(td, real_values=["SUPERSECRETVALUE123456"])
            self.assertEqual(len(hits), 1)
            self.assertIn("a.txt", hits[0])
            self.assertNotIn("SUPERSECRETVALUE123456", hits[0])

    def test_single_cookie_pair_detected(self):
        """文件只含真实 cookie 的单个子对（如 SUBP=...）→ 必须命中。"""
        cookie = "SUB=0123456789abcdef; SUBP=0033WrSXqPxfM725Wspair; ALF=1234567890"
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "cfg.txt")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("weibo_cookie: SUBP=0033WrSXqPxfM725Wspair\n")
            hits = mp.secret_scan(td, real_values=[cookie])
            self.assertEqual(len(hits), 1)
            self.assertIn("cfg.txt", hits[0])

    @unittest.skipUnless(os.path.exists(os.path.join(ROOT, "config.yaml")) and
                         os.path.exists(os.path.join(ROOT, "secrets_tencent.json")),
                         "真实配置文件不存在")
    def test_real_sources_not_leaked_into_templates(self):
        real_api = yaml.safe_load(open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))["llm"]["api_key"]
        real_sid = json.load(open(os.path.join(ROOT, "secrets_tencent.json"), encoding="utf-8"))["SecretId"]
        with tempfile.TemporaryDirectory() as td:
            mp.make_templates(td)
            tpl = (open(os.path.join(td, "config.example.yaml"), encoding="utf-8").read() +
                   open(os.path.join(td, "secrets_tencent.example.json"), encoding="utf-8").read())
        self.assertNotIn(real_api, tpl, "real llm.api_key leaked into template")
        self.assertNotIn(real_sid, tpl, "real SecretId leaked into template")

    @unittest.skipUnless(os.path.exists(os.path.join(ROOT, "config.yaml")),
                         "真实配置文件不存在")
    def test_real_multiline_cookie_no_fragment_in_template(self):
        """真实多行 weibo_cookie 经脱敏后，任一 token 片段都不得出现在模板里。"""
        real_cookie = yaml.safe_load(open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))["weibo_cookie"]
        frags = mp._secret_fragments([real_cookie])
        self.assertTrue(frags, "真实 cookie 应能拆出可扫描片段")
        with tempfile.TemporaryDirectory() as td:
            mp.make_templates(td)
            tpl = open(os.path.join(td, "config.example.yaml"), encoding="utf-8").read()
        for frag in frags:
            self.assertNotIn(frag, tpl, "cookie 片段泄漏进模板")


if __name__ == "__main__":
    unittest.main()
