"""推送：Server酱 Turbo 优先，失败回落 Windows Toast；无 key 且关回退则跳过。"""
import requests, subprocess

MAX_DESP = 2500

def build_push_payload(title: str, content: str) -> dict:
    desp = content if len(content) <= MAX_DESP else content[:MAX_DESP] + "\n\n...(截断)"
    return {"title": title[:64], "desp": desp}

def _toast(title: str, content: str) -> str:
    t0 = title.replace("'", "")[:60]
    body = content.replace("'", "")[:160]
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] | Out-Null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$n=$t.GetElementsByTagName('text');"
        f"$n.Item(0).AppendChild($t.CreateTextNode('{t0}')) | Out-Null;"
        f"$n.Item(1).AppendChild($t.CreateTextNode('{body}')) | Out-Null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'HotPredict').Show([Windows.UI.Notifications.ToastNotification]::new($t))")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       timeout=20, check=True)
        return "toast"
    except Exception:
        return "skipped"

def notify(title: str, content: str, cfg: dict) -> str:
    payload = build_push_payload(title, content)
    key = str((cfg.get("notify") or {}).get("serverchan_sendkey", "") or "").strip()
    if key:
        try:
            r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                              data=payload, timeout=10)
            j = r.json()
            if r.status_code == 200 and j.get("code") in (0, None):
                return "serverchan"
        except Exception:
            pass
    if not cfg.get("notify_fallback", True):
        return "skipped"
    return _toast(title, content)
