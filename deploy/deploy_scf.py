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
    """ListPolicies 默认按 AddTime 倒序（本地策略靠前）；分页查找已存在策略的 ID。"""
    from tencentcloud.cam.v20190116 import models as cam_models
    page = 1
    while page <= 6:
        req = cam_models.ListPoliciesRequest()
        req.Scope = "All"
        req.Page = page
        req.Rp = 200
        resp = cam.ListPolicies(req)
        for p in (resp.List or []):
            if p.PolicyName == name:
                return p.PolicyId
        if (page * 200) >= (resp.TotalNum or 0):
            break
        page += 1
    raise RuntimeError("policy %s not found after pagination" % name)


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
    ap.PolicyId = policy_id
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
    try:
        r = scf_models.CreateFunctionRequest()
        r.Namespace = NS
        r.FunctionName = FN
        r.Runtime = RUNTIME
        r.Handler = "scf_handler.handler"
        r.MemorySize = MEM
        r.Timeout = TIMEOUT
        r.Role = arn                      # 迭代点2
        r.Environment = env
        r.Code = code
        scf.CreateFunction(r)
        print("function created", FN)
    except Exception as e:
        print("create failed -> update code:", str(e)[:200])
        u = scf_models.UpdateFunctionCodeRequest()
        u.Namespace = NS
        u.FunctionName = FN
        u.Code = code
        scf.UpdateFunctionCode(u)
        print("function code updated", FN)
    return scf


def make_trigger(scf):
    from tencentcloud.scf.v20180416 import models as scf_models
    try:
        t = scf_models.CreateTriggerRequest()
        t.Namespace = NS
        t.FunctionName = FN
        t.TriggerName = "every5min"
        t.Type = "timer"
        t.TriggerDesc = json.dumps({"cron": "0 */5 * * * *", "enable": True})
        scf.CreateTrigger(t)
        print("trigger created every5min")
    except Exception as e:
        print("trigger exists or noop:", str(e)[:160])


def make_alarm(scf):
    """免费邮件错误告警；monitor API 形状不确定 → 失败即打印控制台手动步骤（设计 8.3 兜底）。"""
    try:
        from tencentcloud.monitor.v20180724 import monitor_client, models as mon_models
        mon = monitor_client.MonitorClient(_cred(), REGION)
        a = mon_models.CreateAlarmPolicyRequest()
        a.Name = "hotpredict-round-error"
        a.Namespace = "QCS_SCF"
        a.MetricName = "InvokeFail"
        a["Conditions"] = [{"MetricName": "InvokeFail",
                            "Rule": [{"ComparisonOperator": "gt",
                                      "Value": "0", "Count": 1}]}]
        mon.CreateAlarmPolicy(a)
        print("alarm policy created")
    except Exception as e:
        print("alarm API failed (%s) -> 手动控制台步骤：" % str(e)[:120])
        print("  云监控 → 告警配置 → 新建告警策略 → 维度=云函数 SCF/"
              "hotpredict-round → 指标=调用失败次数>0 → 接收渠道=邮件")


def verify(scf):
    from tencentcloud.scf.v20180416 import models as scf_models
    r = scf_models.InvokeRequest()
    r.Namespace = NS
    r.FunctionName = FN
    r.InvocationType = "RequestResponse"
    r.Event = "{}"
    resp = scf.Invoke(r)
    print("invoke ret:", str(resp.RetMsg)[:600])


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
    arn = make_role()
    scf = make_fn(arn)
    make_trigger(scf)
    make_alarm(scf)
    print("deploy done -> 运行: python deploy/deploy_scf.py verify")


if __name__ == "__main__":
    main()
