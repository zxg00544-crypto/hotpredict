# 热点预判 · 云端版换机恢复指南

本包：云端版（不含数据；数据存于 COS 桶 hotpredict-1409272468）。恢复约 5 分钟。

## 既有账号恢复（推荐）
1. 解压本 zip，得到 `热点预判\`
2. 安装 Python 3.11（64 位），然后：`pip install -r requirements.txt`
3. 填密钥（同本地版：两个 example 文件复制改名后填真实值）
4. `python -X utf8 -m unittest discover -s tests` → 预期全部 OK
5. 对接既有云资源（幂等，安全重跑）：`python -X utf8 deploy/deploy_scf.py verify`
   - 预期：`invoke ret:` 返回 `status:ok` 的整轮 JSON
   - 代码没改就到此为止；改了代码用 `python -X utf8 deploy/deploy_scf.py all` 重部（幂等）

## 既有云资源清单（账号 100046784148 / 广州 / AppId 1409272468）
- 函数 `hotpredict-round`（Python3.11，运行角色 hotpredict-cos-role，每 5 分钟触发器 every5min）
- 告警 `policy-w2no0xz5`（错误次数 > 0 通知）
- COS 桶 `hotpredict-1409272468`（config/config.yaml、data/热点.db、states/、日报/、看板/）
- 角色：`SCF_QcsRole`（系统 onboarding 角色）+ `hotpredict-cos-role`（自定义，桶范围策略）
- 手动验收与故障排查：`deploy/验证记录-Task5.md`

## 全新账号 / 全新云重建
`python -X utf8 deploy/deploy_scf.py all`
（自动：打包 → 建桶 → 传 config → ensure SCF_QcsRole → 建角色+策略 → 函数 → 触发器 → 告警；缺任一交付物 exit 1）

## 回滚预案
- 云端停推：控制台停用触发器 `every5min`
- 换回本机推送：本地版机器上 `Enable-ScheduledTask -TaskName HotPredict-Round`
