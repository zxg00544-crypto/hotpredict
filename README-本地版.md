# 热点预判 · 本地版换机恢复指南

本包：本地版（含历史数据：热点.db、日报/、看板/、states/）。恢复约 10 分钟。

## 恢复步骤
1. 解压本 zip，得到 `热点预判\`
2. 安装 Python 3.11（64 位），然后：`pip install -r requirements.txt`
3. 填密钥（密钥不随包走，换机必做）：
   - 复制 `config.example.yaml` 为 `config.yaml`，把 6 个 `<填写:...>` 占位符换成真实值（微博cookie / LLM api_key / Server酱sendkey / 钉钉webhook / 钉钉secret / 钉钉keyword）
   - 复制 `secrets_tencent.example.json` 为 `secrets_tencent.json`，填 SecretId / SecretKey
4. 验证代码完好：`python -X utf8 -m unittest discover -s tests` → 预期全部 OK
5. 手动跑一轮验证推送：`python main.py` → 钉钉收到日报才算成功
6. 注册每 5 分钟计划任务（管理员 PowerShell 执行一次）：`.\install_schedule.ps1`
   - 验证：`Get-ScheduledTask HotPredict-Round` → State: Ready
7. 完成。历史数据随包直接续用；`logs\round.log` 首次运行自动重建

## 注意
- `llm.config_path` 指向旧机器的 opencode.json 路径，新机器路径不同则同步修改（仅影响本地取 key，云端只认 `llm.api_key`）
- 卸载计划任务：`Unregister-ScheduledTask -TaskName HotPredict-Round`
- 密钥永不进 git / 网盘 / 聊天
