"""SCF 云端入口（设计 8.1/8.2）：COS 拉状态 → run_round()（与本地同一条代码）→ 回传 → 软锁防重。
仅云端使用；本机计划任务直接跑 main.py。依赖 qcloud_cos（随函数包分发）。"""
import glob, json, os, time

TMP = "/tmp"
LOCK_TTL = 240          # < 5min 触发周期：轮次开始写的锁，下轮触发时必然过期


def _client():
    from qcloud_cos import CosConfig, CosS3Client
    cfg = CosConfig(
        Region=os.environ.get("COS_REGION", "ap-guangzhou"),
        SecretId=os.environ.get("TENCENTCOS_SECRET_ID", ""),
        SecretKey=os.environ.get("TENCENTCOS_SECRET_KEY", ""),
        Token=os.environ.get("TENCENTCOS_SECURITY_TOKEN", ""))
    return CosS3Client(cfg)


def _bucket():
    b = os.environ.get("COS_BUCKET")
    if not b:
        raise RuntimeError("COS_BUCKET not set")
    return b


def _exists(client, key):
    try:
        client.head_object(Bucket=_bucket(), Key=key)
        return True
    except Exception:
        return False


def sync_down(client, tmp=None):
    """拉 config（必须）+ db（可选，首轮无）+ states 到 tmp；返回 config 路径。"""
    tmp = tmp or TMP
    cfg_local = os.path.join(tmp, "config", "config.yaml")
    os.makedirs(os.path.dirname(cfg_local), exist_ok=True)
    client.download_file(Bucket=_bucket(), Key="config/config.yaml",
                              DestFilePath=cfg_local)      # 缺失抛错 → SCF 报错可见
    db_key = "data/热点.db"
    if _exists(client, db_key):
        client.download_file(Bucket=_bucket(), Key=db_key,
                             DestFilePath=os.path.join(tmp, "热点.db"))
    resp = client.list_objects(Bucket=_bucket(), Prefix="data/states/")
    for obj in resp.get("Contents") or []:
        key = obj["Key"]
        name = key.rsplit("/", 1)[-1]
        if not name:
            continue
        dst = os.path.join(tmp, "states", name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        client.download_file(Bucket=_bucket(), Key=key, DestFilePath=dst)
    return cfg_local


def sync_up(client, tmp=None):
    """先小后大：states → 日报/看板 → db（设计 8.2）。"""
    tmp = tmp or TMP
    for sub in ("states", "日报", "看板"):
        for path in sorted(glob.glob(os.path.join(tmp, sub, "*"))):
            if os.path.isfile(path):
                client.put_object_from_local_file(
                    Bucket=_bucket(),
                    Key="data/%s/%s" % (sub, os.path.basename(path)),
                    LocalFilePath=path)
    dbp = os.path.join(tmp, "热点.db")
    if os.path.exists(dbp):
        client.put_object_from_local_file(Bucket=_bucket(), Key="data/热点.db",
                                    LocalFilePath=dbp)


def acquire_lock(client, ttl=None, tmp=None):
    """COS 软锁：TTL 内已有 → 跳过本轮。GET/PUT 非强互斥，残余竞态为设计 8.4 接受。"""
    ttl = LOCK_TTL if ttl is None else ttl
    tmp = tmp or TMP
    lock_local = os.path.join(tmp, ".lock")
    try:
        client.download_file(Bucket=_bucket(), Key="data/.lock",
                                  DestFilePath=lock_local)
        with open(lock_local, encoding="utf-8") as f:
            taken = float(json.load(f).get("taken_at", 0))
        if time.time() - taken < ttl:
            return False
    except Exception:
        pass
    os.makedirs(tmp, exist_ok=True)
    with open(lock_local, "w", encoding="utf-8") as f:
        json.dump({"taken_at": time.time()}, f)
    client.put_object_from_local_file(Bucket=_bucket(), Key="data/.lock",
                                LocalFilePath=lock_local)
    return True


def handler(event, context):
    if hasattr(time, "tzset"):          # SCF 默认 UTC → 强制东八区（设计 8.2）
        os.environ["TZ"] = "Asia/Shanghai"
        time.tzset()
    client = _client()
    if not acquire_lock(client):
        return {"status": "skipped-locked"}
    cfg_local = sync_down(client)
    import main as app                  # 延迟导入，单测 patch main.run_round 可控
    cfg = app.load_cfg(cfg_local)
    cfg["db_path"] = os.path.join(TMP, "热点.db")
    cfg["out_dir"] = TMP
    cfg["use_llm"] = True
    cfg["dry_run"] = False
    result = app.run_round(cfg)          # 内部已含 prune（Task 1）
    sync_up(client)
    return result
