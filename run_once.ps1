# run_once.ps1 —— 计划任务入口：跑一轮，追加日志，按退出码退出
$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot
$log = Join-Path $PSScriptRoot "logs\round.log"
if (-not (Test-Path $log)) { New-Item -ItemType File -Path $log -Force | Out-Null }
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$out = & python main.py 2>&1 | Out-String
Add-Content -LiteralPath $log -Value "[$stamp] $out" -Encoding UTF8
exit $LASTEXITCODE
