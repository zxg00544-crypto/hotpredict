import datetime, json, os, shutil, tempfile, unittest
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
        with open(DestFilePath, "w", encoding="utf-8") as f:
            f.write(self.objects[Key])

    def put_object_from_local_file(self, Bucket, Key, LocalFilePath):
        with open(LocalFilePath, encoding="utf-8") as f:
            self.objects[Key] = f.read()
        self.put_order.append(Key)

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
                        order.index("data/热点.db"))
        self.assertIn("data/日报/2026-09-28.md", order)
        self.assertEqual(self.client.objects["data/热点.db"], "DB2")


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
        self.assertEqual(self.client.objects["data/热点.db"], "NEWDB")

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


if __name__ == "__main__":
    unittest.main()
