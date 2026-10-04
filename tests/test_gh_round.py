"""gh_round（GitHub Actions 云入口）单测 + workflow 无腾讯云回归断言。"""
import gzip, os, shutil, tempfile, unittest
from unittest.mock import patch

import gh_round

CONFIG_YAML = "llm:\n  model: agnes-2.5-flash\n"
WORKFLOW = os.path.join(gh_round.ROOT, ".github", "workflows", "hotpredict-round.yml")


class TestMaterializeConfig(unittest.TestCase):
    def test_writes_config_and_reports_bytes(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = os.path.join(tmp, "config.yaml")
        with patch.object(gh_round, "CFG_PATH", cfg):
            n = gh_round.materialize_config({"CONFIG_YAML": CONFIG_YAML})
        self.assertEqual(n, os.path.getsize(cfg))
        with open(cfg, encoding="utf-8") as f:
            self.assertEqual(f.read(), CONFIG_YAML)

    def test_appends_trailing_newline(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = os.path.join(tmp, "config.yaml")
        with patch.object(gh_round, "CFG_PATH", cfg):
            gh_round.materialize_config({"CONFIG_YAML": "a: 1"})
        with open(cfg, encoding="utf-8") as f:
            self.assertTrue(f.read().endswith("\n"))

    def test_missing_secret_raises(self):
        with patch.object(gh_round, "CFG_PATH",
                          os.path.join(tempfile.mkdtemp(), "config.yaml")):
            with self.assertRaises(RuntimeError):
                gh_round.materialize_config({})

    def test_blank_secret_raises(self):
        with patch.object(gh_round, "CFG_PATH",
                          os.path.join(tempfile.mkdtemp(), "config.yaml")):
            with self.assertRaises(RuntimeError):
                gh_round.materialize_config({"CONFIG_YAML": "   \n"})


class TestRestoreDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.db = os.path.join(self.tmp, "热点.db")
        self.seed = os.path.join(self.tmp, "data", "热点.db.gz")

    def test_cache_when_db_present(self):
        with open(self.db, "wb") as f:
            f.write(b"CACHEDB")
        with patch.object(gh_round, "DB_PATH", self.db), \
             patch.object(gh_round, "SEED_GZ", self.seed):
            self.assertEqual(gh_round.restore_db(), "cache")
        with open(self.db, "rb") as f:
            self.assertEqual(f.read(), b"CACHEDB")   # cache 不被覆盖

    def test_seed_gz_decompressed_when_no_cache(self):
        os.makedirs(os.path.dirname(self.seed), exist_ok=True)
        with gzip.open(self.seed, "wb") as f:
            f.write(b"SEEDED")
        with patch.object(gh_round, "DB_PATH", self.db), \
             patch.object(gh_round, "SEED_GZ", self.seed):
            self.assertEqual(gh_round.restore_db(), "seed")
        with open(self.db, "rb") as f:
            self.assertEqual(f.read(), b"SEEDED")

    def test_fresh_when_no_cache_and_no_seed(self):
        with patch.object(gh_round, "DB_PATH", self.db), \
             patch.object(gh_round, "SEED_GZ", self.seed):
            self.assertEqual(gh_round.restore_db(), "fresh")
        self.assertFalse(os.path.exists(self.db))


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.patches = [
            patch.object(gh_round, "ROOT", self.tmp),
            patch.object(gh_round, "CFG_PATH", os.path.join(self.tmp, "config.yaml")),
            patch.object(gh_round, "DB_PATH", os.path.join(self.tmp, "热点.db")),
            patch.object(gh_round, "SEED_GZ",
                         os.path.join(self.tmp, "data", "热点.db.gz")),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_run_wires_cfg_and_returns_result(self):
        captured = {}

        def fake_round(cfg):
            captured.update(cfg)
            return {"status": "ok", "fast": 2}

        with patch("main.run_round", side_effect=fake_round):
            out = gh_round.run({"CONFIG_YAML": CONFIG_YAML})

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["db_origin"], "fresh")
        self.assertEqual(captured["db_path"],
                         os.path.join(self.tmp, "热点.db"))
        self.assertEqual(captured["out_dir"], self.tmp)
        self.assertTrue(captured["use_llm"])
        self.assertFalse(captured["dry_run"])
        with open(gh_round.CFG_PATH, encoding="utf-8") as f:   # config 确实落地仓库根
            self.assertEqual(f.read(), CONFIG_YAML)

    def test_run_fails_fast_without_secret(self):
        with patch("main.run_round") as m:
            with self.assertRaises(RuntimeError):
                gh_round.run({})
        m.assert_not_called()


class TestWorkflowContract(unittest.TestCase):
    """workflow 回归合同：GitHub 存储、零腾讯云依赖。"""

    def setUp(self):
        with open(WORKFLOW, encoding="utf-8") as f:
            self.text = f.read()

    def test_no_tencent_cos_refs(self):
        for bad in ("TENCENTCOS", "COS_BUCKET", "COS_REGION", "scf_handler"):
            self.assertNotIn(bad, self.text, "workflow 仍引用腾讯云: %s" % bad)

    def test_uses_github_storage(self):
        for good in ("CONFIG_YAML", "actions/cache", "contents: write",
                     "hpdb-", "gh_round"):
            self.assertIn(good, self.text, "workflow 缺少: %s" % good)

    def test_commit_step_present(self):
        self.assertIn("git add", self.text)
        self.assertIn("states", self.text)


class TestTz(unittest.TestCase):
    def test_set_tz_is_safe_everywhere(self):
        gh_round.set_tz()                       # Windows 无 tzset，也必须不抛
        if hasattr(__import__("time"), "tzset"):
            self.assertEqual(os.environ.get("TZ"), "Asia/Shanghai")


if __name__ == "__main__":
    unittest.main()
