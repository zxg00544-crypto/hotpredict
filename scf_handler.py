"""SCF 云端入口（设计 8.1/8.2）：COS 拉状态 → run_round()（与本地同一条代码）→ 回传 → 软锁防重。
仅云端使用；本机计划任务直接跑 main.py。依赖 qcloud_cos（随函数包分发）。"""
import glob, gzip, json, os, shutil, time

TMP = "/tmp"
LOCK_TTL = 240          # < 5min 触发周期：轮次开始写的锁，下轮触发时必然过期


def _client():
    """凭证优先级（设计 8.1「代码包零密钥；绑角色免密钥」）：
    1) SCF 平台为已绑运行角色的函数自动注入的临时凭证
       环境变量 TENCENTCLOUD_SECRETID / TENCENTCLOUD_SECRETKEY / TENCENTCLOUD_SESSIONTOKEN
       （仅运行时存在，不出现在 GetFunction 的 Env 配置里）；
    2) 回落长期密钥 TENCENTCOS_SECRET_ID / TENCENTCOS_SECRET_KEY。
    两者均不齐时按原语义以空凭证构造，交由 CosConfig 报错（守卫不削弱）。"""
    from qcloud_cos import CosConfig, CosS3Client
    sid = os.environ.get("TENCENTCLOUD_SECRETID", "")
    skey = os.environ.get("TENCENTCLOUD_SECRETKEY", "")
    stoken = os.environ.get("TENCENTCLOUD_SESSIONTOKEN", "")
    if sid and skey and stoken:                  # 平台临时凭证（优先）
        cfg = CosConfig(Region=os.environ.get("COS_REGION", "ap-guangzhou"),
                        SecretId=sid, SecretKey=skey, Token=stoken)
    else:                                        # 回落长期密钥
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
    """拉 config（必须）+ db.gz（可选，首轮无；无 gz 回落明文 db）+ states 到 tmp；返回 config 路径。"""
    tmp = tmp or TMP
    cfg_local = os.path.join(tmp, "config", "config.yaml")
    os.makedirs(os.path.dirname(cfg_local), exist_ok=True)
    client.download_file(Bucket=_bucket(), Key="config/config.yaml",
                              DestFilePath=cfg_local)      # 缺失抛错 → SCF 报错可见
    db_local = os.path.join(tmp, "热点.db")
    if _exists(client, "data/热点.db.gz"):
        t0 = time.time()
        gz = db_local + ".gz"
        client.download_file(Bucket=_bucket(), Key="data/热点.db.gz",
                             DestFilePath=gz)
        with gzip.open(gz, "rb") as f_in, open(db_local, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(gz)
        print("[gta] down db.gz %.1fs" % (time.time() - t0), flush=True)
    elif _exists(client, "data/热点.db"):
        t0 = time.time()
        client.download_file(Bucket=_bucket(), Key="data/热点.db",
                             DestFilePath=db_local)
        print("[gta] down db %.1fs" % (time.time() - t0), flush=True)
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
    """先小后大：states → 日报/看板 → db.gz（设计 8.2；db gzip 压缩回传，逐文件耗时打点）。"""
    tmp = tmp or TMP
    for sub in ("states", "日报", "看板"):
        for path in sorted(glob.glob(os.path.join(tmp, sub, "*"))):
            if os.path.isfile(path):
                key = "data/%s/%s" % (sub, os.path.basename(path))
                t0 = time.time()
                client.put_object_from_local_file(
                    Bucket=_bucket(), Key=key, LocalFilePath=path)
                print("[gta] up %s %.1fs" % (key, time.time() - t0), flush=True)
    dbp = os.path.join(tmp, "热点.db")
    if os.path.exists(dbp):
        gz = dbp + ".gz"
        t0 = time.time()
        with open(dbp, "rb") as f_in, gzip.open(gz, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        size = os.path.getsize(gz)
        t1 = time.time()
        client.put_object_from_local_file(Bucket=_bucket(),
                                          Key="data/热点.db.gz", LocalFilePath=gz)
        print("[gta] up data/热点.db.gz %dB gzip %.1fs upload %.1fs"
              % (size, t1 - t0, time.time() - t1), flush=True)
        os.remove(gz)
        try:                      # 旧明文 db 对象作废，防回落读到陈旧副本
            client.delete_object(Bucket=_bucket(), Key="data/热点.db")
        except Exception:
            pass


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
    print("[gta] client ok", flush=True)
    if not acquire_lock(client):
        print("[gta] skipped-locked", flush=True)
        return {"status": "skipped-locked"}
    print("[gta] sync_down start", flush=True)
    cfg_local = sync_down(client)
    print("[gta] sync_down done", flush=True)
    import main as app                  # 延迟导入，单测 patch main.run_round 可控
    cfg = app.load_cfg(cfg_local)
    cfg["db_path"] = os.path.join(TMP, "热点.db")
    cfg["out_dir"] = TMP
    cfg["use_llm"] = True
    cfg["dry_run"] = False
    print("[gta] run_round start", flush=True)
    result = app.run_round(cfg)          # 内部已含 prune（Task 1）
    print("[gta] run_round done", flush=True)
    sync_up(client)
    print("[gta] sync_up done", flush=True)
    return result
