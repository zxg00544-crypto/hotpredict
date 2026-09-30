import datetime, gzip, json, os, shutil, tempfile, unittest
from unittest.mock import patch
os.environ.setdefault("COS_BUCKET", "hotpredict-100046784148")
import scf_handler


class FakeClient:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.put_order = []

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise RuntimeError("404")
        return {}

    def download_file(self, Bucket, Key, DestFilePath):
        if Key not in self.objects:
            raise RuntimeError("404")
        os.makedirs(os.path.dirname(DestFilePath), exist_ok=True)
        data = self.objects[Key]
        if isinstance(data, bytes):
            with open(DestFilePath, "wb") as f:
                f.write(data)
        else:
            with open(DestFilePath, "w", encoding="utf-8") as f:
                f.write(data)

    def put_object_from_local_file(self, Bucket, Key, LocalFilePath):
        with open(LocalFilePath, "rb") as f:
            self.objects[Key] = f.read()
        self.put_order.append(Key)

    def upload_file(self, Bucket, Key, LocalFilePath, PartSize=1, MAXThread=5,
                    EnableMD5=False, **kw):
        with open(LocalFilePath, "rb") as f:
            self.objects[Key] = f.read()
        self.put_order.append(Key)
        self.upload_args = (PartSize, MAXThread)

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def list_objects(self, Bucket, Prefix):
        return {"Contents": [{"Key": k} for k in self.objects if k.startswith(Prefix)]}


CONFIG_YAML = "llm:\n  model: deepseek-chat\n"

class TestSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.client = FakeClient({
            "config/config.yaml": CONFIG_YAML,
            "data/热点.db": "DBBYTES",
            "data/states/push_state.json": '{"pushed": []}',
        })

    def test_sync_down_pulls_config_db_states(self):
        cfg_path = scf_handler.sync_down(self.client, tmp=self.tmp)
        self.assertTrue(os.path.exists(cfg_path))
        with open(cfg_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), CONFIG_YAML)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "热点.db")))
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp, "states", "push_state.json")))

    def test_sync_down_missing_config_raises(self):
        with self.assertRaises(Exception):
            scf_handler.sync_down(FakeClient({}), tmp=self.tmp)

    def test_sync_down_prefers_gz_over_plain(self):
        self.client.objects["data/热点.db.gz"] = gzip.compress(b"GZDB")
        scf_handler.sync_down(self.client, tmp=self.tmp)
        with open(os.path.join(self.tmp, "热点.db"), "rb") as f:
            self.assertEqual(f.read(), b"GZDB")

    def test_sync_up_states_before_db(self):
        os.makedirs(os.path.join(self.tmp, "states"), exist_ok=True)
        os.makedirs(os.path.join(self.tmp, "日报"), exist_ok=True)
        with open(os.path.join(self.tmp, "states", "s.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(self.tmp, "日报", "2026-09-28.md"), "w") as f:
            f.write("# daily")
        with open(os.path.join(self.tmp, "热点.db"), "w") as f:
            f.write("DB2")
        scf_handler.sync_up(self.client, tmp=self.tmp)
        order = self.client.put_order
        self.assertLess(order.index("data/states/s.json"),
                        order.index("data/热点.db.gz"))
        self.assertIn("data/日报/2026-09-28.md", order)
        self.assertEqual(gzip.decompress(self.client.objects["data/热点.db.gz"]),
                         b"DB2")
        self.assertNotIn("data/热点.db", self.client.objects)

    def test_sync_up_db_upload_failure_swallowed(self):
        os.makedirs(os.path.join(self.tmp, "states"), exist_ok=True)
        with open(os.path.join(self.tmp, "states", "s.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(self.tmp, "热点.db"), "w") as f:
            f.write("DB2")

        def boom(**kw):
            raise RuntimeError("UserNetworkTooSlow")

        self.client.upload_file = boom
        scf_handler.sync_up(self.client, tmp=self.tmp)   # 不抛 = 吞掉通过
        self.assertIn("data/states/s.json", self.client.objects)
        self.assertNotIn("data/热点.db.gz", self.client.objects)


class TestLock(unittest.TestCase):
    def test_no_lock_takes_it(self):
        c = FakeClient()
        self.assertTrue(scf_handler.acquire_lock(c, tmp=tempfile.mkdtemp()))

    def test_fresh_lock_blocks(self):
        c = FakeClient({"data/.lock": json.dumps(
            {"taken_at": __import__("time").time()})})
        self.assertFalse(scf_handler.acquire_lock(c, tmp=tempfile.mkdtemp()))

    def test_stale_lock_taken_over(self):
        c = FakeClient({"data/.lock": json.dumps(
            {"taken_at": __import__("time").time() - 300})})
        self.assertTrue(scf_handler.acquire_lock(c, tmp=tempfile.mkdtemp()))


class TestHandler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.client = FakeClient({"config/config.yaml": CONFIG_YAML})

    def test_handler_wires_cfg_and_returns_result(self):
        captured = {}

        def fake_round(cfg):
            captured.update(cfg)
            with open(os.path.join(self.tmp, "热点.db"), "w") as f:
                f.write("NEWDB")
            return {"status": "ok", "collected": 3}

        with patch.object(scf_handler, "TMP", self.tmp), \
             patch.object(scf_handler, "_client", return_value=self.client), \
             patch("main.run_round", side_effect=fake_round):
            out = scf_handler.handler({}, None)

        self.assertEqual(out["status"], "ok")
        self.assertEqual(captured["db_path"],
                         os.path.join(self.tmp, "热点.db"))
        self.assertEqual(captured["out_dir"], self.tmp)
        self.assertTrue(captured["use_llm"])
        self.assertEqual(
            gzip.decompress(self.client.objects["data/热点.db.gz"]), b"NEWDB")

    def test_handler_skips_when_lock_fresh(self):
        client = FakeClient({
            "config/config.yaml": CONFIG_YAML,
            "data/.lock": json.dumps({"taken_at": __import__("time").time()})})
        with patch.object(scf_handler, "TMP", self.tmp), \
             patch.object(scf_handler, "_client", return_value=client), \
             patch("main.run_round") as m:
            out = scf_handler.handler({}, None)
        self.assertEqual(out["status"], "skipped-locked")
        m.assert_not_called()


class TestClientCredentials(unittest.TestCase):
    """合同项0：凭证优先级——平台临时凭证（含 SESSIONTOKEN）优先，长期密钥回落。"""

    def _capture_cosconfig(self, env):
        captured = {}

        class FakeCosConfig:
            def __init__(self, **kw):
                captured.update(kw)

        class FakeCli:
            def __init__(self, cfg):
                captured["cli_cfg"] = cfg

        fake_mod = type("M", (), {"CosConfig": FakeCosConfig,
                                  "CosS3Client": FakeCli})
        with patch.dict("sys.modules", {"qcloud_cos": fake_mod}):
            with patch.dict(os.environ, env, clear=False):
                for k in ("TENCENTCLOUD_SECRETID", "TENCENTCLOUD_SECRETKEY",
                          "TENCENTCLOUD_SESSIONTOKEN", "TENCENTCOS_SECRET_ID",
                          "TENCENTCOS_SECRET_KEY", "TENCENTCOS_SECURITY_TOKEN"):
                    if k not in env:
                        os.environ.pop(k, None)
                scf_handler._client()
        return captured

    def test_platform_temp_credential_takes_priority_with_token(self):
        c = self._capture_cosconfig({
            "TENCENTCLOUD_SECRETID": "tmp-sid",
            "TENCENTCLOUD_SECRETKEY": "tmp-key",
            "TENCENTCLOUD_SESSIONTOKEN": "tmp-token",
            "TENCENTCOS_SECRET_ID": "long-sid",
            "TENCENTCOS_SECRET_KEY": "long-key"})
        self.assertEqual(c["SecretId"], "tmp-sid")
        self.assertEqual(c["SecretKey"], "tmp-key")
        self.assertEqual(c["Token"], "tmp-token")   # SecurityToken 传递断言
        self.assertEqual(c["Timeout"], 300)         # 慢网给SDK的HTTP超时上限

    def test_falls_back_to_long_term_when_temp_incomplete(self):
        c = self._capture_cosconfig({
            "TENCENTCLOUD_SECRETID": "tmp-sid",
            "TENCENTCLOUD_SECRETKEY": "tmp-key",
            "TENCENTCOS_SECRET_ID": "long-sid",
            "TENCENTCOS_SECRET_KEY": "long-key",
            "TENCENTCOS_SECURITY_TOKEN": ""})
        self.assertEqual(c["SecretId"], "long-sid")
        self.assertEqual(c["SecretKey"], "long-key")

    def test_empty_when_no_credentials_keeps_guard(self):
        c = self._capture_cosconfig({})
        self.assertEqual(c["SecretId"], "")
        self.assertEqual(c["SecretKey"], "")


if __name__ == "__main__":
    unittest.main()
