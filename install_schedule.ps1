# install_schedule.ps1 —— 注册 Windows 计划任务，每 5 分钟跑一轮（管理员执行一次）
$here = $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\run_once.ps1`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "HotPredict-Round" -Action $action -Trigger $trigger `
    -Settings $settings -Force -Description "热点预判调度流水线"
