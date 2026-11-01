"""微博热搜（免 Cookie：PC 端 ajax/side/hotSearch）。

2026-11-01: m.weibo.cn getIndex 接口要求登录 Cookie，config 里的旧 Cookie
已失效（带 Cookie 也返回 ok=-100，无 Cookie 同样被拒）。改走
weibo.com/ajax/side/hotSearch，实测免 Cookie 可拿 50+ 条完整热搜
（word/num/rank），本源不再依赖 Cookie。
"""
import time, requests
from collectors.base import Signal, topic_key
from probe import UA

def parse_realtime(items: list, fetched_at: str) -> list[Signal]:
    out = []
    for i, g in enumerate(items, 1):
        title = g.get("word", "")
        if not title:
            continue
        num = float(g.get("num", 0) or 0)
        out.append(Signal(topic_key=topic_key(title), source="weibo", title=title,
                          url="https://s.weibo.com/weibo?q=" + title,
                          heat=num or max(0, 200 - i * 5),
                          rank=i, rank_delta=0,
                          engagement=num,
                          author_weight=0.7, fetched_at=fetched_at, raw=dict(g)))
    return out

def fetch(cfg: dict) -> list[Signal]:
    h = dict(UA); h["Referer"] = "https://weibo.com/"
    r = requests.get("https://weibo.com/ajax/side/hotSearch", headers=h, timeout=10)
    r.raise_for_status()
    j = r.json()
    items = (j.get("data") or {}).get("realtime") or []
    if not items:
        raise RuntimeError(f"weibo: realtime empty (code={j.get('code')})")
    return parse_realtime(items, time.strftime("%Y-%m-%dT%H:%M:%S"))
