"""推送：钉钉机器人优先（免费无限条），失败回落 Server酱，再回落 Windows Toast；无 key 且关回退则跳过。"""
import base64, hashlib, hmac, subprocess, time, urllib.parse

import requests

MAX_DESP = 2500
MAX_MD = 5000

def build_push_payload(title: str, content: str) -> dict:
    desp = content if len(content) <= MAX_DESP else content[:MAX_DESP] + "\n\n...(截断)"
    return {"title": title[:64], "desp": desp}

def _dingtalk(webhook: str, secret: str, title: str, content: str) -> bool:
    """钉钉自定义机器人 markdown 消息；secret 为加签密钥（可空）。"""
    url = webhook
    if secret:
        ts = str(round(time.time() * 1000))
        sign = base64.b64encode(hmac.new(
            secret.encode("utf-8"), f"{ts}\n{secret}".encode("utf-8"),
            hashlib.sha256).digest()).decode()
        url = f"{webhook}&timestamp={ts}&sign={urllib.parse.quote_plus(sign)}"
    text = content if len(content) <= MAX_MD else content[:MAX_MD] + "\n\n...(截断)"
    msg = {"msgtype": "markdown",
           "markdown": {"title": title[:64], "text": f"### {title[:64]}\n\n{text}"}}
    r = requests.post(url, json=msg, timeout=10)
    j = r.json()
    return j.get("errcode") == 0

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
    n = cfg.get("notify") or {}
    webhook = str(n.get("dingtalk_webhook") or "").strip()
    if webhook:
        try:
            if _dingtalk(webhook, str(n.get("dingtalk_secret") or "").strip(),
                         title, content):
                return "dingtalk"
        except Exception:
            pass
    payload = build_push_payload(title, content)
    key = str(n.get("serverchan_sendkey", "") or "").strip()
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
