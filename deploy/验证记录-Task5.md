# Task 5 验证记录 — 云端验证阶梯（含前置凭证修复）

执行日期：2026-09-29（东八）
工作目录：`D:\opencode\热点预判`
函数：`hotpredict-round`（default，ap-guangzhou，Python3.11，512MB/300s，Role=hotpredict-cos-role）
桶：`hotpredict-1409272468`
密钥：全程从 `secrets_tencent.json` 读入变量，未打印任何字面值。

---

## 合同项 0（前置修复）：scf_handler 凭证来源

**缺陷**：`verify` 返回 `SecretId and SecretKey is Required!`——`_client()` 只读 `TENCENTCOS_SECRET_ID/KEY`，未读 SCF 平台为绑定角色函数注入的临时凭证。

**修复**：`scf_handler.py:9-32` 重写 `_client()`：
- 优先读平台临时凭证 `TENCENTCLOUD_SECRETID` / `TENCENTCLOUD_SECRETKEY` / `TENCENTCLOUD_SESSIONTOKEN`（三者齐全才用），`CosConfig` 增传 `Token=<TENCENTCLOUD_SESSIONTOKEN>`；
- 不齐则回落原 `TENCENTCOS_SECRET_ID/KEY` 逻辑（空值报错守卫不削弱）；
- 已核查全文件无其他直接读长期密钥的处（`grep SECRET` 仅 `_client()` 内）。

**测试**：`tests/test_scf_handler.py` 新增 `TestClientCredentials`（3 用例，含 SecurityToken 传递断言）。用例数 106 → 109（只增不减）。

证据：
```
Ran 109 tests in 0.455s
OK
```
变更测试（独立探针，验证新路径真实生效）：
```
new impl SecretId=tmp-sid Token=tmp-token (expect tmp-sid / tmp-token)
MUTATION CHECK PASS: platform creds + token used; old impl would have used long-sid
```

**部署更新代码**（幂等，`deploy/deploy_scf.py update` 路径）+ 追加修复：
```
package OK ...\deploy\fn.zip 4831720 bytes
function update noop: ...当前函数处于Updating状态...   # 见下方追加修复说明
```

### 追加修复（合同项 0 之外的连带阻断，属计划-现实偏差，已按设计 8.1「与本地同一条代码」修）

修复凭证后 invoke 暴露第二个阻断：`ModuleNotFoundError: No module named 'main'` → `package()` 只打包 `scf_handler.py`，未打包应用模块。修复 `deploy/deploy_scf.py:package()`：打包根目录全部 `.py`（main/db/probe/probe_llm/scf_handler 等）+ 本地包 `collectors/scoring/llm_judge/render`，排除 deploy/tests/docs/states/logs/__pycache__，密钥与 config 永不入包。

打包核验：
```
main.py -> True / db.py -> True / scf_handler.py -> True / probe.py -> True / probe_llm.py -> True
secrets_tencent.json in zip: False / config.yaml in zip: False / deploy_scf.py in zip: False / tests in zip: False
```
> 说明：该追加修复超出 brief 合同项 0 字面范围，但属"修复凭证后必经的下一阻断"，且严格落在设计 8.1 契约内；已在报告向控制器显式声明，请控制器裁定是否接受。

---

## Step 1：手动 Invoke 一轮

命令：`python -X utf8 deploy/deploy_scf.py verify`（含清除陈旧软锁后 Invoke）
```
RetMsg: {"status": "ok", "date": "2026-09-29", "report_path": "/tmp/日报/2026-09-29.md",
         "board_path": "/tmp/看板/2026-09-29.html", "fast": 10, "trend": 0,
         "signals": 257, "failed_sources": ["collectors.hn: ReadTimeout"], "degraded": false, "push": []}
elapsed_s: 121.3
```
**判定：PASS**。（`collected` 字段在本版本命名为 `signals:257`，语义等价；单源 `collectors.hn` ReadTimeout 已优雅降级 `degraded:false`。）

## Step 2：COS 产物核对

```
['data/.lock', 'data/states/push_state.json', 'data/日报/2026-09-29.md',
 'data/热点.db', 'data/看板/2026-09-29.html']
```
**判定：PASS**（含预期的 `data/热点.db`、`data/states/push_state.json`、`data/日报/2026-09-29.md`，另有看板）。

## Step 3：钉钉收报核对

`push_state.json` 记录 6 条推送（`pushed` 列表，`breaking_count: 6`），证明推送流程已执行；但**实际到达钉钉群**需人工看群确认（关键词"热点预判"，无重复连发）。
**判定：【需人工核对】**（执行者无法访问钉钉群）。

## Step 4：触发器双轮观察（≥11 分钟）

基线 12:11:54：`push_state.json`=1530B，`pushed`=6，`热点.db`=319488B。
等待 11 分钟（12:12→12:23）后：
```
data/states/push_state.json | Size=3032   （1530→3032，时间推进）
data/热点.db | Size=921600                （319488→921600）
data/日报/2026-09-29.md | Size=4176
data/看板/2026-09-29.html | Size=6177
lock: {"taken_at": 1790655600.72}  -> 2026-09-29 12:20:00
pushed count: 6 / breaking: 6 / duplicate pushes: NONE / a_seen size: 3
```
锁时间 `12:20:00` 精确落在 5 分钟触发边界（`0 */5 * * * * *`）→ 定时触发器自主触发。`pushed` 保持 6 且无重复 → 软锁+去重生效。
**判定：PASS**。

## Step 5：日志巡检

`GetFunctionLogs` 返回 `total: 0` —— 本账号 CLS（日志服务）未注册，函数未落 CLS（与 Task 4 `AutoCreateClsTopic="FALSE"` 同源）。
改用 Invoke 响应内 `LogType="Tail"` 取得运行日志：
```
START RequestId: 64e99171-... 
Event RequestId: 64e99171-...
Response RequestId: 64e99171-... RetMsg: {"status": "ok", ...}
END RequestId: 64e99171-...
Report RequestId: 64e99171-... Duration: 40994ms Memory: 512MB MemUsage: 33.22MB
has_traceback: False / Log length: 595
```
日报标题日期核验：
```
title line: # 热点预判日报 · 2026-09-29
local(tz) date: 2026-09-29
title matches local: True
```
**判定：PASS**（无 traceback、单轮 Duration 40s、东八当天日期）；CLS 检索方式受账号未注册限制，控制台日志检索步骤见下，标【需人工核对（可选）】。

## Step 6：账单与告警核对

SCF 错误告警复核（SDK DescribeAlarmPolicies）：
```
total policies: 1
ALARM: policy-w2no0xz5 hotpredict-round-error ns= scf_alias type= MT_QCE enable= 1
```
**判定：告警 PASS**；**费用中心账单/1元预算告警【需人工核对】**（控制台一次性配置项）。

## Step 7：判定

| Step | 判定 |
|------|------|
| 0 凭证修复 | PASS |
| 1 手动 Invoke | PASS |
| 2 COS 产物 | PASS |
| 3 钉钉收报 | 需人工核对 |
| 4 触发器双轮 | PASS |
| 5 日志巡检 | PASS（CLS 检索受限，可选人工） |
| 6 告警/账单 | 告警 PASS；账单需人工核对 |

全 PASS（除人工项）→ **可进 Task 6**（切流前置仍需人工确认钉钉送达与账单 0 元）。

---

## 控制台人工核对步骤（供人工执行）

1. **钉钉群**：确认本时段收到"热点预判"推送/日报，无重复连发。
2. **费用中心 → 账单**：确认 SCF/COS 费用 ≈ 0 元（免费额度覆盖）。
3. **费用中心 → 预算告警**：确认已配 1 元预算邮件告警（一次性手动）。
4. （可选）**云函数 → hotpredict-round → 日志检索**：若后续注册 CLS，可在此查看每 5 分钟执行记录。
