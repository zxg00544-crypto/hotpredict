"""推送：钉钉机器人优先（免费无限条），失败回落 Server酱，再回落 Windows Toast；无 key 且关回退则跳过。"""
import base64, hashlib, hmac, re, subprocess, time, urllib.parse

import requests

MAX_DESP = 2500
MAX_MD = 5000
RETRY_DELAY_S = 2  # 仅钉钉网络异常重试一次（errcode 拒收不重试，见 test_dingtalk_fail）

# 日志脱敏：钉钉 access_token/sign、Server酱 sendkey 绝不进日志（零-A3）
_PAT_SECRET = (
    (re.compile(r"access_token=[^&\s]+"), "access_token=***"),
    (re.compile(r"[?&]sign=[^&\s]+"), "&sign=***"),
    (re.compile(r"sctapi\.ftqq\.com/[^?\s]+"), "sctapi.ftqq.com/***"),
)


def _scrub(s) -> str:
    out = str(s)
    for pat, rep in _PAT_SECRET:
        out = pat.sub(rep, out)
    return out[:200]


def build_push_payload(title: str, content: str) -> dict:
    desp = content if len(content) <= MAX_DESP else content[:MAX_DESP] + "\n\n...(截断)"
    return {"title": title[:64], "desp": desp}

def _dingtalk(webhook: str, secret: str, title: str, content: str,
              keyword: str = "") -> bool:
    """钉钉自定义机器人 markdown 消息；secret 为加签密钥（可空）。
    keyword：安全设置勾了"自定义关键词"时，消息必须含该词，否则钉钉 40401 拒收。"""
    url = webhook
    if secret:
        ts = str(round(time.time() * 1000))
        sign = base64.b64encode(hmac.new(
            secret.encode("utf-8"), f"{ts}\n{secret}".encode("utf-8"),
            hashlib.sha256).digest()).decode()
        url = f"{webhook}&timestamp={ts}&sign={urllib.parse.quote_plus(sign)}"
    text = content if len(content) <= MAX_MD else content[:MAX_MD] + "\n\n...(截断)"
    if keyword and keyword not in title and keyword not in text:
        text = f"【{keyword}】\n\n{text}"
    msg = {"msgtype": "markdown",
           "markdown": {"title": title[:64], "text": f"### {title[:64]}\n\n{text}"}}
    r = requests.post(url, json=msg, timeout=10)
    try:
        j = r.json()
    except Exception as e:
        print(f"[push] dingtalk http={r.status_code} non-json: "
              f"{type(e).__name__}", flush=True)
        return False
    ok = j.get("errcode") == 0
    if not ok:
        print(f"[push] dingtalk rejected errcode={j.get('errcode')} "
              f"errmsg={_scrub(j.get('errmsg'))}", flush=True)
    return ok

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

def _try_dingtalk(webhook: str, secret: str, title: str, content: str,
                  keyword: str) -> bool | None:
    """尝试一次钉钉。成功 True；钉钉明确拒收 False；网络/解析异常 None（调用方可重试）。"""
    try:
        return _dingtalk(webhook, secret, title, content, keyword)
    except Exception as e:
        print(f"[push] dingtalk exception: {type(e).__name__}: "
              f"{_scrub(e)}", flush=True)
        return None

def notify(title: str, content: str, cfg: dict) -> str:
    n = cfg.get("notify") or {}
    webhook = str(n.get("dingtalk_webhook") or "").strip()
    if webhook:
        secret = str(n.get("dingtalk_secret") or "").strip()
        keyword = str(n.get("dingtalk_keyword") or "").strip()
        res = _try_dingtalk(webhook, secret, title, content, keyword)
        if res is None:
            # 仅瞬时网络异常重试一次；errcode 拒收（res False）不重试
            time.sleep(RETRY_DELAY_S)
            res = _try_dingtalk(webhook, secret, title, content, keyword)
        if res:
            return "dingtalk"
    payload = build_push_payload(title, content)
    key = str(n.get("serverchan_sendkey", "") or "").strip()
    if key:
        try:
            r = requests.post(f"https://sctapi.ftqq.com/{key}.send",
                              data=payload, timeout=10)
            j = r.json()
            if r.status_code == 200 and j.get("code") in (0, None):
                return "serverchan"
            print(f"[push] serverchan rejected http={r.status_code} "
                  f"code={j.get('code')} msg={_scrub(j.get('message') or j.get('msg'))}",
                  flush=True)
        except Exception as e:
            print(f"[push] serverchan exception: {type(e).__name__}: "
                  f"{_scrub(e)}", flush=True)
    if not cfg.get("notify_fallback", True):
        return "skipped"
    return _toast(title, content)
