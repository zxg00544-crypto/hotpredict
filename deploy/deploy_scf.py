"""一键部署（设计 8.3）。用法：
  python deploy/deploy_scf.py all       # 打包+桶+角色+函数+触发器+config上传
  python deploy/deploy_scf.py verify    # 手动 Invoke 一轮并打印返回
密钥只从 secrets_tencent.json 读，永不进代码包、永不打印。"""
import base64, io, json, os, subprocess, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
REGION = "ap-guangzhou"
BUCKET = "hotpredict-1409272468"   # 部署迭代：cos-python-sdk-v5 建桶须 <bucket>-<AppId>；旧值 -100046784148 是 UIN 非 AppId，真 AppId=1409272468
FN = "hotpredict-round"
NS = "default"
ROLE = "hotpredict-cos-role"
SCF_ROLE = "SCF_QcsRole"           # SCF 首次 onboarding 的配置角色；本账号需自建
SCF_ROLE_POLICY = "QcloudAccessForScfRole"   # FAQ 明示：承担 COS 触发器配置写入 + 代码包读取
RUNTIME = "Python3.11"          # 迭代点1
MEM, TIMEOUT = 512, 300
DEPS = ["requests", "pyyaml", "cos-python-sdk-v5"]


def _secrets():
    with io.open(os.path.join(ROOT, "secrets_tencent.json"), encoding="utf-8") as f:
        return json.load(f)


def _cred():
    from tencentcloud.common import credential
    s = _secrets()
    return credential.Credential(s["SecretId"], s["SecretKey"])


def package():
    build = os.path.join(ROOT, "deploy", "build")
    if os.path.isdir(build):
        import shutil
        shutil.rmtree(build)
    os.makedirs(build, exist_ok=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "-t", build, *DEPS])
    zpath = os.path.join(ROOT, "deploy", "fn.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(build):
            for fn in files:
                p = os.path.join(root, fn)
                z.write(p, os.path.relpath(p, build))
        z.write(os.path.join(ROOT, "scf_handler.py"), "scf_handler.py")
    print("package OK", zpath, os.path.getsize(zpath), "bytes")


def make_bucket():
    from qcloud_cos import CosConfig, CosS3Client
    s = _secrets()
    c = CosConfig(Region=REGION, SecretId=s["SecretId"], SecretKey=s["SecretKey"])
    cli = CosS3Client(c)
    try:
        cli.create_bucket(Bucket=BUCKET)
        print("bucket created", BUCKET)
    except Exception as e:
        print("bucket exists or noop:", str(e)[:120])


def put_config():
    from qcloud_cos import CosConfig, CosS3Client
    s = _secrets()
    c = CosConfig(Region=REGION, SecretId=s["SecretId"], SecretKey=s["SecretKey"])
    cli = CosS3Client(c)
    cli.put_object_from_local_file(Bucket=BUCKET, Key="config/config.yaml",
                             LocalFilePath=os.path.join(ROOT, "config.yaml"))
    print("config uploaded (private bucket)")


def _find_policy_id(cam, name):
    """ListPolicies 默认按 AddTime 倒序（本地策略靠前）；分页查找已存在策略的 ID。
    返回 int（uint64）——AttachRolePolicy.PolicyId 传字符串会报类型错误。
    终止条件：返回条数 < PageSize（最后一页），或 IsTruncated 显式为 false；
    不设固定页数上限，账号策略增长后仍能查到（超长轮询加安全上限防死循环）。"""
    from tencentcloud.cam.v20190116 import models as cam_models
    page_size = 200
    page = 1
    while True:
        req = cam_models.ListPoliciesRequest()
        req.Scope = "All"
        req.Page = page
        req.Rp = page_size
        resp = cam.ListPolicies(req)
        items = resp.List or []
        for p in items:
            if p.PolicyName == name:
                return int(p.PolicyId)
        if not items:
            break
        truncated = getattr(resp, "IsTruncated", None)
        if truncated is False:
            break
        if len(items) < page_size:      # 已是最后一页
            break
        if page_size * page >= (resp.TotalNum or 0):   # 兜底：按总数判定
            break
        if page >= 100:                 # 安全上限：100*200=20000 条，防异常响应死循环
            break
        page += 1
    raise RuntimeError("policy %s not found after full pagination" % name)


def ensure_scf_role():
    """SCF 首次 onboarding 未完成时，账号内无 SCF_QcsRole，CreateFunction 必报
    roleArn error / ResourceNotFound.Role（与 Role 传名还是 ARN、信任主体是否正确无关）。
    本函数幂等：角色存在则跳过，不存在则用 scf.qcloud.com 信任主体建；随后确保
    QcloudAccessForScfRole 预设策略已挂载（承担 COS 触发器配置写入 + 代码包读取）。"""
    from tencentcloud.cam.v20190116 import cam_client, models as cam_models
    cam = cam_client.CamClient(_cred(), REGION)
    trust = {"version": "2.0", "statement": [
        {"action": ["name/sts:AssumeRole"], "effect": "allow",
         "principal": {"service": ["scf.qcloud.com"]}}]}

    exists = True
    try:
        g = cam_models.GetRoleRequest()
        g.RoleName = SCF_ROLE                      # 迭代点：CAM GetRoleRequest 字段是 RoleName
        cam.GetRole(g)
        print("scf role exists", SCF_ROLE)
    except Exception as e:
        exists = False
        print("scf role missing -> create:", str(e)[:120])
    if not exists:
        r = cam_models.CreateRoleRequest()
        r.RoleName = SCF_ROLE
        r.PolicyDocument = json.dumps(trust)       # SDK 字段是 PolicyDocument（非 AssumeRolePolicyDocument）
        r.Description = "SCF default configuration role."
        try:
            cam.CreateRole(r)
            print("scf role created", SCF_ROLE)
        except Exception as e:
            print("scf role create noop:", str(e)[:120])

    # 挂 QcloudAccessForScfRole：GetPolicy 只接受 PolicyId（按名查会报 MissingParameter PolicyId），
    # 因此用 ListPolicies 分页按名找到 ID；PolicyId 必须传 int。
    policy_id = _find_policy_id(cam, SCF_ROLE_POLICY)
    ap = cam_models.AttachRolePolicyRequest()
    ap.AttachRoleName = SCF_ROLE
    ap.PolicyId = policy_id                        # int（uint64）
    try:
        cam.AttachRolePolicy(ap)                   # 幂等：重复挂载返回 OK
        print("scf role policy attached:", SCF_ROLE_POLICY, policy_id)
    except Exception as e:
        print("scf role policy attach noop:", str(e)[:120])

    lp = cam_models.ListAttachedRolePoliciesRequest()
    lp.RoleName = SCF_ROLE
    lp.Page = 1
    lp.Rp = 200
    attached = [p.PolicyName for p in (cam.ListAttachedRolePolicies(lp).List or [])]
    print("scf role attached policies:", attached)
    return SCF_ROLE


def make_role():
    from tencentcloud.cam.v20190116 import cam_client, models as cam_models
    cam = cam_client.CamClient(_cred(), REGION)
    trust = {"version": "2.0", "statement": [
        {"action": ["name/sts:AssumeRole"], "effect": "allow",
         "principal": {"service": ["scf.qcloud.com"]}}]}
    try:
        r = cam_models.CreateRoleRequest()
        r.RoleName = ROLE
        r.PolicyDocument = json.dumps(trust)     # 迭代点2：SDK 字段是 PolicyDocument（非 AssumeRolePolicyDocument）
        r.Description = "hotpredict round COS access"
        cam.CreateRole(r)
        print("role created", ROLE)
    except Exception as e:
        print("role exists or noop:", str(e)[:120])
    policy = {"version": "2.0", "statement": [
        {"action": ["cos:*"], "effect": "allow",
         "resource": ["qcs::cos:%s:uid/1409272468:%s/*" % (REGION, BUCKET)]}]}
    # 迭代点2：无 PutRolePolicy；改为 CreatePolicy 建策略 → AttachRolePolicy 绑角色（API 更新）
    cp = cam_models.CreatePolicyRequest()
    cp.PolicyName = "hotpredict-cos-policy"
    cp.PolicyDocument = json.dumps(policy)
    cp.Description = "hotpredict COS access, bucket scope only"
    try:
        policy_id = cam.CreatePolicy(cp).PolicyId
        print("policy created", policy_id)
    except Exception as e:
        print("policy exists or noop:", str(e)[:120])
        policy_id = _find_policy_id(cam, "hotpredict-cos-policy")
    ap = cam_models.AttachRolePolicyRequest()
    ap.AttachRoleName = ROLE
    ap.PolicyId = policy_id                  # int（uint64）；字符串会报"取值类型错误"
    cam.AttachRolePolicy(ap)
    print("policy attached (bucket scope only)")
    g = cam_models.GetRoleRequest()
    g.RoleName = ROLE
    arn = cam.GetRole(g).RoleInfo.RoleArn    # 迭代点2：字段名 RoleArn（非 Arn），值形如 qcs::cam::uin/...:roleName/<name>
    print("role arn:", arn)
    return arn


def make_fn(arn):
    from tencentcloud.scf.v20180416 import scf_client, models as scf_models
    scf = scf_client.ScfClient(_cred(), REGION)
    with io.open(os.path.join(ROOT, "deploy", "fn.zip"), "rb") as f:
        code_bytes = f.read()
    # 迭代点3：SDK 结构体字段是 Environment.Variables=[Variable]，非顶层 Env；
    #            Code 是 Code 结构体、ZipFile 须 base64 串（SDK 不会自动编码）
    code = scf_models.Code()
    code.ZipFile = base64.b64encode(code_bytes).decode("ascii")
    env = scf_models.Environment()
    env.Variables = []
    for k, v in (("COS_BUCKET", BUCKET), ("COS_REGION", REGION),
                 ("TZ", "Asia/Shanghai")):
        var = scf_models.Variable()
        var.Key = k
        var.Value = v
        env.Variables.append(var)
    # 幂等重入：函数已存在且健康 → 原地更新代码 + 环境；CreateFailed → 删除重建
    existing = None
    try:
        g = scf_models.GetFunctionRequest()
        g.Namespace = NS
        g.FunctionName = FN
        existing = scf.GetFunction(g)
    except Exception:
        existing = None
    if existing is not None and existing.Status == "CreateFailed":
        print("function in CreateFailed -> delete and recreate:", FN)
        try:
            d = scf_models.DeleteFunctionRequest()
            d.Namespace = NS
            d.FunctionName = FN
            scf.DeleteFunction(d)
        except Exception as e:
            print("delete failed:", str(e)[:160])
        existing = None
    if existing is not None:
        try:
            u = scf_models.UpdateFunctionCodeRequest()
            u.Namespace = NS
            u.FunctionName = FN
            u.Code = code
            scf.UpdateFunctionCode(u)
            c = scf_models.UpdateFunctionConfigurationRequest()
            c.Namespace = NS
            c.FunctionName = FN
            c.Role = ROLE
            c.Environment = env
            c.MemorySize = MEM
            c.Timeout = TIMEOUT
            scf.UpdateFunctionConfiguration(c)
            print("function exists -> code+config updated", FN, "status=", existing.Status)
        except Exception as e:
            print("function update noop:", str(e)[:200])
        return scf
    try:
        r = scf_models.CreateFunctionRequest()
        r.Namespace = NS
        r.FunctionName = FN
        r.Runtime = RUNTIME
        r.Handler = "scf_handler.handler"
        r.MemorySize = MEM
        r.Timeout = TIMEOUT
        r.Role = ROLE                     # 迭代点2：Role 传纯角色名（ARN 变体报 InvalidParameter roleArn error）
        r.Environment = env
        r.Code = code
        # AutoCreateClsTopic 必须传字符串 "FALSE"：本账号 CLS（日志服务）未注册，
        # 默认自动建 CLS 主题会让函数落 CreateFailed（StatusReasons=OperationDenied.AccountNotExists CLS）。
        r.AutoCreateClsTopic = "FALSE"
        # 不设 Cpu：本 SDK 序列化后 API 报"未定义参数 Pu"
        scf.CreateFunction(r)
        print("function created", FN)
    except Exception as e:
        msg = str(e)
        # 仅当错误确属"函数已存在"（并发/上次残留）才当成功；其余真实创建失败原样抛出，
        # 不得盲调 UpdateFunctionCode 把失败伪装成成功（review-4 D2）。
        if "already exists" in msg or "FunctionNameInUse" in msg or "名称已存在" in msg:
            print("function exists or noop:", msg[:200])
        else:
            raise
    return scf


def make_trigger(scf):
    from tencentcloud.scf.v20180416 import models as scf_models
    try:
        t = scf_models.CreateTriggerRequest()
        t.Namespace = NS
        t.FunctionName = FN
        t.TriggerName = "every5min"
        t.Type = "timer"
        # 实测：TriggerDesc 必须是裸 7 段 cron 字符串（JSON 对象形式报 "cron is invalid"）。
        # 7 段 = 秒 分 时 日 月 周 年，"0 */5 * * * * *" = 每 5 分钟第 0 秒。
        t.TriggerDesc = "0 */5 * * * * *"
        scf.CreateTrigger(t)
        print("trigger created every5min")
        return True
    except Exception as e:
        msg = str(e)
        if "已经存在" in msg or "already exist" in msg:
            print("trigger exists or noop:", msg[:160])
            return True
        print("trigger failed:", msg[:240])
        return False


def make_alarm(scf):
    """免费邮件错误告警（指标=错误次数>0）。实测 API 形状：
    CreateAlarmPolicy.Condition 是**对象**（非字符串、非 Conditions）；
    MonitorType=MT_QCE；Namespace 用告警视图名 scf_alias；MetricName 是数字 ID
    （scf_alias 视图下 13007=错误次数）；ProjectId=0。失败则打印控制台手动步骤（设计 8.3 兜底）。"""
    try:
        from tencentcloud.monitor.v20180724 import monitor_client, models as mon_models
        mon = monitor_client.MonitorClient(_cred(), REGION)
        # 幂等：已存在同名策略则跳过
        lp = mon_models.DescribeAlarmPoliciesRequest()
        lp.Module = "monitor"
        lp.PageNumber = 1
        lp.PageSize = 50
        existing = [p for p in (mon.DescribeAlarmPolicies(lp).Policies or [])
                    if p.PolicyName == "hotpredict-round-error"]
        if existing:
            print("alarm policy exists:", existing[0].PolicyId)
            return True
        a = mon_models.CreateAlarmPolicyRequest()
        a.Module = "monitor"
        a.PolicyName = "hotpredict-round-error"
        a.MonitorType = "MT_QCE"
        a.Namespace = "scf_alias"
        a.Enable = 1
        a.ProjectId = 0
        a.Condition = {"IsUnionRule": 0, "Rules": [{
            "MetricName": "13007", "Operator": "gt", "Value": "0",
            "Period": 300, "ContinuePeriod": 1}]}
        r = mon.CreateAlarmPolicy(a)
        print("alarm policy created", r.PolicyId)
        return True
    except Exception as e:
        print("alarm API failed (%s) -> 手动控制台步骤：" % str(e)[:160])
        print("  云监控 → 告警配置 → 新建告警策略 → 维度=云函数 SCF/"
              "hotpredict-round → 指标=调用失败次数>0 → 接收渠道=邮件")
        return False


def verify(scf):
    from tencentcloud.scf.v20180416 import models as scf_models
    r = scf_models.InvokeRequest()
    r.Namespace = NS
    r.FunctionName = FN
    r.InvocationType = "RequestResponse"
    r.ClientContext = json.dumps({})   # InvokeRequest 无 Event 字段；事件体走 ClientContext（裸 JSON 字符串）
    r.LogType = "Tail"
    resp = scf.Invoke(r)
    res = json.loads(resp.to_json_string()).get("Result", {})
    print("invoke RetMsg:", str(res.get("RetMsg"))[:800])


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step == "package":
        package(); return
    if step == "verify":
        from tencentcloud.scf.v20180416 import scf_client
        verify(scf_client.ScfClient(_cred(), REGION)); return
    package()
    make_bucket()
    put_config()
    ensure_scf_role()
    arn = make_role()
    scf = make_fn(arn)
    trig_ok = make_trigger(scf)
    alarm_ok = make_alarm(scf)
    if not (trig_ok and alarm_ok):
        missing = []
        if not trig_ok:
            missing.append("触发器 every5min")
        if not alarm_ok:
            missing.append("告警策略 hotpredict-round-error")
        sys.stderr.write("deploy FAILED: 交付物缺失 -> %s\n" % "、".join(missing))
        sys.exit(1)
    print("deploy done -> 运行: python deploy/deploy_scf.py verify")


if __name__ == "__main__":
    main()
