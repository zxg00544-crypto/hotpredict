"""GitHub Actions 云入口（替代 scf_handler 的腾讯云 COS 版，2026-10-04 脱离腾讯云）。

存储分工（全部 GitHub 侧，零成本）：
  config  ← Actions secret CONFIG_YAML（= 本地 config.yaml 全文，gh secret set 更新）
  热点.db ← actions/cache 恢复到仓库根（workflow 以 hpdb-<run_id> 键保存，restore-keys hpdb- 取最近一份）；
            cache 全失时回落仓库种子 data/热点.db.gz，再无则全新建库（当日 trend 降级为 0，不阻断）
  states/日报/看板 → 写仓库根（.gitignore 忽略 states/ 亦可，workflow 用 git add -f 提交）
锁：workflow concurrency: hotpredict-round（串行），无需 COS 软锁。
本机计划任务不走本文件，仍直跑 main.py。"""
import gzip, json, os, shutil, time

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "热点.db")
SEED_GZ = os.path.join(ROOT, "data", "热点.db.gz")
CFG_PATH = os.path.join(ROOT, "config.yaml")


def set_tz():
    """runner 是 UTC → 强制东八区（与 scf_handler 同语义：日期分界/晚报 hour 都按北京时间）。"""
    if hasattr(time, "tzset"):
        os.environ["TZ"] = "Asia/Shanghai"
        time.tzset()


def materialize_config(env=None):
    """CONFIG_YAML → 仓库根 config.yaml（已 gitignore，永不入 git）。返回写入字节数。"""
    env = os.environ if env is None else env
    raw = env.get("CONFIG_YAML", "")
    if not str(raw).strip():
        raise RuntimeError("CONFIG_YAML 未设置（Actions secret = 本地 config.yaml 全文）")
    with open(CFG_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(raw if raw.endswith("\n") else raw + "\n")
    return os.path.getsize(CFG_PATH)


def restore_db():
    """cache 恢复的 db → 仓库种子 gz → 全新建库。返回来源标签 cache/seed/fresh。"""
    if os.path.exists(DB_PATH):
        return "cache"
    if os.path.exists(SEED_GZ):
        t0 = time.time()
        with gzip.open(SEED_GZ, "rb") as f_in, open(DB_PATH, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        print("[gh] db seed from data/热点.db.gz %.1fs" % (time.time() - t0), flush=True)
        return "seed"
    print("[gh] db fresh (no cache, no seed) — trend 当日为 0，不阻断", flush=True)
    return "fresh"


def run(env=None):
    set_tz()
    size = materialize_config(env)
    print("[gh] config %dB" % size, flush=True)
    origin = restore_db()
    import main as app
    cfg = app.load_cfg(CFG_PATH)
    cfg["db_path"] = DB_PATH
    cfg["out_dir"] = ROOT              # states/日报/看板 落仓库根，由 workflow 提交
    cfg["use_llm"] = True
    cfg["dry_run"] = False
    result = app.run_round(cfg)
    result["db_origin"] = origin
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, default=str))
