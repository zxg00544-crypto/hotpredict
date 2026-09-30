' run_hidden.vbs —— 无窗口启动 run_once.ps1，退出码透传给任务计划
' 全 ASCII：路径从脚本自身位置动态取，避开编码问题
Dim fso, sh, d, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("Wscript.Shell")
d = fso.GetParentFolderName(WScript.ScriptFullName)
rc = sh.Run("powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & d & "\run_once.ps1""", 0, True)
WScript.Quit rc
