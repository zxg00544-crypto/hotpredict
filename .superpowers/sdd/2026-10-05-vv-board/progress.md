# SDD ledger — spec: docs/2026-09-28-热点预判工具-design.md 第9节; 执行记录: docs/2026-10-07-大V动向阶段一-实施计划.md

阶段一「大V动向独立板块」执行台账。约定：**全程不 commit**，最终一次性经用户点头 push；无 git diff，任务复核以文件路径+测试输出为包。

Task 1: complete (render/vv_board.py + tests/test_vv_board.py, 20 tests, 全量 205 OK, review SPEC ✅)
Task 1: minor (deferred): push_top 定义于 DEFAULTS 但模块内无读取点，plan_vv_push 不截断，"Top3" 为硬编码标题
Task 1: minor (deferred): 推送文案硬编码 "近24h"/"每人≤3条"，与可配置 window_hours/per_author 脱钩
Task 1: minor (deferred): fetch_rows/plan_vv_push 函数层无默认参数（经 vv_cfg 兜底，功能安全）
Task 1: minor (deferred): 非 weibo url 的 _uid 回退分支无测试覆盖

Task 2: complete (main.py L15 import / L135-149 写板 / L160-169 推送闸 / L172 vv_path; tests/test_main.py +2; 全量 207 OK, review SPEC Approved)
Task 3: complete (workflow L55/L59/L67 + L68-70 三条独立 add; test_commit_step_covers_vv; 全量 208 OK)
Task 3: fix loop (review Important: 多路径 git add 在 大V/ 缺失时原子失败 -> || true 吞错 -> diff-quiet 静默 exit 0 -> 整轮日报/看板/states 丢提交; 修为三条独立 add + bash 实证; 复核复验 Approved)
Task 4: complete e2e (临时 config 剥 notify + notify_fallback=False; 24h 空 -> 占位不推; 168h -> 10 行/4uid/每人<=3; 二跑同 sig 不重推 vv_count 1->1; push 全 skipped, dingtalk/serverchan=0; 208 OK)
Task 4: probe fail recorded (probe_weibo_v HTTP 432 微博风控, cookie present len=429, probe.py 无异常兜底 -> design 9.6 遗留)
Task 4: user decision (question) -> vv 窗口改按 published_at 发布时间过滤 (168h 实测混入 Jun13/Apr15 历史热博霸榜); _published_dt=parsedate_to_datetime + fetch_rows Python 过滤 + 3 用例; 20->23, 全量 211 OK
Task 4: controller independent verify (全量 211 OK; 真库 168h 442 行过期行 0 heat 单调 True; 24h 0 行占位正确)
Task 5: complete (design.md 第9节 spec 唯一事实源 + docs/2026-10-07-大V动向阶段一-实施计划.md + 本台账补记)
pending: 收尾一次性 commit (用户裁决不 commit) -> 源仓 + export 仓同步 -> 用户点头 -> push -> 观察云端 run 大V 入库与钉钉三闸
deferred minors: push_top 无模块内读取点 / 推送文案硬编码近24h / 函数层无默认参 / _uid 回退分支无测试 / probe_weibo_v 无异常兜底 / 板块不看 platforms.weibo_v 开关
